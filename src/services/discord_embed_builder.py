"""
Discord Embed Builder v8.0

웹훅 메시지 생성 통합 모듈

v8.0 변경:
- 기술지표 나열 제거 → 가격+시총+DART+AI만
- 점수/등급 표시 제거
- 매도전략, 보너스태그, PER/PBR 제거
- 타이틀: "감시종목 TOP5"
"""

import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass

from src.config.constants import get_top_n_count

logger = logging.getLogger(__name__)


# ============================================================
# 상수
# ============================================================

# ★ P0-D: Discord 제한 (완전 대응)
DISCORD_FIELD_VALUE_LIMIT = 1024   # 필드 value 최대 길이
DISCORD_FIELD_NAME_LIMIT = 256    # 필드 name 최대 길이
DISCORD_EMBED_TOTAL_LIMIT = 6000  # Embed 전체 길이 제한
DISCORD_FIELD_COUNT_LIMIT = 25    # 필드 개수 제한
DISCORD_DESCRIPTION_LIMIT = 4096  # Description 제한

# 등급 이모지
GRADE_EMOJI = {
    "S": "🏆",
    "A": "🥇",
    "B": "🥈",
    "C": "🥉",
    "D": "⚠️",
}

# AI 추천 이모지
REC_EMOJI = {
    "매수": "🟢",
    "관망": "🟡",
    "매도": "🔴",
}

# 위험도 이모지
RISK_EMOJI = {
    "낮음": "✅",
    "보통": "⚠️",
    "높음": "🚫",
}

# 색상
COLORS = {
    "success": 0x2ECC71,   # 녹색
    "warning": 0xF1C40F,   # 노랑
    "danger": 0xE74C3C,    # 빨강
    "info": 0x3498DB,      # 파랑
    "default": 0x7289DA,   # 디스코드 기본
}

# ★ 순위 이모지 (가시성 개선)
RANK_EMOJI = {
    1: "🔥1위🔥",
    2: "⭐2위",
    3: "✨3위",
    4: "4️⃣",
    5: "5️⃣",
}

# ============================================================
# Embed Builder
# ============================================================

class DiscordEmbedBuilder:
    """Discord Embed 생성기"""
    
    def __init__(self, version: str = "v7.0"):
        self.version = version
    
    def _truncate(self, text: str, max_length: int = DISCORD_FIELD_VALUE_LIMIT, suffix: str = "...") -> str:
        """텍스트 길이 제한 (Discord 제한 대응)
        
        Args:
            text: 원본 텍스트
            max_length: 최대 길이 (기본 1024)
            suffix: 잘릴 때 추가할 접미사
            
        Returns:
            잘린 텍스트 (max_length 이하)
        """
        if not text:
            return ""
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix
    
    def _format_market_cap(self, value: float) -> str:
        """시가총액 포맷"""
        if not value:
            return "-"
        if value >= 10000:
            return f"{value/10000:.1f}조"
        return f"{value:,.0f}억"
    
    def _format_trading_value(self, value: float) -> str:
        """거래대금 포맷"""
        if not value:
            return "-"
        if value >= 1000:
            return f"{value/1000:.1f}조"
        return f"{value:,.0f}억"
    
    def _format_volume(self, value: int) -> str:
        """거래량(주) 포맷 (만주 단위 통일)"""
        if not value:
            return "-"
        if value >= 100000000:  # 1억주 이상
            return f"{value/100000000:.1f}억주"
        if value >= 10000:      # 만주 이상
            return f"{value/10000:.0f}만주"  # 700만주, 1000만주 형태
        return f"{value:,}주"
    
    def _get_grade_value(self, grade) -> str:
        """등급 값 추출 (Enum 또는 문자열)
        
        처리 케이스:
        - StockGrade.S (Enum 객체) → 'S'
        - 'StockGrade.S' (문자열) → 'S'
        - 'S' (문자열) → 'S'
        - None → '-'
        """
        if grade is None:
            return "-"
        
        # Enum인 경우 (hasattr로 체크)
        if hasattr(grade, 'value'):
            val = grade.value
            # value가 또 객체면 str로 변환 후 처리
            val_str = str(val)
            if 'StockGrade.' in val_str:
                return val_str.split('.')[-1]
            return val_str
        
        # 문자열인 경우
        grade_str = str(grade)
        
        # 'StockGrade.S' 형태 처리
        if 'StockGrade.' in grade_str:
            return grade_str.split('.')[-1]
        
        # '<StockGrade.S: 'S'>' 형태 처리 (repr)
        if '<StockGrade.' in grade_str:
            # S, A, B, C, D 중 하나 추출
            for g in ['S', 'A', 'B', 'C', 'D']:
                if f'.{g}' in grade_str or f"'{g}'" in grade_str:
                    return g
        
        return grade_str
    
    # ============================================================
    # TOP5 Embed (메인)
    # ============================================================
    
    def build_top5_embed(
        self,
        stocks: List[Any],
        title: str = "종가매매 TOP5",
        leading_sectors_text: str = None,
        ai_results: Dict[str, Dict] = None,
        run_type: str = "main",  # main / preview
        max_stocks: int = None,  # ★ P0-B: 최대 종목 수 (None이면 설정에서)
    ) -> Dict:
        """TOP5 웹훅 Embed 생성
        
        Args:
            stocks: EnrichedStock 또는 StockScoreV5 리스트
            title: Embed 제목
            leading_sectors_text: 주도섹터 텍스트
            ai_results: AI 분석 결과 {stock_code: {recommendation, risk_level, summary}}
            run_type: 실행 타입 (main: 15:00, preview: 12:00)
            max_stocks: 최대 종목 수 (None이면 설정에서 가져옴)
        
        Returns:
            Discord Embed 딕셔너리
        """
        # ★ P0-B: TOP_N_COUNT 설정 통일
        top_n = max_stocks if max_stocks else get_top_n_count()
        
        fields = []
        
        # 타이틀 수정 (preview 모드)
        if run_type == "preview":
            title = f"🔮 {title} (프리뷰)"
            color = COLORS["info"]
        else:
            title = f"🔔 {title}"
            color = COLORS["success"]
        
        # 주도섹터 정보 (맨 위에 표시)
        if leading_sectors_text:
            fields.append({
                "name": "📈 오늘의 주도섹터",
                "value": leading_sectors_text,
                "inline": False,
            })
        
        for i, stock in enumerate(stocks[:top_n], 1):
            field = self._build_stock_field(stock, i, ai_results)
            fields.append(field)
        
        # 등급 설명
        legend = self._build_grade_legend()
        fields.append({
            "name": "📋 등급별 매도전략",
            "value": legend,
            "inline": False,
        })
        
        # AI 범례 (AI 결과가 있을 때만)
        if ai_results:
            fields.append({
                "name": "🤖 AI 추천 범례",
                "value": "🟢매수 | 🟡관망 | 🔴매도 | ✅위험낮음 | ⚠️위험보통 | 🚫위험높음",
                "inline": False,
            })
        
        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"ClosingBell {self.version} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            }
        }
        
        # ★ P0-D: Embed 총량 제한 체크 및 축약
        embed = self._enforce_embed_limits(embed)
        
        return embed
    
    def _enforce_embed_limits(self, embed: Dict) -> Dict:
        """★ P0-D: Discord Embed 제한 강제 적용
        
        우선순위 (낮을수록 먼저 축약됨):
        1. 뉴스 헤드라인 (가장 먼저 축약)
        2. DART 위험공시 (그 다음)
        3. 핵심지표 (유지)
        4. AI 추천/요약 (유지)
        5. 점수/등급 (절대 유지)
        """
        # 총 길이 계산
        total_length = len(embed.get('title', ''))
        total_length += len(embed.get('description', ''))
        
        for field in embed.get('fields', []):
            total_length += len(field.get('name', ''))
            total_length += len(field.get('value', ''))
        
        total_length += len(embed.get('footer', {}).get('text', ''))
        
        # 필드 개수 체크
        if len(embed.get('fields', [])) > DISCORD_FIELD_COUNT_LIMIT:
            logger.warning(f"Embed 필드 개수 초과: {len(embed['fields'])} > {DISCORD_FIELD_COUNT_LIMIT}")
            embed['fields'] = embed['fields'][:DISCORD_FIELD_COUNT_LIMIT]
        
        # 총량 제한 체크
        if total_length > DISCORD_EMBED_TOTAL_LIMIT:
            logger.warning(f"Embed 총량 초과: {total_length} > {DISCORD_EMBED_TOTAL_LIMIT}, 축약 시작")
            
            # 각 필드 value를 점진적으로 축약
            target_length = DISCORD_EMBED_TOTAL_LIMIT - 500  # 여유분
            
            for field in embed.get('fields', []):
                value = field.get('value', '')
                
                # 긴 필드부터 축약 (우선순위 기반)
                if len(value) > 400:
                    # 뉴스/DART 정보는 더 공격적으로 축약
                    if '뉴스' in field.get('name', '') or 'DART' in field.get('name', ''):
                        field['value'] = self._truncate(value, 200)
                    else:
                        field['value'] = self._truncate(value, 500)
            
            # 다시 계산
            total_length = len(embed.get('title', ''))
            for field in embed.get('fields', []):
                total_length += len(field.get('name', '')) + len(field.get('value', ''))
            
            if total_length > DISCORD_EMBED_TOTAL_LIMIT:
                # 마지막 수단: 필드 제거 (등급 범례, AI 범례 제거)
                embed['fields'] = [
                    f for f in embed['fields'] 
                    if '범례' not in f.get('name', '')
                ]
                logger.warning(f"범례 필드 제거 후 총량: {total_length}")
        
        return embed
    
    def _build_stock_field(
        self, 
        stock: Any, 
        rank: int, 
        ai_results: Dict[str, Dict] = None
    ) -> Dict:
        """개별 종목 필드 생성 - v8.0 심플화"""
        
        # 기본 정보 추출 (StockScoreV5 또는 EnrichedStock 호환)
        stock_code = getattr(stock, 'stock_code', '') or getattr(stock, 'code', '')
        stock_name = getattr(stock, 'stock_name', '') or getattr(stock, 'name', '')
        
        # 가격 정보
        current_price = getattr(stock, 'current_price', 0) or getattr(stock, 'screen_price', 0)
        change_rate = getattr(stock, 'change_rate', 0)
        market_cap = getattr(stock, 'market_cap', 0) or getattr(stock, '_market_cap', 0)
        
        # ============================================================
        # v8.0: 심플 필드 구성 (가격 + 시총 + DART + AI만)
        # ============================================================
        
        field_value = f"현재가: {current_price:,}원 ({change_rate:+.1f}%) | 시총: {self._format_market_cap(market_cap)}"

        # v9.0: ???(Volume Profile) ? ? ??
        detail = getattr(stock, 'score_detail', None)
        if detail and getattr(detail, 'raw_vp_tag', ''):
            vp_tag = getattr(detail, 'raw_vp_tag', '')
            vp_emoji = {"????": "??", "??": "??", "???": "??", "?????": "?", "??": "?"}.get(vp_tag, "?")
            vp_score = getattr(detail, 'raw_vp_score', 0.0)
            vp_above = getattr(detail, 'raw_vp_above_pct', 0.0)
            vp_below = getattr(detail, 'raw_vp_below_pct', 0.0)
            field_value += f"\n{vp_emoji} ??? {vp_score:.0f}? [{vp_tag}] ?:{vp_above:.0f}%/??:{vp_below:.0f}%"
        
        # DART 공시 (위험/주의만)
        dart_text = ""
        risk_obj = getattr(stock, 'risk', None)
        if risk_obj:
            dart_items = getattr(risk_obj, 'items', [])
            if getattr(risk_obj, 'has_critical_risk', False):
                dart_text = "\n━━━━━━━━━━\n📋 **DART 공시**\n🚫 위험 공시 발견!"
                if dart_items:
                    item = dart_items[0]
                    title = getattr(item, 'title', '')
                    date = getattr(item, 'date', '')
                    if title:
                        if len(title) > 40:
                            title = title[:37] + "..."
                        dart_text += f"\n⚠️ {title} ({date})"
            elif getattr(risk_obj, 'has_high_risk', False):
                dart_text = "\n━━━━━━━━━━\n📋 **DART 공시**\n⚠️ 주의 공시"
                if dart_items:
                    item = dart_items[0]
                    title = getattr(item, 'title', '')
                    date = getattr(item, 'date', '')
                    if title:
                        if len(title) > 40:
                            title = title[:37] + "..."
                        dart_text += f"\n⚠️ {title} ({date})"
        
        field_value += dart_text
        
        # AI 분석 결과
        if ai_results and stock_code in ai_results:
            ai = ai_results[stock_code]
            rec = ai.get('recommendation', '관망')
            risk = ai.get('risk_level', '보통')
            summary = ai.get('summary', '')
            
            field_value += (
                f"\n━━━━━━━━━━\n🤖 **AI 분석**\n"
                f"추천: {REC_EMOJI.get(rec, '❓')} {rec} | "
                f"위험도: {RISK_EMOJI.get(risk, '❓')} {risk}"
            )
            if summary:
                if len(summary) > 80:
                    summary = summary[:77] + "..."
                field_value += f"\n💡 {summary}"
        
        # 길이 제한 적용
        field_value = self._truncate(field_value, DISCORD_FIELD_VALUE_LIMIT)
        
        return {
            "name": self._truncate(f"{RANK_EMOJI.get(rank, f'#{rank}')} **{stock_name}** ({stock_code})", DISCORD_FIELD_NAME_LIMIT),
            "value": field_value,
            "inline": False,
        }
    
    def _build_grade_legend(self) -> str:
        """등급 설명 텍스트 - v8.0 제거"""
        return ""
    
    # ============================================================
    # TOP5 Compact Embed (간략 버전)
    # ============================================================
    
    def build_top5_compact(
        self,
        stocks: List[Any],
        ai_results: Dict[str, Dict] = None,
        title: str = "종가매매 TOP5",
        max_stocks: int = None,  # ★ P0-B
    ) -> Dict:
        """TOP5 간략 Embed (모바일 친화적)"""
        
        # ★ P0-B: TOP_N_COUNT 설정 통일
        top_n = max_stocks if max_stocks else get_top_n_count()
        
        lines = []
        for i, stock in enumerate(stocks[:top_n], 1):
            stock_code = getattr(stock, 'stock_code', '')
            stock_name = getattr(stock, 'stock_name', '')
            score = getattr(stock, 'score_total', 0) or getattr(stock, 'screen_score', 0)
            grade = self._get_grade_value(getattr(stock, 'grade', '-'))
            change = getattr(stock, 'change_rate', 0)
            
            # AI 추천
            rec_str = ""
            if ai_results and stock_code in ai_results:
                rec = ai_results[stock_code].get('recommendation', '')
                rec_str = f" {REC_EMOJI.get(rec, '')}"
            
            line = f"**{i}. {stock_name}** {GRADE_EMOJI.get(grade, '')}{grade} ({score:.0f}점) {change:+.1f}%{rec_str}"
            lines.append(line)
        
        return {
            "title": f"🔔 {title}",
            "description": "\n".join(lines),
            "color": COLORS["success"],
            "footer": {
                "text": f"ClosingBell {self.version}"
            }
        }
    
    # ============================================================
    # 유목민 공부법 Embed
    # ============================================================
    
    def build_nomad_embed(
        self,
        candidates: List[Dict],
        study_date: str,
        summary: Dict = None,
    ) -> Dict:
        """유목민 공부법 웹훅 Embed"""
        
        fields = []
        
        # 요약 정보
        if summary:
            fields.append({
                "name": "📊 오늘의 요약",
                "value": (
                    f"상한가: **{summary.get('limit_up', 0)}개** | "
                    f"거래량천만: **{summary.get('volume_explosion', 0)}개** | "
                    f"총: **{summary.get('total', 0)}개**"
                ),
                "inline": False,
            })
        
        # 상한가 종목
        limit_ups = [c for c in candidates if '상한가' in c.get('reason_flag', '')][:5]
        if limit_ups:
            lu_lines = []
            for c in limit_ups:
                lu_lines.append(f"• **{c['stock_name']}** ({c['stock_code']}) +{c.get('change_rate', 0):.1f}%")
            
            fields.append({
                "name": "🚀 상한가",
                "value": "\n".join(lu_lines),
                "inline": True,
            })
        
        # 거래량 폭발 종목
        vol_explosions = [c for c in candidates if '거래량' in c.get('reason_flag', '')][:5]
        if vol_explosions:
            ve_lines = []
            for c in vol_explosions:
                ve_lines.append(f"• **{c['stock_name']}** ({c['stock_code']}) {c.get('trading_value', 0):.0f}억")
            
            fields.append({
                "name": "💰 거래량 폭발",
                "value": "\n".join(ve_lines),
                "inline": True,
            })
        
        return {
            "title": f"📚 유목민 공부법 - {study_date}",
            "color": COLORS["warning"],
            "fields": fields,
            "footer": {
                "text": f"ClosingBell {self.version}"
            }
        }
    
    # ============================================================
    # 일반 알림 Embed
    # ============================================================
    
    def build_alert_embed(
        self,
        title: str,
        message: str,
        alert_type: str = "info",  # info, success, warning, danger
        fields: List[Dict] = None,
    ) -> Dict:
        """일반 알림 Embed"""
        
        embed = {
            "title": title,
            "description": message,
            "color": COLORS.get(alert_type, COLORS["default"]),
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": f"ClosingBell {self.version}"
            }
        }
        
        if fields:
            embed["fields"] = fields
        
        return embed


# ============================================================
# 편의 함수 (기존 코드 호환용)
# ============================================================

def format_discord_embed(
    scores: List,
    title: str = "종가매매 TOP5",
    leading_sectors_text: str = None,
) -> Dict:
    """기존 format_discord_embed 호환 함수"""
    builder = DiscordEmbedBuilder()
    return builder.build_top5_embed(
        stocks=scores,
        title=title,
        leading_sectors_text=leading_sectors_text,
    )


def format_discord_embed_with_ai(
    scores: List,
    title: str = "종가매매 TOP5",
    leading_sectors_text: str = None,
    ai_results: Dict[str, Dict] = None,
) -> Dict:
    """기존 format_discord_embed_with_ai 호환 함수"""
    builder = DiscordEmbedBuilder()
    return builder.build_top5_embed(
        stocks=scores,
        title=title,
        leading_sectors_text=leading_sectors_text,
        ai_results=ai_results,
    )


def get_embed_builder() -> DiscordEmbedBuilder:
    """DiscordEmbedBuilder 인스턴스 반환"""
    return DiscordEmbedBuilder()


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    import json
    
    # 테스트용 더미 데이터
    class DummyScoreDetail:
        raw_cci = 165
        raw_distance = 5.2
        raw_volume_ratio = 1.5
        raw_consec_days = 2
        is_cci_rising = True
        is_ma20_3day_up = True
        is_high_eq_close = False
    
    class DummySellStrategy:
        open_sell_ratio = 30
        target_profit = 4
        stop_loss = -3
    
    class DummyStock:
        def __init__(self, code, name, score):
            self.stock_code = code
            self.stock_name = name
            self.score_total = score
            self.grade = 'S' if score >= 85 else 'A'
            self.current_price = 55000
            self.change_rate = 3.5
            self.trading_value = 1500
            self.market_cap = 42000
            self.score_detail = DummyScoreDetail()
            self.sell_strategy = DummySellStrategy()
            self._sector = "반도체"
            self._is_leading_sector = True
            self._sector_rank = 1
    
    # 테스트 데이터
    test_stocks = [
        DummyStock('005930', '삼성전자', 93.5),
        DummyStock('000660', 'SK하이닉스', 88.2),
        DummyStock('035720', '카카오', 82.0),
    ]
    
    ai_results = {
        '005930': {'recommendation': '매수', 'risk_level': '낮음', 'summary': '반도체 슈퍼사이클 수혜'},
        '000660': {'recommendation': '관망', 'risk_level': '보통', 'summary': 'CCI 과열 주의'},
        '035720': {'recommendation': '매도', 'risk_level': '높음', 'summary': '실적 부진 우려'},
    }
    
    print("="*60)
    print("DiscordEmbedBuilder 테스트")
    print("="*60)
    
    builder = DiscordEmbedBuilder()
    
    # 1. TOP5 Embed
    print("\n[1] TOP5 Embed:")
    embed = builder.build_top5_embed(
        test_stocks,
        leading_sectors_text="1. 반도체 (+5.2%) | 2. 2차전지 (+3.1%)",
        ai_results=ai_results,
    )
    print(f"  제목: {embed['title']}")
    print(f"  필드 수: {len(embed['fields'])}")
    
    # 2. Compact Embed
    print("\n[2] Compact Embed:")
    compact = builder.build_top5_compact(test_stocks, ai_results)
    print(f"  제목: {compact['title']}")
    print(f"  내용:\n{compact['description']}")
    
    # 3. 유목민 Embed
    print("\n[3] 유목민 Embed:")
    nomad_candidates = [
        {'stock_code': '001140', 'stock_name': '국보', 'reason_flag': '상한가', 'change_rate': 30.0},
        {'stock_code': '001840', 'stock_name': '이화공영', 'reason_flag': '상한가', 'change_rate': 30.0},
        {'stock_code': '060250', 'stock_name': 'NHN KCP', 'reason_flag': '거래량천만', 'trading_value': 2323},
    ]
    nomad_embed = builder.build_nomad_embed(
        nomad_candidates,
        study_date="2026-01-27",
        summary={'limit_up': 8, 'volume_explosion': 33, 'total': 47}
    )
    print(f"  제목: {nomad_embed['title']}")
    print(f"  필드 수: {len(nomad_embed['fields'])}")
    
    print("\n" + "="*60)
