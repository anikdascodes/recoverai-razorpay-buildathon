from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Case, CaseState

router = APIRouter()


@router.get("/stats")
def batch_stats(db: Session = Depends(get_db)) -> dict:
    total_cases = db.scalar(select(func.count(Case.id))) or 0
    at_risk = db.scalar(select(func.coalesce(func.sum(Case.amount), 0))) or 0
    recovered_amount = (
        db.scalar(select(func.coalesce(func.sum(Case.recovered_amount), 0)).where(Case.state == CaseState.RECOVERED))
        or 0
    )
    recovered_count = (
        db.scalar(select(func.count(Case.id)).where(Case.state == CaseState.RECOVERED)) or 0
    )
    open_count = (
        db.scalar(select(func.count(Case.id)).where(~Case.state.in_([CaseState.RECOVERED, CaseState.WRITTEN_OFF])))
        or 0
    )
    written_off = db.scalar(select(func.count(Case.id)).where(Case.state == CaseState.WRITTEN_OFF)) or 0
    escalated = db.scalar(select(func.count(Case.id)).where(Case.state == CaseState.ESCALATED)) or 0

    by_cause_rows = db.execute(
        select(
            Case.cause,
            func.count(Case.id),
            func.sum(Case.amount),
            func.coalesce(func.sum(Case.recovered_amount), 0),
        ).group_by(Case.cause)
    ).all()

    recovery_rate = (recovered_amount / at_risk * 100) if at_risk else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": {
            "total": total_cases,
            "open_or_active": open_count,
            "recovered": recovered_count,
            "written_off": written_off,
            "escalated": escalated,
        },
        "money": {
            "at_risk_paise": at_risk,
            "recovered_paise": recovered_amount,
            "at_risk_rupees": round(at_risk / 100, 2),
            "recovered_rupees": round(recovered_amount / 100, 2),
            "recovery_rate_pct": round(recovery_rate, 1),
        },
        "by_cause": [
            {
                "cause": cause.value if hasattr(cause, "value") else str(cause),
                "cases": n,
                "at_risk_paise": amt,
                "recovered_paise": rec,
                "rate_pct": round((rec / amt * 100) if amt else 0, 1),
            }
            for cause, n, amt, rec in by_cause_rows
        ],
    }
