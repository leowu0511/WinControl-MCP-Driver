# -*- coding: utf-8 -*-
"""Phase 2.6 煙霧測試 - 純函數 (不觸碰滑鼠/鍵盤/螢幕)"""
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


print("=== 測試 1: 模組常數 ===")
expect(sorted(e.SUPPORTED_ACTIONS),
       ["NOT_FOUND", "click", "double_click", "drag", "hotkey", "right_click", "scroll", "type"],
       "SUPPORTED_ACTIONS 內容")
expect("ctrl" in e.HOTKEY_ALIAS, True, "HOTKEY_ALIAS 含 ctrl")
expect("win" in e.HOTKEY_ALIAS, True, "HOTKEY_ALIAS 含 win")
expect("enter" in e.HOTKEY_ALIAS, True, "HOTKEY_ALIAS 含 enter")
expect("f12" in e.HOTKEY_ALIAS, True, "HOTKEY_ALIAS 含 f12")

print("\n=== 測試 2: parse_ai_response - 純 JSON ===")
r = e.parse_ai_response('{"action": "click", "target_id": 5, "reason": "x"}')
expect(r, {"action": "click", "target_id": 5, "reason": "x"}, "純 JSON 解析")

print("\n=== 測試 3: parse_ai_response - JSON in markdown fence ===")
r = e.parse_ai_response('```json\n{"action": "hotkey", "keys": "ctrl+c"}\n```')
expect(r["action"], "hotkey", "fence 內 action")
expect(r["keys"], "ctrl+c", "fence 內 keys")

print("\n=== 測試 4: parse_ai_response - JSON with trailing text ===")
r = e.parse_ai_response('好的我幫您處理 {"action": "type", "text": "hello"} 這樣可以嗎？')
expect(r["action"], "type", "trailing text 中 action")
expect(r["text"], "hello", "trailing text 中 text")

print("\n=== 測試 5: parse_ai_response - 舊版純數字 (向後相容) ===")
r = e.parse_ai_response('42')
expect(r["action"], "click", "純數字 → click")
expect(r["target_id"], 42, "純數字 → target_id")

print("\n=== 測試 6: parse_ai_response - NOT_FOUND ===")
r = e.parse_ai_response('{"action": "NOT_FOUND", "reason": "找不到搜尋框"}')
expect(r["action"], "NOT_FOUND", "NOT_FOUND → canonical 大寫 (給 dispatcher 用)")
expect(r["reason"], "找不到搜尋框", "reason 保留")

print("\n=== 測試 7: parse_ai_response - 損壞的 JSON (自動補括號) ===")
r = e.parse_ai_response('{"action": "right_click", "target_id": 12')
expect(r["action"], "right_click", "補括號後 action")
expect(r["target_id"], 12, "補括號後 target_id")

print("\n=== 測試 8: parse_ai_response - 缺 action 但有 target_id (自動補 click) ===")
r = e.parse_ai_response('{"target_id": 99}')
expect(r["action"], "click", "自動補 action=click")
expect(r["target_id"], 99, "target_id 保留")

print("\n=== 測試 9: parse_ai_response - 完全無效 (應 raise) ===")
try:
    e.parse_ai_response('我不知道該怎麼做')
    print("  [FAIL] 應該要 raise ValueError")
    sys.exit(1)
except ValueError as ex:
    print(f"  [OK] raise ValueError: {str(ex)[:60]}...")

print("\n=== 測試 10: parse_ai_response - 不支援的 action (應 raise) ===")
try:
    e.parse_ai_response('{"action": "swim", "target_id": 1}')
    print("  [FAIL] 應該要 raise ValueError")
    sys.exit(1)
except ValueError as ex:
    print(f"  [OK] raise ValueError: {str(ex)[:60]}...")

print("\n=== 測試 11: parse_ai_response - 空字串 (應 raise) ===")
try:
    e.parse_ai_response('')
    print("  [FAIL] 應該要 raise ValueError")
    sys.exit(1)
except ValueError as ex:
    print(f"  [OK] raise ValueError: {ex}")

print("\nAll parse_ai_response tests passed!")
