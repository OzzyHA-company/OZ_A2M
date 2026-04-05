"""
봇 수익률(P&L) API 라우트
"""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import datetime

router = APIRouter(prefix="/bots", tags=["bots"])

# 더미 봇 데이터 (실제로는 DB에서 조회)
BOTS_PNL = [
    {
        "id": "bot-01",
        "name": "Binance Grid",
        "symbol": "BTC/USDT",
        "capital": 11.0,
        "pnl": 123.45,
        "pnl_pct": 11.2,
        "win_rate": 78.5,
        "trades": 45,
        "status": "active",
        "exchange": "Binance"
    },
    {
        "id": "bot-02",
        "name": "Binance DCA",
        "symbol": "BTC/USDT",
        "capital": 14.0,
        "pnl": 56.78,
        "pnl_pct": 4.1,
        "win_rate": 65.2,
        "trades": 23,
        "status": "active",
        "exchange": "Binance"
    },
    {
        "id": "bot-03",
        "name": "Triangular Arb",
        "symbol": "BTC/ETH/BNB",
        "capital": 20.0,
        "pnl": 89.12,
        "pnl_pct": 4.5,
        "win_rate": 82.1,
        "trades": 156,
        "status": "active",
        "exchange": "Binance"
    },
    {
        "id": "bot-04",
        "name": "Funding Rate",
        "symbol": "Multi",
        "capital": 20.0,
        "pnl": 34.56,
        "pnl_pct": 1.7,
        "win_rate": 71.4,
        "trades": 12,
        "status": "active",
        "exchange": "Binance+Bybit"
    },
    {
        "id": "bot-05",
        "name": "Bybit Scalping",
        "symbol": "SOL/USDT",
        "capital": 20.0,
        "pnl": 167.89,
        "pnl_pct": 8.4,
        "win_rate": 69.8,
        "trades": 89,
        "status": "active",
        "exchange": "Bybit"
    },
    {
        "id": "bot-06",
        "name": "Hyperliquid MM",
        "symbol": "SOL-PERP",
        "capital": 20.0,
        "pnl": 234.56,
        "pnl_pct": 11.7,
        "win_rate": 74.2,
        "trades": 134,
        "status": "active",
        "exchange": "Hyperliquid"
    },
    {
        "id": "bot-07",
        "name": "IBKR Forecast",
        "symbol": "AAPL/MSFT",
        "capital": 10.0,
        "pnl": 45.67,
        "pnl_pct": 4.6,
        "win_rate": 58.3,
        "trades": 34,
        "status": "active",
        "exchange": "Interactive Brokers"
    },
    {
        "id": "bot-08",
        "name": "Polymarket AI",
        "symbol": "Multi",
        "capital": 20.0,
        "pnl": 78.90,
        "pnl_pct": 3.9,
        "win_rate": 66.7,
        "trades": 28,
        "status": "active",
        "exchange": "Polymarket"
    },
    {
        "id": "bot-09",
        "name": "Pump.fun Sniper",
        "symbol": "New Tokens",
        "capital": 0.1,
        "pnl": 1234.56,
        "pnl_pct": 45.2,
        "win_rate": 42.1,
        "trades": 245,
        "status": "active",
        "exchange": "Solana"
    },
    {
        "id": "bot-10",
        "name": "GMGN Copy",
        "symbol": "Smart Money",
        "capital": 0.1,
        "pnl": 567.89,
        "pnl_pct": 21.3,
        "win_rate": 51.8,
        "trades": 178,
        "status": "active",
        "exchange": "Solana"
    },
]


@router.get("/pnl")
async def get_bots_pnl() -> Dict[str, Any]:
    """
    모든 봇의 수익률(P&L) 정보 조회
    """
    total_pnl = sum(bot["pnl"] for bot in BOTS_PNL)
    total_capital = sum(bot["capital"] for bot in BOTS_PNL)
    avg_win_rate = sum(bot["win_rate"] for bot in BOTS_PNL) / len(BOTS_PNL)
    total_trades = sum(bot["trades"] for bot in BOTS_PNL)

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_bots": len(BOTS_PNL),
            "total_pnl": round(total_pnl, 2),
            "total_capital": round(total_capital, 2),
            "total_pnl_pct": round((total_pnl / total_capital) * 100, 2) if total_capital > 0 else 0,
            "avg_win_rate": round(avg_win_rate, 2),
            "total_trades": total_trades,
        },
        "bots": BOTS_PNL
    }


@router.get("/pnl/{bot_id}")
async def get_bot_pnl(bot_id: str) -> Dict[str, Any]:
    """
    특정 봇의 수익률 정보 조회
    """
    bot = next((b for b in BOTS_PNL if b["id"] == bot_id), None)
    if not bot:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "bot": bot
    }
