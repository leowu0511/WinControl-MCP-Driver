# -*- coding: utf-8 -*-
"""Phase 2.6 整合測試 - execute_action dispatcher (mock coord_map + dry_run)"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wcmd import engine as e


# 假的 coord_map：3 個元素，座標故意挑不會真的點到東西的位置
COORD_MAP = {0: (10, 10), 1: (100, 100), 2: (200, 200)}


def expect_status(result, expected_status, msg):
    if result["status"] == expected_status:
        print(f"  [OK] {msg}: status={result['status']}")
    else:
        print(f"  [FAIL] {msg}")
        print(f"        expected status: {expected_status}")
        print(f"        actual status  : {result['status']}")
        print(f"        message        : {result['message']}")
        sys.exit(1)


print("=== 測試 A: execute_action - click ===")
r = e.execute_action(
    {"action": "click", "target_id": 1, "reason": "點 OK 按鈕"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "click 成功")
assert r["coord"] == (100, 100), f"coord 錯誤: {r['coord']}"

print("\n=== 測試 B: execute_action - double_click ===")
r = e.execute_action(
    {"action": "double_click", "target_id": 2},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "double_click 成功")

print("\n=== 測試 C: execute_action - right_click ===")
r = e.execute_action(
    {"action": "right_click", "target_id": 0},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "right_click 成功")

print("\n=== 測試 D: execute_action - type (ASCII) ===")
r = e.execute_action(
    {"action": "type", "text": "hello world", "reason": "打 hello"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "type ASCII 成功")
assert r["coord"] is None, "type 不應有 coord"

print("\n=== 測試 E: execute_action - type (Unicode 中文) ===")
r = e.execute_action(
    {"action": "type", "text": "你好世界，這是中文輸入測試"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "type Unicode 成功")

print("\n=== 測試 F: execute_action - hotkey ===")
r = e.execute_action(
    {"action": "hotkey", "keys": "ctrl+shift+esc"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "hotkey 成功")

print("\n=== 測試 G: execute_action - NOT_FOUND ===")
r = e.execute_action(
    {"action": "NOT_FOUND", "reason": "找不到搜尋框"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "not_found", "NOT_FOUND 回傳 not_found")
assert r["action"] == "NOT_FOUND", f"action 應為 NOT_FOUND: {r['action']}"

print("\n=== 測試 H: execute_action - 不存在的 target_id (應 error) ===")
r = e.execute_action(
    {"action": "click", "target_id": 999},
    COORD_MAP, dry_run=True,
)
expect_status(r, "error", "不存在 target_id → error")
assert "999" in r["message"], f"錯誤訊息應含 999: {r['message']}"

print("\n=== 測試 I: execute_action - click 缺 target_id (應 error) ===")
r = e.execute_action(
    {"action": "click"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "error", "缺 target_id → error")

print("\n=== 測試 J: execute_action - type 空字串 (應 error) ===")
r = e.execute_action(
    {"action": "type", "text": ""},
    COORD_MAP, dry_run=True,
)
expect_status(r, "error", "type 空字串 → error")

print("\n=== 測試 K: execute_action - hotkey 空字串 (應 error) ===")
r = e.execute_action(
    {"action": "hotkey", "keys": ""},
    COORD_MAP, dry_run=True,
)
expect_status(r, "error", "hotkey 空字串 → error")

print("\n=== 測試 L: 完整 click 流程 (DRY-RUN) ===")
# 模擬 ask_vision_model 回傳 click 動作 → 經 dispatcher → execute_click
action = {"action": "click", "target_id": 1, "reason": "點擊工作管理員的 X"}
result = e.execute_action(action, COORD_MAP, dry_run=True)
print(f"  status={result['status']}, action={result['action']}, msg={result['message']}, coord={result['coord']}")
assert result["status"] == "ok"
assert result["coord"] == (100, 100)

print("\nAll execute_action tests passed!")
