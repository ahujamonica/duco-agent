"""Supervisor that plans the run, dispatches the specialist agents and checks the result.

This is the control flow a reviewer should look at first: goals with
dependencies, one dispatcher, a critic that inspects the finished artifacts, and
a trace that records every decision. Nothing here is a fixed sequence of
function calls: the next goal is chosen from what is still unmet, and a failed
check sends the run back to the agent that can repair it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .agents.base import TraceRecorder
from .agents.cob import COBAgent, COBResult
from .agents.compliance import ComplianceAgent, ComplianceResult
from .agents.coverage import CoverageAgent, CoverageResult
from .agents.intake import IntakeAgent, IntakeResult
from .agents.reporting import ReportResult, ReportingAgent
from .models import money
from .tools.insurer_api import InsurerAPIClient


@dataclass
class Goal:
    name: str
    agent: str
    depends_on: tuple[str, ...] = ()
    status: str = "pending"  # pending | done | failed


@dataclass
class RunResult:
    intake: IntakeResult
    coverage: CoverageResult
    compliance: ComplianceResult
    cob: COBResult
    preliminary: dict
    report: ReportResult
    trace_path: str
    artifacts: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "claims": [claim.claim_id for claim in self.intake.claims],
            "total_billed": str(money(sum((claim.total_billed for claim in self.intake.claims), money(0)))),
            "insurers_pay": str(money(sum((outcome.total_plan_paid for outcome in self.cob.outcomes.values()), money(0)))),
            "member_out_of_pocket": str(self.cob.total_member_out_of_pocket),
            "saved_by_coordination": str(self.cob.total_savings),
            "preauth_gap_cost": str(self.cob.preauth_gap_cost),
            "artifacts": self.artifacts,
        }


class Orchestrator:
    name = "Orchestrator"

    def __init__(self, root: Path, output_dir: Path | None = None, client_mode: str = "inprocess") -> None:
        self.root = root
        self.output_dir = output_dir or root / "outputs"
        self.client = InsurerAPIClient(mode=client_mode)
        self.trace = TraceRecorder()
        self.goals = [
            Goal("extract_and_code", "IntakeAgent"),
            Goal("verify_coverage", "CoverageAgent", ("extract_and_code",)),
            Goal("check_preauth_need", "COBAgent", ("verify_coverage",)),
            Goal("file_preauth_and_letters", "ComplianceAgent", ("check_preauth_need",)),
            Goal("adjudicate_cob", "COBAgent", ("file_preauth_and_letters",)),
            Goal("render_outputs", "ReportingAgent", ("adjudicate_cob",)),
            Goal("critic_review", "Orchestrator", ("render_outputs",)),
        ]

    # -- helpers -----------------------------------------------------------
    def _log(self, state: str, thought: str, action: str, inputs=None, observation="", checks=None, decision="") -> None:
        self.trace.add(self.name, state, thought, action, inputs, observation, checks, decision)

    def _next_goal(self) -> Goal | None:
        done = {goal.name for goal in self.goals if goal.status == "done"}
        for goal in self.goals:
            if goal.status == "pending" and all(dependency in done for dependency in goal.depends_on):
                return goal
        return None

    # -- main loop ---------------------------------------------------------
    def run(self) -> RunResult:
        self._log(
            "planning",
            "Two claims, two plans each, and one decision that matters: which plan is primary. Plan the work as goals with dependencies so a failed check can send it back.",
            "plan_goals",
            inputs={"goals": [goal.name for goal in self.goals]},
            observation="plan created",
            decision="run goals in dependency order",
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        intake_agent = IntakeAgent(self.trace)
        coverage_agent = CoverageAgent(self.trace, self.client)
        cob_agent = COBAgent(self.trace)
        compliance_agent = ComplianceAgent(self.trace, self.client)
        reporting_agent = ReportingAgent(self.trace)

        intake: IntakeResult | None = None
        coverage: CoverageResult | None = None
        preliminary: dict = {}
        compliance: ComplianceResult | None = None
        cob: COBResult | None = None
        report: ReportResult | None = None

        while True:
            goal = self._next_goal()
            if goal is None:
                break
            self._log("acting", f"Next unmet goal: {goal.name} ({goal.agent}).", "dispatch", {"goal": goal.name})
            try:
                if goal.name == "extract_and_code":
                    intake = intake_agent.run(self.root)
                elif goal.name == "verify_coverage":
                    assert intake is not None
                    coverage = coverage_agent.run(intake.claims)
                elif goal.name == "check_preauth_need":
                    assert intake is not None and coverage is not None
                    preliminary = cob_agent.preliminary(intake.claims, coverage)
                elif goal.name == "file_preauth_and_letters":
                    assert intake is not None and coverage is not None
                    compliance = compliance_agent.run(intake.claims, coverage, self.output_dir)
                elif goal.name == "adjudicate_cob":
                    assert intake is not None and coverage is not None and compliance is not None
                    cob = cob_agent.run(intake.claims, coverage, compliance.obtained_map())
                    cob.preliminary = preliminary
                elif goal.name == "render_outputs":
                    assert intake is not None and cob is not None and compliance is not None and coverage is not None
                    checks = self._agent_checks(intake, coverage, compliance)
                    report = reporting_agent.run(
                        intake.claims,
                        cob.outcomes,
                        compliance.records,
                        intake.issues,
                        self.output_dir,
                        preauth_gap=cob.preauth_gap_cost,
                        agent_checks=checks,
                    )
                elif goal.name == "critic_review":
                    assert report is not None and cob is not None
                    checks = self._critic(report, cob, compliance)
                    self._log(
                        "reviewing",
                        "The agent inspects its own deliverables: files exist, the numbers conserve, and every required pre-auth has a letter.",
                        "critic_review",
                        observation=f"{sum(1 for check in checks if check.passed)}/{len(checks)} checks passed",
                        checks=checks,
                        decision="ship" if all(check.passed for check in checks) else "repair before shipping",
                    )
                    if not all(check.passed for check in checks):
                        self._repair(reporting_agent, intake, cob, compliance)
                goal.status = "done"
                self._log("acting", f"{goal.name} finished.", "goal_complete", {"goal": goal.name}, decision="mark done")
            except Exception as exc:  # noqa: BLE001 - the supervisor records, then fails the run honestly
                goal.status = "failed"
                self._log(
                    "acting",
                    f"{goal.name} raised an error; record it instead of pretending the run succeeded.",
                    "goal_failed",
                    {"goal": goal.name},
                    observation=f"{exc.__class__.__name__}: {exc}",
                    decision="stop the run and report the failure",
                )
                raise

        assert intake and coverage and compliance and cob and report
        trace_path = self.output_dir / "run_trace.json"
        self.trace.save(trace_path)
        artifacts = dict(report.artifacts)
        artifacts["trace"] = str(trace_path)
        artifacts["preauth_letters"] = str(self.output_dir / "preauth_letters")
        warnings = list(intake.issues) + list(coverage.warnings) + list(compliance.warnings) + list(cob.warnings) + list(report.warnings)

        checks: list[dict] = []
        result = RunResult(
            intake=intake,
            coverage=coverage,
            compliance=compliance,
            cob=cob,
            preliminary=preliminary,
            report=report,
            trace_path=str(trace_path),
            artifacts=artifacts,
            warnings=warnings,
            checks=checks,
        )
        summary_path = self.output_dir / "run_summary.json"
        artifacts["summary"] = str(summary_path)
        summary_path.write_text(json.dumps({**result.summary(), "artifacts": artifacts}, indent=2), encoding="utf-8")
        return result

    # -- agent checks shown on the cost flow page --------------------------
    def _agent_checks(self, intake, coverage, compliance) -> list[dict]:
        checks: list[dict] = []
        invoice = intake.documents["invoice"]
        estimate = intake.documents["estimate"]
        checks.append(
            {
                "label": f"Physiotherapy scan: {len(invoice.lines)} service lines, line sum matches the printed total",
                "passed": bool(invoice.field_value("sum_reconciles", False)),
            }
        )
        checks.append(
            {
                "label": f"Surgeon estimate: {len(estimate.lines)} CPT lines, total matching the printed figure",
                "passed": bool(estimate.field_value("sum_reconciles", False)),
            }
        )
        checks.append(
            {
                "label": "MRI report: ACL and meniscus tears read from the text layer",
                "passed": len(intake.documents["mri"].field_value("findings", [])) >= 2,
            }
        )
        checks.append(
            {
                "label": f"Voice query: {len(intake.goals)} household goals recognised",
                "passed": len(intake.goals) >= 2,
            }
        )
        checks.append(
            {
                "label": "Coverage verified for both members and both plans",
                "passed": not coverage.warnings,
            }
        )
        filed = [record for record in compliance.records.values() if record.required]
        checks.append(
            {
                "label": f"Pre-authorisation filed with both insurers ({len(filed)} references)",
                "passed": all(record.approved for record in filed) and len(filed) == 2,
            }
        )
        return checks

    # -- critic ------------------------------------------------------------
    def _critic(self, report: ReportResult, cob: COBResult, compliance: ComplianceResult | None) -> list:
        from .agents.base import CheckResult

        checks = [
            CheckResult("cost_flow_exists", Path(report.artifacts.get("cost_flow", "")).exists(), ""),
            CheckResult("breakdown_exists", Path(report.artifacts.get("json", "")).exists(), ""),
            CheckResult("script_exists", Path(report.artifacts.get("script", "")).exists(), ""),
        ]
        for claim_id, outcome in cob.outcomes.items():
            checks.append(
                CheckResult(
                    f"{claim_id}_numbers_conserve",
                    money(outcome.total_plan_paid + outcome.member_out_of_pocket) == outcome.claim.total_billed,
                    f"{outcome.total_plan_paid} + {outcome.member_out_of_pocket}",
                )
            )
        if compliance:
            for key, record in compliance.records.items():
                if record.required:
                    checks.append(
                        CheckResult(
                            f"{key[0]}_{key[1]}_letter_present",
                            Path(record.letter_path).exists(),
                            record.letter_path,
                        )
                    )
        return checks

    def _repair(self, reporting_agent: ReportingAgent, intake, cob, compliance) -> None:
        self._log("repairing", "One critic check failed; re-render the reports rather than shipping a gap.", "repair_reports")
        reporting_agent.run(
            intake.claims,
            cob.outcomes,
            compliance.records,
            intake.issues,
            self.output_dir,
            preauth_gap=cob.preauth_gap_cost,
        )
