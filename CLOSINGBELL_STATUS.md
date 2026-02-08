# ClosingBell 프로젝트 현황 및 개선 로드맵

## 프로젝트 개요

ClosingBell은 한국 주식 시장 장마감 후 종목 스크리닝 → AI 분석 → 디스코드 알림 → 대시보드 조회까지의 파이프라인을 자동화하는 시스템입니다.

- **규모**: 94개 파일 / 34,000줄 (Python)
- **버전**: v10.1 (2026-02-08 기준)
- **환경**: Windows PC (AMD 9800X3D, 64GB) + Streamlit Cloud (웹 대시보드)
- **DB**: SQLite (data/screener.db) — 23개 테이블
- **API**: 한국투자증권(KIS), 네이버금융, DART, Gemini AI, 디스코드 웹훅

---

## 아키텍처

```
[데이터 수집]                    [분석/처리]                   [출력]
                                                              
OHLCV CSV (키움) ─┐                                          ├─ Streamlit 대시보드 (8페이지)
네이버 금융 크롤링 ─┤  → 스크리닝 엔진  → AI 분석 (Gemini) ─┤─ 디스코드 웹훅
DART API ──────────┤  → 점수 산정      → 등급 배정          ├─ 리포트 파일 (.md)
KIS API (실시간) ──┘  → 시그널 생성    → 추적               └─ SQLite DB
```

### 핵심 모듈

| 모듈 | 파일 | 역할 |
|------|------|------|
| **스케줄러** | `main.py` + `scheduler.py` (716줄) | APScheduler 기반 장중/장후 작업 자동 실행 |
| **DB** | `database.py` (1,145줄) | SQLite + 마이그레이션 23개 테이블 |
| **스크리닝** | `enrichment_service.py` (664줄) | 100점 점수제 + S/A/B/C/D 등급 |
| **AI 분석** | `ai_pipeline.py` (597줄) + `ai_service.py` (374줄) | Gemini 기반 종목 분석 |
| **기업정보** | `company_service.py` (672줄) | 네이버/DART 크롤링 → 시총/PER/PBR 등 |
| **백필** | `backfill_service.py` (761줄) | 과거 데이터 소급 수집 |
| **눌림목** | `pullback_tracker.py` (296줄) | 거래량 폭발 후 눌림목 시그널 감지 |
| **매매일지** | `trade_journal_service.py` (540줄) | KIS API 체결내역 자동 기록 |
| **디스코드** | `discord_service.py` + `discord_embed_builder.py` | 분석 결과 웹훅 전송 |

### 대시보드 (Streamlit, 8페이지)

| 페이지 | 파일 | 기능 |
|--------|------|------|
| 감시종목 TOP5 | `1_top5_tracker.py` (763줄) | 종목 카드 + 캔들차트 + D+20 성과 |
| 유목민 공부법 | `2_nomad_study.py` (699줄) | 상한가/거래량 종목 + 기업정보 |
| 종목 검색 | `3_stock_search.py` | 통합 검색 + 캔들차트 |
| 거래원 수급 | `4_broker_flow.py` | 기관/외국인 매매 동향 |
| 심층분석 | `5_stock_analysis.py` (1,078줄) | 보유종목 리포트 뷰어 |
| 보유종목 | `6_holdings_watch.py` | 실시간 보유 현황 |
| 눌림목 스캐너 | `7_pullback.py` (617줄) | 거래량 폭발 후 눌림목 시그널 |
| 매매일지 | `8_trade_journal.py` | 매매 기록 + 손익비 분석 |

### 스케줄러 타임라인 (장 시작~종료)

```
08:55  프리장 준비 (KIS 토큰)
09:01  프리뷰 스크리닝
12:30  프리뷰 스크리닝
14:55  눌림목 시그널 감지
15:00  메인 스크리닝 (TOP5 확정)
16:00  OHLCV 수집
16:05  거래량 폭발 감지
16:07  눌림목 D+1~D+5 추적
16:10  글로벌 데이터
16:32  유목민 수집
16:37  기업정보 크롤링
16:39  유목민 뉴스
16:40  AI 분석 (유목민)
16:45  AI 분석 (TOP5)
16:48  AI 분석 (거래원)
16:50  보유종목 동기화 + 심층분석 + 매매일지 + 디스코드
17:30  자동 종료
```

---

## DB 스키마 (주요 테이블)

| 테이블 | 행수 | 용도 |
|--------|------|------|
| `closing_top5_history` | 119 | 일별 TOP5 스크리닝 결과 |
| `top5_daily_prices` | 986 | TOP5 종목 D+1~D+20 가격 추적 |
| `nomad_candidates` | 818 | 유목민 후보 (상한가/거래량천만) |
| `nomad_news` | 7,790 | 유목민 종목 뉴스 |
| `pullback_signals` | 5 | 눌림목 시그널 |
| `volume_spikes` | ? | 거래량 폭발 감시풀 |
| `holdings_watch` | 1 | 보유종목 관찰 (휴림로봇 107주) |
| `broker_signals` | 6 | 거래원 수급 시그널 |
| `short_selling_daily` | 0 | 공매도 데이터 (수집 로직 있으나 빈 상태) |
| `support_resistance_cache` | 0 | 지지/저항선 (수집 로직 있으나 빈 상태) |

---

## 현재 알려진 이슈 (v10.1 기준)

### 🔴 즉시 수정 필요

1. **TOP5 요약 카드 HTML 깨짐**
   - 위치: `dashboard/pages/1_top5_tracker.py` 약 490줄
   - 원인: v10.1에서 공매도 배지 추가 시 f-string 안에 조건부 HTML을 넣어서 Streamlit `unsafe_allow_html` 렌더링 깨짐
   - 증상: `<div style="background...` 태그가 텍스트로 노출
   - 해결 방향: 조건부 HTML을 f-string 밖으로 분리하거나 st.columns + st.markdown 분리

2. **공매도/지지저항 데이터 비어있음**
   - `short_selling_daily`, `support_resistance_cache` 테이블 모두 0건
   - 수집 로직은 존재하지만 스케줄러에서 실행되지 않는 것으로 추정
   - 확인 필요: 수집 함수가 스케줄러에 등록되어 있는지, API 키 필요한지

3. **pullback_daily_prices 비어있음**
   - 눌림목 D+1~D+5 추적 결과 저장 테이블이 0건
   - 스케줄러 16:07에 추적 작업 등록은 되어 있으나 실제 데이터 기록 확인 필요

### 🟡 개선 필요

4. **DART 경로에서 시총/PER/PBR 수집 안 됨 (v10.1에서 수정됨)**
   - `company_service.py`의 DART 수집 경로에서 `naver_info.per` (dict에 속성 접근) 버그
   - v10.1 패치에서 `.get('per')` + market_cap 포함으로 수정 완료
   - 기존 데이터는 `python tools/db_cleanup.py --repair-mcap`으로 복구

5. **인트로메딕 등 일부 종목 시총 파싱 실패**
   - 네이버 HTML에 시총이 "0"으로 표시되는 종목 (거래정지/관리종목 추정)
   - 국보(001140) 등 상장폐지 종목도 포함
   - 해결: 이런 종목은 DART 기업정보 또는 KRX 시가총액 API로 폴백

6. **Streamlit `use_container_width` → `width` 마이그레이션 불안정**
   - v10.1에서 `width="stretch"` 마이그레이션 완료했으나
   - `st.button`은 `use_container_width=True` 유지해야 함 (Streamlit 버전별 차이)
   - 실제 배포 환경 Streamlit 버전 확인 후 일괄 통일 필요

### ℹ️ 참고

7. **웹(Streamlit Cloud) vs 로컬 데이터 차이**
   - 로컬: OHLCV CSV 파일 + SQLite DB (전체 기능)
   - 웹: FinanceDataReader(FDR) 온라인 조회 + DB 읽기만
   - AI 분석, 기업정보 크롤링은 로컬에서만 실행 → DB에 저장 → 웹은 읽기

8. **테스트 커버리지**
   - `tests/test_v10_1_e2e.py`: 71개 테스트 (import, 함수 존재, 설정 검증 중심)
   - 실제 데이터 흐름 통합 테스트는 없음 (스크리닝 → DB 저장 → 대시보드 표시)

---

## 개선 로드맵

### Phase 1: 안정화 (현재 → 1주)

목표: 기존 기능이 매일 에러 없이 돌아가는 상태

- [ ] TOP5 요약 카드 HTML 렌더링 수정
- [ ] 공매도/지지저항 수집 파이프라인 활성화 (스케줄러 등록 확인)
- [ ] 눌림목 D+1~D+5 추적 데이터 실제 기록 확인
- [ ] 기업정보 수집 후 시총/PER/PBR 정상 저장 검증 (매일 db_cleanup.py 실행)
- [ ] Streamlit Cloud 배포 후 웹 정상 동작 확인
- [ ] 디스코드 웹훅 전송 내용 정확성 확인

### Phase 2: 데이터 품질 (1~2주)

목표: 수집 데이터의 완전성과 정확성 보장

- [ ] 공매도 데이터 수집 활성화 (KRX 공매도 API 또는 네이버 크롤링)
- [ ] 지지/저항선 계산 로직 활성화 (매물대 분석)
- [ ] 기업정보 크롤링 실패 폴백 강화 (네이버 → DART → KRX)
- [ ] 백필 데이터 정합성 검증 (backfill vs realtime 결과 비교)
- [ ] 휴장일/반일 자동 감지 (현재는 수동 달력 기반)

### Phase 3: 대시보드 UX (2~3주)

목표: 트레이딩 의사결정에 실질적으로 도움되는 UI

- [ ] TOP5 카드: HTML raw 렌더링 → st.columns + st.metric 컴포넌트 기반으로 리팩토링
- [ ] 날짜 네비게이션: ← 이전일 / 다음일 → 버튼 + 키보드 단축키
- [ ] 종목 비교 뷰: 선택한 2~3개 종목 나란히 차트 비교
- [ ] 모바일 최적화: Streamlit은 기본 반응형이지만 카드 레이아웃 개선
- [ ] 다크모드 지원
- [ ] 공매도/지지저항 데이터가 채워지면 대시보드에 자연스럽게 표시

### Phase 4: 트레이딩 고도화 (1~2개월)

목표: 유목민 전략의 체계적 실행 지원

- [ ] 유목민 거래량 단타법 시그널 자동 감지
  - 역사적 저점 터치 → 악재 소멸 → 거래량 급감 → 거래량 폭발 패턴
  - 현재 눌림목 스캐너와 통합 가능
- [ ] 매매일지 자동 분석: 시그널별 승률, 보유기간별 수익률
- [ ] 포지션 사이징 제안 (시총/변동성 기반)
- [ ] 리스크 대시보드: 포트폴리오 집중도, 섹터 노출, 최대 손실 시나리오
- [ ] ScalpingBot/Hantubot 연동: 자동매매 시그널 ↔ ClosingBell 분석 연결

### Phase 5: 인프라 (장기)

- [ ] SQLite → PostgreSQL 마이그레이션 (동시 접근 이슈 대비)
- [ ] Docker 컨테이너화 (환경 재현성)
- [ ] CI/CD 파이프라인 (GitHub Actions → 자동 테스트 → 배포)
- [ ] 통합 테스트 추가 (데이터 흐름 end-to-end)
- [ ] 로그 모니터링 (에러 발생 시 디스코드 알림)

---

## 파일 구조 (주요)

```
C:\Coding\ClosingBell\
├── main.py                           # 엔트리포인트 (CLI + 스케줄러)
├── dashboard/
│   ├── app.py                        # Streamlit 메인
│   ├── components/
│   │   ├── sidebar.py                # 공통 사이드바
│   │   └── date_utils.py             # 휴장일 보정 유틸
│   └── pages/
│       ├── 1_top5_tracker.py         # 감시종목 TOP5
│       ├── 2_nomad_study.py          # 유목민 공부법
│       ├── 3_stock_search.py         # 종목 검색
│       ├── 4_broker_flow.py          # 거래원 수급
│       ├── 5_stock_analysis.py       # 심층분석 리포트
│       ├── 6_holdings_watch.py       # 보유종목 관찰
│       ├── 7_pullback.py             # 눌림목 스캐너
│       └── 8_trade_journal.py        # 매매일지
├── src/
│   ├── config/                       # 설정 파일
│   ├── infrastructure/
│   │   ├── database.py               # DB + 마이그레이션
│   │   ├── scheduler.py              # 스케줄러
│   │   ├── repo_top5.py              # TOP5 repo
│   │   ├── repo_nomad.py             # 유목민 repo
│   │   └── repository.py             # repo 팩토리
│   ├── services/
│   │   ├── company_service.py        # 기업정보 수집
│   │   ├── ai_service.py             # Gemini AI
│   │   ├── ai_pipeline.py            # AI 파이프라인
│   │   ├── discord_service.py        # 디스코드
│   │   ├── enrichment_service.py     # 점수/등급
│   │   ├── pullback_tracker.py       # 눌림목
│   │   ├── trade_journal_service.py  # 매매일지
│   │   └── backfill/                 # 백필 서비스
│   └── utils/
│       └── market_calendar.py        # 휴장일 판단
├── tools/
│   ├── db_cleanup.py                 # DB 진단/정리
│   └── test_mcap.py                  # 시총 수집 테스트
├── tests/
│   └── test_v10_1_e2e.py             # E2E 테스트 (71개)
└── data/
    └── screener.db                   # SQLite DB
```

---

## 이 프롬프트 사용법

새 대화를 시작할 때 이 문서를 첨부하고 다음과 같이 요청:

```
이 문서는 ClosingBell 프로젝트 현황입니다. 
[구체적 요청: 예) Phase 1의 TOP5 카드 렌더링 수정해주세요]
코드는 업로드된 파일을 참조하세요.
```

필요 시 관련 파일만 선별 업로드:
- 대시보드 수정 → 해당 page 파일 + database.py + repo 파일
- 스케줄러 문제 → main.py + scheduler.py + 해당 service 파일
- 데이터 수집 → company_service.py + repo 파일 + database.py
