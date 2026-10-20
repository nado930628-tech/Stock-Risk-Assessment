"""資料來源：股票清單（證交所/櫃買中心 OpenAPI）與日線（Yahoo Finance）。"""
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

TWSE_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_ALL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

# OpenAPI 連不上時的備用清單（權值股為主）
FALLBACK = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電", "2382": "廣達",
    "2891": "中信金", "2881": "富邦金", "2882": "國泰金", "2303": "聯電", "2412": "中華電",
    "3711": "日月光投控", "2886": "兆豐金", "2884": "玉山金", "1216": "統一", "2885": "元大金",
    "2357": "華碩", "2892": "第一金", "3034": "聯詠", "2345": "智邦", "2002": "中鋼",
    "5880": "合庫金", "2880": "華南金", "2887": "台新金", "2301": "光寶科", "3231": "緯創",
    "2883": "開發金", "2603": "長榮", "1303": "南亞", "3008": "大立光", "2890": "永豐金",
    "2379": "瑞昱", "6669": "緯穎", "1301": "台塑", "2395": "研華", "4938": "和碩",
    "3045": "台灣大", "2912": "統一超", "5871": "中租-KY", "2207": "和泰車", "1101": "台泥",
    "6505": "台塑化", "2327": "國巨", "3661": "世芯-KY", "3017": "奇鋐", "2059": "川湖",
    "2609": "陽明", "2615": "萬海", "2408": "南亞科", "3037": "欣興", "3443": "創意",
    "2376": "技嘉", "2344": "華邦電", "2618": "長榮航", "3481": "群創", "2409": "友達",
    "6488": "環球晶", "8046": "南電", "2449": "京元電子", "3533": "嘉澤", "2368": "金像電",
}
FALLBACK_OTC = {"6488"}


def _num(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return 0.0


@st.cache_data(ttl=86400, show_spinner=False)
def stock_list() -> pd.DataFrame:
    """回傳 code / name / market / volume（今日成交股數），只保留 4 碼普通股。"""
    rows = []
    try:
        for r in requests.get(TWSE_ALL, timeout=15).json():
            rows.append((r.get("Code"), r.get("Name"), "TW", _num(r.get("TradeVolume"))))
    except Exception:
        pass
    try:
        for r in requests.get(TPEX_ALL, timeout=15).json():
            rows.append((r.get("SecuritiesCompanyCode"), r.get("CompanyName"), "TWO",
                         _num(r.get("TradingShares"))))
    except Exception:
        pass
    df = pd.DataFrame(rows, columns=["code", "name", "market", "volume"])
    df = df[df["code"].astype(str).str.fullmatch(r"[1-9]\d{3}")]
    if df.empty:
        df = pd.DataFrame([(c, n, "TWO" if c in FALLBACK_OTC else "TW", 0.0)
                           for c, n in FALLBACK.items()],
                          columns=["code", "name", "market", "volume"])
    return df.drop_duplicates("code").sort_values("volume", ascending=False).reset_index(drop=True)


def name_of(code: str) -> str:
    hit = stock_list().query("code == @code")
    return hit["name"].iloc[0] if len(hit) else FALLBACK.get(code, "")


def resolve(query: str) -> str | None:
    """把使用者輸入（代號或中文名稱）轉成 4 碼代號。"""
    q = query.strip().upper().replace(".TWO", "").replace(".TW", "")
    if q.isdigit():
        return q
    lst = stock_list()
    exact = lst[lst["name"] == q]
    if len(exact):
        return exact["code"].iloc[0]
    part = lst[lst["name"].str.contains(q, regex=False, na=False)]
    if len(part):
        return part["code"].iloc[0]
    for c, n in FALLBACK.items():
        if q in n:
            return c
    return None


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def history(code: str):
    """單檔日線，先試上市 .TW 再試上櫃 .TWO。回傳 (symbol, df)。"""
    for suffix in (".TW", ".TWO"):
        df = yf.Ticker(code + suffix).history(period="3y", auto_adjust=False)
        if not df.empty:
            return code + suffix, _clean(df)
    return None, None


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def history_batch(symbols: tuple) -> dict:
    """批次下載多檔日線，回傳 {symbol: df}。"""
    out = {}
    raw = yf.download(list(symbols), period="2y", auto_adjust=False, group_by="ticker",
                      threads=True, progress=False)
    if raw is None or raw.empty:
        return out
    for s in symbols:
        try:
            df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = _clean(df)
            if len(df):
                out[s] = df
        except KeyError:
            continue
    return out
