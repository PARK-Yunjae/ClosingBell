"""매매일지 자동화 서비스 v10.1

holdings_sync 변화 감지 → trade_journal 자동 기록
시그널 출처 자동 연결 (TOP5/눌림목/유목민/수동)
주간 리포트 생성

사용:
    from src.services.trade_journal_service import record_trade_changes, generate_weekly_report
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.infrastructure.database import get_database

logger = logging.getLogger(__name__)


# ============================================================
# 시그널 출처 탐색
# ============================================================

def find_signal_source(stock_code: str, trade_date: date) -> Tuple[str, Optional[int]]:
    """매수 종목의 시그널 출처를 자동 탐색
    
    최근 5일 이내 시그널에서 검색:
    1. closing_top5_history (TOP5 스크리닝)
    2. pullback_signals (눌림목 거감음봉)
    3. nomad_candidates (유목민 수집)
    4. 없으면 "수동"
    
    Returns:
        (source_label, screening_item_id)
    """
    db = get_database()
    cutoff = (trade_date - timedelta(days=5)).isoformat()
    
    # 1. TOP5 스크리닝
    row = db.fetch_one(
        "SELECT id, screen_date, rank, grade, screen_score "
        "FROM closing_top5_history "
        "WHERE stock_code = ? AND screen_date >= ? "
        "ORDER BY screen_date DESC LIMIT 1",
        (stock_code, cutoff),
    )
    if row:
        rank = row["rank"]
        grade = row.get("grade", "?")
        score = row.get("screen_score", 0)
        return f"TOP5 #{rank} ({grade}등급 {score:.0f}점)", row["id"]
    
    # 2. 눌림목 시그널
    row = db.fetch_one(
        "SELECT id, signal_date, signal_strength, spike_date "
        "FROM pullback_signals "
        "WHERE stock_code = ? AND signal_date >= ? "
        "ORDER BY signal_date DESC LIMIT 1",
        (stock_code, cutoff),
    )
    if row:
        strength = row.get("signal_strength", "?")
        return f"눌림목 {strength} (폭발:{row.get('spike_date', '?')})", None
    
    # 3. 유목민 후보
    row = db.fetch_one(
        "SELECT id, study_date, reason_flag "
        "FROM nomad_candidates "
        "WHERE stock_code = ? AND study_date >= ? "
        "ORDER BY study_date DESC LIMIT 1",
        (stock_code, cutoff),
    )
    if row:
        reason = row.get("reason_flag", "?")
        return f"유목민 ({reason})", None
    
    return "수동", None


# ============================================================
# 매매 기록
# ============================================================

def record_trade_changes(
    prev_holdings: Dict[str, Dict],
    curr_holdings: Dict[str, Dict],
    trade_date: Optional[date] = None,
) -> List[Dict]:
    """보유종목 변화를 감지하여 trade_journal에 자동 기록
    
    Args:
        prev_holdings: {code: {name, qty, price}} 이전 상태
        curr_holdings: {code: {name, qty, price}} 현재 상태
        trade_date: 거래일 (기본: 오늘)
    
    Returns:
        기록된 거래 목록
    """
    db = get_database()
    today = trade_date or date.today()
    now = datetime.now().isoformat(timespec="seconds")
    trades = []
    
    prev_codes = set(prev_holdings.keys())
    curr_codes = set(curr_holdings.keys())
    
    # 1. 신규 매수 (없던 종목 등장)
    for code in curr_codes - prev_codes:
        item = curr_holdings[code]
        qty = item.get("qty", 0)
        price = item.get("price", 0)
        name = item.get("name", code)
        
        source, screening_id = find_signal_source(code, today)
        
        trade = {
            "trade_date": today.isoformat(),
            "stock_code": code,
            "stock_name": name,
            "trade_type": "BUY",
            "price": int(price),
            "quantity": int(qty),
            "total_amount": int(price * qty),
            "holding_quantity": int(qty),
            "return_rate": 0.0,
            "screening_item_id": screening_id,
            "memo": f"[자동] {source}",
        }
        _insert_journal(db, trade, now)
        trades.append(trade)
        logger.info(f"[매매일지] 매수 기록: {name} {qty}주 @{price:,}원 | {source}")
    
    # 2. 추가 매수 (수량 증가)
    for code in curr_codes & prev_codes:
        prev_qty = prev_holdings[code].get("qty", 0)
        curr_qty = curr_holdings[code].get("qty", 0)
        curr_price = curr_holdings[code].get("price", 0)
        name = curr_holdings[code].get("name", code)
        
        if curr_qty > prev_qty:
            added = curr_qty - prev_qty
            trade = {
                "trade_date": today.isoformat(),
                "stock_code": code,
                "stock_name": name,
                "trade_type": "BUY",
                "price": int(curr_price),
                "quantity": int(added),
                "total_amount": int(curr_price * added),
                "holding_quantity": int(curr_qty),
                "return_rate": 0.0,
                "screening_item_id": None,
                "memo": f"[자동] 추가매수 ({prev_qty}→{curr_qty}주)",
            }
            _insert_journal(db, trade, now)
            trades.append(trade)
            logger.info(f"[매매일지] 추가매수: {name} +{added}주 @{curr_price:,}원")
        
        elif curr_qty < prev_qty:
            # 3. 부분 매도 (수량 감소)
            sold = prev_qty - curr_qty
            prev_price = prev_holdings[code].get("price", 0)
            ret = ((curr_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
            
            trade = {
                "trade_date": today.isoformat(),
                "stock_code": code,
                "stock_name": name,
                "trade_type": "SELL",
                "price": int(curr_price),
                "quantity": int(sold),
                "total_amount": int(curr_price * sold),
                "holding_quantity": int(curr_qty),
                "return_rate": round(ret, 2),
                "screening_item_id": None,
                "memo": f"[자동] 부분매도 ({prev_qty}→{curr_qty}주) {ret:+.1f}%",
            }
            _insert_journal(db, trade, now)
            trades.append(trade)
            logger.info(f"[매매일지] 부분매도: {name} -{sold}주 @{curr_price:,}원 ({ret:+.1f}%)")
    
    # 4. 전량 매도 (종목 사라짐)
    for code in prev_codes - curr_codes:
        item = prev_holdings[code]
        qty = item.get("qty", 0)
        price = item.get("price", 0)
        name = item.get("name", code)
        
        trade = {
            "trade_date": today.isoformat(),
            "stock_code": code,
            "stock_name": name,
            "trade_type": "SELL",
            "price": int(price),
            "quantity": int(qty),
            "total_amount": int(price * qty),
            "holding_quantity": 0,
            "return_rate": 0.0,  # 정확한 수익률은 매수가 기준 필요
            "screening_item_id": None,
            "memo": "[자동] 전량매도",
        }
        _insert_journal(db, trade, now)
        trades.append(trade)
        logger.info(f"[매매일지] 전량매도: {name} {qty}주 @{price:,}원")
    
    return trades


def _insert_journal(db, trade: Dict, now: str):
    """trade_journal 테이블에 INSERT"""
    db.execute(
        "INSERT INTO trade_journal "
        "(trade_date, stock_code, stock_name, trade_type, price, quantity, "
        "total_amount, holding_quantity, return_rate, screening_item_id, memo, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trade["trade_date"],
            trade["stock_code"],
            trade["stock_name"],
            trade["trade_type"],
            trade["price"],
            trade["quantity"],
            trade["total_amount"],
            trade["holding_quantity"],
            trade["return_rate"],
            trade["screening_item_id"],
            trade["memo"],
            now, now,
        ),
    )


# ============================================================
# 매매일지 조회
# ============================================================

def get_journal_entries(
    days: int = 30,
    trade_type: Optional[str] = None,
) -> List[Dict]:
    """매매일지 조회"""
    db = get_database()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    
    if trade_type:
        rows = db.fetch_all(
            "SELECT * FROM trade_journal WHERE trade_date >= ? AND trade_type = ? "
            "ORDER BY trade_date DESC, id DESC",
            (cutoff, trade_type),
        )
    else:
        rows = db.fetch_all(
            "SELECT * FROM trade_journal WHERE trade_date >= ? "
            "ORDER BY trade_date DESC, id DESC",
            (cutoff,),
        )
    return [dict(r) for r in rows]


def get_journal_stats(days: int = 30) -> Dict:
    """매매 통계"""
    db = get_database()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    
    sells = db.fetch_all(
        "SELECT return_rate, total_amount FROM trade_journal "
        "WHERE trade_date >= ? AND trade_type = 'SELL' AND return_rate != 0",
        (cutoff,),
    )
    
    if not sells:
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "avg_return": 0, "total_pnl": 0}
    
    returns = [s["return_rate"] for s in sells]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    
    return {
        "total_trades": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(returns) * 100 if returns else 0,
        "avg_return": sum(returns) / len(returns) if returns else 0,
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "total_pnl": sum(s["return_rate"] * s["total_amount"] / 100 for s in sells),
        # 손익비: 평균 익절 / |평균 손절| (1 이상이면 돈을 벌 수 있는 구조)
        "profit_loss_ratio": (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
            if wins and losses else 0,
        # 기대값: (승률 × 평균익절) + (패률 × 평균손절)
        "expected_value": (
            (len(wins) / len(returns)) * (sum(wins) / len(wins))
            + (len(losses) / len(returns)) * (sum(losses) / len(losses))
        ) if wins and losses else 0,
        # Profit Factor: 총 수익 / |총 손실|
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else 0,
    }


# ============================================================
# 시그널 출처별 손익비 분석
# ============================================================

def get_signal_source_stats(days: int = 90) -> List[Dict]:
    """시그널 출처별 손익비 분석 — '어디서 돈을 버는가'
    
    Returns:
        [{source, trades, win_rate, avg_win, avg_loss, 
          profit_loss_ratio, expected_value, total_pnl}]
    """
    db = get_database()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    
    sells = db.fetch_all(
        "SELECT memo, return_rate, total_amount FROM trade_journal "
        "WHERE trade_date >= ? AND trade_type = 'SELL' AND return_rate != 0",
        (cutoff,),
    )
    
    if not sells:
        return []
    
    # 시그널 출처 그룹핑 (TOP5/눌림목/유목민/수동)
    from collections import defaultdict
    groups = defaultdict(list)
    for s in sells:
        memo = s["memo"] or ""
        # memo에서 대분류로 매핑
        if "TOP5" in memo:
            key = "TOP5"
        elif "눌림목" in memo:
            key = "눌림목"
        elif "유목민" in memo:
            key = "유목민"
        else:
            key = "수동"
        groups[key].append(s["return_rate"])
    
    results = []
    for source, returns in groups.items():
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        
        avg_w = sum(wins) / len(wins) if wins else 0
        avg_l = sum(losses) / len(losses) if losses else 0
        
        results.append({
            "source": source,
            "trades": len(returns),
            "win_rate": len(wins) / len(returns) * 100 if returns else 0,
            "avg_win": avg_w,
            "avg_loss": avg_l,
            "profit_loss_ratio": avg_w / abs(avg_l) if avg_l else 0,
            "expected_value": (
                (len(wins) / len(returns)) * avg_w
                + (len(losses) / len(returns)) * avg_l
            ) if returns else 0,
            "total_pnl": sum(returns),
        })
    
    # 기대값 높은 순 정렬
    results.sort(key=lambda x: x["expected_value"], reverse=True)
    return results


# ============================================================
# 주간 리포트
# ============================================================

def generate_weekly_report(target_date: Optional[date] = None) -> str:
    """주간 매매 리포트 생성
    
    Args:
        target_date: 기준일 (기본: 오늘, 해당 주의 월~금)
    
    Returns:
        마크다운 형식 리포트
    """
    today = target_date or date.today()
    
    # 이번 주 월~금
    weekday = today.weekday()
    monday = today - timedelta(days=weekday)
    friday = monday + timedelta(days=4)
    
    db = get_database()
    
    # 이번 주 매매 내역
    trades = db.fetch_all(
        "SELECT * FROM trade_journal "
        "WHERE trade_date >= ? AND trade_date <= ? "
        "ORDER BY trade_date ASC, id ASC",
        (monday.isoformat(), friday.isoformat()),
    )
    trades = [dict(r) for r in trades]
    
    # 현재 보유종목
    holdings = db.fetch_all(
        "SELECT * FROM holdings_watch WHERE status = 'holding' ORDER BY last_seen DESC"
    )
    holdings = [dict(r) for r in holdings]
    
    # 누적 통계 (최근 30일)
    stats = get_journal_stats(30)
    
    # 시그널 매칭 통계
    buys = [t for t in trades if t["trade_type"] == "BUY"]
    sells = [t for t in trades if t["trade_type"] == "SELL"]
    
    source_counts = {}
    for t in buys:
        memo = t.get("memo", "")
        if "TOP5" in memo:
            source_counts["TOP5"] = source_counts.get("TOP5", 0) + 1
        elif "눌림목" in memo:
            source_counts["눌림목"] = source_counts.get("눌림목", 0) + 1
        elif "유목민" in memo:
            source_counts["유목민"] = source_counts.get("유목민", 0) + 1
        else:
            source_counts["수동"] = source_counts.get("수동", 0) + 1
    
    # 리포트 생성
    lines = [
        f"# 📊 주간 매매 리포트",
        f"**{monday.strftime('%Y-%m-%d')} ~ {friday.strftime('%Y-%m-%d')}**",
        f"",
        f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
    ]
    
    # 매수 내역
    lines.append("## 📈 매수")
    if buys:
        for t in buys:
            source = t.get("memo", "").replace("[자동] ", "")
            lines.append(
                f"- **{t['stock_name']}** {t['quantity']:,}주 @{t['price']:,}원 "
                f"| 출처: {source}"
            )
    else:
        lines.append("- 이번 주 매수 없음")
    
    lines.append("")
    
    # 매도 내역
    lines.append("## 📉 매도")
    if sells:
        for t in sells:
            ret = t.get("return_rate", 0)
            emoji = "🟢" if ret > 0 else "🔴" if ret < 0 else "⚪"
            lines.append(
                f"- {emoji} **{t['stock_name']}** {t['quantity']:,}주 @{t['price']:,}원 "
                f"({ret:+.1f}%)"
            )
    else:
        lines.append("- 이번 주 매도 없음")
    
    lines.append("")
    
    # 현재 보유
    lines.append("## 💼 현재 보유")
    if holdings:
        for h in holdings:
            qty = h.get("last_qty", 0)
            price = h.get("last_price", 0)
            first = h.get("first_seen", "")[:10]
            holding_days = (today - date.fromisoformat(first)).days if first else 0
            lines.append(
                f"- **{h['stock_name']}** {qty:,}주 @{price:,.0f}원 "
                f"| 보유 {holding_days}일째"
            )
    else:
        lines.append("- 보유종목 없음")
    
    lines.append("")
    
    # 시그널 출처별 매수
    if source_counts:
        lines.append("## 🎯 시그널 출처별 매수")
        for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {src}: {cnt}건")
        lines.append("")
    
    # 누적 성과
    lines.append("## 📈 최근 30일 누적 성과")
    if stats["total_trades"] > 0:
        lines.append(
            f"- {stats['wins']}승 {stats['losses']}패 "
            f"(승률 {stats['win_rate']:.0f}%)"
        )
        lines.append(f"- 평균 수익률: {stats['avg_return']:+.1f}%")
        if stats.get("avg_win"):
            lines.append(f"- 평균 익절: {stats['avg_win']:+.1f}%")
        if stats.get("avg_loss"):
            lines.append(f"- 평균 손절: {stats['avg_loss']:+.1f}%")
    else:
        lines.append("- 매도 기록 없음 (수익률 집계 불가)")
    
    # 핵심 지표: 돈을 버는 구조인가?
    if stats["total_trades"] > 0:
        lines.append("")
        lines.append("## 💰 핵심: 돈을 버는 구조인가?")
        plr = stats.get("profit_loss_ratio", 0)
        ev = stats.get("expected_value", 0)
        pf = stats.get("profit_factor", 0)
        lines.append(f"- 손익비 (R:R): **{plr:.2f}** {'✅' if plr >= 1 else '⚠️'}")
        lines.append(f"- 기대값 (EV): **{ev:+.2f}%** {'✅' if ev > 0 else '⚠️'}")
        lines.append(f"- Profit Factor: **{pf:.2f}** {'✅' if pf >= 1.5 else '⚠️' if pf >= 1 else '❌'}")
        lines.append(f"- 총 실현손익: {stats['total_pnl']:+,.0f}원")
    
    return "\n".join(lines)


# ============================================================
# 디스코드 알림
# ============================================================

def format_trade_discord(trades: List[Dict]) -> str:
    """거래 내역을 디스코드 메시지로 포맷"""
    if not trades:
        return ""
    
    lines = ["📝 **매매일지 자동 기록**", ""]
    
    for t in trades:
        emoji = "🟢" if t["trade_type"] == "BUY" else "🔴"
        source = t.get("memo", "").replace("[자동] ", "")
        ret_str = f" ({t['return_rate']:+.1f}%)" if t.get("return_rate") else ""
        
        lines.append(
            f"{emoji} **{t['stock_name']}** "
            f"{t['trade_type']} {t['quantity']:,}주 @{t['price']:,}원"
            f"{ret_str}"
        )
        if source:
            lines.append(f"   └ {source}")
    
    return "\n".join(lines)
