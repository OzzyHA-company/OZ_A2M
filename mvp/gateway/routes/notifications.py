"""
Notification System for OZ_A2M
WebSocket-based real-time notifications
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import json
import asyncio

router = APIRouter(prefix="/notifications", tags=["notifications"])

class Notification(BaseModel):
    id: str
    type: str  # info, warning, error, success
    title: str
    message: str
    timestamp: str
    read: bool = False
    source: str  # system, bot, department, trade
    metadata: Optional[dict] = None

class NotificationManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.notification_history: List[Notification] = []
        self.max_history = 100

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send recent history on connect
        recent = self.notification_history[-20:]
        await websocket.send_json({
            "type": "history",
            "notifications": [n.dict() for n in recent]
        })

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, notification: Notification):
        # Add to history
        self.notification_history.append(notification)
        if len(self.notification_history) > self.max_history:
            self.notification_history = self.notification_history[-self.max_history:]

        # Broadcast to all connected clients
        message = {
            "type": "notification",
            "notification": notification.dict()
        }

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    def get_unread_count(self) -> int:
        return sum(1 for n in self.notification_history if not n.read)

    def mark_all_read(self):
        for n in self.notification_history:
            n.read = True

    def get_notifications(self, limit: int = 50, unread_only: bool = False) -> List[Notification]:
        notifications = self.notification_history
        if unread_only:
            notifications = [n for n in notifications if not n.read]
        return notifications[-limit:]

# Global notification manager
notification_manager = NotificationManager()

@router.websocket("/ws")
async def notification_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time notifications"""
    await notification_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("action") == "mark_read":
                    notification_manager.mark_all_read()
                    await websocket.send_json({"type": "marked_read"})
                elif message.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        notification_manager.disconnect(websocket)

@router.get("/")
async def get_notifications(limit: int = 50, unread_only: bool = False):
    """Get notification history"""
    notifications = notification_manager.get_notifications(limit, unread_only)
    return {
        "notifications": [n.dict() for n in notifications],
        "unread_count": notification_manager.get_unread_count(),
        "total_count": len(notification_manager.notification_history)
    }

@router.post("/mark-read")
async def mark_all_read():
    """Mark all notifications as read"""
    notification_manager.mark_all_read()
    return {"status": "success", "unread_count": 0}

@router.post("/trigger")
async def trigger_notification(notification: Notification):
    """Trigger a new notification (internal API)"""
    await notification_manager.broadcast(notification)
    return {"status": "broadcasted", "notification_id": notification.id}

# Helper function to create notifications
async def notify(
    notif_type: str,
    title: str,
    message: str,
    source: str = "system",
    metadata: Optional[dict] = None
):
    """Create and broadcast a notification"""
    notification = Notification(
        id=f"notif_{datetime.now().timestamp()}",
        type=notif_type,
        title=title,
        message=message,
        timestamp=datetime.now().isoformat(),
        source=source,
        metadata=metadata or {}
    )
    await notification_manager.broadcast(notification)
    return notification

# Background task for system monitoring alerts
async def monitor_alerts():
    """Background task to send periodic system alerts"""
    import random
    alerts = [
        ("info", "System Check", "All systems operational"),
        ("success", "Trade Executed", "BTC/USDT long position opened"),
        ("warning", "High Latency", "Gateway latency above 100ms"),
        ("error", "Connection Failed", "Exchange API timeout"),
    ]

    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        if notification_manager.active_connections:
            # Randomly send test notifications
            if random.random() < 0.3:  # 30% chance
                alert = random.choice(alerts)
                await notify(alert[0], alert[1], alert[2], "system")
