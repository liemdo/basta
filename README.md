# Async Credit Processing Service

Accept a credit over HTTP, return immediately, and add the amount to the user's balance on a worker. A repeated delivery of the same task does not add the money twice.

Live demo: [https://basta-production-1b91.up.railway.app/](https://basta-production-1b91.up.railway.app/)

## Key Features

- **Accept without waiting**: `POST /credits` stores the credit as `processing` and returns **202** with a `task_id`.
- **Exactly-once balance update**: A Celery worker increments the balance and sets the credit to `processed` in one MongoDB transaction. A redelivery does not apply it again.
- **Idempotency key**: The same `Idempotency-Key` and body return the original task. The same key with a different body returns **409**.
- **Status you can poll**: `GET /credits/{task_id}` reads MongoDB, not a Celery result. Status is `processing`, `processed`, or `failed`.
- **Demo page**: `/` submits a credit and lists committed balances. There is no sign-in.

## Getting Started

### Prerequisites

- Docker, for Compose
- Python 3.11+, only if you run the API or the tests on the host

### Installation

1. Start the API, the worker, MongoDB, and Redis:

   ```bash
   docker compose up --build
   ```

2. Open [http://localhost:8000](http://localhost:8000). `GET /health` returns 200 when MongoDB and Redis both answer.

3. Submit a credit. `amount` is a decimal string. A JSON number is rejected.

   ```bash
   curl -s -X POST http://localhost:8000/credits \
     -H 'content-type: application/json' \
     -H 'Idempotency-Key: demo-1' \
     -d '{"user_id":"u_123","amount":"25.00"}'
   ```

   Poll the task, then read the balance. The balance is a string, for example `"25.00"`.

   ```bash
   curl -s http://localhost:8000/credits/TASK_ID
   curl -s http://localhost:8000/users/u_123
   ```

4. Run the tests. They write to the `credits_test` database and expect MongoDB and Redis on localhost.

   ```bash
   docker compose up -d mongo redis
   python3 -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   .venv/bin/python -m pytest
   ```

To run the processes on the host instead of in Compose, copy `.env.example` to `.env` and point both commands at localhost. The replica-set member is advertised as `mongo`, so the host URI needs `directConnection=true`.

```bash
MONGODB_URI='mongodb://localhost:27017/?directConnection=true' \
REDIS_URL='redis://localhost:6379/0' \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
MONGODB_URI='mongodb://localhost:27017/?directConnection=true' \
REDIS_URL='redis://localhost:6379/0' \
.venv/bin/celery -A app.tasks worker --loglevel=info --concurrency=1
```

The image is Python 3.11. On Python 3.14, add `--pool=solo` to that worker command.

| Variable | Purpose |
| --- | --- |
| `MONGODB_URI` | MongoDB connection string. Compose uses `mongodb://mongo:27017/?replicaSet=rs0`. |
| `MONGODB_DATABASE` | Database name. Default `credits`. |
| `REDIS_URL` | Redis connection string. Compose uses `redis://redis:6379/0`. |
| `PORT` | API port. Default `8000`. |

`user_id` is 1–128 characters from `A–Z`, `a–z`, `0–9`, `_`, and `-`. `amount` is greater than 0, at most `1000000.00`, and has at most two decimal places.

## Documentation

The design note is the architecture discussion: the request flow, why status lives on the credit, how a redelivery is applied once, and the limits of this version.

- [Design and architecture](docs/design.md)
- [Design note (PDF)](docs/design.pdf)
- Interactive request shapes: [http://localhost:8000/docs](http://localhost:8000/docs), or [/docs](https://basta-production-1b91.up.railway.app/docs) on the live demo

## Tech Stack

- **API**: FastAPI, Pydantic v2, Python 3.11
- **Worker**: Celery 5. Redis is the broker. Celery stores no task result
- **Database**: MongoDB. Balances are `Decimal128`. The apply step is one multi-document transaction, so MongoDB runs as a replica set
- **Local runtime**: Docker Compose (`api`, `worker`, `mongo`, `redis`)
- **Tests**: pytest. Unit tests use in-memory stand-ins. Integration tests use the Compose databases

## Honest limits

A crash after the credit is inserted and before it is published can leave it `processing` with nothing queued. Nothing sweeps that gap. Clients poll for completion. The balance is one increment on the user, not a ledger. There is no sign-in.

The [design note](docs/design.md) covers these limits, and the choice of Redis over a heavier broker, in more detail.
