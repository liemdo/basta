# Running the credit service

Compose is the supported way to run the API, the worker, MongoDB, and Redis together. This note covers calling the API by hand, pointing the processes at your own MongoDB or Redis, and running the tests.

The API and the demo page are the same process. [http://localhost:8000](http://localhost:8000) is the page. [http://localhost:8000/docs](http://localhost:8000/docs) is Swagger. [http://localhost:8000/health](http://localhost:8000/health) returns 200 when MongoDB and Redis both answer, and 503 when either does not.

## Submit a credit

`amount` is a decimal string. `"25.00"` is accepted. A JSON number such as `25.00` is rejected with **422**.

`user_id` is 1–128 characters from `A–Z`, `a–z`, `0–9`, `_`, and `-`. `amount` must be greater than 0, at most `1000000.00`, and have at most two decimal places.

```bash
curl -s -X POST http://localhost:8000/credits \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"user_id":"u_123","amount":"25.00"}'
```

The response is **202**:

```json
{ "task_id": "4f1c2a0e-7b3d-4e9a-9c1f-2a6b8d0e5f71", "status": "processing" }
```

Poll until the worker finishes. The balance is a decimal string.

```bash
curl -s http://localhost:8000/credits/TASK_ID
curl -s http://localhost:8000/users/u_123
```

A processed user looks like this:

```json
{ "user_id": "u_123", "balance": "25.00" }
```

The same `Idempotency-Key` and the same body return the original task and do not publish again, including when that task `failed`. The same key with a different amount or user returns **409**. A second POST without the header is a second credit. A blank `Idempotency-Key` is treated as no key. The key is at most 128 characters.

`GET /users` returns at most 100 users, most recently updated first. A user appears only after a credit has been applied. A user who exists only as a failed credit is not in that list.

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/credits` | **202** while `processing`. **409** when the idempotency key was used for a different body. **422** when the body is invalid. **503** when the task could not be queued. |
| `GET` | `/credits/{task_id}` | Status, amount, user, and any error. **404** when the task is unknown. |
| `GET` | `/users/{user_id}` | Committed balance. **404** when this user has no balance yet. |
| `GET` | `/users` | At most 100 users, most recently updated first. |
| `GET` | `/health` | MongoDB and Redis. **503** when either is down. |
| `GET` | `/` | Demo page. |

If Redis rejects the publish, the API marks that credit `failed` and returns **503**. The stored error is `broker publish failed`. Database and network errors on the worker retry up to five times with exponential backoff. Any other error, or the last of those retries, sets the credit to `failed` and leaves the balance unchanged.

## MongoDB and Redis URLs

Both processes read the same four variables. Compose sets them for the containers. You only change them when a process runs on the host, or when MongoDB or Redis is not the Compose service.

| Variable | Purpose |
| --- | --- |
| `MONGODB_URI` | MongoDB connection string. |
| `MONGODB_DATABASE` | Database name. Default `credits`. |
| `REDIS_URL` | Redis connection string. |
| `PORT` | API port. Default `8000`. |

Inside Compose the values are:

```text
MONGODB_URI=mongodb://mongo:27017/?replicaSet=rs0
MONGODB_DATABASE=credits
REDIS_URL=redis://redis:6379/0
PORT=8000
```

`mongo` and `redis` are Compose DNS names. They do not resolve on your machine. A process on the host uses the published ports:

```text
MONGODB_URI=mongodb://localhost:27017/?directConnection=true
REDIS_URL=redis://localhost:6379/0
```

`directConnection=true` is required for that localhost URI. Compose starts MongoDB as a one-node replica set whose member is advertised as `mongo:27017`. Without `directConnection`, a client on the host tries to reconnect to the hostname `mongo` and fails. The replica set is what allows the balance increment and the status change to commit in one transaction. A standalone MongoDB server rejects that transaction.

Copy `.env.example` to `.env` when you run on the host. Environment variables win over the file. To use a MongoDB or Redis you already have, put those URLs in the environment of **both** the API and the worker. If they point at different Redis instances, the API enqueues work that the worker never sees, and the credit stays `processing`.

A remote MongoDB URI still has to be a replica set. Atlas uses a `mongodb+srv://` URL, which already selects the set. Example:

```text
MONGODB_URI=mongodb+srv://USER:PASSWORD@cluster.example.net/?retryWrites=true&w=majority
MONGODB_DATABASE=credits
REDIS_URL=redis://default:PASSWORD@redis.example.net:6379
```

Do not commit `.env`. The password stays in the environment of the machine that runs the process.

## API and worker on the host

Start MongoDB and Redis first, either with Compose or with your own URLs.

```bash
docker compose up -d mongo redis
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

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

The Docker image is Python 3.11, and the Compose worker uses the default prefork pool. On Python 3.14 that pool crashes while tracing a task. Add `--pool=solo` to the host worker command on that version.

The worker log should show it ready, then a line for each applied task. A credit whose `updated_at` never moves, and whose status stays `processing`, was stored by the API and not consumed. Check that the worker is running and that its `REDIS_URL` matches the API.

## Tests

Unit tests build the credit service with in-memory repositories and do not need a broker. Integration tests use MongoDB and Redis on localhost and write to the `credits_test` database, not `credits`. The test setup forces that database name.

```bash
docker compose up -d mongo redis
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

The test setup sets `MONGODB_URI` and `REDIS_URL` to the localhost values above when those variables are unset, and it always uses the `credits_test` database. A shell that already exported `MONGODB_URI` keeps that value, so a URI copied from `.env.example` (`mongo` instead of `localhost`) makes the suite fail to connect. Unset it, or export the localhost URI, before pytest.
