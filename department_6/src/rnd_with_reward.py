#!/usr/bin/env python3
"""
Department 6: R&D Team Service with Reward System Integration
Reward System 통합 연구개발팀 서비스

occore/rnd + reward_system 통합
- 일일 분석 루프 (보상 계산 포함)
- 주간 학습 사이클 (AlphaLoop 방식)
- 봇 RPG 상태 관리
- 자본 재배분 실행
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import aiomqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lib.core.logger import get_logger
from lib.core.tracer import get_tracer

# Reward System 임포트
from lib.core.reward_system import (
    RewardCalculator,
    RewardType,
    RPGSystem,
    BotClassifier,
    CapitalAllocator,
    EpisodeMemory,
    TradeRecord,
)

logger = get_logger(__name__)
tracer = get_tracer("dept6_rnd_reward")

MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
ANALYSIS_SCHEDULE_HOUR = int(os.getenv('ANALYSIS_SCHEDULE_HOUR', '1'))


class RDTeamWithRewardService:
    """
    Reward System 통합 연구개발팀 서비스
    """

    def __init__(
        self,
        mqtt_host: str = MQTT_HOST,
        mqtt_port: int = MQTT_PORT,
        total_capital: float = 97.79,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # Reward System 컴포넌트
        self.calculator = RewardCalculator()
        self.rpg_system = RPGSystem(storage_path="data/rpg_states.json")
        self.classifier = BotClassifier()
        self.capital_allocator = CapitalAllocator(
            total_capital=total_capital,
            storage_path="data/capital_allocations.json"
        )
        self.episode_memory = EpisodeMemory(storage_path="data/episode_memory.json")

        # 상태
        self._running = False
        self._mqtt_client = None
        self.trade_buffer: Dict[str, List[TradeRecord]] = {}

        # 기본 봇 등록
        self._register_default_bots()

        logger.info("RDTeamWithRewardService initialized")

    def _register_default_bots(self):
        """OZ_A2M 기본 11봇 등록"""
        from lib.core.reward_system.bot_classifier import DEFAULT_BOT_CONFIGS

        for config in DEFAULT_BOT_CONFIGS:
            bot_id = config["bot_id"]
            capital = config["capital_usd"]

            self.capital_allocator.register_bot(bot_id, capital)
            self.classifier.create_profile(
                bot_id=bot_id,
                bot_name=config["name"],
                exchange=config["exchange"],
                symbols=config["symbols"],
                capital_usd=capital,
            )

    async def start(self):
        """서비스 시작"""
        self._running = True
        logger.info("Starting R&D Team with Reward Service...")

        # 상태 로드
        self.rpg_system.load()
        self.capital_allocator.load()
        self.episode_memory.load()

        # 태스크 시작
        tasks = [
            asyncio.create_task(self._mqtt_listener()),
            asyncio.create_task(self._daily_analysis_scheduler()),
            asyncio.create_task(self._weekly_learning_scheduler()),
            asyncio.create_task(self._hp_recovery_scheduler()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Service tasks cancelled")
        finally:
            await self.stop()

    async def stop(self):
        """서비스 중지"""
        logger.info("Stopping R&D Team with Reward Service...")
        self._running = False

        # 상태 저장
        self.rpg_system.save()
        self.capital_allocator.save()
        self.episode_memory.save()

    async def _mqtt_listener(self):
        """MQTT 리스너"""
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    client_id="dept6_rnd_reward",
                ) as client:
                    self._mqtt_client = client
                    logger.info("R&D+Reward service connected to MQTT")

                    # 토픽 구독
                    await client.subscribe("oz/a2m/bots/+/trade")
                    await client.subscribe("oz/a2m/bots/+/signal")
                    await client.subscribe("oz/a2m/commands/rnd")

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except aiomqtt.MqttError as e:
                logger.error(f"MQTT error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"MQTT listener error: {e}")
                await asyncio.sleep(5)

    async def _handle_message(self, message):
        """MQTT 메시지 처리"""
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())

            if "/trade" in topic:
                await self._handle_trade(topic, payload)
            elif "/signal" in topic:
                await self._handle_signal(topic, payload)
            elif "command" in topic:
                await self._handle_command(payload)

        except Exception as e:
            logger.error(f"Message handling error: {e}")

    async def _handle_trade(self, topic: str, payload: Dict):
        """거래 처리"""
        parts = topic.split("/")
        if len(parts) < 5:
            return

        bot_id = parts[3]

        # TradeRecord 생성
        trade = TradeRecord(
            timestamp=datetime.fromisoformat(
                payload.get("timestamp", datetime.utcnow().isoformat())
            ),
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

        # 최근 100개 유지
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

        # HP 체크
        if rpg_update.get('died'):
            logger.warning(f"Bot {bot_id} HP depleted! Scheduling review...")
            await self._publish_alert("bot_critical", {
                'bot_id': bot_id,
                'hp': rpg_update.get('hp', 0),
                'action': 'review_or_retire',
            })

        # 에피소드 생성
        self._create_episode(bot_id, payload, trade)

        logger.debug(f"Processed trade for {bot_id}: PnL={trade.pnl:.2f}")

    async def _handle_signal(self, topic: str, payload: Dict):
        """AI 신호 처리 (LLM Confidence)"""
        parts = topic.split("/")
        if len(parts) < 5:
            return

        bot_id = parts[3]

        # LLM Confidence 저장 (Phase 2)
        llm_confidence = payload.get('llm_confidence', 0.5)
        signal_strength = payload.get('signal_strength', 'neutral')

        # 향후 보상 계산에 사용
        if bot_id not in self._llm_confidence_cache:
            self._llm_confidence_cache = {}
        self._llm_confidence_cache[bot_id] = {
            'confidence': llm_confidence,
            'signal': signal_strength,
            'timestamp': datetime.utcnow(),
        }

    async def _handle_command(self, payload: Dict):
        """명령 처리"""
        command = payload.get("command")

        if command == "run_analysis":
            await self._run_daily_analysis()
        elif command == "calculate_rewards":
            await self._run_daily_reward_calculation()
        elif command == "reallocate_capital":
            await self._run_capital_reallocation()
        elif command == "weekly_learning":
            await self._run_weekly_learning()
        elif command == "get_leaderboard":
            await self._publish_leaderboard()
        elif command == "get_bot_status":
            bot_id = payload.get("bot_id")
            await self._publish_bot_status(bot_id)

    def _create_episode(self, bot_id: str, payload: Dict, trade: TradeRecord):
        """에피소드 생성"""
        from lib.core.reward_system.episode_memory import MarketContext, BotAction, EpisodeResult

        context = MarketContext(
            timestamp=trade.timestamp,
            symbol=payload.get("symbol", "UNKNOWN"),
            timeframe=payload.get("timeframe", "1h"),
            price=payload.get("price", 0),
            volume_24h=payload.get("volume_24h", 0),
            volatility_atr=payload.get("volatility_atr", 0),
            trend=payload.get("trend", "sideways"),
            market_regime=payload.get("market_regime", "normal"),
        )

        action = BotAction(
            action_type=payload.get("action", "unknown"),
            position_size=trade.position_size,
            leverage=payload.get("leverage", 1.0),
            confidence=payload.get("confidence", 0.5),
        )

        result = EpisodeResult(
            pnl=trade.pnl,
            pnl_pct=trade.pnl_pct,
            holding_period_minutes=trade.holding_period * 60,
        )

        profile = self.classifier.get_profile(bot_id)
        bot_name = profile.bot_name if profile else bot_id

        self.episode_memory.create_episode(
            bot_id=bot_id,
            bot_name=bot_name,
            context=context,
            action=action,
            result=result,
        )

    async def _daily_analysis_scheduler(self):
        """일일 분석 스케줄러"""
        logger.info(f"Daily analysis scheduler started (hour: {ANALYSIS_SCHEDULE_HOUR})")

        while self._running:
            try:
                now = datetime.utcnow()
                next_run = now.replace(
                    hour=ANALYSIS_SCHEDULE_HOUR,
                    minute=0,
                    second=0,
                    microsecond=0
                )

                if next_run <= now:
                    next_run += timedelta(days=1)

                wait_seconds = (next_run - now).total_seconds()
                logger.info(f"Next analysis in {wait_seconds/3600:.1f} hours")

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                await self._run_daily_analysis()

            except Exception as e:
                logger.error(f"Analysis scheduler error: {e}")
                await asyncio.sleep(3600)

    async def _run_daily_analysis(self):
        """일일 분석 실행 (기존 + Reward)"""
        logger.info("Running daily analysis with reward calculation...")

        # 1. 기존 전략 평가
        # (기존 StrategyEvaluator 로직 유지)

        # 2. 보상 계산
        await self._run_daily_reward_calculation()

        # 3. 자본 재배분
        await self._run_capital_reallocation()

        logger.info("Daily analysis complete")

    async def _run_daily_reward_calculation(self):
        """일간 보상 계산"""
        logger.info("Calculating daily rewards...")

        from lib.core.reward_system.reward_calculator import RewardResult

        results = {}

        for bot_id, trades in self.trade_buffer.items():
            if not trades:
                continue

            # 봇 유형별 보상 함수
            profile = self.classifier.get_profile(bot_id)
            reward_type = self.classifier.get_reward_type(profile.bot_type) if profile else RewardType.OZ_ENSEMBLE

            # LLM Confidence 적용 (Phase 2)
            llm_confidence = None
            if hasattr(self, '_llm_confidence_cache') and bot_id in self._llm_confidence_cache:
                cache = self._llm_confidence_cache[bot_id]
                # 신뢰도를 배율로 변환 (0.5 ~ 1.5)
                llm_confidence = 0.5 + cache['confidence']

            # 보상 계산
            result = self.calculator.calculate(
                bot_id=bot_id,
                trades=trades,
                reward_type=reward_type,
                lookback_days=1,
                llm_confidence=llm_confidence,
            )

            results[bot_id] = result

            # RPG 업데이트
            self.rpg_system.update_from_reward_score(bot_id, result.score)

            logger.info(f"{bot_id}: score={result.score:.2f}, type={reward_type.value}")

        # 결과 발행
        await self._publish_reward_results(results)

        # 저장
        self.rpg_system.save()

    async def _run_capital_reallocation(self, results: Dict = None):
        """자본 재배분"""
        if results is None:
            results = self.calculator.batch_calculate(self.trade_buffer, lookback_days=1)

        plans = self.capital_allocator.calculate_reallocation(results)
        reallocation = self.capital_allocator.apply_reallocation(plans, dry_run=False)

        await self._publish_capital_reallocation(reallocation)

        self.capital_allocator.save()

    async def _weekly_learning_scheduler(self):
        """주간 학습 스케줄러"""
        while self._running:
            try:
                now = datetime.utcnow()
                days_until_sunday = (6 - now.weekday()) % 7

                if days_until_sunday == 0 and now.hour >= ANALYSIS_SCHEDULE_HOUR:
                    days_until_sunday = 7

                next_run = now + timedelta(days=days_until_sunday)
                next_run = next_run.replace(hour=ANALYSIS_SCHEDULE_HOUR, minute=0)

                wait_seconds = (next_run - now).total_seconds()

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                await self._run_weekly_learning()

            except Exception as e:
                logger.error(f"Weekly learning scheduler error: {e}")
                await asyncio.sleep(86400)

    async def _run_weekly_learning(self):
        """주간 학습 실행"""
        logger.info("Running weekly learning cycle...")

        results = self.episode_memory.weekly_learning_cycle()

        # 개선 프롬프트 발행
        for bot_id, prompt in results.get('prompts', {}).items():
            await self._publish_improvement_prompt(bot_id, prompt)

        self.episode_memory.save()

    async def _hp_recovery_scheduler(self):
        """HP 회복 스케줄러"""
        while self._running:
            try:
                await asyncio.sleep(3600)  # 1시간

                if not self._running:
                    break

                for bot_id, state in self.rpg_system.states.items():
                    if not state.is_retired:
                        state.hp.recover()

            except Exception as e:
                logger.error(f"HP recovery error: {e}")

    # 발행 메서드들
    async def _publish_reward_results(self, results: Dict):
        """보상 결과 발행"""
        if not self._mqtt_client:
            return

        await self._mqtt_client.publish(
            "oz/a2m/rewards/daily",
            json.dumps({
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
            }),
            qos=1,
        )

    async def _publish_capital_reallocation(self, results: Dict):
        """자본 재배분 발행"""
        if not self._mqtt_client:
            return

        await self._mqtt_client.publish(
            "oz/a2m/capital/reallocation",
            json.dumps({'type': 'capital_reallocation', **results}),
            qos=1,
        )

    async def _publish_leaderboard(self):
        """리더보드 발행"""
        if not self._mqtt_client:
            return

        leaderboard = self.rpg_system.get_leaderboard(top_n=10)

        await self._mqtt_client.publish(
            "oz/a2m/rewards/leaderboard",
            json.dumps({
                'type': 'leaderboard',
                'timestamp': datetime.utcnow().isoformat(),
                'leaderboard': leaderboard,
            }),
            qos=1,
        )

    async def _publish_bot_status(self, bot_id: str):
        """봇 상태 발행"""
        if not self._mqtt_client or not bot_id:
            return

        state = self.rpg_system.get_or_create_state(bot_id)
        allocation = self.capital_allocator.allocations.get(bot_id)

        await self._mqtt_client.publish(
            f"oz/a2m/bots/{bot_id}/rpg_status",
            json.dumps({
                'type': 'rpg_status',
                'bot_id': bot_id,
                'rpg': state.to_dict(),
                'capital': {
                    'current': allocation.current_capital if allocation else 0,
                    'base': allocation.base_capital if allocation else 0,
                } if allocation else None,
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
        """통계"""
        return {
            'running': self._running,
            'bots_tracked': len(self.trade_buffer),
            'total_trades': sum(len(t) for t in self.trade_buffer.values()),
            'rpg_states': len(self.rpg_system.states),
            'capital_allocations': len(self.capital_allocator.allocations),
        }


async def main():
    """메인 실행"""
    service = RDTeamWithRewardService()

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
