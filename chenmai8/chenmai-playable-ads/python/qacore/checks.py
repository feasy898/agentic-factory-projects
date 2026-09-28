"""检查项定义（M8 规划十项）。

雏形阶段判定状态取值：pass / fail / skip。
- pass/fail：由本次无头打开过程真实测得；
- skip：雏形尚未实装（或依赖 M12 渠道规则库），不做任何假定结论。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Check:
    id: str
    name: str
    status: str  # pass | fail | skip
    detail: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail}


def skip(id_: str, name: str, detail: str) -> Check:
    return Check(id=id_, name=name, status="skip", detail=detail)


def evaluate(
    artifact_bytes: int,
    channel: str,
    external_requests: list[str],
    console_errors: list[str],
    load_ms: float,
    max_load_sec: float,
) -> list[Check]:
    """根据本次打开过程采集到的事实逐项判定（雏形只判 CHK03/08/09）。"""
    checks: list[Check] = []

    checks.append(skip("CHK01", "包体大小 ≤ 渠道上限",
                       f"当前 {artifact_bytes} 字节；channel-rules 渠道上限库（M12）未建，雏形不判定"))
    checks.append(skip("CHK02", "文件数 ≤ 渠道上限", "雏形未实装（单 HTML 输入，无目录清点）"))

    if external_requests:
        shown = "；".join(external_requests[:5])
        more = f"（另 {len(external_requests) - 5} 条略）" if len(external_requests) > 5 else ""
        checks.append(Check("CHK03", "零外网请求", "fail",
                            f"发现 {len(external_requests)} 条非本机请求，已拦截：{shown}{more}"))
    else:
        checks.append(Check("CHK03", "零外网请求", "pass", "全部请求均指向本地伺服地址，无外网请求"))

    checks.append(skip("CHK04", "首交互前静音", "雏形未实装（未注入静音断言）"))
    checks.append(skip("CHK05", "横竖屏渲染非空白", "雏形仅截取竖屏 390x844 一张，未做像素方差判定"))
    checks.append(skip("CHK06", "渠道退出接口调用", "雏形未实装（未注入渠道 stub）"))
    checks.append(skip("CHK07", "自动试玩到结束页", "雏形未实装（未驱动试玩）"))

    if console_errors:
        shown = " | ".join(console_errors[:3])
        more = f"（另 {len(console_errors) - 3} 条略）" if len(console_errors) > 3 else ""
        checks.append(Check("CHK08", "控制台零错误", "fail",
                            f"{len(console_errors)} 条 error/pageerror：{shown}{more}"))
    else:
        checks.append(Check("CHK08", "控制台零错误", "pass", "无 console error 与 pageerror"))

    if load_ms <= max_load_sec * 1000:
        checks.append(Check("CHK09", f"本地加载 ≤{max_load_sec:g}s", "pass",
                            f"load 耗时 {load_ms:.0f}ms"))
    else:
        checks.append(Check("CHK09", f"本地加载 ≤{max_load_sec:g}s", "fail",
                            f"load 耗时 {load_ms:.0f}ms 超过阈值 {max_load_sec * 1000:.0f}ms"))

    checks.append(skip("CHK10", "多语言与 RTL", "雏形未实装（channel 仅透传，未做 locale 仿真）"))
    return checks
