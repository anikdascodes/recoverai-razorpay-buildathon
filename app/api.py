import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.agent.graph import build_graph, run_case
from app.db import SessionLocal
from app.models import Attempt, Case, CaseState, Customer, utcnow
from app.state_machine import transition

router = APIRouter(prefix="/api")

AUDIT_FILE = Path("audit.jsonl")


@router.get("/cases")
def list_cases(state: str | None = None, limit: int = 100) -> dict:
    limit = max(1, min(limit, 500))
    with SessionLocal() as db:
        q = (
            select(Case, Customer)
            .join(Customer, Case.customer_id == Customer.id)
            .order_by(Case.priority, Case.amount.desc())
            .limit(limit)
        )
        if state:
            try:
                state_enum = CaseState(state)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"unknown state: {state}. Valid: {[s.value for s in CaseState]}")
            q = q.where(Case.state == state_enum)
        else:
            q = q.where(~Case.state.in_([CaseState.RECOVERED]))
        rows = db.execute(q).all()
        cases = []
        for case, cust in rows:
            cases.append({
                "id": case.id,
                "customer": {"name": cust.name, "phone": cust.phone, "lang": cust.lang_pref},
                "amount_rs": round(case.amount / 100, 2),
                "cause": case.cause.value,
                "state": case.state.value,
                "failure_code": case.failure_code,
                "attempts": case.attempts_count,
                "recovered_rs": round(case.recovered_amount / 100, 2),
                "created_at": case.created_at.isoformat(),
            })
    return {"cases": cases}


@router.get("/cases/{case_id}/timeline")
def case_timeline(case_id: int) -> dict:
    events = []
    if AUDIT_FILE.exists():
        for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("case_id") == case_id:
                events.append(rec)
    with SessionLocal() as db:
        attempts = db.scalars(
            select(Attempt).where(Attempt.case_id == case_id).order_by(Attempt.id)
        ).all()
        attempt_rows = [
            {
                "action": a.action_type,
                "channel": a.channel,
                "message": a.payload.get("message", ""),
                "link": a.payload.get("link", ""),
                "result": a.result,
                "at": a.created_at.isoformat(),
            }
            for a in attempts
        ]
        case = db.get(Case, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        return {
            "case": {
                "id": case.id,
                "state": case.state.value,
                "amount_rs": round(case.amount / 100, 2),
                "recovered_rs": round(case.recovered_amount / 100, 2),
                "cause": case.cause.value,
                "failure_code": case.failure_code,
                "attempts": case.attempts_count,
            },
            "agent_events": events,
            "channel_attempts": attempt_rows,
        }


@router.get("/approvals")
def approval_inbox() -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(Case, Customer)
            .join(Customer, Case.customer_id == Customer.id)
            .where(Case.state == CaseState.ESCALATED)
            .order_by(Case.amount.desc())
        ).all()
        items = [
            {
                "id": c.id,
                "customer": cu.name,
                "phone": cu.phone,
                "amount_rs": round(c.amount / 100, 2),
                "cause": c.cause.value,
                "attempts": c.attempts_count,
                "opt_out": cu.opt_out,
            }
            for c, cu in rows
        ]
    return {"approvals": items, "count": len(items)}


@router.post("/approvals/{case_id}/approve")
def approve_case(case_id: int) -> dict:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        if case.state != CaseState.ESCALATED:
            raise HTTPException(status_code=400, detail=f"case is {case.state.value}, not escalated")
        case.state = transition(case.state, CaseState.DIAGNOSING)
        db.commit()
    graph = build_graph()
    out = run_case(graph, case_id, round_no=case.attempts_count, human_approved=True)
    return {"status": "processed", **out}


@router.post("/approvals/{case_id}/reject")
def reject_case(case_id: int) -> dict:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        if case.state != CaseState.ESCALATED:
            raise HTTPException(status_code=400, detail="not escalated")
        case.state = CaseState.WRITTEN_OFF
        case.closed_at = case.closed_at or utcnow()
        db.commit()
    return {"status": "written_off"}
