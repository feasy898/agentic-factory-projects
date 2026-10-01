# face_samples — 口部估计样本集（D1 版，真机样本后补）

供 `cs_mouth` eval（`python -m cs_mouth.eval`）与导入脚本使用。**所有真人图片均来自
NASA 影像库（公版 / public domain，NASA Media Usage Guidelines 允许再分发，与本系统
无任何背书关系）**；程序合成帧由 `cs_mouth.synth` 生成，无真人成分。

## 目录结构

```
seeds/      5 张公版真人种子（入库，最大边 900px）
bundled/    种子的确定性变体帧（cs_mouth.bootstrap 自动生成，入库）
labels.json 全部标注帧清单（bundled 自动生成；clips 由导入脚本合并）
clips/      主人后补的手机视频/静帧导入产物（导入脚本写入）
face_demo_carousel.mp4  bundled/*.jpg 合成的内置演示视频（240 帧 @10fps，
            每帧驻留 0.6s；demo_mouth.py 无摄像头时的缺省输入源，见 §再生成）
```

## 内置演示视频再生成（face_demo_carousel.mp4）

派生资产：源头是 `bundled/*.jpg`。重采样本后可再生成（依赖 opencv）：

```bash
python - <<'PY'
import cv2, glob
from pathlib import Path
files = sorted(glob.glob("assets/face_samples/bundled/*.jpg"))
out = Path("assets/face_samples/face_demo_carousel.mp4")
w, h, fps, hold = 720, 900, 10, 6
vw = cv2.VideoWriter(str(out), cv2.VideoWriter.fourcc(*"mp4v"), fps, (w, h))
for f in files:
    img = cv2.imread(f)
    if img.shape[:2] != (h, w):
        img = cv2.resize(img, (w, h))
    for _ in range(hold):
        vw.write(img)
vw.release()
PY
```

## 种子来源（NASA Image and Video Library，2026-09-28 获取）

| 文件 | 图像 ID | 内容 | 标签 |
|---|---|---|---|
| `seed_closed_peake.jpg` | `jsc2013e079278` | 正面微笑、闭嘴 | jaw=closed, turn=false |
| `seed_open_cardman.jpg` | `iss073e0658307` | 大笑、嘴大张 | jaw=open, turn=false |
| `seed_open_williams.jpg` | `iss072e189112` | 开口笑 | jaw=open, turn=false |
| `seed_turn_adenot.jpg` | `iss074e0604606`（裁剪左） | 侧头仰视（实测 yaw≈+35°） | turn=true, jaw=null |
| `seed_front_hathaway.jpg` | `iss074e0604606`（裁剪右） | 仰视、近正面（俯仰大） | turn=false, jaw=null |

获取 URL 形如 `https://images-assets.nasa.gov/image/<ID>/<ID>~medium.jpg`；
查询 API `https://images-api.nasa.gov/search`。

## 标签规范（labels.json）

```json
{"file": "bundled/xxx.jpg", "face": true, "jaw": "open|closed|null", "turn": true|false|null,
 "origin": "来源#变体", "draft": false}
```

- `jaw` 指标只在 `head` 姿态无混淆的正面帧上人工核定；**转头帧与俯仰帧标 null**
  （2D 口径比受姿态混淆，不参与 jaw 一致率统计）；
- 卡通/合成帧 `jaw=null`（几何无真值）；
- 导入脚本产出的帧 `draft=true`，人工对照 `clips/<名>/_contact_sheet.jpg` 修订后
  可改 `draft=false`。

## 为什么 blendshape jawOpen 不直接当 jaw_open（实测记录，2026-09-28）

对上述种子实测：闭嘴微笑帧 jawOpen=0.093，大张嘴帧 jawOpen=0.079–0.094 ——
静帧上该 blendshape 与张闭嘴**无正相关甚至反向**（该头模型偏视频时序调校）。
因此 `cs_mouth` 用几何口径比（上下内唇 13/14 距 ÷ 外眼角 33/263 距）做 jaw_open：
实测闭嘴簇 0.057–0.10、张嘴簇 0.226–0.30，判别清晰（标定常数在
`config/mouth_prior.json` 的 `calib_closed_ratio/calib_open_ratio`）。
`mouthFrown` blendshape 干净可用（微笑帧 0.000–0.004）；`browDown` 微笑误报
（0.68）弃用。

## 主人后补真实样本（D1 之后）

手机录制 3 段 20s 视频（正面 40cm 张闭嘴 ×10、转头 30°、皱眉+说话），然后：

```bash
python scripts/import_face_samples.py --video 前面.mp4 转头.mp4 皱眉.mp4 --fps 2
# 对照 clips/<名>/_contact_sheet.jpg 修订 labels.json 中的 draft 标签后，重跑 eval
python -m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json
```

注意：Windows 下含中文路径的图像读写必须走 `cs_mouth.imgio`（cv2 直连会静默失败）。
