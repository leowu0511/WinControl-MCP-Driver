# -*- coding: utf-8 -*-
"""
============================================================================
 WCMD 套件設定 (config.py)
============================================================================
 集中管理所有可透過環境變數覆寫的設定項，避免在主程式碼中散落 magic string。
 
 優先順序（高 → 低）：
   1. 命令列參數 (僅 CLI 模式)
   2. 環境變數 (WCMD_* 開頭，建議用)
   3. 環境變數 (VISION_* 開頭，相容舊名稱)
   4. 下方預設值
 
 環境變數一覽：
   WCMD_DATA_DIR          資料目錄 (預設 ~/.wcmd)
   WCMD_VISION_API_KEY    Vision Model API Key
   WCMD_VISION_BASE_URL   Vision Model API 端點
   WCMD_VISION_MODEL      Vision Model 名稱
============================================================================
"""

import os
from pathlib import Path


# ============================================================
# 資料目錄
# ============================================================
# 預設放在使用者家目錄下的 .wcmd/ 子目錄 (跨平台、跨帳號安全)
# 範例：Windows → C:\Users\xxx\.wcmd\
#       macOS/Linux → /home/xxx/.wcmd/
_DEFAULT_DATA_DIR = Path.home() / ".wcmd"

DATA_DIR: Path = Path(
    os.environ.get("WCMD_DATA_DIR", str(_DEFAULT_DATA_DIR))
).expanduser().resolve()

# 確保目錄存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 檔案路徑 (全部相對於 DATA_DIR)
# ============================================================
OUTPUT_IMAGE_PATH: str = str(DATA_DIR / "marked_screen.png")
COORD_MAP_PATH: str = str(DATA_DIR / "coord_map.json")
COORD_MAP_GRID_PATH: str = str(DATA_DIR / "coord_map_grid.json")


# ============================================================
# 截圖壓縮設定 (用於 Vision Model API 呼叫與 MCP 回傳)
# ============================================================
# 為什麼需要壓縮？
#   原生 PNG 截圖 (1920x1080 全螢幕) 約 3~5 MB，Base64 後約 4~7 MB 字串
#   這會在 Vision Model API 呼叫時消耗大量 Token (數十萬 token)
#
# 解法：強制轉 JPEG + 必要時縮放
#   - 寬度 > SCREENSHOT_MAX_WIDTH 時縮放至該寬度
#     (對 AI 辨識紅框+數字已足夠，更小也省 token)
#   - JPEG quality=SCREENSHOT_JPEG_QUALITY：
#     對 AI 識別綽綽有餘，比 q70 又省 30%
#   - 4K 螢幕的截圖 Base64 從 ~10MB 降到 ~80KB，省 99% token
SCREENSHOT_MAX_WIDTH: int = 1280
SCREENSHOT_JPEG_QUALITY: int = 60


# ============================================================
# Vision Model 連線設定
# ============================================================
# 解析優先順序：WCMD_* 環境變數 > VISION_* 環境變數 > 預設值
def _get_env(*names: str, default: str = "") -> str:
    """依序檢查多個環境變數名稱，回傳第一個有值的"""
    for name in names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return default


# 預設指向 OpenCode Go (Anthropic 相容模式) + Qwen3.7 Plus
# 推薦供應商 (依使用情境選用)：
#   OpenCode Go (Anthropic 格式)：https://opencode.ai/zen/go + qwen3.7-plus
#   OpenCode Zen (OpenAI 格式)  ：https://opencode.ai/zen/v1 + qwen3.6-plus
#   阿里雲 DashScope (OpenAI)   ：https://dashscope.aliyuncs.com/compatible-mode/v1 + qwen-vl-plus
#   OpenAI 官方                 ：https://api.openai.com/v1 + gpt-4o
#   Anthropic 官方              ：https://api.anthropic.com + claude-sonnet-4
VISION_API_KEY: str = _get_env("WCMD_VISION_API_KEY", "VISION_API_KEY", default="")
VISION_BASE_URL: str = _get_env(
    "WCMD_VISION_BASE_URL",
    "VISION_BASE_URL",
    default="https://opencode.ai/zen/go",
)
VISION_MODEL: str = _get_env(
    "WCMD_VISION_MODEL",
    "VISION_MODEL",
    default="qwen3.7-plus",
)


def is_vision_configured() -> bool:
    """檢查 Vision Model 是否已設定 (有 API Key 即可)"""
    return bool(VISION_API_KEY)


def get_vision_config() -> dict:
    """回傳目前 Vision Model 設定 (用於 debug 與 log)"""
    return {
        "api_key_set": bool(VISION_API_KEY),
        "api_key_preview": (VISION_API_KEY[:8] + "..." + VISION_API_KEY[-4:])
        if VISION_API_KEY and len(VISION_API_KEY) > 12
        else ("(set)" if VISION_API_KEY else "(empty)"),
        "base_url": VISION_BASE_URL,
        "model": VISION_MODEL,
        "data_dir": str(DATA_DIR),
    }
