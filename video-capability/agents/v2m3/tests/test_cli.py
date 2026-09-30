"""CLI 测试: initdb / ingest / status / run --once / report, 隔离 CRADLE_ROOT。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli import main
from src.db import DB
from tests.conftest import write_json
from tests.test_orchestrator import _card


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "templates" / "shotcards").mkdir(parents=True)
    monkeypatch.setenv("CRADLE_ROOT", str(tmp_path))
    return tmp_path


def _card_file(root: Path) -> Path:
    card = _card("S01", "n1")
    return write_json(root / "templates" / "shotcards" / "S01.json", card)


def test_initdb(root):
    code = main(["initdb"])
    assert code == 0
    assert (root / "workdir" / "cradle.sqlite3").exists()


def test_ingest_valid_and_invalid(root, capsys):
    f = _card_file(root)
    assert main(["ingest", str(f), "--template", "t_mini"]) == 0
    out = capsys.readouterr().out
    assert "S01" in out and "1 成功" in out

    db = DB(root / "workdir" / "cradle.sqlite3")
    t = db.get_task("S01")
    assert t["status"] == "pending" and t["template"] == "t_mini"
    assert json.loads(t["card_json"])["shot_id"] == "S01"
    db.close()


def test_ingest_rejects_invalid_card(root, capsys):
    card = _card("S99", "n1")
    card.pop("negative")
    f = write_json(root / "bad.json", card)
    code = main(["ingest", str(f)])
    assert code == 2
    assert "拒绝" in capsys.readouterr().err


def test_ingest_directory(root):
    _card_file(root)
    code = main(["ingest", str(root / "templates" / "shotcards"), "--template", "t_mini"])
    assert code == 0


def test_status_counts(root, capsys):
    f = _card_file(root)
    main(["ingest", str(f)])
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "pending" in out and "total" in out


def test_run_once_blocks_on_missing_asset(root, capsys):
    f = _card_file(root)  # asset=assets/x.png 不存在
    main(["ingest", str(f)])
    capsys.readouterr()
    assert main(["run", "--once"]) == 0
    db = DB(root / "workdir" / "cradle.sqlite3")
    t = db.get_task("S01")
    db.close()
    assert t["status"] == "blocked"


def test_report_json(root, capsys):
    f = _card_file(root)
    main(["ingest", str(f)])
    main(["run", "--once"])
    capsys.readouterr()
    assert main(["report"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tasks_total"] == 1
    assert report["by_status"]["blocked"] == 1
    assert report["yield_with_fallback_rate"] == 0.0
    assert report["blocked_reasons"][0]["shot_id"] == "S01"


def test_report_out_file(root, capsys, tmp_path):
    f = _card_file(root)
    main(["ingest", str(f)])
    capsys.readouterr()
    out = tmp_path / "r.json"
    main(["report", "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["tasks_total"] == 1


def test_ingest_full_shotcard_set(root):
    """真实 12 张镜头卡可被 ingest(在服务器生成后)。"""
    cards_dir = Path(__file__).resolve().parents[1] / "templates" / "shotcards"
    files = sorted(cards_dir.glob("*.json"))
    if len(files) < 12:
        pytest.skip("镜头卡尚未生成(服务器上由 tools/gen_shotcards.py 生成)")
    code = main(["ingest", str(cards_dir), "--template", "product_seeding_25s"])
    assert code == 0
