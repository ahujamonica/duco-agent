"""CPT / ICD-10 reference tables and the code-inference helpers.

The assessment asks the agent to work out the codes that are missing from the
physiotherapy invoice, so this module keeps a small curated catalogue rather
than pretending to be a full code set. Matching is fuzzy (``difflib``) and
every hit carries a confidence score that the intake agent validates.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
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
    CodeEntry("S83.511A", "Sprain of anterior cruciate ligament of right knee, initial encounter", ("acl tear", "anterior cruciate ligament tear", "complete tear acl", "anterior cruciate ligament", "acl"), "injury"),
    CodeEntry("S83.241A", "Other tear of medial meniscus, current injury, right knee, initial encounter", ("medial meniscus tear", "meniscus tear", "medial meniscus", "meniscus"), "injury"),
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


# ---------------------------------------------------------------------------
# Extended catalogue for the dynamic platform.
#
# The original assessment scenario needed a dozen codes; a product that accepts
# arbitrary bills needs a broader working catalogue. It is still a curated
# subset (not a licensed CPT/ICD distribution) and every inferred code is
# returned with a confidence and must be reviewed.
# ---------------------------------------------------------------------------

CPT_CATALOG = CPT_CATALOG + (
    CodeEntry("99213", "Office or outpatient visit, low complexity", ("office visit", "consultation", "opd visit"), "professional"),
    CodeEntry("99214", "Office or outpatient visit, moderate complexity", ("detailed consultation",), "professional"),
    CodeEntry("27447", "Total knee arthroplasty", ("knee replacement", "total knee replacement", "tkr"), "professional"),
    CodeEntry("27130", "Total hip arthroplasty", ("hip replacement", "total hip replacement", "thr"), "professional"),
    CodeEntry("29827", "Arthroscopy, shoulder, with rotator cuff repair", ("rotator cuff repair", "shoulder arthroscopy"), "professional"),
    CodeEntry("43239", "Upper GI endoscopy with biopsy", ("endoscopy", "gastroscopy", "upper gi endoscopy"), "professional"),
    CodeEntry("45378", "Colonoscopy, diagnostic", ("colonoscopy",), "professional"),
    CodeEntry("47562", "Laparoscopic cholecystectomy", ("gallbladder removal", "cholecystectomy"), "professional"),
    CodeEntry("44970", "Laparoscopic appendectomy", ("appendectomy", "appendix removal"), "professional"),
    CodeEntry("59510", "Cesarean delivery with postpartum care", ("c section", "cesarean", "caesarean"), "professional"),
    CodeEntry("59400", "Vaginal delivery with prenatal and postpartum care", ("normal delivery", "vaginal delivery"), "professional"),
    CodeEntry("93000", "Electrocardiogram, routine with interpretation", ("ecg", "ekg", "electrocardiogram"), "diagnostic"),
    CodeEntry("93306", "Echocardiography, complete", ("echo", "echocardiogram"), "diagnostic"),
    CodeEntry("71046", "Chest X-ray, two views", ("chest x ray", "chest xray", "cxr"), "diagnostic"),
    CodeEntry("72148", "MRI lumbar spine without contrast", ("mri lumbar", "mri spine", "lumbar mri"), "diagnostic"),
    CodeEntry("70551", "MRI brain without contrast", ("mri brain", "brain mri"), "diagnostic"),
    CodeEntry("71260", "CT thorax with contrast", ("ct chest", "ct thorax"), "diagnostic"),
    CodeEntry("74177", "CT abdomen and pelvis with contrast", ("ct abdomen", "ct pelvis"), "diagnostic"),
    CodeEntry("80053", "Comprehensive metabolic panel", ("metabolic panel", "cmp", "lft kft"), "diagnostic"),
    CodeEntry("85025", "Complete blood count with differential", ("cbc", "complete blood count", "haemogram"), "diagnostic"),
    CodeEntry("80061", "Lipid panel", ("lipid profile", "cholesterol test"), "diagnostic"),
    CodeEntry("83036", "Glycated haemoglobin (HbA1c)", ("hba1c", "glycated haemoglobin"), "diagnostic"),
    CodeEntry("36415", "Collection of venous blood by venipuncture", ("blood collection", "venipuncture", "sample collection"), "diagnostic"),
    CodeEntry("12002", "Simple repair of superficial wound", ("sutures", "wound repair", "laceration repair"), "professional"),
    CodeEntry("11042", "Debridement of skin and subcutaneous tissue", ("debridement", "wound cleaning"), "professional"),
    CodeEntry("20610", "Arthrocentesis, major joint, with injection", ("joint injection", "knee injection", "steroid injection"), "professional"),
    CodeEntry("29125", "Application of short arm splint", ("splint", "plaster"), "professional"),
    CodeEntry("73630", "X-ray of foot, complete", ("foot x ray", "xray foot"), "diagnostic"),
    CodeEntry("73562", "X-ray of knee, three views", ("knee x ray", "xray knee"), "diagnostic"),
    CodeEntry("77067", "Screening mammography, bilateral", ("mammogram", "mammography"), "diagnostic"),
    CodeEntry("90471", "Immunisation administration", ("vaccination", "immunisation", "vaccine"), "professional"),
    CodeEntry("99396", "Preventive medicine visit, established patient", ("annual health check", "preventive checkup", "master health check"), "professional"),
    CodeEntry("97530", "Therapeutic activities, each 15 minutes", ("therapeutic activities", "functional training"), "therapy"),
    CodeEntry("97116", "Gait training, each 15 minutes", ("gait training", "walking training"), "therapy"),
    CodeEntry("97012", "Application of mechanical traction", ("traction", "mechanical traction", "home traction"), "therapy"),
    CodeEntry("97032", "Electrical stimulation, manual", ("electrical stimulation", "ift", "interferential"), "therapy"),
    CodeEntry("36430", "Blood transfusion service", ("blood transfusion",), "professional"),
    CodeEntry("99291", "Critical care, first hour", ("icu care", "critical care"), "professional"),
    CodeEntry("31575", "Laryngoscopy, flexible", ("laryngoscopy",), "professional"),
    CodeEntry("92557", "Comprehensive audiometry", ("hearing test", "audiometry"), "diagnostic"),
    CodeEntry("95910", "Nerve conduction studies", ("nerve conduction", "ncv"), "diagnostic"),
)

ICD_CATALOG = ICD_CATALOG + (
    CodeEntry("M17.11", "Unilateral primary osteoarthritis, right knee", ("knee osteoarthritis", "osteoarthritis knee"), "musculoskeletal"),
    CodeEntry("M17.12", "Unilateral primary osteoarthritis, left knee", ("left knee osteoarthritis",), "musculoskeletal"),
    CodeEntry("M23.221", "Derangement of posterior horn of medial meniscus", ("meniscus derangement", "torn meniscus", "medial meniscus", "meniscus"), "injury"),
    CodeEntry("M75.41", "Impingement syndrome of right shoulder", ("shoulder impingement",), "musculoskeletal"),
    CodeEntry("K80.20", "Calculus of gallbladder without cholecystitis", ("gallstones", "gallbladder stones"), "digestive"),
    CodeEntry("K35.80", "Unspecified acute appendicitis", ("appendicitis",), "digestive"),
    CodeEntry("I10", "Essential (primary) hypertension", ("hypertension", "high blood pressure"), "circulatory"),
    CodeEntry("E11.9", "Type 2 diabetes mellitus without complications", ("type 2 diabetes", "diabetes"), "endocrine"),
    CodeEntry("J45.909", "Unspecified asthma, uncomplicated", ("asthma",), "respiratory"),
    CodeEntry("J18.9", "Pneumonia, unspecified organism", ("pneumonia",), "respiratory"),
    CodeEntry("N39.0", "Urinary tract infection, site not specified", ("urinary tract infection", "uti"), "genitourinary"),
    CodeEntry("K21.9", "Gastro-oesophageal reflux disease without oesophagitis", ("acid reflux", "gerd", "acidity"), "digestive"),
    CodeEntry("F41.1", "Generalised anxiety disorder", ("anxiety", "anxiety disorder"), "mental"),
    CodeEntry("F32.9", "Major depressive disorder, single episode, unspecified", ("depression",), "mental"),
    CodeEntry("G43.909", "Migraine, unspecified, not intractable", ("migraine",), "nervous"),
    CodeEntry("M54.16", "Radiculopathy, lumbar region", ("lumbar radiculopathy", "sciatica"), "musculoskeletal"),
    CodeEntry("M51.26", "Other intervertebral disc displacement, lumbar region", ("disc prolapse", "slipped disc", "disc bulge"), "musculoskeletal"),
    CodeEntry("S82.001A", "Fracture of right patella, initial encounter", ("patella fracture", "knee cap fracture"), "injury"),
    CodeEntry("S72.001A", "Fracture of neck of right femur, initial encounter", ("hip fracture", "femur neck fracture"), "injury"),
    CodeEntry("O80", "Encounter for full-term uncomplicated delivery", ("full term delivery", "normal delivery"), "pregnancy"),
    CodeEntry("Z34.90", "Encounter for supervision of normal pregnancy, unspecified", ("pregnancy supervision", "antenatal"), "pregnancy"),
    CodeEntry("C50.911", "Malignant neoplasm of unspecified site of right female breast", ("breast cancer",), "neoplasm"),
    CodeEntry("M79.604", "Pain in right leg", ("leg pain",), "musculoskeletal"),
    CodeEntry("R51.9", "Headache, unspecified", ("headache",), "symptoms"),
    CodeEntry("R07.9", "Chest pain, unspecified", ("chest pain",), "symptoms"),
    CodeEntry("Z00.00", "Encounter for general adult medical examination", ("general examination", "health checkup"), "status"),
    CodeEntry("H25.9", "Unspecified age-related cataract", ("cataract",), "eye"),
    CodeEntry("H52.4", "Presbyopia", ("reading glasses", "presbyopia"), "eye"),
    CodeEntry("J06.9", "Acute upper respiratory infection", ("common cold", "upper respiratory infection", "uri"), "respiratory"),
    CodeEntry("A09", "Infectious gastroenteritis and colitis", ("gastroenteritis", "stomach infection"), "infectious"),
)


def suggest_cpt(description: str, limit: int = 3) -> list[dict]:
    """Return the best CPT candidates with their match confidence."""
    scored = sorted(((_score(description, entry), entry) for entry in CPT_CATALOG), reverse=True, key=lambda item: item[0])
    out = []
    for score, entry in scored[:limit]:
        if score < 0.45:
            continue
        out.append(
            {
                "code": entry.code,
                "description": entry.description,
                "confidence": round(min(score, 0.97), 3),
                "category": entry.category,
            }
        )
    return out


def suggest_icd(text: str, limit: int = 3) -> list[dict]:
    """Suggest ICD-10 candidates from clinical prose.

    Radiology and discharge narratives are long and fuzzy matching on the whole
    paragraph invents diagnoses, so a candidate must be supported by an alias
    actually present in the text (or a very close phrase match) and is scored
    on that evidence only.
    """
    windows = [text]
    windows += [part for part in re.split(r"[.;\n]", text) if len(part.strip()) > 8]
    words = text.split()
    windows += [" ".join(words[i : i + 10]) for i in range(0, max(1, len(words)), 6)]
    normalised_windows = [_normalise(window) for window in windows if window.strip()]

    scored_map: dict[str, float] = {}
    for entry in ICD_CATALOG:
        aliases = [_normalise(alias) for alias in (entry.description, *entry.aliases)]
        best = 0.0
        for window in normalised_windows:
            for alias in aliases:
                if len(alias) >= 4 and alias in window:
                    best = max(best, 0.95 if len(alias.split()) > 1 else 0.86)
                    continue
                # Short single-word aliases are only accepted on a close match.
                if len(alias.split()) == 1 and len(alias) >= 6:
                    tokens = set(window.split())
                    if alias in tokens:
                        best = max(best, 0.82)
        if best > 0:
            scored_map[entry.code] = min(0.95, best)
    scored = sorted(
        ((score, next(entry for entry in ICD_CATALOG if entry.code == code)) for code, score in scored_map.items()),
        reverse=True,
        key=lambda item: item[0],
    )
    out = []
    for score, entry in scored[:limit]:
        if score < 0.6:
            continue
        out.append(
            {
                "code": entry.code,
                "description": entry.description,
                "confidence": round(min(score, 0.95), 3),
                "category": entry.category,
            }
        )
    return out


def code_category(code: str) -> str:
    for entry in CPT_CATALOG:
        if entry.code == code:
            return entry.category
    return "professional"
