# 系統架構 (Architecture)

## 三層能力模型 (Capability-Tiered)

WCMD 採用「能力分層」設計，讓 Agent 依自己的智慧程度選用合適工具：

```
┌──────────────────────────────────────────────────────────┐
│ Tier 3 委託層  execute_semantic_intent                   │
│   給「一句話意圖」，全自動完成                            │
│   內部：UIA → 標記截圖 → 問 Vision Model → 執行           │
│   適用：小型 LLM Agent (沒有視覺)                         │
│   需要：Vision API Key                                   │
├──────────────────────────────────────────────────────────┤
│ Tier 2 精確層  execute_exact_action                      │
│   接收明確 action + target_id/grid_id，直接執行          │
│   走 dispatcher，不過 AI API (零延遲、零成本)              │
│   適用：Agent 已知要點哪個元素                             │
│   需要：先呼叫 Tier 1 取得 coord_map                      │
├──────────────────────────────────────────────────────────┤
│ Tier 1 感知層  get_screen_state                          │
│   永遠先呼叫：取得 UI 文字清單 + 座標表 + (可選) 截圖     │
│   不會實際執行任何動作                                    │
│   回傳 JSON，Agent 可直接讀取做決策                       │
└──────────────────────────────────────────────────────────┘
```

---

## 工具 Schema 詳解

### `get_screen_state`

掃描桌面，回傳 UI 結構與座標表。

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `include_screenshot` | bool | `false` | 是否回傳 Base64 截圖 (PNG) |
| `use_grid` | bool | `false` | 強制走 Grid 模式 (略過 UIA) |
| `grid_rows` | int | `10` | Grid 模式的列數 (3~20) |
| `grid_cols` | int | `10` | Grid 模式的欄數 (3~20) |

**回傳**：
```json
{
  "mode": "uia" | "grid" | "empty",
  "element_count": 12,
  "text_list": ["[Test App] 確定 (id 0)", "[Test App] 取消 (id 1)"],
  "coord_map": { "0": [100, 50], "1": [200, 50] },
  "grid_map": null,
  "screenshot_base64": null,
  "screenshot_format": "png",
  "screenshot_path": null
}
```

**狀態副作用**：將 `coord_map` / `grid_map` 快取到 `_state`，供 `execute_exact_action` 使用。

---

### `execute_exact_action`

在已知座標時精確執行動作，**不呼叫 Vision API**。

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `action` | str | ✅ | 動作類型 (見下表) |
| `target_id` | int | 視動作 | UIA 模式下的元素編號 |
| `grid_id` | str | 視動作 | Grid 模式下的格子 (例如 "B3") |
| `text` | str | type | 要輸入的文字 |
| `keys` | str | hotkey | 熱鍵字串 (例如 "ctrl+c") |
| `direction` | str | scroll | "up"/"down"/"left"/"right" |
| `clicks` | int | scroll | 捲動格數 (1~50) |
| `start_id` / `end_id` | int | drag (UIA) | 拖曳起訖 |
| `start_grid_id` / `end_grid_id` | str | drag (Grid) | 拖曳起訖 (Grid 模式) |
| `dry_run` | bool | optional | 預演不執行 |

**支援動作**：
| action | 必要參數 | 說明 |
|---|---|---|
| `click` | target_id 或 grid_id | 左鍵單擊 |
| `double_click` | target_id 或 grid_id | 雙擊 |
| `right_click` | target_id 或 grid_id | 右鍵 |
| `type` | text | 鍵盤輸入 (Unicode 走剪貼簿) |
| `hotkey` | keys | 熱鍵組合 |
| `scroll` | direction (+ optional clicks) | 捲動 |
| `drag` | start + end | 拖曳 |

**回傳**：
```json
{
  "status": "ok" | "error",
  "action": "click",
  "message": "已在座標 (100, 50) 點擊",
  "coord": [100, 50]
}
```

---

### `execute_semantic_intent`

給一句話意圖，全自動完成。

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `instruction` | str | ✅ | 意圖字串 |
| `dry_run` | bool | optional | 預演不執行 |
| `force_grid` | bool | optional | 強制走 Grid 模式 |

**回傳**：
```json
{
  "status": "ok" | "error",
  "action": "click",
  "message": "已自動完成",
  "coord": [100, 50],
  "ai_reason": "這是確定按鈕",
  "mode_used": "uia" | "grid"
}
```

---

## 內部資料流

```
[AI Agent]
   │
   │ MCP JSON-RPC
   ▼
[MCP Server]  wcmd-mcp
   │
   │ imports
   ▼
[wcmd.engine]  engine.py (核心邏輯)
   ├─ get_clickable_elements() → uiautomation 抓 UI 樹
   ├─ generate_marked_screenshot() → pyautogui + Pillow 標記
   ├─ ask_vision_model() → Anthropic SDK / OpenAI SDK
   ├─ execute_action() → dispatcher
   └─ execute_click/type/hotkey/scroll/drag() → pyautogui / pyperclip
   │
   ▼
[Windows API]
   ├─ UI Automation (UI元素列舉)
   ├─ GDI (截圖)
   ├─ SendInput (滑鼠/鍵盤)
   └─ Clipboard (Unicode 輸入)
```

---

## 模組依賴

```
wcmd/
├── __init__.py        版本資訊
├── config.py          環境變數管理 (DATA_DIR, API Key, BASE_URL)
├── engine.py          核心引擎 (UIA + 標記 + Vision + dispatcher)
├── server.py          MCP Server 與 3 個工具
└── __main__.py        python -m wcmd 入口
```

**外部依賴**：
| 套件 | 用途 |
|---|---|
| `pyautogui` | 截圖、滑鼠、鍵盤 |
| `uiautomation` | Windows UI Automation |
| `Pillow` | 標記圖片 (紅框 + 編號) |
| `openai` | OpenAI 格式 API 呼叫 |
| `anthropic` | Anthropic 格式 API 呼叫 |
| `pyperclip` | Unicode 文字輸入 |
| `mcp` | MCP Server 框架 (FastMCP) |

---

## 退出碼約定 (CLI 模式)

`wcmd-cli` 退出碼：

| 碼 | 意義 |
|---|---|
| 0 | 動作成功 |
| 1 | 參數 / 環境錯誤 |
| 2 | AI 表示 NOT_FOUND |
| 3 | 動作執行失敗 |
| 4 | Vision Model 階段失敗 |
