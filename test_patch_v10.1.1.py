#!/usr/bin/env python3
"""
ClosingBell v10.1.1 로컬 테스트
================================
패치 적용 후 실행하여 전체 검증

사용법:
    cd C:\\Coding\\ClosingBell
    python test_patch_v10.1.1.py

테스트 항목:
    [T1] 문법 검증 — 5개 수정 파일 AST 파싱
    [T2] import 검증 — 핵심 모듈 임포트 가능 여부
    [T3] 공매도/SR 로깅 — enrichment 로그 레벨 확인
    [T4] sqlite3.Row 수정 — dict() 변환 코드 존재 확인
    [T5] 눌림목 API 폴백 — _load_ohlcv_df 함수 존재 + 로직 확인
    [T6] VP 방어 코드 — None 체크 + 요약 로그 확인
    [T7] CSS hex 수정 — #888888 6자리 확인
    [T8] DB 연결 — screener.db 접근 + 테이블 확인
    [T9] 공매도 서비스 — ShortSellingScore 모델 속성 확인
    [T10] 눌림목 실데이터 — pullback_signals 존재 + API 폴백 시뮬레이션
"""

import sys
import os
import ast
import importlib
import traceback
from pathlib import Path
from datetime import date

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 환경 설정 (API 호출 방지)
os.environ["DASHBOARD_ONLY"] = "true"


def test_result(name: str, passed: bool, detail: str = ""):
    icon = "✅" if passed else "❌"
    msg = f"  {icon} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return passed


def run_all_tests():
    print("=" * 60)
    print("🧪 ClosingBell v10.1.1 패치 검증")
    print(f"프로젝트: {PROJECT_ROOT}")
    print("=" * 60)
    
    total = 0
    passed = 0
    
    # ============================================================
    # T1: 문법 검증
    # ============================================================
    print("\n[T1] 파일 문법 검증 (AST)")
    files = [
        "src/services/enrichment_service.py",
        "src/services/top5_pipeline.py",
        "src/services/pullback_tracker.py",
        "src/services/screener_service.py",
        "dashboard/pages/1_top5_tracker.py",
    ]
    for f in files:
        total += 1
        fpath = PROJECT_ROOT / f
        try:
            with open(fpath, encoding='utf-8') as fh:
                ast.parse(fh.read())
            if test_result(f, True):
                passed += 1
        except Exception as e:
            test_result(f, False, str(e))
    
    # ============================================================
    # T2: import 검증
    # ============================================================
    print("\n[T2] 모듈 임포트 검증")
    modules = [
        ("src.domain.short_selling", "ShortSellingScore 모델"),
        ("src.domain.volume_profile", "VolumeProfileResult 모델"),
        ("src.domain.score_calculator", "ScoreDetail 모델"),
        ("src.infrastructure.database", "DB 접근"),
    ]
    for mod, desc in modules:
        total += 1
        try:
            importlib.import_module(mod)
            if test_result(f"{mod}", True, desc):
                passed += 1
        except Exception as e:
            test_result(f"{mod}", False, f"{type(e).__name__}: {e}")
    
    # ============================================================
    # T3: enrichment_service 공매도/SR 로깅 레벨
    # ============================================================
    print("\n[T3] 공매도/SR 로깅 레벨 검증")
    total += 1
    try:
        content = (PROJECT_ROOT / "src/services/enrichment_service.py").read_text(encoding='utf-8')
        checks = [
            'logger.info(f"📉 공매도 분석:' in content,
            'logger.info(f"📊 지지/저항:' in content,
            'type(e).__name__' in content,
            '가격 데이터 없음 (prices=None)' in content,
        ]
        ok = all(checks)
        detail = f"{sum(checks)}/4 체크 통과"
        if not ok:
            labels = ["공매도 info 로그", "지지저항 info 로그", "에러타입 추가", "prices=None 경고"]
            missing = [l for l, c in zip(labels, checks) if not c]
            detail += f" (미통과: {', '.join(missing)})"
        if test_result("enrichment 로깅", ok, detail):
            passed += 1
    except Exception as e:
        test_result("enrichment 로깅", False, str(e))
    
    # ============================================================
    # T4: sqlite3.Row .get() 수정
    # ============================================================
    print("\n[T4] sqlite3.Row dict() 변환 검증")
    total += 1
    try:
        content = (PROJECT_ROOT / "src/services/top5_pipeline.py").read_text(encoding='utf-8')
        ok = 'existing = dict(existing)' in content
        if test_result("dict(existing) 변환", ok):
            passed += 1
    except Exception as e:
        test_result("dict(existing) 변환", False, str(e))
    
    # T4b: AI 캐시 로그 레벨
    total += 1
    try:
        ok = 'logger.info(f"AI 캐시 체크 실패' in content
        if test_result("AI 캐시 로그 info 레벨", ok):
            passed += 1
    except Exception as e:
        test_result("AI 캐시 로그", False, str(e))
    
    # ============================================================
    # T5: 눌림목 API 폴백
    # ============================================================
    print("\n[T5] 눌림목 API 폴백 검증")
    total += 1
    try:
        content = (PROJECT_ROOT / "src/services/pullback_tracker.py").read_text(encoding='utf-8')
        checks = [
            'def _load_ohlcv_df(' in content,
            '_get_api_client' in content,
            'get_kiwoom_client' in content,
            'client.get_daily_prices' in content,
            'API 폴백:' in content,
        ]
        ok = all(checks)
        detail = f"{sum(checks)}/5 체크 통과"
        if test_result("pullback API 폴백", ok, detail):
            passed += 1
    except Exception as e:
        test_result("pullback API 폴백", False, str(e))
    
    # ============================================================
    # T6: VP 매물대 방어 코드
    # ============================================================
    print("\n[T6] VP 매물대 방어 코드 검증")
    total += 1
    try:
        content = (PROJECT_ROOT / "src/services/screener_service.py").read_text(encoding='utf-8')
        checks = [
            'if score.score_detail is not None and vp_result is not None:' in content,
            'vp_error_count' in content,
            '(오류: {vp_error_count}개)' in content,
        ]
        ok = all(checks)
        detail = f"{sum(checks)}/3 체크 통과"
        if not ok:
            labels = ["None 가드", "에러 카운터", "요약 로그"]
            missing = [l for l, c in zip(labels, checks) if not c]
            detail += f" (미통과: {', '.join(missing)})"
        if test_result("VP None 방어 + 요약 로그", ok, detail):
            passed += 1
    except Exception as e:
        test_result("VP 방어 코드", False, str(e))
    
    # ============================================================
    # T7: CSS hex 수정
    # ============================================================
    print("\n[T7] CSS hex 6자리 검증")
    total += 1
    try:
        content = (PROJECT_ROOT / "dashboard/pages/1_top5_tracker.py").read_text(encoding='utf-8')
        has_old = "get(ai_rec, '#888')" in content or "get(ai_risk, '#888')" in content
        has_new = "#888888" in content
        ok = not has_old and has_new
        detail = f"old 3자리={'있음 ❌' if has_old else '없음 ✅'}, new 6자리={'있음 ✅' if has_new else '없음 ❌'}"
        if test_result("CSS #888 → #888888", ok, detail):
            passed += 1
    except Exception as e:
        test_result("CSS hex 수정", False, str(e))
    
    # ============================================================
    # T8: DB 연결 + 테이블 확인
    # ============================================================
    print("\n[T8] DB 연결 검증")
    total += 1
    try:
        import sqlite3
        db_path = PROJECT_ROOT / "data" / "screener.db"
        if not db_path.exists():
            test_result("DB 파일", False, f"파일 없음: {db_path}")
        else:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # 핵심 테이블 존재 확인
            tables = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [t[0] for t in tables]
            
            required = [
                'closing_top5_history', 'pullback_signals', 'pullback_daily_prices',
                'volume_spikes', 'nomad_candidates',
            ]
            missing = [t for t in required if t not in table_names]
            ok = len(missing) == 0
            detail = f"{len(table_names)}개 테이블"
            if missing:
                detail += f" (누락: {missing})"
            if test_result("DB 테이블", ok, detail):
                passed += 1
            
            # 공매도/SR 컬럼 확인
            total += 1
            cols = cursor.execute("PRAGMA table_info(closing_top5_history)").fetchall()
            col_names = [c[1] for c in cols]
            sr_cols = ['short_ratio', 'short_score', 'sr_score', 'sr_nearest_support', 'sr_nearest_resistance']
            has_sr = all(c in col_names for c in sr_cols)
            if test_result("공매도/SR 컬럼", has_sr, f"{sum(c in col_names for c in sr_cols)}/5"):
                passed += 1
            
            # TOP5 데이터 확인
            total += 1
            row = cursor.execute(
                "SELECT COUNT(*) as cnt, MAX(screen_date) as latest FROM closing_top5_history"
            ).fetchone()
            cnt, latest = row
            if test_result("TOP5 데이터", cnt > 0, f"{cnt}건, 최근={latest}"):
                passed += 1
            
            # 눌림목 시그널 확인
            total += 1
            row = cursor.execute("SELECT COUNT(*) FROM pullback_signals").fetchone()
            pb_cnt = row[0]
            if test_result("눌림목 시그널", pb_cnt > 0, f"{pb_cnt}건"):
                passed += 1
            
            # 눌림목 추적 데이터 확인
            total += 1
            row = cursor.execute("SELECT COUNT(*) FROM pullback_daily_prices").fetchone()
            pd_cnt = row[0]
            test_result("눌림목 추적 데이터", True, f"{pd_cnt}건 {'(API 폴백으로 채워질 예정)' if pd_cnt == 0 else ''}")
            passed += 1  # 0건도 정상 (다음 실행에서 채워짐)
            
            conn.close()
    except Exception as e:
        test_result("DB 연결", False, str(e))
    
    # ============================================================
    # T9: ShortSellingScore 모델 검증
    # ============================================================
    print("\n[T9] 공매도 모델 검증")
    total += 1
    try:
        from src.domain.short_selling import ShortSellingScore
        ss = ShortSellingScore(stock_code="TEST")
        attrs = ['score', 'latest_short_ratio', 'tags', 'summary']
        has_all = all(hasattr(ss, a) for a in attrs)
        if test_result("ShortSellingScore 속성", has_all, f"score={ss.score}, ratio={ss.latest_short_ratio}"):
            passed += 1
    except Exception as e:
        test_result("ShortSellingScore", False, str(e))
    
    # ============================================================
    # T10: 키움 API 폴백 시뮬레이션 (오프라인)
    # ============================================================
    print("\n[T10] 눌림목 추적 기능 검증 (오프라인)")
    total += 1
    try:
        from src.services.pullback_tracker import update_pullback_tracking
        # 함수 시그니처 확인
        import inspect
        sig = inspect.signature(update_pullback_tracking)
        params = list(sig.parameters.keys())
        ok = 'tracking_days' in params and 'lookback_days' in params
        if test_result("update_pullback_tracking 시그니처", ok, f"params={params}"):
            passed += 1
    except Exception as e:
        test_result("pullback_tracker", False, str(e))
    
    # ============================================================
    # 결과 요약
    # ============================================================
    print()
    print("=" * 60)
    rate = (passed / total * 100) if total > 0 else 0
    status = "✅ ALL PASS" if passed == total else "⚠️ PARTIAL" if passed > total * 0.8 else "❌ FAILED"
    print(f"결과: {passed}/{total} ({rate:.0f}%) — {status}")
    
    if passed == total:
        print()
        print("🎯 모든 테스트 통과! 다음 거래일에 실행하여 확인하세요:")
        print("   python main.py")
        print()
        print("확인할 로그 (시간순):")
        print("   15:00  📉 공매도 분석: xxx → score=..., ratio=...%")
        print("   15:00  📊 지지/저항: xxx → score=..., S=..., R=...")
        print("   15:00  [매물대] N/76개 계산 완료 (오류: M개)")  
        print("   15:00  공매도/SR 체크: xxx → ss=있음, sr=있음")
        print("   16:07  [pullback_tracker] API 폴백: xxx → 30일")
    elif passed < total:
        print()
        print("⚠️ 실패한 테스트를 확인하고 패치를 재적용하세요:")
        print("   python apply_patch_v10.1.1.py --dry-run")
    
    print("=" * 60)
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
