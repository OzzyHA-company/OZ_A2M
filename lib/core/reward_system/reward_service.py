"""
Reward Service - 통합 보상 시스템 서비스

department_6 (R&D Team)과 통합
MQTT 기반 실시간 보상 계산 및 RPG 업데이트

Features:
- 실시간 거래 기록 수신 (MQTT)
- 주간/일간 보상 계산
- RPG 시스템 업데이트 (Level/Grade/HP)
- 자본 재배분 실행
- 에피소드 메모리 관리
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import aiomqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lib.core.logger import get_logger
from lib.core.tracer import get_tracer

from .reward_calculator import RewardCalculator, RewardResult, RewardType, TradeRecord
from .rpg_system import RPGSystem, BotRPGState
from .bot_classifier import BotClassifier, BotType, DEFAULT_BOT_CONFIGS
from .capital_allocator import CapitalAllocator
from .episode_memory import EpisodeMemory, MarketContext, BotAction, EpisodeResult

logger = get_logger(__name__)
tracer = get_tracer("reward_service")


class RewardService:
    """
    통합 보상 시스템 서비스

    OZ_A2M 전체 봇 성과 관리의 중앙 허브
    """

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        total_capital: float = 97.79,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # 핵심 컴포넌트
        self.calculator = RewardCalculator()
        self.rpg_system = RPGSystem()
        self.classifier = BotClassifier()
        self.capital_allocator = CapitalAllocator(total_capital=total_capital)
        self.episode_memory = EpisodeMemory()

        # 상태
        self._running = False
        self._mqtt_client = None
        self.trade_buffer: Dict[str, List[TradeRecord]] = {}  # 봇별 거래 버퍼
        self.last_reward_calc: Dict[str, datetime] = {}

        # 스케줄
        self.daily_calc_hour = 1  # 새벽 1시
        self.weekly_learning_day = 0  # 일요일

        self.logger = logging.getLogger(self.__class__.__name__)

        # 기본 봇 등록
        self._register_default_bots()

    def _register_default_bots(self):
        """OZ_A2M 기본 11봇 등록"""
        for config in DEFAULT_BOT_CONFIGS:
            bot_id = config["bot_id"]
            bot_name = config["name"]
            capital = config["capital_usd"]

            # 자본 배분 등록
            self.capital_allocator.register_bot(bot_id, capital)

            # 봇 유형 분류
            bot_type = self.classifier.classify(bot_id, bot_name)
            self.classifier.create_profile(
                bot_id=bot_id,
                bot_name=bot_name,
                exchange=config["exchange"],
                symbols=config["symbols"],
                capital_usd=capital,
            )

            self.logger.info(f"Registered {bot_id} ({bot_type.value}) with ${capital}")

    async def start(self):
        """서비스 시작"""
        self._running = True
        self.logger.info("Starting Reward Service...")

        # 상태 로드
        self.rpg_system.load()
        self.capital_allocator.load()
        self.episode_memory.load()

        # 태스크 시작
        tasks = [
            asyncio.create_task(self._mqtt_listener()),
            asyncio.create_task(self._daily_reward_scheduler()),
            asyncio.create_task(self._weekly_learning_scheduler()),
            asyncio.create_task(self._hp_recovery_scheduler()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self.logger.info("Service tasks cancelled")
        finally:
            await self.stop()

    async def stop(self):
        """서비스 중지"""
        self.logger.info("Stopping Reward Service...")
        self._running = False

        # 상태 저장
        self.rpg_system.save()
        self.capital_allocator.save()
        self.episode_memory.save()

    async def _mqtt_listener(self):
        """MQTT 메시지 리스너"""
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    client_id="reward_service",
                ) as client:
                    self._mqtt_client = client
                    self.logger.info("Reward service connected to MQTT")

                    # 토픽 구독
                    await client.subscribe("oz/a2m/bots/+/trade")
                    await client.subscribe("oz/a2m/bots/+/status")
                    await client.subscribe("oz/a2m/commands/reward")

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except aiomqtt.MqttError as e:
                self.logger.error(f"MQTT error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                self.logger.error(f"MQTT listener error: {e}")
                await asyncio.sleep(5)

    async def _handle_message(self, message):
        """MQTT 메시지 처리"""
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())

            if "/trade" in topic:
                # 거래 기록 수신
                await self._handle_trade_message(topic, payload)
            elif "/status" in topic:
                # 상태 업데이트
                await self._handle_status_message(topic, payload)
            elif "command" in topic:
                # 명령 처리
                await self._handle_command(payload)

        except Exception as e:
            self.logger.error(f"Message handling error: {e}")

    async def _handle_trade_message(self, topic: str, payload: Dict):
        """거래 메시지 처리"""
        # 봇 ID 추출 (oz/a2m/bots/{bot_id}/trade)
        parts = topic.split("/")
        if len(parts) < 5:
            return

        bot_id = parts[3]

        # 거래 기록 생성
        trade = TradeRecord(
            timestamp=datetime.fromisoformat(payload.get("timestamp", datetime.utcnow().isoformat())),
            pnl=payload.get("pnl", 0),
            pnl_pct=payload.get("pnl_pct", 0),
            position_size=payload.get("position_size", 0),
            holding_period=payload.get("holding_hours", 0),
            win=payload.get("pnl", 0) > 0,
        )

        # 버퍼에 추가
        if bot_id not in self.trade_buffer:
            self.trade_buffer[bot_id] = []
        self.trade_buffer[bot_id].append(trade)

        # 최근 100개만 유지
        if len(self.trade_buffer[bot_id]) > 100:
            self.trade_buffer[bot_id] = self.trade_buffer[bot_id][-100:]

        # RPG 업데이트
        profile = self.classifier.get_profile(bot_id)
        bot_name = profile.bot_name if profile else bot_id

        rpg_update = self.rpg_system.update_from_trade(
            bot_id=bot_id,
            pnl=trade.pnl,
            win=trade.win,
            bot_name=bot_name,
        )

        # HP 0 체크 (재심사 필요)
        if rpg_update.get('died'):
            self.logger.warning(f"Bot {bot_id} HP depleted! Need review.")
            await self._publish_alert("bot_critical", {
                'bot_id': bot_id,
                'hp': rpg_update.get('hp', 0),
                'action_required': 'review_or_retire',
            })

        # 에피소드 메모리에 추가
        self._create_episode_from_trade(bot_id, payload, trade)

        self.logger.debug(f"Processed trade for {bot_id}: PnL={trade.pnl:.2f}")

    async def _handle_status_message(self, topic: str, payload: Dict):
        """상태 메시지 처리"""
        pass  # TODO: 구현

    async def _handle_command(self, payload: Dict):
        """명령 처리"""
        command = payload.get("command")

        if command == "calculate_rewards":
            await self._run_daily_reward_calculation()
        elif command == "reallocate_capital":
            await self._run_capital_reallocation()
        elif command == "weekly_learning":
            await self._run_weekly_learning()
        elif command == "get_leaderboard":
            await self._publish_leaderboard()

    def _create_episode_from_trade(
        self,
        bot_id: str,
        payload: Dict,
        trade: TradeRecord,
    ):
        """거래로부터 에피소드 생성"""
        # 시장 컨텍스트
        context = MarketContext(
            timestamp=trade.timestamp,
            symbol=payload.get("symbol", "UNKNOWN"),
            timeframe=payload.get("timeframe", "1h"),
            price=payload.get("price", 0),
            volume_24h=payload.get("volume_24h", 0),
            volatility_atr=payload.get("volatility_atr", 0),
            rsi=payload.get("rsi"),
            trend=payload.get("trend", "sideways"),
            market_regime=payload.get("market_regime", "normal"),
        )

        # 봇 행동
        action = BotAction(
            action_type=payload.get("action", "unknown"),
            position_size=trade.position_size,
            leverage=payload.get("leverage", 1.0),
            entry_price=payload.get("entry_price"),
            exit_price=payload.get("exit_price"),
            confidence=payload.get("confidence", 0.5),
        )

        # 결과
        result = EpisodeResult(
            pnl=trade.pnl,
            pnl_pct=trade.pnl_pct,
            holding_period_minutes=trade.holding_period * 60,
            max_favorable_excursion=payload.get("mfe", trade.pnl),
            max_adverse_excursion=payload.get("mae", 0),
        )

        # 에피소드 생성
        profile = self.classifier.get_profile(bot_id)
        bot_name = profile.bot_name if profile else bot_id

        self.episode_memory.create_episode(
            bot_id=bot_id,
            bot_name=bot_name,
            context=context,
            action=action,
            result=result,
        )

    async def _daily_reward_scheduler(self):
        """일간 보상 계산 스케줄러"""
        self.logger.info(f"Daily reward scheduler started (hour: {self.daily_calc_hour})")

        while self._running:
            try:
                now = datetime.utcnow()
                next_run = now.replace(
                    hour=self.daily_calc_hour,
                    minute=0,
                    second=0,
                    microsecond=0
                )

                if next_run <= now:
                    next_run += timedelta(days=1)

                wait_seconds = (next_run - now).total_seconds()
                self.logger.info(f"Next reward calc in {wait_seconds/3600:.1f} hours")

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                await self._run_daily_reward_calculation()

            except Exception as e:
                self.logger.error(f"Daily reward scheduler error: {e}")
                await asyncio.sleep(3600)

    async def _weekly_learning_scheduler(self):
        """주간 학습 스케줄러"""
        self.logger.info("Weekly learning scheduler started")

        while self._running:
            try:
                now = datetime.utcnow()

                # 다음 일요일
                days_until_sunday = (6 - now.weekday()) % 7
                if days_until_sunday == 0 and now.hour >= self.daily_calc_hour:
                    days_until_sunday = 7

                next_sunday = now + timedelta(days=days_until_sunday)
                next_run = next_sunday.replace(
                    hour=self.daily_calc_hour,
                    minute=0,
                    second=0
                )

                wait_seconds = (next_run - now).total_seconds()
                self.logger.info(f"Next weekly learning in {wait_seconds/86400:.1f} days")

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                await self._run_weekly_learning()

            except Exception as e:
                self.logger.error(f"Weekly learning scheduler error: {e}")
                await asyncio.sleep(86400)

    async def _hp_recovery_scheduler(self):
        """HP 자연 회복 스케줄러"""
        while self._running:
            try:
                await asyncio.sleep(3600)  # 1시간마다

                if not self._running:
                    break

                # 모든 봇 HP 회복
                for bot_id in self.rpg_system.states:
                    state = self.rpg_system.states[bot_id]
                    if not state.is_retired:
                        state.hp.recover()

                self.logger.debug("HP recovery tick completed")

            except Exception as e:
                self.logger.error(f"HP recovery error: {e}")

    async def _run_daily_reward_calculation(self):
        """일간 보상 계산 실행"""
        self.logger.info("Running daily reward calculation...")

        results = {}

        for bot_id, trades in self.trade_buffer.items():
            if not trades:
                continue

            # 봇 유형별 보상 함수 선택
            profile = self.classifier.get_profile(bot_id)
            if profile:
                reward_type = self.classifier.get_reward_type(profile.bot_type)
            else:
                reward_type = RewardType.OZ_ENSEMBLE

            # 보상 계산
            result = self.calculator.calculate(
                bot_id=bot_id,
                trades=trades,
                reward_type=reward_type,
                lookback_days=1,
            )

            results[bot_id] = result

            # RPG 업데이트
            self.rpg_system.update_from_reward_score(bot_id, result.score)

            self.logger.info(f"{bot_id}: score={result.score:.2f}, type={reward_type.value}")

        # 자본 재배분
        await self._run_capital_reallocation(results)

        # 결과 발행
        await self._publish_reward_results(results)

        # 상태 저장
        self.rpg_system.save()

        self.logger.info(f"Daily reward calculation complete: {len(results)} bots")

    async def _run_capital_reallocation(
        self,
        reward_results: Optional[Dict[str, RewardResult]] = None
    ):
        """자본 재배분 실행"""
        if not reward_results:
            # 거래 버퍼로부터 계산
            reward_results = self.calculator.batch_calculate(
                self.trade_buffer,
                lookback_days=1,
            )

        # 재배분 계산
        plans = self.capital_allocator.calculate_reallocation(reward_results)

        # 적용
        results = self.capital_allocator.apply_reallocation(plans, dry_run=False)

        # 발행
        await self._publish_capital_reallocation(results)

        self.logger.info(f"Capital reallocation complete: {len(plans)} bots affected")

    async def _run_weekly_learning(self):
        """주간 학습 실행"""
        self.logger.info("Running weekly learning cycle...")

        results = self.episode_memory.weekly_learning_cycle()

        # 개선 프롬프트 발행
        for bot_id, prompt in results.get('prompts', {}).items():
            await self._publish_improvement_prompt(bot_id, prompt)

        # 상태 저장
        self.episode_memory.save()

        self.logger.info(f"Weekly learning complete: {results['preferences_generated']} preferences")

    async def _publish_reward_results(self, results: Dict[str, RewardResult]):
        """보상 결과 발행"""
        if not self._mqtt_client:
            return

        message = {
            'type': 'daily_rewards',
            'timestamp': datetime.utcnow().isoformat(),
            'results': {
                bot_id: {
                    'score': r.score,
                    'metrics': r.metrics,
                    'reward_type': r.reward_type.value,
                }
                for bot_id, r in results.items()
            }
        }

        await self._mqtt_client.publish(
            "oz/a2m/rewards/daily",
            json.dumps(message),
            qos=1,
        )

    async def _publish_capital_reallocation(self, results: Dict[str, Any]):
        """자본 재배분 결과 발행"""
        if not self._mqtt_client:
            return

        await self._mqtt_client.publish(
            "oz/a2m/capital/reallocation",
            json.dumps({
                'type': 'capital_reallocation',
                **results,
            }),
            qos=1,
        )

    async def _publish_leaderboard(self):
        """리더보드 발행"""
        if not self._mqtt_client:
            return

        leaderboard = self.rpg_system.get_leaderboard(sort_by="level", top_n=10)

        await self._mqtt_client.publish(
            "oz/a2m/rewards/leaderboard",
            json.dumps({
                'type': 'leaderboard',
                'timestamp': datetime.utcnow().isoformat(),
                'leaderboard': leaderboard,
            }),
            qos=1,
        )

    async def _publish_improvement_prompt(self, bot_id: str, prompt: str):
        """개선 프롬프트 발행"""
        if not self._mqtt_client:
            return

        await self._mqtt_client.publish(
            f"oz/a2m/bots/{bot_id}/improvement_prompt",
            json.dumps({
                'type': 'improvement_prompt',
                'bot_id': bot_id,
                'prompt': prompt,
                'timestamp': datetime.utcnow().isoformat(),
            }),
            qos=1,
        )

    async def _publish_alert(self, alert_type: str, data: Dict):
        """알림 발행"""
        if not self._mqtt_client:
            return

        await self._mqtt_client.publish(
            "oz/a2m/alerts/reward_system",
            json.dumps({
                'type': alert_type,
                **data,
                'timestamp': datetime.utcnow().isoformat(),
            }),
            qos=2,
        )

    def get_stats(self) -> Dict[str, Any]:
        """서비스 통계"""
        return {
            'running': self._running,
            'bots_tracked': len(self.trade_buffer),
            'total_trades': sum(len(t) for t in self.trade_buffer.values()),
            'rpg_states': len(self.rpg_system.states),
            'capital_allocations': len(self.capital_allocator.allocations),
            'episodes': sum(len(e) for e in self.episode_memory.episodes.values()),
        }


# 실행 진입점
async def main():
    """메인 실행"""
    import signal

    service = RewardService()

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        asyncio.create_task(service.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}")
    finally:
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
