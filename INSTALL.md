# 詳細安裝指南 (INSTALL.md)

本文件針對每個 MCP Client 提供 step-by-step 設定。

---

## 共通前置作業

### 1. 確認 Python 版本

```bash
python --version
```

需要 **Python 3.10 或以上**。若沒安裝：
* Windows: <https://www.python.org/downloads/>
* macOS: `brew install python@3.11`

### 2. 確認 pip 可用

```bash
python -m pip --version
```

### 3. 安裝 WCMD

```bash
pip install git+https://github.com/leowu0511/WinControl-MCP-Driver.git
```

驗證安裝成功：
```bash
wcmd-mcp --help
# 或
python -c "import wcmd; print(wcmd.__version__)"
```

### 4. 取得 Vision Model API Key

選擇一個供應商（推薦 [OpenCode Go](https://opencode.ai/zen)）並取得 API Key。

> 💡 **還沒帳號？** 用邀請連結註冊 OpenCode Go，你我都各得 **$5** 額度：
> 👉 **<https://opencode.ai/go?ref=X0VQPG489J>**
>
> 為什麼推薦 OpenCode Go：預設支援 Qwen3.7 Plus、Anthropic 格式（與本套件預設相符）、額度比 OpenAI 官方便宜 5~10 倍。

---

## Claude Desktop

### 設定檔位置

| OS | 路徑 |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

> Windows 路徑通常展開為 `C:\Users\<你的使用者名稱>\AppData\Roaming\Claude\claude_desktop_config.json`

### 設定內容

```json
{
  "mcpServers": {
    "wcmd": {
      "command": "wcmd-mcp",
      "env": {
        "WCMD_VISION_API_KEY": "sk-xxxxxxxxxxxxxx",
        "WCMD_VISION_BASE_URL": "https://opencode.ai/zen/go",
        "WCMD_VISION_MODEL": "qwen3.7-plus"
      }
    }
  }
}
```

> 💡 `command: wcmd-mcp` 會自動找到 pip 安裝的 entry point，不需要寫絕對路徑。

### 重啟 Claude Desktop

關閉並重新開啟 Claude Desktop。

### 驗證

1. 點右下角「🔧 工具」圖示，應該看到 `wcmd` 與 3 個工具
2. 在對話框輸入：「列出螢幕上的可點擊元素」

---

## Cursor

### 設定方式

1. 開啟 Cursor
2. `Ctrl+Shift+P` → 輸入 `MCP` → 選 **「MCP: Open User Configuration File」**
3. 編輯 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "wcmd": {
      "command": "wcmd-mcp",
      "env": {
        "WCMD_VISION_API_KEY": "sk-xxxxxxxxxxxxxx",
        "WCMD_VISION_BASE_URL": "https://opencode.ai/zen/go",
        "WCMD_VISION_MODEL": "qwen3.7-plus"
      }
    }
  }
}
```

4. 重啟 Cursor

### 驗證

在 Cursor Chat 輸入：「用 WCMD 截圖並列出 UI 元素」

---

## Roo Code (VS Code)

### 設定方式 A：UI 設定

1. 開啟 VS Code，安裝 [Roo Code 擴充功能](https://marketplace.visualstudio.com/items?itemName=RooVeterinaryInc.roo-cline)
2. 點 Roo Code 面板右上角 ⚙️ 圖示
3. 點 **MCP Servers** → **Edit Global MCP**
4. 開啟 `mcp_settings.json` 加入：

```json
{
  "mcpServers": {
    "wcmd": {
      "command": "wcmd-mcp",
      "env": {
        "WCMD_VISION_API_KEY": "sk-xxxxxxxxxxxxxx",
        "WCMD_VISION_BASE_URL": "https://opencode.ai/zen/go",
        "WCMD_VISION_MODEL": "qwen3.7-plus"
      }
    }
  }
}
```

### 設定方式 B：專案層級 (推薦團隊使用)

在專案根目錄建立 `.roo/mcp.json`，同樣的內容。每個 clone 此專案的開發者都會自動載入。

### 重啟 VS Code

關閉所有 VS Code 視窗再重開。

### 驗證

在 Roo Code 對話框輸入：「list the WCMD tools」

---

## Cline (VS Code)

### 設定方式

1. 開啟 VS Code，安裝 [Cline 擴充功能](https://marketplace.visualstudio.com/items?itemName=saoudrizwan.claude-dev)
2. 點 Cline 面板右上角齒輪 → **MCP Servers** → **Configure MCP Servers**
3. 開啟 `cline_mcp_settings.json` 加入：

```json
{
  "mcpServers": {
    "wcmd": {
      "command": "wcmd-mcp",
      "env": {
        "WCMD_VISION_API_KEY": "sk-xxxxxxxxxxxxxx",
        "WCMD_VISION_BASE_URL": "https://opencode.ai/zen/go",
        "WCMD_VISION_MODEL": "qwen3.7-plus"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

> ⚠️ 保持 `autoApprove: []` 讓每次點擊都要你手動確認（安全考量）

### 重啟 VS Code

---

## Claude Code (Anthropic CLI)

### 安裝 Claude Code

<https://docs.claude.com/en/docs/claude-code/installation>

### 註冊 MCP Server

```bash
claude mcp add wcmd -- wcmd-mcp \
  -e WCMD_VISION_API_KEY=sk-xxxxxxxxxxxxxx \
  -e WCMD_VISION_BASE_URL=https://opencode.ai/zen/go \
  -e WCMD_VISION_MODEL=qwen3.7-plus
```

或編輯 `~/.claude.json`：

```json
{
  "mcpServers": {
    "wcmd": {
      "command": "wcmd-mcp",
      "env": {
        "WCMD_VISION_API_KEY": "sk-xxxxxxxxxxxxxx",
        "WCMD_VISION_BASE_URL": "https://opencode.ai/zen/go",
        "WCMD_VISION_MODEL": "qwen3.7-plus"
      }
    }
  }
}
```

### 驗證

```bash
claude mcp list
# 應該看到 wcmd 與 3 個工具
```

---

## 常見問題 (Troubleshooting)

### Q0: 安裝時 `WinError 5: 拒絕存取` (pydantic-core 衝突)

**症狀**：
```
ERROR: Could not install packages due to an OSError: [WinError 5] 拒絕存取:
'C:\Users\xxx\AppData\Local\Programs\Python\Python3xx\Lib\site-packages\~ydantic_core\_pydantic_core.cp310-win_amd64.pyd'
```

**原因**：你在用系統 Python，pip 想降版 `pydantic-core` (mcp 的傳遞依賴) → 需覆寫 `.pyd` 編譯檔 → Windows 拒絕。

**✅ 推薦：用虛擬環境**（最乾淨）：

```powershell
python -m venv C:\wcmd-venv
C:\wcmd-venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install git+https://github.com/leowu0511/WinControl-MCP-Driver.git
```

裝完後 MCP config 用絕對路徑：
```json
{
  "mcpServers": {
    "wcmd": {
      "command": "C:\\wcmd-venv\\Scripts\\wcmd-mcp.exe",
      "env": { "WCMD_VISION_API_KEY": "sk-..." }
    }
  }
}
```

**⚡ 快速：用 `--user` 旗標**（不需 venv）：
```bash
pip install --user git+https://github.com/leowu0511/WinControl-MCP-Driver.git
```

**🔧 強制解法**（上兩個都失敗時）：
1. 關閉所有 Python 相關程式（VS Code、Cursor、舊 MCP server）
2. **以系統管理員身分**重新開 PowerShell
3. 再跑 `pip install ...`

### Q1: `wcmd-mcp` 找不到指令

**原因**：pip 安裝到全域或虛擬環境，但目前 shell PATH 沒包含

**解法**：
```bash
# 確認 pip 裝在哪裡
which wcmd-mcp

# 如果在虛擬環境，要啟動該環境
# Windows
.\venv\Scripts\Activate.ps1
# macOS/Linux
source venv/bin/activate
```

或改用絕對路徑：
```json
{
  "command": "C:\\Users\\yourname\\venv\\Scripts\\wcmd-mcp.exe"
}
```

### Q2: `ModuleNotFoundError: No module named 'wcmd'`

**解法**：確認 `pip install` 與執行 MCP server 的 Python 是同一個：
```bash
which python
which pip
# 應該在同一個目錄下
```

### Q3: 出現 `ImportError: DLL load failed` (uiautomation 問題)

**原因**：常見於 Windows 上 Python 3.11+ 缺少 Visual C++ Runtime

**解法**：
1. 安裝 [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
2. 重新安裝 uiautomation：`pip install --force-reinstall uiautomation`

### Q4: 滑鼠/鍵盤沒反應

**可能原因**：
1. 沒有輔助使用權限（Windows 設定 → 隱私與安全性 → 輔助使用）
2. 防毒軟體阻擋
3. 焦點視窗不正確

**解法**：
```bash
# 改成乾跑模式測試
wcmd-cli "點擊確定" --dry-run
```

### Q5: Vision Model API 401/403

* 確認 `WCMD_VISION_API_KEY` 沒有多餘空白
* 確認供應商網址正確
* 確認帳號還有額度

### Q6: 截圖模糊 / 座標偏移

可能是 DPI 設定問題。先試試：
```bash
wcmd-cli "測試" --dry-run
# 觀察啟動時是否印出「DPI 感知設定：成功」
```

如果失敗，請回報 issue 並附上螢幕解析度 + Windows 縮放比例。

---

## 解除安裝

```bash
pip uninstall WCMD
# 刪除資料目錄
rm -rf ~/.wcmd   # macOS/Linux
rmdir /s /q %USERPROFILE%\.wcmd   # Windows
```

從 MCP Client 設定檔刪除 `wcmd` 區塊即可停用。
