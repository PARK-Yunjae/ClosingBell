**ClosingBell v9.0 정합성 체크리스트**
1. 버전 표시: APP_VERSION/APP_FULL_VERSION v9.0, 배너/로그 v9.0
2. CLI 명령어 동작 확인: `--validate`, `--init-db`, `--backfill`, `--run`, `--run-test`, `--run-ai-analysis`, `--run-top5-ai`, `--run-ai-analysis-all`, `--run-top5-ai-all`, `--run-company-info`, `--run-news`, `--run-all`, `--analyze`, `--healthcheck`, 스케줄러 `python main.py`
3. DB 스키마/초기화 루틴: `python main.py --init-db` 성공 로그, 주요 테이블/컬럼 생성 확인 (TOP5/유목민/뉴스/기업정보/AI)
4. 백필 → AI 분석 → 운영 시나리오: 백필 20일, 감시종목 AI 전체, 기업정보/뉴스, 유목민 AI 전체, 다음날 스케줄러
5. 코드 품질/실행 안정성: `python -m py_compile` 전 파일, import 순환, 예외 처리, 타임존/스케줄 시간, 데이터 경로(OHLCV/DB)

**실패 시 3줄 요약 템플릿**
1. 원인:
2. 영향:
3. 해결:
