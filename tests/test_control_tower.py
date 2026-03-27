#!/usr/bin/env python3
"""
OZ_A2M 제1부서: 관제탑센터 테스트 스크립트
"""
import os
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from occore.control_tower import (
    DataCollector, SituationBoard, AlertManager,
    AlertLevel, AlertCategory, DataNormalizer
)


async def test_data_normalizer():
    """데이터 정제 테스트"""
    print("\n" + "="*50)
    print("[1/5] Data Normalizer 테스트")
    print("="*50)

    normalizer = DataNormalizer()

    # 가격 정제 테스트
    from decimal import Decimal
    from occore.control_tower.exchange_adapter import TickerData

    ticker = TickerData(
        symbol="BTC-USDT",
        exchange="test_exchange",
        timestamp=datetime.now(),
        bid=Decimal("50000.123456789"),
        ask=Decimal("50001.987654321"),
        last=Decimal("50000.555555555"),
        volume_24h=Decimal("1234.567890123"),
        change_24h_pct=5.5,
        high_24h=Decimal("51000.0"),
        low_24h=Decimal("49000.0")
    )

    normalized = normalizer.normalize_ticker(ticker)
    print(f"✓ Ticker normalized")
    print(f"  Original last: {ticker.last}")
    print(f"  Normalized last: {normalized.last}")

    print("\n✅ Data Normalizer 테스트 완료")


async def test_alert_manager():
    """알림 관리자 테스트"""
    print("\n" + "="*50)
    print("[2/5] Alert Manager 테스트")
    print("="*50)

    alert_mgr = AlertManager()

    # 알림 생성
    alert = alert_mgr.create_alert(
        level=AlertLevel.HIGH,
        category=AlertCategory.PRICE,
        title="BTC 가격 급등",
        message="BTC 가격이 24시간 내 10% 상승했습니다.",
        source="test_system"
    )
    print(f"✓ Alert created: {alert.id if alert else 'None'}")

    # 중복 알림 방지 테스트
    alert2 = alert_mgr.create_alert(
        level=AlertLevel.HIGH,
        category=AlertCategory.PRICE,
        title="BTC 가격 급등",
        message="BTC 가격이 24시간 내 10% 상승했습니다.",
        source="test_system"
    )
    print(f"✓ Duplicate alert suppressed: {alert2 is None}")

    # 알림 요약
    summary = alert_mgr.get_alert_summary()
    print(f"✓ Active alerts: {summary['total_active']}")
    print(f"✓ By level: {summary['by_level']}")

    print("\n✅ Alert Manager 테스트 완료")


async def test_collector_config():
    """데이터 수집기 설정 테스트"""
    print("\n" + "="*50)
    print("[3/5] Data Collector 설정 테스트")
    print("="*50)

    config = {
        'cache_ttl_seconds': 5,
        'collection_interval_seconds': 10,
        'fetch_orderbook': False,
        'fetch_trades': False
    }

    collector = DataCollector(config)
    print(f"✓ DataCollector created with config")
    print(f"  Cache TTL: {collector._cache_ttl}s")
    print(f"  Collection interval: {collector._collection_interval}s")

    print("\n✅ Data Collector 설정 테스트 완료")


async def test_situation_board_config():
    """전황판 설정 테스트"""
    print("\n" + "="*50)
    print("[4/5] Situation Board 설정 테스트")
    print("="*50)

    config = {
        'cache_ttl_seconds': 5,
        'collection_interval_seconds': 10
    }

    collector = DataCollector(config)
    alert_mgr = AlertManager()

    board_config = {
        'update_interval_seconds': 5
    }

    board = SituationBoard(collector, alert_mgr, board_config)
    print(f"✓ SituationBoard created")
    print(f"  Update interval: {board._update_interval}s")

    # 시장 요약 (빈 상태)
    summary = board.get_market_summary()
    print(f"✓ Market summary: {summary if summary else 'Empty (expected)'}")

    print("\n✅ Situation Board 설정 테스트 완료")


async def test_exchange_adapter_factory():
    """거래소 어댑터 팩토리 테스트"""
    print("\n" + "="*50)
    print("[5/5] Exchange Adapter Factory 테스트")
    print("="*50)

    from occore.control_tower.exchange_adapter import AdapterFactory

    # CCXT 지원 거래소 목록 확인
    exchanges = AdapterFactory.get_supported_ccxt_exchanges()
    print(f"✓ CCXT supports {len(exchanges)} exchanges")
    print(f"  Sample: {exchanges[:5]}")

    # 어댑터 생성 (연결 없이)
    try:
        adapter = AdapterFactory.create_adapter('binance', 'ccxt')
        print(f"✓ Binance adapter created (not connected)")
        print(f"  Exchange ID: {adapter.exchange_id}")
        print(f"  Connected: {adapter.is_connected}")
    except Exception as e:
        print(f"⚠ Adapter creation: {e}")

    print("\n✅ Exchange Adapter Factory 테스트 완료")


async def main():
    """메인 테스트 함수"""
    print("\n" + "="*60)
    print("  OZ_A2M 관제탑센터 (제1부서) 테스트")
    print("="*60)

    try:
        await test_data_normalizer()
        await test_alert_manager()
        await test_collector_config()
        await test_situation_board_config()
        await test_exchange_adapter_factory()

        print("\n" + "="*60)
        print("  ✅ 모든 관제탑센터 테스트 완료!")
        print("="*60)
        return 0

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
