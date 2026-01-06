"""KIS API 클라이언트 통합 테스트 (Mock 사용)"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date

from src.adapters.kis_client import KISClient, get_kis_client
from src.domain.models import StockInfo, DailyPrice, CurrentPrice


class TestKISClientMock:
    """KIS 클라이언트 Mock 테스트"""
    
    @pytest.fixture
    def mock_client(self):
        """Mock된 KIS 클라이언트"""
        with patch.object(KISClient, '_get_token', return_value='mock_token'):
            client = KISClient()
            return client
    
    @patch('requests.get')
    def test_get_daily_prices_success(self, mock_get, mock_client):
        """일봉 데이터 조회 성공"""
        # Mock 응답 설정
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'rt_cd': '0',
            'output': [
                {
                    'stck_bsop_date': '20260106',
                    'stck_oprc': '70000',
                    'stck_hgpr': '72000',
                    'stck_lwpr': '69500',
                    'stck_clpr': '71500',
                    'acml_vol': '10000000',
                    'acml_tr_pbmn': '715000000000',
                },
                {
                    'stck_bsop_date': '20260105',
                    'stck_oprc': '69000',
                    'stck_hgpr': '70500',
                    'stck_lwpr': '68500',
                    'stck_clpr': '70000',
                    'acml_vol': '8000000',
                    'acml_tr_pbmn': '560000000000',
                },
            ],
        }
        mock_get.return_value = mock_response
        
        # 테스트
        prices = mock_client.get_daily_prices('005930', count=5)
        
        assert len(prices) == 2
        assert isinstance(prices[0], DailyPrice)
        # 오래된 순으로 정렬되어야 함
        assert prices[0].date < prices[1].date
    
    @patch('requests.get')
    def test_get_current_price_success(self, mock_get, mock_client):
        """현재가 조회 성공"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'rt_cd': '0',
            'output': {
                'stck_prpr': '71500',
                'prdy_vrss': '1500',
                'prdy_ctrt': '2.14',
                'acml_tr_pbmn': '850500000000',
                'acml_vol': '12000000',
            },
        }
        mock_get.return_value = mock_response
        
        # 테스트
        current = mock_client.get_current_price('005930')
        
        assert isinstance(current, CurrentPrice)
        assert current.price == 71500
        assert current.change == 1500
        assert current.change_rate == 2.14
    
    @patch('requests.get')
    def test_api_error_handling(self, mock_get, mock_client):
        """API 에러 처리"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'rt_cd': '1',  # 에러 코드
            'msg1': '잘못된 요청입니다',
        }
        mock_get.return_value = mock_response
        
        # 에러 발생 확인
        with pytest.raises(Exception):
            mock_client.get_daily_prices('INVALID')
    
    @patch('requests.get')
    def test_rate_limit_handling(self, mock_get, mock_client):
        """Rate Limit 처리"""
        # 첫 번째 호출: 429 (Rate Limit)
        mock_429 = Mock()
        mock_429.status_code = 429
        mock_429.headers = {'Retry-After': '1'}
        
        # 두 번째 호출: 성공
        mock_success = Mock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            'rt_cd': '0',
            'output': [],
        }
        
        mock_get.side_effect = [mock_429, mock_success]
        
        # 재시도 후 성공해야 함
        prices = mock_client.get_daily_prices('005930')
        assert prices is not None


class TestKISClientSingleton:
    """KIS 클라이언트 싱글톤 테스트"""
    
    def test_singleton_instance(self):
        """싱글톤 인스턴스 확인"""
        with patch.object(KISClient, '_get_token', return_value='mock'):
            client1 = get_kis_client()
            client2 = get_kis_client()
            
            assert client1 is client2
