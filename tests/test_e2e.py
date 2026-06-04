# -*- coding: utf-8 -*-
"""Phase 2.6 端到端測試 - main() 流程 (mock Vision Model + UIA + 螢幕)"""
import sys
import os
import io
import contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wcmd import engine as e


FAKE_COORD_MAP = {0: (10, 10), 1: (50, 50), 2: (100, 100)}


# 共用的 mock 函數
def mock_get_clickable_elements():
    return [
        {"id": 0, "control_type": "ButtonControl", "name": "處理程序", "window_name": "工作管理員", "center": (10, 10), "bbox": (0, 0, 20, 20)},
        {"id": 1, "control_type": "ButtonControl", "name": "",          "window_name": "工作管理員", "center": (50, 50), "bbox": (40, 40, 60, 60)},
        {"id": 2, "control_type": "ButtonControl", "name": "X",         "window_name": "PowerShell", "center": (100, 100), "bbox": (90, 90, 110, 110)},
    ]


def mock_generate_marked_screenshot(elements):
    return FAKE_COORD_MAP


def run_main(args_list, mock_action):
    """跑 main() 並回傳 (exit_code, stdout) - 自動 patch 掉所有副作用"""
    orig_argv = sys.argv
    orig_ask = e.ask_vision_model
    orig_get = e.get_clickable_elements
    orig_gen = e.generate_marked_screenshot
    orig_save = e.save_coord_map

    sys.argv = ["agent_engine.py"] + args_list
    e.ask_vision_model = lambda *a, **kw: mock_action
    e.get_clickable_elements = mock_get_clickable_elements
    e.generate_marked_screenshot = mock_generate_marked_screenshot
    e.save_coord_map = lambda m: None

    captured = io.StringIO()
    exit_code = 0
    try:
        with contextlib.redirect_stdout(captured):
            e.main()
    except SystemExit as exc:
        exit_code = exc.code if exc.code is not None else 0
    except Exception as exc:
        exit_code = 99
        print(f"[FATAL] main() raised: {type(exc).__name__}: {exc}")
    finally:
        sys.argv = orig_argv
        e.ask_vision_model = orig_ask
        e.get_clickable_elements = orig_get
        e.generate_marked_screenshot = orig_gen
        e.save_coord_map = orig_save

    return exit_code, captured.getvalue()


# ============================================================
# 測試案例
# ============================================================
print("=== M1: click 動作 (dry-run) → exit 0 ===")
ec, out = run_main(
    ["--dry-run", "--no-wait", "點擊工作管理員的 X"],
    {"action": "click", "target_id": 1, "reason": "點 X"},
)
print(f"  exit_code = {ec}")
assert ec == 0
assert '"status": "ok"' in out
assert '"action": "click"' in out
assert '"coord": [50, 50]' in out
print("  [OK]")


print("\n=== M2: NOT_FOUND 動作 → exit 2 ===")
ec, out = run_main(
    ["--dry-run", "--no-wait", "找不到的東西"],
    {"action": "NOT_FOUND", "reason": "找不到搜尋框"},
)
print(f"  exit_code = {ec}")
assert ec == 2
assert '"status": "not_found"' in out
print("  [OK]")


print("\n=== M3: type 動作 (dry-run) → exit 0 ===")
ec, out = run_main(
    ["--dry-run", "--no-wait", "輸入 hello"],
    {"action": "type", "text": "hello world", "reason": "打字"},
)
print(f"  exit_code = {ec}")
assert ec == 0
assert '"action": "type"' in out
assert "已輸入 11 字元" in out
print("  [OK]")


print("\n=== M4: hotkey 動作 (dry-run) → exit 0 ===")
ec, out = run_main(
    ["--dry-run", "--no-wait", "按 Ctrl+S"],
    {"action": "hotkey", "keys": "ctrl+s", "reason": "存檔"},
)
print(f"  exit_code = {ec}")
assert ec == 0
assert '"action": "hotkey"' in out
# dry-run 印出 'ctrl+s' (原樣)，實際執行會印出 'ctrl + s' (拆解後)
assert "ctrl+s" in out
print("  [OK]")


print("\n=== M5: 不存在的 target_id → exit 3 ===")
ec, out = run_main(
    ["--dry-run", "--no-wait", "點不存在的"],
    {"action": "click", "target_id": 999, "reason": "OOPS"},
)
print(f"  exit_code = {ec}")
assert ec == 3
assert "999" in out
assert '"status": "error"' in out
print("  [OK]")


print("\n=== M6: double_click 動作 (dry-run) → exit 0 ===")
ec, out = run_main(
    ["--dry-run", "--no-wait", "雙擊檔案"],
    {"action": "double_click", "target_id": 2, "reason": "開檔案"},
)
print(f"  exit_code = {ec}")
assert ec == 0
assert '"action": "double_click"' in out
print("  [OK]")


print("\n=== M7: right_click 動作 (dry-run) → exit 0 ===")
ec, out = run_main(
    ["--dry-run", "--no-wait", "右鍵選單"],
    {"action": "right_click", "target_id": 0, "reason": "開選單"},
)
print(f"  exit_code = {ec}")
assert ec == 0
assert '"action": "right_click"' in out
print("  [OK]")


print("\n=== M8: Vision Model 解析失敗 → exit 4 ===")
# ask_vision_model 回傳 None
orig_ask = e.ask_vision_model
orig_get = e.get_clickable_elements
orig_gen = e.generate_marked_screenshot
orig_save = e.save_coord_map
sys.argv = ["agent_engine.py", "--dry-run", "--no-wait", "壞 prompt"]
e.ask_vision_model = lambda *a, **kw: None
e.get_clickable_elements = mock_get_clickable_elements
e.generate_marked_screenshot = mock_generate_marked_screenshot
e.save_coord_map = lambda m: None
captured = io.StringIO()
try:
    with contextlib.redirect_stdout(captured):
        try:
            e.main()
        except SystemExit as exc:
            ec = exc.code if exc.code is not None else 0
finally:
    e.ask_vision_model = orig_ask
    e.get_clickable_elements = orig_get
    e.generate_marked_screenshot = orig_gen
    e.save_coord_map = orig_save
    sys.argv = ["agent_engine.py"]
print(f"  exit_code = {ec}")
assert ec == 4
print("  [OK]")


print("\nAll end-to-end main() tests passed!")
