#!/usr/bin/env python3
"""
OZ_A2M Kafka Topics Initialization
Phase 7: High-Performance Event Bus
"""

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Topic definitions for OZ_A2M
TOPICS = [
    # Market Data Topics
    NewTopic(name="market.data.ohlcv", num_partitions=6, replication_factor=2),
    NewTopic(name="market.data.orderbook", num_partitions=6, replication_factor=2),
    NewTopic(name="market.data.trades", num_partitions=6, replication_factor=2),
    NewTopic(name="market.data.ticker", num_partitions=3, replication_factor=2),

    # Signal Topics
    NewTopic(name="signals.scalping", num_partitions=3, replication_factor=2),
    NewTopic(name="signals.trend", num_partitions=3, replication_factor=2),
    NewTopic(name="signals.arbitrage", num_partitions=3, replication_factor=2),
    NewTopic(name="signals.risk.alert", num_partitions=1, replication_factor=2),

    # Order/Execution Topics
    NewTopic(name="orders.new", num_partitions=6, replication_factor=2),
    NewTopic(name="orders.status", num_partitions=6, replication_factor=2),
    NewTopic(name="orders.fills", num_partitions=6, replication_factor=2),
    NewTopic(name="execution.reports", num_partitions=6, replication_factor=2),

    # System Topics
    NewTopic(name="system.heartbeat", num_partitions=1, replication_factor=2),
    NewTopic(name="system.logs", num_partitions=3, replication_factor=2),
    NewTopic(name="system.metrics", num_partitions=3, replication_factor=2),
    NewTopic(name="system.alerts", num_partitions=1, replication_factor=2),

    # Department Communication Topics
    NewTopic(name="dept.1.control", num_partitions=2, replication_factor=2),
    NewTopic(name="dept.2.analysis", num_partitions=2, replication_factor=2),
    NewTopic(name="dept.3.security", num_partitions=2, replication_factor=2),
    NewTopic(name="dept.4.monitoring", num_partitions=2, replication_factor=2),
    NewTopic(name="dept.5.pnl", num_partitions=2, replication_factor=2),
    NewTopic(name="dept.6.rnd", num_partitions=2, replication_factor=2),
    NewTopic(name="dept.7.operations", num_partitions=6, replication_factor=2),
]


def init_topics(bootstrap_servers: str = "localhost:9092"):
    """Initialize all OZ_A2M Kafka topics."""
    admin_client = KafkaAdminClient(
        bootstrap_servers=bootstrap_servers,
        client_id="oza2m-topic-init"
    )

    for topic in TOPICS:
        try:
            admin_client.create_topics([topic])
            logger.info(f"Created topic: {topic.name}")
        except TopicAlreadyExistsError:
            logger.info(f"Topic already exists: {topic.name}")
        except Exception as e:
            logger.error(f"Failed to create topic {topic.name}: {e}")

    admin_client.close()
    logger.info("Topic initialization complete")


if __name__ == "__main__":
    init_topics()
