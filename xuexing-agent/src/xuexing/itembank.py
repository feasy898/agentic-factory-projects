"""题库：题目存储、校验（Q-matrix 引用完整性、选项/答案一致性）。"""
from __future__ import annotations

import json
from typing import Optional

from .types import Item


class ItemBankError(ValueError):
    pass


class ItemBank:
    def __init__(self) -> None:
        self._items: dict[str, Item] = {}

    def add(self, item: Item) -> None:
        if item.id in self._items:
            raise ItemBankError(f"duplicate item id: {item.id}")
        self._items[item.id] = item

    def get(self, item_id: str) -> Optional[Item]:
        return self._items.get(item_id)

    def has(self, item_id: str) -> bool:
        return item_id in self._items

    def items(self) -> list[Item]:
        return [self._items[k] for k in sorted(self._items)]

    def by_kp(self, kp_id: str, primary_only: bool = False) -> list[Item]:
        out = []
        for it in self.items():
            if kp_id in it.kps and (not primary_only or (it.kps and it.kps[0] == kp_id)):
                out.append(it)
        return out

    def validate_item(self, item: Item) -> list[str]:
        errs: list[str] = []
        if not item.id:
            errs.append("missing id")
        if item.item_type not in ("choice", "fill", "solve"):
            errs.append(f"{item.id}: bad item_type {item.item_type!r}")
        if not item.stem.strip():
            errs.append(f"{item.id}: empty stem")
        if not item.answer.strip():
            errs.append(f"{item.id}: empty answer")
        if not item.kps:
            errs.append(f"{item.id}: no kp tags")
        if not 0.0 <= item.difficulty <= 1.0:
            errs.append(f"{item.id}: difficulty out of [0,1]")
        if not 0.0 <= item.discrimination <= 1.0:
            errs.append(f"{item.id}: discrimination out of [0,1]")
        if item.guess is not None and not 0.0 <= item.guess <= 1.0:
            errs.append(f"{item.id}: guess out of [0,1]")
        if item.item_type == "choice":
            if len(item.options) < 2:
                errs.append(f"{item.id}: choice needs >=2 options")
            else:
                # 答案既可以是完整选项文本，也可以是选项标号（"B" 匹配 "B. -2/3"）
                labels = [o.strip().split(".")[0].strip() for o in item.options]
                texts = [o.strip() for o in item.options]
                if item.answer.strip() not in labels and item.answer.strip() not in texts:
                    errs.append(f"{item.id}: answer not among options")
            if len(set(o.strip() for o in item.options)) != len(item.options):
                errs.append(f"{item.id}: duplicate options")
        return errs

    def validate_all(self, valid_kp_ids: Optional[set[str]] = None) -> list[str]:
        errs: list[str] = []
        for it in self.items():
            errs.extend(self.validate_item(it))
            if valid_kp_ids is not None:
                for k in it.kps:
                    if k not in valid_kp_ids:
                        errs.append(f"{it.id}: unknown kp {k}")
        return sorted(set(errs))


def load_itembank(path: str) -> ItemBank:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return itembank_from_dict(data)


def itembank_from_dict(data: dict) -> ItemBank:
    bank = ItemBank()
    for it in data["items"]:
        bank.add(
            Item(
                id=it["id"],
                item_type=it["item_type"],
                stem=it["stem"],
                answer=str(it["answer"]),
                kps=list(it["kps"]),
                difficulty=float(it["difficulty"]),
                solution=it.get("solution", ""),
                options=list(it.get("options", [])),
                discrimination=float(it.get("discrimination", 0.6)),
                guess=it.get("guess"),
                misconceptions=list(it.get("misconceptions", [])),
            )
        )
    return bank
