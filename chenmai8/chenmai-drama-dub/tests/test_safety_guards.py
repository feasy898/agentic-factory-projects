"""路径安全守护测试（T6 提交时安全门禁要求的落点）。

覆盖两处统一关卡：
  1. ``pipeline.scaffold.ep_dir`` —— 集 ID 白名单（``--ep`` 是全管线工作区
     路径的来源组件，穿越只可能从这里进）；
  2. ``pipeline.contracts._atomic_write_lines`` —— 契约写盘唯一出口的
     ``..`` / NUL 显式把关（经 :func:`dump_jsonl` 间接驱动）。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from pipeline import contracts as C
from pipeline.scaffold import create_workspace, ep_dir


class _Row(BaseModel):
    """最小契约风格行（extra=forbid，同冻结基调）。"""

    model_config = ConfigDict(extra="forbid")
    utt_id: str


def test_ep_dir_rejects_traversal_and_bad_ids(tmp_path):
    for bad in ("../evil", "a/../b", "..", ".", "", "a/b", "a\\b", "/abs",
                "C:/tmp", ".hidden", None):
        with pytest.raises(ValueError):
            ep_dir(bad, tmp_path)  # type: ignore[arg-type]


def test_ep_dir_accepts_conventional_ids(tmp_path):
    for good in ("ep01", "epV", "ep-cli_1.2", "EP99"):
        d = ep_dir(good, tmp_path)
        assert d == tmp_path / good
        assert create_workspace(good, tmp_path)[0] == d


def test_dump_jsonl_rejects_nul_path(tmp_path):
    with pytest.raises(ValueError):
        C.dump_jsonl(tmp_path / "a\x00b.jsonl", [_Row(utt_id="u1")])


def test_dump_jsonl_canonicalizes_dotdot_before_write(tmp_path):
    """含 ``..`` 的路径被 resolve 规范化后落盘到真实位置（不落在字面目录里）。"""
    p = tmp_path / "sub" / ".." / "ok.jsonl"
    n = C.dump_jsonl(p, [_Row(utt_id="u1")])
    assert n == 1
    assert (tmp_path / "ok.jsonl").is_file()          # 规范化后的真实落点
    assert not (tmp_path / "sub" / "ok.jsonl").exists()  # 未按字面分量落盘


def test_dump_jsonl_normal_write_still_works(tmp_path):
    p = tmp_path / "sub" / "rows.jsonl"
    n = C.dump_jsonl(p, [_Row(utt_id="u1"), _Row(utt_id="u2")])
    assert n == 2 and p.is_file()
    rows = C.load_jsonl(p, _Row)
    assert [r.utt_id for r in rows] == ["u1", "u2"]
