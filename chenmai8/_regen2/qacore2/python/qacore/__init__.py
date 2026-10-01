"""qacore — 可玩广告产线唯一质检裁判。

重生成第二轮实现（从零，仅凭回炉后 spec：docs/assets/specs/qacore.md + 冻结夹具/gate）。
对单个 HTML 产物：本地伺服 → 无头浏览器手机仿真开两趟（竖屏/横屏）→ 拦截并记录全部网络请求
→ 采集事实（探针 + 截屏）→（--autoplay）经 __PF_QC__.hint() 真实指针事件驱动到结束页
→ 逐项判定 → 写 report.json + 截屏；任何 fail → exit 1。
"""

__version__ = "2.0.0"
