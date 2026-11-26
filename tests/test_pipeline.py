"""End-to-end test: the agent run produces every artifact and conserves the money."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from duco_agent.agents.base import AgentBase, Attempt, CheckResult, TraceRecorder
from duco_agent.orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parents[1]


def test_retry_loop_accepts_the_second_attempt_and_traces_both():
    trace = TraceRecorder()

    class Demo(AgentBase):
        name = "DemoAgent"
        states = ("working",)

    agent = Demo(trace)
    attempts = [
        Attempt("first", 0.4, None, [CheckResult("reconciles", False)]),
        Attempt("second", 0.9, None, [CheckResult("reconciles", True)]),
    ]
    chosen = agent.retry_loop("parse", lambda: iter(attempts), lambda attempt: all(c.passed for c in attempt.checks))
    assert chosen.label == "second"
    assert len(trace.steps) == 2
    assert trace.steps[0].decision == "retry with another strategy"


def test_full_run_writes_outputs_and_conserves(tmp_path):
    result = Orchestrator(ROOT, tmp_path).run()
    assert (tmp_path / "cost_flow.html").exists()
    assert (tmp_path / "financial_breakdown.json").exists()
    assert (tmp_path / "run_trace.json").exists()
    assert (tmp_path / "briefing_script.txt").exists()
    letters = list((tmp_path / "preauth_letters").glob("*.pdf"))
    assert len(letters) == 2
    for claim in result.intake.claims:
        outcome = result.cob.outcomes[claim.claim_id]
        assert outcome.total_plan_paid + outcome.member_out_of_pocket == claim.total_billed
    # The pre-auth loop must show a real difference between filing and not filing.
    assert result.cob.preauth_gap_cost > 0
    assert result.cob.total_savings > 0
    assert len(result.intake.documents["invoice"].lines) == 3
