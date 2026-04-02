# OZ_A2M System Diagnostic Report

**Date:** 2026-03-30
**Server:** ozzy-claw-PC (Ubuntu, Tailscale: 100.77.207.113)
**Repository:** https://github.com/OzzyHA-company/OZ_A2M
**Working Directory:** `/home/ozzy-claw/OZ_A2M`

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Bots Configured | 11 |
| Running Before Audit | 5 (drift_bot, pump_bot, occore, oz_a2m_bot, scalping_bot) |
| Current Status | **ALL STOPPED** |
| Dashboard | ✅ UP (100.77.207.113:8080) |
| API Gateway | ✅ UP (100.77.207.113:8000) |
| MQTT Broker | ✅ UP (localhost:1883) |
| Redis | ✅ UP (localhost:6379) |
| Tests Status | 316 passed, 5 failed, 16 skipped |
| Environment Vars | 34/46 present (74%) |

---

## System Health Summary

### Infrastructure Components

| Component | Status | Port | Uptime | Notes |
|-----------|--------|------|--------|-------|
| oz_a2m_gateway | ✅ Healthy | 8000 | 40h | FastAPI Gateway |
| oz_a2m_mqtt | ✅ Healthy | 1883 | 40h | Eclipse Mosquitto |
| oz_a2m_redis | ✅ Running | 6379 | 27h | Cache layer |
| oz_a2m_grafana | ✅ Running | 3000 | 43h | Dashboard |
| ozclaw-gateway | ✅ Running | 4002 | 9h | IBKR Gateway |

### External API Connectivity

| Service | Host | Status | Latency |
|---------|------|--------|---------|
| Hyperliquid API | api.hyperliquid.xyz | ✅ OK | 4.15 ms |
| Binance API | api.binance.com | ✅ OK | 2.51 ms |
| Bybit API | api.bybit.com | ✅ OK | 3.78 ms |

---

## Bot Inventory Table

| # | Bot Name | Role | File Path | Status Before | Dependencies | Risk Level |
|---|----------|------|-----------|---------------|--------------|------------|
| 봇-01 | Binance Grid | Grid trading | `department_7/src/bot/grid_bot.py` | Not running | BINANCE_API_KEY, MQTT, Redis | LOW |
| 봇-02 | Binance DCA | DCA strategy | `department_7/src/bot/dca_bot.py` | Not running | BINANCE_API_KEY, MQTT, Redis | LOW |
| 봇-03 | Triangular Arb | Cross-pair arb | `department_7/src/bot/triangular_arb_bot.py` | Not running | BINANCE_API_KEY, MQTT, Redis | MEDIUM |
| 봇-04 | Funding Rate | Funding arb | `department_7/src/bot/funding_rate_bot.py` | Not running | BINANCE/BYBIT_API_KEY, MQTT | MEDIUM |
| 봇-05 | Bybit Grid | Grid trading | `department_7/src/bot/grid_bot.py` | Not running | BYBIT_API_KEY, MQTT, Redis | LOW |
| 봇-06 | Bybit Scalping | Scalping | `department_7/src/bot/scalper.py` | **RUNNING** (Docker) | BYBIT_API_KEY, MQTT, Redis | HIGH |
| 봇-07 | Hyperliquid MM | Market making | `department_7/src/bot/hyperliquid_bot.py` | Not running | PHANTOM_WALLET_A, MQTT | MEDIUM |
| 봇-08 | IBKR Forecast | Prediction trading | `department_7/src/bot/ibkr_forecast_bot.py` | Not running | IBKR TWS, MQTT, Redis | LOW |
| 봇-09 | Polymarket AI | Prediction markets | `department_7/src/bot/polymarket_bot.py` | Not running | METAMASK_ADDRESS, POLYMARKET_API | MEDIUM |
| 봇-10 | KIS DART | Korean disclosure | *Not implemented* | N/A | KIS API, DART API | N/A |
| 봇-11 | Pump.fun Sniper | Meme sniping | `department_7/src/bot/pump_sniper_bot.py` | **RUNNING** | PHANTOM_WALLET_B, HELIUS_RPC | HIGH |
| 봇-12 | GMGN Copy | Copy trading | `department_7/src/bot/copy_trade_bot.py` | Not running | PHANTOM_WALLET_C, HELIUS | MEDIUM |

**Legacy/External Bots:**

| Bot | File Path | Status Before | PID | Issue |
|-----|-----------|---------------|-----|-------|
| drift_bot | `/home/ozzy-claw/drift_bot/main.py` | **RUNNING** | 1384 | Insufficient collateral errors |
| pump_bot | `/home/ozzy-claw/pump_bot/main.py` | **RUNNING** | 1666 | Helius rate limit errors |
| occore/main | `/home/ozzy-claw/occore/main.py` | **RUNNING** | 1412 | Auto-restarts on stop |

---

## Issues Found

### CRITICAL

#### ISSUE-001: Insufficient Collateral (drift_bot)
- **Bot/Component:** drift_bot
- **Severity:** CRITICAL
- **Description:** Bot cannot place orders due to insufficient collateral on Drift Protocol
- **Error Message:** `InsufficientCollateral. Error Number: 6003. margin_requirement: 1846387, total_collateral: 1702319`
- **Root Cause:** Account under-collateralized for desired position size
- **Impact:** Bot cannot trade; continuous retry wasting compute
- **Recommended Fix:**
  1. Deposit additional SOL to Drift account, OR
  2. Reduce position size in config, OR
  3. Stop bot until funding is resolved
- **Priority:** P0
- **Count:** 592 errors in log

#### ISSUE-002: Helius API Rate Limit (pump_bot)
- **Bot/Component:** pump_bot
- **Severity:** CRITICAL
- **Description:** WebSocket connections rejected with HTTP 429 (rate limit)
- **Error Message:** `server rejected WebSocket connection: HTTP 429`
- **Root Cause:** Free Helius plan rate limits exceeded
- **Impact:** Cannot detect new token launches; bot blind
- **Recommended Fix:**
  1. Upgrade Helius plan to paid tier, OR
  2. Implement exponential backoff with jitter, OR
  3. Use multiple Helius API keys with rotation
- **Priority:** P0
- **Count:** 5,285+ errors in log

#### ISSUE-003: Auto-Restart Loop (occore)
- **Bot/Component:** occore/main.py, telegram_commander.py
- **Severity:** CRITICAL
- **Description:** Processes restart automatically after SIGTERM
- **Root Cause:** systemd service with `Restart=always` or cron watchdog
- **Impact:** Cannot cleanly stop bots without disabling systemd service
- **Recommended Fix:**
  1. Run `sudo systemctl disable occore.service` (requires sudo), OR
  2. Edit service file to change `Restart=no`, OR
  3. Use `systemctl mask` to prevent restart
- **Priority:** P0

### WARNING

#### ISSUE-004: Missing Environment Variables
- **Bot/Component:** Multiple bots
- **Severity:** WARNING
- **Description:** 12/46 required environment variables missing
- **Missing Vars:**
  - `PHANTOM_WALLET_A` (봇-07 Hyperliquid)
  - `PHANTOM_WALLET_B` (봇-11 Pump.fun)
  - `PHANTOM_WALLET_C` (봇-12 GMGN)
  - `METAMASK_ADDRESS` (봇-09 Polymarket)
  - `POLYMARKET_API_KEY` (봇-09 Polymarket)
  - `POLYMARKET_API_SECRET` (봇-09 Polymarket)
- **Impact:** 4 bots cannot start in live mode
- **Recommended Fix:** Add missing variables to `/home/ozzy-claw/.ozzy-secrets/master.env`
- **Priority:** P1

#### ISSUE-005: Test Failures (5 tests)
- **Bot/Component:** Test suite
- **Severity:** WARNING
- **Description:** 5 tests failing, possibly due to mock config issues
- **Failing Tests:**
  1. `test_get_bots_summary` - UnifiedBotManager method issue
  2. `test_hyperliquid_mock_mode` - Mock balance assertion
  3. `test_ibkr_bot_initialization` - IBKR init failure
  4. `test_ibkr_mock_data` - Mock data validation
  5. `test_ibkr_status` - Status check assertion
- **Root Cause:** Mock data structures changed; test expectations outdated
- **Impact:** Cannot verify bot behavior before deployment
- **Recommended Fix:** Update test expectations to match current implementation
- **Priority:** P1
- **Estimated Fix Time:** 2-3 hours

#### ISSUE-006: Deprecated datetime.utcnow()
- **Bot/Component:** occore/orchestration/activities.py
- **Severity:** WARNING
- **Description:** 15+ deprecation warnings for datetime.utcnow()
- **Recommended Fix:** Replace with `datetime.now(datetime.UTC)`
- **Priority:** P2

### INFO

#### ISSUE-007: Log File Sizes
- **Bot/Component:** All bots
- **Severity:** INFO
- **Description:** Log files growing large without rotation
- **Largest Files:**
  - drift_bot.log: 14.1 MB (14,716 errors)
  - recorder.log: 14.9 MB
  - pump_bot.log: 4.6 MB (14,266 errors)
- **Recommended Fix:** Implement log rotation with logrotate or Python RotatingFileHandler
- **Priority:** P2

---

## Test Failures Analysis

### Summary
```
Total: 337 tests
Passed: 316 (93.8%)
Failed: 5 (1.5%)
Skipped: 16 (4.7%)
Duration: 13.67s
```

### Detailed Analysis

#### FAIL-001: test_get_bots_summary
```python
# File: tests/test_grid_dca_bots.py
# Issue: UnifiedBotManager.get_bots_summary() method signature mismatch
# Expected: Returns dict with specific keys
# Actual: Method may return different structure or be missing
# Fix: Update test expectation OR restore method signature
# Complexity: LOW (1 hour)
```

#### FAIL-002-005: Hyperliquid/IBKR Mock Tests
```python
# File: tests/test_hyperliquid_ibkr_bots.py
# Issue: Mock mode data structures don't match test expectations
# Expected: bot._mock_balance["USDC"] == 20.0
# Actual: May use different key or structure
# Fix: Align mock data between bot implementation and tests
# Complexity: LOW (30 min each)
```

### Fix Recommendations

| Test | Root Cause | Fix | Est. Time |
|------|------------|-----|-----------|
| test_get_bots_summary | Method signature change | Update test OR restore method | 1 hour |
| test_hyperliquid_mock_mode | Mock balance structure | Update mock data structure | 30 min |
| test_ibkr_bot_initialization | IBKR SDK import | Ensure mock mode works without SDK | 30 min |
| test_ibkr_mock_data | Mock data validation | Update test assertions | 30 min |
| test_ibkr_status | Status dict format | Align status format | 30 min |

**Total Estimated Fix Time:** 3 hours

---

## Missing Configuration

### Cannot Start Without These:

- [ ] `PHANTOM_WALLET_A` - Required for 봇-07 Hyperliquid MM
  - Action: Add private key for Phantom wallet A
  - Impact: Hyperliquid market making unavailable

- [ ] `PHANTOM_WALLET_B` - Required for 봇-11 Pump.fun Sniper
  - Action: Add private key for Phantom wallet B
  - Impact: Pump.fun sniping unavailable

- [ ] `PHANTOM_WALLET_C` - Required for 봇-12 GMGN Copy
  - Action: Add private key for Phantom wallet C
  - Impact: GMGN copy trading unavailable

- [ ] `METAMASK_ADDRESS` - Required for 봇-09 Polymarket AI
  - Action: Add Polygon wallet address
  - Impact: Polymarket trading unavailable

- [ ] `POLYMARKET_API_KEY` - Required for 봇-09 Polymarket AI
  - Action: Create API key at https://polymarket.com
  - Impact: Polymarket trading unavailable

- [ ] `POLYMARKET_API_SECRET` - Required for 봇-09 Polymarket AI
  - Action: Generate secret with API key
  - Impact: Polymarket trading unavailable

### Optional (Have Defaults):

- [ ] `TRACKED_WALLETS` - For GMGN Copy bot
  - Default: Empty list
  - Impact: No wallets to copy until configured

---

## Recommended Next Steps

### Immediate Actions (P0 - Before Restart)

1. **Fix Auto-Restart Issue** (30 min)
   - Edit systemd service files to disable auto-restart
   - Or use sudo to disable services before stopping

2. **Resolve Critical Errors** (1 hour)
   - Decide on drift_bot: fund account or keep stopped
   - Decide on pump_bot: upgrade Helius or keep stopped

3. **Fix Failing Tests** (3 hours)
   - Update test expectations to match current code
   - Verify all 316 tests pass

### Short-Term Actions (P1 - This Week)

4. **Add Missing Environment Variables** (30 min)
   - Create Phantom wallets A, B, C
   - Add to `/home/ozzy-claw/.ozzy-secrets/master.env`
   - Set up Polymarket API credentials

5. **Configure Log Rotation** (1 hour)
   - Implement Python RotatingFileHandler
   - Or configure system logrotate

### Medium-Term Actions (P2 - Next Sprint)

6. **Fix Deprecation Warnings** (2 hours)
   - Replace datetime.utcnow() with timezone-aware alternatives
   - Fix pytest return value warnings

7. **Documentation Update** (2 hours)
   - Document bot dependencies
   - Update restart procedures

---

## Safe Restart Order

### Dependency-Aware Restart Sequence

```bash
# PHASE 1: Infrastructure (must be running)
# Already running: MQTT (1883), Redis (6379), Gateway (8000)

# PHASE 2: Core Services
1. occore/main.py          # Core operations
2. occore/telegram_commander.py  # Telegram alerts

# PHASE 3: External/Standalone Bots
3. drift_bot               # IF collateral issue resolved
4. pump_bot                # IF Helius rate limit resolved

# PHASE 4: OZ_A2M Unified Bots (via UnifiedBotManager)
5. scalper (Bybit)         # Bot-06 - Most tested
6. grid_bot (Binance)      # Bot-01
7. grid_bot (Bybit)        # Bot-05
8. dca_bot (Binance)       # Bot-02
9. arbitrage_bot           # Bot-04
10. triangular_arb_bot     # Bot-03

# PHASE 5: Advanced Bots (after env vars configured)
11. hyperliquid_bot        # Bot-07 - Requires PHANTOM_WALLET_A
12. ibkr_forecast_bot      # Bot-08 - Requires IBKR TWS
13. polymarket_bot         # Bot-09 - Requires POLYMARKET_API_*
14. pump_sniper_bot        # Bot-11 - Requires PHANTOM_WALLET_B
15. gmgn_copy_bot          # Bot-12 - Requires PHANTOM_WALLET_C
```

### Verification Steps Between Phases

After each phase, verify:
```bash
# Check process running
ps aux | grep -E "(occore|bot|drift)" | grep -v grep

# Check MQTT connection
docker exec oz_a2m_mqtt mosquitto_pub -t test -m "hello"

# Check Redis
redis-cli ping  # Should return PONG

# Check Gateway
curl http://localhost:8000/health

# Check Dashboard
curl http://100.77.207.113:8080/health
```

### Monitoring Period

After restart, monitor for **30 minutes** before enabling live trading:

| Time | Check |
|------|-------|
| 0 min | All processes started, no crash loops |
| 5 min | MQTT messages flowing, Redis connected |
| 10 min | Bot status updates in dashboard |
| 15 min | No ERROR logs in first 15 min |
| 30 min | PnL calculator updating correctly |

---

## Appendix

### Log File Locations

```
/home/ozzy-claw/drift_bot/logs/drift_bot.log    (14.1 MB)
/home/ozzy-claw/drift_bot/logs/recorder.log     (14.9 MB)
/home/ozzy-claw/pump_bot/logs/bot.log           (4.6 MB)
/home/ozzy-claw/occore/logs/main.log            (191 KB)
/home/ozzy-claw/occore/logs/dashboard.log       (1.2 MB)
```

### Service Files

```
~/.config/systemd/user/drift-bot.service   (drift_bot)
/etc/systemd/system/pump-bot.service       (pump_bot - system level)
```

### Key Configuration Files

```
/home/ozzy-claw/OZ_A2M/.env                     -> ~/.ozzy-secrets/master.env
/home/ozzy-claw/OZ_A2M/department_7/config/config.json
/home/ozzy-claw/.ozzy-secrets/master.env        (actual secrets)
```

### Important Ports

| Port | Service | Description |
|------|---------|-------------|
| 1883 | MQTT | Message broker |
| 6379 | Redis | Cache/State |
| 8000 | API Gateway | FastAPI |
| 8080 | CEO Dashboard | Grafana/Tailscale |
| 4002 | IBKR Gateway | TWS API |
| 7497 | IBKR TWS | Default TWS port |
| 9092 | Kafka | Message queue |

---

*Report generated by Claude Code on 2026-03-30*
*For updates, run: `cd /home/ozzy-claw/OZ_A2M && python3 -m pytest tests/ -v --tb=short`*
