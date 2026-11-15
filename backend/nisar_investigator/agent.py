"""The investigator: turns a plain-language question into visible analysis steps and a grounded report.

The language model plans and explains. It never sees imagery and never produces numbers: every figure in
the report must come from a tool result, and `submit_report` is rejected when a figure cannot be traced.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import anthropic
import requests

from . import catalog, config, context, plain, provenance
from .schemas import (
    ChangeRequest,
    Investigation,
    InvestigateRequest,
    InvestigationStep,
    MotionRequest,
    Report,
    TimeSeriesRequest,
)

MAX_TURNS = 14
MAX_REPORT_ATTEMPTS = 4
MAX_ANSWER_WORDS = 60

SYSTEM_PROMPT = """\
You are the analysis planner inside Aletheia, a research tool that answers questions about how \
Earth's surface is changing, using data from NISAR, the NASA-ISRO L-band radar satellite. The people asking \
are researchers who are usually not radar specialists: hydrologists, ecologists, geologists, planners, \
students. They have selected an area on a map and asked a question. They need an answer they can cite, so \
what matters most is that every statement is traceable and that the limits of the evidence are plain.

How the tool works. You cannot see imagery or raw data. Deterministic analysis code does the measuring, and \
you reach it through tools that all operate on the user's selected area:
- check_coverage: what NISAR has here (dates, tracks, calibration tier, gaps). Call it first, because every \
later choice depends on which dates actually exist.
- run_change: backscatter change between two dates. Both dates must come from the same stack (same track \
and frame), otherwise the pixel grids and viewing geometry differ.
- run_timeseries: mean backscatter for the area on every available date, per track and polarization.
- run_motion: ground displacement along the radar line of sight from one of NASA's ready-made 12-day \
interferogram pairs, where they exist.
- get_context: independent evidence that is not radar (earthquake catalogue, river gauges).
- submit_report: the final answer. Call it exactly once, when you have what you need.

Choosing an analysis. Pick the smallest set of tool calls that answers the question. "What changed between \
A and B" is run_change. "How did this behave over the season" or "when did it happen" is run_timeseries, \
often followed by run_change across the largest step. "Did the ground move" is run_motion. Prefer validated \
or provisional dates over beta ones, which are uncalibrated. When the question names dates, use exactly those \
dates if a stack has them (pick the stack that has both), and say so if you had to use the nearest ones instead. If the question needs something these tools \
cannot do (multi-year trends, slow subsidence, land-cover classification, forecasts, anything outside the \
dates NISAR has), say so in the report and offer the closest thing the tools can do. An honest "not \
supported yet" is a good outcome; a guess is not.

Grounding rules, and why they exist. Researchers will repeat your numbers, so:
- Every figure with a unit must appear in a tool result, exactly as given there. If you want to express a \
difference or a ratio, quote the two source values and let the reader see the comparison. submit_report \
checks this and will send the report back if a figure cannot be traced.
- Areas and displacements come as ranges (low, central, high). Report the range, because a single number \
would overstate what the method can resolve.
- Each observed statement cites the id of the result it comes from.
- Brightness is not land cover. A tool result tells you that backscatter rose or fell, where, and by how \
much. Why it changed is a hypothesis, and belongs under possible explanations with a way to check it.
- If context evidence is available (a gauge, an earthquake), use it to support or weaken a hypothesis, and \
say which.
- Carry the caveats that matter into the report: calibration tier, noise floor, short record, line of sight.

Radar background you can rely on when forming hypotheses:
- Backscatter (gamma0, in dB) rises with surface roughness, structure and moisture. HH and VV are co-pol; \
HV and VH are cross-pol and respond mostly to volume scattering in vegetation.
- Calm open water is very dark in both channels and often sits at the instrument noise floor. Wind roughens \
water and brightens co-pol by a few dB, with no change on the ground.
- Flooded vegetation is bright in HH (double bounce between water and trunks); L-band penetrates canopy, so \
NISAR sees flooding under forest that shorter wavelengths miss.
- Water that drains to expose wet sediment or sandbars brightens in HH. New standing water over bare ground \
darkens it.
- Vegetation loss (harvest, fire, logging) lowers HV. Regrowth raises it slowly.
- Wetter soil is brighter in co-pol; drying lowers it. Freezing lowers backscatter sharply. Wet snow lowers \
it; dry snow is nearly transparent at L-band.
- Smooth dry ground can be almost as dark as water, so the two are hard to separate in dry terrain.
- Built-up areas are very bright and stable. Steep terrain suffers layover and shadow.
- A single 12-day interferogram carries about 1 to 2 cm of atmospheric noise and, at L-band, ionospheric \
noise. Displacement is along the line of sight and relative within the area.
- NISAR's calibrated record is short (months), so seasonal behaviour cannot be separated from trend.

Writing. Plain English, short sentences, units on every number, no jargon without a few words of \
explanation. The answer is one or two sentences that a busy reader could quote. State confidence as low, \
medium or high with the main reason.
"""

_NULLABLE_STRING = {"type": ["string", "null"]}
_NULLABLE_INT = {"type": ["integer", "null"]}


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "check_coverage",
        "List what NISAR has for the selected area: backscatter (GCOV) dates per stack with calibration tier, "
        "interferogram (GUNW) pairs, soil moisture (SME2) dates, and gaps. Call this before any analysis.",
        {},
    ),
    _tool(
        "run_change",
        "Measure backscatter change between two acquisition dates from the same stack. Returns changed area "
        "as low/central/high ranges for increases and decreases, per-polarization statistics, the "
        "noise-floor fraction and caveats.",
        {
            "date_before": {"type": "string", "description": "Earlier date, YYYY-MM-DD, taken from check_coverage."},
            "date_after": {"type": "string", "description": "Later date, YYYY-MM-DD, from the same stack."},
            "track": {**_NULLABLE_INT, "description": "Track number of the stack, or null to let the tool pick."},
        },
    ),
    _tool(
        "run_timeseries",
        "Mean backscatter of the selected area on every available date, per track and polarization, with "
        "spread and calibration tier, plus the largest step between consecutive dates.",
        {
            "start": {**_NULLABLE_STRING, "description": "Optional first date YYYY-MM-DD, or null for all dates."},
            "end": {**_NULLABLE_STRING, "description": "Optional last date YYYY-MM-DD, or null for all dates."},
        },
    ),
    _tool(
        "run_motion",
        "Ground displacement along the radar line of sight from one NASA 12-day interferogram pair, with the "
        "noise level and whether any signal exceeds it. Only where GUNW pairs exist.",
        {
            "reference_date": {**_NULLABLE_STRING, "description": "Reference (earlier) date of the pair, or null for the latest pair."},
            "track": {**_NULLABLE_INT, "description": "Track number, or null to let the tool pick."},
        },
    ),
    _tool(
        "get_context",
        "Independent, non-radar evidence for the area and period: 'earthquakes' (USGS catalogue, global) or "
        "'river_gauges' (water level at the nearest gauges; Canada and the United States only).",
        {
            "kind": {"type": "string", "enum": ["earthquakes", "river_gauges"]},
            "start": {"type": "string", "description": "First date, YYYY-MM-DD."},
            "end": {"type": "string", "description": "Last date, YYYY-MM-DD."},
        },
    ),
    _tool(
        "submit_report",
        "Deliver the final report. Every figure with a unit must appear in a cited tool result.",
        {
            "answer": {"type": "string", "description": "One or two sentences answering the question."},
            "observed": {
                "type": "array",
                "description": "What the data shows. One measured fact per item.",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "result_id": {"type": "string", "description": "Id of the tool result the statement comes from."},
                    },
                    "required": ["statement", "result_id"],
                    "additionalProperties": False,
                },
            },
            "possible_explanations": {
                "type": "array",
                "description": "Hypotheses about the cause, each with what would confirm or rule it out.",
                "items": {
                    "type": "object",
                    "properties": {"hypothesis": {"type": "string"}, "how_to_check": {"type": "string"}},
                    "required": ["hypothesis", "how_to_check"],
                    "additionalProperties": False,
                },
            },
            "unknown": {"type": "array", "items": {"type": "string"}, "description": "What this data cannot tell."},
            "confidence_level": {"type": "string", "enum": ["low", "medium", "high"]},
            "confidence_reason": {"type": "string"},
        },
    ),
]

_STEP_TITLES = {
    "check_coverage": "Checking what NISAR has for this area",
    "run_change": "Measuring change between two dates",
    "run_timeseries": "Building a time series from every available date",
    "run_motion": "Reading ground motion from NASA's interferogram",
    "get_context": "Looking up independent evidence",
    "submit_report": "Writing the report",
}

# ------------------------------------------------------------------ digests


def _coverage_digest(cov) -> dict:
    """What the model needs from a Coverage object: per-stack dates with tiers, without footprints or URLs.

    Stacks whose footprint covers under half of the area are left out (they only clip its edge and have
    no usable samples), and the rest are listed best first: the most acquisitions on top.
    """
    from .workflows import common

    bbox = tuple(cov.query["bbox"]) if "bbox" in cov.query else None
    stacks: dict[tuple, dict] = {}
    skipped = 0
    for product, granules in cov.products.items():
        for g in granules:
            key = (product, g.track, g.direction, g.frame)
            if key not in stacks:
                share = common.footprint_fraction(g.footprint, bbox) if bbox and g.footprint else 1.0
                stacks[key] = {"product": product, "track": g.track, "direction": g.direction, "frame": g.frame,
                               "polarizations": g.polarizations, "covers_area": share >= 0.5, "acquisitions": []}
            entry = stacks[key]
            if g.date:
                entry["acquisitions"].append({"date": g.date, "tier": g.tier})
            else:
                entry["acquisitions"].append(
                    {"reference_date": g.reference_date, "secondary_date": g.secondary_date, "tier": g.tier}
                )
    usable = [s for s in stacks.values() if s.pop("covers_area")]
    skipped = len(stacks) - len(usable)
    usable.sort(key=lambda s: (s["product"] != "GCOV", -len(s["acquisitions"])))
    notes = list(cov.notes)
    if skipped:
        notes.append(f"{skipped} other stacks only clip the edge of the area and are not listed.")
    return {"id": "coverage", "stacks": usable, "notes": notes}


def _result_digest(result: dict) -> dict:
    """A WorkflowResult without layers, downloads or the receipt: the measured facts only."""
    keep = ("id", "workflow", "status", "summary", "stats", "uncertainty", "caveats")
    out = {k: result.get(k) for k in keep}
    out["series"] = [
        {
            "label": s.get("label"), "unit": s.get("unit"), "track": s.get("track"),
            "direction": s.get("direction"), "polarization": s.get("polarization"),
            "points": [{k: p.get(k) for k in ("date", "value", "spread", "tier")} for p in s.get("points", [])],
        }
        for s in result.get("series", [])
    ]
    out["granules"] = [
        {k: g.get(k) for k in ("date", "reference_date", "secondary_date", "tier", "track", "direction") if g.get(k) is not None}
        for g in result.get("receipt", {}).get("granules", [])
    ]
    return out


# ------------------------------------------------ dates named in a question

_MONTHS = {m: i + 1 for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"))}
_MONTH = "|".join(_MONTHS)
_DATE_PATTERNS = (
    re.compile(r"\b(?P<y>20\d\d)-(?P<m>\d\d)-(?P<d>\d\d)\b"),
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{_MONTH})(?:\s+(?P<y>20\d\d))?\b", re.IGNORECASE),
    re.compile(rf"\b(?P<mon>{_MONTH})\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>20\d\d))?\b", re.IGNORECASE),
)


def question_dates(question: str) -> list[str]:
    """Calendar dates a question names, as YYYY-MM-DD, in order. A date without a year takes the next year
    mentioned after it ("19 June and 17 October 2026"), or the last year mentioned anywhere."""
    years = [(m.start(), m.group()) for m in re.finditer(r"\b20\d\d\b", question)]
    found: list[tuple[int, str]] = []
    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(question):
            groups = m.groupdict()
            month = int(groups["m"]) if groups.get("m") else _MONTHS[groups["mon"].lower()]
            year = groups.get("y") or next((y for pos, y in years if pos > m.start()), years[-1][1] if years else None)
            day = int(groups["d"])
            if year is None or not (1 <= day <= 31 and 1 <= month <= 12):
                continue
            found.append((m.start(), f"{year}-{month:02d}-{day:02d}"))
    ordered = []
    for _, iso in sorted(found):
        if iso not in ordered:
            ordered.append(iso)
    return ordered


# ------------------------------------------------- traceability of figures

_FIGURE = re.compile(
    r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*(km2|km²|square kilometres|square kilometers|dB|cm|mm|m|percent|%)(?![\w²])"
)


def _numbers(obj) -> list[float]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _numbers(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in _numbers(v)]
    if isinstance(obj, str):  # figures quoted inside headlines and notes count as computed too
        return [float(m) for m in re.findall(r"-?\d+(?:\.\d+)?", obj)]
    return []


def _traceable(text_value: str, unit: str, pool: list[float]) -> bool:
    decimals = len(text_value.split(".")[1]) if "." in text_value else 0
    x = abs(float(text_value))
    for v in pool:
        candidates = [abs(v)]
        if unit in ("%", "percent"):
            candidates.append(abs(v) * 100)
        if any(abs(round(c, decimals) - x) < 0.5 * 10**-decimals + 1e-9 for c in candidates):
            return True
    return False


_UNIT = r"(km2|km\u00b2|square kilometres|square kilometers|dB|cm|mm|m|percent|%)(?![\w\u00b2])"
# The first number of a written range shares the unit of the second: "0.2 to 1.1 km2", "between 5 and 7 cm".
# A bare "and" is not enough ("on 2026-09-27 and 3.313 m" is a date followed by a value, not a range).
_RANGE_START = re.compile(
    rf"(?:(?<![\w.\-])(-?\d+(?:\.\d+)?)\s*(?:to|\u2013|-)\s*-?\d+(?:\.\d+)?\s*{_UNIT}"
    rf"|\bbetween\s+(-?\d+(?:\.\d+)?)\s+and\s+-?\d+(?:\.\d+)?\s*{_UNIT})"
)
_ANY_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def _figures(statement: str) -> list[tuple[str, str]]:
    """(value, unit) for every number that carries a unit, including the first number of "X to Y unit"."""
    found = [(m.group(1) or m.group(3), m.group(2) or m.group(4)) for m in _RANGE_START.finditer(statement)]
    found += [(m.group(1), m.group(2)) for m in _FIGURE.finditer(statement)]
    return found


def untraceable_figures(statement: str, digest: dict | None) -> list[str]:
    """Figures with units in a statement that do not appear in the cited result."""
    pool = _numbers(digest) if digest is not None else []
    return [f"{value} {unit}" for value, unit in _figures(statement) if not _traceable(value, unit, pool)]


def half_quoted_ranges(statement: str, digest: dict | None, *, central_counts: bool = True) -> list[str]:
    """Range metrics that a statement quotes only partly (one end, or only the central value).

    Areas and displacements are computed as low/central/high. Quoting a single value would overstate what
    the method can resolve, so a statement that uses any of the three must give both ends.
    """
    figures = _ANY_NUMBER.findall(statement)

    def quoted(value: float) -> bool:
        return any(_traceable(text, "", [value]) for text in figures)

    problems = []
    for metric in ((digest or {}).get("summary") or {}).get("metrics") or []:
        low, central, high = metric.get("low"), metric.get("central"), metric.get("high")
        if low is None or high is None or low == high:
            continue
        has_low, has_high = quoted(low), quoted(high)
        has_central = central_counts and central is not None and quoted(central)
        if (has_low or has_high or has_central) and not (has_low and has_high):
            problems.append(f"{metric.get('label') or metric.get('key')}: give the full range {low} to {high} {metric.get('unit', '')}".strip())
    return problems


# ----------------------------------------------------------------- the loop


def _event(kind: str, **data) -> dict:
    return {"event": kind, "data": data}


class _Session:
    def __init__(self, req: InvestigateRequest):
        self.req = req
        self.id = provenance.new_id("investigation")
        self.results: dict[str, dict] = {}  # full objects, for the interface
        self.digests: dict[str, dict] = {}  # what the model saw, for traceability checks
        self.steps: list[InvestigationStep] = []
        self.report: Report | None = None
        self.report_attempts = 0
        self.model: str | None = None

    # each tool returns (digest_for_model, full_result_for_interface, detail_line)
    def check_coverage(self, _: dict):
        cov = catalog.coverage(bbox=self.req.bbox)
        digest = _coverage_digest(cov)
        named = question_dates(self.req.question)
        if named:
            # Which stacks have the dates the question names: decided here, not left to the model.
            holders = [
                f"track {s['track']} ({s['direction']})"
                for s in digest["stacks"]
                if s["product"] == "GCOV" and all(any(a.get("date") == d for a in s["acquisitions"]) for d in named)
            ]
            digest["dates_named_in_question"] = named
            digest["notes"].append(
                f"The question names {' and '.join(named)}. "
                + (f"Use these exact dates: {', '.join(holders)} has all of them."
                   if holders else "No single backscatter stack has all of them: use the nearest dates on one stack and say so.")
            )
        n = sum(len(s["acquisitions"]) for s in digest["stacks"] if s["product"] == "GCOV")
        return digest, cov.model_dump(mode="json"), f"{n} backscatter acquisitions in {len(digest['stacks'])} stacks"

    def _workflow(self, module: str, func: str, request):
        try:
            mod = __import__(f"nisar_investigator.workflows.{module}", fromlist=[func])
            result = plain.annotate(getattr(mod, func)(request)).model_dump(mode="json")
        except ImportError:
            digest = {"id": f"unavailable_{module}", "status": "unsupported", "summary": {"headline": f"The {module} analysis is not available on this server."}}
            return digest, digest, digest["summary"]["headline"]
        return _result_digest(result), result, result["summary"]["headline"]

    def run_change(self, a: dict):
        req = ChangeRequest(bbox=self.req.bbox, date_before=a["date_before"], date_after=a["date_after"], track=a.get("track"))
        return self._workflow("change", "run_change", req)

    def run_timeseries(self, a: dict):
        return self._workflow("timeseries", "run_timeseries", TimeSeriesRequest(bbox=self.req.bbox, start=a.get("start"), end=a.get("end")))

    def run_motion(self, a: dict):
        return self._workflow("motion", "run_motion", MotionRequest(bbox=self.req.bbox, reference_date=a.get("reference_date"), track=a.get("track")))

    def get_context(self, a: dict):
        if a["kind"] == "earthquakes":
            data = context.earthquakes(self.req.bbox, a["start"], a["end"])
            detail = f"{data.get('count', 0)} earthquakes of magnitude 4.5 or more within 150 km" if data.get("available") else data.get("reason", "")
        else:
            dates = sorted({p["date"] for d in self.digests.values() for s in d.get("series", []) for p in s["points"]}
                           | {g[k] for d in self.digests.values() for g in d.get("granules", []) for k in ("date", "reference_date", "secondary_date") if k in g})
            data = context.river_gauges(self.req.bbox, a["start"], a["end"], dates or None)
            detail = ", ".join(g["station_name"].title() for g in data.get("gauges", [])) if data.get("available") else data.get("reason", "")
        data = {"id": f"ctx_{a['kind']}", **data}
        return data, data, detail

    def submit_report(self, a: dict):
        """Returns (ok, message_for_model)."""
        self.report_attempts += 1
        problems = []
        for item in a["observed"]:
            rid = item["result_id"]
            if rid not in self.digests:
                problems.append(f"Unknown result_id {rid!r}. Known ids: {', '.join(self.digests) or 'none'}.")
                continue
            missing = untraceable_figures(item["statement"], self.digests[rid])
            if missing:
                problems.append(f"In \"{item['statement']}\": {', '.join(missing)} not found in result {rid}.")
            for partial in half_quoted_ranges(item["statement"], self.digests[rid]):
                problems.append(f"In \"{item['statement']}\": {partial}.")
        all_digests = {"all": list(self.digests.values())}
        for text in [a["answer"]] + [e["hypothesis"] for e in a["possible_explanations"]]:
            missing = untraceable_figures(text, all_digests)
            if missing:
                problems.append(f"In \"{text[:80]}\": {', '.join(missing)} not found in any tool result.")
        for digest in self.digests.values():  # the answer may draw on any result; only range ends trigger here
            for partial in half_quoted_ranges(a["answer"], digest, central_counts=False):
                problems.append(f"In the answer: {partial}.")
        if len(a["answer"].split()) > MAX_ANSWER_WORDS:
            problems.append(
                f"The answer has {len(a['answer'].split())} words. Keep it to one or two sentences (at most "
                f"{MAX_ANSWER_WORDS} words) that answer the question; put the detail under observed."
            )
        final_attempt = self.report_attempts >= MAX_REPORT_ATTEMPTS
        if problems and not final_attempt:
            return False, (
                "Report not accepted. Quote values exactly as they appear in the results (same rounding), cite the "
                "right result id, give ranges with both ends (low to high), and replace derived figures with the "
                "two source values.\n- " + "\n- ".join(problems)
            )
        unknown = list(a["unknown"])
        if problems:
            unknown.append("Automatic checking could not trace every figure in this report to a computed result; treat uncited figures with care.")
        self.report = Report(
            answer=a["answer"],
            observed=[f"{o['statement']} [{o['result_id']}]" for o in a["observed"]],
            possible_explanations=[f"{e['hypothesis']} To check: {e['how_to_check']}" for e in a["possible_explanations"]],
            unknown=unknown,
            confidence=f"{a['confidence_level']}: {a['confidence_reason']}",
        )
        return True, "Report accepted."

    def investigation(self) -> Investigation:
        return Investigation(
            id=self.id, question=self.req.question, place_name=self.req.place_name, bbox=self.req.bbox,
            steps=self.steps, results=self.results, report=self.report, model=self.model,
        )


def _user_prompt(req: InvestigateRequest) -> str:
    w, s, e, n = req.bbox
    place = f" ({req.place_name})" if req.place_name else ""
    return (
        f"Question: {req.question}\n\n"
        f"Selected area{place}: west {w:.4f}, south {s:.4f}, east {e:.4f}, north {n:.4f} (degrees).\n"
        f"Today's date: {date.today().isoformat()}."
    )


# ----------------------------------------------------------------- backends
#
# The loop below is the same for every language model. A backend owns the provider-specific message
# history and turns one request into a list of tool calls.


class ModelError(RuntimeError):
    """A language-model failure, with a message that is safe to show to the user."""


@dataclass
class _Call:
    id: str
    name: str
    input: dict
    error: str | None = None  # set when the model's arguments could not be parsed


@dataclass
class _Turn:
    calls: list[_Call]
    pause: bool = False  # the provider paused a long turn; send the same history again


class _AnthropicBackend:
    """Claude through the Anthropic API."""

    def __init__(self, user_prompt: str):
        try:
            self.client = anthropic.Anthropic()
        except anthropic.AnthropicError:
            raise ModelError("The investigator needs a Claude API key on the server (ANTHROPIC_API_KEY).") from None
        self.messages: list[dict] = [{"role": "user", "content": user_prompt}]
        self.label = f"{config.AGENT_MODEL} (Anthropic API)"

    def turn(self) -> _Turn:
        try:
            response = self.client.beta.messages.create(
                model=config.AGENT_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": config.AGENT_EFFORT},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise ModelError("The Claude API key on the server is missing or invalid.") from None
        except anthropic.RateLimitError:
            raise ModelError("The language model is rate limited right now. Try again in a minute.") from None
        except anthropic.APIStatusError as exc:
            raise ModelError(f"The language model returned an error (HTTP {exc.status_code}).") from None
        except anthropic.APIConnectionError:
            raise ModelError("Could not reach the language model. Check the server's network.") from None
        except anthropic.AnthropicError:
            raise ModelError("The investigator needs a Claude API key on the server (ANTHROPIC_API_KEY).") from None

        if response.stop_reason == "refusal":
            raise ModelError("The language model declined this question.")
        if response.stop_reason == "max_tokens":
            raise ModelError("The language model ran out of room before finishing. Try a narrower question.")
        self.messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            return _Turn(calls=[], pause=True)
        return _Turn(calls=[_Call(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"])

    def add_results(self, results: list[tuple[_Call, str, bool]]) -> None:
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error}
                    for call, content, is_error in results
                ],
            }
        )

    def nudge(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})


def _relaxed(schema: dict) -> dict:
    """Tool schema for servers without strict mode: nullable fields become optional plain types."""
    props, required = {}, []
    for name, spec in schema["properties"].items():
        spec = dict(spec)
        if isinstance(spec.get("type"), list):
            spec["type"] = next(t for t in spec["type"] if t != "null")
        else:
            required.append(name)
        props[name] = spec
    return {"type": "object", "properties": props, "required": required}


_FUNCTION_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": _relaxed(t["input_schema"])}}
    for t in TOOLS
]
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class _ChatBackend:
    """Open-weight models: Ollama on this machine (native API), or any OpenAI-compatible endpoint."""

    def __init__(self, user_prompt: str, flavor: str):
        self.flavor = flavor  # "ollama" or "openai"
        self.model = config.LLM_MODEL
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        where = "local, Ollama" if flavor == "ollama" else "OpenAI-compatible endpoint"
        self.label = f"{self.model} ({where})"
        self._n = 0

    def _post(self) -> dict:
        if self.flavor == "ollama":
            url = f"{config.OLLAMA_HOST}/api/chat"
            payload = {
                "model": self.model, "messages": self.messages, "tools": _FUNCTION_TOOLS, "stream": False,
                # Ollama's default context is small; a truncated tool result would silently drop evidence.
                "options": {"num_ctx": config.LLM_NUM_CTX, "temperature": 0.2},
            }
            if config.LLM_THINK is not None:
                payload["think"] = config.LLM_THINK
            headers = {}
        else:
            url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
            payload = {"model": self.model, "messages": self.messages, "tools": _FUNCTION_TOOLS, "tool_choice": "auto", "temperature": 0.2, "max_tokens": 8000}
            headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=(10, 600))
        except requests.ConnectionError:
            hint = " Is Ollama running? Try `brew services start ollama`." if self.flavor == "ollama" else ""
            raise ModelError(f"Could not reach the language model server.{hint}") from None
        except requests.RequestException as exc:
            raise ModelError(f"The language model request failed ({type(exc).__name__}).") from None
        if r.status_code == 404 and self.flavor == "ollama":
            raise ModelError(f"The model {self.model} is not installed in Ollama. Run `ollama pull {self.model}`.")
        if r.status_code in (401, 403):
            raise ModelError("The language model server rejected the API key.")
        if r.status_code >= 400:
            raise ModelError(f"The language model returned an error (HTTP {r.status_code}).")
        return r.json()

    def turn(self) -> _Turn:
        body = self._post()
        message = body["message"] if self.flavor == "ollama" else body["choices"][0]["message"]
        raw_calls = message.get("tool_calls") or []
        calls: list[_Call] = []
        for raw in raw_calls:
            fn = raw.get("function", {})
            args, error = fn.get("arguments"), None
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args, error = {}, "The arguments were not valid JSON."
            if not isinstance(args, dict):
                args, error = {}, "The arguments must be a JSON object."
            self._n += 1
            call_id = raw.get("id") or f"call_{self._n}"
            raw["id"] = call_id  # keep the echoed history consistent with the ids used for results
            calls.append(_Call(call_id, fn.get("name", ""), args, error))
        content = _THINK.sub("", message.get("content") or "").strip()
        echoed = {"role": "assistant", "content": content}
        if raw_calls:
            echoed["tool_calls"] = raw_calls
        self.messages.append(echoed)
        return _Turn(calls=calls)

    def add_results(self, results: list[tuple[_Call, str, bool]]) -> None:
        for call, content, is_error in results:
            text = f"ERROR: {content}" if is_error else content
            if self.flavor == "ollama":
                self.messages.append({"role": "tool", "tool_name": call.name, "content": text})
            else:
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": text})

    def nudge(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})


def _make_backend(user_prompt: str):
    provider = config.agent_provider()
    if provider == "anthropic":
        return _AnthropicBackend(user_prompt)
    if provider == "openai_compatible":
        return _ChatBackend(user_prompt, "openai")
    return _ChatBackend(user_prompt, "ollama")


# ------------------------------------------------------------ input checking

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}


def _check_input(name: str, data: dict) -> str | None:
    """Validate a tool call against its schema. Strict mode guarantees this on the Anthropic API; other
    servers do not, so every call is checked here. Fills missing optional fields with None."""
    schema = _SCHEMAS.get(name)
    if schema is None:
        return f"Unknown tool {name!r}. Available: {', '.join(_SCHEMAS)}."
    for key, spec in schema["properties"].items():
        nullable = isinstance(spec.get("type"), list)
        value = data.get(key)
        if value is None or value == "":
            if nullable:
                data[key] = None
                continue
            return f"Missing required field {key!r}."
        kind = next(t for t in spec["type"] if t != "null") if nullable else spec.get("type")
        if kind == "integer" and isinstance(value, str) and value.lstrip("-").isdigit():
            data[key] = value = int(value)
        if kind == "string" and not isinstance(value, str):
            return f"Field {key!r} must be a string."
        if kind == "integer" and not isinstance(value, int):
            return f"Field {key!r} must be an integer."
        if kind == "array" and not isinstance(value, list):
            return f"Field {key!r} must be a list."
        if "enum" in spec and value not in spec["enum"]:
            return f"Field {key!r} must be one of {spec['enum']}."
        if kind == "string" and ("date" in key or key in ("start", "end")) and not _DATE.match(value):
            return f"Field {key!r} must be a date in YYYY-MM-DD form."
        if kind == "array" and spec.get("items", {}).get("type") == "object":
            needed = spec["items"]["required"]
            for item in value:
                if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in needed):
                    return f"Each item of {key!r} must be an object with string fields {needed}."
        if kind == "array" and spec.get("items", {}).get("type") == "string" and any(not isinstance(v, str) for v in value):
            return f"Each item of {key!r} must be a string."
    return None


# ----------------------------------------------------------------- the loop


def investigate(req: InvestigateRequest) -> Iterator[dict]:
    """Run one investigation, yielding events: step, tool_call, tool_result, done, error."""
    session = _Session(req)
    try:
        backend = _make_backend(_user_prompt(req))
    except ModelError as exc:
        yield _event("error", message=str(exc))
        return
    session.model = backend.label
    yield _event("step", title=f"Planning with {backend.label}", status="done")
    nudged = False

    for _ in range(MAX_TURNS):
        try:
            turn = backend.turn()
        except ModelError as exc:
            yield _event("error", message=str(exc))
            break
        if turn.pause:
            continue
        if not turn.calls:
            if session.report is None and not nudged:
                nudged = True
                backend.nudge("Deliver the result by calling submit_report.")
                continue
            break

        results: list[tuple[_Call, str, bool]] = []
        for call in turn.calls:
            title = _STEP_TITLES.get(call.name, call.name or "Unknown step")
            if call.name == "run_change":
                title = f"Measuring change between {call.input.get('date_before')} and {call.input.get('date_after')}"
            problem = call.error or _check_input(call.name, call.input)
            if problem:
                results.append((call, f"Invalid call to {call.name}: {problem}", True))
                continue
            yield _event("step", title=title, status="running")
            yield _event("tool_call", name=call.name, input=call.input)

            if call.name == "submit_report":
                ok, message = session.submit_report(call.input)
                results.append((call, message, not ok))
                detail = "Report accepted" if ok else "Figures did not match the results; revising"
                session.steps.append(InvestigationStep(title=title, detail=detail))
                yield _event("step", title=title, status="done" if ok else "retry", detail=detail)
                continue

            try:
                digest, full, detail = getattr(session, call.name)(call.input)
            except Exception as exc:  # noqa: BLE001 - a failed tool is reported to the model and the user, not raised
                message = f"{type(exc).__name__}: {exc}"[:300]
                results.append((call, f"Tool failed: {message}", True))
                session.steps.append(InvestigationStep(title=title, detail=f"Failed: {message}"))
                yield _event("step", title=title, status="failed", detail=message)
                continue
            ref = digest["id"]
            session.digests[ref] = digest
            session.results[ref] = full
            session.steps.append(InvestigationStep(title=title, detail=detail, result_ref=ref))
            results.append((call, json.dumps(digest, default=str), False))
            yield _event("tool_result", name=call.name, result_ref=ref, result=full)
            yield _event("step", title=title, status="done", detail=detail, result_ref=ref)

        backend.add_results(results)
        if session.report is not None:
            break

    if session.report is None:
        if not session.results:
            return
        yield _event("error", message="The investigation ended without a report. The steps and results above are still valid.")
    investigation = session.investigation()
    path = provenance.artifact_path(session.id, "investigation.json")
    path.write_text(json.dumps(investigation.model_dump(mode="json"), indent=2))
    yield _event("done", investigation=investigation.model_dump(mode="json"))


def sse(events: Iterator[dict]) -> Iterator[str]:
    """Format investigator events as a text/event-stream body."""
    for ev in events:
        yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], default=str)}\n\n"
