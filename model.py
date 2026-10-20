"""新式形態學三週期評分模型。

60分K（找起漲點）4 項、日K（確認趨勢）4 項、週K（判斷位階）2 項，
共 10 項、每項 10 分，滿分 100。第四類「風控硬性條件」不計分，只發警示。
所有門檻集中在 PARAMS，方便日後調整。
"""
from dataclasses import dataclass, field

import pandas as pd

PARAMS = {
    "h_slope_bars": 20,         # 60分K：60MA 與幾根前比較（約 4 個交易日）
    "h_flat_tolerance": -0.003, # 60分K：60MA 跌幅不超過 0.3% 視為走平
    "d_rise_days": 3,           # 日K：均線與幾天前比較，判斷是否向上
    "w_safe_bias": 0.10,        # 週K：距週20MA 乖離 10% 內算安全區
    "w_danger_bias": 0.20,      # 週K：距週20MA 乖離超過 20% 算危險區
    "below5_days": 3,           # 日K：跌破 5MA 連續幾天站不回算硬性出場
    "big_vol_mult": 2.0,        # 爆量：成交量 >= 20 日均量 × 2
    "high_zone": 0.05,          # 距近 60 日高點 5% 內算高檔
}

MA_LIST = (5, 10, 20, 60, 120, 240)


@dataclass
class Check:
    name: str
    passed: bool | None   # None = 資料不足
    detail: str


@dataclass
class Group:
    name: str
    task: str
    checks: list

    @property
    def score(self) -> int:
        return sum(10 for c in self.checks if c.passed)

    @property
    def full(self) -> int:
        return 10 * len(self.checks)


@dataclass
class Result:
    level: str          # strong / watch / weak / insufficient
    title: str
    summary: str
    score: int = 0
    groups: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    daily: pd.DataFrame | None = None
    hourly: pd.DataFrame | None = None
    weekly: pd.DataFrame | None = None


def add_ma(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for n in MA_LIST:
        df[f"MA{n}"] = df["Close"].rolling(n).mean()
    df["VMA20"] = df["Volume"].rolling(20).mean()
    return df


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    w = daily.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min",
                                     "Close": "last", "Volume": "sum"}).dropna()
    return add_ma(w)


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _ok(x) -> bool:
    return x is not None and pd.notna(x)


# ---------- 60分K：找起漲點（金包銀） ----------
def hourly_checks(h: pd.DataFrame | None, p: dict) -> tuple[list, str]:
    names = ["K棒站上 60MA（生命線）", "60MA 走平或上彎", "長均線在 60MA 上方（金包銀結構）",
             "K棒突破長均線（發動）"]
    if h is None or len(h) < 80:
        return [Check(n, None, "60分K 資料不足") for n in names], "資料不足"
    t = h.iloc[-1]
    close, ma60 = t["Close"], t["MA60"]
    longs = [m for m in (t["MA120"], t["MA240"]) if _ok(m)]

    c1 = Check(names[0], close > ma60, f"收盤 {close:.2f}，60MA {ma60:.2f}")

    prev = h["MA60"].iloc[-1 - p["h_slope_bars"]]
    slope = ma60 / prev - 1 if _ok(prev) else 0
    c2 = Check(names[1], slope >= p["h_flat_tolerance"],
               f"60MA 與 {p['h_slope_bars']} 根前相比 {_pct(slope)}")

    over = [m for m in longs if m > ma60]
    long_txt = "、".join(f"{n}MA {t[f'MA{n}']:.2f}" for n in (120, 240) if _ok(t[f"MA{n}"]))
    c3 = Check(names[2], bool(over), long_txt or "長均線資料不足")

    top = max(longs) if longs else None
    c4 = Check(names[3], bool(over) and top is not None and close > top,
               f"收盤 {close:.2f}，長均線最高 {top:.2f}" if top else "長均線資料不足")

    if c4.passed:
        stage = "突破發動（K棒 > 長均線 > 60MA）"
    elif c1.passed and c3.passed:
        stage = "發動前夾擠（長均線 > K棒 > 60MA）"
    elif c1.passed and not over:
        stage = "已在長均線之上，不是起漲點"
    else:
        stage = "金包銀尚未成形"
    return [c1, c2, c3, c4], stage


# ---------- 日K：確認趨勢（正多頭開花） ----------
def daily_checks(d: pd.DataFrame, p: dict) -> list:
    t = d.iloc[-1]
    n = p["d_rise_days"]
    c5 = Check("K棒站上 5MA（未被蓋頭）", t["Close"] > t["MA5"],
               f"收盤 {t['Close']:.2f}，5MA {t['MA5']:.2f}")
    c6 = Check("5MA > 10MA > 20MA", t["MA5"] > t["MA10"] > t["MA20"],
               f"{t['MA5']:.2f} / {t['MA10']:.2f} / {t['MA20']:.2f}")
    short_min = min(t["MA5"], t["MA10"], t["MA20"])
    long_max = max(t["MA60"], t["MA120"])
    c7 = Check("短均線在 60MA、120MA 之上", short_min > long_max,
               f"短均線最低 {short_min:.2f}，60/120MA 最高 {long_max:.2f}")
    rising = {m: d[f"MA{m}"].iloc[-1] > d[f"MA{m}"].iloc[-1 - n] for m in (5, 10, 20, 60)}
    c8 = Check("均線全部向上發散", all(rising.values()),
               "、".join(f"{m}MA{'↑' if r else '↓'}" for m, r in rising.items()))
    return [c5, c6, c7, c8]


# ---------- 週K：判斷位階（安全防護網） ----------
def weekly_checks(w: pd.DataFrame, p: dict) -> list:
    t = w.iloc[-1]
    if not _ok(t["MA20"]):
        return [Check("週K站上週 20MA", None, "週K 資料不足"),
                Check("週K乖離在安全區", None, "週K 資料不足")]
    bias = t["Close"] / t["MA20"] - 1
    c9 = Check("週K站上週 20MA", t["Close"] > t["MA20"],
               f"週收盤 {t['Close']:.2f}，週20MA {t['MA20']:.2f}")
    c10 = Check("週K乖離在安全區", 0 <= bias <= p["w_safe_bias"],
                f"距週20MA {_pct(bias)}（安全區 0~{p['w_safe_bias'] * 100:.0f}%）")
    return [c9, c10]


# ---------- 第四類：風控硬性條件（只警示） ----------
def risk_checks(d: pd.DataFrame, w: pd.DataFrame, h: pd.DataFrame | None, p: dict) -> list:
    out = []
    t = d.iloc[-1]

    if t["Close"] < t["MA5"] and t["MA5"] < d["MA5"].iloc[-2]:
        out.append("日K 蓋頭反壓：跌破 5MA 且 5MA 下彎，持有者應考慮出場")
    k = p["below5_days"]
    if (d["Close"].iloc[-k:] < d["MA5"].iloc[-k:]).all():
        out.append(f"日K 已連續 {k} 天以上站不回 5MA，符合硬性出場條件")
    if t["Close"] < t["MA60"]:
        out.append("日K 收盤在 60MA（生命線）之下")

    wt = w.iloc[-1]
    if _ok(wt["MA20"]):
        bias = wt["Close"] / wt["MA20"] - 1
        if bias > p["w_danger_bias"]:
            out.append(f"週K 正乖離過大（距週20MA {_pct(bias)}），可能是最後一波，只宜極短線")

    if h is not None and len(h) > p["h_slope_bars"] + 1:
        prev = h["MA60"].iloc[-1 - p["h_slope_bars"]]
        if _ok(prev) and h["MA60"].iloc[-1] / prev - 1 < p["h_flat_tolerance"]:
            out.append("60分K 的 60MA 正在下彎，金包銀不成立")

    recent = d.iloc[-6:]
    hi60 = d["High"].iloc[-60:].max()
    for i in range(len(recent)):
        r = recent.iloc[i]
        if (r["Close"] < r["Open"] and r["Volume"] >= r["VMA20"] * p["big_vol_mult"]
                and r["High"] >= hi60 * (1 - p["high_zone"])):
            msg = f"{recent.index[i]:%m/%d} 出現高檔爆量黑K"
            after = len(recent) - 1 - i
            if after >= 3 and recent["High"].iloc[i + 1:].max() <= r["High"]:
                msg += f"，之後 {after} 天沒有創高，上攻無力"
            out.append(msg)
            break
    return out


def evaluate(daily: pd.DataFrame, hourly: pd.DataFrame | None = None,
             p: dict = PARAMS) -> Result:
    if daily is None or len(daily) < 130:
        return Result("insufficient", "資料不足",
                      "上市時間太短或查無資料，至少需要約半年的日線資料。")

    d = add_ma(daily)
    w = to_weekly(daily)
    h = add_ma(hourly) if hourly is not None and len(hourly) else None

    h_checks, stage = hourly_checks(h, p)
    groups = [
        Group("60分K", "找起漲點（金包銀）", h_checks),
        Group("日K", "確認趨勢（正多頭開花）", daily_checks(d, p)),
        Group("週K", "判斷位階（安全防護網）", weekly_checks(w, p)),
    ]
    score = sum(g.score for g in groups)
    risks = risk_checks(d, w, h, p)

    if score >= 80:
        level, title = "strong", f"🟢 {score} 分　高度符合"
    elif score >= 60:
        level, title = "watch", f"🟡 {score} 分　部分符合，列入觀察"
    else:
        level, title = "weak", f"🔴 {score} 分　目前不符合"
    summary = f"60分K：{stage}。"
    if risks:
        summary += f"另有 {len(risks)} 項風控警示，請先看下方紅框。"

    return Result(level, title, summary, score, groups, risks, d, h, w)
