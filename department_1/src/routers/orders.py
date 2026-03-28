"""Order management router."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from lib.core import get_logger
from lib.messaging.schemas import OrderMessage, OrderSide, OrderType

router = APIRouter()
logger = get_logger(__name__)


class CreateOrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop"] = "market"
    amount: float = Field(gt=0)
    price: float = Field(default=None, gt=0)


@router.post("/")
async def create_order(order: CreateOrderRequest):
    """Create new order."""
    from lib.messaging import get_mqtt_client, OrderMessage, OrderSide, OrderType

    mqtt = get_mqtt_client()

    order_msg = OrderMessage(
        symbol=order.symbol.upper(),
        side=OrderSide(order.side),
        order_type=OrderType(order.order_type),
        amount=order.amount,
        price=order.price,
        source="gateway",
        department="d1",
    )

    await mqtt.publish(
        "oz_a2m/orders/new",
        order_msg.to_dict()
    )

    logger.info("Order created", symbol=order.symbol, side=order.side, amount=order.amount)

    return {
        "status": "created",
        "order_id": order_msg.order_id,
        "symbol": order.symbol.upper(),
        "side": order.side,
        "amount": order.amount,
    }


@router.get("/{order_id}")
async def get_order(order_id: str):
    """Get order status."""
    return {
        "order_id": order_id,
        "status": "pending",
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": 0.1,
        "filled": 0.0,
        "timestamp": "2024-03-28T00:00:00Z",
    }


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: str):
    """Cancel order."""
    from lib.messaging import get_mqtt_client

    mqtt = get_mqtt_client()
    await mqtt.publish(
        "oz_a2m/orders/cancel",
        {"order_id": order_id}
    )

    logger.info("Order cancellation requested", order_id=order_id)

    return {"status": "cancellation_requested", "order_id": order_id}
