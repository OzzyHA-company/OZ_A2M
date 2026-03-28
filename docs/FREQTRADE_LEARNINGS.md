# Freqtrade 학습 정리 (제1부서 관제탑센터 개선용)

## 학습 범위
- **exchange/**: ccxt 래퍼 패턴
- **strategy/**: 전략 인터페이스 패턴
- **persistence/**: 거래 데이터 저장 패턴

---

## 1. Exchange (ccxt 래퍼) 패턴

### 1.1 핵심 아키텍처

```python
class Exchange:
    """ccxt를 래핑하는 메인 클래스"""

    # 거래소별 기능 정의 (ft_has 패턴)
    _ft_has_default: FtHas = {
        "stoploss_on_exchange": False,
        "order_time_in_force": ["GTC"],
        "ohlcv_params": {},
        "ws_enabled": False,
        # ... 거래소별 설정
    }

    def __init__(self, config: Config, validate: bool = True):
        # 동기/비동기 ccxt 인스턴스 생성
        self._api: ccxt.Exchange
        self._api_async: ccxt_pro.Exchange

        # WebSocket 지원
        self._ws_async: ccxt_pro.Exchange = None
        self._exchange_ws: ExchangeWS | None = None

        # TTL 캐시 (성능 최적화)
        self._fetch_tickers_cache: FtTTLCache = FtTTLCache(maxsize=4, ttl=60 * 10)
        self._exit_rate_cache: FtTTLCache = FtTTLCache(maxsize=100, ttl=300)
    ```

### 1.2 ccxt 초기화 패턴

```python
def _init_ccxt(self, exchange_config: dict, sync: bool, ccxt_kwargs: dict):
    """ccxt 인스턴스 생성"""
    name = exchange_config["name"]
    ccxt_module = ccxt if sync else ccxt_pro

    ex_config = {
        "apiKey": exchange_config.get("api_key"),
        "secret": exchange_config.get("secret"),
        "password": exchange_config.get("password"),
        # DEX 지원
        "walletAddress": exchange_config.get("wallet_address"),
        "privateKey": exchange_config.get("private_key"),
    }

    return getattr(ccxt_module, name.lower())(ex_config)
```

### 1.3 재시도 데코레이터 패턴

```python
# common.py - API 재시도 처리
API_RETRY_COUNT = 4

def retrier(_func=None, *, retries=API_RETRY_COUNT):
    """API 호출 자동 재시도 데코레이터"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            count = kwargs.pop("count", retries)
            try:
                return f(*args, **kwargs)
            except (TemporaryError, RetryableOrderError) as ex:
                if count > 0:
                    backoff_delay = calculate_backoff(count + 1, retries)
                    time.sleep(backoff_delay)
                    kwargs.update({"count": count - 1})
                    return wrapper(*args, **kwargs)
                raise ex
        return cast(F, wrapper)
    return decorator if _func is None else decorator(_func)

# 사용 예시
@retrier
def fetch_order(self, order_id: str, pair: str):
    return self._api.fetch_order(order_id, pair)
```

### 1.4 OZ_A2M 적용 제안

```python
# 제1부서 ExchangeAdapter 개선안
class ExchangeAdapter:
    """개선된 ccxt 래퍼"""

    _exchange_capabilities: dict = {
        "binance": {
            "supports_futures": True,
            "supports_margin": True,
            "ws_enabled": True,
            "rate_limit": 1200,  # requests/minute
        },
        "bybit": {
            "supports_futures": True,
            "supports_margin": False,
            "ws_enabled": True,
            "rate_limit": 1000,
        },
    }

    def __init__(self, exchange_id: str, config: dict):
        self._api = self._init_ccxt(exchange_id, config)
        self._api_async = self._init_ccxt_async(exchange_id, config)
        self._cache = TTLCache(maxsize=100, ttl=300)

    @retrier(retries=3)
    async def fetch_ohlcv_with_fallback(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100
    ) -> List[List]:
        """OHLCV 조회 (WebSocket 우선, REST fallback)"""
        if self._ws and self._ws.is_connected():
            return await self._ws.fetch_ohlcv(symbol, timeframe)
        return await self._api_async.fetch_ohlcv(symbol, timeframe, limit=limit)
```

---

## 2. Strategy (전략) 인터페이스 패턴

### 2.1 IStrategy 추상 클래스

```python
class IStrategy(ABC, HyperStrategyMixin):
    """전략 인터페이스 - 모든 전략의 기본"""

    INTERFACE_VERSION: int = 3  # 버전 관리

    # 전략 설정
    minimal_roi: dict = {}  # 최소 수익률
    stoploss: float  # 스톱로스
    timeframe: str  # 시간 프레임
    can_short: bool = False  # 공매도 가능 여부

    # 주문 설정
    order_types: dict = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": False,
    }

    # 추상 메서드 - 반드시 구현 필요
    @abstractmethod
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """인디케이터 계산"""
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """진입 신호 생성 (오버라이드 가능)"""
        return self.populate_buy_trend(dataframe, metadata)

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """청산 신호 생성 (오버라이드 가능)"""
        return self.populate_sell_trend(dataframe, metadata)
```

### 2.2 콜백 패턴 (확장 지점)

```python
def confirm_trade_entry(
    self,
    pair: str,
    order_type: str,
    amount: float,
    rate: float,
    time_in_force: str,
    current_time: datetime,
    entry_tag: str | None,
    side: str,
    **kwargs,
) -> bool:
    """진입 전 확인 콜백"""
    return True  # 기본: 항상 진입

def confirm_trade_exit(
    self,
    pair: str,
    trade: Trade,
    order_type: str,
    amount: float,
    rate: float,
    exit_reason: str,
    **kwargs,
) -> bool:
    """청산 전 확인 콜백"""
    return True

def check_entry_timeout(
    self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs
) -> bool:
    """진입 타임아웃 체크"""
    return False  # 기본: 취소 안함
```

### 2.3 OZ_A2M 적용 제안

```python
# 제2부서 SignalGenerator 개선안
class TradingStrategy(ABC):
    """개선된 전략 인터페이스"""

    strategy_id: str
    timeframe: str
    supported_markets: List[str] = []

    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        indicators: IndicatorValues,
        market_data: MarketData
    ) -> Optional[TradingSignal]:
        """거래 신호 생성"""
        pass

    # 콜백 메서드
    def on_signal_confirmed(self, signal: TradingSignal) -> bool:
        """신호 확정 전 검증"""
        return True

    def on_position_update(self, trade: TradeRecord) -> Optional[TradingSignal]:
        """포지션 업데이트 시 추가 신호"""
        return None
```

---

## 3. Persistence (데이터 저장) 패턴

### 3.1 SQLAlchemy 모델 구조

```python
# base.py
class ModelBase(DeclarativeBase):
    """모든 모델의 기본 클래스"""
    session: ClassVar[SessionType]

# trade_model.py
class Order(ModelBase):
    """주문 데이터 모델"""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ft_trade_id: Mapped[int] = mapped_column(Integer, ForeignKey("trades.id"), index=True)

    # CCXT 호환 필드
    order_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(255))
    symbol: Mapped[str | None] = mapped_column(String(25))
    order_type: Mapped[str | None] = mapped_column(String(50))
    side: Mapped[str] = mapped_column(String(25))
    price: Mapped[float | None] = mapped_column(Float())
    average: Mapped[float | None] = mapped_column(Float())
    amount: Mapped[float | None] = mapped_column(Float())
    filled: Mapped[float | None] = mapped_column(Float())

    # 관계
    _trade: Mapped["Trade"] = relationship("Trade", back_populates="orders")

    def update_from_ccxt_object(self, order: CcxtOrder):
        """CCXT 응답으로 업데이트"""
        self.status = safe_value_fallback(order, "status", default_value=self.status)
        self.price = safe_value_fallback(order, "price", default_value=self.price)
        self.filled = safe_value_fallback(order, "filled", default_value=self.filled)
        # ...
```

### 3.2 데이터베이스 초기화 패턴

```python
def init_db(db_url: str) -> None:
    """데이터베이스 초기화"""
    kwargs = {}

    # SQLite 설정
    if db_url.startswith("sqlite://"):
        kwargs.update({
            "connect_args": {"check_same_thread": False},
        })
        if db_url == "sqlite://":
            kwargs["poolclass"] = StaticPool

    engine = create_engine(db_url, future=True, **kwargs)

    # 스레드 로컬 세션
    Trade.session = scoped_session(
        sessionmaker(bind=engine, autoflush=False),
        scopefunc=get_request_or_thread_id
    )

    # 테이블 생성 및 마이그레이션
    ModelBase.metadata.create_all(engine)
    check_migrate(engine, decl_base=ModelBase, previous_tables=inspect(engine).get_table_names())
```

### 3.3 OZ_A2M 적용 제안

```python
# 제5부서 PnL 개선안 - SQLAlchemy 통합

class TradeModel(ModelBase):
    """개선된 거래 모델"""
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(25), index=True)

    # 가격 정보
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    # 수량 정보
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal('0'))

    # 수수료
    entry_fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal('0'))
    exit_fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal('0'))

    # 손익 계산 (SQL에서 자동 계산)
    @hybrid_property
    def realized_pnl(self) -> Decimal:
        if not self.exit_price:
            return Decimal('0')
        gross_pnl = (self.exit_price - self.entry_price) * self.quantity
        return gross_pnl - self.entry_fee - self.exit_fee
```

---

## 4. 핵심 학습 포인트

### 4.1 ccxt 래퍼 베스트 프랙티스

1. **재시도 패턴**: `@retrier` 데코레이터로 API 실패 시 자동 재시도
2. **캐싱**: TTLCache로 API 호출 최소화
3. **비동기 지원**: sync/async 병행, WebSocket 우선
4. **거래소별 설정**: `_ft_has` 딕셔너리로 거래소별 차이 추상화
5. **타입 안전**: TypedDict로 ccxt 응답 타입 정의

### 4.2 전략 인터페이스 베스트 프랙티스

1. **버전 관리**: `INTERFACE_VERSION`으로 하위 호환성 관리
2. **콜백 패턴**: 확장 지점을 콜백 메서드로 제공
3. **데이터프레임 기반**: pandas DataFrame으로 데이터 흐름
4. **메타데이터 전달**: `metadata` dict로 추가 정보 전달

### 4.3 데이터 저장 베스트 프랙티스

1. **ORM 사용**: SQLAlchemy 2.0 (DeclarativeBase)
2. **ccxt 호환**: `update_from_ccxt_object()` 메서드
3. **스레드 안전**: `scoped_session`으로 스레드별 세션 관리
4. **마이그레이션**: `check_migrate()`로 스키마 버전 관리
5. **하이브리드 속성**: `@hybrid_property`로 SQL/Python 계산 공유

---

## 5. 적용 우선순위

| 우선순위 | 대상 | 개선 사항 | 예상 효과 |
|---------|------|----------|----------|
| 1 | ExchangeAdapter | 재시도 데코레이터, 캐싱 레이어 | API 안정성 ↑ |
| 2 | SignalGenerator | 콜백 패턴, 버전 관리 | 확장성 ↑ |
| 3 | TradeRecord | SQLAlchemy ORM 전환 | 쿼리 성능 ↑ |
| 4 | ControlTower | WebSocket 지원 | 지연 시간 ↓ |
| 5 | DataRouter | ccxt 응답 정규화 | 일관성 ↑ |

---

## 6. 참고 자료

- **Freqtrade GitHub**: https://github.com/freqtrade/freqtrade
- **ccxt 문서**: https://docs.ccxt.com/
- **SQLAlchemy 2.0**: https://docs.sqlalchemy.org/

---

*생성일: 2026-03-27*
*목적: OZ_A2M 제1부서 관제탑센터 개선 참고*
