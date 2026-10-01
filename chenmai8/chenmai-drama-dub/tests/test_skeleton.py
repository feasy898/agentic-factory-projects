"""T1 骨架测试：jobs 目录生成器、CLI、configs 三件套、中性命名纪律。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from pipeline import contracts as C
from pipeline.cli import main
from pipeline.config import CONFIG_DIR, jobs_dir, load_pipeline_config
from pipeline.scaffold import EXPECTED_FILES, LAYERS, create_workspace

from tests.test_contracts import C2_UTT, C7_LABELS

# ---------------------------------------------------------------------------
# jobs 目录生成器
# ---------------------------------------------------------------------------

def test_create_workspace_all_layers(tmp_path):
    created = create_workspace("ep01", tmp_path)
    # 13 层目录 + 5 个子目录 + 根目录
    assert len(created) == 1 + len(LAYERS) + 5
    root = tmp_path / "ep01"
    for layer in LAYERS:
        assert (root / layer).is_dir(), layer
    for sub_dir in ["04_dial/emo_refs", "05_cast/voicebank", "05_cast/consent",
                    "07_synth/wavs", "09_lip/done"]:
        assert (root / sub_dir).is_dir(), sub_dir
    # 骨架不预生成产物文件（避免空文件被误当产物）
    assert not any(p.is_file() for p in root.rglob("*"))


def test_create_workspace_idempotent(tmp_path):
    create_workspace("ep01", tmp_path)
    create_workspace("ep01", tmp_path)  # 二次执行不报错
    assert (tmp_path / "ep01" / "02_shots").is_dir()


def test_expected_path_helper(tmp_path):
    p = C  # noqa: F841  占位避免误删 import
    from pipeline.scaffold import expected_path
    path = expected_path("ep01", "04_dial", "utterances.jsonl", tmp_path)
    assert path == tmp_path / "ep01" / "04_dial" / "utterances.jsonl"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_init(tmp_path, capsys):
    assert main(["init", "ep01", "--jobs-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "OK" in out and "02_shots/" in out
    assert (tmp_path / "ep01" / "12_out").is_dir()


def test_cli_validate_ok_and_fail(tmp_path, capsys):
    u_path = tmp_path / "utterances.jsonl"
    C.dump_jsonl(u_path, C.UtteranceTable.model_validate([json.loads(C2_UTT)]))
    assert main(["validate", "utterances", str(u_path)]) == 0
    assert "OK C2" in capsys.readouterr().out

    bad = tmp_path / "bad.jsonl"
    row = json.loads(C2_UTT)
    bad.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    assert main(["validate", "utterances", str(bad)]) == 1
    assert "FAIL C2" in capsys.readouterr().out


def test_cli_validate_labels(tmp_path, capsys):
    p = tmp_path / "labels.json"
    p.write_text(C7_LABELS, encoding="utf-8")
    assert main(["validate", "labels", str(p)]) == 0
    assert "OK C7" in capsys.readouterr().out


def test_cli_validate_missing_file(tmp_path, capsys):
    assert main(["validate", "shots", str(tmp_path / "nope.json")]) == 1


def test_cli_run_usage_guard(tmp_path):
    # M14 落地后 run=enqueue+resume（pipeline.queue）；用法守卫：未知步骤
    # 在入队前拒绝（exit 2），且不落任何作业行/库文件（T1 占位断言随 M14 更新）。
    db = tmp_path / "jobs.db"
    rc = main(["run", "ep01", "--langs", "en", "--to", "no-such-step",
               "--jobs-dir", str(tmp_path), "--db", str(db),
               "--metrics-db", str(tmp_path / "metrics.db")])
    assert rc == 2
    assert not db.exists()  # 校验先行，未写任何行


# ---------------------------------------------------------------------------
# configs 三件套
# ---------------------------------------------------------------------------

def test_config_dir_exists():
    assert (CONFIG_DIR / "pipeline.yaml").is_file()
    assert (CONFIG_DIR / "models.yaml").is_file()
    assert (CONFIG_DIR / "voices.yaml").is_file()


def test_pipeline_yaml_contract():
    cfg = load_pipeline_config()
    assert cfg["media"]["width"] == 1080 and cfg["media"]["height"] == 1920
    assert cfg["media"]["fps"] == 25
    assert cfg["media"]["audio"]["asr_sr"] == 16000
    assert cfg["media"]["audio"]["mix_sr"] == 48000
    lz = cfg["label_zone"]
    assert lz["position"] == "top-center" and lz["min_duration_s"] >= 3.0
    assert lz["text"] == "本内容由AI生成"
    assert cfg["erase_band"]["y0_px"] < cfg["erase_band"]["y1_px"]
    assert cfg["erase_band"]["y1_px"] <= 1920
    assert cfg["speed_window"] == [0.9, 1.1]
    assert cfg["loudness_lufs"] == -16
    # paths 解析为绝对路径（相对 configs/ 目录）
    assert Path(cfg["paths"]["jobs_dir"]).is_absolute()
    assert Path(cfg["paths"]["jobs_dir"]).name == "jobs"
    # channels：三语种 → 市场规则包 + 字幕样式
    assert set(cfg["channels"]) == {"en", "es", "ar"}
    assert cfg["channels"]["en"]["market"] == "en-US"
    assert cfg["channels"]["es"]["market"] == "es-419"
    assert cfg["channels"]["ar"]["market"] == "ar-SA"
    assert cfg["channels"]["ar"]["subs_align"] == "right-rtl"


def test_models_yaml_engine_routing_and_fallback():
    raw = yaml.safe_load((CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))
    routing = raw["routing"]
    assert routing["tts"]["en"][0] == "dub-tts" and routing["tts"]["ar"] == ["dub-tts", "alt-tts-b"]
    assert routing["mt"]["en"] == ["mt-core", "mt-api"]
    assert routing["align"]["ar"] == "align-proportional"  # 主对齐器无阿语 → 比例估算
    assert routing["lip"] == {"default": "none", "frontal_closeup": "lip-fast", "top10pct": "lip-pro"}

    comps = raw["components"]
    required = {"task", "langs", "device", "weights", "version", "fallback", "volta_status"}
    assert len(comps) >= 20
    for name, comp in comps.items():
        missing = required - set(comp)
        assert not missing, f"{name} 缺字段 {missing}"
        assert isinstance(comp["fallback"], list), name
        assert comp["volta_status"] in {"pending", "ok", "degraded", "fail", "na"}, name
        # Volta 无 bf16：任何组件不得配置 bf16
        assert comp.get("precision") != "bf16", name
    # 关键降级链
    assert comps["dub-tts"]["fallback"] == ["dub-tts-base", "alt-tts-a", "alt-tts-b"]
    assert comps["mt-core"]["fallback"] == ["mt-api"]
    assert comps["lip-pro"]["fallback"] == ["lip-pro-1.5", "lip-fast"]
    assert comps["align-core"]["fallback"] == ["align-proportional"]
    # 降级链引用的组件必须已登记
    names = set(comps)
    for name, comp in comps.items():
        for fb in comp["fallback"]:
            assert fb in names, f"{name} 降级到未登记组件 {fb}"
    # 路由引用的引擎必须已登记
    for chain in routing["tts"].values():
        for eng in chain:
            assert eng in names, f"routing.tts 引用未登记组件 {eng}"


def test_voices_yaml_template():
    raw = yaml.safe_load((CONFIG_DIR / "voices.yaml").read_text(encoding="utf-8"))
    d = raw["defaults"]
    assert d["engine"] == "dub-tts" and 0.0 <= d["emo_alpha_default"] <= 1.0
    cast = raw["casts"]["ep01"]["characters"]
    ch = cast["char_nan"]
    assert ch["voice_ref"].startswith("05_cast/voicebank/")
    assert ch["terms"]["en"] == "Master Cheng"
    lo, hi = d["ref_dur_s_range"]
    for char in cast.values():
        assert lo <= char["ref_dur_s"] <= hi


def test_jobs_dir_helper():
    assert jobs_dir() == Path(load_pipeline_config()["paths"]["jobs_dir"])


# ---------------------------------------------------------------------------
# 中性命名纪律（公开仓库不得出现上游项目名）
# ---------------------------------------------------------------------------

def _banned_tokens() -> list[str]:
    # 拼接构造，避免本测试文件自身包含被禁字符串；与 scripts/gate_b0.py::BANNED_TOKENS 同步。
    # B1 修订（2026-09-28）：每个词根同时禁 无分隔/下划线/连字符 三种写法
    # （上游 API 的蛇形命名如 forced _ aligner 同样不许出现在公开仓）。
    def sep3(*parts: str) -> list[str]:
        return ["".join(parts), "_".join(parts), "-".join(parts)]

    roots = [
        ("paddle", "ocr"), ("paddle", "paddle"), ("sense", "voice"), ("fun", "asr"),
        ("qw", "en"), ("index", "tts"), ("vox", "cpm"), ("hy-", "mt"),
        ("muse", "talk"), ("latent", "sync"), ("trans", "net"), ("light-", "asd"),
        ("3d-", "speaker"), ("pyan", "note"), ("audio", "seal"), ("c2pa", "tool"),
        ("wav2", "lip"), ("whis", "per"), ("audio-", "separator"),
        ("video-subtitle-", "remover"), ("flash", "attention"), ("vll", "m"),
        ("forced", "aligner"), ("content", "auth"), ("dub", "mt"), ("dem", "ucs"),
        ("media", "pipe"), ("cam", "++"),
    ]
    tokens = [v for parts in roots for v in sep3(*parts)]
    tokens.append("c2pa" + " toolchain")
    return tokens


def test_neutral_naming_discipline():
    repo_root = Path(__file__).resolve().parents[1]
    targets: list[Path] = []
    # B1 修订：扫描面扩到 gpu/、gpu-services/、scripts/、data/（docs/ 与
    # requirements.txt 是依赖安装记录，须用真实发行名，维持豁免——同 gate_b0 口径）
    for sub in ["pipeline", "configs", "tests", "gpu", "gpu-services", "scripts", "data"]:
        targets.extend(sorted((repo_root / sub).rglob("*")))
    targets.append(repo_root / "README.md")
    targets.append(repo_root / "conftest.py")
    banned = _banned_tokens()
    hits: list[str] = []
    for path in targets:
        if not path.is_file() or path.suffix not in {".py", ".yaml", ".yml", ".md",
                                                    ".json", ".sh", ".txt"}:
            continue
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for token in banned:
            if token in text:
                hits.append(f"{path.relative_to(repo_root)}: {token}")
    assert not hits, f"公开仓出现上游项目名:\n" + "\n".join(hits)


def test_expected_files_covers_all_layers():
    assert set(EXPECTED_FILES) == set(LAYERS)
    assert "utterances.jsonl" in EXPECTED_FILES["04_dial"]
    assert "characters.json" in EXPECTED_FILES["05_cast"]
