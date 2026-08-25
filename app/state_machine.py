from app.models import CaseState

ALLOWED_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.OPEN: {CaseState.DIAGNOSING, CaseState.ESCALATED, CaseState.WRITTEN_OFF},
    CaseState.DIAGNOSING: {CaseState.ACTING, CaseState.ESCALATED},
    CaseState.ACTING: {CaseState.AWAITING_PAYMENT, CaseState.DIAGNOSING, CaseState.ESCALATED, CaseState.WRITTEN_OFF},
    CaseState.AWAITING_PAYMENT: {
        CaseState.RECOVERED,
        CaseState.ACTING,
        CaseState.ESCALATED,
        CaseState.WRITTEN_OFF,
    },
    CaseState.RECOVERED: set(),
    CaseState.ESCALATED: {CaseState.ACTING, CaseState.WRITTEN_OFF},
    CaseState.WRITTEN_OFF: set(),
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
