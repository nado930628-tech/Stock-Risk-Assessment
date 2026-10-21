# 選股小幫手

輸入台股代號，依 60分K 硬性條件判斷是否可購入，日K、週K 與風控有狀況時以紅框提醒。僅供參考，不構成投資建議。

## 檔案

- `app.py`：網頁介面（Streamlit），分「個股分析」「我的收藏」「選股掃描」三頁
- `jby_model.py`：金包銀判斷邏輯，所有門檻都在最上方的 `PARAMS`
- `tw_data.py`：股票清單（證交所、櫃買中心 OpenAPI）與日線資料（Yahoo Finance）
- `requirements.txt`：需要的套件

## 部署成網址（一次性，約 10 分鐘）

1. 到 https://github.com 註冊或登入，按右上角「+」→「New repository」，名稱例如 `jinbaoyin`，選 Public，建立。
2. 在新 repo 頁面按「uploading an existing file」，把 `app.py`、`jby_model.py`、`tw_data.py`、`requirements.txt` 四個檔案拖進去，按「Commit changes」。
3. 到 https://share.streamlit.io 用 GitHub 帳號登入，按「Create app」→「Deploy a public app from GitHub」。
4. Repository 選剛剛的 repo，Branch 填 `main`，Main file path 填 `app.py`，可在 App URL 自訂網址（例如 `jinbaoyin-xxx`），按「Deploy」。
5. 等一兩分鐘出現頁面後，把網址傳給客戶，請她加到手機主畫面或瀏覽器書籤。

App 一段時間沒人用會休眠，打開時若看到「Yes, get this app back up」按一下，等約 30 秒即可。

## 功能說明

- **個股分析**：可輸入代號或中文名稱（例如「台積電」），按「⭐ 加入收藏」存起來。
- **我的收藏**：一鍵檢查全部收藏的股票，表格列出判斷結果，點選可看詳細分析。收藏存在該裝置的瀏覽器裡，換手機或電腦要重新加；清除瀏覽器資料也會一起清掉。
- **選股掃描**：從成交量前 100 名、前 300 名或全部上市櫃普通股中，列出「通過」與「部分通過」的股票，可排除有紅框提醒的。前 100 名約數十秒，全部約需數分鐘；結果會暫存 6 小時，同一天再掃會很快。若證交所 OpenAPI 連不上，會改用內建的 60 檔權值股清單。

## 在自己電腦上跑

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 判斷規則（60分K 硬性條件制）

門檻都在 `jby_model.py` 最上方的 `PARAMS`。

**60分K 硬性條件（決定結果）**

1. 股價 > 60MA
2. 60MA 與 20 根前相比跌幅 ≤ 0.3%（走平或上彎）
3. 120MA 或 240MA > 60MA，或與 60MA 差距在 1% 內（糾結也算有蓋子）
4. 最近第 6~45 根中，至少 50% 收盤落在 60/120/240MA 區間內（上下各放寬 2%）
5. 股價 > 120MA 與 240MA（突破發動）

🟢 5 項全過：符合，可購入　🟡 少 1~2 項：可觀察　🔴 其餘：不符合

**紅框提醒（不影響結果）**

- 60分K：240MA > 120MA（前面跌過一段）。沒通過的列進紅框。
- 日K：股價 > 5MA；5MA > 10MA > 20MA；5/10/20MA 都 > 60/120MA；5、10、20、60MA 都比 3 天前高。沒通過的列進紅框。
- 週K：股價 > 週20MA；距週20MA 0~10%。沒通過的列進紅框。
- 風控：日K 跌破 5MA 且 5MA 下彎；連續 3 天站不回 5MA；跌破日60MA；距週20MA 超過 20%；高檔爆量收黑後 3 天以上未創高。

60分K 資料來自 Yahoo，抓最近約半年，足夠計算 240MA。抓不到時顯示「資料不足」。

未納入：籌碼、基本面、消息面、產業形態對比。
