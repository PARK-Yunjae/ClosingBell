"""
눌림목 스크리너 서비스 v1.0
==============================

15:02 실행 (TOP5 직후)
- 최근 5일 급등 종목 중 오늘 눌림목 발생 종목 탐지
- Discord 웹훅으로 알림

위치: src/services/dip_scanner.py

사용:
    # 스케줄러에서 자동 호출
    from src.services.dip_scanner import run_dip_scan
    run_dip_scan()
    
    # CLI 실행
    python -m src.services.dip_scanner
    python -m src.services.dip_scanner --no-discord
"""

import logging
import sqlite3
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

from src.config.settings import settings
from src.adapters.discord_notifier import get_discord_notifier

logger = logging.getLogger(__name__)


class DipScanner:
    """눌림목 스크리너
    
    백테스트 결과 기반 조건:
    - 급등: 거래량 전일대비 500%+ AND 거래량 1000만+
    - 눌림목A: 거래량 30% 이하 + 음봉 -3% 이하
    - 눌림목B: 거래량 20% 이하 + 가격방어 -2%~+1%
    """
    
    # ============================================================
    # 급등 조건 (감시 리스트 등록) - 거래량 기준
    # ============================================================
    MIN_VOLUME = 10_000_000      # 1000만주 (기본 유동성)
    VOL_SPIKE_RATIO = 5.0        # 전일 대비 500%+
    
    # ============================================================
    # 눌림목 조건
    # ============================================================
    DIP_MAX_CHANGE = -3.0        # 눌림목형: -3% 이하
    DIP_VOLUME_RATIO = 0.3       # 급등일 대비 30% 이하
    
    # 가격방어형
    DEFEND_MAX_CHANGE = 1.0      # +1% 이내
    DEFEND_MIN_CHANGE = -2.0     # -2% 이상
    DEFEND_VOLUME_RATIO = 0.2    # 급등일 대비 20% 이하
    
    # 추적 기간
    WATCH_DAYS = 5
    
    # ETF/스팩 제외 패턴
    EXCLUDE_PATTERNS = ['ETF', 'ETN', 'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG',
                        '스팩', 'SPAC', '리츠', '인버스', '레버리지', '2X', 'HANARO']
    
    def __init__(self):
        # 경로 설정
        self.ohlcv_dir = self._get_ohlcv_dir()
        self.stock_mapping_path = self._get_mapping_path()
        
        # DB 경로 (기존 screener.db와 같은 폴더)
        self.db_path = Path("data/dip_scanner.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 매핑
        self.name_map = {}
        self.sector_map = {}
        
        self._init_db()
        self._load_mappings()
        
        logger.info(f"DipScanner 초기화 - OHLCV: {self.ohlcv_dir}")
    
    def _get_ohlcv_dir(self) -> Path:
        """OHLCV 디렉토리 경로"""
        from src.config.app_config import OHLCV_FULL_DIR
        return OHLCV_FULL_DIR
    
    def _get_mapping_path(self) -> Path:
        """종목 매핑 파일 경로"""
        from src.config.app_config import MAPPING_FILE
        return MAPPING_FILE
    
    def _init_db(self):
        """DB 초기화"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 급등 종목 감시 테이블
        c.execute('''
            CREATE TABLE IF NOT EXISTS surge_watch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                sector TEXT,
                surge_date TEXT NOT NULL,
                close_price INTEGER,
                volume INTEGER,
                change_rate REAL,
                disparity REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(code, surge_date)
            )
        ''')
        
        # 눌림목 신호 기록
        c.execute('''
            CREATE TABLE IF NOT EXISTS dip_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                surge_date TEXT,
                dip_date TEXT NOT NULL,
                days_after INTEGER,
                surge_change REAL,
                surge_volume INTEGER,
                dip_change REAL,
                dip_volume INTEGER,
                volume_ratio REAL,
                disparity REAL,
                signal_strength INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 인덱스
        c.execute('CREATE INDEX IF NOT EXISTS idx_surge_date ON surge_watch(surge_date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_dip_date ON dip_signals(dip_date)')
        
        conn.commit()
        conn.close()
    
    def _load_mappings(self):
        """종목 매핑 로드"""
        if self.stock_mapping_path.exists():
            try:
                df = pd.read_csv(self.stock_mapping_path, encoding='utf-8-sig')
                df['code'] = df['code'].astype(str).str.zfill(6)
                self.name_map = dict(zip(df['code'], df['name']))
                if 'sector' in df.columns:
                    self.sector_map = dict(zip(df['code'], df['sector']))
                logger.info(f"종목 매핑 로드: {len(self.name_map)}개")
            except Exception as e:
                logger.warning(f"종목 매핑 로드 실패: {e}")
    
    def _is_excluded(self, name: str) -> bool:
        """제외 종목 체크"""
        return any(p in name for p in self.EXCLUDE_PATTERNS)
    
    def get_stock_data(self, code: str, days: int = 30) -> Optional[pd.DataFrame]:
        """종목 OHLCV 데이터 로드"""
        csv_path = self.ohlcv_dir / f"{code}.csv"
        if not csv_path.exists():
            return None
        
        try:
            df = pd.read_csv(csv_path)
            df.columns = df.columns.str.lower()
            
            # date 컬럼 찾기
            if 'date' not in df.columns:
                if 'unnamed: 0' in df.columns:
                    df = df.rename(columns={'unnamed: 0': 'date'})
                else:
                    return None
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').tail(days).reset_index(drop=True)
            
            # 기술지표 계산
            df['change_rate'] = df['close'].pct_change() * 100
            df['ma20'] = df['close'].rolling(20).mean()
            df['disparity'] = (df['close'] - df['ma20']) / df['ma20'] * 100
            
            return df
        except Exception as e:
            logger.debug(f"데이터 로드 실패 {code}: {e}")
            return None
    
    def scan_today_surges(self, today: str = None) -> List[Dict]:
        """오늘의 급등 종목 스캔 → 감시 리스트 추가"""
        if today is None:
            today = date.today().strftime('%Y-%m-%d')
        
        surges = []
        
        if not self.ohlcv_dir.exists():
            logger.warning(f"OHLCV 디렉토리 없음: {self.ohlcv_dir}")
            return surges
        
        csv_files = list(self.ohlcv_dir.glob("*.csv"))
        logger.info(f"급등 종목 스캔 중... ({len(csv_files)}개 파일)")
        
        for f in csv_files:
            code = f.stem
            name = self.name_map.get(code, code)
            
            if self._is_excluded(name):
                continue
            
            df = self.get_stock_data(code)
            if df is None or len(df) < 5:
                continue
            
            # 오늘 또는 가장 최근 데이터
            latest = df[df['date'].dt.strftime('%Y-%m-%d') == today]
            if latest.empty:
                latest = df.iloc[-1:]
            
            row = latest.iloc[0]
            
            # 급등 조건 체크 - 거래량 기준
            # 1) 기본 유동성: 1000만주+
            if row['volume'] < self.MIN_VOLUME:
                continue
            
            # 2) 전일 대비 거래량 폭발 (500%+)
            idx = df.index.get_loc(row.name)
            if idx < 1:
                continue
            
            prev_vol = df.iloc[idx-1]['volume']
            vol_spike = row['volume'] / prev_vol if prev_vol > 0 else 0
            
            if vol_spike < self.VOL_SPIKE_RATIO:
                continue
            
            surges.append({
                'code': code,
                'name': name,
                'sector': self.sector_map.get(code, 'Unknown'),
                'date': row['date'].strftime('%Y-%m-%d'),
                'close': int(row['close']),
                'volume': int(row['volume']),
                'change_rate': round(row['change_rate'], 2) if pd.notna(row['change_rate']) else 0,
                'disparity': round(row['disparity'], 2) if pd.notna(row['disparity']) else 0,
                'vol_spike': round(vol_spike, 1),
            })
        
        logger.info(f"급등 종목 발견: {len(surges)}개")
        return surges
    
    def add_to_watch(self, surges: List[Dict]):
        """감시 리스트에 추가"""
        if not surges:
            return
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        added = 0
        for s in surges:
            try:
                c.execute('''
                    INSERT OR REPLACE INTO surge_watch 
                    (code, name, sector, surge_date, close_price, volume, change_rate, disparity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (s['code'], s['name'], s['sector'], s['date'], 
                      s['close'], s['volume'], s['change_rate'], s['disparity']))
                added += 1
            except:
                pass
        
        conn.commit()
        conn.close()
        logger.info(f"감시 리스트 추가: {added}개")
    
    def get_watch_list(self) -> List[Dict]:
        """감시 리스트 조회 (최근 5일)"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        cutoff = (datetime.now() - timedelta(days=self.WATCH_DAYS)).strftime('%Y-%m-%d')
        
        c.execute('''
            SELECT code, name, sector, surge_date, close_price, volume, change_rate, disparity
            FROM surge_watch
            WHERE surge_date >= ?
            ORDER BY surge_date DESC
        ''', (cutoff,))
        
        rows = c.fetchall()
        conn.close()
        
        return [{
            'code': r[0],
            'name': r[1],
            'sector': r[2],
            'surge_date': r[3],
            'surge_close': r[4],
            'surge_volume': r[5],
            'surge_change': r[6],
            'surge_disparity': r[7],
        } for r in rows]
    
    def check_dip_signals(self, today: str = None) -> List[Dict]:
        """눌림목 신호 체크"""
        if today is None:
            today = date.today().strftime('%Y-%m-%d')
        
        today_dt = datetime.strptime(today, '%Y-%m-%d')
        watch_list = self.get_watch_list()
        
        logger.info(f"눌림목 체크 중... (감시: {len(watch_list)}개)")
        
        signals = []
        
        for watch in watch_list:
            code = watch['code']
            surge_date = watch['surge_date']
            surge_dt = datetime.strptime(surge_date, '%Y-%m-%d')
            
            # D+0은 제외 (급등 당일)
            if surge_date == today:
                continue
            
            # 며칠 후인지
            days_after = (today_dt - surge_dt).days
            if days_after > self.WATCH_DAYS or days_after < 1:
                continue
            
            # 오늘 데이터 확인
            df = self.get_stock_data(code)
            if df is None:
                continue
            
            today_data = df[df['date'].dt.strftime('%Y-%m-%d') == today]
            if today_data.empty:
                today_data = df.iloc[-1:]
            
            row = today_data.iloc[0]
            
            # ============================================================
            # 눌림목 조건 체크 (2가지 타입)
            # ============================================================
            
            vol_ratio = row['volume'] / watch['surge_volume'] if watch['surge_volume'] > 0 else 1
            change = row['change_rate'] if pd.notna(row['change_rate']) else 0
            is_bearish = row['close'] < row['open']
            
            # 타입A: 눌림목형 (음봉 + -3% 이하 + 거래량 30% 이하)
            is_dip = (is_bearish and 
                     change <= self.DIP_MAX_CHANGE and 
                     vol_ratio <= self.DIP_VOLUME_RATIO)
            
            # 타입B: 가격방어형 (변동 -2%~+1% + 거래량 20% 이하)
            is_defend = (self.DEFEND_MIN_CHANGE <= change <= self.DEFEND_MAX_CHANGE and
                        vol_ratio <= self.DEFEND_VOLUME_RATIO)
            
            if not is_dip and not is_defend:
                continue
            
            # 신호 타입
            signal_type = '눌림목' if is_dip else '가격방어'
            
            # ============================================================
            # 신호 강도 계산 (1~3)
            # ============================================================
            strength = 1
            if watch['surge_change'] >= 29:  # 상한가
                strength += 1
            if is_dip and change <= -5:  # 강한 눌림
                strength += 1
            if is_defend and vol_ratio <= 0.15:  # 극단적 거래량 급감
                strength += 1
            if watch['surge_disparity'] >= 30:  # 고이격
                strength += 1
            strength = min(strength, 3)
            
            signals.append({
                'code': code,
                'name': watch['name'],
                'sector': watch['sector'],
                'surge_date': surge_date,
                'dip_date': today,
                'days_after': days_after,
                'surge_change': watch['surge_change'],
                'surge_volume': watch['surge_volume'],
                'surge_disparity': watch['surge_disparity'],
                'dip_close': int(row['close']),
                'dip_change': round(row['change_rate'], 2),
                'dip_volume': int(row['volume']),
                'volume_ratio': round(vol_ratio * 100, 1),
                'current_disparity': round(row['disparity'], 2) if pd.notna(row['disparity']) else 0,
                'strength': strength,
                'signal_type': signal_type,
            })
        
        # 강도순 정렬
        signals.sort(key=lambda x: (-x['strength'], -x['surge_change']))
        
        logger.info(f"눌림목 신호 발견: {len(signals)}개")
        return signals
    
    def save_signals(self, signals: List[Dict]):
        """신호 저장"""
        if not signals:
            return
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        for s in signals:
            try:
                c.execute('''
                    INSERT INTO dip_signals 
                    (code, name, surge_date, dip_date, days_after, surge_change, surge_volume,
                     dip_change, dip_volume, volume_ratio, disparity, signal_strength)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (s['code'], s['name'], s['surge_date'], s['dip_date'], s['days_after'],
                      s['surge_change'], s['surge_volume'], s['dip_change'], s['dip_volume'],
                      s['volume_ratio'], s['current_disparity'], s['strength']))
            except:
                pass
        
        conn.commit()
        conn.close()
    
    def format_discord_message(self, signals: List[Dict], watch_status: List[Dict] = None) -> str:
        """Discord 메시지 포맷
        
        Args:
            signals: 눌림목 신호 리스트
            watch_status: 감시 리스트 현황 (전체)
        """
        today = date.today().strftime('%Y-%m-%d')
        lines = []
        
        # ============================================================
        # 1. 눌림목 신호
        # ============================================================
        if signals:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"📉 눌림목 신호 ({today}) - {len(signals)}개")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
            
            for i, s in enumerate(signals[:5], 1):  # 최대 5개
                stars = "⭐" * s['strength']
                limit_up = " 🔥상한가" if s['surge_change'] >= 29 else ""
                sig_type = "🛡️방어" if s.get('signal_type') == '가격방어' else "📉눌림"
                
                lines.append(f"{i}. {s['name']} ({s['code']}) {stars} {sig_type}")
                lines.append(f"   급등: {s['surge_date']} (D+{s['days_after']})")
                lines.append(f"   급등일: +{s['surge_change']:.1f}%{limit_up}, {s['surge_volume']//10000:,}만주")
                lines.append(f"   오늘: {s['dip_change']:.1f}%, {s['dip_volume']//10000:,}만주 ({s['volume_ratio']:.0f}%)")
                lines.append(f"   이격도: {s['current_disparity']:.1f}%")
                lines.append("")
            
            lines.append("💡 재료/뉴스 확인 후 진입 결정!")
            lines.append("⚠️ 손절 -3% 필수")
        else:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"📉 눌림목 신호 ({today}) - 0개")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        # ============================================================
        # 2. 감시 리스트 현황 (전체)
        # ============================================================
        if watch_status:
            # 신호 종목 코드 세트
            signal_codes = {s['code'] for s in signals} if signals else set()
            
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"📋 감시 리스트 현황 ({len(watch_status)}개)")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("")
            
            for w in watch_status:
                limit_up = "🔥" if w['surge_change'] >= 29 else "  "
                
                # 오늘 상태 표시
                today_change = w.get('today_change', 0)
                today_vol_ratio = w.get('today_vol_ratio', 0)
                days_after = w.get('days_after', 0)
                
                # 태그
                tags = []
                if w['code'] in signal_codes:
                    tags.append("📉눌림목")
                if today_vol_ratio > 0 and today_vol_ratio < 20:
                    if abs(today_change) < 2:
                        tags.append("🛡️가격방어")
                    else:
                        tags.append("📉거래량급감")
                if today_change > 3:
                    tags.append("🚀반등")
                
                tag_str = " ".join(tags) if tags else ""
                
                # 오늘 데이터 있으면 표시
                if w.get('has_today_data'):
                    lines.append(
                        f"{limit_up}{w['name'][:6]:<7s} "
                        f"+{w['surge_change']:>5.1f}% "
                        f"→ D+{days_after} "
                        f"오늘 {today_change:>+5.1f}% "
                        f"(거래량 {today_vol_ratio:>3.0f}%) "
                        f"{tag_str}"
                    )
                else:
                    lines.append(
                        f"{limit_up}{w['name'][:6]:<7s} "
                        f"+{w['surge_change']:>5.1f}% "
                        f"({w['surge_date']})"
                    )
            
            lines.append("")
            lines.append("🛡️=가격방어(변동<2%,거래량<20%)")
        
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        return "\n".join(lines)
    
    def get_watch_status(self, today: str = None) -> List[Dict]:
        """감시 리스트 전체 현황 (오늘 가격/거래량 포함)"""
        if today is None:
            today = date.today().strftime('%Y-%m-%d')
        
        today_dt = datetime.strptime(today, '%Y-%m-%d')
        watch_list = self.get_watch_list()
        
        status_list = []
        
        for watch in watch_list:
            code = watch['code']
            surge_date = watch['surge_date']
            surge_dt = datetime.strptime(surge_date, '%Y-%m-%d')
            days_after = (today_dt - surge_dt).days
            
            item = {
                'code': code,
                'name': watch['name'],
                'sector': watch['sector'],
                'surge_date': surge_date,
                'surge_change': watch['surge_change'],
                'surge_volume': watch['surge_volume'],
                'days_after': days_after,
                'has_today_data': False,
                'today_change': 0,
                'today_vol_ratio': 0,
            }
            
            # 오늘 데이터
            df = self.get_stock_data(code)
            if df is not None:
                today_data = df[df['date'].dt.strftime('%Y-%m-%d') == today]
                if today_data.empty:
                    today_data = df.iloc[-1:]
                
                row = today_data.iloc[0]
                
                if not pd.isna(row['change_rate']):
                    item['has_today_data'] = True
                    item['today_change'] = round(row['change_rate'], 2)
                    item['today_vol_ratio'] = round(
                        row['volume'] / watch['surge_volume'] * 100, 1
                    ) if watch['surge_volume'] > 0 else 0
            
            status_list.append(item)
        
        # 급등일 내림차순, 같은 날이면 등락률 내림차순
        status_list.sort(key=lambda x: (-x['days_after'], -x['surge_change']))
        
        return status_list
    
    def run(self, send_discord: bool = True) -> List[Dict]:
        """스캐너 실행
        
        Args:
            send_discord: Discord 전송 여부
            
        Returns:
            눌림목 신호 리스트
        """
        logger.info("=" * 50)
        logger.info("📉 눌림목 스크리너 시작")
        logger.info("=" * 50)
        
        # 0) 감시 리스트 비어있으면 자동 백필 (최초 실행 시)
        existing_watch = self.get_watch_list()
        if not existing_watch:
            logger.info("⚠️ 감시 리스트 비어있음 - 자동 백필 실행")
            self.backfill_surges(days=5)
        
        # 1) 오늘 급등 종목 → 감시 리스트 추가
        surges = self.scan_today_surges()
        if surges:
            self.add_to_watch(surges)
        
        # 2) 눌림목 신호 체크
        signals = self.check_dip_signals()
        
        # 3) 신호 저장
        if signals:
            self.save_signals(signals)
        
        # 4) 감시 리스트 현황 수집
        watch_status = self.get_watch_status()
        
        # 5) Discord 전송
        if send_discord:
            try:
                notifier = get_discord_notifier()
                message = self.format_discord_message(signals, watch_status)
                notifier.send_message(f"```\n{message}\n```")
                logger.info("📤 Discord 전송 완료")
            except Exception as e:
                logger.error(f"Discord 전송 실패: {e}")
        
        logger.info("=" * 50)
        logger.info(f"✅ 눌림목 스크리너 완료 (신호: {len(signals)}개)")
        logger.info("=" * 50)
        
        return signals
    
    def cleanup_old_data(self, days: int = 30):
        """오래된 데이터 정리"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        c.execute('DELETE FROM surge_watch WHERE surge_date < ?', (cutoff,))
        c.execute('DELETE FROM dip_signals WHERE dip_date < ?', (cutoff,))
        
        conn.commit()
        conn.close()
        logger.info(f"오래된 데이터 정리 완료 ({days}일 이전)")
    
    def scan_surges_for_date(self, target_date: str) -> List[Dict]:
        """특정 날짜의 급등 종목 스캔"""
        surges = []
        
        for f in self.ohlcv_dir.glob("*.csv"):
            code = f.stem
            name = self.name_map.get(code, code)
            
            if self._is_excluded(name):
                continue
            
            df = self.get_stock_data(code)
            if df is None or len(df) < 5:
                continue
            
            # 해당 날짜 데이터
            target_data = df[df['date'].dt.strftime('%Y-%m-%d') == target_date]
            if target_data.empty:
                continue
            
            row = target_data.iloc[0]
            
            # 급등 조건 체크 - 거래량 기준
            # 1) 기본 유동성: 1000만주+
            if row['volume'] < self.MIN_VOLUME:
                continue
            
            # 2) 전일 대비 거래량 폭발 (500%+)
            idx = df.index.get_loc(row.name)
            if idx < 1:
                continue
            
            prev_vol = df.iloc[idx-1]['volume']
            vol_spike = row['volume'] / prev_vol if prev_vol > 0 else 0
            
            if vol_spike < self.VOL_SPIKE_RATIO:
                continue
            
            surges.append({
                'code': code,
                'name': name,
                'sector': self.sector_map.get(code, 'Unknown'),
                'date': target_date,
                'close': int(row['close']),
                'volume': int(row['volume']),
                'change_rate': round(row['change_rate'], 2) if pd.notna(row['change_rate']) else 0,
                'disparity': round(row['disparity'], 2) if pd.notna(row['disparity']) else 0,
                'vol_spike': round(vol_spike, 1),
            })
        
        return surges
    
    def backfill_surges(self, days: int = 5):
        """과거 급등 종목 백필
        
        최초 실행 시 과거 5일치 급등 종목을 감시 리스트에 추가
        
        Args:
            days: 백필할 일수 (기본 5일)
        """
        logger.info(f"📥 과거 {days}일 급등 종목 백필 시작...")
        
        total_added = 0
        today = date.today()
        
        for i in range(1, days + 1):
            target_date = today - timedelta(days=i)
            target_str = target_date.strftime('%Y-%m-%d')
            
            # 주말 스킵
            if target_date.weekday() >= 5:
                logger.info(f"  {target_str} 스킵 (주말)")
                continue
            
            logger.info(f"  {target_str} 스캔 중...")
            surges = self.scan_surges_for_date(target_str)
            
            if surges:
                self.add_to_watch(surges)
                total_added += len(surges)
                logger.info(f"    → {len(surges)}개 추가")
            else:
                logger.info(f"    → 급등 종목 없음")
        
        logger.info(f"✅ 백필 완료: 총 {total_added}개")
        return total_added


# ============================================================
# 스케줄러용 함수
# ============================================================

def run_dip_scan():
    """스케줄러용 눌림목 스캔 (15:02 실행)"""
    logger.info("=" * 40)
    logger.info("📉 눌림목 스캔 시작")
    logger.info("=" * 40)
    
    try:
        scanner = DipScanner()
        signals = scanner.run(send_discord=True)
        
        logger.info(f"✅ 눌림목 스캔 완료: {len(signals)}개 신호")
        return {'status': 'success', 'signals': len(signals)}
        
    except Exception as e:
        logger.error(f"❌ 눌림목 스캔 실패: {e}")
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'error': str(e)}


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    scanner = DipScanner()
    
    # --backfill 옵션: 과거 데이터 백필
    if '--backfill' in sys.argv:
        # --backfill 7 처럼 일수 지정 가능
        days = 5
        try:
            idx = sys.argv.index('--backfill')
            if idx + 1 < len(sys.argv):
                days = int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            pass
        
        scanner.backfill_surges(days=days)
        print(f"\n감시 리스트 확인:")
        watch_list = scanner.get_watch_list()
        for w in watch_list[:10]:
            print(f"  {w['surge_date']} | {w['name']} | +{w['surge_change']:.1f}%")
        if len(watch_list) > 10:
            print(f"  ... 외 {len(watch_list) - 10}개")
        sys.exit(0)
    
    # --no-discord 옵션
    send_discord = '--no-discord' not in sys.argv
    
    signals = scanner.run(send_discord=send_discord)
    
    if not send_discord:
        watch_status = scanner.get_watch_status()
        print("\n" + scanner.format_discord_message(signals, watch_status))