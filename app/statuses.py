from enum import StrEnum


class CreditStatus(StrEnum):
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class ApplyOutcome(StrEnum):
    """Result of asking the worker to apply one credit."""

    APPLIED = "applied"
    ALREADY_PROCESSED = "already_processed"
    MISSING = "missing"


class DependencyStatus(StrEnum):
    UP = "up"
    DOWN = "down"
