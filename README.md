# db-export

透過 CLI 將既有資料庫的表結構匯出為 Word 資料字典。連線設定來自命令列，不讀取 `.env`，也不儲存密碼。文件固定文字使用簡體中文；資料庫中的名稱、註解及自訂標題保留原文。不另列主鍵順序，欄位表格保留主鍵標記。文件採 A4 橫向，包含總覽、欄位型別、主鍵、可空值、預設值、註解、索引、外鍵、唯一約束及檢查約束。

## 安裝

需要 Python 3.9 以上。在此目錄執行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[mysql]'
```

Windows PowerShell 啟用虛擬環境改用 `.venv\Scripts\Activate.ps1`。

依資料庫選擇安裝項目：

| 資料庫 | 安裝命令 | 額外要求 |
| --- | --- | --- |
| MySQL | `python -m pip install '.[mysql]'` | PyMySQL |
| PostgreSQL | `python -m pip install '.[postgres]'` | psycopg 3 |
| SQL Server | `python -m pip install '.[sqlserver]'` | 系統需另装 Microsoft ODBC Driver 18；TLS 設定依伺服器憑證配置 |
| Oracle | `python -m pip install '.[oracle]'` | 預設使用 python-oracledb Thin 模式，以 service name 連線 |
| SQLite | `python -m pip install .` | 指定既有資料庫檔案 |

安裝後可從任意目錄使用 `db-export`，也可執行 `python -m db_export`。如果已安裝 uv，可在此目錄直接使用 `uv run --extra mysql db-export ...`。

## 使用

### 互動模式

更新安裝後，可使用 `db-export --interactive` 逐步填寫連線資料；也可以在原命令加上 `-i`：

```sh
db-export -i --db-type mysql --host localhost --user scene_user \
  --database new_scene_chapter -o output/new_scene_chapter.docx
```

流程為選擇 schema、搜尋與勾選資料表、選擇附加內容、輸入輸出路徑及標題、確認匯出。指定 `--schema` 可跳過 schema 選擇。`--include`／`--exclude` 先限制候選表範圍。

| 操作 | 按鍵 |
| --- | --- |
| 搜尋表名或註解（不分大小寫，表名也支援 glob） | 搜尋框直接輸入 |
| 切換搜尋框與列表 | Tab；列表內 `/` 回到搜尋 |
| 移動／勾選 | ↑↓／空格 |
| 切換全部與已選視圖 | F2 |
| 選取所有符合目前篩選的項目 | F3 |
| 清除全部選取，包括隱藏項目 | F4 |
| 確认選取並下一步 | 列表內 Enter |
| 取消 | Ctrl+C |

搜尋框內 Enter 會移到列表；修改搜尋不會清除已選項目。資料表預設不勾選，必須至少選一張；附加內容預設全選，可以全部取消。可選內容為索引、外鍵、唯一約束、檢查約束；欄位與主鍵標記始終保留。先讀取表名與註解，確認選取後才讀取所選表的完整結構。

此版本的部分選擇以「資料表」及「附加內容」為單位，不提供逐欄位選取。互動模式需要真實終端，不接受管道輸入；原有非互動命令仍可用於自動化。輸出已存在時，可輸入新路徑或以 `--force` 重新執行。Ctrl+C／取消確認不會寫入文件。

### 非互動模式

MySQL，省略密碼參數會互動提示輸入：

```sh
db-export --db-type mysql --host 127.0.0.1 --port 3306 \
  --user reader --database app_db --output output/app_db.docx
```

PostgreSQL，指定 schema 與表名篩選：

```sh
db-export --db-type postgresql --host 127.0.0.1 \
  --user reader --database app_db --schema public \
  --include 'sys_*' --include 'order_*' --exclude '*_backup' \
  --title '系统数据字典' -o output/schema.docx
```

SQL Server：

```sh
db-export --db-type sqlserver --host localhost --user reader \
  --database app_db --schema dbo -o output/sqlserver.docx
```

Oracle，`--database` 表示 service name，schema 通常使用大寫：

```sh
db-export --db-type oracle --host localhost --user READER \
  --database FREEPDB1 --schema APP -o output/oracle.docx
```

SQLite：

```sh
db-export --db-type sqlite --database ./app.db -o output/sqlite.docx
```

也可提供 SQLAlchemy URL，與個別連線參數擇一使用：

```sh
db-export --url 'postgresql+psycopg://reader:password@localhost:5432/app_db' \
  --schema public -o output/schema.docx
```

URL 內密碼的 `@`、`/` 等特殊字元需要百分比編碼；分開使用 `--user`、`--password` 時不需要 URL 編碼。URL 模式使用 URL 中的完整認證，不再提示密碼。自動化可使用 `--password 'password'`，空密碼使用 `--password ''`。互動輸入可以避免密碼進入命令歷史及命令列參數。

`--include`、`--exclude` 是區分大小寫的 glob 表名比對，可重複指定；請用引號包住 `*`。未指定時匯出預設 schema 中的全部實體表；排除條件優先。指定的 include 若完全找不到表，會報錯。

輸出已存在時預設拒絕覆蓋；加 `--force` 才會取代。完整參數請執行 `db-export --help`。

## 範圍與限制

### Word 樣式與分頁

| 參數 | 效果 |
| --- | --- |
| `--theme classic` | 預設；深藍表頭、白字、灰白交錯底色，每張表另起一頁 |
| `--theme compact` | 縮小字級與儲存格間距，預設連續排版 |
| `--theme monochrome` | 灰階表頭與黑字，適合黑白列印，每張表另起一頁 |
| `--table-page-break` | 覆蓋樣式預設，每張表另起一頁 |
| `--no-table-page-break` | 覆蓋樣式預設，連續排版 |

```sh
db-export --db-type mysql --host localhost --user reader --database app_db \
  --theme classic --no-table-page-break -o output/schema.docx
```

互動模式也會詢問樣式與分頁方式。總覽包含欄位數，點擊表名可跳至章節（Word 中可能需要 Ctrl+點擊）。欄位名稱、型別與預設值採等寬字型，長內容可換行。表頭跨頁重複，普通資料列避免拆頁，極長說明允許跨頁。頁尾含文件簡稱與「第 X 頁／共 Y 頁」，Word 開啟或列印時更新頁碼欄位。

### 資料與相容性

- 僅透過 SQLAlchemy reflection 讀取結構，不查詢業務資料，也不修改表或註解。帳號需要目標 schema 的 metadata 讀取權限。
- 此版本匯出實體表，不含 view、stored procedure 或 ER 圖。多個 schema 請分別執行。
- 型別保留驅動提供的長度／精度。註解、自增、運算式索引和資料庫特有屬性的完整度取決於 SQLAlchemy dialect。尚未回傳的註解不會推測補寫。
- 驅動明確不支援的可選 metadata 會在終端及文件中提示；其他查詢錯誤會中止，避免產生看似完整的文件。
- 執行時不要同時修改資料庫結構；多次 metadata 查詢不保證取得跨資料庫一致快照。
- 文件中文字型使用 Microsoft YaHei，未安裝時由 Word 替代。可在 `document.py` 調整。
- 自動測試使用 SQLite；MySQL、PostgreSQL、SQL Server、Oracle 仍需在實際環境驗證連線及 metadata 相容性。

結束碼：`0` 成功、`1` 連線／依賴／I/O 失敗、`2` 參數或篩選錯誤、`130` 使用者取消。

連線或結構讀取失敗時，CLI 會顯示失敗階段及驅動原始原因，並遮蔽已知的帳號、密碼及 URL query 值，不輸出 SQLAlchemy 的 SQL／參數內容。請依新訊息確認原因；`OperationalError` 本身不足以判斷是否為密碼錯誤。回報問題時附上這兩行及移除認證資訊後的命令即可。

## 開發驗證

```sh
python -m pip install -e '.[test]'
python -m pytest
```

`cli.py` 處理參數與連線，`interactive.py` 處理搜尋與多選，`schema.py` 分別提供資料表目錄與完整結構讀取，`document.py` 負責 Word 排版。測試涵蓋真實 SQLite metadata、鍵盤互動、篩選後保留選取、Word 內容及 CLI 失敗時的輸出保護。
