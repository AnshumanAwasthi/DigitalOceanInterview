# Event Ingestion API

FastAPI boilerplate for ingesting events with dual persistence to SQLite and Redis streams.

## Features

- `POST /events` — ingest events with `type`, `source`, and arbitrary JSON `payload`
- SQLite persistence for durable storage
- Redis stream publishing for downstream consumers
- `GET /health` — service health check (includes Redis connectivity)

## Project structure

```
app/
├── main.py              # FastAPI application entry point
├── config.py            # Environment-based settings
├── database.py          # SQLAlchemy models and session
├── schemas.py           # Pydantic request/response models
├── routers/
│   └── events.py        # POST /events endpoint
└── services/
    ├── event_service.py # Orchestrates DB + Redis writes
    └── redis_stream.py  # Redis stream publisher
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Start Redis locally (required for full ingestion flow):

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

Run the API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

## Example request

```bash
curl -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "type": "user.signup",
    "source": "web-app",
    "payload": {
      "user_id": "abc-123",
      "plan": "pro"
    }
  }'
```

Example response:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "user.signup",
  "source": "web-app",
  "payload": {
    "user_id": "abc-123",
    "plan": "pro"
  },
  "redis_stream_id": "1717488000000-0",
  "created_at": "2026-07-04T04:00:00+00:00"
}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./events.db` | SQLite database URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `REDIS_STREAM_NAME` | `events` | Redis stream key |

## Behavior notes

- Events are written to SQLite first, then published to the Redis stream.
- If Redis is unavailable after the DB write, the API returns `503` with the persisted `event_id`.
- The arbitrary JSON payload is stored as JSON in SQLite and serialized in the Redis stream entry.
