"""Agent 壳：LLM 客户端协议 + 错误归因 + 讲解生成 + 出题草稿与入库门。

测试只用 MockLLM（确定性）；运行时用 OpenAICompatClient（密钥只从环境变量读取）。
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional, Protocol

from .itembank import ItemBank
from .types import Item, Misconception


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...


class MockLLM:
    """确定性 mock：按 system 里给定的行为脚本回答，供测试与离线运行。"""

    def __init__(self, mode: str = "default") -> None:
        self.mode = mode
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.mode == "item_drafter":
            m = re.search(r"kp=(\S+).*?difficulty=([\d.]+)", user)
            kp = m.group(1) if m else "kp_unknown"
            diff = float(m.group(2)) if m else 0.5
            a, b = 3 + int(diff * 10), 5
            ans = a + b
            return json.dumps(
                {
                    "id": f"draft-{kp}-{int(diff*100)}",
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
    """OpenAI 兼容 chat/completions 客户端（bigmodel 等）。密钥只从环境变量读。"""

    def __init__(self, base_url: str, model: str, api_key_env: str = "XX_LLM_API_KEY") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env

    def complete(self, system: str, user: str) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise LLMError(f"env {self.api_key_env} not set")
        import httpx

        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
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
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"bad llm response: {e}")


# ---------- 确定性业务函数（不依赖具体 LLM 行为的部分都沉淀在这里） ----------

def attribute_error(
    item: Item,
    learner_answer: str,
    misconceptions: list[Misconception],
    client: LLMClient,
) -> Optional[str]:
    """把错误答案归因到误解模式。先做确定性签名匹配，签名未命中才问 LLM。"""
    if not learner_answer.strip():
        return None
    for mc in misconceptions:
        for sig in mc.signature:
            if sig and sig.strip() == learner_answer.strip():
                return mc.id
    prompt = (
        f"题目: {item.stem}\n正确答案: {item.answer}\n学生答案: {learner_answer}\n"
        f"候选误解:\n" + "\n".join(f"- {mc.id}: {mc.description}" for mc in misconceptions) +
        "\n只返回最匹配的误解 id，无法判断返回 NONE。"
    )
    out = client.complete("你是错因诊断助手。", prompt).strip()
    for mc in misconceptions:
        if mc.id in out:
            return mc.id
    return None


def explain_error(
    item: Item,
    learner_answer: str,
    hint: str,
    client: LLMClient,
) -> str:
    """生成错题讲解。hint 来自误解库（确定性），LLM 只负责展开成讲解文本。"""
    prompt = (
        f"题目: {item.stem}\n正确答案: {item.answer}\n学生答案: {learner_answer}\n"
        f"教学提示: {hint}\n"
        "请写 3-6 句讲解，先点破错误根源，再给一个同类小例子。不要直接报答案流程。"
    )
    out = client.complete("你是耐心的数学辅导老师，遵循教学对齐原则：引导而非代做。", prompt)
    return out if out.strip() else f"【讲解】{hint}"


def draft_item(client: LLMClient, kp_id: str, difficulty: float) -> dict:
    """让 LLM 起草一道题（返回 dict，不入库）。"""
    prompt = (
        f"为知识点 kp={kp_id} 出一道 difficulty={difficulty:.2f} 的题。"
        '返回 JSON: {"id","item_type","stem","answer","kps","difficulty","solution"}'
    )
    raw = client.complete("你是命题助手，输出严格 JSON。", prompt)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("draft is not JSON")
    data = json.loads(raw[start : end + 1])
    data.setdefault("kps", [kp_id])
    return data


def try_accept_draft(draft: dict, bank: ItemBank, valid_kp_ids: set[str]) -> tuple[bool, list[str]]:
    """入库门：草稿必须通过题库校验且不与现有题重复（同题干）才能入库。"""
    from .types import Item

    errs: list[str] = []
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
        return False, [f"malformed draft: {e}"]
    errs.extend(bank.validate_item(item))
    errs.extend(f"{item.id}: unknown kp {k}" for k in item.kps if k not in valid_kp_ids)
    for existing in bank.items():
        if existing.stem.strip() == item.stem.strip():
            errs.append(f"{item.id}: duplicate stem with {existing.id}")
            break
    if errs:
        return False, errs
    bank.add(item)
    return True, []
