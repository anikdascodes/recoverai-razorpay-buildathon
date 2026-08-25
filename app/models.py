import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaseState(str, enum.Enum):
    OPEN = "open"
    DIAGNOSING = "diagnosing"
    ACTING = "acting"
    AWAITING_PAYMENT = "awaiting_payment"
    RECOVERED = "recovered"
    ESCALATED = "escalated"
    WRITTEN_OFF = "written_off"


class FailureCause(str, enum.Enum):
    CARD_EXPIRED = "card_expired"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    MANDATE_ISSUE = "mandate_issue"
    NETWORK_RETRYABLE = "network_retryable"
    AUTHENTICATION_FAILURE = "authentication_failure"
    UNKNOWN = "unknown"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    rzp_customer_id: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(160), default="")
    lang_pref: Mapped[str] = mapped_column(String(16), default="en")
    opt_out: Mapped[bool] = mapped_column(default=False)
    dnd_flag: Mapped[bool] = mapped_column(default=False)


class RawEvent(Base):
    __tablename__ = "raw_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed: Mapped[bool] = mapped_column(default=False)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("source", "source_ref", name="uq_case_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    subscription_id: Mapped[str] = mapped_column(String(64), default="")
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    source: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str] = mapped_column(String(64))
    failure_code: Mapped[str] = mapped_column(String(64), default="")
    failure_reason: Mapped[str] = mapped_column(String(255), default="")
    cause: Mapped[FailureCause] = mapped_column(Enum(FailureCause), default=FailureCause.UNKNOWN)
    state: Mapped[CaseState] = mapped_column(Enum(CaseState), default=CaseState.OPEN)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    recovered_amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(48))
    channel: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
