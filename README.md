# Event Ingestion API

FastAPI service for ingesting events with dual persistence (database + Redis streams), JWT-authenticated subscriber webhooks, and a standalone worker for async delivery.

See [docs/architecture.md](docs/architecture.md) for system diagrams and deployment notes.

## Features

- `POST /events` — ingest events with `type`, `source`, and arbitrary JSON `payload`
- JWT bearer authentication on all protected endpoints
- SQLite persistence with append-only event audit log
- Redis stream publishing for downstream consumers
- Subscriber registration with filter rules and webhook delivery
- Exponential backoff retries with per-attempt delivery tracking
- `GET /deliveries/query` and `GET /deliveries/history` — delivery status APIs
- Standalone worker (`python -m app.worker`) for Redis stream consumption
- GitHub Actions CI/CD with DigitalOcean App Platform deploy

## Project structure

```
app/
├── main.py                 # FastAPI web service entry point
├── worker.py               # Standalone Redis stream worker
├── auth.py                 # JWT helpers
├── config.py               # Environment-based settings
├── database.py             # SQLAlchemy models and session
├── schemas.py              # Pydantic request/response models
├── routers/
│   ├── events.py           # POST /events
│   ├── subscribers.py      # Subscriber CRUD
│   └── deliveries.py       # Delivery query APIs
└── services/
    ├── event_service.py    # DB + Redis ingestion orchestration
    ├── redis_stream.py     # Redis stream publisher
    ├── stream_consumer.py  # Redis consumer group logic
    ├── delivery_service.py # Webhook delivery orchestration
    └── filter_service.py   # Subscriber filter matching
docs/
└── architecture.md         # Architecture diagrams
tests/                      # Unit and integration tests
```

## Setup

### Prerequisites

- Python 3.12+
- Redis 7+ (local Docker or managed instance)

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
JWT_SECRET_KEY=your-secret-key-at-least-32-chars-long
REDIS_URL=redis://localhost:6379/0
```

### 2. Start Redis

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 3. Run the web service

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### 4. Run the worker (optional)

For production-style split deployment, disable the embedded consumer on the web service and run the worker separately:

```bash
# Terminal 1 — web service
CONSUMER_ENABLED=false uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — worker
python -m app.worker
```

For local development, a single web service with `CONSUMER_ENABLED=true` (the default) runs the consumer in-process.

### 5. Create a JWT for API calls

Protected endpoints require a Bearer token signed with `JWT_SECRET_KEY`. Generate one from the project root:

```bash
python -c "from app.auth import create_access_token; print(create_access_token('my-user-id'))"
```

Use the token in requests:

```bash
export TOKEN="<paste-token-here>"
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/subscribers/list
```

### 6. Run tests

```bash
# Unit tests (no Redis required)
pytest -m "not integration"

# Integration tests (requires Redis at REDIS_URL)
pytest -m integration
```

### Docker

```bash
docker build -t event-ingestion-api .
docker run -d \
  -p 8000:8000 \
  -e JWT_SECRET_KEY=your-secret-key-at-least-32-chars-long \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  -v event-data:/data \
  event-ingestion-api
```

## API overview

| Endpoint | Auth | Description |
|----------|------|-------------|
| `POST /events` | JWT | Ingest an event |
| `POST /subscribers/create` | JWT | Register a webhook subscriber |
| `GET /subscribers/list` | JWT | List your subscribers |
| `DELETE /subscribers/{id}` | JWT | Delete your subscriber |
| `GET /deliveries/query` | JWT | Delivery status by `event_id` and/or `subscriber_id` |
| `GET /deliveries/history` | JWT | Delivery status with attempt history |
| `GET /health` | Public | Health check (includes Redis connectivity) |

## Example: ingest an event

```bash
curl -X POST http://localhost:8000/events \
  -H "Authorization: Bearer $TOKEN" \
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
  "status": "Publish to stream",
  "redis_stream_id": "1717488000000-0",
  "created_at": "2026-07-04T04:00:00+00:00"
}
```

## Filter rule syntax

Subscribers receive webhook notifications only when an event matches **all** of their filter rules. Filters are set when creating a subscriber via `POST /subscribers/create`.

### Filter object

```json
{
  "webhook_url": "https://example.com/webhooks/events",
  "filters": {
    "type": "user.signup",
    "source": "web-app",
    "payload_conditions": [
      { "field": "plan", "operator": "eq", "value": "pro" },
      { "field": "metadata.region", "operator": "eq", "value": "us-east" }
    ]
  }
}
```

### Top-level fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | No | Exact match on event `type`. Omit to match any type. |
| `source` | No | Exact match on event `source`. Omit to match any source. |
| `payload_conditions` | No | List of conditions on the event `payload`. All must match (AND). |

### Payload conditions

Each condition targets a field in the event payload using dot notation for nested keys (e.g. `metadata.region`).

| Operator | `value` required | Matches when |
|----------|------------------|--------------|
| `eq` | Yes | Field value equals `value` |
| `neq` | Yes | Field value does not equal `value` |
| `contains` | Yes | String field contains `value`, or list/set/tuple includes `value` |
| `exists` | No | Field is present in the payload (any value) |

### Examples

**Match all signups from the web app:**

```json
{ "type": "user.signup", "source": "web-app", "payload_conditions": [] }
```

**Match pro plan only:**

```json
{
  "payload_conditions": [
    { "field": "plan", "operator": "eq", "value": "pro" }
  ]
}
```

**Match events that include a beta tag:**

```json
{
  "payload_conditions": [
    { "field": "tags", "operator": "contains", "value": "beta" }
  ]
}
```

**Match events with a nested region field:**

```json
{
  "payload_conditions": [
    { "field": "metadata.region", "operator": "neq", "value": "eu-west" }
  ]
}
```

**Match events that include an email field:**

```json
{
  "payload_conditions": [
    { "field": "email", "operator": "exists" }
  ]
}
```

### Webhook payload

When a subscriber matches, the worker POSTs this JSON body to the subscriber's `webhook_url`:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "user.signup",
  "source": "web-app",
  "payload": { "user_id": "abc-123", "plan": "pro" },
  "redis_stream_id": "1717488000000-0"
}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./events.db` | Database connection URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `REDIS_STREAM_NAME` | `events` | Redis stream key |
| `REDIS_CONSUMER_GROUP` | `event-deliverers` | Consumer group name |
| `REDIS_CONSUMER_NAME` | `worker-1` | Consumer name within the group |
| `CONSUMER_ENABLED` | `true` | Start embedded consumer in web service |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | HTTP timeout per webhook attempt |
| `WEBHOOK_MAX_RETRIES` | `3` | Max webhook delivery attempts |
| `WEBHOOK_RETRY_BASE_SECONDS` | `1` | Base delay for exponential backoff |
| `WEBHOOK_RETRY_MAX_SECONDS` | `30` | Max delay between retries |
| `JWT_SECRET_KEY` | *(required)* | Secret for signing JWTs |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |

## Behavior notes

- Events are written to the database first, then published to the Redis stream.
- If Redis is unavailable after the DB write, the API returns `503` with the persisted `event_id`.
- The worker consumes from Redis, matches subscribers, and delivers webhooks with retry.
- Delivery state is tracked in `deliveries` and `delivery_attempts` tables.
- Subscribers and delivery queries are scoped to the JWT user's `sub` claim.

## TODO

- [ ] Migrate production database from SQLite to Managed PostgreSQL for split web/worker deploy
- [ ] Add rate limiting on `POST /events`
- [ ] Add observability (structured logging, metrics, tracing)
- [ ] Add dead-letter handling for repeatedly failing stream messages
