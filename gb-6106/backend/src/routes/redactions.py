from fastapi import APIRouter, Depends

from src.controllers.access import operator
from src.controllers.workbench import clear_note
from src.schemas.redactions import ClearNoteInput, RedactionEntry
from src.services import redactions

router = APIRouter(tags=["Note Redaction"])


@router.post("/redactions", response_model=RedactionEntry)
def create_redaction(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)


@router.post("/redactions/clear", response_model=RedactionEntry, include_in_schema=False)
def clear_redaction(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)


@router.post("/redactions/recover-pending", include_in_schema=False)
def recover_pending_redactions(user=Depends(operator)):
    return {"recovered": redactions.recover_pending()}


@router.post("/redactions/{redaction_id}/resume", response_model=RedactionEntry)
@router.post("/redactions/{redaction_id}/recover", response_model=RedactionEntry, include_in_schema=False)
def resume_redaction(redaction_id: int, user=Depends(operator)):
    return redactions.process_redaction(redaction_id)


@router.post("/work-orders/clear-note", response_model=RedactionEntry, include_in_schema=False)
def clear_work_order_note(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)


@router.post("/work-orders/{code}/records/{key}/clear", response_model=RedactionEntry, include_in_schema=False)
def clear_work_order_record(code: str, key: str, user=Depends(operator)):
    return clear_note(ClearNoteInput(code=code, key=key), user)


@router.post("/change-orders/clear-note", response_model=RedactionEntry, include_in_schema=False)
def clear_change_order_note(form: ClearNoteInput, user=Depends(operator)):
    return clear_note(form, user)
