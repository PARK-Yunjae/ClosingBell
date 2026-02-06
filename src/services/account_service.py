from datetime import datetime
from typing import Dict, List, Optional, Set

from src.adapters.kiwoom_rest_client import get_kiwoom_client
from src.infrastructure.database import get_database


def _parse_int(value: Optional[str]) -> int:
    if value is None:
        return 0
    try:
        return int(str(value).replace(',', '').replace('A', '').strip())
    except ValueError:
        return 0


def _parse_float(value: Optional[str]) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(',', '').strip())
    except ValueError:
        return 0.0


def fetch_account_holdings(qry_tp: str = "1", dmst_stex_tp: str = "KRX") -> Dict[str, List[Dict[str, object]]]:
    """키움 계좌평가잔고내역(kt00018)에서 보유종목 조회."""
    client = get_kiwoom_client()
    data = client.get_account_balance(qry_tp=qry_tp, dmst_stex_tp=dmst_stex_tp)

    items = data.get("acnt_evlt_remn_indv_tot", []) if isinstance(data, dict) else []
    holdings: List[Dict[str, object]] = []
    for item in items:
        code_raw = str(item.get("stk_cd", "")).strip()
        code = code_raw.replace("A", "").strip()
        if not code:
            continue
        holdings.append({
            "code": code,
            "name": str(item.get("stk_nm", "")).strip(),
            "qty": _parse_int(item.get("rmnd_qty")),
            "price": _parse_float(item.get("pur_pric")),
            "cur_price": _parse_float(item.get("cur_prc")),
            "eval_pl": _parse_float(item.get("evltv_prft")),
            "prft_rt": _parse_float(item.get("prft_rt")),
        })

    return {
        "holdings": holdings,
        "summary": {
            "total_pur_amt": _parse_int(data.get("tot_pur_amt")) if isinstance(data, dict) else 0,
            "total_eval_amt": _parse_int(data.get("tot_evlt_amt")) if isinstance(data, dict) else 0,
            "total_eval_pl": _parse_int(data.get("tot_evlt_pl")) if isinstance(data, dict) else 0,
            "total_prft_rt": _parse_float(data.get("tot_prft_rt")) if isinstance(data, dict) else 0.0,
        },
    }


def get_holdings_watchlist(status: Optional[str] = None) -> List[Dict[str, object]]:
    db = get_database()
    if status:
        rows = db.fetch_all(
            "SELECT * FROM holdings_watch WHERE status = ? ORDER BY last_seen DESC",
            (status,),
        )
    else:
        rows = db.fetch_all(
            "SELECT * FROM holdings_watch ORDER BY last_seen DESC"
        )
    return [dict(r) for r in rows]


def add_manual_watch(stock_code: str, stock_name: str = "") -> None:
    db = get_database()
    now = datetime.now().isoformat(timespec="seconds")
    row = db.fetch_one(
        "SELECT stock_code, first_seen FROM holdings_watch WHERE stock_code = ?",
        (stock_code,),
    )
    if row:
        db.execute(
            "UPDATE holdings_watch SET stock_name = ?, updated_at = ? WHERE stock_code = ?",
            (stock_name or row.get("stock_name", ""), now, stock_code),
        )
        return

    db.execute(
        "INSERT INTO holdings_watch (stock_code, stock_name, status, first_seen, last_seen, source, updated_at) "
        "VALUES (?, ?, 'manual', ?, ?, 'manual', ?)",
        (stock_code, stock_name, now, now, now),
    )


def sync_holdings_watchlist() -> Dict[str, object]:
    """현재 보유종목을 누적 관찰 테이블에 반영."""
    db = get_database()
    now = datetime.now().isoformat(timespec="seconds")

    result = fetch_account_holdings()
    holdings = result["holdings"]
    current_codes = {h["code"] for h in holdings}
    changed_codes: Set[str] = set()

    # upsert holding items
    for item in holdings:
        code = item["code"]
        row = db.fetch_one(
            "SELECT stock_code, first_seen, status, last_qty, last_price FROM holdings_watch WHERE stock_code = ?",
            (code,),
        )
        if row:
            prev_status = row.get("status", "")
            prev_qty = int(row.get("last_qty") or 0)
            prev_price = float(row.get("last_price") or 0.0)
            if prev_status != "holding" or prev_qty != item.get("qty", 0) or prev_price != item.get("price", 0.0):
                changed_codes.add(code)
            db.execute(
                "UPDATE holdings_watch SET stock_name = ?, status = 'holding', last_seen = ?, "
                "last_qty = ?, last_price = ?, updated_at = ? WHERE stock_code = ?",
                (
                    item.get("name", ""),
                    now,
                    item.get("qty", 0),
                    item.get("price", 0.0),
                    now,
                    code,
                ),
            )
        else:
            changed_codes.add(code)
            db.execute(
                "INSERT INTO holdings_watch (stock_code, stock_name, status, first_seen, last_seen, "
                "last_qty, last_price, source, updated_at) VALUES (?, ?, 'holding', ?, ?, ?, ?, 'kiwoom', ?)",
                (
                    code,
                    item.get("name", ""),
                    now,
                    now,
                    item.get("qty", 0),
                    item.get("price", 0.0),
                    now,
                ),
            )

    # mark sold for items not in current holdings
    rows = db.fetch_all("SELECT stock_code, status FROM holdings_watch WHERE status = 'holding'")
    sold_count = 0
    for r in rows:
        code = r["stock_code"]
        if code not in current_codes:
            db.execute(
                "UPDATE holdings_watch SET status = 'sold', last_seen = ?, last_qty = 0, updated_at = ? "
                "WHERE stock_code = ?",
                (now, now, code),
            )
            sold_count += 1
            changed_codes.add(code)

    return {
        "holding_count": len(holdings),
        "sold_marked": sold_count,
        "changed_codes": sorted(changed_codes),
    }
