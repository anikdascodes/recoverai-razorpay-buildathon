import argparse
import time

from sqlalchemy import select

from app.agent.graph import build_graph, run_case
from app.db import SessionLocal, init_db
from app.models import Case, CaseState


def main(limit: int | None = None) -> None:
    init_db()
    app = build_graph()

    with SessionLocal() as db:
        ids = list(db.scalars(
            select(Case.id).where(~Case.state.in_([CaseState.RECOVERED, CaseState.WRITTEN_OFF, CaseState.ESCALATED]))
        ).all())
    if limit:
        ids = ids[:limit]

    print(f"running agent on {len(ids)} cases...")
    t0 = time.time()
    recovered = escalated = written_off = 0

    for i, case_id in enumerate(ids, 1):
        try:
            out = run_case(app, case_id)
        except Exception as e:
            print(f"  case {case_id} ERROR: {e}")
            continue
        if out.get("recovered"):
            recovered += 1
        elif out.get("stop_reason") == "escalated_to_human":
            escalated += 1
        elif out.get("stop_reason") == "written_off":
            written_off += 1
        if i % 10 == 0 or i == len(ids):
            print(f"  [{i}/{len(ids)}] recovered={recovered} escalated={escalated} written_off={written_off}")

    print(f"done in {time.time() - t0:.1f}s")
    with SessionLocal() as db:
        stats = db.execute(
            select(Case.state).where(Case.source == "synthetic")
        ).all()
    from collections import Counter
    print("final states:", dict(Counter(s for s, in stats)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    main(args.limit)
