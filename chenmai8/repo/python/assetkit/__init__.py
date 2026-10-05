"""assetkit —— 素材处理流水线（M5）。

四项能力（规划 §6-M5）：
- 压图：经本仓 devDependency 内的 Node 图像库（sharp）多编码竞标——有损 WebP /
  近无损 WebP / 调色板量化 PNG / 常规 PNG，取最小者；压缩不过原图则保留原图
  （永不增大）。
- 音频：ffmpeg 转低码率 AAC（.m4a，播放器兼容面最广）；ffmpeg 不可用或转码
  失败时保留原始并如实记录（不阻塞流水线）。
- 字体子集：fontTools 按 PlayableSpec i18n.strings 字符集（外加数字，供得分
  显示）子集化，woff2（有 brotli 时）/ woff / ttf 输出。
- 图集：自研 shelf（next-fit 递减高）装箱，合成单张图集 + atlas.json 帧表。

输入：文件/目录参数，以及 --spec 声明的素材（assets.sprites / background /
audio / fontSubset，存在者才收，路径解析次序与模板构建脚本一致：spec 目录优先，
仓库根兜底）。

输出（--out 目录，整体重建）：
- 优化后素材（平面文件名，冲突自动加序号）
- ``asset-optmap.json``：键（spec 声明的相对路径串或绝对路径）→ 优化产物，
  供模板构建脚本经环境变量 ``PF_ASSET_OPTMAP`` 接线（命中即内联优化产物，
  未命中回退原素材，构建行为可预期）
- ``report.json``：逐素材原始/优化字节数、编码与告警，汇总降幅；``--min-reduction``
  可作硬门（不达标 exit 1）。

验收（规划 §6-M5 + T2.3 自验收）：
    python -m assetkit selftest                       # 合成素材端到端
    python -m assetkit run <素材目录|文件...> --out build/x --spec <spec.json>
    python -m pfcore make --spec specs-eval/demo-zh.json   # 默认启用素材管线
"""

ASSETKIT_VERSION = "1.0.0"

OPTMAP_NAME = "asset-optmap.json"
REPORT_NAME = "report.json"


class AssetkitError(Exception):
    """带退出码语义的素材管线失败：1=处理失败，2=用法/环境错误。"""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code
