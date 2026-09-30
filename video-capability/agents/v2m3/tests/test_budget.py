"""API 适配层测试: 预算守卫 / 重试切兜底 / env 解析。网络不发真包, 全部注入。"""

from __future__ import annotations

import pytest

from src.api.adapters import (
    Adapter,
    BudgetGuard,
    CAPABILITY_LIMITS,
    Endpoint,
    LocalUnavailable,
    endpoint_from_env,
)


class NullLog:
    def __init__(self):
        self.rows = []

    def __call__(self, level, msg):
        self.rows.append((level, msg))


def make_adapter(db, api_fn=None, local_fn=None, configured=True, limits=None, cap="vlm"):
    ep = Endpoint(cap, "https://api.example", "sk-x", "m-1") if configured else Endpoint(cap)
    return Adapter(cap, ep, BudgetGuard(db, limits=limits), api_fn=api_fn, local_fn=local_fn, log=NullLog())


def test_capability_limits_defaults():
    assert CAPABILITY_LIMITS == {"image": 300, "vlm": 1500, "tts": 200, "asr": 200}


def test_unconfigured_goes_local(db):
    seen = {}

    def local(p, out):
        seen["args"] = (p, out)
        return "LOCAL"

    a = make_adapter(db, api_fn=lambda *a, **k: pytest.fail("不应调 API"), local_fn=local, configured=False)
    result, route = a.call("x", "y")
    assert result == "LOCAL" and route == "local"
    assert seen["args"] == ("x", "y")
    assert db.api_usage_count("vlm", route="local") == 1
    assert db.api_usage_count("vlm", route="api") == 0


def test_api_success_no_retry(db):
    calls = []

    def api(*a, **k):
        calls.append(1)
        return "API"

    a = make_adapter(db, api_fn=api, local_fn=lambda *a, **k: pytest.fail("不应切本地"))
    result, route = a.call()
    assert (result, route) == ("API", "api")
    assert len(calls) == 1
    assert db.api_usage_count("vlm", route="api") == 1


def test_api_retry_once_then_local(db):
    calls = []

    def api(*a, **k):
        calls.append(1)
        raise RuntimeError("503")

    a = make_adapter(db, api_fn=api, local_fn=lambda *a, **k: "LOCAL")
    result, route = a.call()
    assert (result, route) == ("LOCAL", "local")
    assert len(calls) == 2  # 重试1次(共2次尝试)
    s = db.api_usage_summary()["vlm"]
    assert s["api_fail"] == 2 and s["local_ok"] == 1


def test_budget_exhausted_forces_local(db):
    for _ in range(2):  # 预置 vlm api 已用 2 次
        db.log_api_usage("vlm", "api", True)
    a = make_adapter(db, api_fn=lambda *a, **k: pytest.fail("预算耗尽不应调 API"),
                     local_fn=lambda *a, **k: "LOCAL", limits={"vlm": 2})
    result, route = a.call()
    assert (result, route) == ("LOCAL", "local")


def test_budget_remaining_counts_attempts(db):
    bg = BudgetGuard(db, limits={"tts": 3})
    assert bg.can_use_api("tts")
    bg.record("tts", "api", False)
    bg.record("tts", "api", False)
    assert bg.remaining("tts") == 1
    bg.record("tts", "api", False)
    assert not bg.can_use_api("tts")


def test_no_local_impl_raises(db):
    a = make_adapter(db, api_fn=None, local_fn=None, configured=False)
    with pytest.raises(LocalUnavailable):
        a.call()


def test_endpoint_from_env_both_key_styles():
    env = {
        "VLM": {"base": "https://v", "key": "k", "model": "m", "configured": True},
        "TTS": {"base": "https://t", "key": "k", "model": "", "configured": False},
    }
    assert endpoint_from_env(env, "VLM").configured is True
    assert endpoint_from_env(env, "TTS").configured is False


def test_parse_api_env(tmp_path):
    from src.config import parse_api_env

    p = tmp_path / "api.env"
    p.write_text(
        "# 注释\n"
        "IMAGE_API_BASE=\n"
        "VLM_API_BASE=https://v/1\nVLM_API_KEY=kk\nVLM_MODEL=vm1\n"
        "TTS_API_BASE=https://t\nTTS_API_KEY=kk\nTTS_API_MODEL=tm1\n",
        encoding="utf-8",
    )
    env = parse_api_env(p)
    assert env["VLM"]["configured"] is True and env["VLM"]["model"] == "vm1"
    assert env["TTS"]["configured"] is True and env["TTS"]["model"] == "tm1"  # 兼容 X_API_MODEL
    assert env["IMAGE"]["configured"] is False
    assert env["ASR"]["configured"] is False


def test_parse_api_env_missing_file(tmp_path):
    from src.config import parse_api_env

    env = parse_api_env(tmp_path / "nope.env")
    assert all(not v["configured"] for v in env.values())
