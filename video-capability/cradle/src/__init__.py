"""PROJECT CRADLE — 营销视频生成管线。

层级: L0触发 → L1叙事模板 → L2镜头卡 → L3资产 → L4生成 → L5六道门禁 → L6程序合成
纯 Python 3.12; 仅依赖 pyyaml/numpy/Pillow (+可选 diffusers/open_clip/edge-tts/whisper, 均 lazy import)。
"""

__version__ = "0.2.0"
