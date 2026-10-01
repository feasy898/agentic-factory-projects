"""政务问答对合成生成器（M8 · T7.1 回答质量评测素材）：上下文 × 问题 × 参考答案。

与 ``rule_cases``（检测评测集）同源不同用途：问答对面向「脱敏前后回答质量
对比」——每对 = 一段含 seeded 结构化信息的合成政务材料（上下文）+ 一个可从
材料唯一作答的问题 + 确定性参考答案。

确定性纪律（与 cases.py 同款）：seed 固定 → 逐字节可复现；槽位按固定类配额
循环填充，随机流只在 :class:`GenKit` 内消费（builder 抽槽顺序固定）。

问题七类（脱敏面 × 作答机制覆盖）：

- ``cite_id`` / ``cite_phone`` / ``cite_bank`` / ``cite_birth``：引用被脱敏的
  结构化值——脱敏腿上游只见占位符，答案经还原须回到原值（可逆脱敏端到端主探针）；
- ``count_ids``：批量枚举计数（批量名单 → 政务云路由腿）；
- ``cite_sensitive``：敏感属性词面引用（ROUTE_FLAG 词不脱敏、政务云路由腿）；
- ``plain_amount``：非 PII 数值理解锚点（脱敏零影响面的对照腿）。

书写守则（生成器自检 ``validate_pairs`` 的前置条件）：

- 人名/机构/地名的右邻必须是标点或非汉字字符（规则层人名启发式的匹配边界）；
  问题文本不出现人名（用「来电人/申请人/当事人」等角色词指称）；
- 上下文不含密级词/注入指令（不得触发 403）；出生日期槽位左邻必须是「出生日期：」
  （规则层 DATE_BIRTH 上下文门控）；
- 参考答案一律取干净规范写法（槽位原值），与脱敏还原目标值（normalized）一致。
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from benchmark.generator import numbers as nums
from benchmark.generator.personas import Personas
from benchmark.generator.templates import GenKit

#: 质量评测集默认 seed（同 seed 逐字节可复现）
QA_SEED = 20260929
#: 默认问答对数（§6 M8：≥50）
QA_PAIRS = 50

#: 问题类别轮转计划（按序循环填充任意 n；n ≥ 类数即全覆盖，n=50 时 8/7/7/7/7/7/7）
QA_KIND_PLAN: tuple[str, ...] = (
    "cite_id",
    "cite_phone",
    "cite_bank",
    "cite_birth",
    "count_ids",
    "cite_sensitive",
    "plain_amount",
)

#: 临床诊断词面（与 templates.py 医保模板同源词域）
_ILLNESSES = ("尿毒症", "恶性肿瘤", "严重糖尿病")

#: 素材守则：问答对的人名必须落在规则层人名启发式覆盖域（常见单字姓 + 2-3 字
#: 全名）。此表与识别器侧姓氏域为同一契约的两份声明——素材生成按此守则重抽，
#: eval 侧再以真实检测面独立复核（seeded 值未被 MASK 即响亮失败），漂移不静默。
_COVERED_SURNAMES = frozenset(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何林罗高郑梁谢宋唐许韩冯邓曹彭曾肖田董潘"
    "袁蔡蒋余于杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦"
    "邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤"
)


def _covered_person(kit: GenKit):
    """抽人名并重抽至覆盖域内（守则见上；64 次上限为确定性硬失败护栏）。"""
    for _ in range(64):
        slot = kit.person()
        if len(slot.value) in (2, 3) and slot.value[0] in _COVERED_SURNAMES:
            return slot
    raise RuntimeError("person draw exhausted: no heuristic-covered name in 64 draws")


@dataclass
class QAPair:
    """一条问答对：上下文/问题/参考答案 + 脱敏断言面（seeded 值清单）。"""

    qid: str
    kind: str
    context: str
    question: str
    reference: str
    #: 参与脱敏断言的 seeded 值 (EntityClass 值, 原值)——bytes 级零上游命中断言面
    seeded: list[tuple[str, str]]
    #: 预期路由（信息性：断言网关路由符合 §5.2 决策矩阵）
    expect_route: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["seeded"] = [list(x) for x in self.seeded]
        return d


# ── 上下文构件（所有槽值右邻保持标点/非汉字，见模块 docstring 守则）──────


def _ctx_cite_id(kit: GenKit) -> tuple[str, str, str, list[tuple[str, str]]]:
    """12345 工单：引用来电人身份证号。"""
    person, ident, mobile = _covered_person(kit), kit.id_card(), kit.mobile()
    context = (
        "12345政务服务便民热线工单\n"
        f"来电人：{person.value}，公民身份号码：{ident.value}，"
        f"联系电话：{mobile.value}。\n"
        "来电内容：咨询城乡居民养老保险待遇发放事宜，请求核实参保状态。\n"
        f"承办单位：澄迈县{kit.rng.choice(('社会保险服务中心', '政务服务局'))}；"
        f"办理时限：{kit.date_plain()}前答复。"
    )
    question = "材料中来电人的公民身份号码是什么？（只答号码本身）"
    seeded = [("PERSON", person.value), ("ID_CARD", ident.value),
              ("PHONE_MOBILE", mobile.value)]
    return context, question, ident.value, seeded


def _ctx_cite_phone(kit: GenKit) -> tuple[str, str, str, list[tuple[str, str]]]:
    """低保申领回访：引用申请人联系电话。"""
    person, ident, mobile = _covered_person(kit), kit.id_card(), kit.mobile()
    context = (
        "低保申领回访登记表\n"
        f"申请人：{person.value}，公民身份号码：{ident.value}。\n"
        f"回访联系电话：{mobile.value}；回访时间：{kit.date_plain()}。\n"
        "回访事项：核对家庭收入与共同生活成员情况。"
    )
    question = "材料中申请人的联系电话是多少？（只答号码本身）"
    seeded = [("PERSON", person.value), ("ID_CARD", ident.value),
              ("PHONE_MOBILE", mobile.value)]
    return context, question, mobile.value, seeded


def _ctx_cite_bank(kit: GenKit) -> tuple[str, str, str, list[tuple[str, str]]]:
    """补贴发放凭证：引用发放银行账号。"""
    person, ident = _covered_person(kit), kit.id_card()
    bank_slot, bank_name = kit.bank()
    context = (
        "困难群众补贴发放凭证\n"
        f"发放对象：{person.value}，公民身份号码：{ident.value}。\n"
        f"补贴款项已发放至其银行账户（{bank_slot.value}，{bank_name}）。\n"
        f"经办单位：澄迈县民政局；发放日期：{kit.date_plain()}。"
    )
    question = "材料中补贴款项发放到的银行账号是多少？（只答账号本身）"
    seeded = [("PERSON", person.value), ("ID_CARD", ident.value),
              ("BANK_CARD", bank_slot.value)]
    return context, question, bank_slot.value, seeded


def _ctx_cite_birth(kit: GenKit) -> tuple[str, str, str, list[tuple[str, str]]]:
    """待遇资格认证：引用当事人出生日期（DATE_BIRTH 上下文门控：左邻「出生日期：」）。"""
    person, ident = _covered_person(kit), kit.id_card()
    birth = kit.birth(force_fmt="iso")
    context = (
        "退休待遇资格认证表\n"
        f"当事人：{person.value}，出生日期：{birth.value}，"
        f"公民身份号码：{ident.value}。\n"
        f"认证结果：通过；认证单位：澄迈县人力资源和社会保障局；"
        f"认证日期：{kit.date_plain()}。"
    )
    question = "材料中当事人的出生日期是什么？（按材料中的写法回答）"
    seeded = [("PERSON", person.value), ("DATE_BIRTH", birth.value),
              ("ID_CARD", ident.value)]
    return context, question, birth.value, seeded


def _ctx_count_ids(kit: GenKit) -> tuple[str, str, str, list[tuple[str, str]]]:
    """低保名单公示：批量身份证计数（批量名单 → 政务云路由腿）。"""
    mobile = kit.mobile()
    people = [(_covered_person(kit), kit.id_card()) for _ in range(3)]
    lines = [f"{i}. 户主：{p.value}，公民身份号码：{c.value}；"
             for i, (p, c) in enumerate(people, start=1)]
    context = (
        f"澄迈县{kit.rng.choice(('金江镇', '老城镇', '瑞溪镇', '永发镇'))}辖区"
        "2026年第二季度低保对象名单公示\n"
        "经村级评议、县级审核，下列家庭拟纳入最低生活保障：\n"
        + "\n".join(lines) + "\n"
        f"公示期7日，异议请向澄迈县民政局反映；联系电话：{mobile.value}。"
    )
    question = "材料中「公民身份号码：」字段一共出现了几次？（只答数字）"
    seeded = ([("PERSON", p.value) for p, _ in people]
              + [("ID_CARD", c.value) for _, c in people]
              + [("PHONE_MOBILE", mobile.value)])
    return context, question, "3", seeded


def _ctx_cite_sensitive(kit: GenKit) -> tuple[str, str, str, list[tuple[str, str]]]:
    """医保报销回执：引用临床诊断（敏感属性词面 ROUTE_FLAG 不脱敏 → 政务云路由腿）。"""
    person, ident = _covered_person(kit), kit.id_card()
    illness = kit.rng.choice(_ILLNESSES)
    amount, bank_slot = kit.amount(), kit.bank()[0]
    clerk = _covered_person(kit)
    context = (
        "基本医疗保险费用报销回执\n"
        f"参保人：{person.value}，公民身份号码：{ident.value}。\n"
        f"临床诊断：{illness}；门诊治疗费用合计人民币{amount}元。\n"
        f"报销款已拨付至其银行账户（{bank_slot.value}）。\n"
        f"经办人：{clerk.value}；经办日期：{kit.date_plain()}。"
    )
    question = "材料中参保人的临床诊断是什么？（按材料原样回答）"
    seeded = [("PERSON", person.value), ("ID_CARD", ident.value),
              ("BANK_CARD", bank_slot.value), ("PERSON", clerk.value)]
    return context, question, illness, seeded


def _ctx_plain_amount(kit: GenKit) -> tuple[str, str, str, list[tuple[str, str]]]:
    """处罚决定书：引用罚款金额（非 PII 数值锚点，脱敏零影响面对照腿）。"""
    person, ident, plate = _covered_person(kit), kit.id_card(), kit.plate()
    amount = kit.amount()
    context = (
        "行政处罚决定书\n"
        f"当事人：{person.value}，公民身份号码：{ident.value}。\n"
        f"经查：当事人驾驶车辆（号牌：{plate.value}）在澄迈县境内从事未取得"
        "经营许可的营运活动。\n"
        f"处罚内容：罚款人民币{amount}元，于{kit.date_plain()}前缴纳。\n"
        "决定机关：澄迈县交通运输局"
    )
    question = "材料中罚款金额是多少元？（只答数字）"
    seeded = [("PERSON", person.value), ("ID_CARD", ident.value),
              ("PLATE", plate.value)]
    return context, question, amount, seeded


#: 类别 → builder（键即 QAKind 配额计划的类别名）
BUILDERS = {
    "cite_id": _ctx_cite_id,
    "cite_phone": _ctx_cite_phone,
    "cite_bank": _ctx_cite_bank,
    "cite_birth": _ctx_cite_birth,
    "count_ids": _ctx_count_ids,
    "cite_sensitive": _ctx_cite_sensitive,
    "plain_amount": _ctx_plain_amount,
}

#: 各类别的预期路由（§5.2 决策矩阵；以真实决策矩阵在 eval 侧逐对复核）：
#: cite_bank 上下文含「银行账户」（金融账户敏感属性 ROUTE_FLAG）→ GOVCLOUD；
#: cite_sensitive 命中病症敏感属性 → GOVCLOUD；count_ids 批量身份证 ≥3 → GOVCLOUD；
#: 其余单结构化 PII → INTERNET。
EXPECT_ROUTE = {
    "cite_id": "INTERNET",
    "cite_phone": "INTERNET",
    "cite_bank": "GOVCLOUD",
    "cite_birth": "INTERNET",
    "count_ids": "GOVCLOUD",
    "cite_sensitive": "GOVCLOUD",
    "plain_amount": "INTERNET",
}


def _expand_plan(n: int) -> list[str]:
    """类别轮转计划循环填充到 n 个槽（保持计划内顺序，确定性；n≥类数即全覆盖）。"""
    plan = list(QA_KIND_PLAN)
    if not plan:  # pragma: no cover — 计划恒非空
        raise ValueError("QA_KIND_PLAN is empty")
    return [plan[i % len(plan)] for i in range(n)]


def build_qa_pairs(seed: int = QA_SEED, n: int = QA_PAIRS,
                   config_path: str | None = None) -> list[QAPair]:
    """按固定配额循环产出 n 条问答对（同 seed 逐字节可复现）。"""
    rng = random.Random(seed)
    kit = GenKit(rng, Personas(seed, config_path))
    pairs: list[QAPair] = []
    for i, kind in enumerate(_expand_plan(n), start=1):
        context, question, reference, seeded = BUILDERS[kind](kit)
        pairs.append(QAPair(
            qid=f"qa_{i:04d}", kind=kind, context=context, question=question,
            reference=reference, seeded=seeded, expect_route=EXPECT_ROUTE[kind],
        ))
    return pairs


def pairs_bytes(pairs: list[QAPair]) -> bytes:
    """确定性序列化（eval 双跑字节级复现断言对象）。"""
    import json

    return "".join(
        json.dumps(p.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for p in pairs).encode("utf-8")


def checksum_ok(etype: str, value: str) -> bool:
    """seeded 结构化值的独立合法性复核（与识别器实现无关的 eval 侧复核）。"""
    if etype == "ID_CARD":
        return nums.id_card_is_valid(value)
    if etype == "BANK_CARD":
        return nums.bank_card_is_valid(value)
    if etype == "PHONE_MOBILE":
        return len(value) == 11 and value.startswith("1") and value[1] in "3456789"
    if etype == "PLATE":
        return 7 <= len(value) <= 8
    if etype == "DATE_BIRTH":
        return len(value) == 10 and value[4] == "-" and value[7] == "-"
    return bool(value)  # PERSON：词面非空即可（启发式边界由 validate_pairs 保证）
