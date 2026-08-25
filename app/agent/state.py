from typing import TypedDict


class AgentState(TypedDict, total=False):
    case_id: int
    customer: dict
    amount_paise: int
    source: str
    subscription_id: str
    failure_code: str
    failure_reason: str
    attempts: int
    round_no: int
    last_action: str

    cause: str
    confidence: float
    diag_note: str

    allowed_actions: list[str]
    violations: list[str]
    needs_human: bool
    human_approved: bool

    action: str
    channel: str
    message: str

    exec_result: dict
    recovered: bool
    stop_reason: str
