"""
score_calculator.py의 format_discord_embed 수정 패치

웹훅에 AI 추천(매수/관망/매도) 추가
"""

from typing import List, Optional, Dict
from enum import Enum


class StockGrade(Enum):
    """종목 등급"""
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


def format_discord_embed_with_ai(
    scores: List,  # StockScoreV5 리스트
    title: str = "종가매매 TOP5",
    leading_sectors_text: str = None,
    ai_results: Dict[str, Dict] = None,  # {stock_code: {recommendation, risk_level, summary}}
) -> dict:
    """Discord Embed 포맷 - v6.4 AI 추천 포함
    
    Args:
        scores: TOP5 종목 점수 리스트
        title: Embed 제목
        leading_sectors_text: 주도섹터 텍스트
        ai_results: AI 분석 결과 딕셔너리
            - key: stock_code
            - value: {recommendation: 매수/관망/매도, risk_level: 낮음/보통/높음, summary: 요약}
    """
    grade_emoji = {
        "S": "🏆",
        "A": "🥇",
        "B": "🥈",
        "C": "🥉",
        "D": "⚠️",
    }
    
    # AI 추천 이모지
    rec_emoji = {
        "매수": "🟢",
        "관망": "🟡",
        "매도": "🔴",
    }
    
    risk_emoji = {
        "낮음": "✅",
        "보통": "⚠️",
        "높음": "🚫",
    }
    
    fields = []
    
    # 주도섹터 정보 (맨 위에 표시)
    if leading_sectors_text:
        fields.append({
            "name": "📈 오늘의 주도섹터",
            "value": leading_sectors_text,
            "inline": False,
        })
    
    for i, score in enumerate(scores[:5], 1):
        d = score.score_detail
        s = score.sell_strategy
        
        # 섹터 정보
        sector = getattr(score, '_sector', '')
        is_leading = getattr(score, '_is_leading_sector', False)
        sector_rank = getattr(score, '_sector_rank', 99)
        
        sector_badge = ""
        if sector:
            if is_leading:
                sector_badge = f"🔥 {sector} (#{sector_rank})"
            else:
                sector_badge = f"📁 {sector}"
        
        # 보너스 상태
        bonus_icons = []
        if d.is_cci_rising:
            bonus_icons.append("CCI↑")
        if d.is_ma20_3day_up:
            bonus_icons.append("MA20↑")
        if not d.is_high_eq_close:
            bonus_icons.append("캔들✓")
        bonus_str = " ".join(bonus_icons) if bonus_icons else "-"
        
        # 등급 값 추출 (Enum이면 .value, 아니면 그대로)
        grade_val = score.grade.value if hasattr(score.grade, 'value') else score.grade
        
        # AI 추천 정보 추가
        ai_text = ""
        if ai_results and score.stock_code in ai_results:
            ai = ai_results[score.stock_code]
            rec = ai.get('recommendation', '관망')
            risk = ai.get('risk_level', '보통')
            summary = ai.get('summary', '')
            
            ai_text = (
                f"\n🤖 **AI 분석**\n"
                f"추천: {rec_emoji.get(rec, '❓')} **{rec}** | "
                f"위험도: {risk_emoji.get(risk, '❓')} {risk}\n"
            )
            if summary:
                # 요약이 너무 길면 자르기
                if len(summary) > 80:
                    summary = summary[:77] + "..."
                ai_text += f"💡 {summary}\n"
        
        # 필드 값 구성
        field_value = (
            f"**{score.score_total:.1f}점** {grade_emoji.get(grade_val, '❓')}{grade_val}"
        )
        if sector_badge:
            field_value += f" | {sector_badge}"
        field_value += (
            f"\n현재가: {score.current_price:,}원 ({score.change_rate:+.1f}%)\n"
            f"거래대금: {score.trading_value:.0f}억\n"
            f"━━━━━━━━━━\n"
            f"📊 **핵심지표**\n"
            f"CCI: **{d.raw_cci:.0f}** | 이격도: {d.raw_distance:.1f}%\n"
            f"거래량: {d.raw_volume_ratio:.1f}배 | 연속: {d.raw_consec_days}일\n"
            f"━━━━━━━━━━\n"
            f"🎁 보너스: {bonus_str}"
        )
        
        # AI 분석 추가
        field_value += ai_text
        
        field_value += (
            f"━━━━━━━━━━\n"
            f"📈 **매도전략**\n"
            f"시초가 {s.open_sell_ratio}% / 목표 +{s.target_profit}%\n"
            f"손절 {s.stop_loss}%"
        )
        
        fields.append({
            "name": f"#{i} {score.stock_name} ({score.stock_code})",
            "value": field_value,
            "inline": False,
        })
    
    # 등급 설명
    legend = (
        "```\n"
        "🏆S(85+): 시초30% + 목표+4% (손절-3%)\n"
        "🥇A(75-84): 시초40% + 목표+3% (손절-2.5%)\n"
        "🥈B(65-74): 시초50% + 목표+2.5% (손절-2%)\n"
        "🥉C(55-64): 시초70% + 목표+2% (손절-1.5%)\n"
        "⚠️D(<55): 시초 전량매도 권장 (손절-1%)\n"
        "```"
    )
    
    fields.append({
        "name": "📋 등급별 매도전략",
        "value": legend,
        "inline": False,
    })
    
    # AI 추천 범례 추가
    if ai_results:
        ai_legend = "🟢매수 | 🟡관망 | 🔴매도 | ✅위험낮음 | ⚠️위험보통 | 🚫위험높음"
        fields.append({
            "name": "🤖 AI 추천 범례",
            "value": ai_legend,
            "inline": False,
        })
    
    return {
        "title": f"🔔 {title}",
        "color": 3066993,  # 녹색
        "fields": fields,
        "footer": {
            "text": "ClosingBell v6.4 | AI 분석 by Gemini"
        }
    }
