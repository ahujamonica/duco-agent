"""Shared agent plumbing: trace recording, checks and the state machine.

The point of this module is that an agent step is always a triple of
thought -> action -> observation, followed by explicit checks and a decision.
That record is what ``outputs/run_trace.json`` exposes, and it is how the
system proves it is reasoning about its own results instead of running a fixed
script.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..models import TraceStep


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class Attempt:
    """One try at an action, kept so retries can be compared."""

    label: str
    score: float
    payload: Any
    checks: list[CheckResult] = field(default_factory=list)


class TraceRecorder:
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []
        self._index = 0

    def add(
        self,
        agent: str,
        state: str,
        thought: str,
        action: str,
        inputs: Optional[dict] = None,
        observation: str = "",
        checks: Optional[list[CheckResult]] = None,
        decision: str = "",
    ) -> TraceStep:
        self._index += 1
        step = TraceStep(
            index=self._index,
            agent=agent,
            state=state,
            thought=thought,
            action=action,
            inputs=inputs or {},
            observation=observation,
            checks=[check.to_dict() for check in (checks or [])],
            decision=decision,
        )
        self.steps.append(step)
        return step

    def save(self, path: str | Path) -> None:
        payload = {
            "step_count": len(self.steps),
            "agents": sorted({step.agent for step in self.steps}),
            "steps": [step.to_dict() for step in self.steps],
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


class AgentBase:
    """Base class with a name, a state and helpers to log a full step."""

    name = "agent"
    states: tuple[str, ...] = ()

    def __init__(self, trace: TraceRecorder) -> None:
        self.trace = trace
        self.state = self.states[0] if self.states else "init"

    # -- state machine ---------------------------------------------------
    def transition(self, new_state: str) -> None:
        if self.states and new_state not in self.states:
            raise ValueError(f"{self.name}: illegal state {new_state}")
        self.state = new_state

    # -- logging ---------------------------------------------------------
    def act(
        self,
        state: str,
        thought: str,
        action: str,
        inputs: Optional[dict] = None,
        observation: str = "",
        checks: Optional[list[CheckResult]] = None,
        decision: str = "",
    ) -> TraceStep:
        return self.trace.add(
            agent=self.name,
            state=state,
            thought=thought,
            action=action,
            inputs=inputs or {},
            observation=observation,
            checks=checks or [],
            decision=decision,
        )

    def retry_loop(
        self,
        label: str,
        attempts: Callable[[], list[Attempt]],
        accept: Callable[[Attempt], bool],
        max_attempts: int = 3,
    ) -> Attempt:
        """Run attempts until one is accepted, keeping every try on the trace."""
        best: Optional[Attempt] = None
        for index, attempt in enumerate(attempts(), start=1):
            passed = accept(attempt)
            self.act(
                state=self.state,
                thought=f"Attempt {index} at {label}; judge it on the checks rather than assuming it worked.",
                action=label,
                inputs={"attempt": index, "variant": attempt.label},
                observation=f"score={attempt.score:.2f}; checks="
                + ", ".join(f"{check.name}:{'pass' if check.passed else 'fail'}" for check in attempt.checks),
                checks=attempt.checks,
                decision="accept" if passed else "retry with another strategy",
            )
            if best is None or attempt.score > best.score:
                best = attempt
            if passed:
                return attempt
            if index >= max_attempts:
                break
        if best is None:
            raise RuntimeError(f"{label}: no attempts were made")
        self.act(
            self.state,
            f"All attempts at {label} failed their checks; keeping the best evidence and flagging the gap for a human.",
            label,
            observation=f"best score={best.score:.2f}",
            decision="escalate with a warning",
        )
        return best
