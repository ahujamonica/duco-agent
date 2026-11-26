"""CPT / ICD-10 reference tables and the code-inference helpers.

The assessment asks the agent to work out the codes that are missing from the
physiotherapy invoice, so this module keeps a small curated catalogue rather
than pretending to be a full code set. Matching is fuzzy (``difflib``) and
every hit carries a confidence score that the intake agent validates.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional


@dataclass(frozen=True)
class CodeEntry:
    code: str
    description: str
    aliases: tuple[str, ...] = ()
    category: str = "professional"


CPT_CATALOG: tuple[CodeEntry, ...] = (
    CodeEntry("97161", "Physical therapy evaluation, low complexity", ("pt evaluation", "physiotherapy evaluation", "physical therapy assessment"), "therapy"),
    CodeEntry("97162", "Physical therapy evaluation, moderate complexity", ("pt evaluation moderate",), "therapy"),
    CodeEntry("97110", "Therapeutic exercises, each 15 minutes", ("therapeutic exercise", "exercises", "therapeutic exercises"), "therapy"),
    CodeEntry("97140", "Manual therapy techniques", ("manual therapy", "soft tissue mobilisation"), "therapy"),
    CodeEntry("97035", "Application of ultrasound, each 15 minutes", ("ultrasound", "therapeutic ultrasound"), "therapy"),
    CodeEntry("97014", "Electrical stimulation, unattended", ("ift", "interferential therapy", "electrical stimulation"), "therapy"),
    CodeEntry("29888", "Arthroscopically aided ACL reconstruction", ("acl reconstruction", "anterior cruciate ligament reconstruction"), "professional"),
    CodeEntry("29881", "Arthroscopy, knee, surgical; with meniscectomy", ("meniscectomy", "arthroscopy knee meniscectomy"), "professional"),
    CodeEntry("29870", "Arthroscopy, knee, diagnostic", ("diagnostic arthroscopy",), "professional"),
    CodeEntry("73721", "MRI, lower extremity joint without contrast", ("mri knee", "mri lower extremity"), "diagnostic"),
    CodeEntry("E0114", "Crutches, underarm, aluminium", ("crutches",), "equipment"),
    CodeEntry("L1832", "Knee orthosis, adjustable", ("knee brace", "knee orthosis"), "equipment"),
)

ICD_CATALOG: tuple[CodeEntry, ...] = (
    CodeEntry("S83.511A", "Sprain of anterior cruciate ligament of right knee, initial encounter", ("acl tear", "anterior cruciate ligament tear", "complete tear acl"), "injury"),
    CodeEntry("S83.241A", "Other tear of medial meniscus, current injury, right knee, initial encounter", ("medial meniscus tear", "meniscus tear"), "injury"),
    CodeEntry("M54.5", "Low back pain", ("low back pain", "chronic back pain", "lumbago"), "musculoskeletal"),
    CodeEntry("M54.41", "Lumbago with sciatica, right side", ("sciatica",), "musculoskeletal"),
    CodeEntry("M25.561", "Pain in right knee", ("knee pain",), "musculoskeletal"),
    CodeEntry("Z96.651", "Presence of right artificial knee joint", ("knee replacement history",), "status"),
)

# Service descriptions on the invoice that must be mapped to codes because the
# printed document does not carry them.
INFERRED_THERAPY_LINES = {
    "Physical Therapy Evaluation": ("97161", 0.94),
    "Therapeutic Exercise (Ultrasound + IFT)": ("97110", 0.88),
    "Home traction equipment (sale)": (None, 0.0),
}

# Clinical narrative -> diagnosis codes used by the coding agent.
DIAGNOSIS_HINTS = {
    "acl": "S83.511A",
    "anterior cruciate": "S83.511A",
    "meniscus": "S83.241A",
    "back pain": "M54.5",
    "lumbago": "M54.5",
    "physiotherapy": "M54.5",
}


def _normalise(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").replace("(", " ").replace(")", " ").split())


def _score(query: str, entry: CodeEntry) -> float:
    q = _normalise(query)
    candidates = [_normalise(entry.description), *(_normalise(a) for a in entry.aliases)]
    best = 0.0
    for candidate in candidates:
        ratio = SequenceMatcher(None, q, candidate).ratio()
        # Reward full containment of the alias in the query, which is the usual
        # shape of a billing description ("Therapeutic Exercise ...").
        if candidate and candidate in q:
            ratio = max(ratio, 0.90)
        best = max(best, ratio)
    return round(best, 3)


def lookup_cpt(description: str, catalog: Iterable[CodeEntry] = CPT_CATALOG) -> tuple[Optional[str], float]:
    """Best CPT match for a free-text service description."""
    return _best_match(description, catalog)


def lookup_icd(text: str, catalog: Iterable[CodeEntry] = ICD_CATALOG) -> tuple[Optional[str], float]:
    """Best ICD-10 match for a narrative fragment."""
    return _best_match(text, catalog)


def _best_match(description: str, catalog: Iterable[CodeEntry]) -> tuple[Optional[str], float]:
    scored = sorted(((_score(description, entry), entry) for entry in catalog), key=lambda item: item[0], reverse=True)
    if not scored:
        return None, 0.0
    score, entry = scored[0]
    if score < 0.55:
        return None, score
    return entry.code, score


def describe(code: str) -> str:
    for entry in (*CPT_CATALOG, *ICD_CATALOG):
        if entry.code == code:
            return entry.description
    return "Unknown code"


def infer_diagnosis_codes(narrative: str) -> list[tuple[str, float]]:
    """Return diagnosis codes suggested by clinical text, best first."""
    text = _normalise(narrative)
    hits: dict[str, float] = {}
    for hint, code in DIAGNOSIS_HINTS.items():
        if hint in text:
            hits[code] = max(hits.get(code, 0.0), 0.92 if " " in hint else 0.78)
    return sorted(hits.items(), key=lambda item: item[1], reverse=True)
