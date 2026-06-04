# -*- coding: utf-8 -*-
"""Phase 2.7 真實螢幕測試 - generate_grid_screenshot"""
import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wcmd import engine as e


print("=== 真實螢幕: generate_grid_screenshot(8x12) ===")
img, grid_map = e.generate_grid_screenshot(rows=8, cols=12)
img.save("test_grid_real.png")
print(f"  圖片尺寸: {img.size}")
print(f"  grid_map 數量: {len(grid_map)}")
print(f"  預期: 8*12=96")
assert len(grid_map) == 96, f"應有 96 個格子，收到 {len(grid_map)}"

for label in list(grid_map.keys())[:5] + list(grid_map.keys())[-5:]:
    assert re.match(r"^[A-L][1-8]$", label), f"格 {label} 格式錯誤"
print(f"  前 5 個 label: {list(grid_map.keys())[:5]}")
print(f"  後 5 個 label: {list(grid_map.keys())[-5:]}")

a1 = grid_map["A1"]
l8 = grid_map["L8"]
print(f"  A1 中心: {a1}  (左上)")
print(f"  L8 中心: {l8}  (右下)")
assert a1[0] < l8[0] and a1[1] < l8[1], "A1 應在 L8 左上方"

x, y = e.resolve_grid_id("A1", grid_map)
print(f"  resolve_grid_id(A1) = ({x}, {y})")
assert (x, y) == a1

x, y = e.resolve_grid_id("l8", grid_map)  # 小寫也要能解析
print(f"  resolve_grid_id(l8) = ({x}, {y})")
assert (x, y) == l8


print("\n=== 邊界保護: 太大 rows 被截斷 ===")
img2, gm2 = e.generate_grid_screenshot(rows=50, cols=50)
print(f"  請求 50x50，實際產生: {len(gm2)} 個格子")
assert len(gm2) == e.GRID_MAX_SIZE * e.GRID_MAX_SIZE, f"應被截到 {e.GRID_MAX_SIZE}x{e.GRID_MAX_SIZE}"

print("\n=== 邊界保護: 太小 rows 自動放大 ===")
img3, gm3 = e.generate_grid_screenshot(rows=1, cols=1)
print(f"  請求 1x1，實際產生: {len(gm3)} 個格子")
assert len(gm3) == e.GRID_MIN_SIZE * e.GRID_MIN_SIZE

print("\n=== 邊界檢查: GRID_MAX_SIZE 與 GRID_COL_LETTERS 一致性 ===")
print(f"  GRID_MAX_SIZE = {e.GRID_MAX_SIZE}")
print(f"  len(GRID_COL_LETTERS) = {len(e.GRID_COL_LETTERS)}")
assert e.GRID_MAX_SIZE <= len(e.GRID_COL_LETTERS), "MAX_SIZE 不應超過字母表長度"


print("\n=== 預設大小 10x10 ===")
img4, gm4 = e.generate_grid_screenshot()
print(f"  預設: {len(gm4)} 個格子 (預期 100)")
assert len(gm4) == 100

print("\nAll real screen grid tests passed!")
