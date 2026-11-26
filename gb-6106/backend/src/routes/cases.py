from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select

from src.config.resources import engine
from src.controllers.access import identity, operator
from src.controllers.workbench import clear_note, new_case, new_run
from src.models.redactions import note_redactions
from src.schemas.cases import CaseEntry, CaseInput
from src.schemas.redactions import ClearNoteInput, RedactionEntry
from src.schemas.runs import RunEntry, RunInput
from src.services import cases, redactions

router = APIRouter(prefix="/cases", tags=["Cases"])


@router.get("", response_model=list[CaseEntry], dependencies=[Depends(identity)])
def list_cases():
    # Recovery is idempotent.  A crashed clear therefore disappears as soon
    # as the change-order page is loaded by an authenticated visitor.
    redactions.recover_pending_safe()
    with engine.connect() as db:
        return cases.list_entries(db)


@router.get("/{case_id}", response_model=CaseEntry, dependencies=[Depends(identity)])
def case_detail(case_id: int):
    redactions.recover_case_now(case_id)
    with engine.connect() as db:
        entry = cases.get(db, case_id)
        if entry.get("redaction_status") == redactions.PENDING:
            raise HTTPException(409, "该单正在清除整条备注，完成后才恢复查阅")
        return entry


@router.post("", response_model=CaseEntry, status_code=201)
def register(form: CaseInput, user=Depends(operator)):
    return new_case(form, user)


@router.post("/clear", response_model=RedactionEntry, include_in_schema=False)
@router.post("/clear-note", response_model=RedactionEntry)
def clear_note_by_order(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)


@router.post("/redact", response_model=RedactionEntry, include_in_schema=False)
def redact_alias(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)


@router.post("/redact-note", response_model=RedactionEntry, include_in_schema=False)
def redact_note_alias(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)


@router.post("/notes/clear", response_model=RedactionEntry, include_in_schema=False)
def clear_note_collection_alias(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)


@router.post("/{case_id}/clear-note", response_model=RedactionEntry)
def clear_note_for_case(
    case_id: int,
    form: ClearNoteInput | None = Body(default=None),
    key: str | None = Query(default=None),
    record_key: str | None = Query(default=None),
    history_no: str | None = Query(default=None),
    user=Depends(operator),
):
    query_key = key or record_key or history_no
    target = form or ClearNoteInput(case_id=case_id, key=query_key)
    target.case_id = case_id
    if query_key and not target.target_key():
        target.key = query_key
    return clear_note(target, user)


@router.post("/{case_id}/redact", response_model=RedactionEntry, include_in_schema=False)
@router.post("/{case_id}/redactions", response_model=RedactionEntry)
def redact_for_case(
    case_id: int,
    form: ClearNoteInput | None = Body(default=None),
    key: str | None = Query(default=None),
    record_key: str | None = Query(default=None),
    history_no: str | None = Query(default=None),
    user=Depends(operator),
):
    return clear_note_for_case(case_id, form, key, record_key, history_no, user)


@router.post("/{case_id}/notes/{key}/clear", response_model=RedactionEntry)
def clear_note_by_case_and_key(case_id: int, key: str, user=Depends(operator)):
    return clear_note(ClearNoteInput(case_id=case_id, key=key), user)


@router.delete("/{case_id}/notes/{key}", response_model=RedactionEntry, include_in_schema=False)
def delete_note_by_case_and_key(case_id: int, key: str, user=Depends(operator)):
    return clear_note(ClearNoteInput(case_id=case_id, key=key), user)


@router.post("/by-code/{code}/redact", response_model=RedactionEntry, include_in_schema=False)
@router.post("/by-code/{code}/notes/{key}/clear", response_model=RedactionEntry)
def clear_note_by_code_and_key(
    code: str,
    key: str | None = None,
    form: ClearNoteInput | None = Body(default=None),
    user=Depends(operator),
):
    target = form or ClearNoteInput(code=code, key=key)
    target.code = code
    if key and not target.target_key():
        target.key = key
    return clear_note(target, user)


@router.get("/{case_id}/redactions", response_model=list[RedactionEntry], dependencies=[Depends(identity)])
def case_redactions(case_id: int):
    redactions.recover_case_now(case_id)
    with engine.connect() as db:
        cases.get(db, case_id)
        rows = db.execute(
            select(note_redactions)
            .where(note_redactions.c.case_id == case_id)
            .order_by(note_redactions.c.id.desc())
        ).mappings().all()
        code = cases.get(db, case_id)["code"]
        return [redactions.serialize(row, code) for row in rows]


@router.post("/{case_id}/runs", response_model=RunEntry, status_code=202)
def schedule(case_id: int, form: RunInput, user=Depends(operator)):
    redactions.recover_case_now(case_id)
    with engine.connect() as db:
        if cases.get(db, case_id).get("redaction_status") == redactions.PENDING:
            raise HTTPException(409, "该单正在清除整条备注，完成后才能重跑")
    return new_run(case_id, form, user)
