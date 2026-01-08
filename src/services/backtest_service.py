"""
백테스팅 서비스

책임:
- 과거 데이터 기반 백테스트 실행
- ScoreCalculator 로직 재사용
- 다음날 수익률 계산
- 백테스트 결과 집계

데이터 구조:
- adjusted/*.csv: 날짜(인덱스), Open, High, Low, Close, Volume, Change, TradingValue, Marcap, Shares
- final_ranking_v6.csv: Date, Code, Name, Grade, Score, Details, TradingValue_Bn, CCI, Turnover, Gap_Profit, Max_Profit, End_Profit
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import pandas as pd

from src.domain.models import (
    DailyPrice,
    StockData,
    StockScore,
    Weights,
)
from src.domain.score_calculator import ScoreCalculator

logger = logging.getLogger(__name__)


# ============================================================
# 백테스트 결과 모델
# ============================================================

@dataclass
class BacktestTrade:
    """개별 거래 결과"""
    date: date                  # 스크리닝 날짜
    code: str
    name: str
    score: float                # 총점
    entry_price: int            # 진입가 (당일 종가)
    
    # 다음날 결과
    next_open: int = 0          # 다음날 시가
    next_high: int = 0          # 다음날 고가
    next_close: int = 0         # 다음날 종가
    
    @property
    def gap_return(self) -> float:
        """갭 수익률 (시초가 - 전일 종가) %"""
        if self.entry_price == 0:
            return 0.0
        return ((self.next_open - self.entry_price) / self.entry_price) * 100
    
    @property
    def max_return(self) -> float:
        """최대 수익률 (고가 - 전일 종가) %"""
        if self.entry_price == 0:
            return 0.0
        return ((self.next_high - self.entry_price) / self.entry_price) * 100
    
    @property
    def end_return(self) -> float:
        """종가 수익률 (종가 - 전일 종가) %"""
        if self.entry_price == 0:
            return 0.0
        return ((self.next_close - self.entry_price) / self.entry_price) * 100
    
    @property
    def is_gap_positive(self) -> bool:
        """갭 양수 여부"""
        return self.gap_return > 0


@dataclass
class BacktestSummary:
    """백테스트 요약"""
    start_date: date
    end_date: date
    total_trades: int
    
    # 수익률 통계
    avg_gap_return: float = 0.0
    avg_max_return: float = 0.0
    avg_end_return: float = 0.0
    
    # 승률
    gap_win_rate: float = 0.0   # 갭 양수 비율
    end_win_rate: float = 0.0   # 종가 양수 비율
    
    # 최고/최저
    best_trade: Optional[BacktestTrade] = None
    worst_trade: Optional[BacktestTrade] = None
    
    trades: List[BacktestTrade] = field(default_factory=list)


# ============================================================
# 백테스트 서비스
# ============================================================

class BacktestService:
    """백테스팅 서비스"""
    
    def __init__(
        self,
        data_dir: str = "data/adjusted",
        weights: Optional[Weights] = None,
    ):
        """
        Args:
            data_dir: 주가 데이터 디렉토리
            weights: 점수 가중치
        """
        self.data_dir = Path(data_dir)
        self.weights = weights or Weights()
        self.calculator = ScoreCalculator(self.weights)
        
        # 캐시: {종목코드: DataFrame}
        self._price_cache: Dict[str, pd.DataFrame] = {}
        
        # 종목명 매핑: {종목코드: 종목명}
        self._name_map: Dict[str, str] = {}
    
    def load_price_data(self, code: str) -> Optional[pd.DataFrame]:
        """주가 데이터 로드
        
        Args:
            code: 종목코드 (6자리)
            
        Returns:
            DataFrame 또는 None
        """
        if code in self._price_cache:
            return self._price_cache[code]
        
        file_path = self.data_dir / f"{code}.csv"
        if not file_path.exists():
            logger.warning(f"파일 없음: {file_path}")
            return None
        
        try:
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            self._price_cache[code] = df
            return df
        except Exception as e:
            logger.error(f"파일 로드 실패 {code}: {e}")
            return None
    
    def get_stock_data_at_date(
        self,
        code: str,
        target_date: date,
        lookback: int = 30,
    ) -> Optional[StockData]:
        """특정 날짜 기준 종목 데이터 생성
        
        Args:
            code: 종목코드
            target_date: 기준 날짜
            lookback: 과거 데이터 일수
            
        Returns:
            StockData 또는 None
        """
        df = self.load_price_data(code)
        if df is None or df.empty:
            return None
        
        # target_date까지의 데이터만 사용
        target_dt = pd.Timestamp(target_date)
        df_until = df[df.index <= target_dt]
        
        if len(df_until) < lookback:
            return None
        
        # 최근 lookback일 데이터
        df_recent = df_until.tail(lookback)
        
        daily_prices = []
        for idx, row in df_recent.iterrows():
            dp = DailyPrice(
                date=idx.date() if hasattr(idx, 'date') else idx,
                open=int(row['Open']),
                high=int(row['High']),
                low=int(row['Low']),
                close=int(row['Close']),
                volume=int(row['Volume']),
                trading_value=float(row.get('TradingValue', 0)),
            )
            daily_prices.append(dp)
        
        if not daily_prices:
            return None
        
        name = self._name_map.get(code, code)
        today_value = daily_prices[-1].trading_value / 1e8  # 원 -> 억원
        
        return StockData(
            code=code,
            name=name,
            daily_prices=daily_prices,
            current_price=daily_prices[-1].close,
            trading_value=today_value,
        )
    
    def get_next_day_prices(
        self,
        code: str,
        target_date: date,
    ) -> Optional[Tuple[int, int, int]]:
        """다음 거래일 가격 조회
        
        Args:
            code: 종목코드
            target_date: 기준 날짜
            
        Returns:
            (시가, 고가, 종가) 또는 None
        """
        df = self.load_price_data(code)
        if df is None or df.empty:
            return None
        
        target_dt = pd.Timestamp(target_date)
        df_after = df[df.index > target_dt]
        
        if df_after.empty:
            return None
        
        # 다음 거래일
        next_row = df_after.iloc[0]
        return (
            int(next_row['Open']),
            int(next_row['High']),
            int(next_row['Close']),
        )
    
    def run_single_day(
        self,
        target_date: date,
        stock_codes: List[str],
        top_n: int = 3,
    ) -> List[BacktestTrade]:
        """단일 날짜 백테스트
        
        Args:
            target_date: 스크리닝 날짜
            stock_codes: 대상 종목 코드 리스트
            top_n: TOP N 개수
            
        Returns:
            거래 결과 리스트
        """
        # 1. 각 종목 점수 계산
        scores: List[StockScore] = []
        for code in stock_codes:
            stock_data = self.get_stock_data_at_date(code, target_date)
            if stock_data is None:
                continue
            
            score = self.calculator.calculate_single_score(stock_data)
            if score:
                scores.append(score)
        
        # 2. TOP N 선정
        scores.sort(key=lambda x: (-x.score_total, -x.trading_value))
        top_stocks = scores[:top_n]
        
        # 3. 다음날 결과 조회
        trades = []
        for score in top_stocks:
            next_prices = self.get_next_day_prices(score.stock_code, target_date)
            if next_prices is None:
                continue
            
            trade = BacktestTrade(
                date=target_date,
                code=score.stock_code,
                name=score.stock_name,
                score=score.score_total,
                entry_price=score.current_price,
                next_open=next_prices[0],
                next_high=next_prices[1],
                next_close=next_prices[2],
            )
            trades.append(trade)
        
        return trades
    
    def run_backtest(
        self,
        start_date: date,
        end_date: date,
        stock_codes: Optional[List[str]] = None,
        top_n: int = 3,
    ) -> BacktestSummary:
        """기간 백테스트 실행
        
        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            stock_codes: 대상 종목 코드 (None이면 전체)
            top_n: 매일 선정할 TOP N 개수
            
        Returns:
            백테스트 요약
        """
        # 종목 코드 리스트 (파일 기준)
        if stock_codes is None:
            stock_codes = self._get_all_stock_codes()
        
        logger.info(f"백테스트 시작: {start_date} ~ {end_date}, {len(stock_codes)}개 종목")
        
        all_trades: List[BacktestTrade] = []
        current = start_date
        
        while current <= end_date:
            # 주말 건너뛰기
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue
            
            trades = self.run_single_day(current, stock_codes, top_n)
            all_trades.extend(trades)
            
            if trades:
                logger.debug(f"{current}: {len(trades)}개 거래")
            
            current += timedelta(days=1)
        
        # 요약 생성
        summary = self._create_summary(start_date, end_date, all_trades)
        return summary
    
    def run_from_ranking_file(
        self,
        ranking_file: str,
        top_n: int = 3,
    ) -> BacktestSummary:
        """기존 랭킹 파일 기반 백테스트
        
        final_ranking_v6.csv 형식:
        Date, Code, Name, Grade, Score, Details, TradingValue_Bn, CCI, Turnover, Gap_Profit, Max_Profit, End_Profit
        
        Args:
            ranking_file: 랭킹 파일 경로
            top_n: 날짜별 TOP N (이미 정렬된 데이터라면 그대로 사용)
            
        Returns:
            백테스트 요약
        """
        df = pd.read_csv(ranking_file, parse_dates=['Date'])
        
        # 종목명 매핑 업데이트
        for _, row in df.iterrows():
            code = str(row['Code']).zfill(6)
            self._name_map[code] = row['Name']
        
        all_trades: List[BacktestTrade] = []
        
        # 날짜별 그룹
        for date_val, group in df.groupby('Date'):
            target_date = date_val.date() if hasattr(date_val, 'date') else date_val
            
            # TOP N 선정 (Score 기준 상위)
            top_group = group.nlargest(top_n, 'Score')
            
            for _, row in top_group.iterrows():
                code = str(row['Code']).zfill(6)
                
                # 파일에 이미 수익률이 있으면 사용
                if 'Gap_Profit' in row and pd.notna(row['Gap_Profit']):
                    # 가상의 가격 계산 (비율 기준)
                    entry_price = 10000  # 기준가
                    gap_ret = row['Gap_Profit']
                    max_ret = row['Max_Profit']
                    end_ret = row['End_Profit']
                    
                    trade = BacktestTrade(
                        date=target_date,
                        code=code,
                        name=row['Name'],
                        score=row['Score'],
                        entry_price=entry_price,
                        next_open=int(entry_price * (1 + gap_ret / 100)),
                        next_high=int(entry_price * (1 + max_ret / 100)),
                        next_close=int(entry_price * (1 + end_ret / 100)),
                    )
                else:
                    # adjusted 파일에서 조회
                    next_prices = self.get_next_day_prices(code, target_date)
                    if next_prices is None:
                        continue
                    
                    # 당일 종가 조회
                    stock_data = self.get_stock_data_at_date(code, target_date, lookback=5)
                    if stock_data is None:
                        continue
                    
                    trade = BacktestTrade(
                        date=target_date,
                        code=code,
                        name=row['Name'],
                        score=row['Score'],
                        entry_price=stock_data.current_price,
                        next_open=next_prices[0],
                        next_high=next_prices[1],
                        next_close=next_prices[2],
                    )
                
                all_trades.append(trade)
        
        if not all_trades:
            return BacktestSummary(
                start_date=date.today(),
                end_date=date.today(),
                total_trades=0,
            )
        
        start_date = min(t.date for t in all_trades)
        end_date = max(t.date for t in all_trades)
        
        return self._create_summary(start_date, end_date, all_trades)
    
    def _get_all_stock_codes(self) -> List[str]:
        """전체 종목 코드 리스트"""
        codes = []
        if self.data_dir.exists():
            for f in self.data_dir.glob("*.csv"):
                code = f.stem
                if len(code) == 6 and code.isdigit():
                    codes.append(code)
        return codes
    
    def _create_summary(
        self,
        start_date: date,
        end_date: date,
        trades: List[BacktestTrade],
    ) -> BacktestSummary:
        """백테스트 요약 생성"""
        if not trades:
            return BacktestSummary(
                start_date=start_date,
                end_date=end_date,
                total_trades=0,
            )
        
        # 수익률 계산
        gap_returns = [t.gap_return for t in trades]
        max_returns = [t.max_return for t in trades]
        end_returns = [t.end_return for t in trades]
        
        avg_gap = sum(gap_returns) / len(gap_returns)
        avg_max = sum(max_returns) / len(max_returns)
        avg_end = sum(end_returns) / len(end_returns)
        
        # 승률
        gap_wins = sum(1 for r in gap_returns if r > 0)
        end_wins = sum(1 for r in end_returns if r > 0)
        
        gap_win_rate = (gap_wins / len(trades)) * 100
        end_win_rate = (end_wins / len(trades)) * 100
        
        # 최고/최저 거래
        best_trade = max(trades, key=lambda t: t.end_return)
        worst_trade = min(trades, key=lambda t: t.end_return)
        
        return BacktestSummary(
            start_date=start_date,
            end_date=end_date,
            total_trades=len(trades),
            avg_gap_return=avg_gap,
            avg_max_return=avg_max,
            avg_end_return=avg_end,
            gap_win_rate=gap_win_rate,
            end_win_rate=end_win_rate,
            best_trade=best_trade,
            worst_trade=worst_trade,
            trades=trades,
        )


def run_backtest(
    start_date: date,
    end_date: date,
    data_dir: str = "data/adjusted",
    top_n: int = 3,
) -> BacktestSummary:
    """백테스트 실행 유틸리티 함수"""
    service = BacktestService(data_dir=data_dir)
    return service.run_backtest(start_date, end_date, top_n=top_n)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    # 테스트 실행
    from datetime import date
    
    service = BacktestService(data_dir="project/data/adjusted")
    
    # 2024년 1월 백테스트
    result = service.run_backtest(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 31),
        top_n=3,
    )
    
    print(f"\n=== 백테스트 결과 ===")
    print(f"기간: {result.start_date} ~ {result.end_date}")
    print(f"총 거래: {result.total_trades}회")
    print(f"평균 갭 수익률: {result.avg_gap_return:.2f}%")
    print(f"평균 종가 수익률: {result.avg_end_return:.2f}%")
    print(f"갭 승률: {result.gap_win_rate:.1f}%")
    print(f"종가 승률: {result.end_win_rate:.1f}%")
