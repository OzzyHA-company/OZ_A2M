"""
OZ_A2M FastAPI Gateway
MQTT + FastAPI 기반 중앙 게이트웨이
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt
import structlog
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Import LLM Router
from llm_router import router as llm_router

# Import Bots Router
from routes.bots import router as bots_router

# 로깅 설정
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus Metrics
REQUEST_COUNT = Counter(
    'gateway_requests_total',
    'Total requests',
    ['method', 'endpoint', 'status']
)
REQUEST_LATENCY = Histogram(
    'gateway_request_duration_seconds',
    'Request latency',
    ['method', 'endpoint']
)
MQTT_MESSAGES = Counter(
    'gateway_mqtt_messages_total',
    'MQTT messages',
    ['topic', 'direction']
)

# 설정
MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
API_PORT = int(os.getenv('API_PORT', 8000))
ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')

# MQTT 클라이언트
mqtt_client: Optional[mqtt.Client] = None


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Prometheus 메트릭 미들웨어"""

    async def dispatch(self, request: Request, call_next):
        start_time = datetime.utcnow()

        response = await call_next(request)

        latency = (datetime.utcnow() - start_time).total_seconds()
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(latency)

        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()

        return response


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    """MQTT 연결 콜백"""
    if rc == 0:
        logger.info("MQTT connected", host=MQTT_HOST, port=MQTT_PORT)
        # 구독 설정
        client.subscribe("oz/a2m/+/signal")
        client.subscribe("oz/a2m/+/status")
        client.subscribe("oz/a2m/+/log")
    else:
        logger.error("MQTT connection failed", rc=rc)


def on_mqtt_message(client, userdata, msg):
    """MQTT 메시지 콜백"""
    MQTT_MESSAGES.labels(topic=msg.topic, direction='received').inc()
    try:
        payload = json.loads(msg.payload.decode())
        logger.info(
            "MQTT message received",
            topic=msg.topic,
            payload=payload
        )
    except json.JSONDecodeError:
        logger.warning(
            "MQTT non-JSON message received",
            topic=msg.topic,
            payload=msg.payload.decode()
        )


def on_mqtt_disconnect(client, userdata, rc, properties=None):
    """MQTT 연결 해제 콜백"""
    logger.warning("MQTT disconnected", rc=rc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 생명주기 관리"""
    global mqtt_client

    # 시작 시
    logger.info("Starting OZ_A2M Gateway", environment=ENVIRONMENT)

    # MQTT 클라이언트 설정
    mqtt_client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"oz_a2m_gateway_{API_PORT}"
    )
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    mqtt_client.on_disconnect = on_mqtt_disconnect

    # MQTT 연결
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        logger.info("MQTT client started")
    except Exception as e:
        logger.error("MQTT connection error", error=str(e))

    yield

    # 종료 시
    logger.info("Shutting down OZ_A2M Gateway")
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


# FastAPI 앱 생성
app = FastAPI(
    title="OZ_A2M Gateway",
    description="AI Agent to Market - Central Gateway",
    version="1.0.0",
    lifespan=lifespan
)

# 미들웨어
app.add_middleware(PrometheusMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT == 'development' else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== API Endpoints =====

@app.get("/health")
async def health_check():
    """헬스 체크"""
    mqtt_status = "connected" if mqtt_client and mqtt_client.is_connected() else "disconnected"
    return {
        "status": "healthy",
        "mqtt": mqtt_status,
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "service": "OZ_A2M Gateway",
        "version": "1.0.0",
        "environment": ENVIRONMENT,
        "docs": "/docs"
    }


@app.get("/metrics")
async def metrics():
    """Prometheus 메트릭"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


# Department Endpoints
@app.post("/api/v1/signal")
async def publish_signal(signal: Dict[str, Any]):
    """매매 신호 발행"""
    if not mqtt_client or not mqtt_client.is_connected():
        raise HTTPException(status_code=503, detail="MQTT not connected")

    try:
        topic = f"oz/a2m/signal/{signal.get('department', 'unknown')}"
        payload = json.dumps(signal)
        mqtt_client.publish(topic, payload, qos=1)
        MQTT_MESSAGES.labels(topic=topic, direction='sent').inc()

        logger.info("Signal published", topic=topic, signal=signal)
        return {"status": "published", "topic": topic}

    except Exception as e:
        logger.error("Failed to publish signal", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/status/{department}")
async def get_department_status(department: str):
    """부서 상태 조회"""
    # TODO: 실제 상태 조회 로직 구현
    return {
        "department": department,
        "status": "active",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/v1/command/{department}")
async def send_command(department: str, command: Dict[str, Any]):
    """부서에 명령 전송"""
    if not mqtt_client or not mqtt_client.is_connected():
        raise HTTPException(status_code=503, detail="MQTT not connected")

    try:
        topic = f"oz/a2m/command/{department}"
        payload = json.dumps(command)
        mqtt_client.publish(topic, payload, qos=1)
        MQTT_MESSAGES.labels(topic=topic, direction='sent').inc()

        logger.info("Command sent", topic=topic, command=command)
        return {"status": "sent", "topic": topic}

    except Exception as e:
        logger.error("Failed to send command", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 실시간 연결"""
    await websocket.accept()
    logger.info("WebSocket client connected")

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # Echo back with timestamp
            response = {
                "type": "echo",
                "received": message,
                "timestamp": datetime.utcnow().isoformat()
            }
            await websocket.send_json(response)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))

# Include LLM Router
app.include_router(llm_router)

# Include Bots Router
app.include_router(bots_router, prefix="/api/v1")


# ===== Bot Management Endpoints =====

# 봇 레지스트리 (실제 구현에서는 DB 사용)
_registered_bots: Dict[str, Dict[str, Any]] = {
    "scalping_bot_001": {
        "bot_id": "scalping_bot_001",
        "name": "Scalping Bot",
        "type": "scalping",
        "symbol": "BTC/USDT",
        "status": "running",
        "timeframe": "1m",
        "last_seen": datetime.utcnow().isoformat()
    },
    "trend_follower_001": {
        "bot_id": "trend_follower_001",
        "name": "Trend Follower",
        "type": "trend_following",
        "symbol": "BTC/USDT",
        "status": "stopped",
        "timeframe": "15m",
        "last_seen": None
    }
}


@app.get("/bots")
async def get_all_bots():
    """전체 봇 목록 조회"""
    return {
        "bots": list(_registered_bots.values()),
        "count": len(_registered_bots),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/bots/{bot_id}")
async def get_bot_status(bot_id: str):
    """특정 봇 상태 조회"""
    if bot_id not in _registered_bots:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    bot = _registered_bots[bot_id].copy()
    bot["timestamp"] = datetime.utcnow().isoformat()

    return bot


@app.post("/bots/{bot_id}/start")
async def start_bot(bot_id: str):
    """봇 시작"""
    if bot_id not in _registered_bots:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    if not mqtt_client or not mqtt_client.is_connected():
        raise HTTPException(status_code=503, detail="MQTT not connected")

    try:
        # MQTT로 시작 명령 발행
        topic = f"oz/a2m/command/{bot_id}"
        command = {
            "command": "start",
            "timestamp": datetime.utcnow().isoformat()
        }
        mqtt_client.publish(topic, json.dumps(command), qos=1)

        # 상태 업데이트
        _registered_bots[bot_id]["status"] = "starting"
        _registered_bots[bot_id]["last_seen"] = datetime.utcnow().isoformat()

        logger.info("Bot start command sent", bot_id=bot_id)
        return {
            "status": "starting",
            "bot_id": bot_id,
            "message": f"Start command sent to {bot_id}"
        }

    except Exception as e:
        logger.error("Failed to start bot", bot_id=bot_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bots/{bot_id}/stop")
async def stop_bot(bot_id: str):
    """봇 중지"""
    if bot_id not in _registered_bots:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    if not mqtt_client or not mqtt_client.is_connected():
        raise HTTPException(status_code=503, detail="MQTT not connected")

    try:
        # MQTT로 중지 명령 발행
        topic = f"oz/a2m/command/{bot_id}"
        command = {
            "command": "stop",
            "timestamp": datetime.utcnow().isoformat()
        }
        mqtt_client.publish(topic, json.dumps(command), qos=1)

        # 상태 업데이트
        _registered_bots[bot_id]["status"] = "stopping"

        logger.info("Bot stop command sent", bot_id=bot_id)
        return {
            "status": "stopping",
            "bot_id": bot_id,
            "message": f"Stop command sent to {bot_id}"
        }

    except Exception as e:
        logger.error("Failed to stop bot", bot_id=bot_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bots/{bot_id}/performance")
async def get_bot_performance(bot_id: str, days: int = 7):
    """봇 성과 조회"""
    if bot_id not in _registered_bots:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    # TODO: 실제 성과 DB 연동
    return {
        "bot_id": bot_id,
        "period_days": days,
        "pnl": 0.0,
        "trades": 0,
        "win_rate": 0.0,
        "message": "Performance data not yet implemented"
    }


# WebSocket 브릿지 라우터 임포트
try:
    from lib.messaging.websocket_bridge import router as ws_bridge_router
    app.include_router(ws_bridge_router, prefix="/ws")
    logger.info("WebSocket bridge router loaded")
except ImportError as e:
    logger.warning("WebSocket bridge not available", error=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_PORT,
        reload=ENVIRONMENT == 'development',
        workers=1 if ENVIRONMENT == 'development' else 4
    )
