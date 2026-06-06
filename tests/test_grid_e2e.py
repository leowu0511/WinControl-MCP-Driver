# -*- coding: utf-8 -*-
"""Phase 2.7 e2e 測試 - Grid Fallback 路徑 (UIA 為空時自動降級)"""
import sys
import os
import io
import contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wcmd import engine as e


# 記錄有沒有被呼叫
call_log = {"get_clickable_elements": 0, "ask_vision_model": 0, "ask_vision_model_grid": 0}


def mock_get_empty():
    """模擬 UIA 抓不到任何元素 (空陣列)"""
    call_log["get_clickable_elements"] += 1
    return []


def mock_get_with_elements():
    """模擬 UIA 抓得到元素 (3 個)"""
    call_log["get_clickable_elements"] += 1
    return [
        {"id": 0, "control_type": "ButtonControl", "name": "X", "window_name": "Test", "center": (10, 10), "bbox": (0, 0, 20, 20)},
    ]


def mock_ask_grid(*args, **kwargs):
    """模擬 grid 模式的 Vision Model 回傳"""
    call_log["ask_vision_model_grid"] += 1
    return {"action": "click", "grid_id": "C5", "reason": "grid 模式點 C5"}


def mock_ask_uia(*args, **kwargs):
    """模擬 UIA 模式的 Vision Model 回傳"""
    call_log["ask_vision_model"] += 1
    return {"action": "click", "target_id": 0, "reason": "UIA 模式點 0"}


def mock_generate_grid_screenshot(rows, cols):
    """模擬 grid screenshot 產生 (跳過實際截圖)"""
    from PIL import Image
    img = Image.new("RGB", (500, 500), "white")
    grid_map = {}
    for r in range(rows):
        for c in range(cols):
            label = f"{e.GRID_COL_LETTERS[c]}{r + 1}"
            grid_map[label] = (c * 50 + 25, r * 50 + 25)
    return img, grid_map


def mock_generate_marked_screenshot(elements):
    """模擬 UIA 標記截圖 (跳過實際繪製)"""
    return {0: (10, 10)}


def run_main_grid_fallback(args_list, get_fn, ask_grid_fn, ask_uia_fn):
    """跑 main() 並捕捉 stdout/exit_code"""
    orig_argv = sys.argv
    orig_get = e.get_clickable_elements
    orig_ask_grid = e.ask_vision_model_grid
    orig_ask_uia = e.ask_vision_model
    orig_gen_grid = e.generate_grid_screenshot
    orig_gen_marked = e.generate_marked_screenshot
    orig_save = e.save_coord_map

    sys.argv = ["agent_engine.py"] + args_list
    e.get_clickable_elements = get_fn
    e.ask_vision_model_grid = ask_grid_fn
    e.ask_vision_model = ask_uia_fn
    e.generate_grid_screenshot = mock_generate_grid_screenshot
    e.generate_marked_screenshot = mock_generate_marked_screenshot
    e.save_coord_map = lambda m: None

    # reset log
    call_log["get_clickable_elements"] = 0
    call_log["ask_vision_model"] = 0
    call_log["ask_vision_model_grid"] = 0

    captured = io.StringIO()
    exit_code = 0
    try:
        with contextlib.redirect_stdout(captured):
            e.main()
    except SystemExit as exc:
        exit_code = exc.code if exc.code is not None else 0
    except Exception as exc:
        exit_code = 99
        print(f"[FATAL] {type(exc).__name__}: {exc}")
    finally:
        sys.argv = orig_argv
        e.get_clickable_elements = orig_get
        e.ask_vision_model_grid = orig_ask_grid
        e.ask_vision_model = orig_ask_uia
        e.generate_grid_screenshot = orig_gen_grid
        e.generate_marked_screenshot = orig_gen_marked
        e.save_coord_map = orig_save

    return exit_code, captured.getvalue()


# ============================================================
print("=== G-E2E-1: UIA 空 → 自動降級 Grid 模式 → exit 0 ===")
ec, out = run_main_grid_fallback(
    ["--dry-run", "--no-wait", "點中間"],
    mock_get_empty, mock_ask_grid, mock_ask_uia,
)
print(f"  exit_code = {ec}")
print(f"  get_clickable_elements 呼叫次數 = {call_log['get_clickable_elements']}")
print(f"  ask_vision_model_grid 呼叫次數 = {call_log['ask_vision_model_grid']}")
print(f"  ask_vision_model 呼叫次數 = {call_log['ask_vision_model']}")
assert ec == 0, f"應為 0，收到 {ec}"
assert call_log["ask_vision_model_grid"] == 1, "應該走 grid 模式"
assert call_log["ask_vision_model"] == 0, "不該走 UIA 模式"
assert "降級為「純視覺網格模式」" in out, "應有降級訊息"
assert "grid_id" not in out or "C5" in out, "應有 grid_id C5"
print("  [OK]")


print("\n=== G-E2E-2: --force-grid 強制走 Grid 模式 (即使 UIA 有元素) ===")
ec, out = run_main_grid_fallback(
    ["--dry-run", "--no-wait", "--force-grid", "點中間"],
    mock_get_with_elements, mock_ask_grid, mock_ask_uia,
)
print(f"  exit_code = {ec}")
print(f"  ask_vision_model_grid 呼叫次數 = {call_log['ask_vision_model_grid']}")
print(f"  ask_vision_model 呼叫次數 = {call_log['ask_vision_model']}")
assert ec == 0
assert call_log["ask_vision_model_grid"] == 1, "強制 grid 模式應走 grid"
assert call_log["ask_vision_model"] == 0, "強制 grid 不該走 UIA"
assert "強制走純視覺網格模式" in out
print("  [OK]")


print("\n=== G-E2E-3: UIA 有元素 → 走 UIA 模式 (不降級) ===")
ec, out = run_main_grid_fallback(
    ["--dry-run", "--no-wait", "點 X"],
    mock_get_with_elements, mock_ask_grid, mock_ask_uia,
)
print(f"  exit_code = {ec}")
print(f"  ask_vision_model 呼叫次數 = {call_log['ask_vision_model']}")
print(f"  ask_vision_model_grid 呼叫次數 = {call_log['ask_vision_model_grid']}")
assert ec == 0
assert call_log["ask_vision_model"] == 1, "UIA 模式應走 UIA"
assert call_log["ask_vision_model_grid"] == 0, "UIA 模式不該走 grid"
assert "降級" not in out, "不該有降級訊息"
print("  [OK]")


print("\n=== G-E2E-4: Grid 模式 + 5x5 自訂網格 ===")
ec, out = run_main_grid_fallback(
    ["--dry-run", "--no-wait", "--force-grid", "--grid-rows", "5", "--grid-cols", "5", "點"],
    mock_get_empty, mock_ask_grid, mock_ask_uia,
)
print(f"  exit_code = {ec}")
assert ec == 0
assert "5×5" in out, "應印出 5×5 網格"
print("  [OK]")


print("\nAll Grid Fallback e2e tests passed!")
