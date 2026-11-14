"""The investigator: turns a plain-language question into visible analysis steps and a grounded report.

The language model plans and explains. It never sees imagery and never produces numbers: every figure in
the report must come from a tool result, and `submit_report` is rejected when a figure cannot be traced.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date

import anthropic

from . import catalog, config, context, provenance
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
MAX_REPORT_ATTEMPTS = 3

SYSTEM_PROMPT = """\
You are the analysis planner inside NISAR Investigator, a research tool that answers questions about how \
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
or provisional dates over beta ones, which are uncalibrated. If the question needs something these tools \
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
    """What the model needs from a Coverage object: per-stack dates with tiers, without footprints or URLs."""
    stacks: dict[tuple, dict] = {}
    for product, granules in cov.products.items():
        for g in granules:
            key = (product, g.track, g.direction, g.frame)
            entry = stacks.setdefault(
                key,
                {"product": product, "track": g.track, "direction": g.direction, "frame": g.frame,
                 "polarizations": g.polarizations, "acquisitions": []},
            )
            if g.date:
                entry["acquisitions"].append({"date": g.date, "tier": g.tier})
            else:
                entry["acquisitions"].append(
                    {"reference_date": g.reference_date, "secondary_date": g.secondary_date, "tier": g.tier}
                )
    return {"id": "coverage", "stacks": list(stacks.values()), "notes": cov.notes}


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


def untraceable_figures(statement: str, digest: dict | None) -> list[str]:
    """Figures with units in a statement that do not appear in the cited result."""
    pool = _numbers(digest) if digest is not None else []
    return [f"{m.group(1)} {m.group(2)}" for m in _FIGURE.finditer(statement) if not _traceable(m.group(1), m.group(2), pool)]


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

    # each tool returns (digest_for_model, full_result_for_interface, detail_line)
    def check_coverage(self, _: dict):
        cov = catalog.coverage(bbox=self.req.bbox)
        digest = _coverage_digest(cov)
        n = sum(len(s["acquisitions"]) for s in digest["stacks"] if s["product"] == "GCOV")
        return digest, cov.model_dump(mode="json"), f"{n} backscatter acquisitions in {len(digest['stacks'])} stacks"

    def _workflow(self, module: str, func: str, request):
        try:
            mod = __import__(f"nisar_investigator.workflows.{module}", fromlist=[func])
            result = getattr(mod, func)(request).model_dump(mode="json")
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
        all_digests = {"all": list(self.digests.values())}
        for text in [a["answer"]] + [e["hypothesis"] for e in a["possible_explanations"]]:
            missing = untraceable_figures(text, all_digests)
            if missing:
                problems.append(f"In \"{text[:80]}\": {', '.join(missing)} not found in any tool result.")
        final_attempt = self.report_attempts >= MAX_REPORT_ATTEMPTS
        if problems and not final_attempt:
            return False, (
                "Report not accepted: some figures could not be traced to a tool result. Quote values exactly as "
                "they appear in the results (same rounding), cite the right result id, and replace derived "
                "figures with the two source values.\n- " + "\n- ".join(problems)
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
            steps=self.steps, results=self.results, report=self.report,
        )


def _user_prompt(req: InvestigateRequest) -> str:
    w, s, e, n = req.bbox
    place = f" ({req.place_name})" if req.place_name else ""
    return (
        f"Question: {req.question}\n\n"
        f"Selected area{place}: west {w:.4f}, south {s:.4f}, east {e:.4f}, north {n:.4f} (degrees).\n"
        f"Today's date: {date.today().isoformat()}."
    )


def investigate(req: InvestigateRequest) -> Iterator[dict]:
    """Run one investigation, yielding events: step, tool_call, tool_result, done, error."""
    session = _Session(req)
    try:
        client = anthropic.Anthropic()
    except anthropic.AnthropicError:
        yield _event("error", message="The investigator needs a Claude API key on the server (ANTHROPIC_API_KEY).")
        return
    messages: list[dict] = [{"role": "user", "content": _user_prompt(req)}]
    nudged = False

    for _ in range(MAX_TURNS):
        try:
            response = client.beta.messages.create(
                model=config.AGENT_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": config.AGENT_EFFORT},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            yield _event("error", message="The Claude API key on the server is missing or invalid.")
            return
        except anthropic.RateLimitError:
            yield _event("error", message="The language model is rate limited right now. Try again in a minute.")
            return
        except anthropic.APIStatusError as exc:
            yield _event("error", message=f"The language model returned an error (HTTP {exc.status_code}).")
            return
        except anthropic.APIConnectionError:
            yield _event("error", message="Could not reach the language model. Check the server's network.")
            return
        except anthropic.AnthropicError:
            yield _event("error", message="The investigator needs a Claude API key on the server (ANTHROPIC_API_KEY).")
            return

        if response.stop_reason == "refusal":
            yield _event("error", message="The language model declined this question.")
            return
        if response.stop_reason == "max_tokens":
            yield _event("error", message="The language model ran out of room before finishing. Try a narrower question.")
            return

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue

        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            if session.report is None and not nudged:
                nudged = True
                messages.append({"role": "user", "content": "Deliver the result by calling submit_report."})
                continue
            break

        tool_results = []
        for call in calls:
            title = _STEP_TITLES.get(call.name, call.name)
            if call.name == "run_change":
                title = f"Measuring change between {call.input.get('date_before')} and {call.input.get('date_after')}"
            yield _event("step", title=title, status="running")
            yield _event("tool_call", name=call.name, input=call.input)

            if call.name == "submit_report":
                ok, message = session.submit_report(call.input)
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": message, "is_error": not ok})
                detail = "Report accepted" if ok else "Figures did not match the results; revising"
                session.steps.append(InvestigationStep(title=title, detail=detail))
                yield _event("step", title=title, status="done" if ok else "retry", detail=detail)
                continue

            handler = getattr(session, call.name, None)
            if handler is None:
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": f"Unknown tool {call.name}.", "is_error": True})
                continue
            try:
                digest, full, detail = handler(call.input)
            except Exception as exc:  # noqa: BLE001 - a failed tool is reported to the model and the user, not raised
                message = f"{type(exc).__name__}: {exc}"[:300]
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": f"Tool failed: {message}", "is_error": True})
                session.steps.append(InvestigationStep(title=title, detail=f"Failed: {message}"))
                yield _event("step", title=title, status="failed", detail=message)
                continue
            ref = digest["id"]
            session.digests[ref] = digest
            session.results[ref] = full
            session.steps.append(InvestigationStep(title=title, detail=detail, result_ref=ref))
            tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(digest, default=str)})
            yield _event("tool_result", name=call.name, result_ref=ref, result=full)
            yield _event("step", title=title, status="done", detail=detail, result_ref=ref)

        messages.append({"role": "user", "content": tool_results})
        if session.report is not None:
            break

    if session.report is None:
        yield _event("error", message="The investigation ended without a report. The steps and results above are still valid.")
    investigation = session.investigation()
    path = provenance.artifact_path(session.id, "investigation.json")
    path.write_text(json.dumps(investigation.model_dump(mode="json"), indent=2))
    yield _event("done", investigation=investigation.model_dump(mode="json"))


def sse(events: Iterator[dict]) -> Iterator[str]:
    """Format investigator events as a text/event-stream body."""
    for ev in events:
        yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], default=str)}\n\n"
