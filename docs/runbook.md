**ClosingBell v9.0 Runbook (Preflight)**
1. 가상환경 활성화 (PowerShell)
```powershell
.\venv\Scripts\Activate.ps1
```
2. 스케줄러 중지 확인
3. DB 초기화 (파일 삭제)
```powershell
Remove-Item data\screener.db* -ErrorAction SilentlyContinue
```
4. DB 초기화 실행
```powershell
python main.py --init-db
```
5. 백필 20일 (TOP5 + 유목민)
```powershell
python main.py --backfill 20
```
6. 감시종목 AI 분석 (백필용 전체)
```powershell
python main.py --run-top5-ai-all
```
7. 기업정보 수집
```powershell
python main.py --run-company-info
```
8. 뉴스 수집
```powershell
python main.py --run-news
```
9. 유목민 AI 분석 (백필 포함 전체)
```powershell
python main.py --run-ai-analysis-all
```
10. 스케줄러 실행
```powershell
python main.py
```

**옵션: 운영 전 헬스체크**
```powershell
python main.py --healthcheck
```

**성공 로그 키워드 예시**
- DB 초기화: "DB 초기화 완료"
- 백필: "✅ 백필 완료!"
- TOP5 AI 전체 분석: "✅ TOP5 AI 전체 분석 완료!"
- 기업정보 수집: "✅ 기업정보 수집 완료!"
- 뉴스 수집: "✅ 뉴스 수집 완료!"
- 전체 AI 분석: "✅ 전체 AI 분석 완료!"
- 스케줄러: "스케줄러 모드 시작"

**실패 로그 키워드 예시**
- "❌"
- "실패"
- "오류"
- "에러"
