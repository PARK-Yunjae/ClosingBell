"""
키워드 기반 스코어 보너스 설정
============================

이 파일을 수정하여 키워드 분석 결과를 스코어링에 반영합니다.
"""

# ═══════════════════════════════════════════════════════════════════════════
# 키워드 시그널 → 스코어 보너스 설정
# ═══════════════════════════════════════════════════════════════════════════

# 주도 섹터에 해당하면 보너스 (최대 +10점)
SECTOR_BONUS = {
    "로봇/자동화": 10,      # 현재 가장 핫한 섹터
    "AI/반도체": 8,
    "전기차/2차전지": 5,
    "바이오/헬스케어": 5,
    "자율주행": 5,
    "방산/우주항공": 5,
    "양자컴퓨팅": 3,
    "원자력/SMR": 3,
}

# 뉴스 노출 빈도에 따른 보너스
NEWS_COUNT_BONUS = {
    50: 10,   # 50건 이상 노출 → +10점
    30: 7,    # 30건 이상 → +7점
    20: 5,    # 20건 이상 → +5점
    10: 3,    # 10건 이상 → +3점
    5: 1,     # 5건 이상 → +1점
}

# 급부상 키워드 매칭 보너스
TRENDING_KEYWORD_BONUS = 5  # 급부상 키워드 매칭 시 +5점


def get_keyword_bonus(stock_code: str, analyzer=None) -> tuple[float, list[str]]:
    """
    키워드 분석 결과를 기반으로 보너스 점수 계산
    
    Returns:
        (bonus_score, reasons)
    """
    if analyzer is None:
        return 0.0, []
    
    try:
        results = analyzer.analyze(days=7)
        
        bonus = 0.0
        reasons = []
        
        # 시그널 종목 찾기
        for signal in results['시그널_종목']:
            if signal.stock_code == stock_code:
                # 섹터 보너스
                sector_bonus = SECTOR_BONUS.get(signal.sector, 0)
                if sector_bonus > 0:
                    bonus += sector_bonus
                    reasons.append(f"주도섹터({signal.sector})+{sector_bonus}")
                
                # 뉴스 빈도 보너스
                for threshold, pts in sorted(NEWS_COUNT_BONUS.items(), reverse=True):
                    if signal.news_count >= threshold:
                        bonus += pts
                        reasons.append(f"뉴스노출{signal.news_count}건+{pts}")
                        break
                
                break
        
        return min(bonus, 20.0), reasons  # 최대 20점 제한
        
    except Exception as e:
        return 0.0, [f"분석에러: {e}"]
