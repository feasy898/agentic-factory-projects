"""BeanEye · M12 合成数据引擎（beaneye.synth，W12a-lite + W12b）。

程序化豆素材（无外部数据集路径：素材来自程序化生成 + 未来生豆自采，
协议见 ``docs/collect_protocol.md``，自建集 HN-Robusta 为数据主叙事）：

- :mod:`beaneye.synth.beans` —— W12a-lite 程序化素材：taxonomy 13 类参数
  画像（长/宽/长宽比/CIE L\\*a\\*b\\* 颜色范围/轮廓波纹/虫孔/斑块/弦切/
  空腔弧/纵皱纹形态算子）→ 每类 ≥20 固定变体素材库 → 单粒 sprite 渲染
  （alpha 即真值轮廓）；
- :mod:`beaneye.synth.compose` —— W12b 铺盘合成器：随机铺盘（数量/接触/
  重叠/旋转/光照扰动/阴影/亚克力反光简化）→ 成对 top/bottom 整盘图
  （四角 ArUco，M3 标定直接可用）→ 逐粒真值标注（多边形 mm + 托盘 mm
  网格 COCO RLE）+ 标准 YAML 输入格式的 batch manifest；
- :mod:`beaneye.synth.config` —— configs/synth.yaml 严格加载/校验/回写。

确定性：素材库种子与盘种子共同决定全部输出；同种子图像逐像素一致、
labels JSON 字节级一致。

用法（仓库根）::

    from beaneye.synth import compose_tray, write_batch

    tray = compose_tray(seed=42)
    paths = write_batch(tray, "data/synth/demo", index=1)
"""

from beaneye.synth.beans import (
    CLASS_PROFILES,
    BeanSpec,
    Sprite,
    SynthBeanError,
    bean_polygon_mm,
    lab8_to_bgr,
    render_sprite,
    sample_library,
    sample_spec,
)
from beaneye.synth.compose import (
    BeanPlacement,
    SynthComposeError,
    SynthTray,
    compose_tray,
    labels_to_json,
    rasterize_poly_mm,
    rle_decode,
    rle_encode,
    write_batch,
)
from beaneye.synth.config import (
    DEFAULT_SYNTH_CONFIG_PATH,
    ComposeConfig,
    SynthConfigError,
    config_to_dict,
    load_compose_config,
)

__all__ = [
    # W12a-lite 程序化素材
    "CLASS_PROFILES",
    "BeanSpec",
    "Sprite",
    "SynthBeanError",
    "bean_polygon_mm",
    "lab8_to_bgr",
    "render_sprite",
    "sample_library",
    "sample_spec",
    # W12b 铺盘合成器
    "BeanPlacement",
    "SynthComposeError",
    "SynthTray",
    "compose_tray",
    "labels_to_json",
    "rasterize_poly_mm",
    "rle_encode",
    "rle_decode",
    "write_batch",
    # 配置（标准 YAML 输入格式）
    "DEFAULT_SYNTH_CONFIG_PATH",
    "ComposeConfig",
    "SynthConfigError",
    "config_to_dict",
    "load_compose_config",
]
