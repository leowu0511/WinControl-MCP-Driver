# -*- coding: utf-8 -*-
"""
============================================================================
 WCMD MCP Server (wcmd.server)
============================================================================
 為 AI Agent 提供「視覺操控 Windows UI」的能力。
 採用「能力分層 (Capability-Tiered)」設計，提供 3 個 MCP Tools：

   ┌─────────────────────────────────────────────────────────────┐
   │ Tier 1 感知層  get_screen_state                              │
   │   - 掃描螢幕、回傳文字化 UI 清單 (絕不附 Base64 截圖)        │
   │   - 結果會「快取」給後續 execute_exact_action 使用           │
   ├─────────────────────────────────────────────────────────────┤
   │ Tier 2 精確層  execute_exact_action                          │
   │   - 接收明確的 action + 座標/ID，直接 PyAutoGUI 執行         │
   │   - 走 dispatcher，不呼叫 AI API (零延遲、零成本)            │
   ├─────────────────────────────────────────────────────────────┤
    │ Tier 3 委託層  execute_semantic_intent                       │
    │   - 【主要操作工具】所有 AI 優先使用 (全自動 抓圖→問Qwen→執行)│
    │   - 內部呼叫 VISION_API_KEY / VISION_BASE_URL 環境變數       │
    │   - 截圖只在 server 端→Vision API 之間流動，不暴露給 agent  │
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
import json
import os
import sys
import logging
from typing import Optional

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
# 建立 MCP Server
# ============================================================
if _MCP_AVAILABLE:
    mcp = FastMCP("wcmd")
else:
    mcp = None  # type: ignore  # 沒安裝 mcp 套件時用 None 佔位，import 不會炸


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


@mcp.tool()
def get_screen_state(
    use_grid: bool = False,
    grid_rows: int = 10,
    grid_cols: int = 10,
    text_list_max_items: int = 30,
) -> dict:
    """
    【純觀察工具】僅用於查看目前畫面狀態，不用於執行操作。

    ⚠️ 若要執行任何 UI 操作 (點擊/輸入/滾動/按熱鍵/拖曳)，
       請使用 execute_semantic_intent，本工具「不會」執行動作。
       不要看了畫面就假裝操作已完成 — 這是常見的幻覺陷阱。

    用途：
      - 進階用法：搭配 execute_exact_action 自己指定 target_id
        (例如「我要點列表第 47 個項目」)
      - Vision Model API Key 沒設定時的降級方案
        (純文字清單 + 自己讀 ID)

    ⚠️ 本工具「絕對不會」回傳截圖 Base64 給 agent。
       Vision 判斷統一走 execute_semantic_intent (server 端內部完成)。
       這樣可以保證截圖 (Base64 ~80KB) 不會進 agent 的 context，
       避免多步驟操作時 context 累積爆炸。

    掃描當前螢幕並回傳可操作的 UI 元素清單 (文字化)。

    這是「感知工具」：呼叫後，螢幕狀態會被快取，
    緊接著呼叫 execute_exact_action 時會用此快取查找座標。

    Args:
        use_grid: True 時使用「網格模式」(適用於 UIA 抓不到元素的場景，
                  例如 Discord 客製化介面、Steam UI、遊戲、WebGL 畫布)
        grid_rows: 網格列數，僅 use_grid=True 生效 (預設 10，範圍 3~20)
        grid_cols: 網格欄數，僅 use_grid=True 生效 (預設 10，範圍 3~20)
        text_list_max_items: text_list 最多列幾個元素 (預設 30)。
                            字元總長度另有硬上限 (MAX_TEXT_LIST_CHARS)。

    Returns:
        dict 結構:
        {
            "mode": "uia" | "grid" | "empty",
            "element_count": int,
            "text_list": str | None,           # 文字化 UI 清單
            "available_ids": str | None,       # UIA 模式: 緊湊 ID 範圍字串 (e.g. "0~59")
                                                # 座標不直接回傳，內部快取供 execute_exact_action 使用
            "available_grid_ids": str | None,  # Grid 模式: 緊湊 ID 範圍字串 (e.g. "A1~J10")
            "screenshot_path": str | None,     # 截圖本地路徑 (供除錯；不會回傳 base64 給 agent)
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
                # 緊湊 ID 範圍字串: "A1~J10" 比 list 短超多
                "available_grid_ids": (
                    f"A1~{engine.GRID_COL_LETTERS[cols-1]}{rows}" if grid_map else None
                ),
                "grid_map": None,  # ContextGuard: 保留 key 為 None 以維持 schema 穩定
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
            # text_list_max_items=0 表示「只要視窗總覽、不列元素細節」
            # (純除錯用，agent 想知道目前有哪些視窗開著)
            if text_list_max_items > 0:
                text_list = engine.build_element_text_list(
                    elements, max_items=text_list_max_items
                )
            else:
                # 略過元素細節，只給視窗總覽
                all_windows = (
                    elements[0].get("_all_windows", []) if elements else []
                )
                if all_windows:
                    text_list = (
                        f"[畫面上偵測到的視窗] {' | '.join(all_windows)}\n"
                        f"(略過 {len(elements)} 個元素細節)"
                    )
                else:
                    text_list = (
                        f"(偵測到 {len(elements)} 個元素，已略過細節)"
                    )
            _state["last_text_list"] = text_list

            logger.info(
                f"[Tool 1] get_screen_state (UIA) → {len(elements)} 元素"
            )

            result = {
                "mode": "uia",
                "element_count": len(elements),
                "text_list": text_list,
                # ⚠️ ContextGuard: 不回傳完整座標表，只給緊湊 ID 範圍字串
                # 座標仍存在 _state 內，供 execute_exact_action 使用
                "coord_map": None,
                "available_ids": f"0~{len(coord_map)-1}" if coord_map else None,
                "grid_map": None,
                "available_grid_ids": None,
                "screenshot_path": os.path.abspath(image_path),
            }

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
        dict: {"status", "action", "message"}
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
        # ContextGuard: 像素座標對 agent 無用，log 留給人看，response 拿掉
        result.pop("coord", None)
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
    【主要操作工具，所有 AI 均應優先使用此工具執行任何 UI 操作】

    無論你自身是否具備視覺能力，都必須透過此工具操作畫面 UI。
    視覺判斷由內建 Vision Model 負責，不依賴你自身的視覺能力。
    工具內部自動完成：截圖 → Vision Model 定位元素 → 執行 PyAutoGUI 動作。

    ⚠️ 不要用 get_screen_state 看一眼螢幕就假裝操作完成。
       看到元素 ≠ 操作過元素，必須呼叫本工具才會真的執行動作。

    用自然語言描述意圖即可，例如：
      - "點擊確定按鈕"
      - "關閉工作管理員視窗"
      - "在搜尋框輸入 hello"
      - "按 Ctrl+S 儲存"
      - "在工作管理員選第一個處理程序，按結束工作"

    工具會自動完成：抓取當前螢幕 → 呼叫內建 Vision Model (Qwen3.7 Plus) →
    解析動作 JSON → 執行對應 PyAutoGUI 動作。

    內部使用環境變數：
        VISION_API_KEY    Vision Model API Key (或 agent_engine.py 內的常數)
        VISION_BASE_URL   覆寫 API 端點
        VISION_MODEL      覆寫模型名稱

    Args:
        instruction: 高階意圖 (例如 "點擊工作管理員的 X 按鈕"、"按 Ctrl+S 存檔")
        dry_run:     若為 True，僅預演不實際操作 (回傳會包含 ai_reason 讓你預覽)
        force_grid:  強制走 Grid 模式 (略過 UIA 抓元素；UIA 失敗時用)

    Returns:
        dict: {
            "status": "ok" | "error",     # 執行動作是否成功
            "action": "click" | "type" | ...,  # 實際執行的動作類型
            "message": str,                 # 人類可讀的結果訊息
            "ai_reason": str,               # Vision Model 為何選這個動作
            "mode_used": "uia" | "grid",    # 用了哪種掃描模式
        }

    何時該用其他工具：
      - get_screen_state: 除錯、想看 UI 長相、或 Vision API Key 沒設
      - execute_exact_action: 已經知道精確的 target_id/grid_id (例如「點列表第 5 個」)
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
        # ContextGuard: 像素座標對 agent 無用，pop 掉
        result.pop("coord", None)
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
