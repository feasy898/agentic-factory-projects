"""合成测评集生成器（M8 · T1.1）：政务文书语料 + 规则检测评测集 + seeded 文件夹具。

组成（均为代码，确定性可复现；人名/单位/职业语料与 PDF 写入库经
``config/synthetic_corpus.yaml`` 提供模块名、源码 importlib 动态加载）：

- :mod:`benchmark.generator.geo`        海南省/澄迈县行政区划与地址构件表；
- :mod:`benchmark.generator.numbers`    自研号码生成器：身份证(GB 11643 校验位)、
    统一社会信用代码(GB 32174 校验位)、银行卡(Luhn)、手机/座机/车牌/邮箱/IP/密钥/出生日期，
    区划取值域限定海南省、重点覆盖澄迈县(469023)；
- :mod:`benchmark.generator.personas`   合成人名/单位/职业（经配置动态加载）；
- :mod:`benchmark.generator.templates`  14 类槽位化政务文书模板；
- :mod:`benchmark.generator.perturb`    扰动器：全角/插空格分组/空行换行/部分打码/OCR 错字/分隔符变体；
- :mod:`benchmark.generator.cases`      rule_cases 评测集装配（含白名单负例与难负例）；
- :mod:`benchmark.generator.fixtures`   seeded docx/xlsx/pdf 夹具（各 5 份）；
- :mod:`benchmark.generator.build`      ``build_all(seed, outdir)`` 一键产出 + manifest。

CLI::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m benchmark.generator \\
        --seed 20260928 --outdir data

产出（data/ 按 .gitignore 约定不入库，seed 固定即可再生）::

    data/rule_cases.jsonl             检测评测集（≥300 条）
    data/cases/rule_cases.jsonl       同一字节的镜像（规则层 eval 约定路径）
    data/fixtures/*.{docx,xlsx,pdf}   seeded 夹具 5×3
    data/generation_manifest.json     清单：seed/规模分布/全部产物 sha256

rule_cases.jsonl 行 schema（每行一个 JSON 对象，键序固定）::

    {"id": "rc_0001", "template": "low_income_publicity", "grading": "detect",
     "text": "……", "perturbations": ["fullwidth", "ocr_context"],
     "expected": [ {"fid": "f_0001", "type": "ID_CARD", "subtype": null,
                    "start": 9, "end": 27, "raw": "…", "normalized": "…",
                    "confidence": 1.0, "whitelisted": false,
                    "action_hint": "MASK", "graded": true,
                    "rule_detectable": true} ] }

grading 语义（消费方 evals.m2_recognizers 的计分约定）：

- ``detect``     正例：expected 中 graded 且 rule_detectable 的 finding 必须被规则层
  命中（召回分母）；graded=false（值本身被打码/OCR 破坏）与 rule_detectable=false
  （人名/住址走 NER 层、工作秘密走词表可选项）不计入召回分母，命中算加分；
- ``whitelist``  白名单负例：值可被命中，但必须标记 whitelisted=true 或不产出
  finding；产出未带白名单标记的 finding 记为误报（whitelist FPR 分子）；
- ``reject``     难负例（校验位失败/长度越界/非法八元组等）：不应产出
  confidence=1.0 的同类 finding（精确率考核面，单列统计）。

span 为最终 text 上的 Python 切片语义 [start:end)；``raw`` 为扰动后的原文；
``normalized`` 满足唯一不变式：数字串类等 masking.normalize_value 已实装类别恒等
``masking.normalize_value(type, raw)``，DATE_BIRTH 恒为 ISO ``YYYY-MM-DD`` 目标值。

确定性契约：同 seed 两次 ``build_all`` 产出的全部文件字节级一致（manifest 含
sha256）；随机只经 ``random.Random(seed)`` 与按 seed 播种的 personas 实例，
夹具与评测集使用不同 salt，互不扰动消耗序。
"""
from __future__ import annotations

#: 默认随机种子（台账口径，评测集/夹具/manifest 全部由它派生）
DEFAULT_SEED = 20260928

__all__ = ["DEFAULT_SEED"]
