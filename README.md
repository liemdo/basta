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

Install Docker Desktop, which includes Compose:

- Mac: [Install Docker Desktop on Mac](https://docs.docker.com/desktop/setup/install/mac-install/)
- Windows: [Install Docker Desktop on Windows](https://docs.docker.com/desktop/setup/install/windows-install/)

Start Docker and leave it running before the commands below.

### Installation

1. Start the API, the worker, MongoDB, and Redis:

   ```bash
   docker compose up --build
   ```

2. Open the demo at [http://localhost:8000](http://localhost:8000). Try the same routes in Swagger at [http://localhost:8000/docs](http://localhost:8000/docs). The live demo's Swagger is [https://basta-production-1b91.up.railway.app/docs](https://basta-production-1b91.up.railway.app/docs).

`GET /health` returns 200 when MongoDB and Redis both answer.

Submitting a credit by hand, and pointing the app at your own MongoDB or Redis, is covered in [Running the service](docs/running.md).

## Documentation

- [Running the service](docs/running.md): curl examples, idempotency, and custom MongoDB and Redis URLs
- [Design and architecture](docs/design.md): request flow, why status lives on the credit, and the limits of this version
- [Design note (PDF)](docs/design.pdf)

## Tech Stack

- **API**: FastAPI, Pydantic v2, Python 3.11
- **Worker**: Celery 5. Redis is the broker. Celery stores no task result
- **Database**: MongoDB. Balances are `Decimal128`. The apply step is one multi-document transaction, so MongoDB runs as a replica set
- **Local runtime**: Docker Compose (`api`, `worker`, `mongo`, `redis`)
- **Tests**: pytest. Unit tests use in-memory stand-ins. Integration tests use the Compose databases

## Honest limits

A crash after the credit is inserted and before it is published can leave it `processing` with nothing queued. Nothing sweeps that gap. Clients poll for completion. The balance is one increment on the user, not a ledger. There is no sign-in.

The [design note](docs/design.md) covers these limits, and the choice of Redis over a heavier broker, in more detail.
