# ClosingBell v6.5.1 업데이트

## 📋 변경사항 요약

### Phase 1: 버전 통일 + 전역상수
- `src/config/app_config.py` (🆕 신규)
  - APP_VERSION = "v6.5"
  - AI_ENGINE = "Gemini 2.5 Flash"
  - 데이터 경로, 푸터 문구 통합 관리
- 대시보드 전체 버전 통일 (v6.3 → v6.5)

### Phase 2: UI/UX 개선
- 유목민 종목 카드 레이아웃 개선 (컴팩트)
- "기업정보 재수집" 버튼 삭제 (배포 환경 에러 방지)

### Phase 3: DART 확장
- `dart_service.py` 확장
  - 최대주주 지분율 조회 (`get_major_shareholder`)
  - 감사의견 조회 (`get_audit_opinion`)
  - 자본변동 공시 조회 (`get_capital_changes`)
- AI 프롬프트에 새 정보 포함

### Phase 4: AI 분석 개선
- `ai_service.py` 개선
  - PER/PBR 없을 때 "테마·수급 중심 종목" 컨텍스트 제공
  - 유목민 공부법: 목표가/매수/매도 추천 금지
  - 공부 포인트 필드 추가
- `top5_ai_service.py` 개선
  - 밸류에이션 컨텍스트 개선

### 기존 수정 (v6.5)
- Discord 웹훅: 등급(🏆S, 🥇A), 시총, 거래량 표시
- RSI 계산 함수 추가
- PER/PBR/ROE 네이버 보충 수집

---

## 📁 폴더 구조

```
closingbell_v6.5.1_release/
├── src/
│   ├── config/
│   │   └── app_config.py        # 🆕 전역상수
│   ├── domain/
│   │   ├── indicators.py        # RSI 추가
│   │   └── score_calculator.py  # raw_rsi 필드
│   └── services/
│       ├── ai_service.py        # AI 프롬프트 개선
│       ├── company_service.py   # PER/PBR/ROE 보충
│       ├── dart_service.py      # 최대주주/감사의견
│       ├── discord_embed_builder.py  # 등급/시총/거래량
│       ├── screener_service.py  # market_cap 전달
│       └── top5_ai_service.py   # 밸류에이션 개선
├── scripts/
│   └── test_discord_webhook.py  # 웹훅 테스트
├── dashboard/
│   ├── app.py                   # 버전 통일
│   └── pages/
│       ├── 1_top5_tracker.py    # 버전 통일
│       ├── 2_nomad_study.py     # 레이아웃 + 버튼 삭제
│       └── 3_stock_search.py    # 버전 통일
├── README.md
└── TEST_GUIDE.md
```

---

## 🔧 설치 방법

### 1. 파일 복사 (덮어쓰기)

```
기존 프로젝트/
├── src/
│   ├── config/
│   │   └── app_config.py  ← 새로 추가
│   ├── domain/
│   │   ├── indicators.py  ← 덮어쓰기
│   │   └── score_calculator.py  ← 덮어쓰기
│   └── services/
│       ├── ai_service.py  ← 덮어쓰기
│       ├── company_service.py  ← 덮어쓰기
│       ├── dart_service.py  ← 덮어쓰기
│       ├── discord_embed_builder.py  ← 덮어쓰기
│       ├── screener_service.py  ← 덮어쓰기
│       └── top5_ai_service.py  ← 덮어쓰기
├── scripts/
│   └── test_discord_webhook.py  ← 덮어쓰기
└── dashboard/
    ├── app.py  ← 덮어쓰기
    └── pages/
        ├── 1_top5_tracker.py  ← 덮어쓰기
        ├── 2_nomad_study.py  ← 덮어쓰기
        └── 3_stock_search.py  ← 덮어쓰기
```

### 2. 파일 복사 명령어 (Windows)

```cmd
# 압축 해제 후 closingbell 폴더에서 실행
xcopy /Y closingbell_v6.5.1_release\src\config\* src\config\
xcopy /Y closingbell_v6.5.1_release\src\domain\* src\domain\
xcopy /Y closingbell_v6.5.1_release\src\services\* src\services\
xcopy /Y closingbell_v6.5.1_release\scripts\* scripts\
xcopy /Y closingbell_v6.5.1_release\dashboard\* dashboard\
xcopy /Y /S closingbell_v6.5.1_release\dashboard\pages\* dashboard\pages\
```

---

## ⚠️ 주의사항

1. **백업 권장**: 기존 파일 백업 후 덮어쓰기
2. **Python 버전**: 3.10 이상 권장
3. **환경변수**: .env 파일 확인 (DART_API_KEY, GEMINI_API_KEY)

---

## 📞 문의

테스트 가이드는 `TEST_GUIDE.md` 참고
