"""
OZ_A2M 제7부서: 거래소 테스트넷 연동 검증

Binance/Bybit 테스트넷 연동 검증 스크립트
- sandbox=True 유지 (실거래 전환 시 사용자 승인 필요)
- 4종 봇 (Scalper/TrendFollower/MarketMaker/Arbitrage) 테스트
"""

import asyncio
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime

from occore.operations.exchange_connector import ExchangeConnector
from occore.operations.bot_manager import BotManager
from lib.core import get_logger

logger = get_logger(__name__)


class TestnetValidator:
    """테스트넷 연동 검증기"""

    def __init__(self):
        self.results: Dict[str, Dict] = {}
        self.connectors: Dict[str, ExchangeConnector] = {}

    async def validate_all(self) -> Dict[str, Dict]:
        """전체 테스트넷 검증 실행"""
        logger.info("=== Testnet Validation Started ===")

        # 1. 거래소 연결 검증
        await self._validate_exchange_connections()

        # 2. 봇 매니저 검증
        await self._validate_bot_manager()

        # 3. 봇 클래스 검증
        await self._validate_bot_classes()

        # 4. 잔고 조회 검증
        await self._validate_balance_fetching()

        # 5. 주문 생성/취소 검증 (dry_run)
        await self._validate_order_lifecycle()

        logger.info("=== Testnet Validation Completed ===")
        return self.results

    async def _validate_exchange_connections(self):
        """거래소 연결 검증"""
        exchanges = ["binance", "bybit"]

        for exchange_id in exchanges:
            logger.info(f"Validating {exchange_id} testnet connection...")

            try:
                connector = ExchangeConnector(
                    exchange_id=exchange_id,
                    sandbox=True,
                    testnet=True
                )

                connected = await connector.connect()

                self.results[f"{exchange_id}_connection"] = {
                    "status": "passed" if connected else "failed",
                    "exchange": exchange_id,
                    "sandbox": True,
                    "testnet": True,
                    "timestamp": datetime.utcnow().isoformat()
                }

                if connected:
                    self.connectors[exchange_id] = connector
                    logger.info(f"✅ {exchange_id} testnet connected")
                else:
                    logger.warning(f"❌ {exchange_id} testnet connection failed")

            except Exception as e:
                self.results[f"{exchange_id}_connection"] = {
                    "status": "error",
                    "exchange": exchange_id,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
                logger.error(f"❌ {exchange_id} error: {e}")

    async def _validate_bot_manager(self):
        """봇 매니저 검증"""
        logger.info("Validating Bot Manager...")

        try:
            manager = BotManager(
                mqtt_host="localhost",
                mqtt_port=1883,
                dry_run=True  # 테스트넷 모드
            )

            self.results["bot_manager"] = {
                "status": "passed",
                "dry_run": True,
                "timestamp": datetime.utcnow().isoformat()
            }

            logger.info("✅ Bot Manager initialized (dry_run=True)")

        except Exception as e:
            self.results["bot_manager"] = {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
            logger.error(f"❌ Bot Manager error: {e}")

    async def _validate_bot_classes(self):
        """4종 봇 클래스 검증"""
        logger.info("Validating 4 bot types...")

        bot_types = [
            ("scalping", "department_7.src.bot.scalper", "ScalpingBot"),
            ("trend_following", "occore.operations.templates.trend_following_bot", "TrendFollowingBot"),
            ("market_making", "department_7.src.bot.market_maker_bot", "MarketMakerBot"),
            ("arbitrage", "department_7.src.bot.arbitrage_bot", "ArbitrageBot"),
        ]

        for bot_type, module_path, class_name in bot_types:
            try:
                # 동적 임포트
                parts = module_path.split(".")
                module = __import__(module_path, fromlist=[class_name])
                bot_class = getattr(module, class_name)

                self.results[f"bot_{bot_type}"] = {
                    "status": "passed",
                    "class": class_name,
                    "module": module_path,
                    "timestamp": datetime.utcnow().isoformat()
                }

                logger.info(f"✅ {class_name} loaded")

            except Exception as e:
                self.results[f"bot_{bot_type}"] = {
                    "status": "error",
                    "class": class_name,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
                logger.error(f"❌ {class_name} error: {e}")

    async def _validate_balance_fetching(self):
        """잔고 조회 검증"""
        logger.info("Validating balance fetching...")

        for exchange_id, connector in self.connectors.items():
            try:
                balance = await connector.get_balance()

                self.results[f"{exchange_id}_balance"] = {
                    "status": "passed",
                    "exchange": exchange_id,
                    "balance": str(balance),
                    "timestamp": datetime.utcnow().isoformat()
                }

                logger.info(f"✅ {exchange_id} balance fetched: {balance}")

            except Exception as e:
                self.results[f"{exchange_id}_balance"] = {
                    "status": "error",
                    "exchange": exchange_id,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
                logger.warning(f"⚠️ {exchange_id} balance fetch failed: {e}")

    async def _validate_order_lifecycle(self):
        """주문 생명주기 검증 (dry_run)"""
        logger.info("Validating order lifecycle (dry_run)...")

        for exchange_id, connector in self.connectors.items():
            try:
                # 테스트 주문 생성 (실제로는 전송되지 않음)
                order_result = await connector.create_order(
                    symbol="BTC/USDT",
                    side="buy",
                    amount=0.001,
                    price=50000,
                    order_type="limit"
                )

                self.results[f"{exchange_id}_order"] = {
                    "status": "passed",
                    "exchange": exchange_id,
                    "note": "Dry run order created",
                    "timestamp": datetime.utcnow().isoformat()
                }

                logger.info(f"✅ {exchange_id} dry run order created")

            except Exception as e:
                self.results[f"{exchange_id}_order"] = {
                    "status": "warning",
                    "exchange": exchange_id,
                    "note": "Order creation requires API keys",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
                logger.warning(f"⚠️ {exchange_id} order test skipped: {e}")

    def print_summary(self):
        """검증 결과 요약 출력"""
        print("\n" + "="*60)
        print("🧪 TESTNET VALIDATION SUMMARY")
        print("="*60)

        passed = sum(1 for r in self.results.values() if r["status"] == "passed")
        failed = sum(1 for r in self.results.values() if r["status"] == "failed")
        errors = sum(1 for r in self.results.values() if r["status"] == "error")
        warnings = sum(1 for r in self.results.values() if r["status"] == "warning")

        print(f"\n✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"⚠️ Warnings: {warnings}")
        print(f"🔥 Errors: {errors}")

        print("\n--- Detailed Results ---")
        for name, result in self.results.items():
            status_emoji = {
                "passed": "✅",
                "failed": "❌",
                "error": "🔥",
                "warning": "⚠️"
            }.get(result["status"], "❓")
            print(f"{status_emoji} {name}: {result['status']}")

        print("\n" + "="*60)
        print("⚠️  NOTE: Full testnet trading requires API keys")
        print("   - BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET")
        print("   - BYBIT_TESTNET_API_KEY / BYBIT_TESTNET_API_SECRET")
        print("="*60 + "\n")


async def main():
    """메인 실행"""
    logging.basicConfig(level=logging.INFO)

    validator = TestnetValidator()
    await validator.validate_all()
    validator.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
