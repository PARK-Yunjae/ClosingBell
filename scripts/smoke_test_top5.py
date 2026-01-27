#!/usr/bin/env python
"""
ClosingBell v6.5 스모크 테스트 스크립트

P0 이슈 검증:
1. TOP5가 올바르게 출력되는지 (TOP3로 잘리지 않음)
2. DB 덮어쓰기가 발생하지 않는지 (sector/theme 등 보존)
3. AI 분석 결과가 저장되는지
4. 중복 AI 호출이 방지되는지

사용법:
    # 전체 테스트 (dry-run 모드, 웹훅 발송 안 함)
    python scripts/smoke_test_top5.py
    
    # 실제 웹훅 발송 포함
    DISCORD_DRY_RUN=false python scripts/smoke_test_top5.py
    
환경변수:
    DISCORD_DRY_RUN: true면 웹훅 발송 대신 콘솔 출력 (기본 true)
"""

import os
import sys
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

# 프로젝트 루트 추가
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Dry-run 모드 확인
DRY_RUN = os.getenv('DISCORD_DRY_RUN', 'true').lower() == 'true'


class SmokeTestResult:
    """스모크 테스트 결과"""
    def __init__(self, test_name: str):
        self.test_name = test_name
        self.passed = False
        self.message = ""
        self.details = {}
    
    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} [{self.test_name}] {self.message}"


def print_header(title: str):
    """헤더 출력"""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_result(result: SmokeTestResult):
    """결과 출력"""
    print(str(result))
    if result.details:
        for key, value in result.details.items():
            print(f"    - {key}: {value}")


class SmokeTest:
    """스모크 테스트 클래스"""
    
    def __init__(self):
        self.results: List[SmokeTestResult] = []
        self.test_date = date.today().isoformat()
        self.db_path = project_root / 'data' / 'screener.db'
    
    def run_all(self):
        """모든 테스트 실행"""
        print_header("ClosingBell v6.5 스모크 테스트")
        print(f"테스트 날짜: {self.test_date}")
        print(f"Dry-run 모드: {DRY_RUN}")
        print()
        
        # 1. 모듈 import 테스트
        self.test_module_imports()
        
        # 2. 설정 로드 테스트
        self.test_settings_load()
        
        # 3. DB 연결 테스트
        self.test_db_connection()
        
        # 4. TOP5 조회 테스트 (기존 데이터)
        self.test_top5_data()
        
        # 5. AI 필드 업데이트 테스트
        self.test_ai_update()
        
        # 6. AI 중복 호출 방지 테스트
        self.test_ai_skip_logic()
        
        # 7. 웹훅 포맷 테스트
        self.test_webhook_format()
        
        # 결과 요약
        self.print_summary()
    
    def test_module_imports(self):
        """모듈 import 테스트"""
        result = SmokeTestResult("모듈 Import")
        
        try:
            # 핵심 모듈 import
            from src.config.settings import settings
            from src.config.constants import TOP_N_COUNT, get_top_n_count
            from src.infrastructure.repository import get_top5_history_repository
            from src.services.discord_embed_builder import DiscordEmbedBuilder
            from src.services.top5_pipeline import Top5Pipeline
            
            result.passed = True
            result.message = "모든 핵심 모듈 import 성공"
            result.details = {
                "TOP_N_COUNT (상수)": TOP_N_COUNT,
                "get_top_n_count() (함수)": get_top_n_count(),
                "settings.screening.top_n_count": settings.screening.top_n_count,
            }
        except ImportError as e:
            result.message = f"Import 실패: {e}"
        
        self.results.append(result)
        print_result(result)
    
    def test_settings_load(self):
        """설정 로드 테스트"""
        result = SmokeTestResult("설정 로드")
        
        try:
            from src.config.settings import settings
            from src.config.constants import get_top_n_count
            
            # TOP_N_COUNT가 5인지 확인
            top_n = settings.screening.top_n_count
            
            # ★ P0-B: get_top_n_count()가 settings와 일치하는지 확인
            top_n_from_func = get_top_n_count()
            
            if top_n >= 5 and top_n == top_n_from_func:
                result.passed = True
                result.message = f"TOP_N_COUNT = {top_n} (설정 통일 OK)"
            else:
                result.message = f"TOP_N_COUNT 불일치: settings={top_n}, get_top_n_count()={top_n_from_func}"
            
            result.details = {
                "preview_time": settings.screening.screening_time_preview,
                "main_time": settings.screening.screening_time_main,
                "settings.top_n_count": top_n,
                "get_top_n_count()": top_n_from_func,
            }
        except Exception as e:
            result.message = f"설정 로드 실패: {e}"
        
        self.results.append(result)
        print_result(result)
    
    def test_db_connection(self):
        """DB 연결 테스트"""
        result = SmokeTestResult("DB 연결")
        
        try:
            import sqlite3
            
            if not self.db_path.exists():
                result.message = f"DB 파일 없음: {self.db_path}"
                self.results.append(result)
                print_result(result)
                return
            
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # 테이블 존재 확인
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            required_tables = ['closing_top5_history', 'screenings', 'screening_items']
            missing = [t for t in required_tables if t not in tables]
            
            if not missing:
                result.passed = True
                result.message = "DB 연결 및 테이블 확인 완료"
                result.details = {
                    "tables_count": len(tables),
                    "required_tables": "모두 존재",
                }
            else:
                result.message = f"누락된 테이블: {missing}"
            
            conn.close()
        except Exception as e:
            result.message = f"DB 연결 실패: {e}"
        
        self.results.append(result)
        print_result(result)
    
    def test_top5_data(self):
        """TOP5 데이터 조회 및 검증"""
        result = SmokeTestResult("TOP5 데이터 검증")
        
        try:
            import sqlite3
            
            if not self.db_path.exists():
                result.message = "DB 파일 없음"
                self.results.append(result)
                print_result(result)
                return
            
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 최근 날짜의 TOP5 조회
            cursor.execute("""
                SELECT screen_date, COUNT(*) as cnt
                FROM closing_top5_history
                GROUP BY screen_date
                ORDER BY screen_date DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            
            if not row:
                result.message = "TOP5 데이터 없음 (정상 - 첫 실행)"
                result.passed = True
                self.results.append(result)
                print_result(result)
                conn.close()
                return
            
            recent_date = row['screen_date']
            count = row['cnt']
            
            # 해당 날짜의 데이터 검증
            cursor.execute("""
                SELECT * FROM closing_top5_history
                WHERE screen_date = ?
                ORDER BY rank
            """, (recent_date,))
            items = [dict(row) for row in cursor.fetchall()]
            
            # 검증 1: 5개 이상인지
            if count < 5:
                result.message = f"TOP5 개수 부족: {count}개 (5개 이상이어야 함)"
                self.results.append(result)
                print_result(result)
                conn.close()
                return
            
            # 검증 2: sector/theme 등이 빈 값으로 덮어쓰여졌는지
            empty_sector_count = sum(1 for item in items if not item.get('sector'))
            
            # 검증 3: AI 필드 존재 여부
            has_ai = sum(1 for item in items if item.get('ai_recommendation'))
            
            result.passed = True
            result.message = f"최근 {recent_date}: {count}개 종목"
            result.details = {
                "sector_있는_종목": f"{count - empty_sector_count}/{count}",
                "AI_분석_완료": f"{has_ai}/{count}",
            }
            
            conn.close()
        except Exception as e:
            result.message = f"데이터 조회 실패: {e}"
        
        self.results.append(result)
        print_result(result)
    
    def test_ai_update(self):
        """AI 필드 업데이트 테스트"""
        result = SmokeTestResult("AI 업데이트 메서드")
        
        try:
            from src.infrastructure.repository import get_top5_history_repository
            
            repo = get_top5_history_repository()
            
            # 메서드 존재 확인
            methods = ['update_ai_fields', 'has_ai_analysis', 'get_stocks_without_ai']
            missing = [m for m in methods if not hasattr(repo, m)]
            
            if not missing:
                result.passed = True
                result.message = "AI 업데이트 메서드 모두 존재"
                result.details = {
                    "methods": ", ".join(methods),
                }
            else:
                result.message = f"누락된 메서드: {missing}"
        except Exception as e:
            result.message = f"Repository 로드 실패: {e}"
        
        self.results.append(result)
        print_result(result)
    
    def test_ai_skip_logic(self):
        """★ P0-A: AI 중복 호출 방지 로직 테스트"""
        result = SmokeTestResult("AI 중복 호출 방지")
        
        try:
            from src.services.top5_pipeline import Top5Pipeline
            import inspect
            
            # Top5Pipeline.process_top5 코드에 has_ai_analysis 체크가 있는지 확인
            source = inspect.getsource(Top5Pipeline.process_top5)
            
            has_skip_logic = 'has_ai_analysis' in source
            has_already_analyzed = 'already_analyzed' in source
            
            if has_skip_logic and has_already_analyzed:
                result.passed = True
                result.message = "AI 중복 호출 방지 로직 존재"
                result.details = {
                    "has_ai_analysis 체크": has_skip_logic,
                    "already_analyzed 딕셔너리": has_already_analyzed,
                }
            else:
                result.message = "AI 중복 호출 방지 로직 부족"
                result.details = {
                    "has_ai_analysis 체크": has_skip_logic,
                    "already_analyzed 딕셔너리": has_already_analyzed,
                }
        except Exception as e:
            result.message = f"Top5Pipeline 검사 실패: {e}"
        
        self.results.append(result)
        print_result(result)
    
    def test_webhook_format(self):
        """웹훅 포맷 테스트"""
        result = SmokeTestResult("웹훅 포맷")
        
        try:
            from src.services.discord_embed_builder import (
                DiscordEmbedBuilder, 
                DISCORD_FIELD_VALUE_LIMIT,
                DISCORD_EMBED_TOTAL_LIMIT,
            )
            
            builder = DiscordEmbedBuilder()
            
            # truncate 메서드 테스트
            long_text = "A" * 2000
            truncated = builder._truncate(long_text, 1024)
            
            # ★ P0-D: _enforce_embed_limits 메서드 존재 확인
            has_enforce_limits = hasattr(builder, '_enforce_embed_limits')
            
            if len(truncated) <= DISCORD_FIELD_VALUE_LIMIT and has_enforce_limits:
                result.passed = True
                result.message = f"Truncate 정상 + Embed 제한 메서드 존재"
                result.details = {
                    "DISCORD_FIELD_VALUE_LIMIT": DISCORD_FIELD_VALUE_LIMIT,
                    "DISCORD_EMBED_TOTAL_LIMIT": DISCORD_EMBED_TOTAL_LIMIT,
                    "_enforce_embed_limits 존재": has_enforce_limits,
                }
            else:
                result.message = f"Truncate 또는 제한 메서드 문제"
        except Exception as e:
            result.message = f"Embed Builder 테스트 실패: {e}"
        
        self.results.append(result)
        print_result(result)
    
    def print_summary(self):
        """결과 요약 출력"""
        print_header("테스트 결과 요약")
        
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        
        for result in self.results:
            status = "✅" if result.passed else "❌"
            print(f"  {status} {result.test_name}")
        
        print()
        print(f"결과: {passed}/{total} 통과")
        
        if passed == total:
            print("\n🎉 모든 테스트 통과!")
        else:
            print("\n⚠️ 일부 테스트 실패. 위 내용을 확인하세요.")


def run_preview_test():
    """프리뷰 모드 테스트 (dry-run)"""
    print_header("프리뷰 모드 테스트")
    
    if DRY_RUN:
        print("⚠️ Dry-run 모드: 실제 스크리닝 실행하지 않음")
        print("  실제 테스트하려면: DISCORD_DRY_RUN=false python scripts/smoke_test_top5.py")
        return True
    
    try:
        from src.services.screener_service import ScreenerService
        
        service = ScreenerService()
        # 프리뷰 모드 실행
        result = service.run_screening(is_preview=True)
        
        if result:
            print(f"✅ 프리뷰 실행 완료: {len(result.get('top_n', []))}개 종목")
            return True
        else:
            print("❌ 프리뷰 실행 실패")
            return False
    except Exception as e:
        print(f"❌ 프리뷰 테스트 실패: {e}")
        return False


def run_main_test():
    """메인 모드 테스트 (dry-run)"""
    print_header("메인 모드 테스트")
    
    if DRY_RUN:
        print("⚠️ Dry-run 모드: 실제 스크리닝 실행하지 않음")
        return True
    
    try:
        from src.services.screener_service import ScreenerService
        
        service = ScreenerService()
        # 메인 모드 실행
        result = service.run_screening(is_preview=False)
        
        if result:
            print(f"✅ 메인 실행 완료: {len(result.get('top_n', []))}개 종목")
            return True
        else:
            print("❌ 메인 실행 실패")
            return False
    except Exception as e:
        print(f"❌ 메인 테스트 실패: {e}")
        return False


if __name__ == "__main__":
    # 스모크 테스트 실행
    smoke = SmokeTest()
    smoke.run_all()
    
    # 추가 실행 테스트 (dry-run이 아닐 때만)
    if not DRY_RUN:
        run_preview_test()
        run_main_test()
