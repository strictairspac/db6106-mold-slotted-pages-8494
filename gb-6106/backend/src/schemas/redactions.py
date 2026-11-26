from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClearNoteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    case_id: int | None = Field(default=None, ge=1)
    code: str | None = Field(default=None, max_length=48)
    order_no: str | None = Field(default=None, max_length=48)
    order_code: str | None = Field(default=None, max_length=48)
    key: str | None = Field(default=None, max_length=24)
    record_key: str | None = Field(default=None, max_length=24)
    history_no: str | None = Field(default=None, max_length=24)

    @model_validator(mode="before")
    @classmethod
    def accept_chinese_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        aliases = {
            "单号": ("code", "order_no", "order_code"),
            "变更单号": ("code", "order_no", "order_code"),
            "case_code": ("code", "order_no", "order_code"),
            "履历号": ("key", "record_key", "history_no"),
            "记录号": ("key", "record_key", "history_no"),
            "recordKey": ("key", "record_key", "history_no"),
            "caseId": ("case_id",),
        }
        for source, targets in aliases.items():
            if source in normalized:
                value = normalized[source]
                for target in targets:
                    normalized.setdefault(target, value)
        return normalized

    def target_code(self) -> str | None:
        value = self.code or self.order_no or self.order_code
        return value.strip() if isinstance(value, str) and value.strip() else None

    def target_key(self) -> str | None:
        value = self.key or self.record_key or self.history_no
        return value.strip() if isinstance(value, str) and value.strip() else None


class RedactionEntry(BaseModel):
    id: int
    case_id: int
    record_key: str
    status: str
    operation_count: int
    run_count: int
    actor: str
    last_error: str | None
    created_at: int
    updated_at: int
    finished_at: int | None
    code: str | None = None
