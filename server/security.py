"""Authentication, password hashing and ownership checks.

Security posture (documented in docs/SECURITY.md):
* passwords: PBKDF2-HMAC-SHA256 with a per-user salt, 240k iterations (stdlib);
* sessions: signed JWT bearer tokens with an expiry;
* authorisation: every family, document, policy and case read/write checks that
  the signed-in user owns the family; medical files are never served from a
  public directory and never addressed by their on-disk name.
Gaps left for production: field-level encryption, key management, rate
limiting, audit logging on reads, consent records and HTTPS termination.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import JWT_ALGORITHM, JWT_SECRET, TOKEN_TTL_HOURS
from .db import get_db
from .models import Case, Document, Family, Policy, User

PBKDF2_ROUNDS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ROUNDS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


def create_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub", "0"))
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Your session expired. Sign in again.") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid session token.") from exc
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user


def family_for_user(db: Session, family_id: int, user: User) -> Family:
    family = db.get(Family, family_id)
    if not family or family.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Family not found.")
    return family


def case_for_user(db: Session, case_id: int, user: User) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")
    family = db.get(Family, case.family_id)
    if not family or family.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Case not found.")
    return case


def document_for_user(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    family = db.get(Family, document.family_id)
    if not family or family.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def policy_for_user(db: Session, policy_id: int, user: User) -> Policy:
    policy = db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    family = db.get(Family, policy.family_id)
    if not family or family.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return policy
