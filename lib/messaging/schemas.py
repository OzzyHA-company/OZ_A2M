"""Message schemas for OZ_A2M MQTT messaging."""

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Message types."""
    MARKET_DATA = "market_data"
    ORDER = "order"
    SIGNAL = "signal"
    AGENT = "agent"
    SYSTEM = "system"
    LOG = "log"


class OrderSide(str, Enum):
    """Order sides."""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """Order statuses."""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class BaseMessage(BaseModel):
    """Base message schema."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: MessageType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field(default="unknown")
    department: Optional[str] = None
    version: str = Field(default="1.0")
    payload: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return self.model_dump_json()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() + "Z"}


class MarketDataMessage(BaseMessage):
    """Market data message."""
    type: MessageType = MessageType.MARKET_DATA
    symbol: str
    price: float
    volume: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OrderMessage(BaseMessage):
    """Order message."""
    type: MessageType = MessageType.ORDER
    order_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    side: OrderSide
    order_type: OrderType = Field(default=OrderType.MARKET, alias="type")
    amount: float
    price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING


class SignalMessage(BaseMessage):
    """Trading signal message."""
    type: MessageType = MessageType.SIGNAL
    symbol: str
    signal: str  # e.g., "buy", "sell", "hold"
    confidence: float = Field(ge=0.0, le=1.0)
    strategy: str
    timeframe: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentMessage(BaseMessage):
    """Agent communication message."""
    type: MessageType = MessageType.AGENT
    agent_id: str
    action: str
    target_department: Optional[str] = None
    priority: int = Field(default=5, ge=1, le=10)
    requires_response: bool = False


def parse_message(data: str) -> BaseMessage:
    """Parse JSON string to appropriate message type."""
    parsed = json.loads(data)
    msg_type = parsed.get("type")

    type_map = {
        MessageType.MARKET_DATA: MarketDataMessage,
        MessageType.ORDER: OrderMessage,
        MessageType.SIGNAL: SignalMessage,
        MessageType.AGENT: AgentMessage,
    }

    msg_class = type_map.get(msg_type, BaseMessage)
    return msg_class(**parsed)
