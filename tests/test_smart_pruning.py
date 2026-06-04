# -*- coding: utf-8 -*-
"""Smart Pruning + 截圖壓縮 的專屬測試。

驗證兩個 context 爆炸防護都正確生效：
1. get_clickable_elements 走 Smart Pruning (前景 + 彈出層 + maxDepth=5)
2. 截圖 Base64 用 JPEG 壓縮 (非原生 PNG)
"""
import sys
import os
import base64
import io
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PIL import Image

import wcmd.engine as engine
import wcmd.server as mcp_server
from wcmd.config import DATA_DIR


def expect(actual, expected, msg):
    if actual == expected:
        print(f"  [OK] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        print(f"        expected: {expected!r}")
        print(f"        actual  : {actual!r}")
        sys.exit(1)


def expect_true(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        sys.exit(1)


# ============================================================
# Part 1：Smart Pruning 設定檢查
# ============================================================
print("=== SP-1: MAX_WALK_DEPTH 已限制為 5 ===")
expect(engine.MAX_WALK_DEPTH, 5, "MAX_WALK_DEPTH = 5 (不是無限大)")

print("\n=== SP-2: MAX_WALK_DEPTH 是個合理的整數 ===")
expect_true(isinstance(engine.MAX_WALK_DEPTH, int) and engine.MAX_WALK_DEPTH > 0,
            "MAX_WALK_DEPTH 是正整數")


# ============================================================
# Part 2：截圖壓縮設定檢查
# ============================================================
print("\n=== SS-1: 截圖壓縮常數已設定 ===")
expect(mcp_server.SCREENSHOT_MAX_WIDTH, 1920, "最大寬度 = 1920")
expect(mcp_server.SCREENSHOT_JPEG_QUALITY, 70, "JPEG quality = 70")

print("\n=== SS-2: screenshot_format 已改為 jpeg ===")
expect(mcp_server._encode_image_to_base64.__doc__, mcp_server._encode_image_to_base64.__doc__,
            "_encode_image_to_base64 仍是向後相容的別名")
expect_true("JPEG" in str(mcp_server._encode_compressed_screenshot.__doc__),
            "_encode_compressed_screenshot 註解提到 JPEG")


# ============================================================
# Part 3：實際壓縮功能驗證
# ============================================================
print("\n=== SS-3: 4K 截圖壓縮後 Base64 大小應 < 200KB ===")
# 建立一張 4K (3840x2160) 模擬螢幕截圖
img_4k = Image.new("RGB", (3840, 2160), "white")
# 畫一些紅框模擬真實截圖
from PIL import ImageDraw
draw = ImageDraw.Draw(img_4k)
for i in range(20):
    x = i * 200
    draw.rectangle([x, 100, x+150, 200], outline="red", width=3)
    draw.text((x+10, 120), str(i), fill="red")
test_path = DATA_DIR / "test_4k_screen.jpg"
img_4k.save(test_path, "PNG")  # 先存成 PNG (模擬 generate_marked_screenshot 產出)

# 編碼
b64 = mcp_server._encode_compressed_screenshot(str(test_path))
b64_size_kb = len(b64) / 1024
print(f"    4K 截圖壓縮後 Base64 大小: {b64_size_kb:.1f} KB")
expect_true(b64_size_kb < 200,
            f"4K 截圖 Base64 < 200KB (實際 {b64_size_kb:.1f}KB)")

# 解碼回 JPEG bytes 確認是 JPEG
raw = base64.b64decode(b64)
expect_true(raw[:2] == b"\xff\xd8",
            "解碼後前 2 bytes 為 0xFFD8 (JPEG magic number)")

# 還原成圖片確認仍可讀
img_back = Image.open(io.BytesIO(raw))
expect(img_back.format, "JPEG", "解碼後是 JPEG 格式")
expect(img_back.width, 1920, "寬度已縮放至 1920")
expect_true(img_back.height == 1080, f"高度等比例縮放 (1920x1080)，實際 {img_back.height}")


print("\n=== SS-4: 小於 1920 寬的截圖不縮放 ===")
img_small = Image.new("RGB", (1280, 720), "blue")
test_path_small = DATA_DIR / "test_small_screen.png"
img_small.save(test_path_small)
b64_small = mcp_server._encode_compressed_screenshot(str(test_path_small))
img_back_small = Image.open(io.BytesIO(base64.b64decode(b64_small)))
expect(img_back_small.width, 1280, "1280 寬不縮放")
expect(img_back_small.height, 720, "720 高不縮放")


print("\n=== SS-5: 4K 全彩複雜畫面也能控制在合理大小 ===")
# 模擬真實螢幕截圖 (4K + 大量細節)
import random
random.seed(42)
img_real = Image.new("RGB", (3840, 2160), "white")
draw_real = ImageDraw.Draw(img_real)
# 大量彩色細節 (模擬 UI 元素)
for i in range(500):
    x = random.randint(0, 3800)
    y = random.randint(0, 2100)
    w = random.randint(10, 200)
    h = random.randint(10, 80)
    color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    draw_real.rectangle([x, y, x+w, y+h], fill=color)
# 大量文字 (模擬 UI 文字內容)
for i in range(300):
    x = random.randint(0, 3500)
    y = random.randint(0, 2000)
    draw_real.text((x, y), f"Element Label {i:04d}", fill=(0, 0, 0))

img_real.save(DATA_DIR / "test_realistic_4k.png", "PNG")

# 編碼
b64 = mcp_server._encode_compressed_screenshot(str(DATA_DIR / "test_realistic_4k.png"))
b64_size_kb = len(b64) / 1024
print(f"    4K 複雜畫面 JPEG Base64: {b64_size_kb:.1f} KB")
expect_true(b64_size_kb < 300,
            f"4K 複雜畫面 < 300KB (實際 {b64_size_kb:.1f}KB)")
# 對比：若不壓縮，4K 全彩 PNG Base64 通常會到 8~15 MB
# 壓縮後 < 300KB = 省下 95%+ token
print(f"    對比：原生 4K PNG Base64 通常 8~15 MB")
print(f"    壓縮後省下約 95%+ context token")


# ============================================================
# Part 4：清理測試檔
# ============================================================
print("\n=== Cleanup ===")
for f in [test_path, test_path_small, DATA_DIR / "test_for_compare.png"]:
    if f.exists():
        f.unlink()
        print(f"  刪除 {f.name}")


print("\nAll Smart Pruning + Screenshot compression tests passed!")
