# ClosingBell v7.0 - 키움 REST API 전환

## 🆕 v7.0 변경사항

### 1️⃣ 키움증권 REST API 전환 (KIS → Kiwoom)
- **KIS 의존성 완전 제거**
- 키움 REST API로 모든 데이터 조회
- OAuth 토큰 자동 갱신 (메모리 + 파일 캐시)
- Rate Limit 핸들링 (초당 8회)
- Circuit Breaker (연속 실패 시 폴백)

### 2️⃣ 유니버스 조회 개선
- **TV200 조건검색 → 거래대금+거래량 랭킹 조합**
- 거래대금 상위 300개 (ka10032, 연속조회)
- 거래량 상위 150개 (ka10030, 연속조회)
- 교집합 + 필터: 거래대금≥150억, 등락률1~30%

### 3️⃣ Quiet Accumulation 스크리너 (🆕 신규)
- **"거래량 폭발 전, 조용한 축적 패턴" 탐지**
- 가격: 2,000~10,000원
- 변동성 낮음 + 박스권 수렴
- 거래대금 미세 상승 (5일/20일 비율)
- 60일 고점 대비 80% 이상 + 저점 상승 추세

### 4️⃣ Discord 2000자 자동 분할
- 긴 메시지 자동 분할 발송
- 코드블록 래핑 유지

---

## 📋 필수 설정 (.env)

```bash
# 키움증권 REST API 설정 (필수)
KIWOOM_APPKEY=your_appkey
KIWOOM_SECRETKEY=your_secretkey
KIWOOM_BASE_URL=https://api.kiwoom.com
KIWOOM_USE_MOCK=false
```

---

## 🚀 사용법

### 기본 실행
```bash
python main.py              # 스케줄러 모드
python main.py --run        # 즉시 실행
python main.py --run-test   # 테스트 (알림X)
```

### Quiet Accumulation (v7.0 신규)
```bash
python main.py --run-quiet  # 조용한 축적 패턴 스캔
```

### 백필 및 유틸
```bash
python main.py --backfill 20     # 과거 20일 백필
python main.py --check 005930    # 종목 점수 확인
python main.py --validate        # 설정 검증
```

---

## 📁 주요 파일 구조

```
ClosingBell/
├── main.py                    # v7.0 메인
├── src/
│   ├── adapters/
│   │   ├── kiwoom_rest_client.py  # 키움 REST API
│   │   └── discord_notifier.py    # 2000자 분할
│   ├── config/
│   │   ├── settings.py        # 키움 설정 추가
│   │   └── app_config.py      # v7.0 버전
│   └── services/
│       ├── screener_service.py    # 키움 유니버스
│       └── quiet_accumulation.py  # 🆕 선행 신호
├── .env                       # 키움 API 키
└── README.md
```

---

## 📊 스케줄 (기본)

| 시간 | 작업 |
|------|------|
| 12:00 | 프리뷰 스크리닝 |
| 15:00 | 메인 스크리닝 (TOP5) |
| 15:05 | Quiet Accumulation (선행 신호) |
| 17:40 | 자동 종료 |

---

## ⚠️ 주의사항

1. **키움 API 키 필수**: .env에 KIWOOM_APPKEY, KIWOOM_SECRETKEY 설정
2. **Python 3.10+** 권장
3. **KIS 설정은 레거시**: 더 이상 사용하지 않음 (삭제 가능)

---

## 📈 버전 히스토리

- **v7.0** (2026-02-04): 키움 REST API 전환, Quiet Accumulation
- **v6.5** (2026-01-29): Discord 등급/시총 표시, RSI 추가
- **v6.4** (2026-01-28): TV200 스냅샷 DB 저장
- **v6.3** (2026-01-27): CCI 하드필터 비활성화
