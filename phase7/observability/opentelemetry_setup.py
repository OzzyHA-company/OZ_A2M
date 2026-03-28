"""
OZ_A2M OpenTelemetry Observability Setup
Phase 7: Distributed Tracing and Metrics

Features:
- Distributed tracing
- Custom metrics
- Automatic instrumentation
- Export to Prometheus/Jaeger
"""

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metrics_exporter import OTLPMetricExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
from contextlib import contextmanager
import time
import logging
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OZTelemetry:
    """
    OpenTelemetry manager for OZ_A2M distributed observability.
    """

    def __init__(
        self,
        service_name: str = "oza2m",
        service_version: str = "1.0.0",
        jaeger_endpoint: str = "http://localhost:4317",
        enable_prometheus: bool = True
    ):
        self.service_name = service_name
        self.service_version = service_version

        # Create resource
        self.resource = Resource.create({
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": "production",
            "host.name": "oza2m-server"
        })

        # Initialize tracing
        self._init_tracing(jaeger_endpoint)

        # Initialize metrics
        self._init_metrics(enable_prometheus)

        # Instrument libraries
        self._instrument_libraries()

    def _init_tracing(self, jaeger_endpoint: str):
        """Initialize distributed tracing."""
        # Create tracer provider
        tracer_provider = TracerProvider(resource=self.resource)

        # Add OTLP exporter (for Jaeger)
        try:
            otlp_exporter = OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True)
            span_processor = BatchSpanProcessor(otlp_exporter)
            tracer_provider.add_span_processor(span_processor)
        except Exception as e:
            logger.warning(f"Could not connect to Jaeger: {e}")

        # Add console exporter for debugging
        console_exporter = ConsoleSpanExporter()
        tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))

        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)
        self.tracer = trace.get_tracer(__name__)

        logger.info("Tracing initialized")

    def _init_metrics(self, enable_prometheus: bool):
        """Initialize metrics collection."""
        readers = []

        if enable_prometheus:
            # Prometheus reader
            prometheus_reader = PrometheusMetricReader()
            readers.append(prometheus_reader)

        # Create meter provider
        meter_provider = MeterProvider(
            resource=self.resource,
            metric_readers=readers
        )
        metrics.set_meter_provider(meter_provider)
        self.meter = metrics.get_meter(__name__)

        # Create custom metrics
        self._create_custom_metrics()

        logger.info("Metrics initialized")

    def _create_custom_metrics(self):
        """Create OZ_A2M specific metrics."""
        # Counters
        self.order_counter = self.meter.create_counter(
            "oza2m.orders.total",
            description="Total number of orders"
        )

        self.trade_counter = self.meter.create_counter(
            "oza2m.trades.total",
            description="Total number of trades"
        )

        self.error_counter = self.meter.create_counter(
            "oza2m.errors.total",
            description="Total number of errors"
        )

        # Gauges
        self.position_gauge = self.meter.create_gauge(
            "oza2m.position.size",
            description="Current position size"
        )

        self.pnl_gauge = self.meter.create_gauge(
            "oza2m.pnl.current",
            description="Current PnL"
        )

        # Histograms
        self.order_latency = self.meter.create_histogram(
            "oza2m.order.latency",
            description="Order execution latency in ms",
            unit="ms"
        )

        self.signal_processing_time = self.meter.create_histogram(
            "oza2m.signal.processing_time",
            description="Signal processing time in ms",
            unit="ms"
        )

    def _instrument_libraries(self):
        """Instrument third-party libraries."""
        try:
            RedisInstrumentor().instrument()
            logger.info("Redis instrumented")
        except Exception as e:
            logger.warning(f"Could not instrument Redis: {e}")

        try:
            KafkaInstrumentor().instrument()
            logger.info("Kafka instrumented")
        except Exception as e:
            logger.warning(f"Could not instrument Kafka: {e}")

    def instrument_fastapi(self, app):
        """Instrument FastAPI application."""
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumented")

    @contextmanager
    def span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Context manager for creating spans."""
        with self.tracer.start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            yield span

    def record_order(self, symbol: str, side: str, quantity: float, latency_ms: float):
        """Record order metrics."""
        self.order_counter.add(1, {
            "symbol": symbol,
            "side": side
        })
        self.order_latency.record(latency_ms)

    def record_trade(self, symbol: str, side: str, quantity: float, price: float):
        """Record trade metrics."""
        self.trade_counter.add(1, {
            "symbol": symbol,
            "side": side
        })

    def record_error(self, error_type: str, component: str):
        """Record error metrics."""
        self.error_counter.add(1, {
            "error_type": error_type,
            "component": component
        })

    def update_position(self, symbol: str, size: float):
        """Update position gauge."""
        self.position_gauge.set(size, {"symbol": symbol})

    def update_pnl(self, symbol: str, pnl: float):
        """Update PnL gauge."""
        self.pnl_gauge.set(pnl, {"symbol": symbol})

    def trace_signal_processing(self, func):
        """Decorator to trace signal processing."""
        def wrapper(*args, **kwargs):
            start = time.time()
            with self.span(f"signal.{func.__name__}") as span:
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    span.set_attribute("status", "error")
                    span.set_attribute("error.message", str(e))
                    raise
                finally:
                    latency = (time.time() - start) * 1000
                    self.signal_processing_time.record(latency)
        return wrapper


# Global telemetry instance
_telemetry = None

def get_telemetry(
    service_name: str = "oza2m",
    **kwargs
) -> OZTelemetry:
    """Get or create global telemetry instance."""
    global _telemetry
    if _telemetry is None:
        _telemetry = OZTelemetry(service_name=service_name, **kwargs)
    return _telemetry


# Convenience decorators
def trace_function(name: Optional[str] = None):
    """Decorator to trace function execution."""
    def decorator(func):
        telem = get_telemetry()
        span_name = name or func.__name__

        def wrapper(*args, **kwargs):
            with telem.span(span_name, {
                "function.name": func.__name__,
                "function.module": func.__module__
            }):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def trace_bot_method(bot_type: str):
    """Decorator to trace bot methods."""
    def decorator(func):
        telem = get_telemetry()

        def wrapper(*args, **kwargs):
            with telem.span(f"bot.{bot_type}.{func.__name__}", {
                "bot.type": bot_type,
                "method": func.__name__
            }):
                return func(*args, **kwargs)
        return wrapper
    return decorator


if __name__ == "__main__":
    # Test telemetry
    telem = get_telemetry()

    with telem.span("test.operation"):
        telem.record_order("BTC/USDT", "buy", 0.1, 150.5)
        telem.update_pnl("BTC/USDT", 125.50)
        logger.info("Test metrics recorded")
