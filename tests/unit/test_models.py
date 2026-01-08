"""데이터 모델 테스트"""

import pytest
from datetime import date
from dataclasses import asdict

from src.domain.models import (
    DailyPrice,
    StockInfo,
    CurrentPrice,
    ScoreDetail,
    StockScore,
    ScreeningResult,
    ScreeningStatus,
    ScreenerError,
)


class TestDailyPrice:
    """일봉 데이터 모델 테스트"""
    
    def test_daily_price_creation(self):
        """DailyPrice 생성"""
        price = DailyPrice(
            date=date(2026, 1, 6),
            open=10000,
            high=10500,
            low=9800,
            close=10300,
            volume=1000000,
            trading_value=10300000000.0,
        )
        
        assert price.date == date(2026, 1, 6)
        assert price.open == 10000
        assert price.close == 10300
        assert price.high >= price.low
    
    def test_daily_price_as_dict(self):
        """DailyPrice를 dict로 변환"""
        price = DailyPrice(
            date=date(2026, 1, 6),
            open=10000, high=10500, low=9800, close=10300,
            volume=1000000, trading_value=10300000000.0,
        )
        
        d = asdict(price)
        assert 'date' in d
        assert 'close' in d
        assert d['volume'] == 1000000


class TestStockInfo:
    """종목 정보 모델 테스트"""
    
    def test_stock_info_creation(self):
        """StockInfo 생성"""
        stock = StockInfo(
            code="005930",
            name="삼성전자",
            market="KOSPI",
        )
        
        assert stock.code == "005930"
        assert stock.name == "삼성전자"
        assert stock.market == "KOSPI"
    
    def test_stock_info_equality(self):
        """StockInfo 동등성 비교"""
        stock1 = StockInfo(code="005930", name="삼성전자", market="KOSPI")
        stock2 = StockInfo(code="005930", name="삼성전자", market="KOSPI")
        
        assert stock1 == stock2


class TestScoreDetail:
    """점수 상세 모델 테스트"""
    
    def test_score_detail_creation(self):
        """ScoreDetail 생성"""
        detail = ScoreDetail(
            cci_value=8.0,
            cci_slope=7.5,
            ma20_slope=6.0,
            candle=9.0,
            change=7.0,
            raw_cci=175.5,
            raw_ma20=55000,
        )
        
        assert detail.cci_value == 8.0
        assert detail.raw_cci == 175.5
    
    def test_score_detail_score_range(self):
        """점수가 0~10 범위 내"""
        detail = ScoreDetail(
            cci_value=8.0,
            cci_slope=7.5,
            ma20_slope=6.0,
            candle=9.0,
            change=7.0,
            raw_cci=175.5,
            raw_ma20=55000,
        )
        
        scores = [
            detail.cci_value,
            detail.cci_slope,
            detail.ma20_slope,
            detail.candle,
            detail.change,
        ]
        
        for score in scores:
            assert 0 <= score <= 10


class TestStockScore:
    """종목 점수 모델 테스트"""
    
    def test_stock_score_creation(self):
        """StockScore 생성"""
        score_detail = ScoreDetail(
            cci_value=8.0, cci_slope=7.5, ma20_slope=6.0,
            candle=9.0, change=7.0,
            raw_cci=175.5, raw_ma20=55000,
        )
        
        stock_score = StockScore(
            stock_code="005930",
            stock_name="삼성전자",
            current_price=71500,
            change_rate=5.25,
            trading_value=850.5,
            score_detail=score_detail,
            score_total=37.5,
            rank=1,
        )
        
        assert stock_score.stock_code == "005930"
        assert stock_score.score_total == 37.5
        assert stock_score.rank == 1
    
    def test_stock_score_properties(self):
        """StockScore 프로퍼티 접근"""
        detail = ScoreDetail(
            cci_value=8.0, cci_slope=7.5, ma20_slope=6.0,
            candle=9.0, change=7.0,
            raw_cci=175.5, raw_ma20=55000,
        )
        
        score = StockScore(
            stock_code="005930",
            stock_name="삼성전자",
            current_price=71500,
            change_rate=5.25,
            trading_value=850.5,
            score_detail=detail,
            score_total=37.5,
            rank=1,
        )
        
        # 프로퍼티로 점수 접근
        assert score.score_cci_value == 8.0
        assert score.score_cci_slope == 7.5
        assert score.raw_cci == 175.5


class TestScreeningResult:
    """스크리닝 결과 모델 테스트"""
    
    def test_screening_result_success(self):
        """성공 결과 생성"""
        result = ScreeningResult(
            screen_date=date(2026, 1, 6),
            screen_time="15:00",
            total_count=50,
            top3=[],
            all_items=[],
            execution_time_sec=10.5,
            status=ScreeningStatus.SUCCESS,
        )
        
        assert result.status == ScreeningStatus.SUCCESS
        assert result.total_count == 50
    
    def test_screening_result_no_data(self):
        """데이터 없음 결과"""
        result = ScreeningResult(
            screen_date=date(2026, 1, 6),
            screen_time="15:00",
            total_count=0,
            top3=[],
            all_items=[],
            execution_time_sec=5.0,
            status=ScreeningStatus.SUCCESS,
        )
        
        assert result.status == ScreeningStatus.SUCCESS
        assert result.total_count == 0


class TestScreenerError:
    """에러 모델 테스트"""
    
    def test_screener_error_creation(self):
        """ScreenerError 생성"""
        error = ScreenerError(
            code="KIS_001",
            message="토큰 발급 실패",
            recoverable=True,
        )
        
        assert error.code == "KIS_001"
        assert "토큰" in error.message
        assert error.recoverable is True
    
    def test_screener_error_str(self):
        """에러 문자열 표현"""
        error = ScreenerError(
            code="SCREEN_002",
            message="API 호출 실패",
            recoverable=True,
        )
        
        error_str = str(error)
        assert "SCREEN_002" in error_str
        assert "API" in error_str
