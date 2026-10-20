import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from data import history, history_batch, name_of, resolve, stock_list
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
def show_analysis(code: str, key: str):
    with st.spinner("抓取資料中…"):
        symbol, df = history(code)
    if df is None:
        st.error("查不到這檔股票，請確認代號或名稱是否正確。")
        return
    res = evaluate(df)
    name = name_of(code)
    st.markdown(f"**{code} {name}**　資料日期：{df.index[-1]:%Y/%m/%d}　"
                f"收盤 {df['Close'].iloc[-1]:.2f}")
    toggle_button(code, key=f"{key}_fav")
    st.markdown(f'<div class="big">{res.title}</div>', unsafe_allow_html=True)
    st.write(res.summary)

    if res.warnings:
        st.warning("⚠️ 出場警示（若已持有請留意）\n\n" + "\n".join(f"- {w}" for w in res.warnings))

    if res.checks:
        st.subheader("條件檢查")
        for c in res.checks:
            st.markdown(f"{'✅' if c.passed else '❌'} **{c.name}**　{c.detail}")

    if res.df is not None:
        d = res.df.iloc[-180:]
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
            name="K線", increasing_line_color="#e53935", decreasing_line_color="#2e7d32"))
        for n, color in [(5, "#ff9800"), (20, "#9c27b0"), (60, "#1e88e5"),
                         (120, "#8d6e63"), (240, "#616161")]:
            fig.add_trace(go.Scatter(x=d.index, y=d[f"MA{n}"], name=f"{n}MA",
                                     line=dict(width=2 if n == 60 else 1.2, color=color)))
        fig.update_layout(height=480, xaxis_rangeslider_visible=False,
                          margin=dict(l=10, r=10, t=30, b=10),
                          legend=dict(orientation="h", y=1.08))
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        st.plotly_chart(fig, width="stretch", key=f"{key}_chart")
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
        for sym, df in history_batch(part).items():
            res = evaluate(df)
            if res.signal == "insufficient":
                continue
            code = sym.split(".")[0]
            close = df["Close"].iloc[-1]
            rows.append({
                "代號": code, "名稱": names.get(code, ""), "判斷": res.title,
                "符合項數": sum(c.passed for c in res.checks),
                "收盤": round(close, 2),
                "距60MA": f"{(close / res.df['MA60'].iloc[-1] - 1) * 100:+.1f}%",
                "_signal": res.signal,
            })
        done = min(i + chunk, len(symbols))
        bar.progress(done / len(symbols), text=f"掃描中… {done}/{len(symbols)}")
    bar.empty()
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {"breakout": 0, "setup": 1, "none": 2, "extended": 3}
    out["_o"] = out["_signal"].map(order)
    return out.sort_values(["_o", "符合項數"], ascending=[True, False]).drop(columns="_o")


def result_table(df: pd.DataFrame, key: str):
    st.dataframe(df.drop(columns="_signal"), hide_index=True, width="stretch")
    opts = [f"{r['代號']} {r['名稱']}" for _, r in df.iterrows()]
    pick = st.selectbox("點選查看詳細分析", ["（請選擇）"] + opts, key=f"{key}_pick")
    if pick != "（請選擇）":
        show_analysis(pick.split()[0], key=f"{key}_detail")


tab_one, tab_fav, tab_scan = st.tabs(["🔍 個股分析", "⭐ 我的收藏", "🧭 選股掃描"])

with tab_one:
    st.caption("輸入台股代號或名稱，看看現在是不是「金包銀」的起漲進場點。")
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
    st.caption("從一群股票裡，找出目前符合金包銀條件的。")
    scope = st.radio("掃描範圍", ["成交量前 100 名", "成交量前 300 名", "全部上市櫃（約需數分鐘）"],
                     key="scope")
    show = st.radio("顯示", ["五項條件全符合 + 剛突破", "符合 4 項以上", "全部"],
                    horizontal=True, key="show")
    if st.button("開始掃描", width="stretch", key="scan_run"):
        uni = stock_list()
        n = {"成交量前 100 名": 100, "成交量前 300 名": 300}.get(scope, len(uni))
        st.session_state.scan_result = scan(uni.head(n))
    res = st.session_state.get("scan_result")
    if res is not None:
        if res.empty:
            st.warning("這次沒有抓到資料，請稍後再試。")
        else:
            if show.startswith("五項"):
                view = res[(res["符合項數"] == 5) | (res["_signal"] == "breakout")]
            elif show.startswith("符合 4"):
                view = res[res["符合項數"] >= 4]
            else:
                view = res
            st.write(f"共掃描 {len(res)} 檔，符合條件 {len(view)} 檔。")
            if len(view):
                result_table(view, key="scan")

with st.expander("什麼是金包銀？"):
    st.markdown("""
股票跌了一段後跌不下去，K 棒重新站上 **60MA（季線）**，而且 60MA 開始走平、準備上彎；
上方還有 **120MA、240MA** 壓著。K 棒在 60MA 和長均線之間來回震盪，就是「金包銀」。
等它往上突破長均線、均線由短到長排列向上，常會走出一段漲幅。

- 🟢 **金包銀成形**：型態到位、還沒突破，可以開始留意、分批布局
- 🟡 **剛突破長均線**：放量突破，是起漲訊號
- ⚪ **已多頭排列 / 乖離偏大**：已經漲上去了，不追高
- 🔴 **不符合**：條件還沒到齊

**出場警示**：高檔爆量黑K、之後 3~4 天無法創高、跌破 5MA 且 5MA 下彎、跌破 60MA。
""")

st.markdown('<p class="disclaimer">本工具僅依歷史股價與均線做型態判斷，供參考使用，'
            '不構成任何投資建議。未納入籌碼、基本面與消息面，投資前請自行評估風險。'
            '資料來源：Yahoo Finance、證交所、櫃買中心，可能有延遲。</p>', unsafe_allow_html=True)

# 收藏有變動時寫回瀏覽器
if st.session_state.get("save_n"):
    csv = ",".join(watchlist())
    streamlit_js_eval(js_expressions=f"localStorage.setItem('{STORE_KEY}', '{csv}')",
                      key=f"ls_set_{st.session_state.save_n}")
