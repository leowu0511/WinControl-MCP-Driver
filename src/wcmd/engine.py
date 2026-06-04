# -*- coding: utf-8 -*-
"""
============================================================================
 WCMD 核心引擎 (wcmd.engine)
============================================================================
 整體功能 (階段一 + 階段二 + 階段 2.6)：
   1. 使用 Windows UI Automation (uiautomation) 抓取目前桌面所有可點擊的 UI 元素。
   2. 透過 pyautogui 截圖，並使用 Pillow 在每個元素上繪製「紅框 + 數字編號」
      (即 Set-of-Mark 標記策略)。
   3. 將「編號 -> 中心座標」對應表儲存為 JSON，供 VS Code Extension 讀取。
   4. 將標記後的截圖轉成 Base64，送給相容 Anthropic / OpenAI API 的 Vision Model
      (例如 Qwen3.7 Plus on OpenCode Go)，由模型回傳「動作 JSON」。
   5. 將 JSON 動作分派給對應執行器：
        - click        左鍵單擊
        - double_click 雙擊
        - right_click  右鍵
        - type         鍵盤輸入文字 (含 Unicode/中文)
        - hotkey       熱鍵 (例如 ctrl+c、alt+F4、win+d)
        - NOT_FOUND    找不到對應元素時的特殊回應

 後續階段 (Phase 3) 將會整合：
   - VS Code Extension 透過 child_process 呼叫本腳本
============================================================================
"""

# ============================================================
# 套件引入區
# ============================================================
import argparse                     # 用於解析命令列參數
import base64                       # 用於將圖片編碼為 Base64 字串
import ctypes                       # 用於呼叫 Windows API 設定 DPI 感知
import json                         # 用於將座標表存成 JSON / 解析模型回應的動作
import os                           # 用於處理檔案路徑與環境變數
import re                           # 用於正則表達式解析模型回應
import sys                          # 用於 sys.exit 與 sys.argv
import time                         # 用於操作之間的短暫 sleep (避免剪貼簿尚未更新)
from typing import List, Dict, Any, Tuple, Optional

import pyautogui                    # 用於螢幕截圖與後續的滑鼠/鍵盤操作
import uiautomation                 # 用於走訪 Windows UI Automation 樹
from PIL import Image, ImageDraw, ImageFont  # 用於繪製紅框與數字標籤

# WCMD 套件內部設定 (環境變數驅動)
from wcmd import config

# pyperclip - 用於剪貼簿貼上 (中文/Unicode 輸入的唯一可行方案)
try:
    import pyperclip
    _PYPERCLIP_AVAILABLE = True
except ImportError:
    _PYPERCLIP_AVAILABLE = False
    pyperclip = None  # type: ignore

# OpenAI SDK (v1.x) - 用於呼叫相容 OpenAI 格式的 Vision Model (例如 Qwen on Zen、gpt-4o)
try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
    OpenAI = None  # type: ignore

# Anthropic SDK - 用於呼叫相容 Anthropic 格式的 Vision Model (例如 Qwen on OpenCode Go)
try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    anthropic = None  # type: ignore


# ============================================================
# DPI 感知設定 (必須在「任何」螢幕 / 視窗操作之前執行)
# ============================================================
# 為什麼需要這一段？
#   在高 DPI 螢幕 (例如 125%、150% 縮放) 上：
#     - 沒有設定 DPI 感知時，pyautogui 與 uiautomation 會使用「不同的座標系統」
#     - 這會導致「看到的紅框」與「實際點擊的位置」完全對不上
#   設定為 DPI Aware 後，兩個函式庫都會回傳「實體像素座標」，
#   進而保證截圖座標、UI 框座標、滑鼠點擊座標三者完全一致。
# ------------------------------------------------------------
# 優先使用 Win 8.1+ 的現代 API (per-monitor DPI awareness)，
# 若失敗則退回使用 Vista+ 的相容 API。
_dpi_set_ok = False
try:
    # 參數 2 代表 PROCESS_PER_MONITOR_DPI_AWARE (推薦設定)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    _dpi_set_ok = True
except Exception:
    try:
        # 退回方案：PROCESS_SYSTEM_DPI_AWARE (整個 process 共用系統 DPI)
        ctypes.windll.user32.SetProcessDPIAware()
        _dpi_set_ok = True
    except Exception as exc:
        # 若兩者皆失敗，仍繼續執行，但會在後續操作中發出警告
        print(f"[警告] 設定 DPI 感知失敗：{exc}，座標在高 DPI 螢幕上可能會偏移。")

# 停用 pyautogui 預設的滑鼠移動到角落中止機制 (避免干擾後續點擊)
pyautogui.FAILSAFE = False


# ============================================================
# 全域常數設定
# ============================================================
# 標記圖片輸出路徑 (由 config 統一管理，預設 ~/.wcmd/marked_screen.png)
OUTPUT_IMAGE_PATH = config.OUTPUT_IMAGE_PATH

# uiautomation 中，ControlTypeName 的命名規則為 "<類型>Control"，
# 以下為「可點擊 / 可互動」的元素白名單 (可依需求自行擴充)。
CLICKABLE_CONTROL_TYPES = {
    "ButtonControl",          # 一般按鈕 (例如「確定」、「取消」)
    "TabItemControl",         # 分頁標籤
    "HyperlinkControl",       # 超連結
    "MenuItemControl",        # 選單項目
    "CheckBoxControl",        # 核取方塊
    "RadioButtonControl",     # 選項按鈕 (單選)
    "ListItemControl",        # 清單中的項目
    "SplitButtonControl",     # 下拉式按鈕
    "ToggleButtonControl",    # 開關型按鈕
    "TreeItemControl",        # 樹狀結構的節點
}

# 標記繪製相關參數
BOX_COLOR = "red"              # 紅框顏色
BOX_WIDTH = 3                  # 紅框線寬 (像素)
LABEL_BG_COLOR = "red"         # 編號標籤底色
LABEL_TEXT_COLOR = "white"     # 編號文字顏色
LABEL_PADDING = 2              # 編號文字與邊框的內距 (像素)
LABEL_FONT_SIZE = 18           # 編號字型大小

# 元素過濾的最小尺寸 (寬或高小於此值會被忽略，避免抓到無意義的細線)
MIN_ELEMENT_SIZE = 3

# ============================================================
# Callout 導引線設定 (優化 A：解決小元素紅框/編號遮擋問題)
# ============================================================
# 當元素的寬度或高度小於下列門檻時，會改用「外部 callout 標籤」繪製，
# 也就是把編號畫在元素外面，再用一條細線連到元素上 (像設計軟體的標註)。
SMALL_ELEMENT_W_THRESHOLD = 50   # 寬度小於此值用 callout (像素)
SMALL_ELEMENT_H_THRESHOLD = 25   # 高度小於此值用 callout (像素)
CALLOUT_FONT_SIZE = 22           # callout 標籤字型大小
CALLOUT_PADDING = 3              # callout 標籤內距
CALLOUT_LABEL_SIZE = CALLOUT_FONT_SIZE + CALLOUT_PADDING * 2  # callout 標籤方形邊長
CALLOUT_GAP = 6                  # callout 標籤與元素邊界的間距 (像素)
CALLOUT_LINE_COLOR = "black"     # 導引線顏色
CALLOUT_LINE_OUTLINE = "white"   # 導引線外框顏色 (提高對比)
CALLOUT_BORDER_COLOR = "white"   # callout 標籤外框顏色
CALLOUT_BORDER_WIDTH = 2         # callout 標籤外框線寬

# ============================================================
# 文字清單設定 (優化 D：解決純視覺難以判斷小元素的問題)
# ============================================================
# 把 UIA 抓到的元素名稱 (例如「確定」「新增」) 整理成文字清單，
# 一起塞進 Prompt，讓 AI 用「語意」而不是「純視覺」判斷。
TEXT_LIST_MAX_ITEMS = 60         # 最多列出幾個元素 (避免 Prompt 過長)

# 座標表 JSON 輸出路徑 (由 config 統一管理，預設 ~/.wcmd/coord_map.json)
COORD_MAP_PATH = config.COORD_MAP_PATH


# ============================================================
# Vision Model 連線設定 (由 config 統一管理，環境變數驅動)
# ============================================================
# 設定方式（優先順序高 → 低）：
#   1. 命令列參數 (--api-key / --base-url / --model) — 僅 CLI 模式
#   2. 環境變數 WCMD_VISION_API_KEY / WCMD_VISION_BASE_URL / WCMD_VISION_MODEL
#   3. 環境變數 VISION_API_KEY / VISION_BASE_URL / VISION_MODEL (相容舊名稱)
#   4. config 預設值 (OpenCode Go + Qwen3.7 Plus)
#
# 常用供應商設定範例：
#   OpenCode Go (Anthropic 格式)：WCMD_VISION_BASE_URL=https://opencode.ai/zen/go + qwen3.7-plus
#   OpenCode Zen (OpenAI 格式)  ：WCMD_VISION_BASE_URL=https://opencode.ai/zen/v1 + qwen3.6-plus
#   阿里雲 DashScope (OpenAI)   ：WCMD_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 + qwen-vl-plus
#   OpenAI 官方                 ：WCMD_VISION_BASE_URL=https://api.openai.com/v1 + gpt-4o
#   Anthropic 官方              ：WCMD_VISION_BASE_URL=https://api.anthropic.com + claude-sonnet-4-5
# ============================================================
API_KEY: str = config.VISION_API_KEY
BASE_URL: str = config.VISION_BASE_URL
MODEL_NAME: str = config.VISION_MODEL


# ============================================================
# Action Space 設定 (Phase 2.6：擴展支援的動作類型)
# ============================================================
# 本引擎除了「左鍵點擊」之外，還支援下列動作。
# AI 必須回傳以下其中之一的 action 欄位。
# 對應的 JSON 結構範例：
#   {"action": "click",        "target_id": 5,  "reason": "..."}     # 左鍵單擊
#   {"action": "double_click", "target_id": 7,  "reason": "..."}     # 雙擊
#   {"action": "right_click",  "target_id": 12, "reason": "..."}     # 右鍵
#   {"action": "type",         "text": "hello", "reason": "..."}     # 鍵盤輸入
#   {"action": "hotkey",       "keys": "ctrl+c","reason": "..."}     # 熱鍵
#   {"action": "scroll",       "direction": "down", "clicks": 3}      # 捲動畫面
#   {"action": "drag",         "start_id": 5, "end_id": 12}           # 拖曳 (start_id→end_id)
#   {"action": "NOT_FOUND",    "reason": "找不到可完成任務的元素"}    # 找不到時
SUPPORTED_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "type",
    "hotkey",
    "scroll",
    "drag",
    "NOT_FOUND",
}

# 熱鍵別名表 (將使用者 / AI 給的「友善名稱」對應到 pyautogui 期望的按鍵名稱)
# 範例：「ctrl+shift+esc」→ 拆解後每段查表 → ['ctrl', 'shift', 'esc']
HOTKEY_ALIAS = {
    # 修飾鍵 (modifier keys)
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "win", "windows": "win", "meta": "win", "cmd": "win", "super": "win",
    # 主要按鍵
    "enter": "enter", "return": "enter", "⏎": "enter",
    "esc": "esc", "escape": "esc",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace", "bs": "backspace",
    "delete": "delete", "del": "delete",
    "home": "home", "end": "end",
    "pageup": "pageup", "pgup": "pageup",
    "pagedown": "pagedown", "pgdn": "pagedown",
    "up": "up", "down": "down", "left": "left", "right": "right",
    # 功能鍵
    "f1": "f1",  "f2": "f2",  "f3": "f3",  "f4": "f4",
    "f5": "f5",  "f6": "f6",  "f7": "f7",  "f8": "f8",
    "f9": "f9",  "f10": "f10", "f11": "f11", "f12": "f12",
}


# ============================================================
# Scroll (捲動) 設定
# ============================================================
# pyautogui.scroll() 的 amount 參數：正值=向上、負值=向下
# 每 1 click 約等於內部 120 單位 (Windows 預設一格滾輪)
SCROLL_DEFAULT_CLICKS = 3            # 預設捲動 3 格 (約 360 像素)
SCROLL_MAX_CLICKS = 50               # 防止 AI 回傳過大的數值

# ============================================================
# Drag (拖曳) 設定
# ============================================================
DRAG_DEFAULT_DURATION = 0.5          # 拖曳過程秒數 (給你看得到滑鼠軌跡)

# ============================================================
# Grid Fallback (純視覺降級機制) 設定
# ============================================================
# 當 UIA 抓不到元素 (空陣列) 時，改用「在截圖上疊加 NxM 網格」，
# 每個格子用 A1, A2, ..., J10 這類 label 標記，讓 AI 用純視覺判斷座標。
# 這對 Electron/遊戲/WebGL 等 UIA 抓不到的環境特別有用。
GRID_DEFAULT_ROWS = 10               # 預設 10 列
GRID_DEFAULT_COLS = 10               # 預設 10 欄
GRID_MIN_SIZE = 3                    # 網格最小邊數 (避免太細)
GRID_MAX_SIZE = 20                   # 網格最大邊數 (避免太粗)
GRID_COL_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 最多 26 欄
GRID_LINE_COLOR = (0, 200, 200)      # 青色格線 (在多數背景上都清楚)
GRID_LABEL_BG = (255, 255, 0)        # 黃底
GRID_LABEL_FG = (0, 0, 0)            # 黑字
GRID_LABEL_OUTLINE = (0, 0, 0)       # 黑邊


# ============================================================
# 函數 1：抓取目前桌面所有「可點擊」的 UI 元素
# ============================================================
# 最大走訪深度限制 (防止掃到無窮嵌套的 UI 樹耗時過久)
# 經驗值：絕大多數「有意義的可點擊元素」都在 depth 5 以內
MAX_WALK_DEPTH: int = 5


def get_clickable_elements() -> List[Dict[str, Any]]:
    """
    智能剪枝掃描 (Smart Pruning Scan)：只掃描「前景視窗 + 可見的彈出層」。

    為什麼不做全桌面 WalkControl？
      1. 背景應用程式 (Line / Spotify / 檔案總管) 的 UI 節點會灌進來，
         一次掃到幾千幾萬個元素
      2. AI 收到這麼大的 text_list，context 直接撐爆
      3. 掃描時間也會拉長到數秒

    本函式的剪枝策略 (兩關)：
      關卡 1 — 頂層視窗過濾：只保留
        (a) 當前前景視窗 (GetForegroundControl)
        (b) 可見的 MenuControl / WindowControl / PaneControl
            (右鍵選單、對話框、ComboBox 下拉等)
      關卡 2 — 深度限制：每個保留的頂層視窗只走訪 depth <= 5

    回傳格式 (list[dict])：
        [
            {
                "id":           int,            # 元素編號 (0, 1, 2, ...)
                "name":         str,            # 元素名稱 (例如 "確定")
                "control_type": str,            # 元素類型 (例如 "ButtonControl")
                "bbox":         (l, t, r, b),   # 邊界框 (left, top, right, bottom)
                "center":       (cx, cy),       # 中心點座標 (已處理過 DPI)
                "window_name":  str,            # 該元素所屬的視窗名稱
            },
            ...
        ]
    """
    elements: List[Dict[str, Any]] = []
    # 用 set 記錄已抓過的 bbox，過濾掉「父子控制項重疊在同一矩形」的情況
    seen_rects: set = set()
    # 記錄所有出現過的視窗 (用於文字清單的總覽區塊)
    window_set: set = set()

    root = uiautomation.GetRootControl()
    foreground = uiautomation.GetForegroundControl()

    # ============================================================
    # 關卡 1：過濾頂層視窗，只留「有意義」的兩類
    # ============================================================
    target_top_windows: list = []
    for win in root.GetChildren():
        try:
            # 條件 A：當前前景視窗 (主角)
            is_foreground = uiautomation.ControlsAreSame(win, foreground)

            # 條件 B：可見的彈出層 (配角：右鍵選單、對話框、ComboBox 下拉)
            # 用 BoundingRectangle 面積 > 0 判斷是否真的在畫面上
            is_visible_popup = False
            try:
                rect = win.BoundingRectangle
                if rect and (rect.right - rect.left) > 0 and (rect.bottom - rect.top) > 0:
                    # 只抓特定 ControlType，避免抓到背景閒置應用程式的隱藏視窗
                    if win.ControlTypeName in ("MenuControl", "WindowControl", "PaneControl"):
                        is_visible_popup = True
            except Exception:
                is_visible_popup = False

            if is_foreground or is_visible_popup:
                target_top_windows.append(win)
        except Exception:
            # 單一頂層視窗讀取失敗不影響整體
            continue

    # ============================================================
    # 關卡 2：只對「有意義的視窗」做深度走訪 (限制 maxDepth=5)
    # ============================================================
    for top_win in target_top_windows:
        try:
            current_window_name = (top_win.Name or "").strip() or "(未命名視窗)"
            # 排除桌面/Program Manager (它不是應用程式)
            if current_window_name.lower() in ("program manager", "desktop"):
                current_window_name = "(桌面)"
            window_set.add(current_window_name)

            for control, depth in uiautomation.WalkControl(
                top_win, includeTop=True, maxDepth=MAX_WALK_DEPTH
            ):
                try:
                    # 1. 取得控制項類型名稱 (例如 "ButtonControl")
                    ctype = control.ControlTypeName
                    if ctype not in CLICKABLE_CONTROL_TYPES:
                        continue

                    # 2. 取得 BoundingRectangle
                    rect = control.BoundingRectangle
                    if rect is None:
                        continue

                    left, top, right, bottom = (
                        rect.left, rect.top, rect.right, rect.bottom
                    )
                    width = right - left
                    height = bottom - top

                    # 3. 過濾掉面積過小的元素
                    if width < MIN_ELEMENT_SIZE or height < MIN_ELEMENT_SIZE:
                        continue

                    # 4. 過濾掉重複的矩形 (父子控制項重疊時常見)
                    rect_key = (left, top, right, bottom)
                    if rect_key in seen_rects:
                        continue
                    seen_rects.add(rect_key)

                    # 5. 計算中心點座標
                    cx = (left + right) // 2
                    cy = (top + bottom) // 2

                    # 6. 加入元素清單
                    elements.append({
                        "id":           len(elements),
                        "name":         control.Name or "",
                        "control_type": ctype,
                        "bbox":         (left, top, right, bottom),
                        "center":       (cx, cy),
                        "window_name":  current_window_name,
                    })
                except Exception:
                    # 單一元素讀取失敗不影響整體
                    continue
        except Exception:
            # 整個視窗走訪失敗不影響其他視窗
            continue

    # 把所有出現過的視窗記在第一個元素上 (供 Prompt 顯示總覽)
    if elements:
        elements[0]["_all_windows"] = sorted(window_set)
    return elements


# ============================================================
# 函數 2：產生「帶有 Set-of-Mark 標記」的螢幕截圖
# ============================================================
def _needs_callout(elem: Dict[str, Any]) -> bool:
    """
    判斷某個元素是否需要用「外部 callout 標籤」來標記。
    判斷標準：元素寬度或高度小於門檻值。
    """
    left, top, right, bottom = elem["bbox"]
    width = right - left
    height = bottom - top
    return (width < SMALL_ELEMENT_W_THRESHOLD) or (height < SMALL_ELEMENT_H_THRESHOLD)


def _draw_standard_label(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    elem: Dict[str, Any],
) -> None:
    """
    在元素的「左上角」繪製標準編號標籤 (適合一般大小的按鈕/分頁)。
    紅底白字、緊貼元素左上角。
    """
    idx = elem["id"]
    left, top, _right, _bottom = elem["bbox"]
    label_text = str(idx)

    # 計算標籤文字的尺寸
    text_bbox = draw.textbbox((0, 0), label_text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    # 繪製實心紅色背景 + 白色數字
    label_x1 = left
    label_y1 = top
    label_x2 = left + text_w + LABEL_PADDING * 2
    label_y2 = top + text_h + LABEL_PADDING * 2
    draw.rectangle(
        [(label_x1, label_y1), (label_x2, label_y2)],
        fill=LABEL_BG_COLOR,
    )
    draw.text(
        (label_x1 + LABEL_PADDING, label_y1 + LABEL_PADDING),
        label_text,
        fill=LABEL_TEXT_COLOR,
        font=font,
    )


def _calc_callout_position(
    elem: Dict[str, Any],
    label_size: int,
    img_w: int,
    img_h: int,
) -> Tuple[int, int]:
    """
    計算 callout 標籤的左上角 (x, y) 座標。
    策略：
      1. 預設放在元素「正上方」(垂直置中對齊元素)
      2. 若會超出畫面上邊界，則改放在元素「正下方」
      3. 處理左右邊界，避免標籤超出畫面
    """
    left, top, right, bottom = elem["bbox"]
    cx, _cy = elem["center"]

    # 標籤中心對齊元素中心 (x 方向)
    label_x = cx - label_size // 2
    # 標籤放在元素上方
    label_y = top - label_size - CALLOUT_GAP

    # 超出上邊界 → 改放下方
    if label_y < 0:
        label_y = bottom + CALLOUT_GAP

    # 處理左右邊界 (clamp 到畫面範圍內)
    if label_x < 0:
        label_x = 0
    elif label_x + label_size > img_w:
        label_x = img_w - label_size

    # 處理上下邊界 (雙重保險)
    if label_y < 0:
        label_y = 0
    elif label_y + label_size > img_h:
        label_y = img_h - label_size

    return (label_x, label_y)


def _draw_callout_label(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    elem: Dict[str, Any],
    img_w: int,
    img_h: int,
) -> None:
    """
    為「小元素」繪製 callout 標籤：
      1. 在元素外部 (上方優先，其次下方) 畫一個固定大小的方塊
      2. 用一條細線 (黑線 + 白邊) 從元素連到方塊

    這是為了解決「紅框/編號把小按鈕整個蓋住」與「相鄰小元素標籤黏在一起」
    的視覺問題。Callout 標籤固定大小，元素再小都不會被蓋住。
    """
    idx = elem["id"]
    left, top, right, bottom = elem["bbox"]
    cx, cy = elem["center"]
    label_text = str(idx)
    label_size = CALLOUT_LABEL_SIZE

    # (1) 計算標籤位置
    label_x, label_y = _calc_callout_position(elem, label_size, img_w, img_h)
    label_cx = label_x + label_size // 2
    label_cy = label_y + label_size // 2

    # (2) 計算導引線的兩端 (從元素邊緣到標籤邊緣，避免線穿過元素或標籤)
    if label_cy < top:    # 標籤在元素上方
        line_start = (cx, top)
        line_end = (label_cx, label_y + label_size)
    else:                 # 標籤在元素下方
        line_start = (cx, bottom)
        line_end = (label_cx, label_y)

    # (3) 繪製導引線 (先畫白色外框，再畫黑色本體，確保在各種背景下都看得見)
    for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        draw.line(
            [
                (line_start[0] + dx, line_start[1] + dy),
                (line_end[0] + dx, line_end[1] + dy),
            ],
            fill=CALLOUT_LINE_OUTLINE,
            width=3,
        )
    draw.line([line_start, line_end], fill=CALLOUT_LINE_COLOR, width=1)

    # (4) 繪製 callout 標籤方塊 (紅底 + 白邊框)
    draw.rectangle(
        [(label_x, label_y), (label_x + label_size, label_y + label_size)],
        fill=LABEL_BG_COLOR,
        outline=CALLOUT_BORDER_COLOR,
        width=CALLOUT_BORDER_WIDTH,
    )

    # (5) 將數字文字「置中」繪製在方塊內
    text_bbox = draw.textbbox((0, 0), label_text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    text_x = label_x + (label_size - text_w) // 2
    text_y = label_y + (label_size - text_h) // 2 - 2  # -2 微調讓視覺更置中
    draw.text(
        (text_x, text_y),
        label_text,
        fill=LABEL_TEXT_COLOR,
        font=font,
    )


def generate_marked_screenshot(
    elements: List[Dict[str, Any]],
) -> Dict[int, Tuple[int, int]]:
    """
    截取目前螢幕畫面，並在每個 UI 元素上繪製：
      1. 紅色矩形外框
      2. 左上角的「實心紅底 + 白色數字」標籤

    參數：
        elements (list[dict]): get_clickable_elements() 的回傳結果

    回傳：
        coord_map (dict): 將「數字編號」對應到「中心點 (x, y) 座標」
                          例如 {0: (450, 320), 1: (612, 88), ...}
    """
    # --------------------------------------------------------
    # (A) 螢幕截圖
    # --------------------------------------------------------
    # 設定 SetProcessDPIAware 已經在模組載入時完成，
    # 因此 pyautogui.screenshot() 會回傳「實體像素」大小的圖片。
    screenshot = pyautogui.screenshot()
    # 轉成 RGB 模式，避免 RGBA 在存檔時出現非預期結果
    image = screenshot.convert("RGB")
    draw = ImageDraw.Draw(image)

    # --------------------------------------------------------
    # (B) 載入字型
    # --------------------------------------------------------
    # 優先使用 Windows 內建的「微軟正黑體」來顯示中文字，
    # 若找不到則退回 Pillow 內建字型。
    # 由於「標準標籤」與「Callout 標籤」字型大小不同，必須分別載入。
    font = None
    callout_font = None
    try:
        msyh_path = r"C:\Windows\Fonts\msyh.ttc"
        if os.path.exists(msyh_path):
            font = ImageFont.truetype(msyh_path, LABEL_FONT_SIZE)
            callout_font = ImageFont.truetype(msyh_path, CALLOUT_FONT_SIZE)
    except Exception:
        font = None
        callout_font = None
    if font is None:
        # 退回預設字型 (可能不支援中文，但至少能顯示數字)
        font = ImageFont.load_default()
    if callout_font is None:
        callout_font = ImageFont.load_default()

    # 取得整張截圖的尺寸 (供 callout 標籤避免超出邊界用)
    img_w, img_h = image.size

    # --------------------------------------------------------
    # (C) 逐一繪製每個元素的紅框與編號
    # --------------------------------------------------------
    coord_map: Dict[int, Tuple[int, int]] = {}

    for elem in elements:
        idx = elem["id"]                       # 元素編號
        left, top, right, bottom = elem["bbox"]
        cx, cy = elem["center"]                # 中心點座標

        # (1) 繪製紅色矩形外框
        draw.rectangle(
            [(left, top), (right, bottom)],
            outline=BOX_COLOR,
            width=BOX_WIDTH,
        )

        # (2) 判斷是否需要使用 callout (小元素用導引線拉到外面畫)
        if _needs_callout(elem):
            _draw_callout_label(draw, callout_font, elem, img_w, img_h)
        else:
            _draw_standard_label(draw, font, elem)

        # (3) 記錄「編號 -> 中心座標」對應
        coord_map[idx] = (cx, cy)

    # --------------------------------------------------------
    # (D) 將標記後的圖片存檔
    # --------------------------------------------------------
    abs_path = os.path.abspath(OUTPUT_IMAGE_PATH)
    image.save(OUTPUT_IMAGE_PATH)
    print(f"[完成] 標記圖片已儲存至：{abs_path}")

    return coord_map


# ============================================================
# 函數 2b：產生「帶有 N×M 網格」的螢幕截圖 (Grid Fallback)
# ============================================================
def generate_grid_screenshot(
    rows: int = GRID_DEFAULT_ROWS,
    cols: int = GRID_DEFAULT_COLS,
) -> Tuple[Image.Image, Dict[str, Tuple[int, int]]]:
    """
    拍一張螢幕截圖，並在上面疊加一個 rows×cols 的均勻網格，
    每個格子左上角貼一個黃底黑字的 label (例如 A1、B5、J10)。
    這是當 UIA 抓不到任何元素時的「純視覺降級機制」。

    標籤規則：
        - 直行 (col)：A, B, C, ... 從左到右
        - 橫列 (row)：1, 2, 3, ... 從上到下
        - 完整 label：{col_letter}{row_number}，例如 "C5" 表示第 C 欄第 5 列
        - 範圍：A1 (左上) ~ Z{rows} (右下)

    參數：
        rows: 列數 (預設 10)
        cols: 欄數 (預設 10)

    回傳：
        (image, grid_map):
            - image:    PIL.Image 物件 (含網格疊加)
            - grid_map: dict，{ "A1": (cx, cy), "A2": (cx, cy), ... }，
                        cx/cy 為該格子的「中心座標」(像素)
    """
    # 邊界保護
    rows = max(GRID_MIN_SIZE, min(GRID_MAX_SIZE, rows))
    cols = max(GRID_MIN_SIZE, min(GRID_MAX_SIZE, cols))
    if cols > len(GRID_COL_LETTERS):
        raise ValueError(
            f"cols={cols} 超過字母表長度 {len(GRID_COL_LETTERS)}"
        )

    # 1. 拍螢幕截圖
    screen = pyautogui.screenshot()
    width, height = screen.size
    cell_w = width / cols
    cell_h = height / rows

    # 2. 載入字型 (若找不到 arial 就退回預設)
    try:
        label_font = ImageFont.truetype("arial.ttf", 16)
    except (OSError, IOError):
        label_font = ImageFont.load_default()

    draw = ImageDraw.Draw(screen)

    # 3. 畫格線 (直 + 橫)
    for c in range(cols + 1):
        x = int(c * cell_w)
        draw.line([(x, 0), (x, height)], fill=GRID_LINE_COLOR, width=1)
    for r in range(rows + 1):
        y = int(r * cell_h)
        draw.line([(0, y), (width, y)], fill=GRID_LINE_COLOR, width=1)

    # 4. 為每個格子畫 label (左上角黃底) 並記錄中心座標
    grid_map: Dict[str, Tuple[int, int]] = {}
    label_box_w, label_box_h = 38, 22
    for r in range(rows):
        for c in range(cols):
            label = f"{GRID_COL_LETTERS[c]}{r + 1}"
            cell_x = int(c * cell_w)
            cell_y = int(r * cell_h)
            # 黃底黑字標籤 (左上角)
            draw.rectangle(
                [cell_x + 3, cell_y + 3,
                 cell_x + 3 + label_box_w, cell_y + 3 + label_box_h],
                fill=GRID_LABEL_BG,
                outline=GRID_LABEL_OUTLINE,
                width=1,
            )
            draw.text(
                (cell_x + 8, cell_y + 5),
                label,
                fill=GRID_LABEL_FG,
                font=label_font,
            )
            # 中心座標
            cx = int((c + 0.5) * cell_w)
            cy = int((r + 0.5) * cell_h)
            grid_map[label] = (cx, cy)

    print(
        f"[Grid] 已產生 {rows}×{cols} 網格，"
        f"格數={len(grid_map)}，A1~{GRID_COL_LETTERS[cols - 1]}{rows}"
    )
    return screen, grid_map


# ============================================================
# 函數 2c：將 grid_id (例如 "C5") 解析為該格子的中心座標
# ============================================================
def resolve_grid_id(
    grid_id: str,
    grid_map: Dict[str, Tuple[int, int]],
) -> Tuple[int, int]:
    """
    從 grid_id 字串取出對應格子的中心座標 (像素)。

    參數：
        grid_id:  例如 "C5" / "c5" / " J10 " (自動 trim & 大寫)
        grid_map: generate_grid_screenshot() 回傳的對應表

    回傳：
        (cx, cy): 該格子的中心座標

    例外：
        ValueError: grid_id 為空、或不存在於 grid_map 中
    """
    if not grid_id or not grid_id.strip():
        raise ValueError("grid_id 不可為空 (例如 'C5')")
    if not grid_map:
        raise ValueError("grid_map 是空的，請先呼叫 generate_grid_screenshot()")

    key = grid_id.strip().upper()
    if key not in grid_map:
        avail_sample = sorted(grid_map.keys())[:8]
        raise ValueError(
            f"grid_id {grid_id!r} (正規化為 {key!r}) 不存在於 grid_map。"
            f"可用範例：{avail_sample} ... (共 {len(grid_map)} 個)"
        )
    return grid_map[key]


# ============================================================
# 函數 3 (輔助)：依編號取得中心座標 (給後續階段呼叫)
# ============================================================
def get_center_by_id(
    coord_map: Dict[int, Tuple[int, int]],
    element_id: int,
) -> Tuple[int, int]:
    """
    給定 AI 模型回傳的「數字編號」，查出對應的螢幕中心座標。
    若編號不存在則拋出例外。

    參數：
        coord_map:    generate_marked_screenshot() 回傳的對應表
        element_id:   AI 模型給出的編號

    回傳：
        (x, y): 該元素在螢幕上的中心座標
    """
    if element_id not in coord_map:
        raise ValueError(f"找不到編號 {element_id} 對應的元素")
    return coord_map[element_id]


# ============================================================
# 函數 4：將「編號 -> 中心座標」對應表存成 JSON
# ============================================================
def save_coord_map(
    coord_map: Dict[int, Tuple[int, int]],
    output_path: str = COORD_MAP_PATH,
) -> None:
    """
    將座標表存成 JSON 檔案，方便 Phase 3 的 VS Code Extension 讀取。
    JSON 格式範例：
        {
            "0": [450, 320],
            "1": [612, 88],
            "2": [1250, 75]
        }
    註：JSON 規範不允許整數當 key，所以這裡將 key 統一轉成字串。
    """
    serializable = {str(k): [int(v[0]), int(v[1])] for k, v in coord_map.items()}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"[完成] 座標表已儲存至：{os.path.abspath(output_path)}")


# ============================================================
# 函數 5：將圖片檔編碼為 Base64 字串
# ============================================================
def encode_image_to_base64(image_path: str) -> str:
    """
    讀取指定路徑的圖片，並回傳 Base64 編碼後的字串。
    此字串會被組合成 data URL (`data:image/png;base64,...`) 傳給 Vision Model。
    """
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ============================================================
# 函數 5b：將元素清單組成「給 AI 看的文字描述」
# ============================================================
def build_element_text_list(
    elements: List[Dict[str, Any]],
    max_items: int = TEXT_LIST_MAX_ITEMS,
) -> str:
    """
    把 UIA 抓到的元素整理成簡潔的文字清單，
    讓 AI 可以用「語意」(例如看到「確定」兩個字) 判斷，
    而不是只能靠圖片上的紅框與編號去猜。

    每個元素前綴會帶上「[視窗名稱]」標籤，這對於「多視窗都有同名元素」
    (例如多個視窗的關閉 X 按鈕) 是必要的判斷依據。

    範例輸出：
        [畫面上偵測到的視窗] 工作管理員, Windows PowerShell, 檔案總管

        可點擊元素清單 (共 1056 個，這裡列前 60 個)：
        [0] [工作管理員] Button '處理程序' @(100, 200)
        ...
        [30] [工作管理員] Button '' @(1200, 80)        ← 工作管理員的 X
        [40] [Windows PowerShell] Button '' @(1206, 80) ← PowerShell 的 X
    """
    # 收集所有出現過的視窗 (從第一個元素上的 _all_windows 拿)
    all_windows: List[str] = []
    if elements and "_all_windows" in elements[0]:
        all_windows = elements[0]["_all_windows"]

    lines: List[str] = []
    # (1) 視窗總覽
    if all_windows:
        lines.append(f"[畫面上偵測到的視窗] {' | '.join(all_windows)}")
        lines.append("")

    # (2) 元素清單
    lines.append(
        f"可點擊元素清單 (共 {len(elements)} 個，這裡列前 "
        f"{min(len(elements), max_items)} 個)："
    )
    for elem in elements[:max_items]:
        ctype_short = elem["control_type"].replace("Control", "")
        name = (elem.get("name") or "").strip().replace("\n", " ")[:40]
        wname = elem.get("window_name", "(未知視窗)")
        cx, cy = elem["center"]
        if name:
            lines.append(
                f"  [{elem['id']:>3}] [{wname}] {ctype_short} '{name}' @({cx}, {cy})"
            )
        else:
            lines.append(
                f"  [{elem['id']:>3}] [{wname}] {ctype_short} (無文字) @({cx}, {cy})"
            )
    if len(elements) > max_items:
        lines.append(f"  ... (略過 {len(elements) - max_items} 個，編號 ≥ {max_items})")

    return "\n".join(lines)


# ============================================================
# 函數 5c：解析 Vision Model 的回應字串為「動作字典」
# ============================================================
def parse_ai_response(raw_text: str) -> Dict[str, Any]:
    """
    將 Vision Model 的回傳字串清洗、解析為「動作字典」。

    模型可能回傳的格式 (由寬鬆到嚴格)：
      (a) 純 JSON 物件，例如：   {"action": "click", "target_id": 5, "reason": "..."}
      (b) 包在 ```json ... ``` 內的 JSON 區塊
      (c) JSON 後面接一些廢話 (例如 "好的，已經為您點擊...")，本函式會自動抓出第一個 {...}
      (d) 舊版「純數字」回應 (例如 "5")，自動包成 click 動作 (向後相容)

    參數：
        raw_text: Vision Model 原始回應字串

    回傳：
        dict: 例如
            {"action": "click", "target_id": 5, "reason": "..."}
            {"action": "type",  "text": "hello", "reason": "..."}
            {"action": "hotkey","keys": "ctrl+c","reason": "..."}
            {"action": "NOT_FOUND", "reason": "..."}

    例外：
        ValueError: 無法解析成任何已知的動作格式
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("模型回傳為空字串")

    text = raw_text.strip()

    # --------------------------------------------------------
    # 步驟 1：剝掉 markdown 程式碼區塊 (```json ... ``` 或 ``` ... ```)
    # --------------------------------------------------------
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    # --------------------------------------------------------
    # 步驟 2：抓出「候選 JSON 物件」(容忍 JSON 後面接廢話、或缺少右大括號)
    # --------------------------------------------------------
    # 兩種情況：
    #   (a) 有完整的 {...} 區塊：取第一個 { 到最後一個 } 之間
    #   (b) 只有 { 沒有 } (模型被截斷)：取第一個 { 到字串結尾
    candidate = ""
    if "{" in text:
        start = text.index("{")
        if "}" in text[start:]:
            end = text.rindex("}") + 1
            candidate = text[start:end]
        else:
            # 模型輸出被截斷，從 { 抓到結尾
            candidate = text[start:]

    # --------------------------------------------------------
    # 步驟 3：嘗試解析 JSON；若不完整，自動補上缺少的右大括號
    # --------------------------------------------------------
    parsed: Optional[Dict[str, Any]] = None
    if candidate:
        # 先嘗試直接解析
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                parsed = obj
        except json.JSONDecodeError:
            # 解析失敗 → 嘗試修補：補上缺少的右大括號
            fixed = candidate
            while fixed.count("{") > fixed.count("}"):
                fixed += "}"
            try:
                obj = json.loads(fixed)
                if isinstance(obj, dict):
                    parsed = obj
            except json.JSONDecodeError:
                pass

    # --------------------------------------------------------
    # 步驟 4：若不是 JSON，看是不是「舊版純數字」(向後相容)
    # --------------------------------------------------------
    if parsed is None:
        match = re.search(r"\d+", text)
        if match:
            parsed = {
                "action": "click",
                "target_id": int(match.group(0)),
                "reason": "(舊版數字格式，自動轉為 click 動作)",
            }
        else:
            raise ValueError(
                f"無法解析模型回應為 JSON 動作，也找不到任何數字：\n{raw_text!r}"
            )

    # --------------------------------------------------------
    # 步驟 5：驗證 action 欄位 (必要時自動補上 'click')
    # --------------------------------------------------------
    action_raw = str(parsed.get("action", "")).strip()
    if not action_raw and "target_id" in parsed:
        # 例如 {"target_id": 5} 沒有 action 欄位 → 預設為 click
        action_raw = "click"

    # 大小寫不敏感地比對，找出 canonical 形式
    # (支援的動作在 SUPPORTED_ACTIONS 內是標準大小寫，例如 'click' / 'NOT_FOUND')
    canonical: Optional[str] = None
    for supported in SUPPORTED_ACTIONS:
        if supported.lower() == action_raw.lower():
            canonical = supported
            break

    if canonical is None:
        raise ValueError(
            f"不支援的 action：{action_raw!r}。"
            f"支援的動作：{sorted(SUPPORTED_ACTIONS)}"
        )

    # 正規化回 canonical 大小寫 (例如 'not_found' → 'NOT_FOUND')
    parsed["action"] = canonical
    return parsed


# ============================================================
# 函數 6：呼叫 Vision Model 取得「動作字典」
# ============================================================
def ask_vision_model(
    image_path: str,
    user_instruction: str,
    elements: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    將標記過的截圖、使用者意圖 (與可選的元素文字清單) 送給 Vision Model，
    取得 AI 判斷後的「動作字典」(action + 對應欄位)。
    若模型回應無法解析，則回傳 None。

    參數：
        image_path:       標記過的截圖路徑
        user_instruction: 使用者意圖 (例如 "關閉視窗的 X 按鈕")
        elements:         (選用) UIA 抓到的元素清單，
                          若提供則會一併塞進 Prompt，幫助 AI 用「語意」判斷
                          (這對小元素 / 純圖示按鈕特別有效)

    回傳：
        清洗過的「數字字串」，或 None (解析失敗時)
    """
    # --------------------------------------------------------
    # (A) 解析最終生效的 API 設定 (CLI > 環境變數 > 模組全域)
    # --------------------------------------------------------
    api_key = API_KEY or os.environ.get("VISION_API_KEY", "")
    base_url = BASE_URL or os.environ.get(
        "VISION_BASE_URL", "https://opencode.ai/zen/go"
    )
    model_name = MODEL_NAME or os.environ.get("VISION_MODEL", "qwen3.7-plus")

    if not _ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic 套件未安裝，請先 pip install anthropic")
    if not api_key:
        raise RuntimeError(
            "尚未設定 API Key！請在 agent_engine.py 填入 API_KEY，"
            "或設定環境變數 VISION_API_KEY，或使用 --api-key 參數。"
        )

    # --------------------------------------------------------
    # (B) 將圖片編碼為 Base64
    # --------------------------------------------------------
    # 注意：Anthropic API 只需要純 base64 字串，不需要 data URL 前綴
    print(f"[編碼中] 將 {image_path} 轉為 Base64...")
    b64_image = encode_image_to_base64(image_path)

    # --------------------------------------------------------
    # (C) 建構 Prompt
    # --------------------------------------------------------
    # System Prompt：給模型的角色設定與輸出規範
    # 【Phase 2.6 改版】不再要求只回數字，而是回傳「動作 JSON」
    system_prompt = (
        "你是一個精準的 Windows UI 操作助手。\n"
        "你的唯一任務是：根據使用者意圖，從給定的『帶有數字編號的截圖』中，"
        "挑出最符合的元素，並決定要對它執行什麼動作。\n\n"
        "【你必須輸出一個 JSON 物件，不要任何其他文字、標點、Markdown 或解釋】\n"
        "支援的動作 (action 欄位必須是以下其中之一)：\n"
        '  - {"action": "click",        "target_id": <number>, "reason": "..."}     # 左鍵單擊\n'
        '  - {"action": "double_click", "target_id": <number>, "reason": "..."}     # 雙擊\n'
        '  - {"action": "right_click",  "target_id": <number>, "reason": "..."}     # 右鍵\n'
        '  - {"action": "type",         "text": "<要輸入的字串>", "reason": "..."}   # 鍵盤輸入\n'
        '  - {"action": "hotkey",       "keys": "<例如 ctrl+c 或 alt+F4>", "reason": "..."}  # 熱鍵\n'
        '  - {"action": "scroll",       "direction": "up|down|left|right", "clicks": <number>, "reason": "..."}  # 捲動 (clicks 預設 3，可選帶 target_id 指定位置)\n'
        '  - {"action": "drag",         "start_id": <number>, "end_id": <number>, "reason": "..."}  # 拖曳 (start_id → end_id)\n'
        '  - {"action": "NOT_FOUND",    "reason": "找不到可完成任務的元素"}           # 找不到時用\n\n'
        "【動作選擇規則】\n"
        "1. 使用者說『點擊/按/選擇/打開連結』→ click\n"
        "2. 使用者說『雙擊/打開(檔案)/連點兩下』→ double_click\n"
        "3. 使用者說『右鍵/右鍵選單/內容選單』→ right_click\n"
        "4. 使用者說『打/輸入/輸入文字/搜尋/打 XXX 這段字』→ type (此時請把完整字串放在 text 欄位)\n"
        "5. 使用者說『複製/貼上/存檔/關閉視窗/全選/復原/最小化/切換桌面』等 → hotkey\n"
        "   對應熱鍵範例：ctrl+c、ctrl+v、ctrl+s、alt+F4、ctrl+a、ctrl+z、win+d\n"
        "6. 使用者說『往下捲/往上捲/滾輪向下/滑到下面/看到更多』等 → scroll (direction=down 或 up)\n"
        "   若目標元素不在畫面中 (例如很長的網頁/清單)，先 scroll 再點。\n"
        "7. 使用者說『拖曳/拖到/把 A 拉到 B/調整 XXX 寬度/移動檔案到』等 → drag (start_id → end_id)\n"
        "8. 使用者的意圖在畫面上找不到對應元素 → NOT_FOUND\n"
        "9. 元素清單中每個元素都有 [視窗名稱] 前綴，請依視窗名稱挑選正確的元素"
    )

    # User Prompt：包含 (1) 元素文字清單 (2) 任務說明 與 (3) 使用者意圖
    # 註：當 elements 提供時，AI 可以用「語意」直接對照名稱判斷 (例如「確定」「取消」)
    #     圖片只作為空間位置輔助參考。對於非常小的元素 (小圖示按鈕) 特別有效。
    text_list_section = ""
    if elements:
        text_list_section = build_element_text_list(elements) + "\n\n"

    user_prompt = (
        text_list_section
        + "這是一張帶有數字編號的 Windows UI 截圖 (圖中每個元素都有一個紅色編號)。\n"
        + f"使用者的意圖是：{user_instruction}。\n\n"
        + "【重要判斷規則】\n"
        + "1. 請先看清單頂部的 [畫面上偵測到的視窗] 區塊，了解目前螢幕上有哪幾個視窗。\n"
        + "2. 請優先根據「視窗名稱」匹配使用者意圖：\n"
        + "   - 如果使用者明確提到某個視窗 (例如「工作管理員」「檔案總管」)，"
        + "     請只從該視窗內的元素中挑選。\n"
        + "   - 如果使用者沒指定視窗，請挑選語意最符合的元素。\n"
        + "3. 元素清單中每個元素前綴的 [視窗名稱] 標籤就是它所屬的視窗，請善加利用。\n"
        + "4. 對於多個視窗都有同類按鈕 (例如每個視窗都有自己的『關閉 X』)，"
        + "一定要依「視窗名稱」挑選正確的那個。\n\n"
        + "【輸出格式】請輸出一個 JSON 物件，例如：\n"
        + '  - click       → {"action": "click", "target_id": 5, "reason": "..."}\n'
        + '  - type        → {"action": "type",  "text": "hello", "reason": "..."}\n'
        + '  - hotkey      → {"action": "hotkey","keys": "ctrl+c","reason": "..."}\n'
        + '  - NOT_FOUND   → {"action": "NOT_FOUND", "reason": "找不到搜尋框"}\n'
        + "請只輸出那一個 JSON 物件，絕對不要包含其他文字、標點符號或解釋。"
    )

    # --------------------------------------------------------
    # (D) 呼叫 Anthropic Messages API
    # --------------------------------------------------------
    # OpenCode Go 的 Qwen 系列使用 Anthropic 格式 (POST /v1/messages)，
    # 而非 OpenAI 格式 (POST /v1/chat/completions)。
    print(f"[呼叫 Vision Model] {model_name} @ {base_url}")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    try:
        response = client.messages.create(
            model=model_name,
            system=system_prompt,           # Anthropic 將 system 獨立於 messages 之外
            messages=[
                {
                    "role": "user",
                    "content": [
                        # 先放圖片 (Anthropic 慣例：圖片在前、文字在後效果較佳)
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64_image,
                            },
                        },
                        # 再放文字指令
                        {
                            "type": "text",
                            "text": user_prompt,
                        },
                    ],
                },
            ],
            max_tokens=300,   # 提高上限，JSON 動作可能稍長 (含 reason 欄位)
            temperature=0,    # 設為 0 讓輸出更穩定、可重現
        )
    except Exception as exc:
        raise RuntimeError(f"Vision Model API 呼叫失敗：{exc}") from exc

    # --------------------------------------------------------
    # (E) 解析並清洗模型回應
    # --------------------------------------------------------
    # Anthropic 回應結構：response.content 是 list，每個元素是 TextBlock / ImageBlock ...
    # 我們只關心 type="text" 的區塊並串接起來
    raw_answer = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            raw_answer += block.text
    raw_answer = raw_answer.strip()
    print(f"[模型回應] 原始字串：{raw_answer!r}")

    # 交給 parse_ai_response 清洗成動作字典 (會處理 markdown fence / 容錯補括號 / 舊版數字)
    try:
        action_dict = parse_ai_response(raw_answer)
    except ValueError as exc:
        print(f"[警告] {exc}")
        return None

    print(
        f"[解析結果] 動作：{action_dict.get('action')}, "
        f"target_id={action_dict.get('target_id')}, "
        f"text={action_dict.get('text')!r}, "
        f"keys={action_dict.get('keys')!r}"
    )
    return action_dict


# ============================================================
# 函數 6b：呼叫 Vision Model (Grid Fallback 純視覺模式)
# ============================================================
def ask_vision_model_grid(
    image_path: str,
    user_instruction: str,
    rows: int = GRID_DEFAULT_ROWS,
    cols: int = GRID_DEFAULT_COLS,
) -> Optional[Dict[str, Any]]:
    """
    純視覺模式：把「疊加網格後的截圖」送給模型，
    模型根據格子 label (A1, C5, J10...) 回傳包含 grid_id 的動作字典。
    適用於 UIA 抓不到任何元素的場景 (例如 Electron 客製化介面、遊戲、WebGL 畫布)。

    與 ask_vision_model 的差異：
        - Prompt 改為要求 grid_id (例如 "C5") 而非 target_id (例如 30)
        - 點擊類動作會帶有 grid_id；scroll/drag 可選擇帶 grid_id 作為座標

    參數：
        image_path:       含網格疊加的截圖路徑
        user_instruction: 使用者意圖
        rows / cols:      網格大小 (預設 10x10，會跟圖片上的標記一致)

    回傳：
        dict: 例如 {"action": "click", "grid_id": "C5", "reason": "..."}
              或 None (解析失敗)
    """
    # --------------------------------------------------------
    # (A) 解析最終生效的 API 設定
    # --------------------------------------------------------
    api_key = API_KEY or os.environ.get("VISION_API_KEY", "")
    base_url = BASE_URL or os.environ.get(
        "VISION_BASE_URL", "https://opencode.ai/zen/go"
    )
    model_name = MODEL_NAME or os.environ.get("VISION_MODEL", "qwen3.7-plus")

    if not _ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic 套件未安裝，請先 pip install anthropic")
    if not api_key:
        raise RuntimeError("尚未設定 API Key！")

    # --------------------------------------------------------
    # (B) 編碼圖片
    # --------------------------------------------------------
    print(f"[編碼中] 將 {image_path} 轉為 Base64 (grid mode)...")
    b64_image = encode_image_to_base64(image_path)

    # --------------------------------------------------------
    # (C) 建構 Prompt (Grid 模式專用)
    # --------------------------------------------------------
    col_letters_str = GRID_COL_LETTERS[:cols]
    row_range_str = f"1~{rows}"

    system_prompt = (
        "你是一個精準的 Windows UI 操作助手，目前處於「純視覺網格模式」。\n"
        f"螢幕已被劃分成 {cols} 欄 × {rows} 列的均勻網格。\n"
        f"欄的標籤是 A, B, C, ..., {col_letters_str[-1]} (從左到右)。\n"
        f"列的標籤是 1, 2, 3, ..., {row_range_str.split('~')[-1]} (從上到下)。\n"
        "每個格子的左上角都有一個黃底黑字的標籤 (例如 A1, B5, J10)，代表「欄+列」。\n"
        "你的任務：根據使用者意圖與螢幕截圖，\n"
        "挑出最符合的格子 (或格子組合)，並決定要對它做什麼動作。\n\n"
        "【你必須輸出一個 JSON 物件，不要任何其他文字、標點、Markdown 或解釋】\n"
        "支援的動作 (action 欄位必須是以下其中之一)：\n"
        '  - {"action": "click",        "grid_id": "C5", "reason": "..."}     # 點擊格子 C5 中心\n'
        '  - {"action": "double_click", "grid_id": "C5", "reason": "..."}     # 雙擊\n'
        '  - {"action": "right_click",  "grid_id": "C5", "reason": "..."}     # 右鍵\n'
        '  - {"action": "type",         "text": "<要輸入的字串>", "reason": "..."}    # 鍵盤輸入\n'
        '  - {"action": "hotkey",       "keys": "<例如 ctrl+c>", "reason": "..."}    # 熱鍵\n'
        '  - {"action": "scroll",       "direction": "down", "clicks": 3, "reason": "..."}  # 捲動 (可選帶 grid_id 指定捲動位置)\n'
        '  - {"action": "drag",         "start_grid_id": "A1", "end_grid_id": "B5", "reason": "..."}  # 拖曳\n'
        '  - {"action": "NOT_FOUND",    "reason": "找不到可完成任務的元素"}  # 找不到時\n\n'
        "【grid_id 規則】\n"
        f"  - 格式：{col_letters_str[0]}1, {col_letters_str[1]}1, ..., {col_letters_str[-1]}{rows}\n"
        "  - 全部大寫 (例如 C5，不能寫 c5 或 row 5 col C)\n"
        "  - 必須是圖片上實際有標記的格子\n"
    )

    user_prompt = (
        f"這是一張已被疊加 {cols}×{rows} 網格的 Windows 螢幕截圖。\n"
        f"每個格子的左上角都有一個黃底黑字的 label (例如 A1, C5, J{rows})。\n"
        f"使用者的意圖是：{user_instruction}。\n\n"
        "請仔細看截圖，挑出對應的格子並決定動作，輸出對應的 JSON 物件。\n"
        "若使用者想操作某個按鈕/圖示/區塊，請挑選該元素「中心點所在的格子」。\n"
        "若找不到任何可完成任務的格子，請輸出 NOT_FOUND。\n"
        "【重要】請只輸出一個 JSON 物件，不要任何其他文字！"
    )

    # --------------------------------------------------------
    # (D) 呼叫 API
    # --------------------------------------------------------
    print(f"[呼叫 Vision Model (grid)] {model_name} @ {base_url}")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    try:
        response = client.messages.create(
            model=model_name,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64_image,
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            max_tokens=300,
            temperature=0,
        )
    except Exception as exc:
        raise RuntimeError(f"Vision Model (grid) API 呼叫失敗：{exc}") from exc

    # --------------------------------------------------------
    # (E) 解析回應
    # --------------------------------------------------------
    raw_answer = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            raw_answer += block.text
    raw_answer = raw_answer.strip()
    print(f"[模型回應 (grid)] 原始字串：{raw_answer!r}")

    try:
        action_dict = parse_ai_response(raw_answer)
    except ValueError as exc:
        print(f"[警告] {exc}")
        return None

    print(
        f"[解析結果 (grid)] 動作：{action_dict.get('action')}, "
        f"grid_id={action_dict.get('grid_id')!r}, "
        f"start={action_dict.get('start_grid_id')!r}, "
        f"end={action_dict.get('end_grid_id')!r}"
    )
    return action_dict


# ============================================================
# 函數 7：依「編號」執行滑鼠點擊 (支援單擊/雙擊/右鍵)
# ============================================================
def execute_click(
    target_id: Any,
    mapping_table: Dict[int, Tuple[int, int]],
    dry_run: bool = False,
    click_type: str = "single",
) -> Tuple[int, int]:
    """
    根據 AI 給的編號，從 mapping_table 取出中心座標並執行滑鼠點擊。

    參數：
        target_id:      AI 回傳的編號 (支援 int 或數字字串)
        mapping_table:  generate_marked_screenshot() 回傳的對應表
        dry_run:        若為 True，僅移動滑鼠、不實際點擊 (用於安全測試)
        click_type:     "single" (左鍵單擊) / "double" (左鍵雙擊) / "right" (右鍵)

    回傳：
        (x, y): 實際點擊 / 移動到的中心座標

    例外：
        ValueError:  target_id 不是數字、編號不存在、或 click_type 不合法
    """
    # --------------------------------------------------------
    # (A) 驗證 target_id 型別並轉成 int
    # --------------------------------------------------------
    if isinstance(target_id, str):
        stripped = target_id.strip()
        if not stripped.isdigit():
            raise ValueError(f"target_id 必須是數字字串，但收到：{target_id!r}")
        target_id_int = int(stripped)
    elif isinstance(target_id, int):
        target_id_int = target_id
    else:
        raise TypeError(
            f"target_id 必須是 int 或數字字串，但收到型別：{type(target_id).__name__}"
        )

    # --------------------------------------------------------
    # (B) 驗證編號是否真的存在於對應表中
    # --------------------------------------------------------
    if target_id_int not in mapping_table:
        avail = sorted(mapping_table.keys())
        raise ValueError(
            f"編號 {target_id_int} 不存在於 mapping_table 中。"
            f"可用編號範圍：{min(avail)} ~ {max(avail)} (共 {len(avail)} 個)"
        )

    # --------------------------------------------------------
    # (C) 驗證 click_type 並選用對應的 pyautogui 函式
    # --------------------------------------------------------
    click_type_norm = click_type.lower().strip()
    type_map = {
        "single": ("左鍵單擊", pyautogui.click),
        "double": ("雙擊",     pyautogui.doubleClick),
        "right":  ("右鍵",     pyautogui.rightClick),
    }
    if click_type_norm not in type_map:
        raise ValueError(
            f"click_type 必須是 'single' / 'double' / 'right'，但收到：{click_type!r}"
        )
    type_label, click_func = type_map[click_type_norm]

    # --------------------------------------------------------
    # (D) 取出中心座標、執行移動與點擊
    # --------------------------------------------------------
    x, y = mapping_table[target_id_int]
    print(f"[準備{type_label}] 編號 {target_id_int} → 座標 ({x}, {y})")

    # 先平順地移動滑鼠 (duration=0.5 讓你看得到軌跡)
    pyautogui.moveTo(x, y, duration=0.5)

    if dry_run:
        print(f"[DRY-RUN] 略過實際{type_label}()，滑鼠僅停留在 ({x}, {y})。")
    else:
        click_func()
        print(f"[完成] 已在 ({x}, {y}) 執行{type_label}。")

    return (x, y)


# ============================================================
# 函數 7b：模擬鍵盤輸入文字 (含 Unicode/中文支援)
# ============================================================
def execute_type(text: str, dry_run: bool = False, interval: float = 0.02) -> None:
    """
    模擬鍵盤輸入文字。

    策略：
    - 若全部為 ASCII，使用 pyautogui.typewrite() (較快、較穩定)
    - 若含 Unicode (中文/日文/Emoji/特殊符號)，改用「剪貼簿貼上」策略：
        pyperclip.copy() → pyautogui.hotkey('ctrl', 'v')
      (因為 pyautogui.typewrite() / write() 對 Unicode 支援不佳)

    參數：
        text:     要輸入的字串
        dry_run:  若為 True，僅印出預計輸入的內容，不實際操作
        interval: 每個字元之間的延遲 (秒)，預設 0.02 (僅 ASCII 模式生效)
    """
    if not text:
        print("[警告] execute_type 收到空字串，略過。")
        return

    if dry_run:
        preview = text if len(text) <= 60 else text[:57] + "..."
        print(f"[DRY-RUN] 略過實際輸入，預計輸入：{preview!r}")
        return

    # 判斷是否全 ASCII
    is_ascii = all(ord(c) < 128 for c in text)

    if is_ascii:
        print(f"[鍵盤輸入] 使用 typewrite() 輸入 {len(text)} 個 ASCII 字元...")
        pyautogui.typewrite(text, interval=interval)
    else:
        if not _PYPERCLIP_AVAILABLE:
            raise RuntimeError(
                "pyperclip 套件未安裝，無法輸入 Unicode (含中文)。\n"
                "請先執行：pip install pyperclip"
            )
        print(f"[鍵盤輸入] 使用剪貼簿貼上策略 (含 Unicode，{len(text)} 字元)...")
        pyperclip.copy(text)
        # 等剪貼簿更新完再貼上 (否則可能貼到舊內容)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        # 等待貼上動作完成
        time.sleep(0.05)

    preview = text if len(text) <= 60 else text[:57] + "..."
    print(f"[完成] 已輸入：{preview!r}")


# ============================================================
# 函數 7c：執行鍵盤熱鍵組合 (例如 ctrl+c、alt+F4、win+d)
# ============================================================
def execute_hotkey(keys_str: str, dry_run: bool = False) -> None:
    """
    解析熱鍵字串並執行按鍵組合。

    支援的格式：
        "ctrl+c"              → ['ctrl', 'c']
        "Ctrl + Shift + Esc"  → ['ctrl', 'shift', 'esc']  (容忍空白與大小寫)
        "alt+f4"              → ['alt', 'f4']
        "win+d"               → ['win', 'd']
        "enter"               → ['enter']
        "F5"                  → ['f5']

    修飾鍵與功能鍵的別名可參考本檔案全域常數 HOTKEY_ALIAS。

    參數：
        keys_str: 熱鍵字串 (用 '+' 連接多個按鍵)
        dry_run:  若為 True，僅印出預計按下的組合，不實際操作

    例外：
        ValueError: 熱鍵字串為空、或拆解後沒有任何有效按鍵
    """
    if not keys_str or not keys_str.strip():
        raise ValueError("hotkey 必須是非空字串，例如 'ctrl+c' 或 'alt+F4'")

    if dry_run:
        print(f"[DRY-RUN] 略過實際熱鍵，預計按下：{keys_str!r}")
        return

    # 拆解：用 '+' 切，每段去空白，再轉小寫
    raw_parts = [p.strip().lower() for p in keys_str.split("+") if p.strip()]

    if not raw_parts:
        raise ValueError(f"hotkey 拆解後沒有任何按鍵：{keys_str!r}")

    # 用別名表標準化 (找不到別名就保留原樣，pyautogui 支援單一字元如 a/b/c/1/2)
    normalized: List[str] = []
    for part in raw_parts:
        if part in HOTKEY_ALIAS:
            normalized.append(HOTKEY_ALIAS[part])
        else:
            normalized.append(part)

    print(f"[熱鍵] 執行：{' + '.join(normalized)}")
    pyautogui.hotkey(*normalized)
    print(f"[完成] 已按下熱鍵：{' + '.join(normalized)}")


# ============================================================
# 函數 7e：模擬滑鼠滾輪 (捲動畫面)
# ============================================================
def execute_scroll(
    direction: str = "down",
    clicks: int = SCROLL_DEFAULT_CLICKS,
    target_pos: Optional[Tuple[int, int]] = None,
    dry_run: bool = False,
) -> None:
    """
    模擬滑鼠滾輪捲動畫面。

    參數：
        direction:  "up" / "down" / "left" / "right"
        clicks:     滾輪格數 (1 click ≈ 120 內部單位)，預設 SCROLL_DEFAULT_CLICKS
        target_pos: (x, y) 若提供則先將滑鼠移到該位置再捲動；None=在目前位置捲動
        dry_run:    預演模式

    例外：
        ValueError: direction 非法 或 clicks <= 0
    """
    direction_norm = str(direction).lower().strip()
    if direction_norm not in ("up", "down", "left", "right"):
        raise ValueError(
            f"direction 必須是 up/down/left/right，收到 {direction!r}"
        )

    clicks_int = int(clicks)
    if clicks_int <= 0:
        raise ValueError(f"clicks 必須是正整數，收到 {clicks!r}")
    if clicks_int > SCROLL_MAX_CLICKS:
        print(f"[警告] clicks={clicks_int} 超過 {SCROLL_MAX_CLICKS}，已自動限制。")
        clicks_int = SCROLL_MAX_CLICKS

    # pyautogui.scroll()：正=up, 負=down；hscroll()：正=right, 負=left
    if direction_norm in ("up", "down"):
        amount = clicks_int if direction_norm == "up" else -clicks_int
    else:  # left / right
        amount = clicks_int if direction_norm == "right" else -clicks_int

    if dry_run:
        if target_pos:
            print(
                f"[DRY-RUN] 略過實際捲動，預計在 {target_pos} 處捲動 "
                f"{direction_norm} {clicks_int} 格 (amount={amount})"
            )
        else:
            print(
                f"[DRY-RUN] 略過實際捲動，預計在目前滑鼠位置捲動 "
                f"{direction_norm} {clicks_int} 格 (amount={amount})"
            )
        return

    # 先把滑鼠移到目標位置 (若有指定)
    if target_pos is not None:
        x, y = target_pos
        pyautogui.moveTo(x, y, duration=0.3)
        print(f"[捲動] 先將滑鼠移至 ({x}, {y})")

    print(
        f"[捲動] direction={direction_norm}, clicks={clicks_int}, "
        f"amount={amount}"
    )

    if direction_norm in ("up", "down"):
        pyautogui.scroll(amount)
    else:
        pyautogui.hscroll(amount)

    # 給系統一點時間反應捲動結果
    time.sleep(0.2)
    print(f"[完成] 已捲動 {direction_norm} {clicks_int} 格")


# ============================================================
# 函數 7f：滑鼠拖曳 (Drag & Drop)
# ============================================================
def execute_drag(
    from_pos: Tuple[int, int],
    to_pos: Tuple[int, int],
    duration: float = DRAG_DEFAULT_DURATION,
    dry_run: bool = False,
) -> None:
    """
    從 from_pos 拖曳到 to_pos (按住左鍵不放 → 移動 → 放開)。

    實作：pyautogui.moveTo(from) → mouseDown() → moveTo(to, duration) → mouseUp()

    參數：
        from_pos: (x, y) 拖曳起點
        to_pos:   (x, y) 拖曳終點
        duration: 拖曳過程秒數 (預設 0.5s，給你看得到軌跡)
        dry_run:  預演模式
    """
    fx, fy = from_pos
    tx, ty = to_pos

    if dry_run:
        print(
            f"[DRY-RUN] 略過實際拖曳，預計從 ({fx}, {fy}) 拖到 ({tx}, {ty})，"
            f"duration={duration}s"
        )
        return

    print(f"[拖曳] 從 ({fx}, {fy}) 到 ({tx}, {ty})，duration={duration}s")
    pyautogui.moveTo(fx, fy, duration=0.3)
    pyautogui.mouseDown()
    try:
        pyautogui.moveTo(tx, ty, duration=duration)
    finally:
        # 無論中間是否出例外，都要放開滑鼠鍵 (避免卡住)
        pyautogui.mouseUp()
    print(f"[完成] 拖曳完成 ({fx}, {fy}) → ({tx}, {ty})")


# ============================================================
# 函數 7d：動作分派器 (依 action 欄位分派到對應執行器)
# ============================================================
def execute_action(
    action_dict: Dict[str, Any],
    coord_map: Dict[int, Tuple[int, int]],
    dry_run: bool = False,
    grid_map: Optional[Dict[str, Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    """
    動作分派器：依 action_dict["action"] 欄位分派到對應的執行器。

    支援的 action 與必要欄位：
        - click         → 必要: target_id 或 grid_id (二選一)
        - double_click  → 必要: target_id 或 grid_id
        - right_click   → 必要: target_id 或 grid_id
        - type          → 必要: text
        - hotkey        → 必要: keys
        - scroll        → 必要: direction ("up"/"down"/"left"/"right") + clicks (預設 3)
        - drag          → 必要: (start_id, end_id) 或 (start_grid_id, end_grid_id)
        - NOT_FOUND     → 不執行，回傳特殊狀態

    參數：
        action_dict:  ask_vision_model() 回傳的動作字典
        coord_map:    編號 → 中心座標的對應表 (UIA 模式)
        dry_run:      若為 True，所有執行器都只預演不實際操作
        grid_map:     grid_id → 中心座標的對應表 (Grid Fallback 模式，可選)

    回傳：
        dict: {
            "status":   "ok" (成功) | "not_found" (AI 表示找不到) | "error" (執行失敗),
            "action":   執行的 action 名稱,
            "message":  人類可讀的執行結果訊息,
            "coord":    (x, y) 若為點擊/拖曳類動作才回傳，否則 None,
        }
    """
    action = str(action_dict.get("action", "")).strip()
    reason = str(action_dict.get("reason", "")).strip()
    if reason:
        print(f"[AI 判斷理由] {reason}")

    # grid_map 為 None 時用空 dict，避免後面 NoneType 錯誤
    grid_map = grid_map if grid_map is not None else {}

    try:
        # --------------------------------------------------------
        # NOT_FOUND：AI 表示畫面上沒有可完成任務的元素
        # --------------------------------------------------------
        if action == "NOT_FOUND":
            msg = reason or "模型表示找不到可完成任務的元素"
            print(f"[NOT_FOUND] {msg}")
            return {
                "status": "not_found",
                "action": "NOT_FOUND",
                "message": msg,
                "coord": None,
            }

        # --------------------------------------------------------
        # 點擊類動作 (click / double_click / right_click)
        # 支援兩種座標來源：target_id (UIA 編號) 或 grid_id (網格座標)
        # --------------------------------------------------------
        elif action in ("click", "double_click", "right_click"):
            target_id = action_dict.get("target_id")
            grid_id = action_dict.get("grid_id")
            if target_id is None and grid_id is None:
                raise ValueError(f"{action} 動作缺少 target_id 或 grid_id 欄位")

            # 對應 pyautogui 函式的 click_type 名稱
            ct_map = {
                "click": "single",
                "double_click": "double",
                "right_click": "right",
            }
            verb_map = {
                "click": "點擊",
                "double_click": "雙擊",
                "right_click": "右鍵",
            }

            if target_id is not None:
                # 走 UIA 編號路徑
                x, y = execute_click(
                    target_id, coord_map, dry_run=dry_run, click_type=ct_map[action]
                )
            else:
                # 走 Grid Fallback 路徑：解析 grid_id → 座標 → 直接點擊
                if not grid_map:
                    raise ValueError("此動作帶有 grid_id，但未提供 grid_map")
                gx, gy = resolve_grid_id(grid_id, grid_map)
                print(
                    f"[Grid] {action} 對應格子 {grid_id!r} → 中心座標 ({gx}, {gy})"
                )
                pyautogui.moveTo(gx, gy, duration=0.5)
                if not dry_run:
                    if ct_map[action] == "single":
                        pyautogui.click()
                    elif ct_map[action] == "double":
                        pyautogui.doubleClick()
                    elif ct_map[action] == "right":
                        pyautogui.rightClick()
                x, y = gx, gy

            return {
                "status": "ok",
                "action": action,
                "message": f"已在座標 ({x}, {y}) 執行{verb_map[action]}",
                "coord": (x, y),
            }

        # --------------------------------------------------------
        # 鍵盤輸入文字
        # --------------------------------------------------------
        elif action == "type":
            text = action_dict.get("text", "")
            if not text:
                raise ValueError("type 動作缺少 text 欄位或 text 為空")
            execute_type(text, dry_run=dry_run)
            preview = text if len(text) <= 40 else text[:37] + "..."
            return {
                "status": "ok",
                "action": "type",
                "message": f"已輸入 {len(text)} 字元：{preview!r}",
                "coord": None,
            }

        # --------------------------------------------------------
        # 熱鍵組合
        # --------------------------------------------------------
        elif action == "hotkey":
            keys = action_dict.get("keys", "")
            if not keys:
                raise ValueError("hotkey 動作缺少 keys 欄位或 keys 為空")
            execute_hotkey(keys, dry_run=dry_run)
            return {
                "status": "ok",
                "action": "hotkey",
                "message": f"已按下熱鍵：{keys}",
                "coord": None,
            }

        # --------------------------------------------------------
        # 捲動畫面 (scroll)
        # 支援兩種捲動位置：target_id (UIA 元素中心) 或 grid_id (網格中心)
        # --------------------------------------------------------
        elif action == "scroll":
            direction = action_dict.get("direction", "down")
            clicks = action_dict.get("clicks", SCROLL_DEFAULT_CLICKS)
            target_id = action_dict.get("target_id")
            grid_id = action_dict.get("grid_id")

            target_pos: Optional[Tuple[int, int]] = None
            if target_id is not None and target_id in coord_map:
                target_pos = coord_map[target_id]
            elif grid_id is not None and grid_map:
                target_pos = resolve_grid_id(grid_id, grid_map)

            execute_scroll(
                direction=direction,
                clicks=clicks,
                target_pos=target_pos,
                dry_run=dry_run,
            )
            return {
                "status": "ok",
                "action": "scroll",
                "message": f"已捲動 {direction} {clicks} 格 (target={target_pos})",
                "coord": target_pos,
            }

        # --------------------------------------------------------
        # 拖曳 (drag)
        # 支援兩種座標來源：start_id/end_id (UIA 編號) 或 start_grid_id/end_grid_id
        # --------------------------------------------------------
        elif action == "drag":
            start_id = action_dict.get("start_id")
            end_id = action_dict.get("end_id")
            start_grid_id = action_dict.get("start_grid_id")
            end_grid_id = action_dict.get("end_grid_id")

            from_pos: Optional[Tuple[int, int]] = None
            to_pos: Optional[Tuple[int, int]] = None

            if start_id is not None and end_id is not None:
                # UIA 編號路徑
                if start_id not in coord_map:
                    raise ValueError(f"start_id {start_id} 不在 coord_map 中")
                if end_id not in coord_map:
                    raise ValueError(f"end_id {end_id} 不在 coord_map 中")
                from_pos = coord_map[start_id]
                to_pos = coord_map[end_id]
            elif start_grid_id is not None and end_grid_id is not None:
                # 網格路徑
                if not grid_map:
                    raise ValueError("此 drag 動作帶有 grid_id，但未提供 grid_map")
                from_pos = resolve_grid_id(start_grid_id, grid_map)
                to_pos = resolve_grid_id(end_grid_id, grid_map)
            else:
                raise ValueError(
                    "drag 需要 (start_id, end_id) 或 (start_grid_id, end_grid_id) 其中一組"
                )

            execute_drag(from_pos, to_pos, dry_run=dry_run)
            return {
                "status": "ok",
                "action": "drag",
                "message": f"已從 {from_pos} 拖曳到 {to_pos}",
                "coord": to_pos,
            }

        else:
            raise ValueError(
                f"不支援的 action：{action!r}。"
                f"支援的動作：{sorted(SUPPORTED_ACTIONS)}"
            )

    except Exception as exc:
        return {
            "status": "error",
            "action": action or "<unknown>",
            "message": f"執行失敗：{exc}",
            "coord": None,
        }


# ============================================================
# 命令列參數解析
# ============================================================
def parse_cli_args() -> argparse.Namespace:
    """解析命令列參數，回傳 argparse.Namespace。"""
    parser = argparse.ArgumentParser(
        prog="wcmd-cli",
        description=(
            "WCMD：透過 Vision Model + Set-of-Mark 標記，"
            "自動點擊 Windows UI 元素。"
        ),
    )
    parser.add_argument(
        "instruction",
        nargs="?",
        default=None,
        help="要執行的 UI 操作意圖 (例如：'點擊確定按鈕')。未提供時進入互動輸入。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只移動滑鼠到目標位置，不實際點擊 (建議首次測試使用)。",
    )
    parser.add_argument(
        "--no-save-map",
        action="store_true",
        help="不要將座標表存成 JSON (預設會存到 coord_map.json)。",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="不要在開始前等待按 Enter (供 child_process 呼叫時使用)。",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="覆寫 API Key (也可設環境變數 WCMD_VISION_API_KEY 或 VISION_API_KEY)。",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="覆寫 API Base URL (預設為 OpenCode Go: https://opencode.ai/zen/go，Anthropic SDK 會自動補 /v1/messages)。",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆寫模型名稱 (也可設環境變數 WCMD_VISION_MODEL 或 VISION_MODEL)。",
    )
    parser.add_argument(
        "--force-grid",
        action="store_true",
        help="強制走「純視覺網格模式」(略過 UIA 抓元素，直接在截圖上疊加網格給 AI 看)。",
    )
    parser.add_argument(
        "--grid-rows",
        type=int,
        default=GRID_DEFAULT_ROWS,
        help=f"網格的列數 (預設 {GRID_DEFAULT_ROWS}，範圍 {GRID_MIN_SIZE}~{GRID_MAX_SIZE})。",
    )
    parser.add_argument(
        "--grid-cols",
        type=int,
        default=GRID_DEFAULT_COLS,
        help=f"網格的欄數 (預設 {GRID_DEFAULT_COLS}，範圍 {GRID_MIN_SIZE}~{GRID_MAX_SIZE})。",
    )
    return parser.parse_args()


# ============================================================
# 主程式進入點 (本機測試 / child_process 呼叫)
# ============================================================
# 退出碼約定 (供 Phase 3 的 VS Code Extension 或 Agent 判斷執行結果)：
#   0 = 動作成功執行
#   1 = 參數 / 環境錯誤
#   2 = AI 表示 NOT_FOUND (找不到可完成任務的元素)
#   3 = 動作執行失敗 (例如 target_id 不在 coord_map)
#   4 = Vision Model 階段失敗 (API 錯誤 / 解析失敗)
EXIT_OK = 0
EXIT_USAGE_ERROR = 1
EXIT_NOT_FOUND = 2
EXEC_ERROR = 3
EXIT_VISION_ERROR = 4


def main() -> None:
    """主流程：抓 UI → 標記截圖 → 問 AI → 分派並執行動作 (Phase 2.7)。
    支援 Grid Fallback：UIA 抓不到元素 (空陣列) 時自動改用網格模式。
    """
    global API_KEY, BASE_URL, MODEL_NAME  # 允許 CLI 參數覆寫

    args = parse_cli_args()

    # CLI 參數覆寫全域設定
    if args.api_key:
        API_KEY = args.api_key
    if args.base_url:
        BASE_URL = args.base_url
    if args.model:
        MODEL_NAME = args.model

    # 取得使用者意圖 (沒帶參數就互動輸入)
    instruction = args.instruction
    if not instruction:
        try:
            instruction = input("\n>>> 請輸入你想執行的 UI 操作意圖：").strip()
        except EOFError:
            instruction = ""
    if not instruction:
        print("[錯誤] 必須提供使用者意圖。")
        print("       用法：python agent_engine.py \"點擊確定按鈕\"")
        sys.exit(EXIT_USAGE_ERROR)

    # 整理 grid 設定 (邊界保護)
    grid_rows = max(GRID_MIN_SIZE, min(GRID_MAX_SIZE, args.grid_rows))
    grid_cols = max(GRID_MIN_SIZE, min(GRID_MAX_SIZE, args.grid_cols))

    # --------------------------------------------------------
    # 印出本次執行設定
    # --------------------------------------------------------
    print("=" * 64)
    print(" WinControl MCP Driver - 階段 2.7：Action Space + Grid Fallback")
    print("=" * 64)
    print(f" DPI 感知設定：{'成功' if _dpi_set_ok else '失敗'}")
    print(f" 螢幕解析度   ：{pyautogui.size()}")
    print(f" Vision Model：{MODEL_NAME}")
    print(f" Base URL    ：{BASE_URL}")
    has_key = bool(API_KEY or os.environ.get("VISION_API_KEY", ""))
    print(f" API Key 已設定：{'是' if has_key else '否'}")
    print(f" 支援的動作  ：{sorted(SUPPORTED_ACTIONS)}")
    print(f" 使用者意圖  ：{instruction}")
    print(f" 執行模式    ：{'DRY-RUN (不操作)' if args.dry_run else '正式操作'}")
    print(f" 強制網格模式：{'是' if args.force_grid else '否'}")
    print(f" 網格設定    ：{grid_rows}×{grid_cols} (僅 grid 模式生效)")

    # 等使用者把目標視窗切到前景
    if not args.no_wait:
        input("\n>>> 請切換到目標應用程式視窗，按 Enter 繼續...")

    # --------------------------------------------------------
    # 步驟 1/4：決定走 UIA 模式還是 Grid Fallback 模式
    # --------------------------------------------------------
    use_grid_mode = bool(args.force_grid)
    elements: List[Dict[str, Any]] = []
    coord_map: Dict[int, Tuple[int, int]] = {}
    grid_map: Dict[str, Tuple[int, int]] = {}

    if use_grid_mode:
        # 強制走網格模式
        print("\n[步驟 1/4] ⚠️  強制走純視覺網格模式 (略過 UIA 抓元素)")
    else:
        print("\n[步驟 1/4] 抓取可點擊 UI 元素中 (UIA 模式)...")
        elements = get_clickable_elements()
        print(f"            共找到 {len(elements)} 個元素。")
        if not elements:
            # ★ Grid Fallback 觸發點
            print("            ⚠️  沒有抓到任何可點擊元素，自動降級為「純視覺網格模式」！")
            print("               (適用於 Electron 客製化介面、遊戲、WebGL 渲染等 UIA 無法解析的環境)")
            use_grid_mode = True

    # 顯示前 5 個元素 (UIA 模式)
    if elements and not use_grid_mode:
        for elem in elements[:5]:
            print(
                f"   [{elem['id']:>3}] {elem['control_type']:<20} "
                f"name='{elem['name'][:18]}' center={elem['center']}"
            )
        if len(elements) > 5:
            print(f"   ... (略過 {len(elements) - 5} 個)")

    # --------------------------------------------------------
    # 步驟 2/4：產生標記截圖 (UIA 模式) 或 網格截圖 (Grid 模式)
    # --------------------------------------------------------
    if use_grid_mode:
        print(f"\n[步驟 2/4] 產生 {grid_rows}×{grid_cols} 網格截圖 (Grid Fallback)...")
        grid_image, grid_map = generate_grid_screenshot(rows=grid_rows, cols=grid_cols)
        grid_path = OUTPUT_IMAGE_PATH
        grid_image.save(grid_path)
        print(f"[完成] 網格截圖已儲存至：{os.path.abspath(grid_path)}")
        # 存一份 grid_map 為 JSON 供 Phase 3 Extension 讀取
        if not args.no_save_map:
            grid_map_path = COORD_MAP_PATH.replace(".json", "_grid.json")
            serializable = {k: [int(v[0]), int(v[1])] for k, v in grid_map.items()}
            with open(grid_map_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
            print(f"[完成] 網格座標表已儲存至：{os.path.abspath(grid_map_path)}")
    else:
        print("\n[步驟 2/4] 產生標記截圖中 (UIA 模式)...")
        coord_map = generate_marked_screenshot(elements)
        # 額外存一份 JSON 供 Phase 3 的 VS Code Extension 讀取
        if not args.no_save_map:
            save_coord_map(coord_map)

    # --------------------------------------------------------
    # 步驟 3/4：呼叫 Vision Model 判斷「動作 JSON」
    # --------------------------------------------------------
    print("\n[步驟 3/4] 呼叫 Vision Model 判斷動作...")
    try:
        if use_grid_mode:
            action_dict = ask_vision_model_grid(
                OUTPUT_IMAGE_PATH, instruction, rows=grid_rows, cols=grid_cols
            )
        else:
            # 將 elements 一起傳入，啟用「文字清單輔助」優化
            action_dict = ask_vision_model(OUTPUT_IMAGE_PATH, instruction, elements)
    except Exception as exc:
        print(f"[錯誤] Vision Model 階段失敗：{exc}")
        sys.exit(EXIT_VISION_ERROR)

    if not action_dict:
        print("[錯誤] Vision Model 沒有回傳有效動作字典，請檢查 Prompt 或 API 設定。")
        sys.exit(EXIT_VISION_ERROR)

    # --------------------------------------------------------
    # 步驟 4/4：分派並執行動作
    # --------------------------------------------------------
    print("\n[步驟 4/4] 分派並執行動作中...")
    result = execute_action(
        action_dict,
        coord_map,
        dry_run=args.dry_run,
        grid_map=grid_map,
    )

    # 印出結構化結果 (給 Extension 抓 stdout 用)
    print("\n[執行結果]")
    print(f"  status : {result['status']}")
    print(f"  action : {result['action']}")
    print(f"  message: {result['message']}")
    if result["coord"] is not None:
        print(f"  coord  : {result['coord']}")

    # 額外印出 JSON 格式的結果 (給 Phase 3 的 Extension / Agent 用)
    result_json = json.dumps(result, ensure_ascii=False)
    print(f"\n===RESULT===\n{result_json}\n===END===")

    # 退出碼約定
    if result["status"] == "ok":
        print("\n[全部完成] WCMD 流程已成功執行。")
        sys.exit(EXIT_OK)
    elif result["status"] == "not_found":
        print("\n[結束] AI 表示畫面上找不到可完成任務的元素。")
        sys.exit(EXIT_NOT_FOUND)
    else:  # "error"
        print("\n[結束] 動作執行過程中發生錯誤。")
        sys.exit(EXEC_ERROR)


if __name__ == "__main__":
    main()
