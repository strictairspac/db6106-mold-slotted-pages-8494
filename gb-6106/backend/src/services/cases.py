from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import insert, select

from src.domain import scenario
from src.models.cases import cases
from src.models.redactions import note_redactions
from .audit import record


def _with_redaction_status(db, entry):
    pending = db.scalar(
        select(note_redactions.c.id).where(
            note_redactions.c.case_id == entry["id"],
            note_redactions.c.status == "pending",
        ).limit(1)
    )
    if pending is not None:
        entry["redaction_status"] = "pending"
        return entry
    status = db.scalar(
        select(note_redactions.c.status)
        .where(note_redactions.c.case_id == entry["id"])
        .order_by(note_redactions.c.id.desc())
        .limit(1)
    )
    entry["redaction_status"] = status
    return entry


def get(db, case_id):
    entry = db.execute(select(cases).where(cases.c.id == case_id)).mappings().first()
    if entry is None:
        raise HTTPException(404, "资料不存在")
    return _with_redaction_status(db, dict(entry))


def list_entries(db):
    entries = [dict(row) for row in db.execute(select(cases).order_by(cases.c.id.desc()).limit(100)).mappings()]
    ids = [entry["id"] for entry in entries]
    latest_status = {}
    if ids:
        redaction_rows = db.execute(
            select(note_redactions.c.case_id, note_redactions.c.status)
            .where(note_redactions.c.case_id.in_(ids))
            .order_by(note_redactions.c.id.desc())
        ).all()
        for case_id, status in redaction_rows:
            latest_status.setdefault(case_id, status)
    for entry in entries:
        status = latest_status.get(entry["id"])
        entry["redaction_status"] = status
        if status == "pending":
            # Never serialize the original remark while its durable clear is
            # still unfinished.  Detail reads recover the clear before responding.
            entry["payload"] = {
                "redaction": {
                    "status": "pending",
                    "message": "该单备注正在清除，完成后恢复查阅。",
                }
            }
    return entries


def create(db, data, actor):
    validator = getattr(scenario, "validate", None)
    if validator is not None:
        try:
            validator(data.payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    change = db.execute(insert(cases).values(**data.model_dump(), code=f"CASE-{uuid4().hex[:12].upper()}", created_by=actor))
    case_id = change.inserted_primary_key[0]
    record(db, "create_case", actor, "case", case_id)
    return get(db, case_id)
