# 네트워크 문제 해결 요약

**Date:** 2026-04-06  
**Status:** Jito Shredstream 승인 대기 중, 대체 방안 모색 중

---

## 현재 상황 (최종)

| 시도 | 결과 |
|------|------|
| Helius Free | ❌ Rate limit (100req/min) |
| QuickNode Free | ❌ Rate limit 걸림 |
| Jito Shredstream | ⏳ 승인 대기 중 |
| 공유기 포트포워딩 | ❌ 메인 공유기 접근 불가 (스위칭허브 환경) |
| UPnP | ❌ 비활성화됨 |
| Jito Block Engine | ⚠️ HTTPS는 가능하지만 블록 데이터 지연 |

---

## 남은 선택지

### 1. 여러 RPC 프로바이더 Round-Robin ⭐ (즉시 적용 가능)
```python
# lib/core/multi_rpc_manager.py 구현
# Helius + QuickNode + Alchemy + Syndica 순환 사용
```

**장점:** 무제한, 설정 즉시 가능  
**단점:** 각 provider별 계정 필요, 관리 복잡

### 2. Jito Shredstream 승인 + 공유기 관리자 설득
- Jito Discord에서 승인 확인
- 건축주/관리실/입주민 대표 연락 시도

### 3. 유료 RPC 플랜
- Helius Developer: $49/month
- QuickNode Solana: $49/month

### 4. 로컬 Solana 검증자 노드 (Validator)
- 직접 노드 운영 (하지만 리소스 많이 필요)

---

## 즉시 적용: Multi-RPC Round-Robin

여러 묣은 RPC를 번갈아 사용하여 rate limit 회피:

| Provider | Free Tier | 특징 |
|----------|-----------|------|
| Helius | 100 req/min | 현재 사용 중, 제한됨 |
| QuickNode | 제한됨 | 이전 사용, 제한됨 |
| Alchemy | 300M CU | 아직 사용 안 함 |
| Syndica | 묣은 티어 | 아직 사용 안 함 |
| Chainstack | 묣은 요청 | 아직 사용 안 함 |
| GetBlock | 묣은 티어 | 아직 사용 안 함 |

---

## 구현 제안

### MultiRPCManager 클래스 생성
- 여러 RPC 엔드포인트 관리
- 자동 failover
- Rate limit 감지 시 다음 provider로 전환

**필요 여부 확인:** 위 multi-RPC 방식으로 구현해 드릴까요?
