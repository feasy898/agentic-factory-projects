"""training/ 资产包 dry-run 测试（T11；真实训练一律不在本机执行）。

覆盖（全部无硬件、无真实训练）：
- act.build_train_cmd：入口名 fail-closed（exit 2）/ 占位符 / 注入生成 /
  配置校验拒绝（exit 2）/ §10.2 报告落盘；
- spoon_cls.prepare_data：episode 布局校验、自动标注取窗、按回合确定性
  切分（无泄漏）、--write 产物、dry-run 不写文件；
- spoon_cls.train：dry-run 计划（exit 0）/ --execute 无放行拒绝（exit 2）；
- spoon_cls.export_onnx：无 checkpoint 拒绝（exit 2）/ dry-run 计划（exit 0）；
- spoon_cls.eval：指标重算达标（exit 0）/ 漏检率超线（exit 1）/ 坏输入（exit 2）；
- transfer.cos_transfer：计划生成（exit 0）/ execute 无 --yes / 无 coscmd 拒绝（exit 2）；
- record.record_demo：dry-run 计划（exit 0）/ execute 无硬件会话拒绝（exit 2）。

运行（仓库根）：python -m pytest tests/test_training_scripts.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

ENV_BASE = {"PYTHONUTF8": "1", "PYTHONPATH": str(REPO_ROOT)}


def run_module(module: str, *argv: str, env_extra: dict | None = None,
               cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    env = {**os.environ, **ENV_BASE, **(env_extra or {})}
    env.pop("CS_ALLOW_TRAIN", None)
    env.pop("CS_HW_SESSION", None)
    return subprocess.run(
        [PY, "-m", module, *argv], cwd=str(cwd), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=120,
    )


# ---------------------------------------------------------------------------
# act.build_train_cmd
# ---------------------------------------------------------------------------

def test_build_train_cmd_requires_entry_point_fail_closed():
    r = run_module("chengshao.training.act.build_train_cmd")
    assert r.returncode == 2, r.stdout
    assert "CS_TRAIN_CMD" in r.stdout  # 提示注入方式


def test_build_train_cmd_placeholder_and_injected(tmp_path):
    r = run_module("chengshao.training.act.build_train_cmd", "--allow-placeholder")
    assert r.returncode == 0, r.stdout
    assert "--policy.type=act" in r.stdout and "--wandb.enable=false" in r.stdout

    out = tmp_path / "cmd_report.json"
    r2 = run_module("chengshao.training.act.build_train_cmd",
                    "--train-cmd", "some-train-cli", "--out", str(out))
    assert r2.returncode == 0, r2.stdout
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["metrics"]["entry_resolved"] is True
    assert "some-train-cli" in rep["metrics"]["generated_command"]
    assert rep["metrics"]["flags"][-1] == "--wandb.enable=false"


def test_build_train_cmd_rejects_bad_config(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "$comment": "坏配置：wandb 未关", "policy": {"type": "act"},
    }), encoding="utf-8")
    r = run_module("chengshao.training.act.build_train_cmd", "--config", str(bad))
    assert r.returncode == 2, r.stdout


# ---------------------------------------------------------------------------
# spoon_cls.prepare_data
# ---------------------------------------------------------------------------

def _make_episode(root: Path, episode_id: str, n_frames: int,
                  scoop: list[int], bite: list[int]) -> None:
    d = root / episode_id
    d.mkdir(parents=True)
    frames = [f"f{i:06d}.png" for i in range(n_frames)]
    (d / "events.json").write_text(json.dumps(
        {"frames": frames, "scoop_done": scoop, "bite_end": bite}), encoding="utf-8")


def test_prepare_data_dry_run_writes_nothing(tmp_path):
    raw = tmp_path / "raw"
    _make_episode(raw, "ep_a", 50, [20], [40])
    _make_episode(raw, "ep_b", 50, [10], [45])
    ds = tmp_path / "ds"
    r = run_module("chengshao.training.spoon_cls.prepare_data",
                   "--episodes-root", str(raw), "--out", str(ds.relative_to(tmp_path)),
                   cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    assert "dry-run" in r.stdout
    assert not ds.exists() and not (tmp_path / "data").exists()


def test_prepare_data_labels_windows_and_split_without_leakage(tmp_path):
    raw = tmp_path / "raw"
    for i in range(6):
        _make_episode(raw, f"ep_{i}", 60, [20], [50])
    # prepare_data 的 --out 走 safe_rel_output（仓库相对）；测试里把产物写到
    # 仓库内 data/ 下再断言，最后清理。
    repo_ds = REPO_ROOT / "data" / "_pytest_spoon_ds"
    try:
        r = run_module("chengshao.training.spoon_cls.prepare_data",
                       "--episodes-root", str(raw), "--out", "data/_pytest_spoon_ds",
                       "--write")
        assert r.returncode == 0, r.stdout
        index = (repo_ds / "index.csv").read_text(encoding="utf-8").strip().splitlines()
        assert index[0] == "split,episode_id,frame,label"
        rows = [ln.split(",") for ln in index[1:]]
        assert len(rows) == 6 * 14  # 每回合 2 事件 × 7 帧窗（±3）
        # 标注取窗：scoop_done=20 → 17..23 标 1；bite_end=50 → 47..53 标 0
        ep0 = {ln.split(",")[2]: int(ln.split(",")[3])
               for ln in index[1:] if ln.split(",")[1] == "ep_0"}
        assert len(ep0) == 14
        for k in range(17, 24):
            assert ep0[f"f{k:06d}.png"] == 1
        for k in range(47, 54):
            assert ep0[f"f{k:06d}.png"] == 0
        # 切分：按回合，无泄漏（同回合只进一个 split）
        split = json.loads((repo_ds / "split.json").read_text(encoding="utf-8"))["splits"]
        all_eps = [e for s in split.values() for e in s]
        assert sorted(all_eps) == sorted(f"ep_{i}" for i in range(6))
        assert len(set(all_eps)) == len(all_eps)
        assert len(split["train"]) == 4 and len(split["val"]) == 1 and len(split["test"]) == 1
    finally:
        shutil.rmtree(repo_ds, ignore_errors=True)


def test_prepare_data_rejects_missing_events(tmp_path):
    raw = tmp_path / "raw"
    (raw / "ep_bad").mkdir(parents=True)
    r = run_module("chengshao.training.spoon_cls.prepare_data",
                   "--episodes-root", str(raw), cwd=tmp_path)
    assert r.returncode == 2, r.stdout


def test_prepare_data_split_is_deterministic(tmp_path):
    raw = tmp_path / "raw"
    for i in range(8):
        _make_episode(raw, f"ep_{i}", 40, [10], [30])
    a = run_module("chengshao.training.spoon_cls.prepare_data",
                   "--episodes-root", str(raw), cwd=tmp_path)
    b = run_module("chengshao.training.spoon_cls.prepare_data",
                   "--episodes-root", str(raw), cwd=tmp_path)
    plan_a = [ln for ln in a.stdout.splitlines() if ln.startswith("PLAN:")]
    plan_b = [ln for ln in b.stdout.splitlines() if ln.startswith("PLAN:")]
    assert plan_a and plan_a == plan_b  # 同输入两次 dry-run 计划一致（时间戳除外）


# ---------------------------------------------------------------------------
# spoon_cls.train
# ---------------------------------------------------------------------------

def test_spoon_train_dry_run_rejects_missing_dataset():
    r = run_module("chengshao.training.spoon_cls.train",
                   "--dataset", "data/_pytest_nonexist")
    # 数据集不存在 → exit 2（参数/路径错误），这是 dry-run 的校验职责
    assert r.returncode == 2, r.stdout


def test_spoon_train_dry_run_plan_on_real_dataset(tmp_path):
    raw = tmp_path / "raw"
    for i in range(4):
        _make_episode(raw, f"ep_{i}", 40, [10], [30])
    repo_ds = REPO_ROOT / "data" / "_pytest_spoon_ds2"
    try:
        r = run_module("chengshao.training.spoon_cls.prepare_data",
                       "--episodes-root", str(raw), "--out", "data/_pytest_spoon_ds2",
                       "--write")
        assert r.returncode == 0, r.stdout
        r2 = run_module("chengshao.training.spoon_cls.train",
                        "--dataset", "data/_pytest_spoon_ds2")
        assert r2.returncode == 0, r2.stdout
        assert "'steps_total':" in r2.stdout and "dry-run" in r2.stdout
    finally:
        shutil.rmtree(repo_ds, ignore_errors=True)


def test_spoon_train_dry_run_is_deterministic(tmp_path):
    raw = tmp_path / "raw"
    for i in range(4):
        _make_episode(raw, f"ep_{i}", 40, [10], [30])
    repo_ds = REPO_ROOT / "data" / "_pytest_spoon_ds3"
    try:
        run_module("chengshao.training.spoon_cls.prepare_data",
                   "--episodes-root", str(raw), "--out", "data/_pytest_spoon_ds3",
                   "--write")
        outs = []
        for _ in range(2):
            r = run_module("chengshao.training.spoon_cls.train",
                           "--dataset", "data/_pytest_spoon_ds3")
            assert r.returncode == 0, r.stdout
            outs.append([ln for ln in r.stdout.splitlines() if ln.startswith("PLAN:")])
        assert outs[0] == outs[1]  # 计划逐行一致（时间戳不在 PLAN 行内）
    finally:
        shutil.rmtree(repo_ds, ignore_errors=True)


def test_spoon_train_execute_refused_without_allow_flag():
    r = run_module("chengshao.training.spoon_cls.train", "--execute")
    assert r.returncode == 2, r.stdout
    assert "CS_ALLOW_TRAIN" in r.stdout


def test_spoon_train_execute_refused_even_with_flag_on_cpu_machine():
    # 本机有 torch 但无 CUDA：人工放行也必须拒绝（真实训练只允许 GPU 机）
    r = run_module("chengshao.training.spoon_cls.train", "--execute",
                   env_extra={"CS_ALLOW_TRAIN": "1"})
    assert r.returncode == 2, r.stdout


# ---------------------------------------------------------------------------
# spoon_cls.export_onnx / eval
# ---------------------------------------------------------------------------

def test_spoon_export_requires_checkpoint_without_dry_run():
    r = run_module("chengshao.training.spoon_cls.export_onnx",
                   "--checkpoint", "data/_pytest_nonexist.pt")
    assert r.returncode == 2, r.stdout


def test_spoon_export_dry_run_plan(tmp_path):
    r = run_module("chengshao.training.spoon_cls.export_onnx",
                   "--checkpoint", str(tmp_path / "whatever.pt"), "--dry-run")
    assert r.returncode == 0, r.stdout
    assert "'opset': 17" in r.stdout


def test_spoon_cls_eval_thresholds(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({
        "split": "test",
        "predictions": [{"prob": 0.9, "label": 1}] * 50 + [{"prob": 0.1, "label": 0}] * 45
                       + [{"prob": 0.2, "label": 1}] * 2 + [{"prob": 0.8, "label": 0}] * 3,
        "cpu_latency_ms": [10.0, 12.0, 11.5],
    }), encoding="utf-8")
    r = run_module("chengshao.training.spoon_cls.eval", "--metrics", str(good))
    # acc = 95/100 = 0.95 ≥ 0.95；漏检 = 2/52 ≈ 0.0385 > 0.03 硬线 → exit 1
    assert r.returncode == 1, r.stdout
    assert "'miss_rate': 0.0385" in r.stdout

    better = tmp_path / "better.json"
    better.write_text(json.dumps({
        "split": "test",
        "predictions": [{"prob": 0.9, "label": 1}] * 50 + [{"prob": 0.1, "label": 0}] * 48
                       + [{"prob": 0.2, "label": 1}] * 1,
        "cpu_latency_ms": [10.0, 12.0, 11.5],
    }), encoding="utf-8")
    r2 = run_module("chengshao.training.spoon_cls.eval", "--metrics", str(better))
    # acc = 98/99 ≈ 0.99；漏检 = 1/51 ≈ 0.0196 ≤ 0.03 → 达标
    assert r2.returncode == 0, r2.stdout


def test_spoon_cls_eval_bad_input(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"predictions": "not-a-list"}), encoding="utf-8")
    r = run_module("chengshao.training.spoon_cls.eval", "--metrics", str(bad))
    assert r.returncode == 2, r.stdout


# ---------------------------------------------------------------------------
# transfer.cos_transfer
# ---------------------------------------------------------------------------

def test_cos_transfer_plan_generation(tmp_path):
    out = tmp_path / "plan.json"
    r = run_module("chengshao.training.transfer.cos_transfer",
                   "--entry", "spoon_scooping_v1", "up", "--out", str(out))
    assert r.returncode == 0, r.stdout
    plan = json.loads(out.read_text(encoding="utf-8"))["plan"]
    assert plan["direction"] == "up"
    assert any(cmd.startswith("7z") for cmd in plan["commands"])
    assert any(cmd.startswith("coscmd") for cmd in plan["commands"])
    assert plan["executed"] is False


def test_cos_transfer_execute_requires_yes():
    r = run_module("chengshao.training.transfer.cos_transfer",
                   "--entry", "runs", "up", "--execute")
    assert r.returncode == 2, r.stdout
    assert "--yes" in r.stdout


def test_cos_transfer_unknown_entry():
    r = run_module("chengshao.training.transfer.cos_transfer", "--entry", "nope", "up")
    assert r.returncode == 2, r.stdout


# ---------------------------------------------------------------------------
# record.record_demo
# ---------------------------------------------------------------------------

def test_record_demo_dry_run_plan():
    r = run_module("chengshao.training.record.record_demo", "--episode", "taro_a_001")
    assert r.returncode == 0, r.stdout
    assert "'joint_channels': 6" in r.stdout  # 契约 v1.1：N_ARM_JOINTS=6
    assert "dry-run" in r.stdout


def test_record_demo_rejects_bad_fps_and_cams():
    r = run_module("chengshao.training.record.record_demo",
                   "--episode", "x", "--fps", "120")
    assert r.returncode == 2, r.stdout
    r2 = run_module("chengshao.training.record.record_demo",
                    "--episode", "x", "--cams", "left,right")
    assert r2.returncode == 2, r2.stdout


def test_record_demo_execute_refused_without_hw_session():
    r = run_module("chengshao.training.record.record_demo",
                   "--episode", "x", "--execute")
    assert r.returncode == 2, r.stdout
    assert "CS_HW_SESSION" in r.stdout
