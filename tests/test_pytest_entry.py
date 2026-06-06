# -*- coding: utf-8 -*-
"""Pytest 入口：用 subprocess 跑所有 script-style 測試。

原本的 test_*.py 檔是 script-style（在模組層級直接 assert），
透過 subprocess 呼叫它們執行，並用 pytest 收集回報。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent

# 列出所有要跑的 script-style 測試 (依賴順序：基礎測試先跑)
SCRIPTS = [
    "test_phase26.py",         # parse_ai_response 單元測試
    "test_dispatcher.py",      # execute_action dispatcher
    "test_e2e.py",             # main() 端到端
    "test_phase27.py",         # scroll/drag/grid
    "test_grid_e2e.py",        # grid fallback e2e
    "test_grid_real.py",       # 真實螢幕 grid
    "test_mcp_tools.py",       # 3 個 MCP tools
    "test_smart_pruning.py",   # Smart Pruning + JPEG 截圖壓縮
]


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_script_runs_successfully(script_name):
    """跑一個 script-style 測試檔，確認回傳 0 且有 'All ... passed!' 訊息。"""
    script_path = TESTS_DIR / script_name
    assert script_path.exists(), f"找不到測試檔：{script_path}"

    # 環境變數：給假 API Key (避免測試因缺 key 失敗)
    env = os.environ.copy()
    env["WCMD_VISION_API_KEY"] = env.get("WCMD_VISION_API_KEY", "sk-dummy-for-pytest")
    # Windows 中文環境必備
    env["PYTHONIOENCODING"] = "utf-8"
    # 確保能找到 src/wcmd 套件
    src_path = str(TESTS_DIR.parent / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # 無法解碼的字元用 � 取代，避免拋例外
        env=env,
        timeout=120,  # 每個測試最多 2 分鐘
    )

    # 印出 stdout/stderr 讓 pytest -v 顯示細節
    if result.stdout:
        sys.stdout.write(f"\n--- {script_name} stdout ---\n{result.stdout[-2000:]}\n")
    if result.stderr and result.returncode != 0:
        sys.stdout.write(f"\n--- {script_name} stderr ---\n{result.stderr[-2000:]}\n")

    assert result.returncode == 0, (
        f"{script_name} 退出碼 {result.returncode} (預期 0)\n"
        f"stderr 最後 500 字：{result.stderr[-500:] if result.stderr else '(empty)'}"
    )
    assert "All" in result.stdout and "passed!" in result.stdout, (
        f"{script_name} 沒印出 'All ... passed!' 訊息\n"
        f"stdout 最後 500 字：{result.stdout[-500:]}"
    )
