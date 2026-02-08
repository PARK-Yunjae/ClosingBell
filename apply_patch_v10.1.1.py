#!/usr/bin/env python3
"""
ClosingBell v10.1.1 패치 적용 스크립트
=====================================
5개 파일, 6개 수정사항

사용법:
    cd C:\\Coding\\ClosingBell
    python apply_patch_v10.1.1.py           # 실제 적용
    python apply_patch_v10.1.1.py --dry-run  # 미리보기만
    python apply_patch_v10.1.1.py --revert   # 백업에서 복원

수정 목록:
    1. enrichment_service.py   - 공매도/SR 로깅 debug→info, 에러 타입 추가
    2. top5_pipeline.py        - 공매도/SR DB 저장 로깅 + sqlite3.Row .get() 수정 + AI 캐시 로그
    3. pullback_tracker.py     - OHLCV CSV 없을 때 키움 API 폴백 추가
    4. screener_service.py     - VP 매물대 None 방어 + 로그 스팸 제거 (76건→1줄 요약)
    5. 1_top5_tracker.py       - CSS hex color #888 → #888888 (alpha 호환)
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

# ============================================================
# 설정
# ============================================================
PROJECT_ROOT = Path(__file__).parent
BACKUP_DIR = PROJECT_ROOT / "_backup_v10.1.0"

PATCHES = []

# ============================================================
# Patch 1: enrichment_service.py - 공매도/SR 로깅 강화
# ============================================================
PATCHES.append({
    "file": "src/services/enrichment_service.py",
    "desc": "공매도/SR 로깅 debug→info + 에러 타입 추가",
    "old": '''        # 3. v10.0: 공매도/대차거래 분석
        try:
            from src.services.short_selling_service import fetch_and_analyze
            from src.adapters.kiwoom_rest_client import get_kiwoom_client
            broker = get_kiwoom_client()
            stock.short_selling_score = fetch_and_analyze(stock.stock_code, broker)
            logger.debug(f"공매도 분석: {stock.stock_code} → {stock.short_selling_score.summary}")
        except Exception as e:
            logger.warning(f"공매도 분석 실패 ({stock.stock_code}): {e}")
            stock.enrich_errors.append(f"Short: {str(e)[:50]}")
        
        # 4. v10.0: 지지/저항선 분석
        try:
            from src.services.sr_calculator import calculate_support_resistance
            from src.adapters.kiwoom_rest_client import get_kiwoom_client
            broker = get_kiwoom_client()
            prices = broker.get_daily_prices(stock.stock_code, count=120)
            if prices:
                current = stock.screen_price or (prices[-1].close if prices else 0)
                stock.sr_analysis = calculate_support_resistance(
                    stock.stock_code, prices, current_price=current
                )
                logger.debug(f"지지/저항: {stock.stock_code} → {stock.sr_analysis.summary}")
        except Exception as e:
            logger.warning(f"지지/저항 분석 실패 ({stock.stock_code}): {e}")
            stock.enrich_errors.append(f"SR: {str(e)[:50]}")''',
    "new": '''        # 3. v10.0: 공매도/대차거래 분석
        try:
            from src.services.short_selling_service import fetch_and_analyze
            from src.adapters.kiwoom_rest_client import get_kiwoom_client
            broker = get_kiwoom_client()
            stock.short_selling_score = fetch_and_analyze(stock.stock_code, broker)
            logger.info(f"📉 공매도 분석: {stock.stock_code} → score={stock.short_selling_score.score}, ratio={stock.short_selling_score.latest_short_ratio}%, {stock.short_selling_score.summary}")
        except Exception as e:
            logger.warning(f"⚠️ 공매도 분석 실패 ({stock.stock_code}): {type(e).__name__}: {e}")
            stock.enrich_errors.append(f"Short: {str(e)[:50]}")
        
        # 4. v10.0: 지지/저항선 분석
        try:
            from src.services.sr_calculator import calculate_support_resistance
            from src.adapters.kiwoom_rest_client import get_kiwoom_client
            broker = get_kiwoom_client()
            prices = broker.get_daily_prices(stock.stock_code, count=120)
            if prices:
                current = stock.screen_price or (prices[-1].close if prices else 0)
                stock.sr_analysis = calculate_support_resistance(
                    stock.stock_code, prices, current_price=current
                )
                logger.info(f"📊 지지/저항: {stock.stock_code} → score={stock.sr_analysis.score}, S={stock.sr_analysis.nearest_support}, R={stock.sr_analysis.nearest_resistance}")
            else:
                logger.warning(f"⚠️ 지지/저항: {stock.stock_code} → 가격 데이터 없음 (prices=None)")
        except Exception as e:
            logger.warning(f"⚠️ 지지/저항 분석 실패 ({stock.stock_code}): {type(e).__name__}: {e}")
            stock.enrich_errors.append(f"SR: {str(e)[:50]}")'''
})

# ============================================================
# Patch 2a: top5_pipeline.py - 공매도/SR DB 저장 로깅 강화
# ============================================================
PATCHES.append({
    "file": "src/services/top5_pipeline.py",
    "desc": "공매도/SR DB 저장 로깅 강화",
    "old": '''            # v10.0: 공매도/지지저항 필드 저장
            if enriched_stocks:
                ss_count = 0
                missing_data_count = 0
                for stock in enriched_stocks:
                    code = getattr(stock, 'stock_code', '')
                    ss = getattr(stock, 'short_selling_score', None)
                    sr = getattr(stock, 'sr_analysis', None)
                    
                    if ss or sr:
                        try:
                            repo.update_short_sr_fields(
                                screen_date=screen_date.isoformat(),
                                stock_code=code,
                                short_ratio=getattr(ss, 'latest_short_ratio', 0) if ss else 0,
                                short_score=getattr(ss, 'score', 0) if ss else 0,
                                short_tags=' '.join(getattr(ss, 'tags', [])) if ss else '',
                                sr_score=getattr(sr, 'score', 0) if sr else 0,
                                sr_nearest_support=getattr(sr, 'nearest_support', 0) if sr else 0,
                                sr_nearest_resistance=getattr(sr, 'nearest_resistance', 0) if sr else 0,
                                sr_tags=' '.join(getattr(sr, 'tags', [])) if sr else '',
                            )
                            ss_count += 1
                        except Exception as e:
                            logger.debug(f"공매도/SR 저장 실패 ({code}): {e}")
                    else:
                        missing_data_count += 1''',
    "new": '''            # v10.0: 공매도/지지저항 필드 저장
            if enriched_stocks:
                ss_count = 0
                missing_data_count = 0
                for stock in enriched_stocks:
                    code = getattr(stock, 'stock_code', '')
                    ss = getattr(stock, 'short_selling_score', None)
                    sr = getattr(stock, 'sr_analysis', None)
                    
                    logger.info(f"  공매도/SR 체크: {code} → ss={'있음' if ss else 'None'}, sr={'있음' if sr else 'None'}")
                    
                    if ss or sr:
                        try:
                            repo.update_short_sr_fields(
                                screen_date=screen_date.isoformat(),
                                stock_code=code,
                                short_ratio=getattr(ss, 'latest_short_ratio', 0) if ss else 0,
                                short_score=getattr(ss, 'score', 0) if ss else 0,
                                short_tags=' '.join(getattr(ss, 'tags', [])) if ss else '',
                                sr_score=getattr(sr, 'score', 0) if sr else 0,
                                sr_nearest_support=getattr(sr, 'nearest_support', 0) if sr else 0,
                                sr_nearest_resistance=getattr(sr, 'nearest_resistance', 0) if sr else 0,
                                sr_tags=' '.join(getattr(sr, 'tags', [])) if sr else '',
                            )
                            ss_count += 1
                            logger.debug(f"  ✅ 공매도/SR 저장: {code}")
                        except Exception as e:
                            logger.warning(f"  ❌ 공매도/SR 저장 실패 ({code}): {e}")
                    else:
                        missing_data_count += 1'''
})

# ============================================================
# Patch 2b: top5_pipeline.py - sqlite3.Row .get() 수정
# ============================================================
PATCHES.append({
    "file": "src/services/top5_pipeline.py",
    "desc": "sqlite3.Row .get() → dict() 변환 수정",
    "old": '''                            if existing:
                                already_analyzed[stock_code] = {
                                    'recommendation': existing.get('ai_recommendation', '관망'),
                                    'risk_level': existing.get('ai_risk_level', '보통'),
                                    'summary': existing.get('ai_summary', ''),
                                    'investment_point': '',
                                    'risk_factor': '',
                                }''',
    "new": '''                            if existing:
                                existing = dict(existing)
                                already_analyzed[stock_code] = {
                                    'recommendation': existing.get('ai_recommendation', '관망'),
                                    'risk_level': existing.get('ai_risk_level', '보통'),
                                    'summary': existing.get('ai_summary', ''),
                                    'investment_point': '',
                                    'risk_factor': '',
                                }'''
})

# ============================================================
# Patch 2c: top5_pipeline.py - AI 캐시 로그 레벨 상향
# ============================================================
PATCHES.append({
    "file": "src/services/top5_pipeline.py",
    "desc": "AI 캐시 체크 실패 로그 debug→info",
    "old": '''                except Exception as e:
                    logger.debug(f"AI 캐시 체크 실패 (전체 분석 진행): {e}")
                    stocks_to_analyze = enriched_stocks if enriched_stocks else scores[:self.top_n_count]''',
    "new": '''                except Exception as e:
                    logger.info(f"AI 캐시 체크 실패 (전체 분석 진행): {type(e).__name__}: {e}")
                    stocks_to_analyze = enriched_stocks if enriched_stocks else scores[:self.top_n_count]'''
})

# ============================================================
# Patch 3: pullback_tracker.py - API 폴백 추가
# ============================================================
PATCHES.append({
    "file": "src/services/pullback_tracker.py",
    "desc": "눌림목 추적: OHLCV CSV 없을 때 키움 API 폴백",
    "old": '''    # OHLCV 데이터 경로
    ohlcv_dir = DATA_DIR / "ohlcv_kiwoom"
    
    for sig in signals:
        signal_id = sig["id"]
        stock_code = sig["stock_code"]
        signal_date = sig["signal_date"]
        signal_close = sig["close_price"]
        
        if not signal_close or signal_close <= 0:
            continue
        
        # 이미 추적 완료된 일수 확인
        existing = db.fetch_all(
            "SELECT days_after FROM pullback_daily_prices "
            "WHERE pullback_signal_id = ? ORDER BY days_after",
            (signal_id,),
        )
        existing_days = {r["days_after"] for r in existing}
        
        # D+tracking_days까지 완료되면 스킵
        if len(existing_days) >= tracking_days:
            continue
        
        # OHLCV 파일에서 가격 로드
        csv_path = ohlcv_dir / f"{stock_code}.csv"
        if not csv_path.exists():
            continue
        
        try:
            df = pd.read_csv(csv_path)
            df.columns = df.columns.str.lower()
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # signal_date 이후의 거래일 데이터
            signal_dt = pd.to_datetime(signal_date)
            future = df[df['date'] > signal_dt].head(tracking_days)
            
            if future.empty:
                continue
            
            signals_tracked += 1
            
            for day_n, (_, row) in enumerate(future.iterrows(), 1):
                if day_n in existing_days:
                    continue
                
                trade_date = row['date'].strftime('%Y-%m-%d')
                
                # 수익률 계산
                open_price = row.get('open', 0)
                close_price = row.get('close', 0)
                high_price = row.get('high', 0)
                low_price = row.get('low', 0)
                volume = int(row.get('volume', 0))
                
                gap_rate = (open_price / signal_close - 1) * 100 if day_n == 1 else 0
                return_from_signal = (close_price / signal_close - 1) * 100
                high_return = (high_price / signal_close - 1) * 100
                low_return = (low_price / signal_close - 1) * 100
                
                db.execute(
                    """INSERT OR IGNORE INTO pullback_daily_prices 
                    (pullback_signal_id, stock_code, trade_date, days_after,
                     open_price, high_price, low_price, close_price, volume,
                     gap_rate, return_from_signal, high_return, low_return)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (signal_id, stock_code, trade_date, day_n,
                     open_price, high_price, low_price, close_price, volume,
                     gap_rate, return_from_signal, high_return, low_return),
                )
                prices_updated += 1
                
        except Exception as e:
            logger.warning(f"[pullback_tracker] {stock_code} 처리 실패: {e}")
            continue''',
    "new": '''    # OHLCV 데이터 경로
    ohlcv_dir = DATA_DIR / "ohlcv_kiwoom"
    
    # API 폴백용 클라이언트 (lazy init)
    _api_client = None
    
    def _get_api_client():
        nonlocal _api_client
        if _api_client is None:
            try:
                from src.adapters.kiwoom_rest_client import get_kiwoom_client
                _api_client = get_kiwoom_client()
            except Exception as e:
                logger.warning(f"[pullback_tracker] API 클라이언트 초기화 실패: {e}")
        return _api_client
    
    def _load_ohlcv_df(stock_code: str) -> Optional[pd.DataFrame]:
        """OHLCV CSV 로드, 없으면 API 폴백"""
        csv_path = ohlcv_dir / f"{stock_code}.csv"
        
        # 1순위: CSV 파일
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                df.columns = df.columns.str.lower()
                df['date'] = pd.to_datetime(df['date'])
                return df.sort_values('date')
            except Exception as e:
                logger.debug(f"[pullback_tracker] CSV 로드 실패 ({stock_code}): {e}")
        
        # 2순위: 키움 API
        client = _get_api_client()
        if client:
            try:
                prices = client.get_daily_prices(stock_code, count=30)
                if prices:
                    rows = []
                    for p in prices:
                        rows.append({
                            'date': pd.to_datetime(getattr(p, 'date', None) or getattr(p, 'trade_date', None)),
                            'open': getattr(p, 'open', 0) or getattr(p, 'open_price', 0),
                            'high': getattr(p, 'high', 0) or getattr(p, 'high_price', 0),
                            'low': getattr(p, 'low', 0) or getattr(p, 'low_price', 0),
                            'close': getattr(p, 'close', 0) or getattr(p, 'close_price', 0),
                            'volume': getattr(p, 'volume', 0),
                        })
                    df = pd.DataFrame(rows)
                    df = df.dropna(subset=['date'])
                    if not df.empty:
                        logger.info(f"[pullback_tracker] API 폴백: {stock_code} → {len(df)}일")
                        return df.sort_values('date')
            except Exception as e:
                logger.debug(f"[pullback_tracker] API 조회 실패 ({stock_code}): {e}")
        
        logger.debug(f"[pullback_tracker] OHLCV 없음: {stock_code}")
        return None
    
    for sig in signals:
        signal_id = sig["id"]
        stock_code = sig["stock_code"]
        signal_date = sig["signal_date"]
        signal_close = sig["close_price"]
        
        if not signal_close or signal_close <= 0:
            continue
        
        # 이미 추적 완료된 일수 확인
        existing = db.fetch_all(
            "SELECT days_after FROM pullback_daily_prices "
            "WHERE pullback_signal_id = ? ORDER BY days_after",
            (signal_id,),
        )
        existing_days = {r["days_after"] for r in existing}
        
        # D+tracking_days까지 완료되면 스킵
        if len(existing_days) >= tracking_days:
            continue
        
        # OHLCV 데이터 로드 (CSV → API 폴백)
        df = _load_ohlcv_df(stock_code)
        if df is None:
            continue
        
        try:
            # signal_date 이후의 거래일 데이터
            signal_dt = pd.to_datetime(signal_date)
            future = df[df['date'] > signal_dt].head(tracking_days)
            
            if future.empty:
                continue
            
            signals_tracked += 1
            
            for day_n, (_, row) in enumerate(future.iterrows(), 1):
                if day_n in existing_days:
                    continue
                
                trade_date = row['date'].strftime('%Y-%m-%d')
                
                # 수익률 계산
                open_price = row.get('open', 0)
                close_price = row.get('close', 0)
                high_price = row.get('high', 0)
                low_price = row.get('low', 0)
                volume = int(row.get('volume', 0))
                
                gap_rate = (open_price / signal_close - 1) * 100 if day_n == 1 else 0
                return_from_signal = (close_price / signal_close - 1) * 100
                high_return = (high_price / signal_close - 1) * 100
                low_return = (low_price / signal_close - 1) * 100
                
                db.execute(
                    """INSERT OR IGNORE INTO pullback_daily_prices 
                    (pullback_signal_id, stock_code, trade_date, days_after,
                     open_price, high_price, low_price, close_price, volume,
                     gap_rate, return_from_signal, high_return, low_return)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (signal_id, stock_code, trade_date, day_n,
                     open_price, high_price, low_price, close_price, volume,
                     gap_rate, return_from_signal, high_return, low_return),
                )
                prices_updated += 1
                
        except Exception as e:
            logger.warning(f"[pullback_tracker] {stock_code} 처리 실패: {e}")
            continue'''
})

# ============================================================
# Patch 4: screener_service.py - VP 매물대 오류 방어 + 로그 정리
# ============================================================
PATCHES.append({
    "file": "src/services/screener_service.py",
    "desc": "VP 매물대: None 방어 + 로그 스팸 76건→1줄 요약",
    "old": """            vp_data_cache = None
            for score in scores_filtered:
                code = score.stock_code
                price = score.current_price
                try:
                    vp_result = None
                    vp_meta = ""
                    
                    # 키움 API
                    if use_kiwoom and kiwoom_client and kiwoom_available:
                        try:
                            if vp_data_cache is None:
                                data = kiwoom_client.get_volume_profile(
                                    stock_code=code,
                                    cycle_tp=str(vp_cfg.cycle),
                                    prpscnt=str(vp_cfg.bands),
                                    cur_prc_entry=str(vp_cfg.cur_entry),
                                    trde_qty_tp=str(vp_cfg.trde_qty_tp),
                                    tr_id=str(vp_cfg.api_id),
                                )
                                if isinstance(data, dict) and not any(
                                    isinstance(v, list) and v for v in data.values()
                                ):
                                    kiwoom_available = False
                                    data = {}
                                vp_data_cache = data
                            else:
                                data = vp_data_cache
                            
                            vp_result = calc_volume_profile_from_kiwoom(
                                data=data, current_price=price,
                                n_days=vp_cfg.cycle, cur_entry=vp_cfg.cur_entry,
                                stock_code=code,
                            )
                            vp_meta = f"kiwoom/{vp_cfg.cycle}d/{vp_cfg.bands}b/cur{vp_cfg.cur_entry}"
                        except Exception as e:
                            logger.debug(f"VP(kiwoom) {code} 오류: {e}")
                    
                    if vp_result is not None and vp_result.tag == "데이터부족":
                        vp_result = None
                    
                    # 로컬 CSV 폴백
                    if vp_result is None and use_local:
                        vp_result = calc_volume_profile_from_csv(
                            stock_code=code, current_price=price,
                            ohlcv_dir=OHLCV_FULL_DIR,
                            n_days=vp_cfg.cycle, n_bands=vp_cfg.bands,
                        )
                        vp_meta = f"local/{vp_cfg.cycle}d/{vp_cfg.bands}b/cur{vp_cfg.cur_entry}"
                    
                    if vp_result is None:
                        vp_result = VolumeProfileResult()
                        vp_meta = ""
                    
                    score.score_detail.raw_vp_score = vp_result.score
                    score.score_detail.raw_vp_above_pct = vp_result.above_pct
                    score.score_detail.raw_vp_below_pct = vp_result.below_pct
                    score.score_detail.raw_vp_tag = vp_result.tag
                    score.score_detail.raw_vp_meta = vp_meta
                    if vp_result.tag != "데이터부족":
                        vp_count += 1
                except Exception as e:
                    logger.debug(f"VP {code} 오류: {e}")
                    score.score_detail.raw_vp_score = VP_SCORE_NEUTRAL
                    score.score_detail.raw_vp_above_pct = 0.0
                    score.score_detail.raw_vp_below_pct = 0.0
                    score.score_detail.raw_vp_tag = "오류"
                    score.score_detail.raw_vp_meta = ""
            
            logger.info(f"[매물대] {vp_count}/{len(scores_filtered)}개 계산 완료")""",
    "new": """            vp_data_cache = None
            vp_error_count = 0
            for score in scores_filtered:
                code = score.stock_code
                price = score.current_price
                try:
                    vp_result = None
                    vp_meta = ""
                    
                    # 키움 API
                    if use_kiwoom and kiwoom_client and kiwoom_available:
                        try:
                            if vp_data_cache is None:
                                data = kiwoom_client.get_volume_profile(
                                    stock_code=code,
                                    cycle_tp=str(vp_cfg.cycle),
                                    prpscnt=str(vp_cfg.bands),
                                    cur_prc_entry=str(vp_cfg.cur_entry),
                                    trde_qty_tp=str(vp_cfg.trde_qty_tp),
                                    tr_id=str(vp_cfg.api_id),
                                )
                                if isinstance(data, dict) and not any(
                                    isinstance(v, list) and v for v in data.values()
                                ):
                                    kiwoom_available = False
                                    data = {}
                                vp_data_cache = data
                            else:
                                data = vp_data_cache
                            
                            vp_result = calc_volume_profile_from_kiwoom(
                                data=data, current_price=price,
                                n_days=vp_cfg.cycle, cur_entry=vp_cfg.cur_entry,
                                stock_code=code,
                            )
                            vp_meta = f"kiwoom/{vp_cfg.cycle}d/{vp_cfg.bands}b/cur{vp_cfg.cur_entry}"
                        except Exception as e:
                            logger.debug(f"VP(kiwoom) {code} 오류: {e}")
                    
                    if vp_result is not None and vp_result.tag == "데이터부족":
                        vp_result = None
                    
                    # 로컬 CSV 폴백
                    if vp_result is None and use_local:
                        vp_result = calc_volume_profile_from_csv(
                            stock_code=code, current_price=price,
                            ohlcv_dir=OHLCV_FULL_DIR,
                            n_days=vp_cfg.cycle, n_bands=vp_cfg.bands,
                        )
                        vp_meta = f"local/{vp_cfg.cycle}d/{vp_cfg.bands}b/cur{vp_cfg.cur_entry}"
                    
                    if vp_result is None:
                        vp_result = VolumeProfileResult()
                        vp_meta = ""
                    
                    # 안전한 속성 접근 (score_detail 또는 vp_result가 None인 케이스 방어)
                    if score.score_detail is not None and vp_result is not None:
                        score.score_detail.raw_vp_score = vp_result.score
                        score.score_detail.raw_vp_above_pct = vp_result.above_pct
                        score.score_detail.raw_vp_below_pct = vp_result.below_pct
                        score.score_detail.raw_vp_tag = vp_result.tag
                        score.score_detail.raw_vp_meta = vp_meta
                        if vp_result.tag != "데이터부족":
                            vp_count += 1
                    else:
                        vp_error_count += 1
                except Exception as e:
                    vp_error_count += 1
                    if score.score_detail is not None:
                        score.score_detail.raw_vp_score = VP_SCORE_NEUTRAL
                        score.score_detail.raw_vp_above_pct = 0.0
                        score.score_detail.raw_vp_below_pct = 0.0
                        score.score_detail.raw_vp_tag = "오류"
                        score.score_detail.raw_vp_meta = ""
            
            # 요약 로그 (개별 오류 스팸 제거)
            if vp_error_count > 0:
                logger.info(f"[매물대] {vp_count}/{len(scores_filtered)}개 계산 완료 (오류: {vp_error_count}개)")
            else:
                logger.info(f"[매물대] {vp_count}/{len(scores_filtered)}개 계산 완료")"""
})

# ============================================================
# Patch 5a: 1_top5_tracker.py - CSS #888 → #888888 (요약카드)
# ============================================================
PATCHES.append({
    "file": "dashboard/pages/1_top5_tracker.py",
    "desc": "CSS hex 3자리→6자리 수정 (요약카드 rec_color)",
    "old": "rec_color = {'매수': '#4CAF50', '관망': '#FF9800', '매도': '#F44336'}.get(ai_rec, '#888')",
    "new": "rec_color = {'매수': '#4CAF50', '관망': '#FF9800', '매도': '#F44336'}.get(ai_rec, '#888888')",
})

# ============================================================
# Patch 5b: 1_top5_tracker.py - CSS #888 → #888888 (상세분석)
# ============================================================
PATCHES.append({
    "file": "dashboard/pages/1_top5_tracker.py",
    "desc": "CSS hex 3자리→6자리 수정 (상세분석 risk_color)",
    "old": "risk_color = {'높음': '#4CAF50', '보통': '#FF9800', '낮음': '#F44336'}.get(ai_risk, '#888')",
    "new": "risk_color = {'높음': '#4CAF50', '보통': '#FF9800', '낮음': '#F44336'}.get(ai_risk, '#888888')",
})


# ============================================================
# 패치 적용 엔진
# ============================================================

def apply_patches(dry_run=False, revert=False):
    """패치 적용/복원"""
    
    if revert:
        return revert_from_backup()
    
    print(f"{'🔍 DRY RUN' if dry_run else '🔧 APPLYING'} - ClosingBell v10.1.1 패치")
    print(f"프로젝트 루트: {PROJECT_ROOT}")
    print(f"패치 수: {len(PATCHES)}개")
    print("=" * 60)
    
    # 백업
    if not dry_run:
        BACKUP_DIR.mkdir(exist_ok=True)
        backed_up = set()
        for p in PATCHES:
            fpath = PROJECT_ROOT / p["file"]
            if fpath.exists() and p["file"] not in backed_up:
                backup_path = BACKUP_DIR / p["file"].replace("/", "_").replace("\\", "_")
                shutil.copy2(fpath, backup_path)
                backed_up.add(p["file"])
        print(f"📦 백업 완료: {len(backed_up)}개 파일 → {BACKUP_DIR}")
        print()
    
    success = 0
    failed = 0
    skipped = 0
    
    for i, p in enumerate(PATCHES, 1):
        fpath = PROJECT_ROOT / p["file"]
        print(f"[{i}/{len(PATCHES)}] {p['file']}")
        print(f"  📝 {p['desc']}")
        
        if not fpath.exists():
            print(f"  ❌ 파일 없음!")
            failed += 1
            continue
        
        content = fpath.read_text(encoding='utf-8')
        
        if p["old"] not in content:
            if p["new"] in content:
                print(f"  ⏭️ 이미 적용됨 (스킵)")
                skipped += 1
            else:
                print(f"  ❌ 매칭 실패! (코드가 변경되었을 수 있음)")
                failed += 1
            continue
        
        # 유일성 검증
        count = content.count(p["old"])
        if count > 1:
            print(f"  ⚠️ 중복 매칭 {count}회 (첫 번째만 교체)")
        
        new_content = content.replace(p["old"], p["new"], 1)
        
        if dry_run:
            print(f"  ✅ 매칭 성공 (적용 가능)")
        else:
            fpath.write_text(new_content, encoding='utf-8')
            print(f"  ✅ 적용 완료")
        
        success += 1
    
    print()
    print("=" * 60)
    print(f"결과: ✅ {success}개 성공 | ⏭️ {skipped}개 스킵 | ❌ {failed}개 실패")
    
    if not dry_run and failed == 0:
        print()
        print("🎯 다음 단계:")
        print("  1. python test_patch_v10.1.1.py   ← 로컬 검증 실행")
        print("  2. 거래일에 python main.py 실행 후 로그 확인")
    
    return failed == 0


def revert_from_backup():
    """백업에서 복원"""
    if not BACKUP_DIR.exists():
        print(f"❌ 백업 디렉토리 없음: {BACKUP_DIR}")
        return False
    
    restored = 0
    for backup_file in BACKUP_DIR.iterdir():
        # 역변환: src_services_xxx.py → src/services/xxx.py
        # 원본 이름 추정 (단순 매핑)
        original_name = None
        for p in PATCHES:
            expected_backup = p["file"].replace("/", "_").replace("\\", "_")
            if backup_file.name == expected_backup:
                original_name = p["file"]
                break
        
        if original_name:
            target = PROJECT_ROOT / original_name
            shutil.copy2(backup_file, target)
            print(f"  ♻️ 복원: {original_name}")
            restored += 1
    
    print(f"\n✅ {restored}개 파일 복원 완료")
    return True


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    revert = "--revert" in sys.argv
    
    if not apply_patches(dry_run=dry_run, revert=revert):
        sys.exit(1)
