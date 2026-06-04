# -*- coding: utf-8 -*-
"""
============================================================================
 WCMD MCP Server (wcmd.server)
============================================================================
 為 AI Agent 提供「視覺操控 Windows UI」的能力。
 採用「能力分層 (Capability-Tiered)」設計，提供 3 個 MCP Tools：

   ┌─────────────────────────────────────────────────────────────┐
   │ Tier 1 感知層  get_screen_state                              │
   │   - 掃描螢幕、回傳文字化 UI 清單 + (可選) Base64 截圖        │
   │   - 結果會「快取」給後續 execute_exact_action 使用           │
   ├─────────────────────────────────────────────────────────────┤
   │ Tier 2 精確層  execute_exact_action                          │
   │   - 接收明確的 action + 座標/ID，直接 PyAutoGUI 執行         │
   │   - 走 dispatcher，不呼叫 AI API (零延遲、零成本)            │
   ├─────────────────────────────────────────────────────────────┤
   │ Tier 3 委託層  execute_semantic_intent                       │
   │   - 給無視覺模型使用：全自動 (抓圖 → 問 Qwen → 執行)         │
   │   - 內部呼叫 VISION_API_KEY / VISION_BASE_URL 環境變數       │
   └─────────────────────────────────────────────────────────────┘

 啟動方式：
     python mcp_server.py
   (使用 stdio transport，適合本機 Agent 呼叫)

 Claude Desktop / Cursor / Cline 設定範例：
     {
       "mcpServers": {
         "wcmd": {
           "command": "wcmd-mcp",
           "env": {
             "WCMD_VISION_API_KEY": "sk-xxxxxxxxxxxxxx"
           }
         }
       }
     }
         }
       }
     }
============================================================================
"""

# ============================================================
# 套件引入與環境設定
# ============================================================
import base64
import io
import json
import os
import sys
import logging
from typing import Optional

from PIL import Image  # 用於截圖壓縮 (JPEG + resize)

# ★ 重要：所有 log 走 stderr (stdout 是 MCP 通訊用，不能混用)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("wcmd-mcp")

# MCP 套件 (官方 SDK)
try:
    from mcp.server.fastmcp import FastMCP
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    FastMCP = None  # type: ignore
    logger.error("mcp 套件未安裝，請先執行：pip install mcp")

# WinControl MCP Driver 引擎 (同套件內的 engine)
from wcmd import engine
from wcmd import config as wcmd_config


# ============================================================
# MCP Server 全域狀態 (跨工具呼叫保留)
# ============================================================
# 為什麼需要狀態？
#   get_screen_state 掃描後產生的 coord_map / grid_map 必須快取，
#   之後 execute_exact_action 才能從同一份快取查表取得座標。
#   若使用者先跑 UIA 模式再跑 Grid 模式，狀態會被覆寫。
_state: dict = {
    "mode": None,                # "uia" | "grid" | "empty" | None
    "coord_map": {},             # UIA 模式：{int: (x, y)}
    "grid_map": {},              # Grid 模式：{str: (x, y)}
    "last_screenshot_path": None,
    "last_text_list": None,      # 上次掃描的文字清單 (供 Agent 查閱)
}


def _reset_state():
    """重置所有快取"""
    _state["mode"] = None
    _state["coord_map"] = {}
    _state["grid_map"] = {}
    _state["last_screenshot_path"] = None
    _state["last_text_list"] = None


# ============================================================
# 截圖壓縮設定 (防止 context 爆炸)
# ============================================================
# 為什麼需要這段？
#   原生 PNG 截圖 (1920x1080 全螢幕) 約 3~5 MB
#   Base64 後約 4~7 MB 字串
#   對 Vision Model 而言 = 數十萬 Token → context 瞬間撐爆
#
# 解法：強制轉 JPEG + 必要時縮放
#   - 寬度 > 1280 時縮放至 1280 (對 AI 辨識紅框+數字已足夠，更小也省 token)
#   - JPEG quality=60：對 AI 識別綽綽有餘，比 q70 又省 30%
#   - 4K 螢幕的截圖 Base64 從 ~10MB 降到 ~80KB，省 99% token
SCREENSHOT_MAX_WIDTH: int = 1280
SCREENSHOT_JPEG_QUALITY: int = 60


def _encode_compressed_screenshot(image_path: str) -> str:
    """讀取截圖 → 縮放 (必要時) → JPEG 壓縮 → 回傳 Base64 字串。

    為什麼不用原本的 PNG 編碼？
      - 1920x1080 PNG ≈ 3~5 MB，Base64 ≈ 4~7 MB → 數十萬 token
      - 同畫面 JPEG q70 ≈ 200~400 KB，Base64 ≈ 300~500 KB → 數萬 token
      - 視覺品質對 AI 識別紅框+編號無差別 (都是純色幾何)
    """
    with Image.open(image_path) as img:
        # 1) 過寬就縮放 (4K 螢幕或更高解析度)
        if img.width > SCREENSHOT_MAX_WIDTH:
            new_w = SCREENSHOT_MAX_WIDTH
            new_h = int(img.height * (new_w / img.width))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 2) 轉 RGB (PNG 可能有 RGBA/灰階，JPEG 不支援)
        if img.mode != "RGB":
            img = img.convert("RGB")

        # 3) JPEG 壓縮
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=SCREENSHOT_JPEG_QUALITY, optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _encode_image_to_base64(image_path: str) -> str:
    """舊版 PNG Base64 編碼 (向後相容別名)。

    強烈建議使用 _encode_compressed_screenshot() 以避免 context 爆炸。
    保留這個函式是為了在測試或除錯時仍能拿到原始 PNG。
    """
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ============================================================
# 建立 MCP Server
# ============================================================
mcp = FastMCP("wcmd")


# ============================================================
# Tool 1：get_screen_state (感知層)
# ============================================================
@mcp.tool()
def get_screen_state(
    include_screenshot: bool = False,
    use_grid: bool = False,
    grid_rows: int = 10,
    grid_cols: int = 10,
    text_list_max_items: int = 30,
) -> dict:
    """
    掃描當前螢幕並回傳可操作的 UI 元素清單 (文字化)。

    這是「感知工具」：呼叫後，螢幕狀態會被快取，
    緊接著呼叫 execute_exact_action 時會用此快取查找座標。

    兩種使用模式 (二選一，避免浪費 context)：
      【文字模式】include_screenshot=False (預設)
        → 回傳 text_list，Agent 用語意判斷要點哪個 ID
        → 適合無/弱視覺的小型 LLM
      【視覺模式】include_screenshot=True
        → 額外回傳 screenshot_base64，Agent 用視覺判斷
        → 建議 text_list_max_items=0 跳過文字清單 (避免重複)
        → 適合 Claude 3.5+ / GPT-4o / Qwen-VL-Plus

    Args:
        include_screenshot: 是否額外回傳 Base64 編碼的螢幕截圖
                           (供視覺模型觀看，例如 Claude 3.5 Sonnet/Opus)
        use_grid: True 時使用「網格模式」(適用於 UIA 抓不到元素的場景，
                  例如 Discord 客製化介面、Steam UI、遊戲、WebGL 畫布)
        grid_rows: 網格列數，僅 use_grid=True 生效 (預設 10，範圍 3~20)
        grid_cols: 網格欄數，僅 use_grid=True 生效 (預設 10，範圍 3~20)
        text_list_max_items: text_list 最多列幾個元素 (預設 30，視覺模式建議設 0)。
                            字元總長度另有硬上限 (MAX_TEXT_LIST_CHARS)。

    Returns:
        dict 結構:
        {
            "mode": "uia" | "grid" | "empty",
            "element_count": int,
            "text_list": str,                  # 文字化 UI 清單 (給無視覺模型)
            "available_ids": list[str] | None, # UIA 模式：可用 target_id 清單 (e.g. ["0","1","2"])
                                                # 座標不直接回傳，內部快取供 execute_exact_action 使用
            "available_grid_ids": list[str] | None, # Grid 模式：可用 grid_id 清單 (e.g. ["A1","A2",...])
            "screenshot_base64": str | None,   # 僅 include_screenshot=True 時有值
            "screenshot_format": "jpeg",
            "screenshot_path": str | None,     # 截圖本地路徑 (供除錯)
        }
    """
    try:
        if use_grid:
            # ---------- 網格模式 (強制) ----------
            rows = max(engine.GRID_MIN_SIZE, min(engine.GRID_MAX_SIZE, grid_rows))
            cols = max(engine.GRID_MIN_SIZE, min(engine.GRID_MAX_SIZE, grid_cols))

            image, grid_map = engine.generate_grid_screenshot(rows=rows, cols=cols)
            image_path = engine.OUTPUT_IMAGE_PATH
            image.save(image_path)

            _state["mode"] = "grid"
            _state["coord_map"] = {}
            _state["grid_map"] = grid_map
            _state["last_screenshot_path"] = image_path

            last_col_letter = engine.GRID_COL_LETTERS[cols - 1]
            text_list = (
                f"[Grid Mode] 螢幕已被劃分成 {cols}×{rows} 網格，"
                f"共 {len(grid_map)} 個格子 (A1 ~ {last_col_letter}{rows})。"
                f"請告訴 AI 想操作哪個格子 (例如 'click on C5' 或 'drag A1 to C5')。"
            )
            _state["last_text_list"] = text_list

            logger.info(
                f"[Tool 1] get_screen_state (grid {rows}×{cols}) → "
                f"{len(grid_map)} cells"
            )

            result = {
                "mode": "grid",
                "element_count": len(grid_map),
                "text_list": text_list,
                "coord_map": None,
                "available_ids": None,
                "available_grid_ids": list(grid_map.keys()),  # 只給 id，不給座標
                "grid_map": None,  # ContextGuard: 保留 key 為 None 以維持 schema 穩定
                "screenshot_base64": None,
                "screenshot_format": "jpeg",
                "screenshot_path": os.path.abspath(image_path),
            }
        else:
            # ---------- UIA 模式 (預設) ----------
            elements = engine.get_clickable_elements()
            if not elements:
                # UIA 抓不到元素 → 不自動降級 (由呼叫方決定是否再呼叫 use_grid=True)
                _reset_state()
                _state["mode"] = "empty"
                logger.info("[Tool 1] get_screen_state → 0 元素 (UIA 抓不到)")
                return {
                    "status": "ok",
                    "mode": "empty",
                    "element_count": 0,
                    "text_list": (
                        "UIA 抓不到任何可點擊元素。"
                        "建議：再用 use_grid=True 重新掃描一次 (網格模式)。"
                    ),
                    "coord_map": None,
                    "available_ids": None,
                    "grid_map": None,
                    "available_grid_ids": None,
                    "screenshot_base64": None,
                    "screenshot_format": "jpeg",
                    "screenshot_path": None,
                }

            # 產生標記截圖 (Set-of-Mark 紅框)
            coord_map = engine.generate_marked_screenshot(elements)
            image_path = engine.OUTPUT_IMAGE_PATH

            _state["mode"] = "uia"
            _state["coord_map"] = coord_map
            _state["grid_map"] = {}
            _state["last_screenshot_path"] = image_path

            # 文字化清單 (給無視覺模型判斷用)
            # ContextGuard: 透過 text_list_max_items 讓 agent 自控長度
            # text_list_max_items=0 表示完全跳過 (視覺模式不需要)
            if text_list_max_items > 0:
                text_list = engine.build_element_text_list(
                    elements, max_items=text_list_max_items
                )
            else:
                # 視覺模式：只給視窗總覽，不列元素細節
                all_windows = (
                    elements[0].get("_all_windows", []) if elements else []
                )
                if all_windows:
                    text_list = (
                        f"[畫面上偵測到的視窗] {' | '.join(all_windows)}\n"
                        f"(視覺模式：略過 {len(elements)} 個元素細節，"
                        f"請直接看截圖)"
                    )
                else:
                    text_list = (
                        f"(視覺模式：偵測到 {len(elements)} 個元素，"
                        f"請直接看截圖)"
                    )
            _state["last_text_list"] = text_list

            logger.info(
                f"[Tool 1] get_screen_state (UIA) → {len(elements)} 元素"
            )

            result = {
                "mode": "uia",
                "element_count": len(elements),
                "text_list": text_list,
                # ⚠️ ContextGuard: 不回傳完整座標表，只回傳 ID 清單
                # 座標仍存在 _state 內，供 execute_exact_action 用
                "coord_map": None,
                "available_ids": [str(k) for k in coord_map.keys()],
                "grid_map": None,
                "available_grid_ids": None,
                "screenshot_base64": None,
                "screenshot_format": "jpeg",
                "screenshot_path": os.path.abspath(image_path),
            }

        # 附加 Base64 截圖 (若要求) - 強制 JPEG 壓縮避免 context 爆炸
        if include_screenshot and _state["last_screenshot_path"]:
            result["screenshot_base64"] = _encode_compressed_screenshot(
                _state["last_screenshot_path"]
            )
            logger.info(
                f"[Tool 1] 已附加截圖 ({len(result['screenshot_base64'])} chars, "
                f"JPEG q{SCREENSHOT_JPEG_QUALITY})"
            )

        return result

    except Exception as exc:
        logger.exception("[Tool 1] get_screen_state 發生錯誤")
        return {
            "status": "error",
            "message": f"get_screen_state 失敗：{exc}",
        }


# ============================================================
# Tool 2：execute_exact_action (精確層)
# ============================================================
@mcp.tool()
def execute_exact_action(
    action: str,
    target_id: Optional[int] = None,
    grid_id: Optional[str] = None,
    text: Optional[str] = None,
    keys: Optional[str] = None,
    direction: Optional[str] = None,
    clicks: Optional[int] = None,
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    start_grid_id: Optional[str] = None,
    end_grid_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    執行明確的動作 (需先呼叫 get_screen_state 取得座標快取)。

    這是「精確工具」：走 dispatcher 分派到對應的 PyAutoGUI 函式，
    完全不經過 AI API (零延遲、零成本)。適合已看過螢幕的 Agent 呼叫。

    Args:
        action: 動作類型，必填，可選值：
                "click" / "double_click" / "right_click" / "type" /
                "hotkey" / "scroll" / "drag" / "NOT_FOUND"
        target_id:  UIA 模式下的元素編號 (整數，例如 5)
        grid_id:    Grid 模式下的格子 label (例如 "C5")
        text:       type 動作要輸入的文字
        keys:       hotkey 動作的按鍵組合 (例如 "ctrl+c"、"alt+F4")
        direction:  scroll 動作方向 ("up"/"down"/"left"/"right")
        clicks:     scroll 動作的滾輪格數
        start_id / end_id:           drag 動作 (UIA 模式) 的起訖編號
        start_grid_id / end_grid_id: drag 動作 (Grid 模式) 的起訖格子
        dry_run:    若為 True，僅預演不實際操作

    Returns:
        dict: {"status", "action", "message", "coord"}
    """
    try:
        # 檢查狀態
        if _state["mode"] is None or _state["mode"] == "empty":
            return {
                "status": "error",
                "action": action,
                "message": (
                    "尚未呼叫 get_screen_state，無座標快取。"
                    "請先呼叫 get_screen_state (UIA 或 Grid 模式皆可) 取得座標。"
                ),
                "coord": None,
            }

        # 組合動作字典
        action_dict: dict = {
            "action": action,
            "reason": "(via MCP execute_exact_action)",
        }
        if target_id is not None:
            action_dict["target_id"] = target_id
        if grid_id is not None:
            action_dict["grid_id"] = grid_id
        if text is not None:
            action_dict["text"] = text
        if keys is not None:
            action_dict["keys"] = keys
        if direction is not None:
            action_dict["direction"] = direction
        if clicks is not None:
            action_dict["clicks"] = clicks
        if start_id is not None:
            action_dict["start_id"] = start_id
        if end_id is not None:
            action_dict["end_id"] = end_id
        if start_grid_id is not None:
            action_dict["start_grid_id"] = start_grid_id
        if end_grid_id is not None:
            action_dict["end_grid_id"] = end_grid_id

        # 交給 dispatcher 執行
        result = engine.execute_action(
            action_dict,
            _state["coord_map"],
            dry_run=dry_run,
            grid_map=_state["grid_map"],
        )
        logger.info(
            f"[Tool 2] execute_exact_action: action={action}, "
            f"status={result.get('status')}, coord={result.get('coord')}"
        )
        return result

    except Exception as exc:
        logger.exception("[Tool 2] execute_exact_action 發生錯誤")
        return {
            "status": "error",
            "action": action,
            "message": f"execute_exact_action 失敗：{exc}",
            "coord": None,
        }


# ============================================================
# Tool 3：execute_semantic_intent (委託層)
# ============================================================
@mcp.tool()
def execute_semantic_intent(
    instruction: str,
    dry_run: bool = False,
    force_grid: bool = False,
) -> dict:
    """
    給無視覺能力的小型 LLM 使用的高階介面。

    工具會自動完成：抓取螢幕 → 呼叫內建 Vision Model (Qwen3.7 Plus) →
    解析動作 JSON → 執行對應 PyAutoGUI 動作。

    內部使用環境變數：
        VISION_API_KEY    Vision Model API Key (或 agent_engine.py 內的常數)
        VISION_BASE_URL   覆寫 API 端點
        VISION_MODEL      覆寫模型名稱

    Args:
        instruction: 高階意圖 (例如 "點擊工作管理員的 X 按鈕"、"按 Ctrl+S 存檔")
        dry_run:     若為 True，僅預演不實際操作
        force_grid:  強制走 Grid 模式 (略過 UIA 抓元素)

    Returns:
        dict: {"status", "action", "message", "coord", "ai_reason"}
    """
    try:
        # 檢查 API Key (優先順序：config → engine 全域常數 → 環境變數)
        api_key = wcmd_config.VISION_API_KEY or engine.API_KEY
        if not api_key:
            return {
                "status": "error",
                "message": (
                    "尚未設定 Vision Model API Key。"
                    "請設定環境變數 WCMD_VISION_API_KEY (或 VISION_API_KEY)，"
                    "或在 MCP config 的 env 區塊加入 WCMD_VISION_API_KEY 變數。"
                ),
            }

        # 決定模式
        use_grid_mode = bool(force_grid)
        elements = None
        coord_map: dict = {}
        grid_map: dict = {}

        if not use_grid_mode:
            # 嘗試 UIA
            elements = engine.get_clickable_elements()
            if not elements:
                logger.info(
                    "[Tool 3] UIA 抓不到元素，自動降級為 Grid 模式"
                )
                use_grid_mode = True
            else:
                coord_map = engine.generate_marked_screenshot(elements)
                _state["mode"] = "uia"
                _state["coord_map"] = coord_map
                _state["grid_map"] = {}
                _state["last_screenshot_path"] = engine.OUTPUT_IMAGE_PATH

        if use_grid_mode:
            image, grid_map = engine.generate_grid_screenshot()
            image_path = engine.OUTPUT_IMAGE_PATH
            image.save(image_path)
            _state["mode"] = "grid"
            _state["grid_map"] = grid_map
            _state["coord_map"] = {}
            _state["last_screenshot_path"] = image_path
            elements = None  # Grid 模式不傳 elements

        # 呼叫 Vision Model
        logger.info(
            f"[Tool 3] execute_semantic_intent: 模式={'grid' if use_grid_mode else 'uia'}, "
            f"instruction={instruction!r}"
        )
        if use_grid_mode:
            action_dict = engine.ask_vision_model_grid(
                engine.OUTPUT_IMAGE_PATH, instruction
            )
        else:
            action_dict = engine.ask_vision_model(
                engine.OUTPUT_IMAGE_PATH, instruction, elements
            )

        if not action_dict:
            return {
                "status": "error",
                "message": "Vision Model 沒有回傳有效動作字典 (請檢查 Prompt 或 API 設定)",
            }

        # 執行
        result = engine.execute_action(
            action_dict, coord_map, dry_run=dry_run, grid_map=grid_map
        )
        # 補上 AI 判斷理由
        result["ai_reason"] = action_dict.get("reason", "")
        result["mode_used"] = "grid" if use_grid_mode else "uia"
        logger.info(
            f"[Tool 3] 完成: status={result.get('status')}, "
            f"action={result.get('action')}"
        )
        return result

    except Exception as exc:
        logger.exception("[Tool 3] execute_semantic_intent 發生錯誤")
        return {
            "status": "error",
            "message": f"execute_semantic_intent 失敗：{exc}",
        }


# ============================================================
# Server 啟動
# ============================================================
def main() -> None:
    """MCP Server 進入點 (供 console script 與 python -m 呼叫)。"""
    if not _MCP_AVAILABLE:
        logger.error("mcp 套件未安裝，無法啟動 MCP Server")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(" WinControl MCP Driver Server 啟動中...")
    logger.info("=" * 60)
    logger.info(f"  螢幕解析度 : {engine.pyautogui.size()}")
    logger.info(f"  DPI 感知   : {'成功' if engine._dpi_set_ok else '失敗'}")
    logger.info(f"  Vision Model: {engine.MODEL_NAME}")
    logger.info(f"  Base URL   : {engine.BASE_URL}")
    has_key = bool(wcmd_config.VISION_API_KEY or engine.API_KEY)
    logger.info(f"  API Key    : {'已設定' if has_key else '未設定 (Tool 3 將無法使用)'}")
    logger.info(f"  支援動作   : {sorted(engine.SUPPORTED_ACTIONS)}")
    logger.info("  Transport : stdio")
    logger.info("=" * 60)
    logger.info(" MCP Server 開始監聽 stdin/stdout ...")

    # FastMCP 預設使用 stdio transport
    mcp.run()


if __name__ == "__main__":
    main()
