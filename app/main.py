from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import deliveries, events, subscribers
from app.services.redis_stream import redis_publisher
from app.services.stream_consumer import stream_consumer


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    stream_consumer.start()
    yield
    stream_consumer.stop()


app = FastAPI(
    title="Event Ingestion API",
    description="FastAPI boilerplate for ingesting events into SQLite and Redis streams.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(events.router)
app.include_router(subscribers.router)
app.include_router(deliveries.router)


@app.get("/health")
def health_check() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "redis": redis_publisher.ping(),
    }
