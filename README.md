# 🔔 ClosingBell v2

종가매매 종목 추천 시스템

## 기능
- 15:00 TV200 조건검색 → CCI/MA20 기반 TOP5 추천
- 디스코드 웹훅 알림
- Streamlit 대시보드 (closingbell.streamlit.app)
- 장 종료 후 자동 데이터 갱신 + Git push

## 설치

```bash
cd C:\Coding\ClosingBell
.\setup_venv.bat
copy .env.example .env
notepad .env
```

## 사용법

```bash
python main.py                  # 자동 스케줄러
python main.py --screen         # 즉시 스크리닝
python main.py --update         # 데이터 갱신
python main.py --backtest 30    # 백테스트
python main.py --dashboard      # 대시보드
```

## 점수 체계 (100점)

| 지표 | 배점 | 최적 | 근거 |
|------|------|------|------|
| CCI(14) | 30 | 160~180 | 9.5년 백테스트 50.4% 승률 |
| MA20 이격도 | 25 | 2~8% | 추세 위 적정 거리 |
| 등락률 | 20 | 2~8% | 스윗스팟 |
| CCI 기울기 | 15 | 3일↑ | 모멘텀 |
| MA20 기울기 | 10 | 3일↑ | 중기 추세 |
