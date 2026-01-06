# Cline 초기 프롬프트 - 종가매매 스크리너 프로젝트

아래 프롬프트를 Cline에 복사하여 사용하세요.

---

## 🚀 프로젝트 시작 프롬프트 (Phase 1)

```
나는 "종가매매 스크리너" 프로젝트를 시작하려고 해.
프로젝트 폴더의 docs/ 디렉토리에 8개의 설계 문서가 있어.

먼저 아래 문서들을 순서대로 읽어줘:
1. docs/01_PRD_v1.0.md - 프로젝트 목표와 범위
2. docs/02_User_Stories.md - 유저 스토리와 수용 기준
3. docs/06_Architecture.md - 아키텍처와 폴더 구조

문서를 읽은 후, Phase 1 작업을 시작하자:
- 한투 API 연동 (토큰 발급, 일봉 조회)
- 거래대금 300억 이상 종목 필터링
- 5가지 지표 점수 산출
- TOP 3 선정
- 디스코드 알림
- SQLite DB 저장

폴더 구조는 docs/06_Architecture.md의 6.3절을 따라줘.
먼저 프로젝트 구조를 생성하고, src/config/settings.py부터 시작하자.
```
---

## 📋 작업별 세부 프롬프트

### 1. 프로젝트 구조 생성
```
docs/06_Architecture.md의 6.3절 폴더 구조대로 프로젝트 스켈레톤을 생성해줘.
빈 __init__.py 파일들과 requirements.txt도 포함해서.
```

### 2. 설정 모듈 구현
```
src/config/settings.py와 constants.py를 구현해줘.
- .env 파일에서 환경 변수 로드
- 한투 API, 디스코드 웹훅 URL 설정
- Rate Limit 설정 (초당 4회, 0.25초 간격)
docs/06_Architecture.md의 6.6절 참고
```

### 3. 한투 API 클라이언트 구현
```
src/adapters/kis_client.py를 구현해줘.
docs/05_API_Spec.md의 5.2.1절 참고.
- OAuth 토큰 발급/갱신
- 일봉 데이터 조회
- 현재가 조회
- Rate Limit 핸들링 (0.25초 간격)
- 프로젝트 폴더 내 .env 파일에 키들이 있습니다.
```

### 4. 기술 지표 계산 구현
```
src/domain/indicators.py를 구현해줘.
- CCI(14일) 계산
- MA(20일) 계산  
- 기울기 계산 (CCI: 5일, MA20: 7일)
docs/02_User_Stories.md의 US-02, US-03, US-04 참고
```

### 5. 점수 계산 구현
```
src/domain/score_calculator.py를 구현해줘.
docs/02_User_Stories.md 참고:
- CCI 값 점수: 180 근접 시 최고점, 거리에 따라 감점
- CCI 기울기 점수: 5일 기준 상승세
- MA20 기울기 점수: 7일 기준 상승세
- 양봉 품질 점수: 윗꼬리 짧고 MA 위 안착
- 상승률 점수: 5~20% 최적, 벗어나면 감점
```

### 6. DB 구현
```
src/infrastructure/database.py와 repository.py를 구현해줘.
docs/04_Database_Design.md의 DDL을 사용해서.
- 테이블 생성 (init_database)
- CRUD 메서드
- WAL 모드 설정
```

### 7. 디스코드 알림 구현
```
src/adapters/discord_notifier.py를 구현해줘.
docs/05_API_Spec.md의 5.2.2절 참고.
- Embed 메시지 포맷
- 웹훅 발송
- Rate Limit 대응
```

### 8. 스크리너 서비스 통합
```
src/services/screener_service.py를 구현해줘.
docs/03_User_Flows.md의 Flow 1 참고.
전체 플로우를 오케스트레이션:
1. 거래대금 300억+ 종목 조회
2. 각 종목 일봉 데이터 수집
3. 기술 지표 계산
4. 점수 산출
5. TOP 3 선정
6. DB 저장
7. 디스코드 알림
```

### 9. 스케줄러 + 메인 실행
```
src/infrastructure/scheduler.py와 main.py를 구현해줘.
- APScheduler로 15:00, 12:30 스케줄 등록
- 장 운영일 체크 (휴장일 제외)
```

---

## ⚠️ 주의사항 (Cline에게 알려줄 것)

```
작업 시 아래 사항을 지켜줘:

1. Rate Limit: 한투 API 호출은 반드시 0.25초 간격 유지 (초당 4회 미만)
2. 가중치 범위: 0.5 ~ 5.0 (max 5.0)
3. 상승률 점수: 5~20% 사이가 최고점, 벗어나면 감점
4. CCI 점수: 180에 가까울수록 고득점, 멀어질수록 감점
5. 기울기 기간: CCI는 5일, MA20은 7일
6. 뉴스 연동 없음: 차트에 모든 정보가 반영된다는 철학

에러 처리:
- 한투 API 401 → 토큰 재발급 후 재시도
- 한투 API 429 → Retry-After 대기 후 재시도
- 디스코드 429 → 대기 후 재시도
```

---

## 🔍 문서 참조 가이드

| 작업 | 참조 문서 |
|------|----------|
| 전체 목표/범위 | 01_PRD_v1.0.md |
| 기능 상세 스펙 | 02_User_Stories.md |
| 플로우/시퀀스 | 03_User_Flows.md |
| DB 스키마/DDL | 04_Database_Design.md |
| API 명세 | 05_API_Spec.md |
| 폴더 구조/모듈 | 06_Architecture.md |
| 예상 문제/대응 | 07_Risk_Analysis.md |
| 테스트/릴리즈 | 08_Test_Plan.md |

---

## 💡 팁

1. **문서 먼저 읽게 하기**: 각 작업 전에 관련 문서 섹션을 먼저 읽게 하면 정확도가 높아짐
2. **작은 단위로 작업**: 한 번에 한 파일씩 구현하고 확인
3. **테스트 포함 요청**: "이 모듈의 단위 테스트도 같이 작성해줘"
4. **막히면 문서 참조**: "docs/05_API_Spec.md의 5.2.1절을 다시 읽고 수정해줘"
