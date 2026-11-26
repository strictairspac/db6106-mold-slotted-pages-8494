"""Length-preserving redaction helpers.

The slotted page addresses records by byte offset.  Clearing a remark must
remove its readable text without changing UTF-8 byte length; otherwise slots,
offsets and rejection decisions from a replay would change.  Mapping every
character to a mask character with the same UTF-8 length preserves both the
character count and the exact byte count.
"""
from copy import deepcopy
from typing import Any

MASK_BY_UTF8_LENGTH = {
    1: "*",
    2: "×",
    3: "■",
    4: "🟥",
}


def clear_text(text: str) -> str:
    """Return an opaque mask with the same UTF-8 byte length as ``text``."""
    if not isinstance(text, str):
        raise TypeError("只能清除文本备注")
    return "".join(MASK_BY_UTF8_LENGTH[len(character.encode("utf-8"))] for character in text)


def _replace_everywhere(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for original, masked in replacements.items():
            if original:
                value = value.replace(original, masked)
        return value
    if isinstance(value, list):
        return [_replace_everywhere(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_everywhere(item, replacements) for key, item in value.items()}
    return value


def clear_operations(payload: dict, key: str) -> tuple[dict, list[str], int]:
    """Clear every note belonging to ``key`` in one change order payload."""
    cleared = deepcopy(payload)
    originals: list[str] = []
    count = 0
    operations = cleared.get("operations") if isinstance(cleared, dict) else None
    if not isinstance(operations, list):
        return cleared, originals, count

    for operation in operations:
        if not isinstance(operation, dict) or operation.get("key") != key:
            continue
        note = operation.get("note")
        if isinstance(note, str):
            originals.append(note)
            operation["note"] = clear_text(note)
            count += 1
    return cleared, originals, count


def clear_result(result: dict | None, key: str, originals: list[str] | None = None) -> tuple[dict | None, int]:
    """Remove a target remark from a persisted replay result.

    Exact original strings are replaced everywhere first.  The trace row for
    ``key`` is then masked structurally so recovery also works when the payload
    has already been rewritten and the originals are no longer available.
    """
    if not isinstance(result, dict):
        return result, 0

    changed = 0
    scrubbed = deepcopy(result)
    if originals:
        replacements = {original: clear_text(original) for original in originals if original}
        before = repr(scrubbed)
        scrubbed = _replace_everywhere(scrubbed, replacements)
        if repr(scrubbed) != before:
            changed += 1

    rows = scrubbed.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("履历") != key:
                continue
            # The trace row's "结果" is the decoded record body.  Operation
            # rows use that field for short status messages and are left alone.
            if row.get("操作") == "追溯地址" and isinstance(row.get("结果"), str):
                masked = clear_text(row["结果"])
                if row["结果"] != masked:
                    row["结果"] = masked
                    changed += 1
    return scrubbed, changed
