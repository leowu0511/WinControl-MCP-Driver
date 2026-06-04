# -*- coding: utf-8 -*-
"""pytest 共用 fixtures 與路徑設定。"""
import sys
import os
import pytest

# 確保 src/ 在 path 中，這樣 `from wcmd import engine` 才找得到
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """讓每個測試使用獨立的資料目錄 (避免污染 ~/.wcmd/)。"""
    monkeypatch.setenv("WCMD_DATA_DIR", str(tmp_path))
    # 重新載入 config 模組以套用新的 env var
    from wcmd import config
    import importlib
    importlib.reload(config)
    # 同步更新 engine 模組的全域常數
    from wcmd import engine
    engine.OUTPUT_IMAGE_PATH = config.OUTPUT_IMAGE_PATH
    engine.COORD_MAP_PATH = config.COORD_MAP_PATH
    yield


@pytest.fixture
def fake_api_key():
    """提供一個假的 API Key 給測試用。"""
    os.environ["WCMD_VISION_API_KEY"] = "sk-fake-test-key-not-real"
    return "sk-fake-test-key-not-real"
