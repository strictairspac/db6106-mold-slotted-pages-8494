from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, UniqueConstraint, Table

from .base import metadata


note_redactions = Table(
    "note_redactions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("record_key", String(24), nullable=False),
    Column("status", String(16), nullable=False, default="pending", index=True),
    Column("operation_count", Integer, nullable=False, default=0),
    Column("run_count", Integer, nullable=False, default=0),
    Column("actor", String(48), nullable=False),
    Column("last_error", String(320), nullable=True),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger, nullable=True),
    UniqueConstraint("case_id", "record_key", name="uq_note_redactions_case_record"),
)
