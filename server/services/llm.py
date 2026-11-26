"""Optional LLM enrichment for document extraction.

The deterministic pipeline always runs and is the source of truth. When
``DUCO_LLM_API_KEY`` is configured, an OpenAI-compatible chat-completions
endpoint is asked for a second opinion on the document type and on fields the
local extractor left missing or uncertain. The response is validated and any
suggestion is marked as low-trust for human review. With no key — the default
in this prototype — nothing is called and no result is invented.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from ..config import LLM_BASE_URL, LLM_ENABLED, LLM_MODEL

SYSTEM_PROMPT = (
    "You extract structured data from health-insurance documents. Reply with one JSON object only: "
    '{"doc_type": one of policy|invoice|estimate|radiology|prescription|discharge|transcript|unknown, '
    '"fields": {<field>: {"value": <string|number>, "confidence": 0-1, "evidence": <short quote>}}, '
    '"notes": [<string>]}. Only include fields present in the text. Do not guess a diagnosis or a code. '
    "Never invent a policy term."
)

ALLOWED_TYPES = {"policy", "invoice", "estimate", "radiology", "prescription", "discharge", "transcript", "unknown"}


def configured() -> bool:
    return LLM_ENABLED


def _call(prompt: str) -> dict | None:
    body = json.dumps(
        {
            "model": LLM_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt[:14000]},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {__import__('os').environ.get('DUCO_LLM_API_KEY', '')}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed config URL
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    return json.loads(content)


def enrich(text: str, doc_type: str, confidence: float, fields: dict[str, dict]) -> dict:
    """Return ``{used, error, doc_type, fields, notes}``; never raises."""
    result = {"used": False, "error": None, "doc_type": None, "fields": {}, "notes": []}
    if not configured() or not text.strip():
        return result
    known = ", ".join(sorted(fields.keys()))
    prompt = (
        f"Declared document type: {doc_type} (local confidence {confidence:.2f}).\n"
        f"Fields already extracted: {known}.\n"
        f"Document text follows between markers.\n---BEGIN---\n{text}\n---END---"
    )
    try:
        parsed = _call(prompt)
        if not isinstance(parsed, dict):
            raise ValueError("response was not an object")
        suggested_type = str(parsed.get("doc_type") or "").lower()
        if suggested_type in ALLOWED_TYPES:
            result["doc_type"] = suggested_type
        raw_fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
        for key, value in raw_fields.items():
            if not isinstance(value, dict) or value.get("value") in (None, ""):
                continue
            existing = fields.get(key) or {}
            existing_confidence = float(existing.get("confidence") or 0)
            # Never overwrite a confident deterministic value.
            if existing.get("value") not in (None, "") and existing_confidence >= 0.7:
                continue
            if existing.get("status") == "missing" or not existing:
                result["fields"][str(key)] = {
                    "value": value.get("value"),
                    "confidence": max(0.35, min(0.85, float(value.get("confidence") or 0.55))),
                    "evidence": str(value.get("evidence") or "suggested by the optional extraction model")[:400],
                }
        notes = parsed.get("notes")
        if isinstance(notes, list):
            result["notes"] = [str(note)[:300] for note in notes[:5]]
        result["used"] = True
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return result
