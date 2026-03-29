"""Agent management router with Redis registry."""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import datetime

from lib.core import get_logger
from lib.cache import get_redis_cache

router = APIRouter()
logger = get_logger(__name__)

# Redis 캐시 인스턴스
_redis_cache = None


async def _get_cache():
    """Redis 캐시 인스턴스 가져오기 (지연 초기화)"""
    global _redis_cache
    if _redis_cache is None:
        _redis_cache = get_redis_cache(host="localhost", port=6379, db=0)
        await _redis_cache.connect()
    return _redis_cache


@router.get("/")
async def list_agents():
    """List all active agents from Redis registry."""
    cache = await _get_cache()
    agents = await cache.list_agents()

    if not agents:
        # Redis에 데이터가 없을 경우 기본값 반환
        return {
            "agents": [
                {"id": "d1-market", "department": "1", "status": "active", "role": "market_analysis"},
                {"id": "d2-strategy", "department": "2", "status": "active", "role": "strategy"},
                {"id": "d3-risk", "department": "3", "status": "active", "role": "risk_management"},
                {"id": "d4-portfolio", "department": "4", "status": "active", "role": "portfolio"},
                {"id": "d5-data", "department": "5", "status": "active", "role": "data_management"},
                {"id": "d6-system", "department": "6", "status": "active", "role": "system_ops"},
                {"id": "d7-trading", "department": "7", "status": "active", "role": "trading_execution"},
            ],
            "source": "default"
        }

    return {"agents": agents, "source": "redis", "count": len(agents)}


@router.post("/register")
async def register_agent(
    agent_id: str,
    department: str,
    role: str,
    status: str = "active",
    metadata: Dict[str, Any] = None
):
    """Register a new agent to Redis registry."""
    cache = await _get_cache()
    await cache.register_agent(
        agent_id=agent_id,
        department=department,
        role=role,
        status=status,
        metadata=metadata or {}
    )
    logger.info(f"Agent registered: {agent_id}")
    return {
        "status": "registered",
        "agent_id": agent_id,
        "department": department,
        "role": role
    }


@router.post("/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str):
    """Update agent heartbeat."""
    cache = await _get_cache()
    await cache.update_agent_heartbeat(agent_id)
    return {"status": "ok", "agent_id": agent_id, "timestamp": datetime.utcnow().isoformat()}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get agent details from Redis."""
    cache = await _get_cache()
    agent = await cache.get_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    return agent


@router.post("/{agent_id}/command")
async def send_command(agent_id: str, command: Dict[str, Any]):
    """Send command to agent via MQTT."""
    from lib.messaging import get_mqtt_client

    mqtt = get_mqtt_client()
    action = command.get("action", "unknown")

    await mqtt.publish(
        f"oz_a2m/agents/{agent_id}/command",
        {
            "action": action,
            "payload": command.get("payload", {}),
            "timestamp": datetime.utcnow().isoformat()
        }
    )

    logger.info("Agent command sent", agent_id=agent_id, command=action)
    return {"status": "sent", "agent_id": agent_id, "command": command}


@router.post("/{agent_id}/status")
async def set_agent_status(agent_id: str, status: str):
    """Update agent status."""
    cache = await _get_cache()
    await cache.set_agent_status(agent_id, status)
    logger.info(f"Agent status updated: {agent_id} -> {status}")
    return {"status": "updated", "agent_id": agent_id, "new_status": status}


@router.post("/{agent_id}/broadcast")
async def broadcast_message(agent_id: str, message: Dict[str, Any]):
    """Broadcast message to all departments."""
    from lib.messaging import get_mqtt_client

    mqtt = get_mqtt_client()
    await mqtt.publish(
        f"oz_a2m/agents/{agent_id}/broadcast",
        {
            **message,
            "from": agent_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    return {"status": "broadcasted", "from": agent_id}
