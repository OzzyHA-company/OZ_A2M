"""
WebSocket 브릿지 테스트

STEP 3: Trend Following 봇 + WebSocket 브릿지
"""

import pytest
import json
import asyncio
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from lib.messaging.websocket_bridge import (
    WebSocketBridge,
    WSMessage,
    get_bridge
)


class TestWSMessage:
    """WSMessage 데이터클스 테스트"""

    def test_ws_message_creation(self):
        """WSMessage 생성 테스트"""
        msg = WSMessage(
            topic='oz/a2m/market/BTCUSDT',
            payload={'price': 50000.0, 'volume': 100.0},
            timestamp='2024-03-28T10:00:00'
        )

        assert msg.topic == 'oz/a2m/market/BTCUSDT'
        assert msg.payload['price'] == 50000.0

    def test_ws_message_to_dict(self):
        """WSMessage 직렬화 테스트"""
        msg = WSMessage(
            topic='test/topic',
            payload={'data': 'value'},
            timestamp='2024-03-28T10:00:00'
        )

        data = msg.to_dict()
        assert data['topic'] == 'test/topic'
        assert data['payload'] == {'data': 'value'}
        assert data['timestamp'] == '2024-03-28T10:00:00'


class TestWebSocketBridge:
    """WebSocketBridge 테스트"""

    @pytest.fixture
    def bridge(self):
        """테스트용 브릿지 인스턴스"""
        return WebSocketBridge(
            mqtt_host='localhost',
            mqtt_port=1883,
            enable_mqtt=False  # MQTT 비활성화 (테스트용)
        )

    @pytest.fixture
    def mock_websocket(self):
        """Mock WebSocket"""
        ws = Mock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        ws.receive_text = AsyncMock(return_value='{"action": "ping"}')
        ws.close = AsyncMock()
        return ws

    def test_bridge_initialization(self, bridge):
        """브릿지 초기화 테스트"""
        assert bridge.mqtt_host == 'localhost'
        assert bridge.mqtt_port == 1883
        assert bridge.enable_mqtt is False
        assert bridge._mqtt_connected is False

    def test_get_stats_empty(self, bridge):
        """빈 통계 테스트"""
        stats = bridge.get_stats()

        assert stats['mqtt_connected'] is False
        assert stats['total_connections'] == 0
        assert 'market' in stats['connections']
        assert 'signals' in stats['connections']
        assert 'orders' in stats['connections']
        assert 'system' in stats['connections']

    @pytest.mark.asyncio
    async def test_connect_ws(self, bridge, mock_websocket):
        """WebSocket 연결 테스트"""
        # receive_text가 disconnect 되도록 설정
        from fastapi import WebSocketDisconnect
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        # 미리 connections에 추가 (accept 호출 직후)
        bridge.connections['market'].add(mock_websocket)

        # 연결
        task = asyncio.create_task(
            bridge.connect_ws(mock_websocket, 'market')
        )

        # 잠시 대기
        await asyncio.sleep(0.1)

        # 검증
        mock_websocket.accept.assert_called_once()

        # 정리
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_broadcast_to_ws_market(self, bridge, mock_websocket):
        """시장 데이터 브로드캐스트 테스트"""
        bridge.connections['market'].add(mock_websocket)

        await bridge._broadcast_to_ws(
            'oz/a2m/market/BTCUSDT',
            {'price': 50000.0, 'volume': 100.0}
        )

        # 메시지 전송 확인
        mock_websocket.send_text.assert_called_once()
        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data['topic'] == 'oz/a2m/market/BTCUSDT'
        assert sent_data['payload']['price'] == 50000.0

    @pytest.mark.asyncio
    async def test_broadcast_to_ws_signals(self, bridge, mock_websocket):
        """신호 브로드캐스트 테스트"""
        bridge.connections['signals'].add(mock_websocket)

        await bridge._broadcast_to_ws(
            'oz/a2m/signals/bot_001',
            {'action': 'BUY', 'price': 50000.0}
        )

        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert 'signals' in sent_data['topic']

    @pytest.mark.asyncio
    async def test_broadcast_with_disconnected_client(self, bridge, mock_websocket):
        """연결 끊긴 클라이언트 처리 테스트"""
        # 첫 번째 호출에서 에러 발생
        mock_websocket.send_text.side_effect = Exception("Connection closed")

        bridge.connections['market'].add(mock_websocket)

        await bridge._broadcast_to_ws(
            'oz/a2m/market/BTCUSDT',
            {'price': 50000.0}
        )

        # 연결 끊긴 클라이언트가 제거되었는지 확인
        assert mock_websocket not in bridge.connections['market']

    @pytest.mark.asyncio
    async def test_handle_ws_message_ping(self, bridge, mock_websocket):
        """WebSocket ping 메시지 처리 테스트"""
        await bridge._handle_ws_message(
            mock_websocket,
            'market',
            '{"action": "ping"}'
        )

        # pong 응답 확인
        mock_websocket.send_text.assert_called_once()
        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data['action'] == 'pong'
        assert 'timestamp' in sent_data

    @pytest.mark.asyncio
    async def test_handle_ws_message_invalid_json(self, bridge, mock_websocket):
        """잘못된 JSON 처리 테스트"""
        # 에러가 발생하지 않아야 함
        await bridge._handle_ws_message(
            mock_websocket,
            'market',
            'invalid json{'
        )

    @pytest.mark.asyncio
    async def test_disconnect_all(self, bridge, mock_websocket):
        """모든 연결 종료 테스트"""
        bridge.connections['market'].add(mock_websocket)
        bridge.connections['signals'].add(mock_websocket)

        await bridge.disconnect_all()

        # 모든 WebSocket이 닫혔는지 확인
        assert mock_websocket.close.call_count == 2
        assert len(bridge.connections['market']) == 0
        assert len(bridge.connections['signals']) == 0


class TestGetBridge:
    """get_bridge 함수 테스트"""

    def test_get_bridge_singleton(self):
        """싱글톤 패턴 테스트"""
        bridge1 = get_bridge(mqtt_host='host1', mqtt_port=1883)
        bridge2 = get_bridge(mqtt_host='host2', mqtt_port=1884)

        # 같은 인스턴스여야 함
        assert bridge1 is bridge2
        # 첫 번째 설정이 유지되어야 함
        assert bridge1.mqtt_host == 'host1'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
