"""거래원 수급 AI 분석 서비스 (v9.1)

스케줄러에서 실행되어 broker_signals 테이블의 AI 분석 결과를 저장합니다.
대시보드는 저장된 결과만 표시합니다.
"""

import os
import time
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def analyze_broker_signals_ai(target_date: Optional[date] = None) -> bool:
    """거래원 수급 데이터에 대한 AI 분석 실행 및 DB 저장

    Args:
        target_date: 분석 대상 날짜 (기본: 오늘)

    Returns:
        성공 여부
    """
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime("%Y-%m-%d")

    # 1. DB에서 거래원 데이터 조회
    try:
        from src.infrastructure.repository import get_broker_signal_repository
        repo = get_broker_signal_repository()
        signals = repo.get_signals_by_date(date_str)
    except Exception as e:
        logger.error(f"[broker_ai] DB 조회 실패: {e}")
        return False

    if not signals:
        logger.info(f"[broker_ai] {date_str} 거래원 데이터 없음 - 스킵")
        return True

    # 이미 AI 분석이 있으면 스킵
    existing = repo.get_ai_summary_by_date(date_str)
    if existing:
        logger.info(f"[broker_ai] {date_str} 이미 AI 분석 완료 - 스킵")
        return True

    # 2. 종목명 매핑
    names = {}
    try:
        from src.config.app_config import MAPPING_FILE
        if MAPPING_FILE and MAPPING_FILE.exists():
            import csv
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    names[str(row.get("code", "")).zfill(6)] = row.get("name", "")
    except Exception:
        pass

    # 3. 프롬프트 구성
    parts = []
    for sig in signals:
        row = dict(sig) if not isinstance(sig, dict) else sig
        code = row.get("stock_code", "")
        name = names.get(code, row.get("stock_name", code))
        parts.append(
            f"- {name}({code}): 이상치={row.get('anomaly_score', 0)}점, "
            f"비주류={row.get('unusual_score', 0)}, 비대칭={row.get('asymmetry_score', 0)}, "
            f"분포이상={row.get('distribution_score', 0)}, 외국계={row.get('foreign_score', 0)}, "
            f"태그={row.get('tag', '')}, "
            f"외국인매수={row.get('frgn_buy', 0)}, 외국인매도={row.get('frgn_sell', 0)}"
        )

    prompt = f"""아래는 {date_str} 감시종목의 거래원 수급 분석 데이터입니다.

{chr(10).join(parts)}

다음 항목을 분석해주세요:
1. **특이 패턴**: 비정상적인 거래 패턴이 보이는 종목과 이유
2. **세력 매집 의심**: 비주류 증권사 점수가 높은 종목 해석
3. **외국인 동향**: 외국계 매수/매도 흐름 요약
4. **전체 수급 분위기**: 매수 우위 / 매도 우위 / 관망
5. **주의 종목**: 특별히 주시할 종목과 이유

한국어로 간결하게 답변해주세요. 마크다운 가능."""

    # 4. Gemini API 호출
    try:
        from google import genai
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("[broker_ai] GEMINI_API_KEY 미설정 - 스킵")
            return False

        client = genai.Client(api_key=api_key)

        # 설정에서 모델명 로드
        try:
            from src.config.settings import settings
            model_name = settings.ai.model
            temperature = settings.ai.temperature
            max_tokens = settings.ai.max_output_tokens
        except Exception:
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            temperature = 0.3
            max_tokens = 1500

        response = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "max_output_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                break
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"[broker_ai] 재시도 {attempt+1}/3 ({wait}초): {e}")
                    time.sleep(wait)
                else:
                    raise

        if not response or not response.text:
            logger.warning("[broker_ai] AI 응답 없음")
            return False

        ai_text = response.text.strip()

    except ImportError:
        logger.warning("[broker_ai] google-genai 패키지 없음 - 스킵")
        return False
    except Exception as e:
        logger.error(f"[broker_ai] AI 호출 실패: {e}")
        return False

    # 5. DB 저장
    saved = repo.save_ai_summary(date_str, ai_text)
    if saved:
        logger.info(f"[broker_ai] {date_str} AI 분석 저장 완료 ({len(ai_text)}자)")
    else:
        logger.error(f"[broker_ai] {date_str} AI 분석 저장 실패")

    return saved


def run_broker_ai_analysis():
    """스케줄러용 엔트리 포인트"""
    return analyze_broker_signals_ai()
