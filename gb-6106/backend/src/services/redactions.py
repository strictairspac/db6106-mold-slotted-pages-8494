import logging
import re
import time

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from src.config.resources import engine
from src.domain.redaction import clear_operations, clear_result
from src.models.cases import cases
from src.models.redactions import note_redactions
from src.models.runs import runs
from src.schemas.redactions import ClearNoteInput
from src.services.audit import record
from src.utils.serial import content_digest

logger = logging.getLogger(__name__)

KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,24}")
PENDING = "pending"
DONE = "done"


def _now():
    return int(time.time())


def serialize(row, code=None):
    data = dict(row)
    data.setdefault("code", code)
    return data


def resolve_case(db, case_id=None, code=None):
    if case_id is not None:
        statement = select(cases).where(cases.c.id == case_id)
    elif code:
        statement = select(cases).where(cases.c.code == code)
    else:
        raise HTTPException(422, "请提供单号或资料 ID")

    entry = db.execute(statement).mappings().first()
    if entry is None and code and str(code).isdigit():
        numeric_id = int(code)
        entry = db.execute(select(cases).where(cases.c.id == numeric_id)).mappings().first()
        if entry is None:
            # Accept a batch/run number as an alias for its change order.
            case_id = db.scalar(select(runs.c.case_id).where(runs.c.id == numeric_id))
            if case_id is not None:
                entry = db.execute(select(cases).where(cases.c.id == case_id)).mappings().first()
    if entry is None:
        raise HTTPException(404, "变更单不存在")
    return dict(entry)


def _validate_key(key):
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise HTTPException(422, "履历号须为 1 至 24 位字母、数字、下划线或连字符")


def note_count(payload, key):
    operations = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(operations, list):
        return 0
    return sum(
        1 for operation in operations
        if isinstance(operation, dict)
        and operation.get("key") == key
        and isinstance(operation.get("note"), str)
    )


def request_clear(db, form, actor):
    """Create or reuse the durable clear request and commit it by the caller."""
    case = resolve_case(db, case_id=form.case_id, code=form.target_code())
    key = form.target_key()
    _validate_key(key)

    if note_count(case["payload"], key) == 0:
        raise HTTPException(404, "该单号下没有此履历号的整条备注")

    now = _now()
    existing = db.execute(
        select(note_redactions).where(
            note_redactions.c.case_id == case["id"],
            note_redactions.c.record_key == key,
        )
    ).mappings().first()

    if existing is not None:
        db.execute(
            update(note_redactions).where(note_redactions.c.id == existing["id"]).values(
                status=PENDING, actor=actor, last_error=None, updated_at=now,
            )
        )
        row = db.execute(
            select(note_redactions).where(note_redactions.c.id == existing["id"])
        ).mappings().first()
        return serialize(row, case["code"])

    change = db.execute(note_redactions.insert().values(
        case_id=case["id"], record_key=key, status=PENDING,
        operation_count=0, run_count=0, actor=actor, last_error=None,
        created_at=now, updated_at=now, finished_at=None,
    ))
    redaction_id = change.inserted_primary_key[0]
    record(db, "request_clear_note", actor, "redaction", redaction_id)
    row = db.execute(
        select(note_redactions).where(note_redactions.c.id == redaction_id)
    ).mappings().first()
    return serialize(row, case["code"])


def _apply(db, redaction_id, wait=True):
    statement = select(note_redactions).where(note_redactions.c.id == redaction_id)
    statement = statement.with_for_update() if wait else statement.with_for_update(skip_locked=True)
    row = db.execute(statement).mappings().first()
    if row is None:
        if not wait:
            return {"id": redaction_id, "status": PENDING, "skipped": True}
        raise HTTPException(404, "清除记录不存在")
    row = dict(row)
    if row["status"] == DONE:
        case = db.execute(select(cases.c.code).where(cases.c.id == row["case_id"])).scalar()
        return serialize(row, case)

    case_id = row["case_id"]
    key = row["record_key"]

    # Worker transactions lock their run row first and then finish it.  Keep
    # the same run -> case lock direction here to avoid a lock-order inversion.
    db.execute(
        select(runs.c.id).where(runs.c.case_id == case_id).order_by(runs.c.id).with_for_update()
    ).all()
    case_row = db.execute(
        select(cases).where(cases.c.id == case_id).with_for_update()
    ).mappings().first()
    if case_row is None:
        raise HTTPException(404, "变更单不存在")

    new_payload, originals, operation_count = clear_operations(case_row["payload"], key)
    db.execute(update(cases).where(cases.c.id == case_id).values(payload=new_payload))

    run_rows = db.execute(
        select(runs.c.id, runs.c.result)
        .where(runs.c.case_id == case_id)
        .order_by(runs.c.id)
        .with_for_update()
    ).mappings().all()
    cleared_runs = 0
    for run_row in run_rows:
        result = run_row["result"]
        if not isinstance(result, dict):
            continue
        scrubbed, changed = clear_result(result, key, originals)
        if changed:
            db.execute(update(runs).where(runs.c.id == run_row["id"]).values(
                result=scrubbed, digest=content_digest(scrubbed),
            ))
            cleared_runs += 1

    now = _now()
    db.execute(update(note_redactions).where(note_redactions.c.id == redaction_id).values(
        status=DONE,
        operation_count=operation_count,
        run_count=cleared_runs,
        last_error=None,
        updated_at=now,
        finished_at=now,
    ))
    record(db, "clear_note", row["actor"], "redaction", redaction_id)

    fresh = db.execute(
        select(note_redactions).where(note_redactions.c.id == redaction_id)
    ).mappings().first()
    return serialize(fresh, case_row["code"])


def _retryable_lock_error(exc):
    text = str(getattr(exc, "orig", exc)).lower()
    return any(token in text for token in ("deadlock", "lock wait timeout", "1213", "1205", "database is locked"))


def process_redaction(redaction_id, wait=True):
    last_error = None
    for attempt in range(3):
        try:
            with engine.begin() as db:
                return _apply(db, redaction_id, wait=wait)
        except OperationalError as exc:
            last_error = exc
            if not wait or attempt == 2 or not _retryable_lock_error(exc):
                raise
            time.sleep(0.05 * (attempt + 1))
    raise last_error  # pragma: no cover


def _record_error(redaction_id, exc):
    try:
        with engine.begin() as db:
            db.execute(update(note_redactions).where(note_redactions.c.id == redaction_id).values(
                last_error=str(exc)[:320], updated_at=_now(),
            ))
    except Exception:  # pragma: no cover - error reporting must not mask failure
        logger.exception("Unable to record redaction error for %s", redaction_id)


def submit_clear(form, actor):
    with engine.begin() as db:
        row = request_clear(db, form, actor)
        redaction_id = row["id"]
    try:
        return process_redaction(redaction_id)
    except Exception as exc:
        _record_error(redaction_id, exc)
        raise


def clear_note(*, actor="operator", **target):
    """Convenience wrapper for tests and callers that do not use FastAPI forms."""
    aliases = {
        "order_no": target.get("order_no") or target.get("order_code"),
        "record_key": target.get("record_key") or target.get("history_no"),
    }
    form = ClearNoteInput(
        case_id=target.get("case_id"),
        code=target.get("code") or target.get("order_no") or target.get("order_code"),
        order_no=aliases["order_no"],
        key=target.get("key") or target.get("record_key") or target.get("history_no"),
        record_key=aliases["record_key"],
    )
    return submit_clear(form, actor)


def pending_ids(db=None, limit=20):
    statement = (
        select(note_redactions.c.id)
        .where(note_redactions.c.status == PENDING)
        .order_by(note_redactions.c.id)
        .limit(limit)
    )
    if db is not None:
        return list(db.execute(statement).scalars())
    with engine.connect() as connection:
        return list(connection.execute(statement).scalars())


def recover_pending(limit=20):
    recovered = 0
    for redaction_id in pending_ids(limit=limit):
        try:
            result = process_redaction(redaction_id, wait=False)
            if not result.get("skipped"):
                recovered += 1
        except Exception:
            logger.exception("Interrupted note clear %s could not be recovered", redaction_id)
    return recovered


def recover_pending_safe(limit=20):
    try:
        return recover_pending(limit=limit)
    except Exception:
        logger.exception("Note clear recovery scan failed")
        return 0


def recover_case(db, case_id):
    ids = db.execute(
        select(note_redactions.c.id).where(
            note_redactions.c.case_id == case_id,
            note_redactions.c.status == PENDING,
        ).order_by(note_redactions.c.id)
    ).scalars()
    result = None
    for redaction_id in ids:
        result = _apply(db, redaction_id)
    return result


def recover_case_now(case_id):
    """Recover a case in committed transactions before serving a fresh read."""
    with engine.connect() as db:
        ids = list(db.execute(
            select(note_redactions.c.id).where(
                note_redactions.c.case_id == case_id,
                note_redactions.c.status == PENDING,
            ).order_by(note_redactions.c.id)
        ).scalars())
    for redaction_id in ids:
        process_redaction(redaction_id)
    return len(ids)


def pending_case_ids(db):
    return set(db.execute(
        select(note_redactions.c.case_id).where(note_redactions.c.status == PENDING)
    ).scalars())


def sanitize_result_for_case(db, case_id, result):
    """Mask trace rows for already completed clears before writing a fresh run.

    The worker's transaction can have an old snapshot when a clear commits
    concurrently.  Read the barrier with a fresh connection so SQLite and
    repeatable-read deployments observe the latest committed clear.
    """
    if not isinstance(result, dict):
        return result
    with engine.connect() as latest:
        keys = latest.execute(
            select(note_redactions.c.record_key).where(
                note_redactions.c.case_id == case_id,
                note_redactions.c.status == DONE,
            )
        ).scalars().all()
    sanitized = result
    for key in keys:
        sanitized, _ = clear_result(sanitized, key)
    return sanitized
