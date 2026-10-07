from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, Writer, audit, get_site
from app.models import BankAccount, ImportBatch
from app.services import imports as svc
from app.services.bank_parsers import StatementParseError

router = APIRouter(prefix="/api", tags=["imports"])

MAX_UPLOAD = 15 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Dosya çok büyük (en fazla 15 MB)")
    if not data:
        raise HTTPException(400, "Dosya boş")
    return data


@router.post("/imports/bank")
async def upload_bank_statement(db: DB, user: Writer, file: UploadFile = File(...), site_id: int | None = Form(None)):
    if site_id is not None:
        get_site(db, user, site_id)
    data = await _read(file)
    try:
        result = svc.import_bank_statement(db, data, file.filename or "ekstre.xlsx", user_id=user.id, site_id=site_id)
    except svc.UnknownIbanError as e:
        db.rollback()
        st = e.statement
        return JSONResponse(status_code=409, content={
            "detail": str(e), "code": "unknown_iban", "iban": st.iban, "account_holder": st.account_holder,
            "bank_name": st.bank_name, "period_start": st.period_start.isoformat() if st.period_start else None,
            "period_end": st.period_end.isoformat() if st.period_end else None, "rows": len(st.transactions),
        })
    except (svc.ImportError_, StatementParseError, ValueError) as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    get_site(db, user, result["site_id"])
    if not result.get("already_imported"):
        audit(db, user, "import", "bank_statement", result["import_id"], result["site_id"],
              {"file": file.filename, "new": result["new"], "duplicates": result["duplicates"]})
    db.commit()
    return result


@router.post("/imports/tracking/preview")
async def tracking_preview(
    db: DB, user: Writer, file: UploadFile = File(...), site_id: int | None = Form(None),
    site_name: str | None = Form(None), start_year: int | None = Form(None), cutoff: str | None = Form(None),
    sheet: str | None = Form(None),
):
    if site_id is not None:
        get_site(db, user, site_id)
    data = await _read(file)
    try:
        return svc.preview_tracking(db, data, site_id=site_id, site_name=site_name, start_year=start_year,
                                    cutoff=cutoff or None, sheet=sheet or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/imports/tracking/commit")
async def tracking_commit(
    db: DB, user: Writer, file: UploadFile = File(...), site_id: int | None = Form(None),
    site_name: str | None = Form(None), site_code: str | None = Form(None), start_year: int | None = Form(None),
    cutoff: str | None = Form(None), sheet: str | None = Form(None),
):
    if site_id is not None:
        get_site(db, user, site_id)
    data = await _read(file)
    try:
        result = svc.commit_tracking(db, data, file.filename or "takip.xlsx", user_id=user.id, site_id=site_id,
                                     site_name=site_name, site_code=site_code, start_year=start_year,
                                     cutoff=cutoff or None, sheet=sheet or None)
    except (svc.ImportError_, ValueError) as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    audit(db, user, "import", "tracking_excel", result["import_id"], result["site_id"],
          {"file": file.filename, "cutoff": result["cutoff"]})
    db.commit()
    return result


@router.get("/sites/{site_id}/imports")
def list_imports(site_id: int, db: DB, user: CurrentUser):
    get_site(db, user, site_id)
    q = select(ImportBatch).where(ImportBatch.site_id == site_id).order_by(ImportBatch.id.desc())
    return [{"id": b.id, "kind": b.kind, "file_name": b.file_name, "bank_code": b.bank_code,
             "period_start": b.period_start, "period_end": b.period_end, "stats": b.stats,
             "uploaded_at": b.uploaded_at} for b in db.scalars(q)]


@router.get("/sites/{site_id}/coverage")
def coverage(site_id: int, db: DB, user: CurrentUser):
    """Hesap başına yüklenmiş ekstre aralıkları ve bakiye zincirindeki boşluklar."""
    get_site(db, user, site_id)
    out = []
    for acc in db.scalars(select(BankAccount).where(BankAccount.site_id == site_id)):
        out.append({"bank_account_id": acc.id, "iban": acc.iban, "bank_name": acc.bank_name,
                    "statements": svc.account_coverage(db, acc.id), "gaps": svc.account_gaps(db, acc.id)})
    return out
