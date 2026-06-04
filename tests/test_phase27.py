# -*- coding: utf-8 -*-
"""Phase 2.7 新功能測試 - scroll / drag / grid fallback"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wcmd import engine as e


def expect(actual, expected, msg):
    if actual == expected:
        print(f"  [OK] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        print(f"        expected: {expected!r}")
        print(f"        actual  : {actual!r}")
        sys.exit(1)


def expect_status(result, expected_status, msg):
    if result["status"] == expected_status:
        print(f"  [OK] {msg}: status={result['status']}")
    else:
        print(f"  [FAIL] {msg}")
        print(f"        expected status: {expected_status}")
        print(f"        actual status  : {result['status']}")
        print(f"        message        : {result['message']}")
        sys.exit(1)


COORD_MAP = {0: (10, 10), 1: (50, 50), 2: (100, 100), 3: (200, 200)}
GRID_MAP = {
    "A1": (50, 50),   "A2": (50, 150),  "A3": (50, 250),
    "B1": (150, 50),  "B2": (150, 150), "B3": (150, 250),
    "C1": (250, 50),  "C2": (250, 150), "C3": (250, 250),
}


# ============================================================
# Scroll
# ============================================================
print("=== S1: execute_scroll (dry-run) ===")
e.execute_scroll("down", clicks=3, dry_run=True)
print("  [OK] (印出預計動作)")

print("\n=== S2: execute_scroll - 解析錯誤 direction ===")
try:
    e.execute_scroll("diagonal")
    print("  [FAIL] 應 raise")
    sys.exit(1)
except ValueError as ex:
    print(f"  [OK] raise: {ex}")

print("\n=== S3: execute_scroll - 負數 clicks ===")
try:
    e.execute_scroll("down", clicks=-3)
    print("  [FAIL] 應 raise")
    sys.exit(1)
except ValueError as ex:
    print(f"  [OK] raise: {ex}")

print("\n=== S4: execute_action - scroll 動作 (UIA 模式) ===")
r = e.execute_action(
    {"action": "scroll", "direction": "down", "clicks": 5, "reason": "往下捲"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "scroll (UIA, 無 target)")
assert r["coord"] is None, f"無 target 應 coord=None，收到 {r['coord']}"

print("\n=== S5: execute_action - scroll 帶 target_id ===")
r = e.execute_action(
    {"action": "scroll", "direction": "down", "clicks": 3, "target_id": 2, "reason": "在元素 2 處捲"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "scroll with target_id")
expect(r["coord"], (100, 100), "coord = target_id 2 的中心")

print("\n=== S6: execute_action - scroll 帶 grid_id ===")
r = e.execute_action(
    {"action": "scroll", "direction": "up", "clicks": 2, "grid_id": "B2"},
    COORD_MAP, dry_run=True, grid_map=GRID_MAP,
)
expect_status(r, "ok", "scroll with grid_id")
expect(r["coord"], (150, 150), "coord = grid B2 中心")


# ============================================================
# Drag
# ============================================================
print("\n=== D1: execute_drag (dry-run) ===")
e.execute_drag((10, 10), (200, 200), dry_run=True)
print("  [OK]")

print("\n=== D2: execute_action - drag with start_id/end_id ===")
r = e.execute_action(
    {"action": "drag", "start_id": 0, "end_id": 3, "reason": "從 A 拖到 D"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "drag UIA 模式")
expect(r["coord"], (200, 200), "end 座標")

print("\n=== D3: execute_action - drag with start_grid_id/end_grid_id ===")
r = e.execute_action(
    {"action": "drag", "start_grid_id": "A1", "end_grid_id": "C3", "reason": "對角拖"},
    COORD_MAP, dry_run=True, grid_map=GRID_MAP,
)
expect_status(r, "ok", "drag grid 模式")
expect(r["coord"], (250, 250), "end grid C3 中心")

print("\n=== D4: execute_action - drag 缺欄位 (應 error) ===")
r = e.execute_action(
    {"action": "drag", "start_id": 0},  # 缺 end_id
    COORD_MAP, dry_run=True,
)
expect_status(r, "error", "drag 缺 end_id → error")

print("\n=== D5: execute_action - drag start_id 不存在 ===")
r = e.execute_action(
    {"action": "drag", "start_id": 999, "end_id": 3},
    COORD_MAP, dry_run=True,
)
expect_status(r, "error", "drag 不存在 start_id → error")


# ============================================================
# Grid Fallback
# ============================================================
print("\n=== G1: resolve_grid_id 正常 ===")
x, y = e.resolve_grid_id("C5", {"A1": (10, 10), "C5": (100, 200)})
expect((x, y), (100, 200), "解析 C5")

print("\n=== G2: resolve_grid_id - 大小寫不敏感 ===")
x, y = e.resolve_grid_id("c5", {"C5": (100, 200)})
expect((x, y), (100, 200), "小寫 c5 也能解析")

print("\n=== G3: resolve_grid_id - 空字串 (應 raise) ===")
try:
    e.resolve_grid_id("", GRID_MAP)
    print("  [FAIL] 應 raise")
    sys.exit(1)
except ValueError as ex:
    print(f"  [OK] raise: {ex}")

print("\n=== G4: resolve_grid_id - 不存在 (應 raise) ===")
try:
    e.resolve_grid_id("Z99", GRID_MAP)
    print("  [FAIL] 應 raise")
    sys.exit(1)
except ValueError as ex:
    print(f"  [OK] raise: {ex}")

print("\n=== G5: execute_action - click with grid_id ===")
r = e.execute_action(
    {"action": "click", "grid_id": "B2", "reason": "點 B2"},
    COORD_MAP, dry_run=True, grid_map=GRID_MAP,
)
expect_status(r, "ok", "click with grid_id")
expect(r["coord"], (150, 150), "B2 中心座標")

print("\n=== G6: execute_action - double_click with grid_id ===")
r = e.execute_action(
    {"action": "double_click", "grid_id": "C3", "reason": "雙擊"},
    COORD_MAP, dry_run=True, grid_map=GRID_MAP,
)
expect_status(r, "ok", "double_click with grid_id")
expect(r["coord"], (250, 250), "C3 中心座標")

print("\n=== G7: execute_action - right_click with grid_id ===")
r = e.execute_action(
    {"action": "right_click", "grid_id": "A1", "reason": "右鍵"},
    COORD_MAP, dry_run=True, grid_map=GRID_MAP,
)
expect_status(r, "ok", "right_click with grid_id")
expect(r["coord"], (50, 50), "A1 中心座標")

print("\n=== G8: execute_action - click grid 但缺 grid_map (應 error) ===")
r = e.execute_action(
    {"action": "click", "grid_id": "B2"},
    COORD_MAP, dry_run=True, grid_map={},  # 空的
)
expect_status(r, "error", "click grid 但 grid_map 空 → error")


# ============================================================
# 混合場景：先 grid 模式 scroll，再切回 UIA 點擊
# ============================================================
print("\n=== M1: 完整 grid 流程 ===")
r = e.execute_action(
    {"action": "scroll", "direction": "down", "clicks": 3, "grid_id": "B2"},
    COORD_MAP, dry_run=True, grid_map=GRID_MAP,
)
expect_status(r, "ok", "grid scroll 成功")

print("\n=== M2: 完整 drag (UIA 模式) ===")
r = e.execute_action(
    {"action": "drag", "start_id": 1, "end_id": 3, "reason": "拖動側邊欄"},
    COORD_MAP, dry_run=True,
)
expect_status(r, "ok", "drag 完整流程")


# ============================================================
# 額外常數檢查
# ============================================================
print("\n=== C1: 常數檢查 ===")
expect("scroll" in e.SUPPORTED_ACTIONS, True, "SUPPORTED_ACTIONS 含 scroll")
expect("drag" in e.SUPPORTED_ACTIONS, True, "SUPPORTED_ACTIONS 含 drag")
expect(e.SCROLL_DEFAULT_CLICKS, 3, "SCROLL_DEFAULT_CLICKS 預設 3")
expect(e.GRID_DEFAULT_ROWS, 10, "GRID_DEFAULT_ROWS 預設 10")
expect(e.GRID_DEFAULT_COLS, 10, "GRID_DEFAULT_COLS 預設 10")
expect(len(e.GRID_COL_LETTERS) >= 10, True, "GRID_COL_LETTERS 至少 10 個字母")

print("\nAll Phase 2.7 tests passed!")
