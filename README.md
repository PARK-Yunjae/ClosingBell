# ClosingBell v5.1 - 종가매매 스크리너

종가에 매수하여 익일 시초가에 매도하는 전략을 위한 종목 선정 시스템입니다.

## 🎯 핵심 변경사항 (v5.1)

### 점수 체계 (100점 만점)
- **핵심 6개 지표**: 각 15점 (총 90점)
  - CCI (160~180 최적) - v5.1: 전 구간 만점
  - 등락률 (2~8% 최적)
  - 이격도 (2~8% 최적)
  - 연속양봉 (2~3일 최적) - v5.1: 5일+ 강한 감점
  - 거래량비율 (1.5~3.0배 최적)
  - 캔들품질 (양봉+짧은윗꼬리)

- **보너스 3개**: 총 10점
  - CCI 상승중 (+4점)
  - MA20 3일연속상승 (+3점)
  - 고가≠종가 (+3점)

### 등급별 매도전략
```
🏆 S등급 (85+): 시초 30% + 목표 +4% | 손절 -3%
🥇 A등급 (75-84): 시초 40% + 목표 +3% | 손절 -2.5%
🥈 B등급 (65-74): 시초 50% + 목표 +2.5% | 손절 -2%
🥉 C등급 (55-64): 시초 70% + 목표 +2% | 손절 -1.5%
⚠️ D등급 (<55): 시초 전량매도 | 손절 -1%
```

## 📂 프로젝트 구조

```
ClosingBell-v5.1/
├── main.py                    # 메인 실행 파일
├── requirements.txt           # 의존성
├── pyproject.toml            # 프로젝트 설정
├── run_screener.bat          # Windows 실행 스크립트
└── src/
    ├── adapters/             # 외부 연동
    │   ├── kis_client.py     # 한국투자증권 API
    │   └── discord_notifier.py
    ├── config/               # 설정
    │   ├── settings.py       # 환경변수 관리
    │   ├── constants.py      # 상수
    │   └── validator.py      # 설정 검증
    ├── domain/               # 도메인 로직
    │   ├── models.py         # 데이터 모델
    │   ├── indicators.py     # 기술 지표 계산
    │   └── score_calculator.py  # 점수 계산 (v5.1)
    ├── infrastructure/       # 인프라
    │   ├── database.py       # SQLite DB
    │   ├── repository.py     # 데이터 저장소
    │   ├── scheduler.py      # 스케줄러
    │   └── logging_config.py
    ├── services/             # 서비스
    │   └── screener_service.py  # 스크리닝 서비스
    └── utils/                # 유틸리티
        └── stock_filters.py  # 종목 필터
```

## 🚀 사용법

### 설치
```bash
pip install -r requirements.txt
```

### 환경변수 설정 (.env)
```
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=your_account_no
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 실행
```bash
# 스케줄러 모드 (12:30 프리뷰, 15:00 메인)
python main.py

# 즉시 실행
python main.py --run

# 테스트 (알림 없음)
python main.py --run-test

# 설정 검증
python main.py --validate
```

## 📊 Discord 알림 예시

```
🔔 종가매매 TOP5

#1 우리기술 (032820)
83.4점 🥇A
현재가: 4,125원 (+4.0%)
거래대금: 224억
━━━━━━━━━━
📊 핵심지표
CCI: 165 | 이격도: 5.2%
거래량: 1.8배 | 연속: 3일
━━━━━━━━━━
🎁 보너스: CCI↑ MA20↑ 캔들✓
📈 매도전략
시초가 40% / 목표 +3.0%
손절 -2.5%
```

## 🔧 v5.1 변경사항

1. **CCI 점수 개선**: 160~180 전체 구간 만점 (기존: 170 중심)
2. **연속양봉 감점 강화**: 5일+ 더 강한 감점
3. **Discord 핵심지표 표시**: CCI, 이격도, 거래량, 연속양봉 추가

## 📋 제거된 파일들 (레거시)

- `score_calculator_v5.py` → `score_calculator.py`로 통합
- `screener_service_v5.py` → `screener_service.py`로 통합
- `score_calculator.py` (v4) - 삭제
- `screener_service.py` (v4) - 삭제
- `learner_service.py` - 현재 미사용
- `backtest_service.py` - 별도 도구로 분리
- `weight_optimizer.py` - learner와 함께 제거
