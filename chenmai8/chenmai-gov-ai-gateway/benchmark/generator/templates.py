"""槽位化政务文书模板（M8 · T1.1）：14 类文书 + 白名单/难负例小模板。

模板 = 常量文字 + 实体槽位（:class:`Slot`）的块序列（:class:`GenKit` 按固定
随机序填充）；扰动在 cases 装配阶段施加（perturb 模块），槽位值域见
numbers/geo/personas 模块。敏感属性/密级/工作秘密以**精确词槽位**表达
（span 即词面），供规则词表类识别器对照。
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from benchmark.generator import geo
from benchmark.generator import numbers as nums
from benchmark.generator.personas import Personas

#: 出生日期版式（digit 版式规则层可检；cn_full 中文数字版式为难度加分项）
DATE_FORMATS = ("iso", "cn", "slash", "dot", "cn_full")

_CN_DIGITS = "零一二三四五六七八九"


def _cn_num(n: int) -> str:
    """1-31 的中文数字（合成日期版式用）。"""
    if n <= 0:
        return "零"
    if n == 10:
        return "十"
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + _CN_DIGITS[n - 10]
    tens, ones = divmod(n, 10)
    return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")


@dataclass
class Slot:
    """实体槽位：value 为干净值（扰动前）；meta 记白名单/层级/ISO 目标。"""

    etype: str                       # EntityClass 值，如 "ID_CARD"
    value: str
    subtype: str | None = None
    whitelisted: bool = False
    action_hint: str = "MASK"
    rule_detectable: bool = True     # 人名/住址=NER 层、工作秘密=词表可选 → False
    wl_kind: str = ""                # 白名单类别（hotline/emergency/doc_number/unit_landline/title_only）
    iso: str | None = None           # DATE_BIRTH 的 ISO 目标值
    note: str = ""


Chunk = tuple[str, "Slot | None"]


class GenKit:
    """槽位工厂：持有确定性随机源与语料提供器，模板按固定顺序取用。"""

    def __init__(self, rng: random.Random, personas: Personas) -> None:
        self.rng = rng
        self.personas = personas

    # ── 文字构件 ──────────────────────────────────────────────────
    def county_office(self) -> str:
        return "澄迈县" + self.rng.choice(geo.COUNTY_OFFICES)

    def town(self) -> str:
        return self.rng.choice(geo.CHENGMAI_TOWNS) if self.rng.random() < 0.7 else (
            "澄迈县" + self.rng.choice(geo.CHENGMAI_TOWNS))

    # ── 实体槽位 ──────────────────────────────────────────────────
    def id_card(self) -> Slot:
        region, _ = nums.pick_region(self.rng)
        return Slot("ID_CARD", nums.gen_id_card(self.rng, region, nums.gen_birth(self.rng)))

    def person(self) -> Slot:
        return Slot("PERSON", self.personas.person_name(), rule_detectable=False)

    def address(self) -> Slot:
        region, name = nums.pick_region(self.rng)
        town = self.rng.choice(geo.CHENGMAI_TOWNS) if region == geo.CHENGMAI_CODE else (
            self.rng.choice(geo.GENERAL_TOWNS))
        road = self.rng.choice(geo.ROADS)
        no = self.rng.randrange(1, 300)
        return Slot("ADDRESS", f"海南省{name}{town}{road}{no}号", rule_detectable=False)

    def mobile(self) -> Slot:
        return Slot("PHONE_MOBILE", nums.gen_mobile(self.rng))

    def landline(self) -> Slot:
        return Slot("PHONE_LANDLINE", nums.gen_landline(self.rng))

    def unit_landline(self) -> Slot:
        return Slot("PHONE_LANDLINE", nums.gen_landline(self.rng, unit=True,
                                                         prefix=geo.UNIT_LANDLINE_PREFIX),
                    whitelisted=True, wl_kind="unit_landline")

    def bank(self) -> tuple[Slot, str]:
        card, bank = nums.gen_bank_card(self.rng)
        return Slot("BANK_CARD", card, note=bank), bank

    def uscc(self) -> Slot:
        region, _ = nums.pick_region(self.rng)
        return Slot("USCC", nums.gen_uscc(self.rng, region))

    def plate(self) -> Slot:
        return Slot("PLATE", nums.gen_plate(self.rng))

    def email(self) -> Slot:
        return Slot("EMAIL", nums.gen_email(self.rng))

    def ipv4(self) -> Slot:
        return Slot("IP", nums.gen_ipv4(self.rng))

    def secret_key(self) -> Slot:
        return Slot("SECRET_KEY", nums.gen_secret_key(self.rng))

    def birth(self, *, force_fmt: str | None = None) -> Slot:
        d = nums.gen_birth(self.rng)
        fmt = force_fmt or self.rng.choice(DATE_FORMATS)
        iso = f"{d:%Y-%m-%d}"
        y, m, day = d.year, d.month, d.day
        if fmt == "iso":
            text = iso
        elif fmt == "cn":
            text = f"{y}年{m}月{day}日"
        elif fmt == "slash":
            text = f"{y}/{m:02d}/{day:02d}"
        elif fmt == "dot":
            text = f"{y}.{m:02d}.{day:02d}"
        else:  # cn_full 中文数字
            text = f"{_cn_year(y)}年{_cn_num(m)}月{_cn_num(day)}日"
        return Slot("DATE_BIRTH", text, iso=iso, rule_detectable=(fmt != "cn_full"))

    def date_plain(self, *, lo: int = 2023, hi: int = 2026) -> str:
        return f"{self.rng.randrange(lo, hi + 1)}-{self.rng.randrange(1, 13):02d}-{self.rng.randrange(1, 29):02d}"

    def amount(self) -> str:
        return nums.gen_amount(self.rng)

    def doc_number(self) -> Slot:
        org = self.rng.choice(geo.DOC_NUMBER_ORG_CODES)
        year = self.rng.randrange(2023, 2027)
        n = self.rng.randrange(1, 200)
        return Slot("DOC_NUMBER", f"{org}〔{year}〕{n}号", whitelisted=True,
                    wl_kind="doc_number")

    def sensitive(self, subtype: str, term: str) -> Slot:
        return Slot("SENSITIVE_ATTR", term, subtype=subtype, action_hint="ROUTE_FLAG")

    def classification(self, term: str) -> Slot:
        return Slot("CLASSIFICATION_MARK", term, action_hint="BLOCK_FLAG")

    def work_secret(self, term: str) -> Slot:
        return Slot("WORK_SECRET", term, action_hint="ROUTE_FLAG", rule_detectable=False)

    # ── 难负例坏值 ────────────────────────────────────────────────
    def bad_id_card(self) -> str:
        region, _ = nums.pick_region(self.rng)
        while True:
            bad = list(nums.gen_id_card(self.rng, region, nums.gen_birth(self.rng)))
            pos = self.rng.randrange(0, 17)
            bad[pos] = self.rng.choice("0123456789")
            s = "".join(bad)
            if not nums.id_card_is_valid(s):
                return s

    def bad_bank_card(self) -> str:
        while True:
            s = "".join(self.rng.choice("0123456789") for _ in range(16))
            if not nums.bank_card_is_valid(s):
                return s

    def bad_uscc(self) -> str:
        region, _ = nums.pick_region(self.rng)
        while True:
            s = list(nums.gen_uscc(self.rng, region))
            pos = self.rng.randrange(0, 18)
            s[pos] = self.rng.choice("0123456789ABCDEFGHJKLMNPQRTUWXY")
            t = "".join(s)
            if not nums.uscc_is_valid(t):
                return t

    def bad_phone_len(self) -> str:
        return "1" + "".join(self.rng.choice("0123456789") for _ in range(11))

    def bad_ipv4(self) -> str:
        return f"{self.rng.choice((10, 192, 172))}.{self.rng.randrange(1, 255)}.0.{self.rng.randrange(256, 1000)}"


def _cn_year(y: int) -> str:
    return "".join(_CN_DIGITS[int(d)] for d in str(y))


# ── 14 类政务文书模板 ─────────────────────────────────────────────────
# 模板函数签名统一 (kit: GenKit) -> list[Chunk]；"\n" 块为行分隔。


def t_low_income_publicity(kit: GenKit) -> list[Chunk]:
    """低保公示：批量身份证 + 银行卡 + 低保特困敏感属性。"""
    person = kit.person()
    ident, addr, mobile = kit.id_card(), kit.address(), kit.mobile()
    bank_slot, bank_name = kit.bank()
    low = kit.sensitive("低保特困", kit.rng.choice(("低保对象", "低保户", "特困供养人员")))
    contact = kit.person()
    return [
        (f"{kit.town()}2026年第三批", None), ("\n", None),
        ("最低生活保障对象名单公示：经户主申请、村级评议、县级审核，下列家庭拟纳入", None),
        (low.value, low), ("。", None), ("\n", None),
        ("户主：", None), (person.value, person),
        ("，公民身份号码：", None), (ident.value, ident),
        ("；家庭住址：", None), (addr.value, addr), ("。", None), ("\n", None),
        ("补助金按月发放至其银行账户（", None), (bank_slot.value, bank_slot),
        (f"，{bank_name}）。", None), ("\n", None),
        ("公示期7日，异议请向", None), (kit.county_office(), None),
        ("反映，联系人：", None), (contact.value, contact),
        ("，电话：", None), (mobile.value, mobile), ("。", None), ("\n", None),
        (f"发布日期：{kit.date_plain()}", None),
    ]


def t_petition_transfer(kit: GenKit) -> list[Chunk]:
    """信访转办单：信访人敏感属性 + 身份证 + 手机 + 文号。"""
    num, person = kit.doc_number(), kit.person()
    xf, ident = kit.sensitive("信访人", "信访人"), kit.id_card()
    addr, mobile = kit.address(), kit.mobile()
    chunks: list[Chunk] = [
        ("信访事项转办单（", None), (num.value, num), ("）", None), ("\n", None),
        (person.value, person), ("（", None), (xf.value, xf), ("），反映", None),
        (f"{kit.town()}{kit.rng.choice(('征地补偿', '村道硬化', '饮水安全', '宅基地纠纷'))}问题。", None),
        ("\n", None),
        ("身份证号：", None), (ident.value, ident), ("；联系电话：", None),
        (mobile.value, mobile), ("；居住地址：", None), (addr.value, addr), ("。", None), ("\n", None),
    ]
    if kit.rng.random() < 0.5:
        cm = kit.classification(kit.rng.choice(("内部资料 注意保密", "不得外传")))
        chunks += [("本单", None), (cm.value, cm), ("，办理过程注意保护", None),
                   (xf.value, xf), ("个人信息。", None), ("\n", None)]
    chunks += [
        ("转办要求：请", None), (kit.county_office(), None),
        (f"于{kit.date_plain()}前核查处理并反馈。", None),
    ]
    return chunks


def t_administrative_penalty(kit: GenKit) -> list[Chunk]:
    """行政处罚决定书：身份证 + 住址 + 车牌 + 犯罪记录 + 文号。"""
    num, person = kit.doc_number(), kit.person()
    ident, addr = kit.id_card(), kit.address()
    mobile, plate = kit.mobile(), kit.plate()
    record = kit.sensitive("犯罪记录", "犯罪记录")
    return [
        ("行政处罚决定书（", None), (num.value, num), ("）", None), ("\n", None),
        ("当事人：", None), (person.value, person),
        ("，公民身份号码：", None), (ident.value, ident),
        ("，住址：", None), (addr.value, addr),
        ("，联系电话：", None), (mobile.value, mobile), ("。", None), ("\n", None),
        (f"经查：{kit.date_plain()}，当事人驾驶车辆（号牌：", None), (plate.value, plate),
        ("）在澄迈县境内从事未取得经营许可的营运活动。", None), ("\n", None),
        ("调查核实，当事人此前存在", None), (record.value, record),
        ("，依法从重处罚。", None), ("\n", None),
        (f"处罚内容：罚款人民币{kit.amount()}元，于{kit.date_plain()}前缴纳。", None),
    ]


def t_medical_reimburse(kit: GenKit) -> list[Chunk]:
    """医保报销回执：病症 + 金融账户 + 银行卡 + 身份证。"""
    person, ident = kit.person(), kit.id_card()
    illness = kit.sensitive("病症", kit.rng.choice(("尿毒症", "恶性肿瘤", "严重糖尿病")))
    amount, acct = kit.amount(), kit.sensitive("金融账户", "银行账户")
    bank_slot, bank_name = kit.bank()
    clerk = kit.person()
    return [
        ("基本医疗保险费用报销回执", None), ("\n", None),
        ("参保人：", None), (person.value, person),
        ("，公民身份号码：", None), (ident.value, ident),
        ("。就诊医院：澄迈县人民医院。", None), ("\n", None),
        ("临床诊断：", None), (illness.value, illness),
        (f"，门诊治疗费用合计人民币{amount}元。", None), ("\n", None),
        ("报销款已拨付至其", None), (acct.value, acct),
        ("（", None), (bank_slot.value, bank_slot), (f"，{bank_name}）。", None), ("\n", None),
        ("经办人：", None), (clerk.value, clerk),
        (f"　经办日期：{kit.date_plain()}", None),
    ]


def t_disability_subsidy(kit: GenKit) -> list[Chunk]:
    """残疾人补贴审批表：残障 + 银行卡 + 金融账户 + 信用代码。"""
    person, ident = kit.person(), kit.id_card()
    disabled = kit.sensitive("残障", kit.rng.choice(("肢体残疾人", "听力残疾人", "视力残疾人")))
    bank_slot, bank_name = kit.bank()
    acct, amount = kit.sensitive("金融账户", "银行账户"), kit.amount()
    addr, mobile = kit.address(), kit.mobile()
    agency, uscc = kit.personas.company_name(), kit.uscc()
    return [
        ("困难残疾人补贴审批表", None), ("\n", None),
        ("申请人：", None), (person.value, person),
        ("，公民身份号码：", None), (ident.value, ident),
        ("，属", None), (disabled.value, disabled), ("。", None), ("\n", None),
        ("补贴按月发放至其", None), (acct.value, acct), ("（", None),
        (bank_slot.value, bank_slot), (f"，{bank_name}），标准为每月{amount}元。", None),
        ("\n", None),
        ("户籍地址：", None), (addr.value, addr), ("；联系电话：", None),
        (mobile.value, mobile), ("。", None), ("\n", None),
        ("服务机构：", None), (agency, None), ("（统一社会信用代码：", None),
        (uscc.value, uscc), ("）。", None),
    ]


def t_community_correction(kit: GenKit) -> list[Chunk]:
    """社区矫正宣告书：社区矫正敏感属性 + 座机（规则可检正例）。"""
    person, ident = kit.person(), kit.id_card()
    corr = kit.sensitive("社区矫正", "社区矫正对象")
    months, landline = kit.rng.randrange(3, 25), kit.landline()
    addr = kit.address()
    announcer = kit.person()
    return [
        ("社区矫正宣告书", None), ("\n", None),
        ("矫正对象：", None), (person.value, person),
        ("，公民身份号码：", None), (ident.value, ident), ("。", None), ("\n", None),
        ("依法将其列入", None), (corr.value, corr),
        (f"管理，矫正期{months}个月，自宣告之日起至{kit.date_plain()}止。", None),
        ("\n", None),
        ("司法所联系电话：", None), (landline.value, landline),
        ("；居住地：", None), (addr.value, addr), ("。", None), ("\n", None),
        ("宣告人：", None), (announcer.value, announcer),
        ("（司法所工作人员）", None),
    ]


def t_cadre_assessment(kit: GenKit) -> list[Chunk]:
    """干部考察材料：出生日期 + 工作秘密（词表可选）。"""
    person, birth = kit.person(), kit.birth()
    title = kit.rng.choice(geo.TITLES)
    ws = kit.work_secret(kit.rng.choice(("未公开人事任免", "未公开的干部考察情况")))
    p2, p3 = kit.person(), kit.person()
    return [
        ("干部考察材料", None), ("\n", None),
        (person.value, person), ("，", None),
        (kit.rng.choice(("男", "女")), None), ("，", None),
        (birth.value, birth), ("出生，汉族，海南", None),
        (kit.rng.choice(geo.HAINAN_COUNTIES)[1], None),
        (f"人，{kit.rng.randrange(1995, 2023)}年参加工作。", None), ("\n", None),
        ("现任", None), (kit.county_office(), None), (f"{title}。", None), ("\n", None),
        ("考察组认为：该同志……（材料涉及", None), (ws.value, ws),
        ("事项，知悉范围按有关规定控制。）", None), ("\n", None),
        ("考察组成员：", None), (p2.value, p2), ("、", None), (p3.value, p3),
        (f"。{kit.date_plain()}", None),
    ]


def t_talent_publicity(kit: GenKit) -> list[Chunk]:
    """人才引进公示：出生日期 + 邮箱 + 信用代码。"""
    person, birth = kit.person(), kit.birth()
    agency, uscc = kit.personas.company_name(), kit.uscc()
    email, mobile = kit.email(), kit.mobile()
    return [
        ("年度人才引进拟聘用人员公示", None), ("\n", None),
        (person.value, person), ("，", None), (birth.value, birth),
        (f"出生，拟引进至{agency}（统一社会信用代码：", None), (uscc.value, uscc), ("）。", None),
        ("\n", None),
        ("联系方式：电子邮箱 ", None), (email.value, email), ("；移动电话 ", None),
        (mobile.value, mobile), ("。", None), ("\n", None),
        (f"公示期：{kit.date_plain()} 至 {kit.date_plain()}。", None),
    ]


def t_business_registration(kit: GenKit) -> list[Chunk]:
    """企业开办登记：信用代码 + 住址 + 法定代表人 + 座机/邮箱。"""
    agency = kit.personas.company_name()
    uscc, addr = kit.uscc(), kit.address()
    legal, landline, email = kit.person(), kit.landline(), kit.email()
    return [
        ("企业开办登记通知书", None), ("\n", None), (agency, None), ("：", None), ("\n", None),
        ("你单位提交的设立登记申请材料齐全，准予登记。统一社会信用代码：", None),
        (uscc.value, uscc), ("。", None), ("\n", None),
        ("住所：", None), (addr.value, addr), ("。法定代表人：", None),
        (legal.value, legal), ("。", None), ("\n", None),
        ("联系电话：", None), (landline.value, landline), ("；电子邮箱：", None),
        (email.value, email), ("。", None),
    ]


def t_security_incident_report(kit: GenKit) -> list[Chunk]:
    """网络安全事件报告：密钥 + IP + 邮箱 + 手机。"""
    day, clerk = kit.date_plain(), kit.person()
    secret, ip = kit.secret_key(), kit.ipv4()
    owner, email, mobile = kit.person(), kit.email(), kit.mobile()
    return [
        ("网络安全事件报告", None), ("\n", None),
        (f"{day}，运维人员", None), (clerk.value, clerk),
        ("巡查发现：测试环境配置文件泄露一枚访问密钥（", None),
        (secret.value, secret), ("）。", None), ("\n", None),
        ("异常访问源地址为 ", None), (ip.value, ip),
        ("，已临时封禁。", None), ("\n", None),
        ("已联系系统责任人", None), (owner.value, owner),
        ("（电子邮箱 ", None), (email.value, email),
        ("，手机 ", None), (mobile.value, mobile),
        ("）完成密钥轮换，初步判断未造成数据外泄。", None),
    ]


def t_meeting_minutes(kit: GenKit) -> list[Chunk]:
    """会议纪要：人名/职务 + 工作秘密 + 单位座机（白名单）+ 密级字样。"""
    office = kit.county_office()
    chair, title = kit.person(), kit.rng.choice(geo.TITLES)
    ws = kit.work_secret(kit.rng.choice(("未公开人事任免", "内部议题", "未公开的干部考察情况")))
    unit_phone = kit.unit_landline()
    cm = kit.classification(kit.rng.choice(("内部资料 注意保密", "不得外传", "秘密★")))
    p2, p3 = kit.person(), kit.person()
    return [
        (f"{office}党组会议纪要", None), ("\n", None),
        (f"时间：{kit.date_plain()}上午；地点：机关三楼会议室。", None), ("\n", None),
        ("主持：", None), (chair.value, chair), (f"（{title}）；列席：", None),
        (p2.value, p2), ("、", None), (p3.value, p3), ("。", None), ("\n", None),
        ("议题：一是研究", None), (ws.value, ws), ("事项；二是部署汛期值班工作。", None),
        ("\n", None),
        ("会务联系电话：", None), (unit_phone.value, unit_phone),
        ("（办公室总机）。", None), ("\n", None),
        ("（本纪要", None), (cm.value, cm), ("，按规定存档。）", None),
    ]


def t_procurement_notice(kit: GenKit) -> list[Chunk]:
    """采购公告：信用代码 + 文号/单位座机（白名单）+ 邮箱。"""
    num = kit.doc_number()
    office, agency = kit.county_office(), kit.personas.company_name()
    uscc, addr = kit.uscc(), kit.address()
    contact, unit_phone, email = kit.person(), kit.unit_landline(), kit.email()
    return [
        ("政府采购项目公告（", None), (num.value, num), ("）", None), ("\n", None),
        (f"采购人：{office}；代理机构：{agency}（统一社会信用代码：", None),
        (uscc.value, uscc), ("）。", None), ("\n", None),
        (f"投标人须于{kit.date_plain()}前将投标文件送达：", None),
        (addr.value, addr), ("。", None), ("\n", None),
        ("联系人：", None), (contact.value, contact), ("；电话：", None),
        (unit_phone.value, unit_phone), ("；电子邮箱：", None),
        (email.value, email), ("。", None),
    ]


def t_hotline_workorder(kit: GenKit) -> list[Chunk]:
    """12345 工单：手机 + 住址 + 热线（隐性白名单负例）。"""
    caller, mobile = kit.person(), kit.mobile()
    matter = kit.rng.choice(("小区路灯损坏多日未修", "村道路面破损影响出行",
                             "农贸市场周边占道经营", "公交车班次少群众候车时间长"))
    return [
        ("12345政务服务便民热线工单", None), ("\n", None),
        ("来电人：", None), (caller.value, caller), ("；联系电话：", None),
        (mobile.value, mobile), ("。", None), ("\n", None),
        (f"来电反映：{kit.town()}{matter}，请核实处理。", None), ("\n", None),
        ("承办单位：", None), (kit.county_office(), None),
        (f"，办理时限：{kit.date_plain()}。", None), ("\n", None),
        ("回访提示：来电人可拨打12345查询办理进度。", None),
    ]


def t_key_personnel_visit(kit: GenKit) -> list[Chunk]:
    """重点人员走访记录：特定身份 + 行踪轨迹 + 车牌 + 手机。"""
    person = kit.person()
    identity = kit.sensitive("特定身份", kit.rng.choice(("涉军优抚对象", "退役军人")))
    mobile = kit.mobile()
    day, addr = kit.date_plain(), kit.address()
    trail, plate = kit.sensitive("行踪轨迹", "活动轨迹"), kit.plate()
    visitor = kit.person()
    return [
        ("重点人员走访记录", None), ("\n", None),
        ("走访对象：", None), (person.value, person), ("（", None),
        (identity.value, identity), ("）；联系电话：", None),
        (mobile.value, mobile), ("。", None), ("\n", None),
        (f"{day}在", None), (addr.value, addr),
        ("上门走访；近期", None), (trail.value, trail),
        ("：主要在住所与镇区之间往返。", None), ("\n", None),
        ("家属车辆号牌：", None), (plate.value, plate), ("。", None), ("\n", None),
        ("走访人：", None), (visitor.value, visitor),
    ]


#: 模板注册表（名称 → 构建器；顺序即产出顺序，勿重排以免破坏 seed 对齐）
DOC_TEMPLATES: dict[str, object] = {
    "low_income_publicity": t_low_income_publicity,
    "petition_transfer": t_petition_transfer,
    "administrative_penalty": t_administrative_penalty,
    "medical_reimburse": t_medical_reimburse,
    "disability_subsidy": t_disability_subsidy,
    "community_correction": t_community_correction,
    "cadre_assessment": t_cadre_assessment,
    "talent_publicity": t_talent_publicity,
    "business_registration": t_business_registration,
    "security_incident_report": t_security_incident_report,
    "meeting_minutes": t_meeting_minutes,
    "procurement_notice": t_procurement_notice,
    "hotline_workorder": t_hotline_workorder,
    "key_personnel_visit": t_key_personnel_visit,
}


# ── 白名单负例小模板（grading=whitelist）──────────────────────────────


def w_hotline(kit: GenKit) -> list[Chunk]:
    return [("便民服务提示：涉及政务咨询、投诉建议，请拨打12345政务服务便民热线，"
             "或登录县政府门户网站留言板反映。", None)]


def w_emergency(kit: GenKit) -> list[Chunk]:
    return [("安全提示：火情请拨119，伤病急救请拨120，治安报警请拨110，"
             "道路交通事故请拨122，水上遇险搜救请拨12395。", None)]


def w_doc_number(kit: GenKit) -> list[Chunk]:
    num = kit.doc_number()
    return [("根据", None), (num.value, num), ("文件要求，各镇、各单位认真做好汛期值班"
             "和信息报送工作，遇突发情况按规定及时上报。特此通告。", None)]


def w_unit_landline(kit: GenKit) -> list[Chunk]:
    phone = kit.unit_landline()
    return [("县政务服务中心办事指南：不动产登记、社保征缴等业务实行一窗受理，"
             "咨询请拨打总机 ", None), (phone.value, phone),
            ("（工作日 8:30-17:30）。", None)]


def w_title_only(kit: GenKit) -> list[Chunk]:
    return [(f"{kit.rng.choice(geo.LEADER_TITLES)}带队督查{kit.town()}安全生产"
             "工作，县应急管理局、消防救援大队负责同志参加。", None)]


WHITELIST_TEMPLATES: dict[str, object] = {
    "wl_hotline": w_hotline,
    "wl_emergency": w_emergency,
    "wl_doc_number": w_doc_number,
    "wl_unit_landline": w_unit_landline,
    "wl_title_only": w_title_only,
}


# ── 难负例小模板（grading=reject；expected 恒空，探测值记入 reject_probe）──


def r_bad_id(kit: GenKit) -> tuple[list[Chunk], dict[str, str]]:
    bad = kit.bad_id_card()
    return [("信息核对：系统内登记号码 ", None), (bad, None),
            (" 与证件影像不一致，请经办人核实后再行录入。", None)], {"type": "ID_CARD", "raw": bad}


def r_bad_bank(kit: GenKit) -> tuple[list[Chunk], dict[str, str]]:
    bad = kit.bad_bank_card()
    return [("对账说明：补贴代发回盘失败，卡号 ", None), (bad, None),
            (" 无法入账，请与户主核对开户信息后重新报盘。", None)], {"type": "BANK_CARD", "raw": bad}


def r_bad_uscc(kit: GenKit) -> tuple[list[Chunk], dict[str, str]]:
    bad = kit.bad_uscc()
    return [("名录校验：该单位登记代码 ", None), (bad, None),
            (" 未通过校验，暂缓公示，待登记机关更正。", None)], {"type": "USCC", "raw": bad}


def r_bad_phone_len(kit: GenKit) -> tuple[list[Chunk], dict[str, str]]:
    bad = kit.bad_phone_len()
    return [("回访记录：按登记号码 ", None), (bad, None),
            (" 回拨时提示空号，已改用其他方式联系。", None)], {"type": "PHONE_MOBILE", "raw": bad}


def r_bad_ip(kit: GenKit) -> tuple[list[Chunk], dict[str, str]]:
    bad = kit.bad_ipv4()
    return [("日志核查：记录中的来源地址 ", None), (bad, None),
            (" 为非法取值，判定为设备时钟错乱导致的记录异常。", None)], {"type": "IP", "raw": bad}


REJECT_TEMPLATES: dict[str, object] = {
    "r_bad_id": r_bad_id,
    "r_bad_bank": r_bad_bank,
    "r_bad_uscc": r_bad_uscc,
    "r_bad_phone_len": r_bad_phone_len,
    "r_bad_ip": r_bad_ip,
}
