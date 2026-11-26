"""Document upload, retrieval, correction and re-processing."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, UPLOAD_DIR
from ..db import get_db
from ..models import Document, User, utcnow
from ..security import current_user, document_for_user, family_for_user
from ..serializers import document_out
from ..services.document_intel import UnsupportedFile, analyse_file, checksum, store_bytes, validate_file

router = APIRouter(prefix="/api", tags=["documents"])


class DocumentPatchIn(BaseModel):
    doc_type: str | None = None
    fields: dict[str, str] | None = None


@router.post("/documents/upload", status_code=201)
async def upload_document(
    family_id: int = Form(...),
    doc_type: str = Form("auto"),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    family_for_user(db, family_id, user)
    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type. Upload a PDF, PNG, JPG, WEBP, TIFF, TXT or audio file.",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024*1024)} MB.")
    try:
        validate_file(filename, file.content_type, len(content))
    except UnsupportedFile as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    digest = checksum(content)
    duplicate = (
        db.query(Document)
        .filter(Document.family_id == family_id, Document.sha256 == digest)
        .one_or_none()
    )
    if duplicate:
        return {
            "document": document_out(duplicate),
            "duplicate": True,
            "message": "This exact file is already in the household. Reused the existing copy.",
        }

    stored_name, path = store_bytes(content, suffix)
    hint = None if doc_type in ("auto", "", None) else doc_type
    document = Document(
        family_id=family_id,
        uploaded_by=user.id,
        original_filename=filename,
        stored_name=stored_name,
        mime=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        doc_type=doc_type if hint else "unknown",
        status="uploaded",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        result = analyse_file(path, filename, hint=hint)
        document.doc_type = result["doc_type"]
        document.classification_confidence = result["classification_confidence"]
        document.method = result["method"]
        document.pages = result["pages"]
        document.mean_ocr_confidence = result["mean_ocr_confidence"]
        document.raw_text = result["text"][:20000]
        fields = dict(result["fields"])
        fields["_lines"] = result["lines"]
        fields["_classification"] = {
            "confidence": result["classification_confidence"],
            "evidence": result["classification_evidence"],
        }
        document.fields = fields
        document.issues = result["issues"]
        document.status = "needs_review" if result["needs_review"] else "processed"
    except Exception as exc:  # keep the file, explain the failure
        document.status = "failed"
        document.issues = [f"Processing failed: {exc}"]
    db.add(document)
    db.commit()
    db.refresh(document)
    return {"document": document_out(document), "duplicate": False, "message": "Uploaded and processed."}


@router.get("/documents")
def list_documents(
    family_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if family_id:
        family_for_user(db, family_id, user)
        documents = (
            db.query(Document).filter(Document.family_id == family_id).order_by(Document.id.desc()).all()
        )
    else:
        from ..models import Family

        family_ids = [family.id for family in db.query(Family).filter(Family.owner_id == user.id).all()]
        documents = (
            db.query(Document).filter(Document.family_id.in_(family_ids)).order_by(Document.id.desc()).all()
            if family_ids
            else []
        )
    return {"documents": [document_out(document, include_fields=False) for document in documents]}


@router.get("/documents/{document_id}")
def get_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return document_out(document_for_user(db, document_id, user))


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = document_for_user(db, document_id, user)
    path = (UPLOAD_DIR / document.stored_name).resolve()
    if UPLOAD_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    return FileResponse(
        path,
        media_type=document.mime,
        filename=document.original_filename,
        headers={"Cache-Control": "private, no-store"},
    )


@router.patch("/documents/{document_id}")
def patch_document(
    document_id: int,
    payload: DocumentPatchIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    document = document_for_user(db, document_id, user)
    if payload.doc_type:
        document.doc_type = payload.doc_type
    if payload.fields:
        fields = dict(document.fields or {})
        for key, value in payload.fields.items():
            field = dict(fields.get(key) or {})
            field.update({"value": value, "confidence": 1.0, "source": "user", "status": "ok"})
            fields[key] = field
        document.fields = fields
    document.status = "needs_review" if document.issues else "processed"
    db.add(document)
    db.commit()
    db.refresh(document)
    return document_out(document)


@router.post("/documents/{document_id}/confirm")
def confirm_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = document_for_user(db, document_id, user)
    document.status = "confirmed"
    document.confirmed_at = utcnow()
    db.add(document)
    db.commit()
    db.refresh(document)
    return document_out(document)


@router.post("/documents/{document_id}/reprocess")
def reprocess_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = document_for_user(db, document_id, user)
    path = UPLOAD_DIR / document.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    result = analyse_file(path, document.original_filename, hint=document.doc_type)
    document.doc_type = result["doc_type"]
    document.classification_confidence = result["classification_confidence"]
    document.method = result["method"]
    document.pages = result["pages"]
    document.mean_ocr_confidence = result["mean_ocr_confidence"]
    document.raw_text = result["text"][:20000]
    fields = dict(result["fields"])
    fields["_lines"] = result["lines"]
    fields["_classification"] = {
        "confidence": result["classification_confidence"],
        "evidence": result["classification_evidence"],
    }
    document.fields = fields
    document.issues = result["issues"]
    document.status = "needs_review" if result["needs_review"] else "processed"
    db.add(document)
    db.commit()
    db.refresh(document)
    return document_out(document)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = document_for_user(db, document_id, user)
    try:
        (UPLOAD_DIR / document.stored_name).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(document)
    db.commit()
