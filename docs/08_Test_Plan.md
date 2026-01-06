# 8. 테스트 플랜 및 릴리즈 체크리스트 (Test Plan & Release Checklist)

**프로젝트명:** 종가매매 스크리너  
**버전:** 1.0  
**작성일:** 2025-01-06  

---

## 8.1 개요

### 8.1.1 결론
단위 테스트, 통합 테스트, E2E 테스트로 구성된 테스트 전략을 수립하고, Phase별 릴리즈 체크리스트를 정의한다.

### 8.1.2 근거
- 핵심 비즈니스 로직 검증 필수
- 외부 API 연동 안정성 확보
- 릴리즈 품질 보장

### 8.1.3 리스크/대안
| 리스크 | 대안 |
|--------|------|
| 외부 API Mock 부정확 | 실제 API 응답 캡처하여 fixture 생성 |
| 시간 의존 테스트 | freezegun으로 시간 고정 |

---

## 8.2 테스트 전략 개요

```
┌─────────────────────────────────────────────────────────────┐
│                    Test Pyramid                              │
└─────────────────────────────────────────────────────────────┘

                          ┌───────┐
                         /   E2E   \          ← 적음 (느림, 비용↑)
                        /   Tests   \
                       ┌─────────────┐
                      /  Integration  \       ← 중간
                     /     Tests       \
                    ┌───────────────────┐
                   /     Unit Tests      \    ← 많음 (빠름, 비용↓)
                  └───────────────────────┘
```

| 레벨 | 목적 | 비율 | 도구 |
|------|------|------|------|
| Unit | 개별 함수/클래스 검증 | 70% | pytest |
| Integration | 모듈 간 연동 검증 | 20% | pytest + mock |
| E2E | 전체 플로우 검증 | 10% | 수동 + 자동화 |

---

## 8.3 단위 테스트 (Unit Tests)

### 8.3.1 테스트 대상

| 모듈 | 테스트 파일 | 테스트 항목 |
|------|------------|------------|
| domain/indicators.py | test_indicators.py | CCI 계산, MA 계산, 기울기 |
| domain/score_calculator.py | test_score_calculator.py | 5가지 점수 산출, TOP 3 선정 |
| domain/weight_optimizer.py | test_weight_optimizer.py | 상관관계 분석, 가중치 조정 |
| domain/models.py | test_models.py | 데이터 클래스 검증 |

### 8.3.2 test_indicators.py 예시

```python
"""기술 지표 계산 단위 테스트"""
import pytest
from datetime import date
from src.domain.indicators import calculate_cci, calculate_ma, calculate_slope
from src.domain.models import DailyPrice


class TestCCI:
    """CCI 계산 테스트"""
    
    @pytest.fixture
    def sample_prices(self):
        """14일 이상의 샘플 데이터"""
        closes = [50000, 51000, 50500, 52000, 53000, 52500, 54000, 
                  55000, 54500, 56000, 57000, 56500, 58000, 59000, 60000]
        return [
            DailyPrice(date=date(2025, 1, i+1), open=c-500, high=c+500, 
                      low=c-1000, close=c, volume=1000000)
            for i, c in enumerate(closes)
        ]
    
    def test_cci_calculation_normal(self, sample_prices):
        """정상적인 CCI 계산"""
        cci_values = calculate_cci(sample_prices, period=14)
        assert len(cci_values) == len(sample_prices) - 13
        assert all(isinstance(v, float) for v in cci_values)
    
    def test_cci_insufficient_data(self):
        """데이터 부족 시 빈 리스트 반환"""
        prices = [DailyPrice(date=date(2025, 1, i+1), open=50000, high=51000,
                            low=49000, close=50000, volume=1000000)
                  for i in range(10)]
        cci_values = calculate_cci(prices, period=14)
        assert cci_values == []
    
    def test_cci_range(self, sample_prices):
        """CCI 값 범위 확인"""
        cci_values = calculate_cci(sample_prices, period=14)
        for cci in cci_values:
            assert -500 <= cci <= 500


class TestMA:
    """이동평균 계산 테스트"""
    
    def test_ma20_calculation(self):
        """MA20 계산"""
        prices = [
            DailyPrice(date=date(2025, 1, i+1), open=50000, high=51000,
                      low=49000, close=50000 + i*100, volume=1000000)
            for i in range(25)
        ]
        ma_values = calculate_ma(prices, period=20)
        assert len(ma_values) == len(prices) - 19


class TestSlope:
    """기울기 계산 테스트"""
    
    def test_positive_slope(self):
        """상승 기울기"""
        values = [100.0, 110.0, 120.0]
        slope = calculate_slope(values, period=3)
        assert slope > 0
    
    def test_negative_slope(self):
        """하락 기울기"""
        values = [120.0, 110.0, 100.0]
        slope = calculate_slope(values, period=3)
        assert slope < 0
```

### 8.3.3 test_score_calculator.py 예시

```python
"""점수 산출 단위 테스트"""
import pytest
from src.domain.score_calculator import (
    calculate_cci_value_score,
    calculate_candle_score,
    select_top_n
)
from src.domain.models import StockScore


class TestCCIValueScore:
    """CCI 값 점수 테스트"""
    
    @pytest.mark.parametrize("cci,expected_min,expected_max", [
        (180, 9.0, 10.0),   # 최적 구간
        (150, 7.0, 9.0),    # 근접 구간
        (250, 3.0, 5.0),    # 과열 구간
    ])
    def test_cci_value_score_ranges(self, cci, expected_min, expected_max):
        score = calculate_cci_value_score(cci)
        assert expected_min <= score <= expected_max


class TestCandleScore:
    """양봉 품질 점수 테스트"""
    
    def test_ideal_candle(self):
        """이상적인 양봉"""
        score = calculate_candle_score(
            open_price=100, close_price=110, 
            high_price=111, low_price=99, ma20=105
        )
        assert score >= 8.0
    
    def test_bearish_candle(self):
        """음봉은 낮은 점수"""
        score = calculate_candle_score(
            open_price=110, close_price=100,
            high_price=111, low_price=99, ma20=105
        )
        assert score <= 3.0


class TestTopNSelection:
    """TOP N 선정 테스트"""
    
    def test_select_top3(self):
        """상위 3개 선정"""
        scores = [
            StockScore(stock_code="A", score_total=9.0, trading_value=500),
            StockScore(stock_code="B", score_total=8.0, trading_value=400),
            StockScore(stock_code="C", score_total=7.0, trading_value=300),
            StockScore(stock_code="D", score_total=6.0, trading_value=200),
        ]
        top3 = select_top_n(scores, n=3)
        assert len(top3) == 3
        assert top3[0].stock_code == "A"
    
    def test_tiebreaker_by_trading_value(self):
        """동점 시 거래대금 높은 순"""
        scores = [
            StockScore(stock_code="A", score_total=8.0, trading_value=300),
            StockScore(stock_code="B", score_total=8.0, trading_value=500),
        ]
        top3 = select_top_n(scores, n=2)
        assert top3[0].stock_code == "B"
```

---

## 8.4 통합 테스트 (Integration Tests)

### 8.4.1 테스트 대상

| 모듈 | 테스트 파일 | 테스트 항목 |
|------|------------|------------|
| adapters/kis_client.py | test_kis_client.py | 토큰 발급, API 호출, 에러 핸들링 |
| services/screener_service.py | test_screener_service.py | 전체 스크리닝 플로우 |
| infrastructure/repository.py | test_repository.py | DB CRUD |

### 8.4.2 test_kis_client.py 예시

```python
"""한투 API 클라이언트 통합 테스트"""
import pytest
from unittest.mock import Mock, patch
from src.adapters.kis_client import KISClient


class TestKISClient:
    @pytest.fixture
    def client(self):
        return KISClient()
    
    @patch('requests.post')
    def test_get_token_success(self, mock_post, client):
        """토큰 발급 성공"""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {"access_token": "test_token", "expires_in": 86400}
        )
        client.refresh_token()
        assert client.token == "test_token"
    
    @patch('requests.get')
    def test_rate_limit_handling(self, mock_get, client):
        """Rate Limit 핸들링"""
        client.token = "test_token"
        mock_get.side_effect = [
            Mock(status_code=429, headers={"Retry-After": "1"}),
            Mock(status_code=200, json=lambda: {"rt_cd": "0", "output": []})
        ]
        prices = client.get_daily_prices("005930", count=1)
        assert mock_get.call_count == 2
```

### 8.4.3 test_repository.py 예시

```python
"""Repository 통합 테스트"""
import pytest
import sqlite3
from datetime import date
from src.infrastructure.repository import Repository
from src.infrastructure.database import init_database


class TestRepository:
    @pytest.fixture
    def db_connection(self, tmp_path):
        """임시 DB 생성"""
        db_path = tmp_path / "test.db"
        init_database(str(db_path))
        conn = sqlite3.connect(str(db_path))
        yield conn
        conn.close()
    
    @pytest.fixture
    def repository(self, db_connection):
        return Repository(db_connection)
    
    def test_save_and_get_screening(self, repository):
        """스크리닝 저장 및 조회"""
        from src.domain.models import ScreeningResult, StockScore
        
        result = ScreeningResult(
            screen_date=date(2025, 1, 6),
            screen_time="15:00",
            total_count=50,
            top3=[StockScore(stock_code="005930", stock_name="삼성전자",
                            score_total=8.5, trading_value=500)],
            status="SUCCESS"
        )
        screening_id = repository.save_screening(result)
        retrieved = repository.get_screening_by_date(date(2025, 1, 6))
        
        assert screening_id > 0
        assert retrieved.total_count == 50
```

---

## 8.5 E2E 테스트 (End-to-End Tests)

### 8.5.1 수동 테스트 시나리오

| ID | 시나리오 | 테스트 단계 | 예상 결과 |
|----|----------|------------|----------|
| E2E-01 | 전체 스크리닝 | 1. main.py 실행<br>2. 15:00 대기<br>3. 디스코드 확인 | TOP 3 알림 수신 |
| E2E-02 | 12:30 프리뷰 | 1. main.py 실행<br>2. 12:30 대기<br>3. 디스코드 확인 | [프리뷰] 알림 수신 |
| E2E-03 | 익일 결과 수집 | 1. 16:30 대기<br>2. DB 확인 | next_day_results 저장 |
| E2E-04 | 대시보드 조회 | 1. streamlit run<br>2. 각 페이지 확인 | 차트/테이블 정상 표시 |
| E2E-05 | 매매일지 입력 | 1. 매매일지 페이지<br>2. 폼 입력/저장 | DB에 저장 확인 |

---

## 8.6 테스트 커버리지 목표

| 모듈 | 목표 커버리지 | 우선순위 |
|------|--------------|----------|
| domain/indicators.py | 90% | 필수 |
| domain/score_calculator.py | 90% | 필수 |
| domain/weight_optimizer.py | 80% | 필수 |
| services/screener_service.py | 80% | 필수 |
| adapters/kis_client.py | 70% | 중요 |
| infrastructure/repository.py | 70% | 중요 |
| dashboard/* | 50% | 선택 |

---

## 8.7 릴리즈 체크리스트

### 8.7.1 Phase 1: 핵심 기능 (1주)

**개발 완료 조건:**
- [ ] 한투 API 연동 (토큰, 일봉, 현재가)
- [ ] 거래대금 300억 필터링
- [ ] 5가지 지표 점수 산출
- [ ] TOP 3 선정 로직
- [ ] 디스코드 알림 (15:00)
- [ ] DB 저장 (screenings, screening_items)

**테스트 완료 조건:**
- [ ] 단위 테스트 통과 (indicators, score_calculator)
- [ ] 통합 테스트 통과 (kis_client, screener_service)
- [ ] 수동 E2E 테스트 (E2E-01)

**배포 전 체크리스트:**
- [ ] .env 파일 설정 확인
- [ ] DB 초기화 스크립트 실행
- [ ] 로그 디렉토리 생성
- [ ] systemd 서비스 등록
- [ ] 테스트 알림 발송 확인

---

### 8.7.2 Phase 2: 12:30 알림 + 익일 추적 (3일)

**개발 완료 조건:**
- [ ] 12:30 프리뷰 알림 (저장 없음)
- [ ] 익일 결과 수집
- [ ] 가중치 최적화 로직
- [ ] 가중치 이력 저장

**테스트 완료 조건:**
- [ ] 단위 테스트 (weight_optimizer)
- [ ] 통합 테스트 (learner_service)
- [ ] 수동 E2E (E2E-02, E2E-03)

**배포 전 체크리스트:**
- [ ] 스케줄러에 12:30, 16:30 작업 추가
- [ ] 30일 데이터 수집 후 최적화 활성화

---

### 8.7.3 Phase 3: 매매일지 + 대시보드 (1주)

**개발 완료 조건:**
- [ ] Streamlit 대시보드 메인
- [ ] 스크리닝 결과 페이지
- [ ] 분석/통계 페이지
- [ ] 매매일지 입력/조회

**테스트 완료 조건:**
- [ ] 통합 테스트 (repository - journal)
- [ ] 수동 E2E (E2E-04, E2E-05)

**배포 전 체크리스트:**
- [ ] Streamlit 서비스 등록
- [ ] 포트 8501 방화벽 오픈 (필요 시)

---

### 8.7.4 Phase 4: 카카오톡 + 최적화 (3일)

**개발 완료 조건:**
- [ ] 카카오 알림톡 연동 (선택)
- [ ] 성능 최적화
- [ ] 에러 핸들링 강화

**테스트 완료 조건:**
- [ ] 전체 회귀 테스트
- [ ] 부하 테스트 (100종목 처리)

**배포 전 체크리스트:**
- [ ] 전체 문서 최종 검토
- [ ] 백업 스크립트 cron 등록
- [ ] 모니터링 알림 설정

---

## 8.8 테스트 실행 명령어

```bash
# 전체 테스트
pytest tests/ -v

# 단위 테스트만
pytest tests/unit/ -v

# 통합 테스트만
pytest tests/integration/ -v

# 커버리지 리포트
pytest tests/ --cov=src --cov-report=html

# 특정 테스트 파일
pytest tests/unit/test_indicators.py -v

# 마커 기반 실행
pytest -m "not e2e"  # E2E 제외
```

---

## 8.9 문서 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|------|------|----------|--------|
| 1.0 | 2025-01-06 | 초안 작성 | Architect AI |

---

**이전 문서:** [07_Risk_Analysis.md](./07_Risk_Analysis.md)  
**프로젝트 루트:** [../README.md](../README.md)
