class CreditNotFound(Exception):
    """No credit exists for this task id."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(task_id)


class UserNotFound(Exception):
    """No balance exists for this user id."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        super().__init__(user_id)


class IdempotencyConflict(Exception):
    """This idempotency key was already used for a different credit."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(idempotency_key)


class BrokerPublishError(Exception):
    """The credit was stored, but the task could not be published."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(task_id)
