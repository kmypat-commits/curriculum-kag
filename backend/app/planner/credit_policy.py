"""Explicit total-credit allowance; semester loads remain separately enforced."""


def total_credit_tolerance(constraints: dict, *, legacy_default: int = 5) -> int:
    if (int(constraints.get("total_credits") or 240) == 240
            and int(constraints.get("total_semesters") or 8) == 8):
        return 4
    # Other durations have exact acceptance. The optimiser and verifier must
    # use the same envelope rather than manufacture unpublishable plans.
    return 0


def total_credits_accepted(actual: int, constraints: dict) -> bool:
    target = int(constraints.get("total_credits") or 240)
    if target == 240 and int(constraints.get("total_semesters") or 8) == 8:
        return target <= actual <= target + 4
    # Acceptance for other degrees remains exact; no new allowance inferred.
    return actual == target
