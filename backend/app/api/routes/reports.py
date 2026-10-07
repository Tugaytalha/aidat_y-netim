from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_site
from app.models import AuditLog, User, Unit
from app.services.common import add_months, period_of
from app.services.ledger import unit_statement
from app.services.reports import excel_export
from app.services.reports.grid import dashboard, debtors, payment_grid, reconciliation

router = APIRouter(prefix="/api", tags=["reports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


def _range(start: str | None, end: str | None) -> tuple[str, str]:
    end = end or period_of(date.today())
    start = start or add_months(end, -11)
    if start > end:
        raise HTTPException(400, "Başlangıç bitişten sonra olamaz")
    return start, end


@router.get("/sites/{site_id}/dashboard")
def get_dashboard(site_id: int, db: DB, user: CurrentUser, period: str | None = None):
    get_site(db, user, site_id)
    return dashboard(db, site_id, period)


@router.get("/sites/{site_id}/grid")
def get_grid(site_id: int, db: DB, user: CurrentUser, start: str | None = None, end: str | None = None):
    get_site(db, user, site_id)
    return payment_grid(db, site_id, *_range(start, end))


@router.get("/sites/{site_id}/debtors")
def get_debtors(site_id: int, db: DB, user: CurrentUser):
    get_site(db, user, site_id)
    return debtors(db, site_id)


@router.get("/sites/{site_id}/reconciliation")
def get_reconciliation(site_id: int, db: DB, user: CurrentUser):
    get_site(db, user, site_id)
    return reconciliation(db, site_id)


def _unit(db, user, unit_id: int) -> Unit:
    u = db.get(Unit, unit_id)
    if not u:
        raise HTTPException(404, "Daire bulunamadı")
    get_site(db, user, u.block.site_id)
    return u


@router.get("/units/{unit_id}/statement")
def get_statement(unit_id: int, db: DB, user: CurrentUser):
    u = _unit(db, user, unit_id)
    return {"unit_id": u.id, "code": u.code, "entries": unit_statement(db, unit_id)}


@router.get("/sites/{site_id}/export/grid.xlsx")
def export_grid(site_id: int, db: DB, user: CurrentUser, start: str | None = None, end: str | None = None):
    site = get_site(db, user, site_id)
    s, e = _range(start, end)
    return _xlsx(excel_export.grid_workbook(site.name, payment_grid(db, site_id, s, e)), f"{site.name} tahsilat {s}_{e}.xlsx")


@router.get("/sites/{site_id}/export/debtors.xlsx")
def export_debtors(site_id: int, db: DB, user: CurrentUser):
    site = get_site(db, user, site_id)
    return _xlsx(excel_export.debtors_workbook(site.name, debtors(db, site_id)), f"{site.name} borçlular.xlsx")


@router.get("/units/{unit_id}/export/statement.xlsx")
def export_statement(unit_id: int, db: DB, user: CurrentUser):
    u = _unit(db, user, unit_id)
    site = get_site(db, user, u.block.site_id)
    return _xlsx(excel_export.statement_workbook(site.name, u.code, unit_statement(db, unit_id)), f"{site.name} {u.code} ekstre.xlsx")


@router.get("/sites/{site_id}/audit")
def get_audit(site_id: int, db: DB, user: CurrentUser, limit: int = 200):
    get_site(db, user, site_id)
    names = {u.id: u.full_name or u.email for u in db.scalars(select(User))}
    q = select(AuditLog).where(AuditLog.site_id == site_id).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    return [{"id": a.id, "user": names.get(a.user_id), "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "data": a.data, "created_at": a.created_at} for a in db.scalars(q)]
