"""
Log Streaming API for OZ_A2M
Provides real-time log streaming and filtering
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from typing import List, Optional, AsyncGenerator
from datetime import datetime
import asyncio
import os
import aiofiles

router = APIRouter(prefix="/logs", tags=["logs"])

LOG_PATHS = {
    "gateway": "/home/ozzy-claw/repos/OZ_A2M/mvp/gateway/logs/gateway.log",
    "bots": "/home/ozzy-claw/repos/OZ_A2M/mvp/gateway/logs/bots.log",
    "mqtt": "/home/ozzy-claw/repos/OZ_A2M/mvp/gateway/logs/mqtt.log",
    "system": "/home/ozzy-claw/logs/recovery.log",
}

class LogEntry(BaseModel):
    timestamp: str
    level: str
    source: str
    message: str

class LogFilter(BaseModel):
    level: Optional[str] = None  # DEBUG, INFO, WARNING, ERROR
    source: Optional[str] = None
    search: Optional[str] = None
    since: Optional[str] = None
    limit: int = 100

async def tail_log_file(filepath: str, n: int = 100) -> List[str]:
    """Get last n lines from log file"""
    if not os.path.exists(filepath):
        return []

    lines = []
    try:
        async with aiofiles.open(filepath, mode='r') as f:
            async for line in f:
                lines.append(line.strip())
                if len(lines) > n:
                    lines.pop(0)
    except Exception:
        pass

    return lines

def parse_log_line(line: str, source: str) -> Optional[LogEntry]:
    """Parse a log line into structured format"""
    try:
        # Try to extract timestamp and level
        parts = line.split(' ', 2)
        if len(parts) >= 2:
            timestamp = parts[0]
            level = "INFO"
            message = line

            # Check for log level indicators
            upper_line = line.upper()
            if 'ERROR' in upper_line or 'CRITICAL' in upper_line:
                level = "ERROR"
            elif 'WARNING' in upper_line or 'WARN' in upper_line:
                level = "WARNING"
            elif 'DEBUG' in upper_line:
                level = "DEBUG"

            return LogEntry(
                timestamp=timestamp,
                level=level,
                source=source,
                message=message
            )
    except Exception:
        pass

    return LogEntry(
        timestamp=datetime.now().isoformat(),
        level="INFO",
        source=source,
        message=line
    )

@router.get("/")
async def get_logs(
    source: str = Query(default="gateway", description="Log source"),
    level: Optional[str] = Query(default=None, description="Filter by level"),
    search: Optional[str] = Query(default=None, description="Search term"),
    limit: int = Query(default=100, ge=10, le=1000)
):
    """Get recent logs from a source"""
    filepath = LOG_PATHS.get(source, LOG_PATHS["gateway"])

    if not os.path.exists(filepath):
        return {
            "logs": [],
            "source": source,
            "total": 0,
            "filtered": 0
        }

    lines = await tail_log_file(filepath, limit * 2)
    logs = []

    for line in lines:
        if not line.strip():
            continue

        entry = parse_log_line(line, source)

        # Apply filters
        if level and entry.level != level.upper():
            continue
        if search and search.lower() not in line.lower():
            continue

        logs.append(entry)

        if len(logs) >= limit:
            break

    return {
        "logs": [log.dict() for log in logs],
        "source": source,
        "total": len(lines),
        "filtered": len(logs)
    }

@router.get("/sources")
async def get_log_sources():
    """Get available log sources"""
    sources = []
    for name, path in LOG_PATHS.items():
        sources.append({
            "name": name,
            "path": path,
            "exists": os.path.exists(path),
            "size": os.path.getsize(path) if os.path.exists(path) else 0
        })
    return {"sources": sources}

@router.websocket("/stream/{source}")
async def log_websocket(websocket: WebSocket, source: str):
    """WebSocket endpoint for real-time log streaming"""
    await websocket.accept()

    filepath = LOG_PATHS.get(source, LOG_PATHS["gateway"])
    if not os.path.exists(filepath):
        await websocket.send_json({
            "error": f"Log source '{source}' not found"
        })
        await websocket.close()
        return

    try:
        # Send initial logs
        lines = await tail_log_file(filepath, 50)
        for line in lines:
            if line.strip():
                entry = parse_log_line(line, source)
                await websocket.send_json({
                    "type": "log",
                    "data": entry.dict()
                })

        # Tail the file for new entries
        async with aiofiles.open(filepath, mode='r') as f:
            await f.seek(0, 2)  # Go to end of file

            while True:
                line = await f.readline()
                if line:
                    entry = parse_log_line(line.strip(), source)
                    await websocket.send_json({
                        "type": "log",
                        "data": entry.dict()
                    })
                else:
                    await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })

# Background task to generate sample logs
async def generate_sample_logs():
    """Generate sample logs for testing"""
    import random

    log_dir = "/home/ozzy-claw/repos/OZ_A2M/mvp/gateway/logs"
    os.makedirs(log_dir, exist_ok=True)

    levels = ["INFO", "DEBUG", "WARNING", "ERROR"]
    messages = [
        "Gateway request processed",
        "MQTT message received",
        "Bot signal generated",
        "Trade executed successfully",
        "Connection established",
        "Cache hit ratio: 94%",
        "Latency spike detected",
        "Order book updated",
    ]

    while True:
        await asyncio.sleep(random.uniform(1, 5))

        level = random.choice(levels)
        message = random.choice(messages)
        timestamp = datetime.now().isoformat()

        log_line = f"{timestamp} [{level}] {message}\n"

        try:
            async with aiofiles.open(f"{log_dir}/gateway.log", mode='a') as f:
                await f.write(log_line)
        except Exception:
            pass
