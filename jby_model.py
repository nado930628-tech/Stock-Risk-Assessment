"""新式形態學判斷模型（硬性條件制）。

主判斷只看 60分K 的 6 項硬性條件：
  全部通過 → 符合，可購入；少 1~2 項 → 可觀察；其餘 → 不符合。
日K、週K 條件與風控警示不影響判斷，但沒通過或被觸發時會列進紅框提醒。
所有門檻集中在 PARAMS，方便日後調整。
"""
from dataclasses import dataclass, field

import pandas as pd

PARAMS = {
    "h_slope_bars": 20,         # 60分K：60MA 與幾根前比較（約 4 個交易日）
    "h_flat_tolerance": -0.003, # 60分K：60MA 跌幅不超過 0.3% 視為走平
    "h_base_bars": 40,          # 60分K：整理區間觀察根數（約 8 個交易日）
    "h_base_skip": 5,           # 60分K：觀察整理區間時略過最近幾根（突破那幾根）
    "h_base_ratio": 0.5,        # 60分K：至少一半時間在 60MA 與長均線之間
    "watch_max_miss": 2,        # 少幾項以內算「可觀察」
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
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)


@dataclass
class Result:
    status: str          # buy / watch / fail / insufficient
    title: str
    summary: str
    main: Group | None = None                       # 60分K 硬性條件
    refs: list = field(default_factory=list)        # 日K、週K 參考條件
    risks: list = field(default_factory=list)       # 風控警示文字
    daily: pd.DataFrame | None = None
    hourly: pd.DataFrame | None = None
    weekly: pd.DataFrame | None = None

    @property
    def misses(self) -> list:
        """日K、週K 沒通過的項目名稱。"""
        return [f"{g.name}：{c.name}" for g in self.refs for c in g.checks if c.passed is False]

    @property
    def alert_count(self) -> int:
        return len(self.misses) + len(self.risks)


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


# ---------- 60分K：硬性條件（主判斷） ----------
H_NAMES = [
    "股價站上 60MA（生命線）",
    "60MA 走平或上彎（不可下彎）",
    "長均線在 60MA 上方（上方有蓋子）",
    "240MA 在 120MA 上方（長均線由長到短排列）",
    "突破前在 60MA 與長均線之間整理（金包銀）",
    "股價突破 120MA 與 240MA（發動）",
]


def hourly_checks(h: pd.DataFrame | None, p: dict) -> tuple[list, str]:
    if h is None or len(h) < 250 or not _ok(h["MA240"].iloc[-1]):
        return [Check(n, None, "60分K 資料不足") for n in H_NAMES], "60分K 資料不足"
    t = h.iloc[-1]
    close, ma60, ma120, ma240 = t["Close"], t["MA60"], t["MA120"], t["MA240"]
    top = max(ma120, ma240)

    c1 = Check(H_NAMES[0], close > ma60, f"收盤 {close:.2f}，60MA {ma60:.2f}")

    prev = h["MA60"].iloc[-1 - p["h_slope_bars"]]
    slope = ma60 / prev - 1
    c2 = Check(H_NAMES[1], slope >= p["h_flat_tolerance"],
               f"60MA 與 {p['h_slope_bars']} 根前相比 {_pct(slope)}")

    c3 = Check(H_NAMES[2], top > ma60, f"長均線較高者 {top:.2f}，60MA {ma60:.2f}")
    c4 = Check(H_NAMES[3], ma240 > ma120, f"240MA {ma240:.2f}，120MA {ma120:.2f}")

    base = h.iloc[-p["h_base_bars"] - p["h_base_skip"]:-p["h_base_skip"]]
    upper = base[["MA120", "MA240"]].max(axis=1)
    inside = ((base["Close"] >= base["MA60"]) & (base["Close"] <= upper)).mean()
    c5 = Check(H_NAMES[4], inside >= p["h_base_ratio"],
               f"前 {p['h_base_bars']} 根中有 {inside * 100:.0f}% 時間在區間內"
               f"（需 {p['h_base_ratio'] * 100:.0f}% 以上）")

    c6 = Check(H_NAMES[5], close > top, f"收盤 {close:.2f}，長均線較高者 {top:.2f}")

    if c6.passed and c3.passed:
        stage = "突破發動（股價 > 長均線 > 60MA）"
    elif c1.passed and close <= top and c3.passed:
        stage = "發動前夾擠（長均線 > 股價 > 60MA）"
    elif c1.passed and not c3.passed:
        stage = "60MA 已在長均線之上，不是起漲點"
    else:
        stage = "金包銀尚未成形"
    return [c1, c2, c3, c4, c5, c6], stage


# ---------- 日K：確認趨勢（參考，不影響判斷） ----------
def daily_checks(d: pd.DataFrame, p: dict) -> list:
    t = d.iloc[-1]
    n = p["d_rise_days"]
    c1 = Check("股價站上 5MA（沒被壓著）", t["Close"] > t["MA5"],
               f"收盤 {t['Close']:.2f}，5MA {t['MA5']:.2f}")
    c2 = Check("5MA > 10MA > 20MA", t["MA5"] > t["MA10"] > t["MA20"],
               f"{t['MA5']:.2f} / {t['MA10']:.2f} / {t['MA20']:.2f}")
    short_min = min(t["MA5"], t["MA10"], t["MA20"])
    long_max = max(t["MA60"], t["MA120"])
    c3 = Check("短均線在 60MA、120MA 之上", short_min > long_max,
               f"短均線最低 {short_min:.2f}，60/120MA 較高者 {long_max:.2f}")
    rising = {m: d[f"MA{m}"].iloc[-1] > d[f"MA{m}"].iloc[-1 - n] for m in (5, 10, 20, 60)}
    c4 = Check("均線全部向上", all(rising.values()),
               "、".join(f"{m}MA{'↑' if r else '↓'}" for m, r in rising.items()))
    return [c1, c2, c3, c4]


# ---------- 週K：判斷位階（參考，不影響判斷） ----------
def weekly_checks(w: pd.DataFrame, p: dict) -> list:
    t = w.iloc[-1]
    if not _ok(t["MA20"]):
        return [Check("股價站上週 20MA", None, "週K 資料不足"),
                Check("離週 20MA 不遠（安全區）", None, "週K 資料不足")]
    bias = t["Close"] / t["MA20"] - 1
    c1 = Check("股價站上週 20MA", t["Close"] > t["MA20"],
               f"週收盤 {t['Close']:.2f}，週20MA {t['MA20']:.2f}")
    c2 = Check("離週 20MA 不遠（安全區）", 0 <= bias <= p["w_safe_bias"],
               f"距週20MA {_pct(bias)}（安全區 0~{p['w_safe_bias'] * 100:.0f}%）")
    return [c1, c2]


# ---------- 風控警示（不影響判斷） ----------
def risk_checks(d: pd.DataFrame, w: pd.DataFrame, h: pd.DataFrame | None, p: dict) -> list:
    out = []
    t = d.iloc[-1]

    if t["Close"] < t["MA5"] and t["MA5"] < d["MA5"].iloc[-2]:
        out.append("日K 跌破 5MA 且 5MA 下彎（蓋頭反壓），持有者應考慮出場")
    k = p["below5_days"]
    if (d["Close"].iloc[-k:] < d["MA5"].iloc[-k:]).all():
        out.append(f"日K 已連續 {k} 天以上站不回 5MA，符合硬性出場條件")
    if t["Close"] < t["MA60"]:
        out.append("日K 收盤在 60MA（生命線）之下")

    wt = w.iloc[-1]
    if _ok(wt["MA20"]):
        bias = wt["Close"] / wt["MA20"] - 1
        if bias > p["w_danger_bias"]:
            out.append(f"週K 漲離週20MA 太遠（{_pct(bias)}），可能是最後一波，只宜極短線")

    recent = d.iloc[-6:]
    hi60 = d["High"].iloc[-60:].max()
    for i in range(len(recent)):
        r = recent.iloc[i]
        if (r["Close"] < r["Open"] and r["Volume"] >= r["VMA20"] * p["big_vol_mult"]
                and r["High"] >= hi60 * (1 - p["high_zone"])):
            msg = f"{recent.index[i]:%m/%d} 高檔爆量收黑（收盤低於開盤）"
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
    main = Group("60分K", "找起漲點（金包銀）硬性條件", h_checks)
    refs = [Group("日K", "確認趨勢（正多頭開花）", daily_checks(d, p)),
            Group("週K", "判斷位階（避免買在天價）", weekly_checks(w, p))]
    risks = risk_checks(d, w, h, p)

    total = len(h_checks)
    if any(c.passed is None for c in h_checks):
        status, title = "insufficient", "⬜ 60分K 資料不足，無法判斷"
    elif main.passed == total:
        status, title = "buy", f"🟢 符合，可購入（{total}/{total}）"
    elif main.passed >= total - p["watch_max_miss"]:
        status, title = "watch", f"🟡 可觀察（{main.passed}/{total}）"
    else:
        status, title = "fail", f"🔴 不符合（{main.passed}/{total}）"

    res = Result(status, title, f"60分K：{stage}。", main, refs, risks, d, h, w)
    if res.alert_count:
        res.summary += f"另有 {res.alert_count} 項提醒，請看下方紅框。"
    return res
