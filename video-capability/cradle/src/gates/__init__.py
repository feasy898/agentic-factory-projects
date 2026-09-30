"""六道门禁包 (SPECS §5.4)。每道门禁输出结构化 dict: {gate, passed, score, detail}。"""

from __future__ import annotations

GATE_IDS = ("G1", "G2", "G3", "G4", "G5", "G6")


def all_passed(gates: dict) -> bool:
    return all(bool(gates[g]["passed"]) for g in GATE_IDS if g in gates)


def make_gate(gate: str, passed: bool, score: float, **detail) -> dict:
    return {"gate": gate, "passed": bool(passed), "score": float(score), "detail": detail}
