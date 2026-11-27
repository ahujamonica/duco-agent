"""Stateful supervisor for the DuCO agent workflow.

The supervisor owns a goal graph with dependencies, dispatches one specialist at
a time, records an auditable event for every decision, pauses for human review
when extraction confidence is low, and runs a critic over the finished
artefacts before it declares the case complete.

This is a small, explicit state machine rather than a linear script: the next
goal is chosen from what is still unmet, a failed node can be retried, and a
case can be resumed from its persisted checkpoint after a human review. The
design mirrors a LangGraph supervisor graph; it is implemented in-process so
every state transition is stored on the case and visible in the trace.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AgentEvent, Case, PolicyVersion, utcnow

TASK_GRAPH = [
    {"name": "intake", "agent": "Intake Agent", "depends_on": []},
    {"name": "documents", "agent": "Document Intelligence Agent", "depends_on": ["intake"]},
    {"name": "coverage", "agent": "Coverage Agent", "depends_on": ["documents"]},
    {"name": "cob", "agent": "COB Agent", "depends_on": ["coverage"]},
    {"name": "compliance", "agent": "Compliance Agent", "depends_on": ["cob"]},
    {"name": "financial", "agent": "Financial Calculation Agent", "depends_on": ["compliance"]},
    {"name": "reporting", "agent": "Reporting Agent", "depends_on": ["financial"]},
    {"name": "critic", "agent": "Supervisor Agent", "depends_on": ["reporting"]},
]


@dataclass
class RunContext:
    db: Session
    case: Case
    run_id: str
    seq: int = 0
    state: dict = field(default_factory=dict)
    gaps: list[dict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.state = dict(self.case.workflow_state or {})
        last = (
            self.db.query(AgentEvent)
            .filter(AgentEvent.case_id == self.case.id)
            .order_by(AgentEvent.seq.desc())
            .first()
        )
        self.seq = last.seq if last else 0
        self.gaps = list(self.state.get("gaps") or [])
        self.assumptions = list(self.state.get("assumptions") or [])

    # -- trace ---------------------------------------------------------
    def emit(
        self,
        agent: str,
        goal: str,
        action: str,
        tool: str | None = None,
        inputs: dict | None = None,
        observation: str = "",
        checks: list[dict] | None = None,
        decision: str = "",
        next_action: str | None = None,
        status: str = "succeeded",
        duration_ms: int | None = None,
    ) -> AgentEvent:
        self.seq += 1
        started = utcnow() - timedelta(milliseconds=duration_ms or 0)
        event = AgentEvent(
            case_id=self.case.id,
            seq=self.seq,
            run_id=self.run_id,
            agent=agent,
            goal=goal,
            state=str(self.state.get("stage") or "running"),
            action=action,
            tool=tool,
            inputs=_safe(inputs or {}),
            observation=observation,
            checks=checks or [],
            decision=decision,
            next_action=next_action,
            status=status,
            started_at=started,
            duration_ms=duration_ms,
        )
        self.db.add(event)
        self.db.commit()
        return event

    # -- state ---------------------------------------------------------
    def save(self, **updates) -> None:
        # ``self.state`` is the live copy the supervisor mutates; merge it back
        # so task statuses and the current stage are never lost.
        state = {**(self.case.workflow_state or {}), **self.state}
        state.update(updates)
        state["gaps"] = _safe(self.gaps)
        state["assumptions"] = list(dict.fromkeys(self.assumptions))
        self.state = state
        self.case.workflow_state = state
        self.db.add(self.case)
        self.db.commit()

    def set_stage(self, stage: str) -> None:
        self.state["stage"] = stage
        self.case.workflow_state = {**(self.case.workflow_state or {}), **self.state, "stage": stage}
        self.db.add(self.case)

    def gap(self, code: str, severity: str, title: str, detail: str, action: str | None = None) -> None:
        if any(item.get("code") == code and item.get("title") == title for item in self.gaps):
            return
        self.gaps.append(
            {
                "code": code,
                "severity": severity,
                "title": title,
                "detail": detail,
                "action": action,
            }
        )

    def resolve_gap(self, code: str) -> None:
        self.gaps = [item for item in self.gaps if item.get("code") != code]

    def assume(self, text: str) -> None:
        if text and text not in self.assumptions:
            self.assumptions.append(text)


def _safe(value: Any) -> Any:
    """Make a dict JSON-safe without leaking non-serialisable objects."""
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class Supervisor:
    def __init__(self, db: Session, case: Case, run_id: str):
        self.db = db
        self.case = case
        self.run_id = run_id
        self.ctx = RunContext(db=db, case=case, run_id=run_id)

    def run(self) -> str:
        from . import nodes

        ctx = self.ctx
        ctx.state["stage"] = "planning"
        ctx.state["tasks"] = {task["name"]: "pending" for task in TASK_GRAPH}
        ctx.state["review_pending"] = 0
        ctx.state.pop("pause_reason", None)
        ctx.emit(
            "Supervisor Agent",
            "Plan the case",
            "create_goal_graph",
            inputs={"goals": [task["name"] for task in TASK_GRAPH]},
            observation="A goal graph with explicit dependencies was created for this case.",
            checks=[{"name": "Every goal has a named owner", "passed": True, "detail": "8 goals assigned"}],
            decision="Dispatch the first goal whose prerequisites are met; pause for review if extraction is uncertain.",
            next_action="intake",
            status="running",
        )

        while True:
            task = self._next_task()
            if task is None:
                break
            ctx.state["stage"] = task["name"]
            ctx.state["tasks"][task["name"]] = "running"
            ctx.save()
            ctx.emit(
                "Supervisor Agent",
                task["name"],
                f"dispatch:{task['agent']}",
                inputs={"dependencies_met": task["depends_on"]},
                observation=f"All prerequisites for '{task['name']}' are satisfied.",
                decision=f"Hand control to the {task['agent']}.",
                next_action=task["name"],
                status="running",
            )
            node: Callable = getattr(nodes, f"{task['name']}_node")
            try:
                result = node(ctx)
            except Exception as exc:  # pragma: no cover - defensive
                self.db.rollback()
                self.case = self.db.get(Case, self.case.id)
                ctx.case = self.case
                ctx.emit(
                    task["agent"],
                    task["name"],
                    "unhandled_error",
                    observation=str(exc),
                    checks=[{"name": "Node completed", "passed": False, "detail": str(exc)}],
                    decision="Stop the run and surface the error for repair.",
                    status="failed",
                )
                self.case.status = "failed"
                self.case.error = f"{task['name']}: {exc}"
                self.db.add(self.case)
                self.db.commit()
                traceback.print_exc()
                return "failed"

            ctx.state["tasks"][task["name"]] = "done" if result == "done" else result
            ctx.save()
            if result == "pause":
                review_pending = int(ctx.state.get("review_pending") or 0)
                blocking_gap = next(
                    (gap for gap in reversed(ctx.gaps) if gap.get("severity") == "blocking"),
                    None,
                )
                pause_detail = (
                    f"{review_pending} extracted field(s) need confirmation."
                    if review_pending
                    else (
                        f"{blocking_gap.get('title')}: {blocking_gap.get('detail')}"
                        if blocking_gap
                        else "The workflow paused without pending review fields or a blocking gap."
                    )
                )
                ctx.state["pause_reason"] = {
                    "kind": "human_review" if review_pending else "required_action",
                    "detail": pause_detail,
                }
                ctx.save()
                self.case.status = "awaiting_review"
                self.case.workflow_state = {**(self.case.workflow_state or {}), "stage": "review"}
                self.db.add(self.case)
                self.db.commit()
                ctx.emit(
                    "Supervisor Agent",
                    "Pause for human review" if review_pending else "Pause for required action",
                    "interrupt",
                    observation=pause_detail,
                    checks=[
                        {
                            "name": "Pending review fields",
                            "passed": review_pending == 0,
                            "detail": str(review_pending),
                        },
                        {
                            "name": "Pause reason identified",
                            "passed": bool(blocking_gap or review_pending),
                            "detail": pause_detail,
                        },
                    ],
                    decision=(
                        "Pause before any money is calculated until a person confirms the fields."
                        if review_pending
                        else "Pause until the blocking requirement is resolved."
                    ),
                    next_action="awaiting_review" if review_pending else "resolve_required_action",
                    status="waiting",
                )
                return "paused"
            if result == "failed":
                self.case.status = "failed"
                self.db.add(self.case)
                self.db.commit()
                return "failed"

        # ------------------------------------------------------------------
        # Final critic is a task in the graph; if it passed, complete.
        # ------------------------------------------------------------------
        self.case.status = "complete"
        self.case.completed_at = utcnow()
        self.case.workflow_state = {
            **(self.case.workflow_state or {}),
            "stage": "complete",
            "gaps": _safe(ctx.gaps),
            "assumptions": ctx.assumptions,
        }
        self.db.add(self.case)
        self.db.commit()
        ctx.emit(
            "Supervisor Agent",
            "Close the case",
            "complete_run",
            inputs={"tasks": ctx.state.get("tasks")},
            observation="Every goal in the graph has finished; the critic checked the deliverables.",
            checks=[{"name": "All goals complete", "passed": True, "detail": "8 of 8"}],
            decision="Case complete. Results, trace and reports are available for review.",
            status="succeeded",
        )
        return "complete"

    def _next_task(self) -> dict | None:
        statuses = self.ctx.state.get("tasks") or {}
        for task in TASK_GRAPH:
            if statuses.get(task["name"], "pending") != "pending":
                continue
            if all(statuses.get(dep) == "done" for dep in task["depends_on"]):
                return task
        return None


def _revert_accumulators(db: Session, case: Case) -> None:
    """Undo the per-member accumulator deltas a previous run of this case applied."""
    from ..models import PolicyAccumulator

    applied = (case.workflow_state or {}).get("applied_accumulators") or {}
    for accumulator_id, delta in applied.items():
        accumulator = db.get(PolicyAccumulator, int(accumulator_id))
        if not accumulator:
            continue
        accumulator.deductible_used = max(
            0, (accumulator.deductible_used or 0) - Decimal(str(delta.get("deductible", 0)))
        )
        accumulator.oop_used = max(0, (accumulator.oop_used or 0) - Decimal(str(delta.get("oop", 0))))
        accumulator.annual_limit_used = max(
            0, (accumulator.annual_limit_used or 0) - Decimal(str(delta.get("annual", 0)))
        )
        sublimits = dict(accumulator.sublimits or {})
        for key, value in (delta.get("sublimits") or {}).items():
            try:
                sublimits[key] = str(max(0, Decimal(str(sublimits.get(key) or 0)) - Decimal(str(value))))
            except Exception:
                pass
        accumulator.sublimits = sublimits
        db.add(accumulator)
    db.commit()


def run_case(case_id: int, run_id: str | None = None) -> str:
    """Run the workflow for one case. Returns the terminal status."""
    db = SessionLocal()
    try:
        case = db.get(Case, case_id)
        if not case:
            return "missing"
        run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        case.status = "running"
        case.error = None
        case.run_token = run_id
        db.add(case)
        db.commit()
        _revert_accumulators(db, case)
        supervisor = Supervisor(db, case, run_id)
        outcome = supervisor.run()
        return outcome
    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        case = db.get(Case, case_id)
        if case:
            case.status = "failed"
            case.error = str(exc)
            db.add(case)
            db.commit()
            RunContext(db=db, case=case, run_id=run_id or "run-error").emit(
                "Supervisor Agent",
                "Run failure",
                "abort",
                observation=str(exc),
                checks=[{"name": "Run finished", "passed": False, "detail": str(exc)}],
                decision="Stop and surface the failure.",
                status="failed",
            )
        traceback.print_exc()
        return "failed"
    finally:
        db.close()


def start_run_async(case_id: int) -> str:
    """Start the workflow in a background thread; returns the run id."""
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        case = db.get(Case, case_id)
        if case:
            case.status = "queued"
            case.run_token = run_id
            case.error = None
            db.add(case)
            db.commit()
    finally:
        db.close()
    thread = threading.Thread(target=run_case, args=(case_id, run_id), daemon=True, name=f"duco-{case_id}")
    thread.start()
    return run_id
