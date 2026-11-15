"""The investigator's grounding checks: figures in a report must be traceable to a computed result."""

from nisar_investigator import agent
from nisar_investigator.schemas import InvestigateRequest

DIGEST = {
    "id": "chg_1",
    "summary": {
        "headline": "Radar brightness rose over 0.21 to 1.09 km2.",
        "metrics": [{"key": "increase", "low": 0.21, "central": 0.44, "high": 1.09, "unit": "km2"}],
    },
    "stats": {"HH": {"before_db": -17.38, "after_db": -10.71}},
    "uncertainty": {"noise_floor_fraction": 0.3142},
}


def test_figures_present_in_result_are_traceable():
    assert agent.untraceable_figures("Brightness rose over 0.21 to 1.09 km2, most likely 0.44 km2.", DIGEST) == []
    assert agent.untraceable_figures("HH went from -17.4 dB to -10.7 dB.", DIGEST) == []
    assert agent.untraceable_figures("About 31% of pixels sit at the noise floor.", DIGEST) == []


def test_derived_or_invented_figures_are_flagged():
    assert agent.untraceable_figures("HH rose by 6.7 dB.", DIGEST) == ["6.7 dB"]
    assert agent.untraceable_figures("The change covers 2.5 km2.", DIGEST) == ["2.5 km2"]


def test_both_ends_of_a_written_range_are_checked():
    assert agent.untraceable_figures("Brightness rose over 0.21 to 1.09 km2.", DIGEST) == []
    assert agent.untraceable_figures("Brightness rose over 0.05 to 1.09 km2.", DIGEST) == ["0.05 km2"]


def test_dates_and_counts_are_not_treated_as_figures():
    assert agent.untraceable_figures("Measured on 19 June 2026 across 9 dates on 2 tracks.", DIGEST) == []


def test_a_range_must_be_quoted_with_both_ends():
    assert agent.half_quoted_ranges("Brightness rose over 0.21 to 1.09 km2.", DIGEST) == []
    assert agent.half_quoted_ranges("HH went from -17.4 dB to -10.7 dB.", DIGEST) == []
    assert len(agent.half_quoted_ranges("Brightness rose over 1.09 km2.", DIGEST)) == 1
    assert len(agent.half_quoted_ranges("Brightness rose over about 0.44 km2.", DIGEST)) == 1
    # in the answer, a central value alone does not trigger (it may belong to another result)
    assert agent.half_quoted_ranges("About 0.44 km2 changed.", DIGEST, central_counts=False) == []


def test_report_quoting_one_end_of_a_range_is_sent_back():
    s = _session()
    ok, message = s.submit_report(_report("Brightness rose over 1.09 km2."))
    assert not ok and "full range" in message


def _session() -> agent._Session:
    s = agent._Session(InvestigateRequest(question="What changed?", bbox=(-120.56, 50.675, -120.40, 50.735)))
    s.digests["chg_1"] = DIGEST
    return s


def _report(statement: str, result_id: str = "chg_1") -> dict:
    return {
        "answer": "Brightness rose over part of the area.",
        "observed": [{"statement": statement, "result_id": result_id}],
        "possible_explanations": [{"hypothesis": "Water drained and exposed sandbars.", "how_to_check": "Compare with the river gauge."}],
        "unknown": ["Whether the change is seasonal."],
        "confidence_level": "medium",
        "confidence_reason": "One pair of dates.",
    }


def test_report_with_traceable_figures_is_accepted_and_cites_its_result():
    s = _session()
    ok, _ = s.submit_report(_report("Brightness rose over 0.21 to 1.09 km2."))
    assert ok and s.report is not None
    assert s.report.observed == ["Brightness rose over 0.21 to 1.09 km2. [chg_1]"]


def test_report_with_untraceable_figure_is_sent_back():
    s = _session()
    ok, message = s.submit_report(_report("Brightness rose over 3.3 km2."))
    assert not ok and s.report is None
    assert "3.3 km2" in message


def test_report_citing_unknown_result_is_sent_back():
    s = _session()
    ok, message = s.submit_report(_report("Brightness rose over 0.44 km2.", result_id="chg_missing"))
    assert not ok and "chg_missing" in message


def test_after_repeated_failures_the_report_is_kept_but_flagged():
    s = _session()
    for _ in range(agent.MAX_REPORT_ATTEMPTS - 1):
        ok, _ = s.submit_report(_report("Brightness rose over 3.3 km2."))
        assert not ok
    ok, _ = s.submit_report(_report("Brightness rose over 3.3 km2."))
    assert ok and s.report is not None
    assert any("could not trace" in u for u in s.report.unknown)


def test_dates_named_in_a_question_are_found():
    q = "How did the lake change between 19 June and 17 October 2026, and does the gauge agree?"
    assert agent.question_dates(q) == ["2026-06-19", "2026-10-17"]
    assert agent.question_dates("Did the ground move on June 24, 2026?") == ["2026-06-24"]
    assert agent.question_dates("Compare 2026-09-27 with 2026-10-21.") == ["2026-09-27", "2026-10-21"]
    assert agent.question_dates("What changed here over the summer?") == []


def test_a_long_answer_is_sent_back():
    s = _session()
    report = _report("Brightness rose over 0.21 to 1.09 km2.")
    report["answer"] = " ".join(["word"] * (agent.MAX_ANSWER_WORDS + 1))
    ok, message = s.submit_report(report)
    assert not ok and "one or two sentences" in message


def test_a_date_followed_by_a_value_is_not_read_as_a_range():
    gauge = {"id": "ctx_river_gauges", "gauges": [{"level_on_dates": {"2026-09-27": 1.494, "2026-10-21": 3.313}}]}
    text = "River gauge 02366500 recorded 1.494 m on 2026-09-27 and 3.313 m on 2026-10-21."
    assert agent.untraceable_figures(text, gauge) == []
    assert agent.untraceable_figures("It moved between 5 and 7 cm.", {"a": 7.0}) == ["5 cm"]
    assert agent.untraceable_figures("It moved 5-7 cm.", {"a": 7.0}) == ["5 cm"]
