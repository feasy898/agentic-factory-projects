"""Agent 壳（重生成终版实现）——契约来源 specs/frozen/agent_shell.spec.md。

把 LLM 调用与确定性业务逻辑分离：client 经 LLMClient 协议注入，四个业务函数
（错因归因 / 错题讲解 / 出题草稿 / 草稿入库门）本身确定：不读时钟、不用 random、
不做 IO（OpenAICompatClient 是唯一网络豁免，且不在契约测试覆盖内）。

bank 参数按结构使用（duck typing），只依赖 validate_item(item) -> list[str]、
items() -> list[Item]、add(item) -> None 三个方法；按规格 §2，不 import 任何
题库模块。
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional, Protocol

from xuexing.types import Item, Misconception

__all__ = [
    "LLMError",
    "LLMClient",
    "MockLLM",
    "OpenAICompatClient",
    "attribute_error",
    "explain_error",
    "draft_item",
    "try_accept_draft",
]


class LLMError(RuntimeError):
    """LLM 相关失败：草稿非 JSON、生产客户端密钥缺失 / HTTP 失败 / 响应形状错。"""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class MockLLM:
    """确定性 mock：complete 是 (mode, system, user) 的纯函数（追加 calls 记录除外）。

    calls 每次按 (system, user) 顺序追加一条。
    """

    def __init__(self, mode: str = "default") -> None:
        self.mode = mode
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.mode == "item_drafter":
            m = re.search(r"kp=(\S+).*?difficulty=([\d.]+)", user)
            if m:
                kp = m.group(1)
                diff = float(m.group(2))
            else:
                kp = "kp_unknown"
                diff = 0.5
            a = 3 + int(diff * 10)
            b = 5
            ans = a + b
            return json.dumps(
                {
                    "id": f"draft-{kp}-{int(diff * 100)}",
                    "item_type": "fill",
                    "stem": f"计算：{a} + {b} = ?",
                    "answer": str(ans),
                    "kps": [kp],
                    "difficulty": diff,
                    "solution": f"{a} + {b} = {ans}",
                },
                ensure_ascii=False,
            )
        if self.mode == "explainer":
            m = re.search(r"教学提示:\s*(.+)$", user, re.M)
            hint = m.group(1).strip() if m else "回顾基础概念"
            return f"【讲解】{hint} 我们一步步来看这道题……"
        return "OK"


class OpenAICompatClient:
    """OpenAI 兼容生产客户端（§3.4 [仅参考]：无契约测试覆盖，行为不冻结）。"""

    def __init__(self, base_url: str, model: str, api_key_env: str = "XX_LLM_API_KEY") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env

    def complete(self, system: str, user: str) -> str:
        import httpx  # 延迟 import：契约测试路径不触网

        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise LLMError(f"env {self.api_key_env} not set")
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60.0,
        )
        if resp.status_code != 200:
            raise LLMError(f"llm http {resp.status_code}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"bad llm response: {e}") from e


_SYSTEM_ATTRIBUTION = "你是错因诊断助手。"
_SYSTEM_EXPLAIN = "你是耐心的数学辅导老师，遵循教学对齐原则：引导而非代做。"
_SYSTEM_DRAFT = "你是数学出题助手，只输出一个 JSON 对象。"


def attribute_error(
    item: Item,
    learner_answer: str,
    misconceptions: list[Misconception],
    client: LLMClient,
) -> Optional[str]:
    """错因归因：确定性签名匹配优先（免 LLM），未命中恰好一次 LLM 兜底。"""
    answer = learner_answer.strip()
    if not answer:
        return None  # I1：空答案不归因，不调 LLM
    for mc in misconceptions:  # I2：列表序 / 组内签名序，两侧 strip
        for sig in mc.signature:
            if sig.strip() and sig.strip() == answer:
                return mc.id
    candidates = "\n".join(f"- {mc.id}: {mc.description}" for mc in misconceptions)
    user = (
        f"题目: {item.stem}\n"
        f"正确答案: {item.answer}\n"
        f"学生答案: {learner_answer}\n"
        f"候选误解:\n"
        f"{candidates}\n"
        "只返回最匹配的误解 id，无法判断返回 NONE。"
    )
    reply = client.complete(_SYSTEM_ATTRIBUTION, user).strip()  # I3：恰好一次
    for mc in misconceptions:
        if mc.id in reply:
            return mc.id
    return None


def explain_error(item: Item, learner_answer: str, hint: str, client: LLMClient) -> str:
    """错题讲解：hint 确定性来自误解库，LLM 只展开。

    冻结耦合：user 中存在恰为 `教学提示: {hint}` 的行（半角冒号 + 半角空格）。
    """
    user = (
        f"题目: {item.stem}\n"
        f"学生答案: {learner_answer}\n"
        f"正确答案: {item.answer}\n"
        f"教学提示: {hint}\n"
        "请基于教学提示展开讲解，引导而非代做。"
    )
    reply = client.complete(_SYSTEM_EXPLAIN, user)  # 不做空答案特判，恒走 LLM
    if reply.strip():
        return reply
    return f"【讲解】{hint}"


def draft_item(client: LLMClient, kp_id: str, difficulty: float) -> dict:
    """出题草稿：返回解析后的 dict，绝不入库。

    冻结耦合：user 中 `kp={kp_id}` 与 `difficulty={difficulty:.2f}` 同行、kp 在前，
    满足自验谓词 re.search(r"kp=(\\S+).*?difficulty=([\\d.]+)", user) 且
    group(1) == kp_id、float(group(2)) == difficulty。
    """
    user = (
        f"请起草一道题，参数同行如下：kp={kp_id} difficulty={difficulty:.2f}\n"
        "只返回一个 JSON 对象，不要附加说明。"
    )
    raw = client.complete(_SYSTEM_DRAFT, user)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("draft is not JSON")
    parsed = json.loads(raw[start : end + 1])  # 非法 JSON：JSONDecodeError 原样冒泡
    parsed.setdefault("kps", [kp_id])  # 已有键（含空列表）不覆盖
    return parsed


def try_accept_draft(draft: dict, bank, valid_kp_ids: set[str]) -> tuple[bool, list[str]]:
    """草稿入库门：校验 + 查重 + 原子入库，全有或全无。

    步骤 1 字段收敛是唯一短路出口（TypeError/ValueError -> malformed draft）；
    步骤 2/3/4 收集式、无条件依序执行、错误累积；零错误才 bank.add。
    """
    try:
        item = Item(
            id=str(draft.get("id", "")),
            item_type=str(draft.get("item_type", "")),
            stem=str(draft.get("stem", "")),
            answer=str(draft.get("answer", "")),
            kps=[str(k) for k in draft.get("kps", [])],
            difficulty=float(draft.get("difficulty", -1)),
            solution=str(draft.get("solution", "")),
        )
    except (TypeError, ValueError) as e:
        return (False, [f"malformed draft: {e}"])

    errs: list[str] = []
    errs.extend(bank.validate_item(item))  # 题库校验错误原样透传
    for k in item.kps:  # 按 kps 顺序逐个
        if k not in valid_kp_ids:
            errs.append(f"{item.id}: unknown kp {k}")
    for existing in bank.items():  # id 升序，取第一条同题干即停（两侧 strip）
        if existing.stem.strip() == item.stem.strip():
            errs.append(f"{item.id}: duplicate stem with {existing.id}")
            break

    if errs:
        return (False, errs)
    bank.add(item)
    return (True, [])
