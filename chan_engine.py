"""
缠论分析引擎 (Chan Theory / Entanglement Theory Engine)

核心模块：
1. K线合并 (Inclusive Candle Merging) — 含合并后回溯再合并
2. 分型识别 (Fractal/Fenxing Detection) - 顶分型/底分型
3. 笔划分 (Stroke/Bi Identification)
4. 线段划分 (Segment/XianDuan Identification)
5. 中枢识别 (Hub/ZhongShu Detection) - 基于笔构建
6. 背驰检测 (Divergence/BeiChi Detection)
7. 买卖点判断 (Buy/Sell Point Detection)
"""

import pandas as pd


def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Make date column timezone-naive timestamps for reliable comparisons."""
    if df.empty or "date" not in df.columns:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    if getattr(out["date"].dt, "tz", None) is not None:
        out["date"] = out["date"].dt.tz_localize(None)
    return out


def _as_ts(value):
    ts = pd.to_datetime(value, errors="coerce")
    if getattr(ts, "tz", None) is not None:
        ts = ts.tz_localize(None)
    return ts


# ─────────────────────────────────────────────
# 1. K线合并 (Inclusive Candle Merging)
# ─────────────────────────────────────────────

def _is_inclusive(a: dict, b: dict) -> bool:
    return (
        (a["high"] >= b["high"] and a["low"] <= b["low"])
        or (b["high"] >= a["high"] and b["low"] <= a["low"])
    )


def _pair_direction(prev: dict, first: dict) -> int:
    """Direction of the pair relative to the candle before it: 1=up, -1=down."""
    if first["high"] > prev["high"]:
        return 1
    if first["low"] < prev["low"]:
        return -1
    if first["high"] >= prev["high"]:
        return 1
    return -1


def _merge_pair(a: dict, b: dict, direction: int) -> dict:
    out = b.copy()
    if direction == 1:
        out["high"] = max(a["high"], b["high"])
        out["low"] = max(a["low"], b["low"])
    else:
        out["high"] = min(a["high"], b["high"])
        out["low"] = min(a["low"], b["low"])
    if "open" in a:
        out["open"] = a["open"]
    if "close" in b:
        out["close"] = b["close"]
    out["volume"] = max(a.get("volume", 0) or 0, b.get("volume", 0) or 0)
    out["date"] = b["date"]
    return out


def merge_inclusive_candles(df: pd.DataFrame) -> pd.DataFrame:
    """
    处理包含关系的K线合并。
    输入 df 需有 columns: date, open, high, low, close, volume
    输出: 合并后的K线 DataFrame

    合并后若结果与前一根仍包含，继续向前合并（标准缠论处理）。
    """
    if df.empty or len(df) < 2:
        return df.copy()

    rows = [r.copy() for r in df.to_dict("records")]
    merged = [rows[0]]

    for cur in rows[1:]:
        merged.append(cur.copy())
        while len(merged) >= 2 and _is_inclusive(merged[-2], merged[-1]):
            if len(merged) >= 3:
                direction = _pair_direction(merged[-3], merged[-2])
            else:
                direction = 1 if merged[-1]["high"] >= merged[-2]["high"] else -1
            merged[-2:] = [_merge_pair(merged[-2], merged[-1], direction)]

    return pd.DataFrame(merged)


# ─────────────────────────────────────────────
# 2. 分型识别 (Fractal/Fenxing Detection)
# ─────────────────────────────────────────────

def detect_fenxing(merged_df: pd.DataFrame) -> list:
    """
    识别顶分型和底分型。
    合并后无包含关系时，顶分型 = 中间K线 high 最高；底分型 = 中间K线 low 最低。
    返回: list of dict {index, date, type: 'top'/'bottom', price}
    """
    fenxing_list = []
    if len(merged_df) < 3:
        return fenxing_list

    rows = merged_df.to_dict("records")
    for i in range(1, len(rows) - 1):
        prev, cur, nxt = rows[i - 1], rows[i], rows[i + 1]

        is_top = cur["high"] > prev["high"] and cur["high"] > nxt["high"]
        is_bottom = cur["low"] < prev["low"] and cur["low"] < nxt["low"]

        # After inclusive merge, a true top also has higher lows; require both
        # to avoid marking a K that only expanded one side.
        if is_top and cur["low"] >= prev["low"] and cur["low"] >= nxt["low"]:
            fenxing_list.append({
                "index": i,
                "date": cur["date"],
                "type": "top",
                "price": cur["high"],
            })
        elif is_bottom and cur["high"] <= prev["high"] and cur["high"] <= nxt["high"]:
            fenxing_list.append({
                "index": i,
                "date": cur["date"],
                "type": "bottom",
                "price": cur["low"],
            })

    return fenxing_list


# ─────────────────────────────────────────────
# 3. 笔划分 (Stroke/Bi Identification)
# ─────────────────────────────────────────────

_MIN_FX_GAP = 4  # 两分型之间至少 1 根独立K线 → 合并K线索引差 >= 4


def identify_bi(fenxing_list: list, merged_df: pd.DataFrame = None) -> list:
    """
    从分型序列中划分笔。
    规则:
    - 顶分型与底分型交替出现
    - 相邻两个分型之间至少有1根独立K线（合并后索引差>=4）
    - 向上笔终点价必须高于起点，向下笔相反
    返回: list of dict {start_date, end_date, start_price, end_price, direction}
    """
    if len(fenxing_list) < 2:
        return []

    valid = [fenxing_list[0]]
    for fx in fenxing_list[1:]:
        last = valid[-1]

        if fx["type"] == last["type"]:
            if fx["type"] == "top" and fx["price"] > last["price"]:
                valid[-1] = fx
            elif fx["type"] == "bottom" and fx["price"] < last["price"]:
                valid[-1] = fx
            continue

        if abs(fx["index"] - last["index"]) < _MIN_FX_GAP:
            # Opposite but too close: keep looking; do not replace last
            # unless this opposite is so close it invalidates nothing.
            continue

        valid.append(fx)

    # After replacements, drop any remaining same-type neighbors (shouldn't
    # happen) and re-check gaps against the previous opposite.
    cleaned = []
    for fx in valid:
        if not cleaned:
            cleaned.append(fx)
            continue
        if fx["type"] == cleaned[-1]["type"]:
            if fx["type"] == "top" and fx["price"] > cleaned[-1]["price"]:
                cleaned[-1] = fx
            elif fx["type"] == "bottom" and fx["price"] < cleaned[-1]["price"]:
                cleaned[-1] = fx
            continue
        if abs(fx["index"] - cleaned[-1]["index"]) < _MIN_FX_GAP:
            continue
        cleaned.append(fx)
    valid = cleaned

    bi_list = []
    for i in range(1, len(valid)):
        prev_fx = valid[i - 1]
        cur_fx = valid[i]
        direction = "up" if cur_fx["type"] == "top" else "down"
        start_price = prev_fx["price"]
        end_price = cur_fx["price"]
        if direction == "up" and end_price <= start_price:
            continue
        if direction == "down" and end_price >= start_price:
            continue
        change_pct = (
            (end_price - start_price) / start_price * 100 if start_price else 0.0
        )
        bi_list.append({
            "start_date": prev_fx["date"],
            "end_date": cur_fx["date"],
            "start_price": start_price,
            "end_price": end_price,
            "direction": direction,
            "start_index": prev_fx["index"],
            "end_index": cur_fx["index"],
            "change_pct": change_pct,
        })

    return bi_list


# ─────────────────────────────────────────────
# 4. 线段划分 (Segment/XianDuan Identification)
# ─────────────────────────────────────────────

def identify_xianduan(bi_list: list) -> list:
    """
    简化特征序列法划分线段。

    确认条件：连续三笔（同向-反向-同向）且第三笔极值超过第一笔，
    构成该方向线段。线段延续直到反向三笔同样被确认。
    """
    if len(bi_list) < 3:
        return []

    segments = []
    n = len(bi_list)
    i = 0
    while i <= n - 3:
        d = bi_list[i]["direction"]
        if bi_list[i + 1]["direction"] == d or bi_list[i + 2]["direction"] != d:
            i += 1
            continue

        if d == "up":
            confirmed = bi_list[i + 2]["end_price"] > bi_list[i]["end_price"]
        else:
            confirmed = bi_list[i + 2]["end_price"] < bi_list[i]["end_price"]

        if not confirmed:
            i += 1
            continue

        end = i + 2
        for k in range(end + 1, n - 2):
            rd = bi_list[k]["direction"]
            if rd == d:
                continue
            if bi_list[k + 1]["direction"] != d or bi_list[k + 2]["direction"] == d:
                continue
            if rd == "down":
                rev_ok = bi_list[k + 2]["end_price"] < bi_list[k]["end_price"]
            else:
                rev_ok = bi_list[k + 2]["end_price"] > bi_list[k]["end_price"]
            if rev_ok:
                end = k - 1
                break
        else:
            end = n - 1

        if end < i + 2:
            end = i + 2

        start_price = bi_list[i]["start_price"]
        end_price = bi_list[end]["end_price"]
        segments.append({
            "start_date": bi_list[i]["start_date"],
            "end_date": bi_list[end]["end_date"],
            "start_price": start_price,
            "end_price": end_price,
            "direction": d,
            "bi_count": end - i + 1,
            "start_bi": i,
            "end_bi": end,
        })
        i = end + 1

    return segments


# ─────────────────────────────────────────────
# 5. 中枢识别 (Hub/ZhongShu Detection)
# ─────────────────────────────────────────────

def detect_zhongshu(bi_list: list) -> list:
    """
    识别中枢。中枢由至少3笔的重叠区间构成。
    中枢区间 = 连续三笔高低点重叠区域（后续笔只决定是否延伸，不改区间）。
    返回: list of dict {start_date, end_date, high, low, bi_count}
    """
    if len(bi_list) < 3:
        return []

    zhongshu_list = []
    i = 0
    while i < len(bi_list) - 2:
        b1, b2, b3 = bi_list[i], bi_list[i + 1], bi_list[i + 2]
        ranges = []
        for b in (b1, b2, b3):
            ranges.append((
                min(b["start_price"], b["end_price"]),
                max(b["start_price"], b["end_price"]),
            ))

        zs_low = max(r[0] for r in ranges)
        zs_high = min(r[1] for r in ranges)

        if zs_low < zs_high:
            bi_count = 3
            zs_start = b1["start_date"]
            zs_end = b3["end_date"]
            j = i + 3
            while j < len(bi_list):
                bj = bi_list[j]
                bj_high = max(bj["start_price"], bj["end_price"])
                bj_low = min(bj["start_price"], bj["end_price"])
                if bj_low < zs_high and bj_high > zs_low:
                    bi_count += 1
                    zs_end = bj["end_date"]
                    j += 1
                else:
                    break

            zhongshu_list.append({
                "start_date": zs_start,
                "end_date": zs_end,
                "high": zs_high,
                "low": zs_low,
                "bi_count": bi_count,
            })
            i = j
        else:
            i += 1

    return zhongshu_list


# ─────────────────────────────────────────────
# 6. 趋势与背驰检测 (Trend & Divergence)
# ─────────────────────────────────────────────

def detect_trend(zhongshu_list: list) -> str:
    """
    根据中枢之间的关系判断趋势。
    上涨趋势: 后一中枢高于前一中枢
    下跌趋势: 后一中枢低于前一中枢
    盘整: 中枢重叠
    """
    if len(zhongshu_list) < 2:
        return "consolidation"

    zs1, zs2 = zhongshu_list[-2], zhongshu_list[-1]

    if zs2["low"] > zs1["high"]:
        return "uptrend"
    if zs2["high"] < zs1["low"]:
        return "downtrend"
    return "consolidation"


def _slice_by_bi(df: pd.DataFrame, bi: dict) -> pd.DataFrame:
    start = _as_ts(bi["start_date"])
    end = _as_ts(bi["end_date"])
    dates = pd.to_datetime(df["date"], errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    return df.loc[(dates >= start) & (dates <= end)]


def _macd_dif_area(bi, df):
    """
    计算一笔区间内DIF与DEA围成的面积（即MACD柱状图面积之和）。
    缠论原著用黄白线（DIF/DEA）围成的面积比较力度，
    MACD柱 = 2*(DIF-DEA) 正是这个面积的度量。
    """
    if df.empty or "macd" not in df.columns:
        return 0
    segment = _slice_by_bi(df, bi)["macd"]
    if segment.empty:
        return 0
    return float(abs(segment.sum()))


def _dif_peak_in_bi(bi, df):
    """取一笔区间内DIF的极值（上涨笔取最大值，下跌笔取最小值的绝对值）"""
    if df.empty or "dif" not in df.columns:
        return 0
    segment = _slice_by_bi(df, bi)["dif"]
    if segment.empty:
        return 0
    if bi["direction"] == "up":
        return float(segment.max())
    return float(abs(segment.min()))


def _dif_cross_zero_between(bi1, bi2, df):
    """
    检查两笔之间DIF是否回抽零轴。
    缠论：两次同向走势之间DIF回拉零轴 → 趋势背驰；
    DIF未回零轴 → 盘整背驰。
    """
    if df.empty or "dif" not in df.columns:
        return False
    start = _as_ts(bi1["end_date"])
    end = _as_ts(bi2["start_date"])
    dates = pd.to_datetime(df["date"], errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    segment = df.loc[(dates >= start) & (dates <= end), "dif"]
    if segment.empty:
        return False
    if bi1["direction"] == "up":
        return float(segment.min()) <= 0
    return float(segment.max()) >= 0


def _zhongshu_between(bi1, bi2, zhongshu_list) -> bool:
    if not zhongshu_list:
        return False
    start = _as_ts(bi1["end_date"])
    end = _as_ts(bi2["start_date"])
    for zs in zhongshu_list:
        zs_start = _as_ts(zs["start_date"])
        zs_end = _as_ts(zs["end_date"])
        if zs_end > start and zs_start < end:
            return True
    return False


def _beichi_for_pair(last_bi, prev_same_dir, df_with_macd, zhongshu_list):
    area_last = _macd_dif_area(last_bi, df_with_macd)
    area_prev = _macd_dif_area(prev_same_dir, df_with_macd)
    if area_prev == 0:
        return None

    area_ratio = area_last / area_prev
    dif_peak_last = _dif_peak_in_bi(last_bi, df_with_macd)
    dif_peak_prev = _dif_peak_in_bi(prev_same_dir, df_with_macd)
    dif_ratio = dif_peak_last / dif_peak_prev if dif_peak_prev != 0 else 1.0
    dif_crossed_zero = _dif_cross_zero_between(prev_same_dir, last_bi, df_with_macd)
    zs_between = _zhongshu_between(prev_same_dir, last_bi, zhongshu_list or [])

    is_area_beichi = area_ratio < 0.9
    is_dif_beichi = dif_ratio < 0.9
    if not is_area_beichi:
        return None

    # 趋势背驰以DIF回抽零轴为准；中枢间隔只作为描述补充
    is_trend = dif_crossed_zero
    bc_type = "趋势背驰" if is_trend else "盘整背驰"
    dif_note = "确认" if is_dif_beichi else "未确认"
    zs_note = " | 两笔间有中枢" if zs_between else ""

    if last_bi["direction"] == "up":
        price_new_extreme = last_bi["end_price"] >= prev_same_dir["end_price"] * 0.98
        if not price_new_extreme:
            return None
        return {
            "type": "top_beichi",
            "subtype": "trend" if is_trend else "consolidation",
            "date": last_bi["end_date"],
            "price": last_bi["end_price"],
            "area_ratio": area_ratio,
            "dif_ratio": dif_ratio,
            "strength_ratio": area_ratio,
            "dif_crossed_zero": dif_crossed_zero,
            "dif_confirmed": is_dif_beichi,
            "desc": (
                f"{bc_type} | 面积比={area_ratio:.2f} DIF峰值比={dif_ratio:.2f}"
                f"({dif_note}) | DIF{'回抽' if dif_crossed_zero else '未回'}零轴"
                f"{zs_note}"
            ),
        }

    price_new_extreme = last_bi["end_price"] <= prev_same_dir["end_price"] * 1.02
    if not price_new_extreme:
        return None
    return {
        "type": "bottom_beichi",
        "subtype": "trend" if is_trend else "consolidation",
        "date": last_bi["end_date"],
        "price": last_bi["end_price"],
        "area_ratio": area_ratio,
        "dif_ratio": dif_ratio,
        "strength_ratio": area_ratio,
        "dif_crossed_zero": dif_crossed_zero,
        "dif_confirmed": is_dif_beichi,
        "desc": (
            f"{bc_type} | 面积比={area_ratio:.2f} DIF峰值比={dif_ratio:.2f}"
            f"({dif_note}) | DIF{'回抽' if dif_crossed_zero else '未回'}零轴"
            f"{zs_note}"
        ),
    }


def detect_beichi(bi_list: list, df_with_macd: pd.DataFrame,
                  zhongshu_list: list = None) -> list:
    """
    按缠论原著的背驰检测。扫描每一笔与其前一同向笔，而不仅是最后一笔，
    这样第一类买卖点不会在后续回调出现时消失，第二类买卖点才有依据。
    """
    beichi_list = []
    if len(bi_list) < 3 or df_with_macd is None or df_with_macd.empty:
        return beichi_list

    if "macd" not in df_with_macd.columns:
        df_with_macd = compute_macd(df_with_macd)

    for i in range(2, len(bi_list)):
        last_bi = bi_list[i]
        prev_same_dir = None
        for j in range(i - 2, -1, -1):
            if bi_list[j]["direction"] == last_bi["direction"]:
                prev_same_dir = bi_list[j]
                break
        if prev_same_dir is None:
            continue
        item = _beichi_for_pair(last_bi, prev_same_dir, df_with_macd, zhongshu_list)
        if item:
            beichi_list.append(item)

    return beichi_list


# ─────────────────────────────────────────────
# 7. MACD 计算
# ─────────────────────────────────────────────

def compute_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    """计算MACD指标"""
    df = df.copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    df["dif"] = ema_fast - ema_slow
    df["dea"] = df["dif"].ewm(span=signal, adjust=False).mean()
    df["macd"] = 2 * (df["dif"] - df["dea"])
    return df


# ─────────────────────────────────────────────
# 8. 买卖点识别 (Buy/Sell Point Detection)
# ─────────────────────────────────────────────

def detect_buy_sell_points(bi_list: list, zhongshu_list: list,
                           beichi_list: list, current_price: float,
                           latest_date=None, df_macd: pd.DataFrame = None) -> list:
    """
    按缠论原著识别三类买卖点，结合MACD确认。

    第一类买点: 下跌趋势中最后一段背驰
    第二类买点: 第一类买点后的第一次回调不创新低
    第三类买点: 向上离开中枢后的回调不跌回中枢
    """
    signals = []

    if not bi_list:
        return signals, None

    last_bi = bi_list[-1]

    def signal_status(signal_price, is_buy):
        if current_price is None or signal_price is None:
            return "unknown"
        try:
            signal_price = float(signal_price)
            current = float(current_price)
        except (TypeError, ValueError):
            return "unknown"
        if is_buy:
            if current > signal_price * 1.05:
                return "historical"
        else:
            if current < signal_price * 0.95:
                return "historical"
        return "active"

    def macd_at_bi_end(bi):
        if df_macd is None or df_macd.empty:
            return {}
        end = _as_ts(bi["end_date"])
        dates = pd.to_datetime(df_macd["date"], errors="coerce")
        if getattr(dates.dt, "tz", None) is not None:
            dates = dates.dt.tz_localize(None)
        mask = dates <= end
        if mask.sum() == 0:
            return {}
        row = df_macd.loc[mask].iloc[-1]
        return {
            "dif": row.get("dif", 0),
            "dea": row.get("dea", 0),
            "macd": row.get("macd", 0),
        }

    def _cross_near(bi, golden: bool) -> bool:
        if df_macd is None or df_macd.empty:
            return False
        seg = _slice_by_bi(df_macd, bi)
        if len(seg) < 2:
            return False
        for i in range(max(0, len(seg) - 3), len(seg)):
            if i == 0:
                continue
            dif_now, dea_now = seg.iloc[i]["dif"], seg.iloc[i]["dea"]
            dif_prev, dea_prev = seg.iloc[i - 1]["dif"], seg.iloc[i - 1]["dea"]
            if golden and dif_now > dea_now and dif_prev <= dea_prev:
                return True
            if not golden and dif_now < dea_now and dif_prev >= dea_prev:
                return True
        return False

    def macd_golden_cross_near(bi):
        return _cross_near(bi, True)

    def macd_dead_cross_near(bi):
        return _cross_near(bi, False)

    forming_info = None
    if current_price is not None:
        try:
            current_price = float(current_price)
        except (TypeError, ValueError):
            current_price = None

    if current_price is not None and last_bi["direction"] == "down" and current_price > last_bi["end_price"]:
        forming_info = {
            "type": "forming_up",
            "name": "上涨笔形成中",
            "from_price": last_bi["end_price"],
            "current_price": current_price,
            "change_pct": (current_price - last_bi["end_price"]) / last_bi["end_price"] * 100,
            "desc": f"从{last_bi['end_price']:.2f}反弹至{current_price:.2f}"
                    f" (+{(current_price - last_bi['end_price']) / last_bi['end_price'] * 100:.1f}%)"
                    f"，等待顶分型确认",
        }
    elif current_price is not None and last_bi["direction"] == "up" and current_price < last_bi["end_price"]:
        forming_info = {
            "type": "forming_down",
            "name": "下跌笔形成中",
            "from_price": last_bi["end_price"],
            "current_price": current_price,
            "change_pct": (current_price - last_bi["end_price"]) / last_bi["end_price"] * 100,
            "desc": f"从{last_bi['end_price']:.2f}回落至{current_price:.2f}"
                    f" ({(current_price - last_bi['end_price']) / last_bi['end_price'] * 100:.1f}%)"
                    f"，等待底分型确认",
        }

    for bc in beichi_list or []:
        is_buy = bc["type"] == "bottom_beichi"
        status = signal_status(bc["price"], is_buy)
        bc_subtype = bc.get("subtype", "unknown")
        bc_desc = bc.get("desc", "")

        if is_buy:
            signals.append({
                "type": "1B",
                "name": f"第一类买点({'趋势' if bc_subtype == 'trend' else '盘整'}背驰)",
                "date": bc["date"],
                "price": bc["price"],
                "strength": bc.get("area_ratio", bc.get("strength_ratio", 0)),
                "status": status,
                "desc": f"底背驰 | {bc_desc}",
            })
        else:
            signals.append({
                "type": "1S",
                "name": f"第一类卖点({'趋势' if bc_subtype == 'trend' else '盘整'}背驰)",
                "date": bc["date"],
                "price": bc["price"],
                "strength": bc.get("area_ratio", bc.get("strength_ratio", 0)),
                "status": status,
                "desc": f"顶背驰 | {bc_desc}",
            })

    prior_1b = [s for s in signals if s["type"] == "1B"]
    prior_1s = [s for s in signals if s["type"] == "1S"]

    # 第二类：必须先有第一类，且出现在第一类之后的回调/反弹上
    if len(bi_list) >= 4:
        last_end = _as_ts(last_bi["end_date"])
        if last_bi["direction"] == "down" and prior_1b:
            prev_1b = prior_1b[-1]
            if _as_ts(prev_1b["date"]) < last_end and last_bi["end_price"] > prev_1b["price"]:
                status = signal_status(last_bi["end_price"], True)
                macd_info = macd_at_bi_end(last_bi)
                dif_val = macd_info.get("dif", 0)
                has_golden = macd_golden_cross_near(last_bi)
                macd_detail = f"DIF={dif_val:.4f}"
                if has_golden:
                    macd_detail += " MACD金叉确认"
                signals.append({
                    "type": "2B",
                    "name": "第二类买点",
                    "date": last_bi["end_date"],
                    "price": last_bi["end_price"],
                    "strength": 0,
                    "status": status,
                    "desc": (
                        f"1买后回调不创新低: {last_bi['end_price']:.2f} > "
                        f"1买{prev_1b['price']:.2f} | {macd_detail}"
                    ),
                })

        if last_bi["direction"] == "up" and prior_1s:
            prev_1s = prior_1s[-1]
            if _as_ts(prev_1s["date"]) < last_end and last_bi["end_price"] < prev_1s["price"]:
                status = signal_status(last_bi["end_price"], False)
                macd_info = macd_at_bi_end(last_bi)
                dif_val = macd_info.get("dif", 0)
                has_dead = macd_dead_cross_near(last_bi)
                macd_detail = f"DIF={dif_val:.4f}"
                if has_dead:
                    macd_detail += " MACD死叉确认"
                signals.append({
                    "type": "2S",
                    "name": "第二类卖点",
                    "date": last_bi["end_date"],
                    "price": last_bi["end_price"],
                    "strength": 0,
                    "status": status,
                    "desc": (
                        f"1卖后反弹不创新高: {last_bi['end_price']:.2f} < "
                        f"1卖{prev_1s['price']:.2f} | {macd_detail}"
                    ),
                })

    # 第三类：前一笔必须先离开中枢，当前反向笔不回到中枢
    if zhongshu_list and len(bi_list) >= 2:
        last_zs = zhongshu_list[-1]
        prev_bi = bi_list[-2]

        if last_bi["direction"] == "down":
            left_up = (
                prev_bi["direction"] == "up"
                and prev_bi["end_price"] > last_zs["high"]
            )
            if left_up and last_bi["end_price"] > last_zs["high"]:
                bi_low = last_bi["end_price"]
                status = signal_status(bi_low, True)
                macd_info = macd_at_bi_end(last_bi)
                has_golden = macd_golden_cross_near(last_bi)
                macd_detail = f"MACD柱={macd_info.get('macd', 0):.4f}"
                if has_golden:
                    macd_detail += " 金叉确认"
                signals.append({
                    "type": "3B",
                    "name": "第三类买点",
                    "date": last_bi["end_date"],
                    "price": bi_low,
                    "strength": 0,
                    "status": status,
                    "desc": (
                        f"离开后回调{bi_low:.2f}未进中枢"
                        f"[{last_zs['low']:.2f}-{last_zs['high']:.2f}] | {macd_detail}"
                    ),
                })

        if last_bi["direction"] == "up":
            left_down = (
                prev_bi["direction"] == "down"
                and prev_bi["end_price"] < last_zs["low"]
            )
            if left_down and last_bi["end_price"] < last_zs["low"]:
                bi_high = last_bi["end_price"]
                status = signal_status(bi_high, False)
                macd_info = macd_at_bi_end(last_bi)
                has_dead = macd_dead_cross_near(last_bi)
                macd_detail = f"MACD柱={macd_info.get('macd', 0):.4f}"
                if has_dead:
                    macd_detail += " 死叉确认"
                signals.append({
                    "type": "3S",
                    "name": "第三类卖点",
                    "date": last_bi["end_date"],
                    "price": bi_high,
                    "strength": 0,
                    "status": status,
                    "desc": (
                        f"离开后反弹{bi_high:.2f}未回中枢"
                        f"[{last_zs['low']:.2f}-{last_zs['high']:.2f}] | {macd_detail}"
                    ),
                })

    return signals, forming_info


# ─────────────────────────────────────────────
# 9. 完整分析流水线
# ─────────────────────────────────────────────

def full_chan_analysis(df: pd.DataFrame) -> dict:
    """
    完整的缠论分析流水线。
    输入: 标准OHLCV DataFrame (date, open, high, low, close, volume)
    输出: dict with all analysis results
    """
    if df is None or df.empty or len(df) < 10:
        return {"error": "数据不足，至少需要10根K线"}

    required = {"date", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        return {"error": f"缺少必要列: {', '.join(sorted(missing))}"}

    df = _normalize_dates(df)
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    if len(df) < 10:
        return {"error": "数据不足，至少需要10根K线"}

    df_macd = compute_macd(df)
    merged = merge_inclusive_candles(df_macd)
    fenxing = detect_fenxing(merged)
    bi_list = identify_bi(fenxing, merged)
    xianduan = identify_xianduan(bi_list)
    zhongshu = detect_zhongshu(bi_list)
    zhongshu_xd = detect_zhongshu(xianduan) if len(xianduan) >= 3 else []
    trend = detect_trend(zhongshu_xd) if len(zhongshu_xd) >= 2 else detect_trend(zhongshu)
    beichi = detect_beichi(bi_list, df_macd, zhongshu)
    current_price = float(df["close"].iloc[-1])
    latest_date = df["date"].iloc[-1]
    signals, forming_info = detect_buy_sell_points(
        bi_list, zhongshu, beichi, current_price, latest_date, df_macd)

    return {
        "merged_count": len(merged),
        "fenxing": fenxing,
        "fenxing_count": len(fenxing),
        "bi_list": bi_list,
        "bi_count": len(bi_list),
        "xianduan": xianduan,
        "xianduan_count": len(xianduan),
        "zhongshu": zhongshu,
        "zhongshu_count": len(zhongshu),
        "trend": trend,
        "beichi": beichi,
        "signals": signals,
        "forming": forming_info,
        "current_price": current_price,
        "last_date": df["date"].iloc[-1],
        "macd_latest": {
            "dif": float(df_macd["dif"].iloc[-1]),
            "dea": float(df_macd["dea"].iloc[-1]),
            "macd": float(df_macd["macd"].iloc[-1]),
        },
    }
