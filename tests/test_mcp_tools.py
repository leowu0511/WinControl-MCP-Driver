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
    expect(r["screenshot_base64"], None, "未要求時 screenshot_base64 應為 None")
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


print("\n=== T1-5: get_screen_state (with screenshot) ===")
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
    r = mcp_server.get_screen_state(include_screenshot=True)
    expect(r["screenshot_base64"] is not None, True, "screenshot_base64 有值")
    # Base64 解碼後應該能讀回原圖
    import base64
    decoded = base64.b64decode(r["screenshot_base64"])
    expect(len(decoded) > 0, True, f"Base64 解碼後有 {len(decoded)} bytes")
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
expect(r["coord"], (100, 100), "coord = (100, 100)")


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
expect(r["coord"], (150, 150), "B2 座標")


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
expect(r["coord"], (500, 500), "end 座標")


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
try:
    r = mcp_server.execute_semantic_intent("點中間", dry_run=True)
    expect(r["status"], "ok", "Grid 降級 click 成功")
    expect(r["action"], "click", "action=click")
    expect(r["coord"], (150, 150), "B2 座標")
    expect(r["mode_used"], "grid", "記錄使用 grid 模式")
    expect(mcp_server._state["mode"], "grid", "state 更新為 grid")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_grid_screenshot = orig_grid
    engine.ask_vision_model_grid = orig_ask_grid


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
try:
    r = mcp_server.execute_semantic_intent("點左上", dry_run=True, force_grid=True)
    expect(r["mode_used"], "grid", "force_grid 應走 grid")
    expect(r["status"], "ok", "成功")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_grid_screenshot = orig_grid
    engine.ask_vision_model_grid = orig_ask_grid


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
    # Step 1: 感知
    # ContextGuard: include_screenshot=True 時 text_list 會被設為 None (避免重複)
    # 所以先不帶截圖取得 text_list，再帶截圖驗證截圖功能
    state1_noimg = mcp_server.get_screen_state(include_screenshot=False)
    expect(state1_noimg["mode"], "uia", "感知 → UIA 模式")
    expect(state1_noimg["element_count"], 10, "抓到 10 個元素")
    expect("Btn5" in state1_noimg["text_list"], True, "text_list 提到 Btn5")

    state1 = mcp_server.get_screen_state(include_screenshot=True)
    expect(state1["mode"], "uia", "感知 → UIA 模式 (含截圖)")
    expect(state1["element_count"], 10, "抓到 10 個元素 (含截圖)")
    expect(state1["text_list"], None, "含截圖時 text_list 應為 None (ContextGuard)")
    print(f"    (Agent 觀察到 {state1['element_count']} 個元素，截圖 {len(state1['screenshot_base64'])} chars)")

    # Step 2: Agent 根據 text_list 決定要按 Btn5 (target_id=5)
    result = mcp_server.execute_exact_action(
        action="click", target_id=5, dry_run=True
    )
    expect(result["status"], "ok", "點擊 Btn5 成功")
    expect(result["coord"], (500, 100), "Btn5 座標")
    print(f"    (Agent 決定 → click target 5 → 座標 {result['coord']})")

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
try:
    r = mcp_server.execute_semantic_intent("按確定", dry_run=True)
    expect(r["status"], "ok", "Tier 3 成功")
    expect(r["ai_reason"], "OK 按鈕", "AI 判斷理由保留")
    print(f"    (Vision-less Agent 只給「按確定」→ 自動完成: {r['message']})")
finally:
    engine.get_clickable_elements = orig_get
    engine.generate_marked_screenshot = orig_gen
    engine.ask_vision_model = orig_ask


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
