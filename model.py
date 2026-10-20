"""金包銀模型：用日線資料判斷是否為起漲進場點，並檢查出場警示。

所有門檻集中在 PARAMS，方便日後調整。
"""
from dataclasses import dataclass, field

import pandas as pd

PARAMS = {
    "drop_lookback": 250,      # 回看約一年找「先跌」
    "min_drop": 0.15,          # 從高點回落至少 15%
    "base_window": 20,         # 盤整區間觀察天數
    "max_range": 0.15,         # 盤整區間高低差上限 15%
    "slope_days": 10,          # 60MA 斜率比較天數
    "flat_tolerance": -0.005,  # 60MA 10 天內跌幅不超過 0.5% 視為走平
    "breakout_days": 5,        # 幾天內突破長均線算「剛突破」
    "vol_mult": 1.5,           # 突破時成交量 >= 20 日均量 × 1.5
    "max_bias": 0.10,          # 收盤距 60MA 乖離上限（超過算追高）
    "big_vol_mult": 2.0,       # 爆量定義：成交量 >= 20 日均量 × 2
    "high_zone": 0.05,         # 距近 60 日高點 5% 內算高檔
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Result:
    signal: str          # setup / breakout / extended / none / insufficient
    title: str
    summary: str
    checks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    df: pd.DataFrame | None = None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for n in (5, 10, 20, 60, 120, 240):
        df[f"MA{n}"] = df["Close"].rolling(n).mean()
    df["VMA20"] = df["Volume"].rolling(20).mean()
    return df


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def evaluate(raw: pd.DataFrame, p: dict = PARAMS) -> Result:
    if raw is None or len(raw) < 130:
        return Result("insufficient", "資料不足",
                      "上市時間太短或查無資料，至少需要約半年的日線資料。")

    df = add_indicators(raw)
    t = df.iloc[-1]
    close, ma60 = t["Close"], t["MA60"]
    ma120 = t["MA120"]
    ma240 = t["MA240"] if pd.notna(t["MA240"]) else None
    longs = [m for m in (ma120, ma240) if m is not None and pd.notna(m)]

    # 1. 先跌後止跌
    look = df.iloc[-p["drop_lookback"]:]
    peak_idx = look["High"].idxmax()
    after_peak = look.loc[peak_idx:]
    drop = 1 - after_peak["Low"].min() / look.loc[peak_idx, "High"]
    recent_low = df["Low"].iloc[-p["base_window"]:].min()
    prior_low = df["Low"].iloc[-60:-p["base_window"]].min()
    stop_falling = recent_low >= prior_low * 0.99
    c1 = Check("先跌後止跌", drop >= p["min_drop"] and stop_falling,
               f"近{p['drop_lookback']}日從高點最大回落 {_pct(drop)}；"
               f"近{p['base_window']}日{'沒有' if stop_falling else '仍有'}再破前低")

    # 2. 站上 60MA
    c2 = Check("站上生命線（60MA）", close > ma60,
               f"收盤 {close:.2f}，60MA {ma60:.2f}")

    # 3. 60MA 走平或上彎
    ma60_prev = df["MA60"].iloc[-1 - p["slope_days"]]
    slope = ma60 / ma60_prev - 1
    c3 = Check("60MA 走平或上彎", slope >= p["flat_tolerance"],
               f"60MA 與 {p['slope_days']} 天前相比 {'+' if slope >= 0 else ''}{_pct(slope)}"
               + ("（上彎）" if slope > 0.002 else "（走平）" if slope >= p["flat_tolerance"] else "（下彎）"))

    # 4. 長均線壓在 60MA 上方
    over = [m for m in longs if m > ma60]
    long_txt = f"120MA {ma120:.2f}" + (f"、240MA {ma240:.2f}" if ma240 else "（240MA 資料不足）")
    c4 = Check("長均線在上方壓著", len(over) > 0, long_txt)

    # 5. 盤整區間
    base = df.iloc[-p["base_window"]:]
    rng = base["High"].max() / base["Low"].min() - 1
    c5 = Check("盤整震盪", rng <= p["max_range"],
               f"近{p['base_window']}日高低差 {_pct(rng)}（上限 {_pct(p['max_range'])}）")

    checks = [c1, c2, c3, c4, c5]

    # 是否剛突破上方長均線
    cap = min(over) if over else (max(longs) if longs else None)
    breakout = False
    if longs:
        top = max(longs)
        win = df.iloc[-p["breakout_days"] - 1:]
        long_series = df[["MA120", "MA240"]].max(axis=1).iloc[-p["breakout_days"] - 1:]
        was_below = (win["Close"].iloc[:-1] <= long_series.iloc[:-1]).any()
        vol_ok = t["Volume"] >= t["VMA20"] * p["vol_mult"] or \
            (win["Volume"].iloc[1:] >= win["VMA20"].iloc[1:] * p["vol_mult"]).any()
        breakout = close > top and was_below and vol_ok

    bias = close / ma60 - 1
    stack = [t["MA5"], t["MA10"], t["MA20"], ma60, ma120] + ([ma240] if ma240 else [])
    bull_stack = all(a > b for a, b in zip(stack, stack[1:]))

    warnings = exit_warnings(df, p)

    base_ok = c1.passed and c2.passed and c3.passed
    if breakout and c2.passed and c3.passed:
        if bias <= p["max_bias"]:
            res = Result("breakout", "🟡 剛突破長均線，起漲訊號",
                         f"股價在 {p['breakout_days']} 天內放量突破上方長均線，距 60MA 乖離 {_pct(bias)}，尚未過度追高。")
        else:
            res = Result("extended", "⚪ 已突破但乖離偏大",
                         f"已突破長均線，但距 60MA 乖離 {_pct(bias)}，超過 {_pct(p['max_bias'])}，進場容易買在短線高點。")
    elif base_ok and c4.passed and c5.passed and cap is not None and close < cap:
        res = Result("setup", "🟢 金包銀成形，可留意布局",
                     f"股價在 60MA（{ma60:.2f}）與上方長均線（{cap:.2f}）之間整理，符合起漲前的型態。")
    elif bull_stack:
        res = Result("extended", "⚪ 已多頭排列，非起漲點",
                     f"均線已由短到長向上排列，行情已發動。距 60MA 乖離 {_pct(bias)}，不建議追高。")
    else:
        passed = sum(c.passed for c in checks)
        res = Result("none", "🔴 目前不符合金包銀",
                     f"五項條件符合 {passed} 項，建議放入觀察名單，等條件到齊再看。")

    res.checks, res.warnings, res.df = checks, warnings, df
    return res


def exit_warnings(df: pd.DataFrame, p: dict = PARAMS) -> list:
    """回傳出場警示文字清單（以最新一天為準）。"""
    out = []
    t = df.iloc[-1]
    recent = df.iloc[-6:]

    # 高檔爆量黑K（近 5 天內）
    hi60 = df["High"].iloc[-60:].max()
    for i in range(len(recent)):
        r = recent.iloc[i]
        if (r["Close"] < r["Open"] and r["Volume"] >= r["VMA20"] * p["big_vol_mult"]
                and r["High"] >= hi60 * (1 - p["high_zone"])):
            days_after = len(recent) - 1 - i
            msg = f"{recent.index[i]:%m/%d} 出現高檔爆量黑K，進入警戒"
            if days_after >= 3 and recent["High"].iloc[i + 1:].max() <= r["High"]:
                msg += f"；之後 {days_after} 天都沒有創高，上攻無力"
            out.append(msg)
            break

    # 跌破 5MA 且 5MA 下彎
    if t["Close"] < t["MA5"] and t["MA5"] < df["MA5"].iloc[-2]:
        out.append("跌破 5 日均線且 5MA 下彎（蓋頭反壓），短線應考慮出場")

    # 跌破 60MA
    if t["Close"] < t["MA60"] and df["Close"].iloc[-2] >= df["MA60"].iloc[-2]:
        out.append("今日跌破 60MA（生命線）")
    return out
