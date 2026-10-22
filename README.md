# Async credit service

`POST /credits` stores a credit as `processing` and returns 202 with a task id. A Celery worker adds the amount to the user's balance and sets the credit to `processed`. Open [http://localhost:8000](http://localhost:8000) to submit a credit and see balances. There is no sign-in.

The design is in [docs/design.md](docs/design.md). Request shapes are also at [http://localhost:8000/docs](http://localhost:8000/docs).

## Run

Docker Compose runs the API, the worker, MongoDB, and Redis.

```bash
docker compose up --build
```

The API listens on port 8000. `GET /health` returns 200 when MongoDB and Redis both answer, and 503 when either does not.

## Try a credit

`amount` is a decimal string. `"25.00"` is accepted. A JSON number such as `25.00` is rejected.

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

The same `Idempotency-Key` and body return the original task. The same key with a different amount returns 409. A POST without the header creates another credit.

## API

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/credits` | 202 while `processing`. 409 when the idempotency key was used for a different body. 422 when the body is invalid. 503 when the task could not be queued. |
| `GET` | `/credits/{task_id}` | Status, amount, and user. 404 when the task is unknown. |
| `GET` | `/users/{user_id}` | Committed balance. 404 when this user has no balance yet. |
| `GET` | `/users` | At most 100 users, most recently updated first. |
| `GET` | `/health` | MongoDB and Redis. 503 when either is down. |
| `GET` | `/` | Demo page. |

`user_id` is 1–128 characters from `A–Z`, `a–z`, `0–9`, `_`, and `-`. `amount` is greater than 0, at most `1000000.00`, and has at most two decimal places.

## Tests

The suite expects MongoDB and Redis on localhost. Tests write to the `credits_test` database.

```bash
docker compose up -d mongo redis
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `MONGODB_URI` | MongoDB connection string. Compose uses `mongodb://mongo:27017/?replicaSet=rs0`. |
| `MONGODB_DATABASE` | Database name. Default `credits`. |
| `REDIS_URL` | Redis connection string. Compose uses `redis://redis:6379/0`. |
| `PORT` | API port. Default `8000`. |

Copy `.env.example` to `.env` to run the API on the host. The hostnames in that file resolve inside Compose. From the host, use `localhost`, and set `directConnection=true` because the replica-set member is advertised as `mongo`.

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

The image is Python 3.11. On Python 3.14, add `--pool=solo` to that worker command. The prefork pool crashes on that version.
