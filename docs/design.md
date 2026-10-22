# Async credit processing

`POST /credits` checks `user_id` and `amount`, stores the credit as `processing`, enqueues a Celery task, and returns 202 with a task id. A worker adds the amount to that user's balance and sets the credit to `processed`. MongoDB is the source of truth for status. Redis only delivers work. Celery stores no task result.

## Status belongs on the credit

Two credits for one user can be in flight together. A user document has room for one status, so the second credit would overwrite the first, and a Celery retry could add money twice. Balance and status are separate documents.

`users` stores `user_id` and `balance`. The user is created when the first credit is processed. `credits` stores `task_id`, `user_id`, `amount`, `status`, an optional `idempotency_key`, timestamps, and an optional `error`. Status is `processing`, `processed`, or `failed`. `failed` is an extension: the credit will not be applied, and the balance does not change. Indexes are a unique `user_id` on users, a unique sparse `idempotency_key` on credits, and `user_id` on credits.

The balance increment and the change from `processing` to `processed` commit in one MongoDB transaction, so Compose runs MongoDB as a single-node replica set (`rs0`). The status update matches only a credit that is still `processing`. The worker that loses that update does not increment the balance. A later delivery of a `processed` or `failed` credit is a no-op.

## Money

Python uses `decimal.Decimal`. MongoDB uses `Decimal128`. JSON has no decimal type, and a JSON number is a binary float, so `amount` and `balance` are decimal strings such as `"25.00"`. Added as floats, `0.10` and `0.20` become `0.30000000000000004`. Reading the JSON number `0.30` back does not produce `0.30`.

An amount must be greater than zero, at most `1000000.00`, and have at most two decimal places. `user_id` is 1–128 characters from letters, digits, `_`, and `-`. A JSON number, a negative amount, or a third decimal place returns 422.

## Delivery

Celery can deliver a task more than once. The worker acknowledges late, puts the task back if the process is lost, and prefetches one message. Database and network errors retry up to five times with backoff. Any other error, or a retryable error after that budget, marks the credit `failed` and acknowledges the message.

`Idempotency-Key` is optional. The same key and body return the original task, including a failed one, and do not publish again. The same key with a different body returns 409. A second POST without the header is a second credit.

If Redis rejects the publish, the API marks that credit `failed` and returns 503. A crash after the insert and before the publish can leave a credit in `processing` with nothing queued. There is no sweeper for that gap.

## Demo page

`GET /` is an unauthenticated page on the API process. It is a review aid. The contract under review is still `POST /credits` and the worker. curl and `GET /docs` stay valid.

The browser calls only the JSON API. There is no account, session, or password, and the server does not know who is using the page. `user_id` is whatever the operator types. The table lists at most 100 users who already have a balance, most recently updated first. A user who exists only as a failed credit does not appear. The balance on screen is the last committed balance and changes when the polled credit becomes `processed`. Each submit sends a new idempotency key, so a double-click does not create two credits. The page polls about once a second for up to 30 seconds, then says the credit is still processing. The amount field keeps two decimal places and rejects a value that is not positive. User ids are inserted as text.

The page is public. Anyone with the link can credit any `user_id`. That fits a short review window and does not fit a shared host.

## Left out

Authentication, withdrawals, multiple currencies, a reconciliation sweeper, RabbitMQ, Kubernetes, and a separate frontend are out of scope. `GET /users` exists for the page. It has no search, paging, edit, or delete.
