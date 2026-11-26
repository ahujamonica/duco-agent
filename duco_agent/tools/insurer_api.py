"""Client the agent uses to talk to the mock insurer APIs.

``mode="inprocess"`` calls the handlers directly (the default, so the demo needs
no ports); ``mode="http"`` talks to ``python -m duco_agent.mock_api.server``.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from ..mock_api import service


class InsurerAPIClient:
    def __init__(self, mode: str = "inprocess", base_url: str = "http://127.0.0.1:8765"):
        self.mode = mode
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, **params) -> dict:
        if self.mode == "inprocess":
            handler = {"eligibility": "eligibility", "benefits": "benefits", "plans": "plans"}[path]
            return service.HANDLERS[handler](**params)
        url = f"{self.base_url}/{path}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, path: str, payload: dict) -> dict:
        if self.mode == "inprocess":
            handler = {"preauth": "preauth", "claim": "claim"}[path]
            return service.HANDLERS[handler](payload=payload, **{k: v for k, v in payload.items() if k != "payload"})
        request = urllib.request.Request(
            f"{self.base_url}/{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    # -- typed helpers ---------------------------------------------------
    def list_plans(self) -> dict:
        return self._get("plans")

    def eligibility(self, plan_id: str, member_id: str) -> dict:
        return self._get("eligibility", plan_id=plan_id, member_id=member_id)

    def benefits(self, plan_id: str, member_id: str) -> dict:
        return self._get("benefits", plan_id=plan_id, member_id=member_id)

    def submit_preauth(self, plan_id: str, member_id: str, claim_id: str, payload: dict | None = None) -> dict:
        request = {"plan_id": plan_id, "member_id": member_id, "claim_id": claim_id}
        if payload:
            request.update(payload)
        return self._post("preauth", request)

    def submit_claim(self, payload: dict) -> dict:
        return self._post("claim", payload)
