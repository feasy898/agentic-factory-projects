"""演示场景材料物化 CLI（T4.3）：场景夹具 → data/fixtures/materials/。

用法::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m ops.demo.build_fixtures

产物（幂等；双构建字节级一致自证后写盘）：

- 场景2 三路由材料 ×3（ordinary/roster = docx，classified = pdf 文本层）；
- 场景4 防注入网页存档 ×2（webpage_policy_qa_clean/injected = docx）+
  预物化聊天请求体 ``scene4_request_clean.json`` / ``scene4_request_injected.json``
  （聊天页 T5.2 上线前的 curl 驱动体；content = 文件正文抽取面，与网关检测面
  同一文本）；
- 场景5 合成扫描件 ``scan_lowincome_publicity_demo.pdf``（绘图文字 → 纯图像
  PDF，零文本层，时间戳冻结确定性）。

与 webui 演示入口（GET /webui/demo/materials/{filename}）同源：该路由按需调用
同一构建器（:mod:`benchmark.generator.materials`），无需预跑本 CLI。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.generator.materials import (  # noqa: E402
    CLASSIFIED_MATERIAL,
    DEMO_SCAN_FILENAME,
    ORDINARY_MATERIAL,
    ROSTER_MATERIAL,
    WEBPAGE_CLEAN_MATERIAL,
    WEBPAGE_INJECTED_MATERIAL,
    build_demo_scan,
    build_materials,
    material_plain_text,
)

OUT_DIR = REPO_ROOT / "data" / "fixtures" / "materials"

#: 场景4 预物化聊天请求体（/v1/chat/completions 的 body；content = 文件正文）
_SCENE4_REQUESTS = (
    ("scene4_request_clean.json", WEBPAGE_CLEAN_MATERIAL),
    ("scene4_request_injected.json", WEBPAGE_INJECTED_MATERIAL),
)

_LABELS = {
    ORDINARY_MATERIAL.filename: "场景2 材料① 普通公文（→INTERNET 逐字原文）",
    ROSTER_MATERIAL.filename: "场景2 材料② 低保名单（→GOVCLOUD 全量脱敏）",
    CLASSIFIED_MATERIAL.filename: "场景2 材料③ 机密纪要（→BLOCK 403）",
    WEBPAGE_CLEAN_MATERIAL.filename: "场景4 材料 干净版网页存档（→INTERNET）",
    WEBPAGE_INJECTED_MATERIAL.filename: "场景4 材料 埋注版网页存档（→403 INJECTION）",
    DEMO_SCAN_FILENAME: "场景5 材料 合成扫描件（体检 HIGH → 重打码导出）",
}


def main() -> int:
    first = build_materials(OUT_DIR)
    second = build_materials(OUT_DIR)
    if [e["sha256"] for e in first] != [e["sha256"] for e in second]:
        print("FAIL: materials not byte-deterministic")
        return 1
    entries: list[dict] = list(first)
    scan = build_demo_scan(OUT_DIR)
    if scan["sha256"] != build_demo_scan(OUT_DIR)["sha256"]:
        print("FAIL: demo scan not byte-deterministic")
        return 1
    entries.append(scan)

    # 场景4 预物化请求体（content = 材料正文抽取面预测，与网关见到的文本同源）
    for req_name, spec in _SCENE4_REQUESTS:
        body = {"model": "mock-chat", "stream": False,
                "messages": [{"role": "user",
                              "content": material_plain_text(spec)}]}
        (OUT_DIR / req_name).write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"演示场景材料就绪: {OUT_DIR}")
    for entry in entries:
        label = _LABELS.get(entry["filename"], "")
        print(f"  {entry['filename']:42s} {entry['kind']:8s} "
              f"{entry['sha256'][:12]}  {label}")
    for req_name, _spec in _SCENE4_REQUESTS:
        print(f"  {req_name:42s} {'json':8s} {'—':12s}  场景4 curl 请求体")
    return 0


if __name__ == "__main__":
    sys.exit(main())
