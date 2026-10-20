import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from data import history, history_batch, hourly, name_of, resolve, stock_list
from model import evaluate

st.set_page_config(page_title="金包銀選股小幫手", page_icon="📈", layout="centered")

st.markdown("""
<style>
html, body, [class*="css"] { font-size: 18px; }
.big { font-size: 1.6rem; font-weight: 700; margin: .4rem 0; }
.disclaimer { color: #888; font-size: .85rem; }
</style>
""", unsafe_allow_html=True)

st.title("📈 金包銀選股小幫手")

# ---------- 收藏清單：存在這台裝置的瀏覽器裡 ----------
STORE_KEY = "jby_watch"
if "watch" not in st.session_state:
    saved = streamlit_js_eval(js_expressions=f"localStorage.getItem('{STORE_KEY}') || ''",
                              key="ls_get")
    if saved is not None:
        st.session_state.watch = [c for c in saved.split(",") if c]


def watchlist() -> list:
    return st.session_state.get("watch") or []


def set_watch(codes: list):
    st.session_state.watch = codes
    st.session_state.save_n = st.session_state.get("save_n", 0) + 1


def toggle_button(code: str, key: str):
    w = watchlist()
    if code in w:
        if st.button("☆ 取消收藏", key=key):
            set_watch([c for c in w if c != code])
            st.rerun()
    elif st.button("⭐ 加入收藏", key=key):
        set_watch(w + [code])
        st.rerun()


# ---------- 單檔分析畫面 ----------
def chart(d: pd.DataFrame, key: str, bars: int, weekly: bool = False):
    d = d.iloc[-bars:]
    x = d.index.strftime("%m/%d %H:%M") if not weekly and (d.index.hour != 0).any() \
        else d.index.strftime("%Y/%m/%d")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="K線", increasing_line_color="#e53935", decreasing_line_color="#2e7d32"))
    for n, color in [(5, "#ff9800"), (20, "#9c27b0"), (60, "#1e88e5"),
                     (120, "#8d6e63"), (240, "#616161")]:
        fig.add_trace(go.Scatter(x=x, y=d[f"MA{n}"], name=f"{n}MA",
                                 line=dict(width=2 if n == 60 else 1.2, color=color)))
    fig.update_layout(height=460, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=1.08))
    fig.update_xaxes(type="category", nticks=8)
    st.plotly_chart(fig, width="stretch", key=key)


def show_analysis(code: str, key: str):
    with st.spinner("抓取資料中…"):
        symbol, df = history(code)
        h = hourly(symbol) if symbol else None
    if df is None:
        st.error("查不到這檔股票，請確認代號或名稱是否正確。")
        return
    res = evaluate(df, h)
    st.markdown(f"**{code} {name_of(code)}**　資料日期：{df.index[-1]:%Y/%m/%d}　"
                f"收盤 {df['Close'].iloc[-1]:.2f}")
    toggle_button(code, key=f"{key}_fav")
    st.markdown(f'<div class="big">{res.title}</div>', unsafe_allow_html=True)
    st.write(res.summary)

    if res.risks:
        st.error("🚨 風控警示（硬性條件，不計分）\n\n" + "\n".join(f"- {r}" for r in res.risks))
    elif res.groups:
        st.success("✅ 風控條件目前都沒有觸發")

    for g in res.groups:
        st.subheader(f"{g.name}：{g.score} / {g.full} 分")
        st.caption(g.task)
        for c in g.checks:
            mark = "⬜" if c.passed is None else ("✅" if c.passed else "❌")
            st.markdown(f"{mark} **{c.name}**　{c.detail}")

    if res.daily is not None:
        options = ["日K", "週K"] + (["60分K"] if res.hourly is not None else [])
        pick = st.radio("圖表", options, horizontal=True, key=f"{key}_period")
        if pick == "日K":
            chart(res.daily, f"{key}_d", 180)
        elif pick == "週K":
            chart(res.weekly, f"{key}_w", 104, weekly=True)
        else:
            chart(res.hourly, f"{key}_h", 300)
        st.caption("藍色粗線是 60MA（生命線），棕色和灰色是 120MA、240MA（長均線）。")


# ---------- 多檔掃描 ----------
def scan(universe: pd.DataFrame) -> pd.DataFrame:
    rows = []
    symbols = [f"{c}.{m}" for c, m in zip(universe["code"], universe["market"])]
    names = dict(zip(universe["code"], universe["name"]))
    bar = st.progress(0.0, text="掃描中…")
    chunk = 50
    for i in range(0, len(symbols), chunk):
        part = tuple(symbols[i:i + chunk])
        days = history_batch(part)
        hours = history_batch(part, interval="60m")
        for sym, df in days.items():
            res = evaluate(df, hours.get(sym))
            if res.level == "insufficient":
                continue
            code = sym.split(".")[0]
            g = {x.name: x.score for x in res.groups}
            rows.append({
                "代號": code, "名稱": names.get(code, ""), "總分": res.score,
                "60分K": g["60分K"], "日K": g["日K"], "週K": g["週K"],
                "風控警示": len(res.risks), "收盤": round(df["Close"].iloc[-1], 2),
            })
        done = min(i + chunk, len(symbols))
        bar.progress(done / len(symbols), text=f"掃描中… {done}/{len(symbols)}")
    bar.empty()
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["總分", "風控警示"], ascending=[False, True])


def result_table(df: pd.DataFrame, key: str):
    st.dataframe(df, hide_index=True, width="stretch")
    opts = [f"{r['代號']} {r['名稱']}" for _, r in df.iterrows()]
    pick = st.selectbox("點選查看詳細分析", ["（請選擇）"] + opts, key=f"{key}_pick")
    if pick != "（請選擇）":
        show_analysis(pick.split()[0], key=f"{key}_detail")


tab_one, tab_fav, tab_scan = st.tabs(["🔍 個股分析", "⭐ 我的收藏", "🧭 選股掃描"])

with tab_one:
    st.caption("輸入台股代號或名稱，依 60分K、日K、週K 三個週期評分（滿分 100），並檢查風控警示。")
    with st.form("search"):
        q = st.text_input("股票代號或名稱", placeholder="例如 2330、台積電、聯電")
        if st.form_submit_button("開始分析", width="stretch") and q.strip():
            st.session_state.current = resolve(q) or "__notfound__"
    cur = st.session_state.get("current")
    if cur == "__notfound__":
        st.error("找不到這檔股票，請改用代號查詢（例如 2330）。")
    elif cur:
        show_analysis(cur, key="one")

with tab_fav:
    w = watchlist()
    if not w:
        st.info("還沒有收藏。分析個股時按「⭐ 加入收藏」，就會出現在這裡。收藏會記在這台手機或電腦的瀏覽器裡。")
    else:
        st.caption(f"共 {len(w)} 檔，按下面按鈕一次檢查全部收藏。")
        if st.button("檢查我的收藏", width="stretch", key="fav_run"):
            uni = stock_list()
            uni = pd.DataFrame({"code": w}).merge(uni, on="code", how="left")
            uni["market"] = uni["market"].fillna("TW")
            uni["name"] = uni["name"].fillna("")
            st.session_state.fav_result = scan(uni)
        res = st.session_state.get("fav_result")
        if res is not None and not res.empty:
            result_table(res[res["代號"].isin(w)], key="fav")
        with st.expander("管理收藏"):
            keep = st.multiselect("目前收藏（按 × 移除）", w, default=w, key="fav_edit",
                                  format_func=lambda c: f"{c} {name_of(c)}")
            if keep != w and st.button("儲存變更", key="fav_save"):
                set_watch(keep)
                st.rerun()

with tab_scan:
    st.caption("從一群股票裡，依三週期評分找出目前分數高的。60分K 資料較多，掃描會比較久。")
    scope = st.radio("掃描範圍", ["成交量前 100 名", "成交量前 300 名", "全部上市櫃（約需數分鐘）"],
                     key="scope")
    show = st.radio("顯示", ["80 分以上", "60 分以上", "全部"], horizontal=True, key="show")
    no_risk = st.checkbox("排除有風控警示的股票", value=True, key="no_risk")
    if st.button("開始掃描", width="stretch", key="scan_run"):
        uni = stock_list()
        n = {"成交量前 100 名": 100, "成交量前 300 名": 300}.get(scope, len(uni))
        st.session_state.scan_result = scan(uni.head(n))
    res = st.session_state.get("scan_result")
    if res is not None:
        if res.empty:
            st.warning("這次沒有抓到資料，請稍後再試。")
        else:
            min_score = {"80 分以上": 80, "60 分以上": 60}.get(show, 0)
            view = res[res["總分"] >= min_score]
            if no_risk:
                view = view[view["風控警示"] == 0]
            st.write(f"共掃描 {len(res)} 檔，符合條件 {len(view)} 檔。")
            if len(view):
                result_table(view, key="scan")

with st.expander("評分方式說明"):
    st.markdown("""
共 10 項條件，每項 10 分，滿分 100 分。

**60分K：找起漲點（金包銀），40 分**
- K棒站上 60MA（生命線）
- 60MA 走平或上彎，不可下彎
- 120MA 或 240MA 在 60MA 上方壓著（金包銀結構）
- K棒往上突破長均線（發動點）

**日K：確認趨勢（正多頭開花），40 分**
- K棒站上 5MA，沒有被蓋頭
- 5MA > 10MA > 20MA
- 5/10/20MA 都在 60MA、120MA 之上
- 5、10、20、60MA 全部向上

**週K：判斷位階（安全防護網），20 分**
- 週K站上週 20MA
- 距週 20MA 乖離在 0~10% 的安全區

**風控硬性條件（不計分，觸發就警示）**
- 日K 跌破 5MA 且 5MA 下彎（蓋頭反壓）
- 日K 連續 3 天站不回 5MA
- 日K 跌破 60MA
- 週K 正乖離過大（距週 20MA 超過 20%）
- 60分K 的 60MA 下彎
- 高檔爆量黑K、之後 3~4 天無法創高

🟢 80 分以上：高度符合　🟡 60~79 分：列入觀察　🔴 60 分以下：不符合
""")

st.markdown('<p class="disclaimer">本工具僅依歷史股價與均線做型態判斷，供參考使用，'
            '不構成任何投資建議。未納入籌碼、基本面與消息面，投資前請自行評估風險。'
            '資料來源：Yahoo Finance、證交所、櫃買中心，可能有延遲。</p>', unsafe_allow_html=True)

# 收藏有變動時寫回瀏覽器
if st.session_state.get("save_n"):
    csv = ",".join(watchlist())
    streamlit_js_eval(js_expressions=f"localStorage.setItem('{STORE_KEY}', '{csv}')",
                      key=f"ls_set_{st.session_state.save_n}")
