"""
WebSocket 브릿지
MQTT 토픽 → WebSocket 실시간 전달

제1부서 게이트웨이에 통합
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


@dataclass
class WSMessage:
    """WebSocket 메시지"""
    topic: str
    payload: Dict
    timestamp: str

    def to_dict(self) -> Dict:
        return {
            'topic': self.topic,
            'payload': self.payload,
            'timestamp': self.timestamp
        }


class WebSocketBridge:
    """
    MQTT to WebSocket 브릿지

    기능:
    - MQTT 토픽 구독
    - WebSocket 클라이언트 관리
    - 실시간 데이터 브로드캐스트
    """

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        enable_mqtt: bool = True
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.enable_mqtt = enable_mqtt

        # MQTT
        self.mqtt_client: Optional[mqtt.Client] = None
        self._mqtt_connected = False

        # WebSocket 연결 관리
        self.connections: Dict[str, Set[WebSocket]] = {
            'market': set(),
            'signals': set(),
            'orders': set(),
            'system': set()
        }

        # 메시지 핸들러
        self.message_handlers: Dict[str, Callable] = {}

    async def connect_mqtt(self):
        """MQTT 연결"""
        if not self.enable_mqtt:
            return

        try:
            self.mqtt_client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2
            )
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_message = self._on_mqtt_message

            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.mqtt_client.loop_start()

            logger.info(f"WebSocketBridge connected to MQTT: {self.mqtt_host}:{self.mqtt_port}")
        except Exception as e:
            logger.error(f"Failed to connect MQTT: {e}")
            self._mqtt_connected = False

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        """MQTT 연결 콜백"""
        if rc == 0:
            self._mqtt_connected = True
            logger.info("WebSocketBridge MQTT connected")

            # 토픽 구독
            self.mqtt_client.subscribe("oz/a2m/market/#")
            self.mqtt_client.subscribe("oz/a2m/signals/#")
            self.mqtt_client.subscribe("oz/a2m/orders/#")
            self.mqtt_client.subscribe("oz/a2m/system/#")
        else:
            logger.error(f"MQTT connection failed: {rc}")

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT 메시지 콜백"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())

            # WebSocket으로 브로드캐스트
            asyncio.create_task(
                self._broadcast_to_ws(topic, payload)
            )
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    async def _broadcast_to_ws(self, topic: str, payload: Dict):
        """WebSocket으로 브로드캐스트"""
        message = WSMessage(
            topic=topic,
            payload=payload,
            timestamp=datetime.now().isoformat()
        )

        data = json.dumps(message.to_dict())

        # 토픽에 따라 적절한 채널로 전송
        if 'market' in topic:
            await self._send_to_channel('market', data)
        elif 'signals' in topic:
            await self._send_to_channel('signals', data)
        elif 'orders' in topic:
            await self._send_to_channel('orders', data)
        else:
            await self._send_to_channel('system', data)

    async def _send_to_channel(self, channel: str, data: str):
        """채널에 메시지 전송"""
        disconnected = set()

        for ws in self.connections.get(channel, set()):
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.add(ws)

        # 연결 끊긴 클라이언트 정리
        for ws in disconnected:
            self.connections[channel].discard(ws)

    async def connect_ws(self, websocket: WebSocket, channel: str):
        """WebSocket 클라이언트 연결"""
        await websocket.accept()

        if channel not in self.connections:
            self.connections[channel] = set()

        self.connections[channel].add(websocket)

        logger.info(f"WebSocket client connected to {channel}. Total: {len(self.connections[channel])}")

        try:
            while True:
                # 클라이언트로부터 메시지 수신 (ping/pong 등)
                data = await websocket.receive_text()
                await self._handle_ws_message(websocket, channel, data)
        except WebSocketDisconnect:
            self.connections[channel].discard(websocket)
            logger.info(f"WebSocket client disconnected from {channel}")

    async def _handle_ws_message(self, websocket: WebSocket, channel: str, data: str):
        """WebSocket 메시지 처리"""
        try:
            message = json.loads(data)
            action = message.get('action')

            if action == 'ping':
                await websocket.send_text(json.dumps({'action': 'pong', 'timestamp': datetime.now().isoformat()}))
            elif action == 'subscribe':
                # 추가 구독 처리
                pass
            elif action == 'unsubscribe':
                # 구독 해제 처리
                pass
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received: {data}")

    async def disconnect_all(self):
        """모든 연결 종료"""
        # WebSocket 연결 종료
        for channel, connections in self.connections.items():
            for ws in connections:
                try:
                    await ws.close()
                except Exception:
                    pass
            connections.clear()

        # MQTT 연결 종료
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        logger.info("WebSocketBridge disconnected all clients")

    def get_stats(self) -> Dict:
        """통계 정보"""
        return {
            'mqtt_connected': self._mqtt_connected,
            'connections': {
                channel: len(connections)
                for channel, connections in self.connections.items()
            },
            'total_connections': sum(
                len(connections)
                for connections in self.connections.values()
            )
        }


# FastAPI 앱용 라우터 설정
from fastapi import APIRouter

router = APIRouter()

# 전역 브릿지 인스턴스
_bridge_instance: Optional[WebSocketBridge] = None


def get_bridge(
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883
) -> WebSocketBridge:
    """전역 브릿지 인스턴스"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = WebSocketBridge(mqtt_host, mqtt_port)
    return _bridge_instance


@router.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """시장 데이터 WebSocket 엔드포인트"""
    bridge = get_bridge()
    await bridge.connect_ws(websocket, 'market')


@router.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket):
    """신호 WebSocket 엔드포인트"""
    bridge = get_bridge()
    await bridge.connect_ws(websocket, 'signals')


@router.websocket("/ws/orders")
async def websocket_orders(websocket: WebSocket):
    """주문 WebSocket 엔드포인트"""
    bridge = get_bridge()
    await bridge.connect_ws(websocket, 'orders')


@router.websocket("/ws/system")
async def websocket_system(websocket: WebSocket):
    """시스템 WebSocket 엔드포인트"""
    bridge = get_bridge()
    await bridge.connect_ws(websocket, 'system')


@router.get("/ws/stats")
async def websocket_stats():
    """WebSocket 통계"""
    bridge = get_bridge()
    return bridge.get_stats()
