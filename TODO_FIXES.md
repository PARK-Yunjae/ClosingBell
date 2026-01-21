# ClosingBell v6.1 수정사항 및 TODO

## ✅ 이번 업데이트 완료 (2026-01-20)

### 1. 네이버 금융 기업정보 수집 완전 재작성 (`company_service.py`)

이전 대화에서 논의된 모든 데이터 수집:

| 항목 | 소스 | 패턴 |
|------|------|------|
| 시가총액 | coinfo | `id="_market_sum"` |
| 시가총액순위 | coinfo | `코스피 <em>13</em>위` |
| PER | coinfo | `id="_per"` |
| EPS | coinfo | `id="_eps"` |
| PBR | coinfo | `id="_pbr"` |
| BPS | coinfo | PBR 다음 `<em>` |
| ROE | main | `ROE.*<em>` |
| 추정 PER | coinfo | `id="_cns_per"` |
| 추정 EPS | coinfo | `id="_cns_eps"` |
| 외국인보유율 | coinfo | `외국인소진율` |
| 외국인보유주수 | coinfo | `외국인보유주식수` |
| 투자의견 | coinfo | `<em>4.00</em>매수` |
| 목표주가 | coinfo | `목표주가</th>...<em>` |
| 52주최고/최저 | coinfo | `52주최고...<em>` |
| 배당수익률 | coinfo | `배당수익률` |
| 기업개요 | coinfo | `<p>동사는...` |
| 업종 | main | `업종...<a>` |
| 시장 | main | `kospi_link` |
| 매출액/영업이익 | main | 텍스트 파싱 |

### 2. DB 스키마 확장 (`migrations/v6_1_add_company_fields.sql`)

새로 추가된 컬럼:
- `bps` - 주당순자산
- `foreign_rate` - 외국인 보유율
- `foreign_shares` - 외국인 보유주수
- `analyst_opinion` - 투자의견 점수 (1~5)
- `analyst_recommend` - 매수/매도/중립
- `target_price` - 목표주가
- `high_52w`, `low_52w` - 52주 최고/최저
- `market_cap_rank` - 시가총액 순위
- `consensus_per`, `consensus_eps` - 컨센서스
- `dividend_yield` - 배당수익률

### 3. 유목민 공부법 페이지 완전 재작성 (`2_유목민_공부법.py`)

- **기업정보 탭**: 모든 수집 데이터 표시
  - 밸류에이션 (PER/PBR/ROE/EPS/BPS)
  - 외국인/투자의견
  - 52주 범위 (프로그레스 바 시각화)
  - 재무정보
  
- **AI 종합 분석 탭**: 수집된 모든 데이터 활용
  - Gemini 2.0 Flash 모델 사용 (무료)
  - 분석 항목:
    - 핵심 요약
    - 주가 움직임 원인
    - 밸류에이션 분석
    - 외국인 수급 분석
    - 투자 포인트 / 리스크 요인
    - 52주 위치 코멘트
    - 목표가 분석
    - 단기 전망 (1-2주)
    - 종합 의견 (매수/관망/매도)

### 4. Repository 업데이트 (`repository.py`)

- `update_company_info_by_id` 메서드에 새 컬럼 추가

---

## 📋 남은 TODO (나중에)

### 1. 스트림릿 메인페이지 개선

- [ ] 하단 "최근 결과" 항목 날짜 변경 안됨
- [ ] 스크롤 생기면서 흔들리는 문제
- [ ] 소수점 가독성 개선 (CCI, 이평선 등 → 소수점 1자리)

### 2. 데이터 정리

- [ ] 20일 데이터 삭제 (장 시작 전이라 비어있음)
  ```bash
  python delete_20th.py
  ```

---

## 🚀 설치 방법 (중요!)

### 1. DB 마이그레이션 (새 컬럼 추가)

```bash
cd C:\Coding\ClosingBell

# 마이그레이션 실행
sqlite3 data/screener.db < migrations/v6_1_add_company_fields.sql
```

> ⚠️ 이미 존재하는 컬럼은 에러가 나지만 무시해도 됩니다.

### 2. 기업정보 재수집

```bash
# DB에서 company_info_collected 플래그 리셋
sqlite3 data/screener.db "UPDATE nomad_candidates SET company_info_collected = 0"

# 수정된 company_service.py로 재수집
python main.py --run-company-info
```

### 3. 대시보드 실행

```bash
streamlit run dashboard/app.py
```

---

## 🧪 테스트 방법

### 기업정보 크롤링 테스트
```bash
cd C:\Coding\ClosingBell
python -c "from src.services.company_service import fetch_naver_finance; info=fetch_naver_finance('005930'); print([f'{k}: {v}' for k,v in info.items() if v])"
```

예상 출력:
```
market: KOSPI
sector: 반도체
market_cap: 3450000.0
market_cap_rank: 1
per: 11.75
eps: 5777.0
pbr: 1.56
bps: 43611.0
foreign_rate: 55.23
analyst_opinion: 4.5
analyst_recommend: 매수
target_price: 85000
high_52w: 88000
low_52w: 52800
...
```

---

## 📁 변경된 파일

1. `src/services/company_service.py` - 완전 재작성 (이전 대화 논의 반영)
2. `src/infrastructure/repository.py` - 새 컬럼 저장 추가
3. `dashboard/pages/2_유목민_공부법.py` - 완전 재작성 (새 데이터 + AI 분석)
4. `migrations/v6_1_add_company_fields.sql` - 새 컬럼 마이그레이션
