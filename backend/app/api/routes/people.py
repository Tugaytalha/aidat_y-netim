from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, Writer, audit, get_site
from app.models import Person, Unit, UnitOccupancy
from app.services.matching.normalize import normalize_name

router = APIRouter(prefix="/api", tags=["people"])


def person_out(p: Person) -> dict:
    return {"id": p.id, "full_name": p.full_name, "phone": p.phone, "email": p.email, "notes": p.notes,
            "units": [{"occupancy_id": o.id, "unit_id": o.unit_id, "code": o.unit.code, "role": o.role,
                       "is_primary": o.is_primary} for o in p.occupancies]}


@router.get("/sites/{site_id}/persons")
def list_persons(site_id: int, db: DB, user: CurrentUser):
    get_site(db, user, site_id)
    q = (select(Person).where(Person.site_id == site_id).order_by(Person.full_name)
         .options(selectinload(Person.occupancies).selectinload(UnitOccupancy.unit)))
    return [person_out(p) for p in db.scalars(q)]


class PersonIn(BaseModel):
    full_name: str
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    unit_id: int | None = None
    role: str = "owner"
    is_primary: bool = True


@router.post("/sites/{site_id}/persons", status_code=201)
def create_person(site_id: int, body: PersonIn, db: DB, user: Writer):
    get_site(db, user, site_id)
    p = Person(site_id=site_id, full_name=body.full_name.strip(), normalized_name=normalize_name(body.full_name),
               phone=body.phone, email=body.email, notes=body.notes)
    db.add(p)
    db.flush()
    if body.unit_id:
        _link(db, body.unit_id, p, body.role, body.is_primary)
    audit(db, user, "create", "person", p.id, site_id, {"name": p.full_name})
    db.commit()
    db.refresh(p)
    return person_out(p)


class PersonPatch(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


@router.patch("/persons/{person_id}")
def update_person(person_id: int, body: PersonPatch, db: DB, user: Writer):
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(404, "Kişi bulunamadı")
    get_site(db, user, p.site_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    if "full_name" in data:
        p.normalized_name = normalize_name(p.full_name)
    audit(db, user, "update", "person", p.id, p.site_id, data)
    db.commit()
    db.refresh(p)
    return person_out(p)


def _link(db, unit_id: int, p: Person, role: str, is_primary: bool) -> UnitOccupancy:
    unit = db.get(Unit, unit_id)
    if not unit or unit.block.site_id != p.site_id:
        raise HTTPException(400, "Daire bu siteye ait değil")
    if is_primary:
        for o in db.scalars(select(UnitOccupancy).where(UnitOccupancy.unit_id == unit_id)):
            o.is_primary = False
    o = UnitOccupancy(unit_id=unit_id, person_id=p.id, role=role, is_primary=is_primary, start_date=date.today())
    db.add(o)
    db.flush()
    return o


class OccupancyIn(BaseModel):
    person_id: int | None = None
    full_name: str | None = None
    role: str = "owner"
    is_primary: bool = True


@router.post("/units/{unit_id}/occupancies", status_code=201)
def add_occupancy(unit_id: int, body: OccupancyIn, db: DB, user: Writer):
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(404, "Daire bulunamadı")
    site_id = unit.block.site_id
    get_site(db, user, site_id)
    if body.person_id:
        p = db.get(Person, body.person_id)
        if not p or p.site_id != site_id:
            raise HTTPException(400, "Kişi bulunamadı")
    elif body.full_name:
        key = normalize_name(body.full_name)
        p = db.scalar(select(Person).where(Person.site_id == site_id, Person.normalized_name == key))
        if p is None:
            p = Person(site_id=site_id, full_name=body.full_name.strip(), normalized_name=key)
            db.add(p)
            db.flush()
    else:
        raise HTTPException(400, "Kişi seçin ya da ad yazın")
    o = _link(db, unit_id, p, body.role, body.is_primary)
    audit(db, user, "create", "occupancy", o.id, site_id, {"unit": unit.code, "person": p.full_name, "role": body.role})
    db.commit()
    return {"id": o.id, "person_id": p.id, "name": p.full_name, "role": o.role, "is_primary": o.is_primary}


class OccupancyPatch(BaseModel):
    role: str | None = None
    is_primary: bool | None = None
    end_date: date | None = None


@router.patch("/occupancies/{occ_id}")
def update_occupancy(occ_id: int, body: OccupancyPatch, db: DB, user: Writer):
    o = db.get(UnitOccupancy, occ_id)
    if not o:
        raise HTTPException(404, "Kayıt bulunamadı")
    get_site(db, user, o.unit.block.site_id)
    if body.is_primary:
        for other in db.scalars(select(UnitOccupancy).where(UnitOccupancy.unit_id == o.unit_id)):
            other.is_primary = False
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    db.commit()
    return {"id": o.id, "role": o.role, "is_primary": o.is_primary}


@router.delete("/occupancies/{occ_id}", status_code=204)
def delete_occupancy(occ_id: int, db: DB, user: Writer):
    o = db.get(UnitOccupancy, occ_id)
    if not o:
        raise HTTPException(404, "Kayıt bulunamadı")
    site_id = o.unit.block.site_id
    get_site(db, user, site_id)
    audit(db, user, "delete", "occupancy", o.id, site_id, {"unit_id": o.unit_id, "person_id": o.person_id})
    db.delete(o)
    db.commit()
