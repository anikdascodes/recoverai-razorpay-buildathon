from app.models import CaseState

ALLOWED_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.OPEN: {CaseState.DIAGNOSING, CaseState.ESCALATED, CaseState.WRITTEN_OFF},
    # DIAGNOSING -> AWAITING_PAYMENT: policy gate deferred the case (e.g.
    # outside contact window); it waits for the next batch run.
    CaseState.DIAGNOSING: {CaseState.ACTING, CaseState.AWAITING_PAYMENT, CaseState.ESCALATED},
    CaseState.ACTING: {CaseState.AWAITING_PAYMENT, CaseState.DIAGNOSING, CaseState.ESCALATED, CaseState.WRITTEN_OFF},
    CaseState.AWAITING_PAYMENT: {
        CaseState.RECOVERED,
        CaseState.ACTING,
        CaseState.ESCALATED,
        CaseState.WRITTEN_OFF,
    },
    CaseState.RECOVERED: set(),
    # ESCALATED -> DIAGNOSING happens when a human approves and the agent
    # re-runs with the amount gate unlocked.
    CaseState.ESCALATED: {CaseState.DIAGNOSING, CaseState.ACTING, CaseState.AWAITING_PAYMENT, CaseState.WRITTEN_OFF},
    # WRITTEN_OFF is terminal for agent actions. The only exit is a genuine
    # late authorization event handled by the reconciler in normalizer.py.
    CaseState.WRITTEN_OFF: {CaseState.RECOVERED},
}

TERMINAL_STATES = {CaseState.RECOVERED, CaseState.WRITTEN_OFF}


def can_transition(current: CaseState, target: CaseState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


class IllegalTransition(Exception):
    pass


def transition(current: CaseState, target: CaseState) -> CaseState:
    if not can_transition(current, target):
        raise IllegalTransition(f"{current.value} -> {target.value} is not allowed")
    return target
