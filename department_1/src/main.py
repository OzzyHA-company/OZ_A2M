"""FastAPI Gateway for OZ_A2M."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import sys
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.core import get_settings, setup_logging, get_logger
from lib.core.exceptions import OZA2MError
from lib.messaging import get_mqtt_client
from lib.data import get_redis_client, get_es_client

# Setup logging
settings = get_settings()
setup_logging(settings.log_level, settings.log_format)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan handler."""
    # Startup
    logger.info("Gateway starting up", environment=settings.environment)

    # Connect to services
    mqtt = get_mqtt_client()
    redis = get_redis_client()
    es = get_es_client()

    try:
        await mqtt.connect()
        await redis.connect()
        await es.connect()

        # Publish startup event
        await mqtt.publish(
            "oz_a2m/system/health",
            {"status": "up", "service": "gateway"}
        )

        logger.info("Gateway startup complete")
        yield
    finally:
        # Shutdown
        logger.info("Gateway shutting down")
        await mqtt.publish(
            "oz_a2m/system/health",
            {"status": "down", "service": "gateway"}
        )
        await mqtt.disconnect()
        await redis.disconnect()
        await es.disconnect()
        logger.info("Gateway shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="OZ_A2M Gateway",
    description="AI-Powered Multi-Agent Trading System Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OZA2MError)
async def oz_a2m_exception_handler(request: Request, exc: OZA2MError):
    """Handle OZ_A2M exceptions."""
    logger.error("Request failed", error=exc.message, code=exc.code)
    return JSONResponse(
        status_code=400,
        content={"error": exc.code, "message": exc.message, "details": exc.details},
    )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "OZ_A2M Gateway",
        "version": "0.1.0",
        "environment": settings.environment,
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "gateway",
        "environment": settings.environment,
    }


@app.get("/api/v1/status")
async def system_status():
    """System status endpoint."""
    mqtt = get_mqtt_client()
    redis = get_redis_client()

    return {
        "gateway": "up",
        "mqtt": "connected" if mqtt.is_connected else "disconnected",
        "redis": "connected" if redis._client else "disconnected",
        "environment": settings.environment,
    }


# Import routers
from .routers import agents, market, orders

app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(market.router, prefix="/api/v1/market", tags=["market"])
app.include_router(orders.router, prefix="/api/v1/orders", tags=["orders"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
