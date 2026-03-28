# OZ_A2M - AI-Powered Multi-Agent Trading System

🤖 **OZ_A2M**은 7개 부서의 AI 에이전트가 협업하여 실시간 암호화폐 트레이딩을 수행하는 분산 시스템입니다.

## 🏗️ 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                         OZ_A2M System                           │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│   제1부서 │   제2부서 │   제3부서 │   제4부서 │   제5부서 │   제6부서 │
│  시장분석 │  전략수립 │  리스크관리│  포트폴리오│  데이터관리│  시스템운영│
│   (MA)   │   (ST)   │   (RM)   │   (PM)   │   (DM)   │   (SO)   │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬─────┘
     │          │          │          │          │          │
     └──────────┴──────────┴────┬─────┴──────────┴──────────┘
                                │
                    ┌───────────┴───────────┐
                    │       제7부서         │
                    │     운영팀 (OPS)       │
                    │   - 실제 거래 실행     │
                    │   - Freqtrade 연동    │
                    └───────────────────────┘
```

## 📁 프로젝트 구조

```
OZ_A2M/
├── department_1/          # 제1부서: 시장분석 (Market Analysis)
├── department_2/          # 제2부서: 전략수립 (Strategy)
├── department_3/          # 제3부서: 리스크관리 (Risk Management)
├── department_4/          # 제4부서: 포트폴리오관리 (Portfolio)
├── department_5/          # 제5부서: 데이터관리 (Data Management)
├── department_6/          # 제6부서: 시스템운영 (System Operations)
├── department_7/          # 제7부서: 운영팀 (Operations)
├── lib/                   # 공통 라이브러리
├── config/                # 시스템 설정
├── tests/                 # 통합 테스트
└── docs/                  # 문서
```

## 🚀 빠른 시작

### 필수 요구사항
- Python 3.11+
- Docker & Docker Compose
- 8GB+ RAM

### 설치

```bash
# 저장소 클론
git clone https://github.com/OzzyHA-company/OZ_A2M.git
cd OZ_A2M

# 가상환경 설정
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 패키지 설치
pip install -e ".[all]"

# 환경 변수 설정
cp .env.example .env
# .env 파일 편집

# 서비스 시작
docker-compose up -d
```

### 서비스 확인

```bash
# Gateway 상태 확인
curl http://localhost:8000/health

# MQTT 브로커 상태
mosquitto_sub -h localhost -t "#" -v

# Netdata 대시보드
open http://localhost:19999

# Trading UI
open http://localhost:8080
```

## 🔧 주요 기능

### 핵심 서비스
- **MQTT Broker**: 실시간 메시징 (mosquitto)
- **Redis**: 캐싱 및 상태 관리
- **Elasticsearch**: 로그 및 데이터 저장
- **Netdata**: 시스템 모니터링
- **FastAPI Gateway**: API 게이트웨이
- **Freqtrade**: 자동 트레이딩 엔진

### 부서별 역할

| 부서 | 역할 | 기술 스택 |
|------|------|----------|
| 제1부서 | 시장 분석 및 예측 | pandas, numpy, scikit-learn |
| 제2부서 | 트레이딩 전략 개발 | ta-lib, freqtrade |
| 제3부서 | 리스크 관리 및 감사 | VaR, Monte Carlo |
| 제4부서 | 포트폴리오 최적화 | PyPortfolioOpt |
| 제5부서 | 데이터 수집 및 관리 | Apache Kafka, InfluxDB |
| 제6부서 | 시스템 운영 및 모니터링 | Prometheus, Grafana |
| 제7부서 | 실제 거래 실행 | Freqtrade, CCXT |

## 📡 MQTT 토픽 구조

```
oz_a2m/
├── market/
│   ├── price/{symbol}      # 실시간 가격
│   ├── orderbook/{symbol}  # 오더북
│   └── signals             # 거래 신호
├── orders/
│   ├── new                 # 새 주문
│   ├── update              # 주문 업데이트
│   └── status              # 주문 상태
├── system/
│   ├── health              # 시스템 상태
│   ├── logs                # 로그
│   └── alerts              # 알림
└── agents/
    ├── d1/analysis         # 제1부서 분석 결과
    ├── d2/strategy         # 제2부서 전략
    └── d7/execution        # 제7부서 실행 결과
```

## 🔐 보안

- CSRF 보호 적용
- API 키 암호화 저장
- 보안 감사 로깅
- 비밀번호 해싱 (bcrypt)

## 📝 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 🤝 기여

기여는 언제나 환영합니다! 자세한 내용은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참조하세요.

---

**Made with ❤️ by OzzyHA Company**
