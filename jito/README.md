# Jito Integration for OZ_A2M

## Overview

Jito Labs integration for Solana MEV protection and high-performance trading.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Data In  │ Jito Shredstream Proxy                       │
│           │  - Scout: mempool 탐색 (Ant-Colony)          │
│           │  - Workers: TX 파싱/필터링                   │
│           │  - Soldiers: 검증/중복 제거                  │
└───────────┴─────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  Brain    │ pi-mono + Gemini Pro + Ant-Colony           │
│           │  - Queen: 전략 수립                          │
│           │  - Scouts: 기회 탐색                         │
│           │  - Workers: 분석/예측 (병렬)                 │
│           │  - Soldiers: 검증/리스크 관리                │
└───────────┴─────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  Data Out │ Jito Block Engine Bundle                    │
│           │  - Builders: bundle 생성/최적화              │
│           │  - Protectors: MEV 보호/검증                 │
│           │  - Sender: 블록 엔진 전송                    │
└─────────────────────────────────────────────────────────┘
```

## Components

### Shredstream Proxy (`shredstream/`)

**Ant-Colony Architecture:**

| Agent | Role | Description |
|-------|------|-------------|
| **Scout** | Exploration | mempool 탐색, 고수익 TX 식별 |
| **Worker** | Processing | TX 파싱, 데이터 정규화 |
| **Soldier** | Validation | 데이터 검증, 중복 제거 |

**Features:**
- Real-time mempool data ingestion
- Parallel transaction processing
- Opportunity detection
- Pheromone-based shared state

### Block Engine Sender (`block_engine/`)

**Ant-Colony Architecture:**

| Agent | Role | Description |
|-------|------|-------------|
| **Builder** | Construction | bundle 생성, 최적화 |
| **Protector** | Validation | MEV 보호, 검증 |

**Features:**
- Bundle building with tip optimization
- MEV protection (sandwich detection)
- Parallel bundle submission
- Success probability estimation

## Installation

```bash
pip install grpcio protobuf solana solders
```

## Usage

### Shredstream Proxy

```python
from jito.shredstream.proxy import JitoShredstreamProxy

proxy = JitoShredstreamProxy(
    endpoint="shredstream.jito.wtf",
    port=10000,
    num_scouts=3,
    num_workers=5,
    num_soldiers=2,
)

await proxy.start()

# Get validated transactions
tx = proxy.get_validated_tx()

# Get opportunities
opp = proxy.get_opportunity()
```

### Block Engine Sender

```python
from jito.block_engine.sender import JitoBlockEngineSender
from solders.transaction import Transaction

sender = JitoBlockEngineSender(
    block_engine_url="mainnet.block-engine.jito.wtf",
    num_builders=3,
    num_protectors=2,
)

await sender.start()

# Send bundle
uuid = await sender.send_bundle(
    transactions=[tx1, tx2, tx3],
    tip_amount=1_000_000,  # 0.001 SOL
)

# Check status
status = await sender.get_bundle_status(uuid)
```

## Configuration

### Environment Variables

```bash
export JITO_BLOCK_ENGINE_URL="mainnet.block-engine.jito.wtf"
export JITO_SHREDSTREAM_ENDPOINT="shredstream.jito.wtf"
export SOLANA_RPC_URL="https://api.mainnet-beta.solana.com"
```

### Ant-Colony Tuning

```python
# High-frequency trading
proxy = JitoShredstreamProxy(
    num_scouts=10,    # More scouts for better coverage
    num_workers=20,   # More workers for faster processing
    num_soldiers=5,   # More validation
)

# Conservative trading
proxy = JitoShredstreamProxy(
    num_scouts=2,
    num_workers=3,
    num_soldiers=5,   # Heavy validation
)
```

## Performance

| Metric | Target |
|--------|--------|
| Mempool latency | <50ms |
| Bundle submission | <100ms |
| Success rate | >95% |
| Throughput | 10,000+ TX/sec |

## References

- [Jito Docs](https://jito-labs.gitbook.io/mev/searcher-services)
- [Solana MEV](https://docs.solana.com/developing/programming-model/transactions)
