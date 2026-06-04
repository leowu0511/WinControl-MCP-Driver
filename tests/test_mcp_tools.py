# -*- coding: utf-8 -*-
"""Phase 3 MCP Server 測試 - 3 個工具的單元與整合測試"""
import sys
import os
import io
import contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wcmd import server as mcp_server
from wcmd import engine


def expect(actual, expected, msg):
    if actual == expected:
        print(f"  [OK] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        print(f"        expected: {expected!r}")
        print(f"        actual  : {actual!r}")
        sys.exit(1)


def reset():
    """重置 MCP server 全域狀態"""
    mcp_server._reset_state()


# ============================================================
# Tool 1: get_screen_state
# ============================================================
print("=== T1-1: get_screen_state (UIA 模式) ===")
reset()
orig_get = engine.get_clickable_elements
orig_gen = engine.generate_marked_screenshot
engine.get_clickable_elements = lambda: [
    {"id": 0, "control_type": "ButtonControl", "name": "確定", "window_name": "Test", "center": (100, 100), "bbox": (0, 0, 200, 50)},
    {"id": 1, "control_type": "ButtonControl", "name": "取消", "window_name": "Test", "center": (300, 100), "bbox": (200, 0, 400, 50)},
]
engine.generate_marked_screenshot = lambda e: {0: (100, 100), 1: (300, 100)}
try:
    r = mcp_server.get_screen_state()
    expect(r["mode"], "uia", "UIA 模式")
    expect(r["element_count"], 2, "抓到 2 個元素")
    expect("確定" in r["text_list"], True, "text_list 包含元素名稱")
    # ContextGuard: 不再回傳完整 coord_map，只回緊湊 ID 範圍字串
    expect(r["coord_map"], None, "coord_map 應為 None (ContextGuard 移除)")
    expect(r["available_ids"], "0~1", "available_ids = '0~1'")
    expect(r["available_grid_ids"], None, "UIA 模式 available_grid_ids 應為 None")
    expect(r["grid_map"], None, "UIA 模式 grid_map 應為 None")
    # ⚠️ ContextGuard R6: screenshot_base64 key 整個不存在 (不再有 include_screenshot 選項)
    expect("screenshot_base64" in r, False, "screenshot_base64 key 不應存在 (防 agent 收截圖)")
    # 檢查狀態快取 (座標還在內部)
    expect(mcp_server._state["mode"], "uia", "state.mode = uia")
    expect(len(mcp_server._state["coord_map"]), 2, "state.coord_map 保留 2 個座標")
    expect(mcp_server._state["coord_map"][0], (100, 100), "state.coord_map[0] = (100, 100)")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen


print("\n=== T1-2: get_screen_state (UIA 空 → mode=empty) ===")
reset()
orig_get = engine.get_clickable_elements
engine.get_clickable_elements = lambda: []
try:
    r = mcp_server.get_screen_state()
    expect(r["mode"], "empty", "UIA 空 → mode=empty")
    expect(r["element_count"], 0, "element_count=0")
    expect(r["coord_map"], None, "empty 時 coord_map=None")
    expect(r["available_ids"], None, "empty 時 available_ids=None")
    expect(mcp_server._state["mode"], "empty", "state 標記為 empty")
finally:
    engine.get_clickable_elements = orig_get


print("\n=== T1-3: get_screen_state (Grid 模式) ===")
reset()
orig_grid = engine.generate_grid_screenshot
engine.generate_grid_screenshot = lambda rows=10, cols=10: (
    __import__("PIL").Image.new("RGB", (1000, 800), "white"),
    {f"{engine.GRID_COL_LETTERS[c]}{r+1}": (c*100+50, r*80+40)
     for r in range(rows) for c in range(cols)}
)
try:
    r = mcp_server.get_screen_state(use_grid=True, grid_rows=5, grid_cols=8)
    expect(r["mode"], "grid", "Grid 模式")
    expect(r["element_count"], 40, "5*8=40 個格子")
    # ContextGuard: 不回傳 grid_map 座標表，只回緊湊 ID 範圍字串
    expect(r["grid_map"], None, "grid_map 應為 None (ContextGuard 移除)")
    expect(r["available_grid_ids"], "A1~H5", "available_grid_ids = 'A1~H5' (5 列 8 欄 = H)")
    expect(r["coord_map"], None, "Grid 模式 coord_map=None")
    expect(mcp_server._state["mode"], "grid", "state.mode=grid")
    expect(mcp_server._state["grid_map"]["E5"], (450, 360), "state.grid_map 保留座標")
finally:
    engine.generate_grid_screenshot = orig_grid


print("\n=== T1-4: get_screen_state (Grid 邊界保護) ===")
reset()
orig_grid = engine.generate_grid_screenshot
# 驗證 grid_rows/cols 會被限制在 [3, 20]
captured_rows_cols = {}
def mock_grid(rows=10, cols=10):
    captured_rows_cols["rows"] = rows
    captured_rows_cols["cols"] = cols
    return (None, {})
engine.generate_grid_screenshot = mock_grid
try:
    mcp_server.get_screen_state(use_grid=True, grid_rows=100, grid_cols=0)
    expect(captured_rows_cols["rows"], 20, "rows=100 被截到 20")
    expect(captured_rows_cols["cols"], 3, "cols=0 被放大到 3")
finally:
    engine.generate_grid_screenshot = orig_grid


print("\n=== T1-5: get_screen_state (絕不附截圖 — ContextGuard R6) ===")
reset()
orig_get = engine.get_clickable_elements
orig_gen = engine.generate_marked_screenshot
# 產生一張真的圖片
from PIL import Image
img = Image.new("RGB", (200, 200), "red")
img.save(engine.OUTPUT_IMAGE_PATH)
engine.get_clickable_elements = lambda: [
    {"id": 0, "control_type": "Button", "name": "X", "window_name": "W", "center": (10, 10), "bbox": (0, 0, 20, 20)}
]
engine.generate_marked_screenshot = lambda e: {0: (10, 10)}
try:
    r = mcp_server.get_screen_state()
    # ⚠️ 關鍵斷言: Tool 1 絕對不該回傳截圖 Base64 給 agent
    expect("screenshot_base64" in r, False, "screenshot_base64 key 不應存在 (防 context 爆炸)")
    expect("screenshot_format" in r, False, "screenshot_format key 不應存在 (防 context 爆炸)")
    expect(r.get("screenshot_path"), engine.OUTPUT_IMAGE_PATH, "screenshot_path 仍存在供除錯")
    expect(r["text_list"] is not None, True, "text_list 一定有 (純觀察工具)")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen


# ============================================================
# Tool 2: execute_exact_action
# ============================================================
print("\n=== T2-1: execute_exact_action (未先呼叫 get_screen_state) ===")
reset()
r = mcp_server.execute_exact_action(action="click", target_id=5)
expect(r["status"], "error", "未初始化時 → error")
expect("尚未呼叫 get_screen_state" in r["message"], True, "錯誤訊息含提示")


print("\n=== T2-2: execute_exact_action (UIA 模式 click) ===")
reset()
# 模擬已呼叫 get_screen_state
mcp_server._state["mode"] = "uia"
mcp_server._state["coord_map"] = {0: (10, 10), 1: (100, 100), 2: (200, 200)}
mcp_server._state["grid_map"] = {}
r = mcp_server.execute_exact_action(action="click", target_id=1, dry_run=True)
expect(r["status"], "ok", "click 成功")
expect(r.get("coord"), None, "coord 被移除 (ContextGuard，agent 不需像素座標)")


print("\n=== T2-3: execute_exact_action (UIA 模式 hotkey) ===")
r = mcp_server.execute_exact_action(action="hotkey", keys="ctrl+c", dry_run=True)
expect(r["status"], "ok", "hotkey 成功")


print("\n=== T2-4: execute_exact_action (Grid 模式 click) ===")
reset()
mcp_server._state["mode"] = "grid"
mcp_server._state["grid_map"] = {"A1": (50, 50), "B2": (150, 150), "C3": (250, 250)}
mcp_server._state["coord_map"] = {}
r = mcp_server.execute_exact_action(action="click", grid_id="B2", dry_run=True)
expect(r["status"], "ok", "grid click 成功")
expect(r.get("coord"), None, "coord 被移除 (ContextGuard)")


print("\n=== T2-5: execute_exact_action (UIA 模式但給 grid_id → 找不到) ===")
reset()
mcp_server._state["mode"] = "uia"
mcp_server._state["coord_map"] = {0: (10, 10)}
mcp_server._state["grid_map"] = {}
r = mcp_server.execute_exact_action(action="click", grid_id="C5", dry_run=True)
# grid_id 不會被用，因為 state 是 uia → target_id 缺 → 報錯
expect(r["status"], "error", "UIA 模式但給 grid_id → error")


print("\n=== T2-6: execute_exact_action (scroll) ===")
reset()
mcp_server._state["mode"] = "uia"
mcp_server._state["coord_map"] = {0: (10, 10)}
r = mcp_server.execute_exact_action(
    action="scroll", direction="down", clicks=5, dry_run=True
)
expect(r["status"], "ok", "scroll 成功")


print("\n=== T2-7: execute_exact_action (drag UIA 模式) ===")
reset()
mcp_server._state["mode"] = "uia"
mcp_server._state["coord_map"] = {0: (10, 10), 5: (500, 500)}
r = mcp_server.execute_exact_action(
    action="drag", start_id=0, end_id=5, dry_run=True
)
expect(r["status"], "ok", "drag 成功")
expect(r.get("coord"), None, "drag coord 被移除 (ContextGuard)")


print("\n=== T2-8: execute_exact_action (type Unicode 中文) ===")
reset()
mcp_server._state["mode"] = "uia"
mcp_server._state["coord_map"] = {}
r = mcp_server.execute_exact_action(
    action="type", text="你好世界", dry_run=True
)
expect(r["status"], "ok", "type 中文成功")


print("\n=== T2-9: execute_exact_action (status=empty 模式) ===")
reset()
mcp_server._state["mode"] = "empty"
r = mcp_server.execute_exact_action(action="click", target_id=0)
expect(r["status"], "error", "empty 模式 → error")


# ============================================================
# Tool 3: execute_semantic_intent
# ============================================================
print("\n=== T3-1: execute_semantic_intent (UIA 模式 + 假 Qwen 回 click) ===")
reset()
orig_get = engine.get_clickable_elements
orig_gen = engine.generate_marked_screenshot
orig_ask = engine.ask_vision_model
orig_ask_grid = engine.ask_vision_model_grid

engine.get_clickable_elements = lambda: [
    {"id": 0, "control_type": "Button", "name": "X", "window_name": "W", "center": (10, 10), "bbox": (0, 0, 20, 20)}
]
engine.generate_marked_screenshot = lambda e: {0: (100, 100)}
engine.ask_vision_model = lambda img, instr, els: {"action": "click", "target_id": 0, "reason": "點 X"}
# 設假 API Key 讓 server 的 API Key 檢查通過 (T3 才會繼續到 mock 的 ask_vision_model)
from wcmd import config as wcmd_config
saved_api_key = wcmd_config.VISION_API_KEY
wcmd_config.VISION_API_KEY = "fake-key-for-test"
try:
    r = mcp_server.execute_semantic_intent("點 X 按鈕", dry_run=True)
    expect(r["status"], "ok", "全自動 click 成功")
    expect(r["action"], "click", "action=click")
    expect(r["ai_reason"], "點 X", "ai_reason 保留")
    expect(r["mode_used"], "uia", "記錄使用的模式")
    expect(mcp_server._state["mode"], "uia", "state 更新為 uia")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen
    engine.ask_vision_model = orig_ask
    engine.ask_vision_model_grid = orig_ask_grid
    wcmd_config.VISION_API_KEY = saved_api_key


print("\n=== T3-2: execute_semantic_intent (UIA 空 → 自動降級 Grid) ===")
reset()
orig_get = engine.get_clickable_elements
orig_grid = engine.generate_grid_screenshot
orig_ask_grid = engine.ask_vision_model_grid

# 預先建立真的空白 PIL Image
from PIL import Image as _PILImage
_fake_img = _PILImage.new("RGB", (1000, 800), "white")

engine.get_clickable_elements = lambda: []
engine.generate_grid_screenshot = lambda rows=10, cols=10: (
    _fake_img, {"A1": (50, 50), "B2": (150, 150)}
)
engine.ask_vision_model_grid = lambda img, instr, rows=10, cols=10: {
    "action": "click", "grid_id": "B2", "reason": "網格 B2"
}
# 設假 API Key (T3 才會繼續到 mock)
from wcmd import config as wcmd_config
saved_api_key_2 = wcmd_config.VISION_API_KEY
wcmd_config.VISION_API_KEY = "fake-key-for-test"
try:
    r = mcp_server.execute_semantic_intent("點中間", dry_run=True)
    expect(r["status"], "ok", "Grid 降級 click 成功")
    expect(r["action"], "click", "action=click")
    expect(r.get("coord"), None, "coord 被移除 (ContextGuard)")
    expect(r["mode_used"], "grid", "記錄使用 grid 模式")
    expect(mcp_server._state["mode"], "grid", "state 更新為 grid")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_grid_screenshot = orig_grid
    engine.ask_vision_model_grid = orig_ask_grid
    wcmd_config.VISION_API_KEY = saved_api_key_2


print("\n=== T3-3: execute_semantic_intent (force_grid=True) ===")
reset()
orig_get = engine.get_clickable_elements
orig_grid = engine.generate_grid_screenshot
orig_ask_grid = engine.ask_vision_model_grid

engine.get_clickable_elements = lambda: [{"id": 0, "control_type": "B", "name": "X", "window_name": "W", "center": (10, 10), "bbox": (0, 0, 20, 20)}]  # 有元素
engine.generate_grid_screenshot = lambda rows=10, cols=10: (_fake_img, {"A1": (50, 50)})
engine.ask_vision_model_grid = lambda img, instr, rows=10, cols=10: {
    "action": "click", "grid_id": "A1", "reason": "強制 grid"
}
# 設假 API Key (T3 才會繼續到 mock)
saved_api_key_3 = wcmd_config.VISION_API_KEY
wcmd_config.VISION_API_KEY = "fake-key-for-test"
try:
    r = mcp_server.execute_semantic_intent("點左上", dry_run=True, force_grid=True)
    expect(r["mode_used"], "grid", "force_grid 應走 grid")
    expect(r["status"], "ok", "成功")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_grid_screenshot = orig_grid
    engine.ask_vision_model_grid = orig_ask_grid
    wcmd_config.VISION_API_KEY = saved_api_key_3


print("\n=== T3-4: execute_semantic_intent (Vision Model 失敗) ===")
reset()
orig_get = engine.get_clickable_elements
orig_gen = engine.generate_marked_screenshot
orig_ask = engine.ask_vision_model

engine.get_clickable_elements = lambda: [{"id": 0, "control_type": "B", "name": "X", "window_name": "W", "center": (10, 10), "bbox": (0, 0, 20, 20)}]
engine.generate_marked_screenshot = lambda e: {0: (10, 10)}
engine.ask_vision_model = lambda *a, **kw: None  # 回傳 None
try:
    r = mcp_server.execute_semantic_intent("壞 prompt", dry_run=True)
    expect(r["status"], "error", "Vision 失敗 → error")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen
    engine.ask_vision_model = orig_ask


# ============================================================
# 整合測試：模擬 Agent 完整流程
# ============================================================
print("\n=== INT-1: 模擬 Agent 完整流程 (Tier 1 + Tier 2) ===")
print("   模擬：Agent 先 get_screen_state 觀察 → 決定 click target 5 → execute_exact_action")
reset()
orig_get = engine.get_clickable_elements
orig_gen = engine.generate_marked_screenshot

engine.get_clickable_elements = lambda: [
    {"id": i, "control_type": "Button", "name": f"Btn{i}", "window_name": "App", "center": (i*100, 100), "bbox": (i*100-50, 50, i*100+50, 150)}
    for i in range(10)
]
engine.generate_marked_screenshot = lambda e: {i: (i*100, 100) for i in range(10)}
try:
    # Step 1: 感知 (純文字模式 — R6 起不附截圖)
    state1 = mcp_server.get_screen_state()
    expect(state1["mode"], "uia", "感知 → UIA 模式")
    expect(state1["element_count"], 10, "抓到 10 個元素")
    # ⚠️ R6: screenshot_base64 key 整個不存在 (不再有 include_screenshot 選項)
    expect("screenshot_base64" in state1, False, "Tool 1 絕不附截圖 (ContextGuard R6)")
    expect(state1["text_list"] is not None, True, "text_list 一定有 (純觀察工具)")
    print(f"    (Agent 從 text_list 看到 {state1['element_count']} 個元素，截圖已從 schema 徹底移除)")

    # Step 2: Agent 根據 text_list 決定要按 Btn5 (target_id=5)
    result = mcp_server.execute_exact_action(
        action="click", target_id=5, dry_run=True
    )
    expect(result["status"], "ok", "點擊 Btn5 成功")
    expect(result.get("coord"), None, "coord 被移除 (ContextGuard)")
    print(f"    (Agent 決定 → click target 5 → 像素座標已在 MCP log，不進 context)")

    # Step 3: 然後按 Ctrl+S
    result2 = mcp_server.execute_exact_action(action="hotkey", keys="ctrl+s", dry_run=True)
    expect(result2["status"], "ok", "按 Ctrl+S 成功")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen


print("\n=== INT-2: 模擬 Vision-less Agent (只用 Tier 3) ===")
print("   模擬：小型 LLM Agent 沒有視覺，只能給文字意圖")
reset()
orig_get = engine.get_clickable_elements
orig_gen = engine.generate_marked_screenshot
orig_ask = engine.ask_vision_model

engine.get_clickable_elements = lambda: [{"id": 0, "control_type": "B", "name": "OK", "window_name": "D", "center": (100, 100), "bbox": (0, 0, 200, 200)}]
engine.generate_marked_screenshot = lambda e: {0: (100, 100)}
engine.ask_vision_model = lambda img, instr, els: {"action": "click", "target_id": 0, "reason": "OK 按鈕"}
# 設假 API Key (與 T3-1/T3-2/T3-3 一致，本機無 env 時也能跑)
saved_api_key_int2 = wcmd_config.VISION_API_KEY
wcmd_config.VISION_API_KEY = "fake-key-for-test"
try:
    r = mcp_server.execute_semantic_intent("按確定", dry_run=True)
    expect(r["status"], "ok", "Tier 3 成功")
    expect(r["ai_reason"], "OK 按鈕", "AI 判斷理由保留")
    print(f"    (Vision-less Agent 只給「按確定」→ 自動完成: {r['message']})")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen
    engine.ask_vision_model = orig_ask
    wcmd_config.VISION_API_KEY = saved_api_key_int2


# ============================================================
# 錯誤處理：例外不應 crash server
# ============================================================
print("\n=== ERR-1: 內部例外不應 crash server ===")
reset()
orig_get = engine.get_clickable_elements
engine.get_clickable_elements = lambda: (_ for _ in ()).throw(RuntimeError("模擬 UIA 爆炸"))
try:
    r = mcp_server.get_screen_state()
    expect(r.get("status"), "error", "UIA 爆炸時 → error 狀態")
    expect("失敗" in r.get("message", ""), True, "錯誤訊息含 '失敗'")
finally:
    engine.get_clickable_elements = orig_get


print("\nAll MCP Server tests passed!")


# ============================================================
# Part R7：Message 內容不可含像素座標 (ContextGuard)
# ============================================================
print("\n=== R7-1: click/scroll/drag message 不應含像素座標 ===")
reset()
orig_get = engine.get_clickable_elements
orig_gen = engine.generate_marked_screenshot
engine.get_clickable_elements = lambda: [
    {"id": 0, "control_type": "Button", "name": "OK", "window_name": "App", "center": (123, 456), "bbox": (100, 400, 150, 500)}
]
engine.generate_marked_screenshot = lambda e: {0: (123, 456)}
try:
    # 先掃描讓 state.coord_map 有資料
    mcp_server.get_screen_state()

    # click — 座標 123, 456 不應出現在 message
    r_click = mcp_server.execute_exact_action(action="click", target_id=0, dry_run=True)
    expect(r_click["status"], "ok", "click 成功")
    expect(
        "123" not in r_click.get("message", "") and "456" not in r_click.get("message", ""),
        True,
        f"click message 不含座標 (實際: {r_click.get('message')!r})"
    )
    print(f"    (click message: {r_click.get('message')!r})")

    # scroll — 座標不應出現在 message
    r_scroll = mcp_server.execute_exact_action(
        action="scroll", direction="down", clicks=3, dry_run=True
    )
    expect(
        "target=" not in r_scroll.get("message", ""),
        True,
        f"scroll message 不含 target= (實際: {r_scroll.get('message')!r})"
    )
    print(f"    (scroll message: {r_scroll.get('message')!r})")

    # drag (UIA→UIA 模式) — 起點/終點座標不應出現在 message
    r_drag = mcp_server.execute_exact_action(
        action="drag", start_id=0, end_id=0, dry_run=True
    )
    expect(r_drag["status"], "ok", "drag 成功")
    expect(
        "(" not in r_drag.get("message", "") or "拖曳" in r_drag.get("message", ""),
        True,
        f"drag message 不含座標 (實際: {r_drag.get('message')!r})"
    )
    print(f"    (drag message: {r_drag.get('message')!r})")

    # ⚠️ server.py 仍會 pop 掉 coord key (R4)
    expect(r_click.get("coord"), None, "click 結果的 coord key 仍被 pop (R4)")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen


print("\n=== R7-2: encode_image_to_base64 已改為私有 _encode_image_to_base64_raw ===")
expect(
    not hasattr(engine, "encode_image_to_base64"),
    True,
    "engine.encode_image_to_base64 不應存在 (R7 改為私有)"
)
expect(
    hasattr(engine, "_encode_image_to_base64_raw"),
    True,
    "engine._encode_image_to_base64_raw 應存在"
)


print("\nAll R7 ContextGuard tests passed!")
