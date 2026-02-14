"""
缠论分析引擎 (Chan Theory / Entanglement Theory Engine)

核心模块：
1. K线合并 (Inclusive Candle Merging)
2. 分型识别 (Fractal/Fenxing Detection) - 顶分型/底分型
3. 笔划分 (Stroke/Bi Identification)
4. 线段划分 (Segment/XianDuan Identification)
5. 中枢识别 (Hub/ZhongShu Detection)
6. 背驰检测 (Divergence/BeiChi Detection)
7. 买卖点判断 (Buy/Sell Point Detection)
"""

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────
# 1. K线合并 (Inclusive Candle Merging)
# ─────────────────────────────────────────────

def merge_inclusive_candles(df: pd.DataFrame) -> pd.DataFrame:
    """
    处理包含关系的K线合并。
    输入 df 需有 columns: date, open, high, low, close, volume
    输出: 合并后的K线 DataFrame
    """
    if df.empty or len(df) < 3:
        return df.copy()

    merged = []
    rows = df.to_dict("records")
    merged.append(rows[0].copy())

    # 确定初始方向: 1=上升, -1=下降
    direction = 1 if rows[1]["high"] >= rows[0]["high"] else -1

    for i in range(1, len(rows)):
        cur = rows[i]
        prev = merged[-1]

        # 检查包含关系: prev包含cur 或 cur包含prev
        if (prev["high"] >= cur["high"] and prev["low"] <= cur["low"]) or \
           (cur["high"] >= prev["high"] and cur["low"] <= prev["low"]):
            # 合并
            if direction == 1:  # 上升趋势: 取高的high和高的low
                merged[-1]["high"] = max(prev["high"], cur["high"])
                merged[-1]["low"] = max(prev["low"], cur["low"])
            else:  # 下降趋势: 取低的high和低的low
                merged[-1]["high"] = min(prev["high"], cur["high"])
                merged[-1]["low"] = min(prev["low"], cur["low"])
            # 保留较大成交量和最新日期
            merged[-1]["volume"] = max(prev.get("volume", 0), cur.get("volume", 0))
            merged[-1]["date"] = cur["date"]
        else:
            # 不包含, 更新方向
            if cur["high"] > prev["high"]:
                direction = 1
            elif cur["low"] < prev["low"]:
                direction = -1
            merged.append(cur.copy())

    return pd.DataFrame(merged)


# ─────────────────────────────────────────────
# 2. 分型识别 (Fractal/Fenxing Detection)
# ─────────────────────────────────────────────

def detect_fenxing(merged_df: pd.DataFrame) -> list:
    """
    识别顶分型和底分型。
    顶分型: 中间K线的high最高
    底分型: 中间K线的low最低
    返回: list of dict {index, date, type: 'top'/'bottom', price}
    """
    fenxing_list = []
    if len(merged_df) < 3:
        return fenxing_list

    rows = merged_df.to_dict("records")
    for i in range(1, len(rows) - 1):
        prev, cur, nxt = rows[i - 1], rows[i], rows[i + 1]

        if cur["high"] > prev["high"] and cur["high"] > nxt["high"] and \
           cur["low"] > prev["low"] and cur["low"] > nxt["low"]:
            fenxing_list.append({
                "index": i,
                "date": cur["date"],
                "type": "top",
                "price": cur["high"],
            })
        elif cur["low"] < prev["low"] and cur["low"] < nxt["low"] and \
             cur["high"] < prev["high"] and cur["high"] < nxt["high"]:
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

def identify_bi(fenxing_list: list, merged_df: pd.DataFrame) -> list:
    """
    从分型序列中划分笔。
    规则:
    - 顶分型与底分型交替出现
    - 相邻两个分型之间至少有1根独立K线（即分型之间>=5根原始K线，合并后>=3根）
    返回: list of dict {start_date, end_date, start_price, end_price, direction: 'up'/'down'}
    """
    if len(fenxing_list) < 2:
        return []

    # 过滤分型: 保证交替出现且间隔足够
    valid = [fenxing_list[0]]
    for i in range(1, len(fenxing_list)):
        fx = fenxing_list[i]
        last = valid[-1]

        # 必须交替
        if fx["type"] == last["type"]:
            # 同类型: 取更极端的
            if fx["type"] == "top" and fx["price"] > last["price"]:
                valid[-1] = fx
            elif fx["type"] == "bottom" and fx["price"] < last["price"]:
                valid[-1] = fx
            continue

        # 间隔检查: 至少间隔4根合并K线
        if abs(fx["index"] - last["index"]) < 4:
            continue

        valid.append(fx)

    # 从有效分型构建笔
    bi_list = []
    for i in range(1, len(valid)):
        prev_fx = valid[i - 1]
        cur_fx = valid[i]
        direction = "up" if cur_fx["type"] == "top" else "down"
        bi_list.append({
            "start_date": prev_fx["date"],
            "end_date": cur_fx["date"],
            "start_price": prev_fx["price"],
            "end_price": cur_fx["price"],
            "direction": direction,
        })

    return bi_list


# ─────────────────────────────────────────────
# 4. 中枢识别 (Hub/ZhongShu Detection)
# ─────────────────────────────────────────────

def detect_zhongshu(bi_list: list) -> list:
    """
    识别中枢。中枢由至少3笔的重叠区间构成。
    中枢区间 = 连续笔的高低点重叠区域
    返回: list of dict {start_date, end_date, high, low, bi_count, level}
    """
    if len(bi_list) < 3:
        return []

    zhongshu_list = []

    i = 0
    while i < len(bi_list) - 2:
        # 取3笔, 找重叠区间
        b1, b2, b3 = bi_list[i], bi_list[i + 1], bi_list[i + 2]

        # 每笔的高低范围
        ranges = []
        for b in [b1, b2, b3]:
            h = max(b["start_price"], b["end_price"])
            l = min(b["start_price"], b["end_price"])
            ranges.append((l, h))

        # 重叠区间
        zs_low = max(r[0] for r in ranges)
        zs_high = min(r[1] for r in ranges)

        if zs_low < zs_high:
            # 有效中枢, 尝试扩展
            bi_count = 3
            zs_start = b1["start_date"]
            zs_end = b3["end_date"]

            j = i + 3
            while j < len(bi_list):
                bj = bi_list[j]
                bj_high = max(bj["start_price"], bj["end_price"])
                bj_low = min(bj["start_price"], bj["end_price"])
                # 检查是否与中枢有重叠
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
            i = j  # 跳到中枢之后
        else:
            i += 1

    return zhongshu_list


# ─────────────────────────────────────────────
# 5. 趋势与背驰检测 (Trend & Divergence)
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

    last_two = zhongshu_list[-2:]
    zs1, zs2 = last_two[0], last_two[1]

    if zs2["low"] > zs1["high"]:
        return "uptrend"
    elif zs2["high"] < zs1["low"]:
        return "downtrend"
    else:
        return "consolidation"


def _macd_dif_area(bi, df):
    """
    计算一笔区间内DIF与DEA围成的面积（即MACD柱状图面积之和）。
    缠论原著用黄白线（DIF/DEA）围成的面积比较力度，
    MACD柱 = 2*(DIF-DEA) 正是这个面积的度量。
    """
    mask = (df["date"] >= bi["start_date"]) & (df["date"] <= bi["end_date"])
    segment = df.loc[mask, "macd"]
    if segment.empty:
        return 0
    return abs(segment.sum())


def _dif_peak_in_bi(bi, df):
    """取一笔区间内DIF的极值（上涨笔取最大值，下跌笔取最小值的绝对值）"""
    mask = (df["date"] >= bi["start_date"]) & (df["date"] <= bi["end_date"])
    segment = df.loc[mask, "dif"]
    if segment.empty:
        return 0
    if bi["direction"] == "up":
        return segment.max()
    else:
        return abs(segment.min())


def _dif_cross_zero_between(bi1, bi2, df):
    """
    检查两笔之间DIF是否回抽零轴。
    缠论：两次同向走势之间DIF回拉零轴 → 说明经历了一个完整的中枢震荡，
    之后的背驰属于"趋势背驰"（更强的信号）。
    DIF未回零轴 → "盘整背驰"（较弱的信号）。
    """
    mask = (df["date"] >= bi1["end_date"]) & (df["date"] <= bi2["start_date"])
    segment = df.loc[mask, "dif"]
    if segment.empty:
        return False
    if bi1["direction"] == "up":
        # 上涨趋势中间，DIF应该回到零轴以下
        return segment.min() <= 0
    else:
        # 下跌趋势中间，DIF应该回到零轴以上
        return segment.max() >= 0


def detect_beichi(bi_list: list, df_with_macd: pd.DataFrame,
                  zhongshu_list: list = None) -> list:
    """
    按缠论原著的背驰检测。

    核心逻辑（缠中说禅原文）：
    1. 比较两段同向走势的MACD黄白线面积（DIF与DEA围成的面积）
    2. 价格创新高/低，但MACD面积缩小 → 背驰
    3. 两段之间DIF回抽零轴 → 趋势背驰（强信号，至少有两个中枢）
    4. 两段之间DIF未回零轴 → 盘整背驰（弱信号，一个中枢内的波动）
    5. DIF极值也用于辅助判断：DIF峰值降低也是背驰特征

    返回: list of dict
    """
    beichi_list = []
    if len(bi_list) < 3 or df_with_macd.empty:
        return beichi_list

    if "macd" not in df_with_macd.columns:
        df_with_macd = compute_macd(df_with_macd)

    last_bi = bi_list[-1]

    # 找前一个同向笔（隔一笔，即倒数第3笔起找）
    prev_same_dir = None
    prev_idx = None
    for j in range(len(bi_list) - 3, -1, -1):
        if bi_list[j]["direction"] == last_bi["direction"]:
            prev_same_dir = bi_list[j]
            prev_idx = j
            break

    if prev_same_dir is None:
        return beichi_list

    # ── 面积比较（核心） ──
    area_last = _macd_dif_area(last_bi, df_with_macd)
    area_prev = _macd_dif_area(prev_same_dir, df_with_macd)

    if area_prev == 0:
        return beichi_list

    area_ratio = area_last / area_prev

    # ── DIF极值比较（辅助） ──
    dif_peak_last = _dif_peak_in_bi(last_bi, df_with_macd)
    dif_peak_prev = _dif_peak_in_bi(prev_same_dir, df_with_macd)
    dif_ratio = dif_peak_last / dif_peak_prev if dif_peak_prev != 0 else 1.0

    # ── 零轴回抽判断：区分趋势背驰和盘整背驰 ──
    dif_crossed_zero = _dif_cross_zero_between(prev_same_dir, last_bi, df_with_macd)

    # ── 背驰判断 ──
    # 面积缩小 = 背驰的必要条件
    is_area_beichi = area_ratio < 0.9

    # DIF极值也缩小 = 更强确认
    is_dif_beichi = dif_ratio < 0.9

    if last_bi["direction"] == "up":
        # 价格创新高（或接近），面积缩小
        price_new_extreme = last_bi["end_price"] >= prev_same_dir["end_price"] * 0.98
        if price_new_extreme and is_area_beichi:
            bc_type = "趋势背驰" if dif_crossed_zero else "盘整背驰"
            beichi_list.append({
                "type": "top_beichi",
                "subtype": "trend" if dif_crossed_zero else "consolidation",
                "date": last_bi["end_date"],
                "price": last_bi["end_price"],
                "area_ratio": area_ratio,
                "dif_ratio": dif_ratio,
                "strength_ratio": area_ratio,  # 兼容旧字段
                "dif_crossed_zero": dif_crossed_zero,
                "desc": f"{bc_type} | 面积比={area_ratio:.2f} DIF峰值比={dif_ratio:.2f}"
                        f" | DIF{'回抽' if dif_crossed_zero else '未回'}零轴",
            })

    elif last_bi["direction"] == "down":
        price_new_extreme = last_bi["end_price"] <= prev_same_dir["end_price"] * 1.02
        if price_new_extreme and is_area_beichi:
            bc_type = "趋势背驰" if dif_crossed_zero else "盘整背驰"
            beichi_list.append({
                "type": "bottom_beichi",
                "subtype": "trend" if dif_crossed_zero else "consolidation",
                "date": last_bi["end_date"],
                "price": last_bi["end_price"],
                "area_ratio": area_ratio,
                "dif_ratio": dif_ratio,
                "strength_ratio": area_ratio,  # 兼容旧字段
                "dif_crossed_zero": dif_crossed_zero,
                "desc": f"{bc_type} | 面积比={area_ratio:.2f} DIF峰值比={dif_ratio:.2f}"
                        f" | DIF{'回抽' if dif_crossed_zero else '未回'}零轴",
            })

    return beichi_list


# ─────────────────────────────────────────────
# 6. MACD 计算
# ─────────────────────────────────────────────

def compute_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    """计算MACD指标"""
    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = ema_fast - ema_slow
    df["dea"] = df["dif"].ewm(span=signal, adjust=False).mean()
    df["macd"] = 2 * (df["dif"] - df["dea"])
    return df


# ─────────────────────────────────────────────
# 7. 买卖点识别 (Buy/Sell Point Detection)
# ─────────────────────────────────────────────

def detect_buy_sell_points(bi_list: list, zhongshu_list: list,
                           beichi_list: list, current_price: float,
                           latest_date=None, df_macd: pd.DataFrame = None) -> list:
    """
    按缠论原著识别三类买卖点，结合MACD确认。

    缠论买卖点体系（缠中说禅原文）：

    第一类买点: 下跌趋势中，最后一段背驰（MACD面积缩小），形成底分型
      - 必须有背驰作为前提（MACD力度递减）
      - 趋势背驰（DIF回零轴后）比盘整背驰更可靠
    第一类卖点: 上涨趋势中，最后一段背驰，形成顶分型

    第二类买点: 第一类买点后的第一次回调不创新低
      - MACD确认：此时MACD柱应在零轴附近或缩短，DIF回抽零轴
    第二类卖点: 第一类卖点后的第一次反弹不创新高

    第三类买点: 中枢形成后，向上离开中枢的回调不跌回中枢内
      - MACD确认：回调时MACD柱缩短或金叉
    第三类卖点: 中枢形成后，向下离开中枢的反弹不回到中枢内
    """
    signals = []

    if not bi_list:
        return signals, None

    last_bi = bi_list[-1]

    # ── 信号新鲜度 ──
    def signal_status(signal_price, is_buy):
        if current_price is None:
            return "unknown"
        if is_buy:
            if current_price > signal_price * 1.05:
                return "historical"
        else:
            if current_price < signal_price * 0.95:
                return "historical"
        return "active"

    # ── MACD辅助函数 ──
    def macd_at_bi_end(bi):
        """取笔结束时的MACD状态"""
        if df_macd is None or df_macd.empty:
            return {}
        mask = df_macd["date"] <= bi["end_date"]
        if mask.sum() == 0:
            return {}
        row = df_macd.loc[mask].iloc[-1]
        return {
            "dif": row.get("dif", 0),
            "dea": row.get("dea", 0),
            "macd": row.get("macd", 0),
        }

    def macd_golden_cross_near(bi):
        """检查笔结束附近是否出现MACD金叉（DIF上穿DEA）"""
        if df_macd is None or df_macd.empty:
            return False
        mask = (df_macd["date"] >= bi["start_date"]) & (df_macd["date"] <= bi["end_date"])
        seg = df_macd.loc[mask]
        if len(seg) < 2:
            return False
        # 检查最后几根K线是否出现金叉
        for i in range(max(0, len(seg) - 3), len(seg)):
            if i > 0 and seg.iloc[i]["dif"] > seg.iloc[i]["dea"] and \
               seg.iloc[i - 1]["dif"] <= seg.iloc[i - 1]["dea"]:
                return True
        return False

    def macd_dead_cross_near(bi):
        """检查笔结束附近是否出现MACD死叉（DIF下穿DEA）"""
        if df_macd is None or df_macd.empty:
            return False
        mask = (df_macd["date"] >= bi["start_date"]) & (df_macd["date"] <= bi["end_date"])
        seg = df_macd.loc[mask]
        if len(seg) < 2:
            return False
        for i in range(max(0, len(seg) - 3), len(seg)):
            if i > 0 and seg.iloc[i]["dif"] < seg.iloc[i]["dea"] and \
               seg.iloc[i - 1]["dif"] >= seg.iloc[i - 1]["dea"]:
                return True
        return False

    # ── 当前走势状态（未完成的笔）──
    forming_info = None
    if last_bi["direction"] == "down" and current_price > last_bi["end_price"]:
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
    elif last_bi["direction"] == "up" and current_price < last_bi["end_price"]:
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

    # ══════════════════════════════════════════
    # 第一类买卖点: 背驰 + 分型确认
    # ══════════════════════════════════════════
    for bc in beichi_list:
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

    # ══════════════════════════════════════════
    # 第二类买卖点: 1买/1卖后第一次回调/反弹不创新低/高
    # MACD确认: 回调时MACD柱缩短，DIF靠近零轴
    # ══════════════════════════════════════════
    if len(bi_list) >= 4:
        if last_bi["direction"] == "down":
            prev_down = None
            for j in range(len(bi_list) - 3, -1, -1):
                if bi_list[j]["direction"] == "down":
                    prev_down = bi_list[j]
                    break
            if prev_down and last_bi["end_price"] > prev_down["end_price"]:
                status = signal_status(last_bi["end_price"], True)
                # MACD确认: 回调结束时DIF回抽零轴附近
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
                    "desc": f"回调不创新低: {last_bi['end_price']:.2f} > 前低{prev_down['end_price']:.2f}"
                            f" | {macd_detail}",
                })

        if last_bi["direction"] == "up":
            prev_up = None
            for j in range(len(bi_list) - 3, -1, -1):
                if bi_list[j]["direction"] == "up":
                    prev_up = bi_list[j]
                    break
            if prev_up and last_bi["end_price"] < prev_up["end_price"]:
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
                    "desc": f"反弹不创新高: {last_bi['end_price']:.2f} < 前高{prev_up['end_price']:.2f}"
                            f" | {macd_detail}",
                })

    # ══════════════════════════════════════════
    # 第三类买卖点: 离开中枢后回踩不回中枢
    # MACD确认: 回踩时MACD柱缩短，说明回踩力度弱
    # ══════════════════════════════════════════
    if zhongshu_list and len(bi_list) >= 2:
        last_zs = zhongshu_list[-1]

        if last_bi["direction"] == "down":
            bi_low = last_bi["end_price"]
            # 严格3买：回调低点在中枢上沿之上
            if bi_low > last_zs["high"]:
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
                    "desc": f"回调{bi_low:.2f}未进中枢[{last_zs['low']:.2f}-{last_zs['high']:.2f}]"
                            f" | {macd_detail}",
                })

        if last_bi["direction"] == "up":
            bi_high = last_bi["end_price"]
            # 严格3卖：反弹高点在中枢下沿之下
            if bi_high < last_zs["low"]:
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
                    "desc": f"反弹{bi_high:.2f}未回中枢[{last_zs['low']:.2f}-{last_zs['high']:.2f}]"
                            f" | {macd_detail}",
                })

    return signals, forming_info


# ─────────────────────────────────────────────
# 8. 完整分析流水线
# ─────────────────────────────────────────────

def full_chan_analysis(df: pd.DataFrame) -> dict:
    """
    完整的缠论分析流水线。
    输入: 标准OHLCV DataFrame (date, open, high, low, close, volume)
    输出: dict with all analysis results
    """
    if df.empty or len(df) < 10:
        return {"error": "数据不足，至少需要10根K线"}

    # Step 1: MACD
    df_macd = compute_macd(df)

    # Step 2: K线合并
    merged = merge_inclusive_candles(df_macd)

    # Step 3: 分型识别
    fenxing = detect_fenxing(merged)

    # Step 4: 笔划分
    bi_list = identify_bi(fenxing, merged)

    # Step 5: 中枢识别
    zhongshu = detect_zhongshu(bi_list)

    # Step 6: 趋势判断
    trend = detect_trend(zhongshu)

    # Step 7: 背驰检测 (传入中枢列表用于趋势/盘整背驰区分)
    beichi = detect_beichi(bi_list, df_macd, zhongshu)

    # Step 8: 买卖点 (传入df_macd用于MACD金叉/死叉确认)
    current_price = df["close"].iloc[-1]
    latest_date = df["date"].iloc[-1]
    signals, forming_info = detect_buy_sell_points(
        bi_list, zhongshu, beichi, current_price, latest_date, df_macd)

    return {
        "merged_count": len(merged),
        "fenxing": fenxing,
        "fenxing_count": len(fenxing),
        "bi_list": bi_list,
        "bi_count": len(bi_list),
        "zhongshu": zhongshu,
        "zhongshu_count": len(zhongshu),
        "trend": trend,
        "beichi": beichi,
        "signals": signals,
        "forming": forming_info,
        "current_price": current_price,
        "last_date": df["date"].iloc[-1],
        "macd_latest": {
            "dif": df_macd["dif"].iloc[-1],
            "dea": df_macd["dea"].iloc[-1],
            "macd": df_macd["macd"].iloc[-1],
        },
    }
