# ClosingBell v9.0 - 종목 심층 분석

## ✨ 핵심 기능
- 감시종목 TOP5 스크리닝 (7핵심 100점)
- 매물대(Volume Profile) 표시
- `--analyze` 종목 심층 분석 리포트 생성
- 대시보드 5번 페이지: 종목 심층 분석

---

## 🚀 사용법

### 기본 실행
```bash
python main.py              # 스케줄러 모드
python main.py --run        # 즉시 실행
python main.py --run-test   # 테스트 (알림X)
```

### 종목 심층 분석
```bash
python main.py --analyze 090710
python main.py --analyze 090710 --full
```

### 백필 및 유틸
```bash
python main.py --backfill 20     # 과거 20일 백필
python main.py --check 005930    # 종목 점수 확인
python main.py --validate        # 설정 검증
```

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

## 📁 주요 구조

```
ClosingBell/
├── main.py
├── src/
│   ├── analyzers/               # v9.0 분석 모듈
│   ├── services/
│   │   ├── screener_service.py
│   │   ├── analysis_report.py
│   │   └── discord_embed_builder.py
│   ├── domain/
│   │   └── volume_profile.py
│   └── config/
│       └── app_config.py
├── dashboard/
│   └── pages/
│       └── 5_stock_analysis.py  # v9.0 심층 분석 페이지
└── README.md
```

---

## 📈 버전 히스토리

- **v9.0** (2026-02): 종목 심층 분석, 매물대 표시, 분석 대시보드
- **v8.0** (2026-02): 거래원 점수 편입, 스크리닝 안정화
- **v7.0** (2026-02): 키움 REST API 전환

