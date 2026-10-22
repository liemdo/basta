# Async credit service

Asynchronous credit API. `POST /credits` stores a credit as `processing` and returns 202. A Celery worker adds the amount to the user's balance and sets the credit to `processed`. Open `/` to add a credit and see balances. There is no sign-in.

## Run

```bash
docker compose up --build
```

The API listens on port 8000. `GET /health` checks MongoDB and Redis.

```bash
curl -s -X POST http://localhost:8000/credits \
  -H 'content-type: application/json' \
  -d '{"user_id":"u_123","amount":"25.00"}'
```

For a local virtualenv, copy `.env.example` to `.env`. The `mongo` and `redis` hostnames in that file work inside Compose. Use `localhost` when the process runs on your machine and the ports are published.
