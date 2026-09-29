"""assetkit 端到端自测（python -m assetkit selftest）。

在仓库 tmp/ 下合成一套"全类型"素材（压图两类：平色带 alpha 的游戏件 / 渐变
噪声的照片类；低码率音频：合成正弦 WAV；字体：本机系统字体里挑出覆盖中文字
形与阿拉伯字形的各一个，只读输入、绝不入库），带一份合成 spec（i18n 中/阿字
符串 + sprite/audio 声明），跑完整管线后逐项断言：

  1. 汇总降幅 ≥30%（--min-reduction 同款语义，minReductionMet=true）；
  2. 游戏件压图生效且不增大；照片类走有损 WebP 且大幅下降；
  3. WAV → 低码率 AAC 生效且明显变小；
  4. 中文字体子集含全部请求中文字形；阿拉伯字体子集含全部请求阿拉伯字形；
     子集 ≤40KB（规划 §6-M5 字体线）；
  5. 图集：帧数=可装箱图数、帧两两不重叠、全部在界内、图集图可解码且尺寸一致；
  6. asset-optmap.json / report.json 落盘，optmap 键与素材一一对应。

系统字体候选缺失时字体项如实记 SKIP（不假绿）；其余项缺一即 FAIL（exit 1）。
"""

from __future__ import annotations

import json
import math
import random
import shutil
import struct
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = REPO_ROOT / "tmp" / "assetkit-selftest"

ZH_FONT_CANDIDATES = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf"]
AR_FONT_CANDIDATES = ["arial.ttf", "tahoma.ttf", "times.ttf", "segoeui.ttf", "calibri.ttf"]

ZH_TEXT = "得分通关啦立即下载拖动宝石三色连成一线"
AR_TEXT = "مرحبا بكم في اللعبة اسحب الجواهر"


def _synth_gem(path: Path) -> None:
    """平色圆角"宝石"（带 alpha 抗锯齿边）：模拟游戏小件，量化编码应大幅受益。"""
    from PIL import Image, ImageDraw

    size = 128
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=28, fill=(46, 134, 222, 235))
    d.rounded_rectangle((24, 20, size - 44, size - 60), radius=16, fill=(120, 190, 255, 255))
    d.polygon([(size // 2, 36), (size - 40, size // 2), (size // 2, size - 36), (40, size // 2)],
              fill=(28, 96, 176, 255))
    img.save(path)


def _synth_photo(path: Path) -> None:
    """渐变 + 伪随机噪声的"照片"类大图：有损 WebP 应大幅受益。"""
    from PIL import Image

    w = h = 512
    rng = random.Random(20261008)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            n = rng.randrange(48)
            px[x, y] = ((x * 255 // w + n) % 256, (y * 255 // h + n) % 256, (n * 5) % 256)
    img.save(path)


def _synth_wav(path: Path) -> None:
    """0.5s 440Hz 正弦 + 衰减包络的 16-bit 单声道 WAV（提示音的代理）。"""
    rate = 22050
    dur = 0.5
    n = int(rate * dur)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        env = math.exp(-4.0 * t)
        v = int(32000 * env * math.sin(2 * math.pi * 440.0 * t))
        frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def _pick_font(candidates: list[str], must_cover: str) -> Path | None:
    """从候选里挑第一个"存在且覆盖全部 must_cover 字形"的系统字体（只读）。"""
    from fontTools.ttLib import TTFont

    for name in candidates:
        p = Path("C:/Windows/Fonts") / name
        if not p.is_file():
            continue
        try:
            f = TTFont(str(p), fontNumber=0, lazy=True)
            cmap = f.getBestCmap() or {}
            if all(ord(ch) in cmap for ch in must_cover if not ch.isspace()):
                return p
        except Exception:
            continue
    return None


def _write_spec(tmp: Path) -> Path:
    spec = {
        "specVersion": "1.0.0",
        "meta": {"projectId": "assetkit-selftest", "title": "素材自测", "seed": 1},
        "game": {"template": "match3", "params": {}, "difficulty": {"targetLevel": 0.5},
                 "attract": {"nearWin": True}, "durationBudgetSec": {"target": 20, "max": 30}},
        "flow": {"tutorial": {"enabled": True, "gesture": "tap", "maxSec": 3},
                 "endScreen": {"showScore": True, "ctaKey": "cta",
                               "landingUrl": "https://example.com/lp"}},
        "assets": {
            "sprites": {"piece-0": "selftest-gem.png"},
            "audio": {"tap": "selftest-sfx.wav"},
        },
        "i18n": {
            "defaultLocale": "zh",
            "locales": ["zh", "ar"],
            "strings": {
                "zh": {"cta": "立即下载", "tutorial": ZH_TEXT, "win": "通关啦！",
                       "lose": "再试一次！", "score": "得分"},
                "ar": {"cta": "حمّل الآن", "tutorial": AR_TEXT, "win": "فوز!",
                       "lose": "حاول مرة أخرى", "score": "النقاط"},
            },
            "rtl": ["ar"],
        },
        "channels": {"targets": ["applovin"], "orientation": "portrait", "overrides": {}},
        "qc": {"maxLoadSec": 3.0, "autoplayTimeoutSec": 45},
    }
    p = tmp / "selftest-spec.json"
    p.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _assert(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'ok ' if ok else 'FAIL'} {name}" + (f"（{detail}）" if detail else ""))
    return ok


def run_selftest(keep: bool = False) -> int:
    from .pipeline import run_assetkit

    if TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT)
    TMP_ROOT.mkdir(parents=True)
    print(f"[assetkit] selftest 工作目录：{TMP_ROOT}")

    _synth_gem(TMP_ROOT / "selftest-gem.png")
    _synth_photo(TMP_ROOT / "selftest-photo.png")
    _synth_wav(TMP_ROOT / "selftest-sfx.wav")
    spec_path = _write_spec(TMP_ROOT)

    gem_bytes = (TMP_ROOT / "selftest-gem.png").stat().st_size
    photo_bytes = (TMP_ROOT / "selftest-photo.png").stat().st_size
    wav_bytes = (TMP_ROOT / "selftest-sfx.wav").stat().st_size
    print(f"  合成素材：gem {gem_bytes}B / photo {photo_bytes}B / wav {wav_bytes}B")

    zh_font = _pick_font(ZH_FONT_CANDIDATES, ZH_TEXT)
    ar_font = _pick_font(AR_FONT_CANDIDATES, AR_TEXT)
    if zh_font is None or ar_font is None:
        print(f"  SKIP 系统字体候选不足（zh={zh_font}, ar={ar_font}），字体子集项本机无法验证")
    else:
        print(f"  字体样本（只读输入，不入库）：zh={zh_font.name}, ar={ar_font.name}")

    report = run_assetkit(
        inputs=[str(TMP_ROOT / "selftest-photo.png")] + ([str(zh_font), str(ar_font)] if zh_font and ar_font else []),
        out=TMP_ROOT / "opt",
        spec=spec_path,
        min_reduction_pct=30.0,
    )

    ok = True
    totals = report["totals"]
    ok &= _assert("汇总降幅 ≥30%", totals["minReductionMet"] is True,
                  f"{totals['originalBytes']:,}B → {totals['optimizedBytes']:,}B（降 {totals['reductionPct']}%）")

    mat = report["materials"]
    gem_e = next((e for e in mat["image"] if e["key"] == "selftest-gem.png"), None)
    photo_e = next((e for e in mat["image"] if e["key"].endswith("selftest-photo.png")), None)
    ok &= _assert("游戏件压图生效（量化/近无损竞标，永不增大）",
                  gem_e is not None and gem_e["status"] == "optimized"
                  and gem_e["optimizedBytes"] < gem_e["originalBytes"],
                  f"{gem_e['encoding']} {gem_e['originalBytes']}→{gem_e['optimizedBytes']}B" if gem_e else "缺条目")
    ok &= _assert("照片类走有损 WebP 且大幅下降",
                  photo_e is not None and photo_e["status"] == "optimized"
                  and photo_e["encoding"] == "webp-lossy" and photo_e["reductionPct"] >= 30,
                  f"{photo_e['reductionPct']}%" if photo_e else "缺条目")

    wav_e = next((e for e in mat["audio"] if e["key"] == "selftest-sfx.wav"), None)
    ok &= _assert("WAV → 低码率 AAC 生效且明显变小",
                  wav_e is not None and wav_e["status"] == "optimized"
                  and str(wav_e.get("out", "")).endswith(".m4a") and wav_e["reductionPct"] >= 50,
                  f"{wav_e['originalBytes']}→{wav_e['optimizedBytes']}B" if wav_e else "缺条目")

    if zh_font and ar_font:
        from fontTools.ttLib import TTFont

        zh_e = next((e for e in mat["font"] if e["src"] == str(zh_font)), None)
        ar_e = next((e for e in mat["font"] if e["src"] == str(ar_font)), None)

        def _subset_covers(entry, text):
            f = TTFont(str((TMP_ROOT / "opt") / entry["out"]), lazy=True)
            cmap = f.getBestCmap() or {}
            return all(ord(ch) in cmap for ch in text if not ch.isspace())

        ok &= _assert("中文字体子集含全部请求中文字形且 ≤40KB",
                      zh_e is not None and zh_e["status"] == "optimized"
                      and _subset_covers(zh_e, ZH_TEXT) and zh_e["optimizedBytes"] <= 40_960,
                      f"{zh_e['optimizedBytes']}B，{zh_e['note']}" if zh_e else "缺条目")
        ok &= _assert("阿拉伯字体子集含全部请求阿拉伯字形且 ≤40KB",
                      ar_e is not None and ar_e["status"] == "optimized"
                      and _subset_covers(ar_e, AR_TEXT) and ar_e["optimizedBytes"] <= 40_960,
                      f"{ar_e['optimizedBytes']}B，{ar_e['note']}" if ar_e else "缺条目")

    atlas = report.get("atlas") or {}
    n_images = sum(1 for e in mat["image"] if e.get("status") == "optimized")
    frames = (json.loads((TMP_ROOT / "opt" / "atlas.json").read_text(encoding="utf-8"))
              if (TMP_ROOT / "opt" / "atlas.json").is_file() else {})
    fr = frames.get("frames") or {}
    no_overlap = True
    keys = list(fr)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = fr[keys[i]], fr[keys[j]]
            if (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
                    and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]):
                no_overlap = False
    in_bounds = all(f["x"] + f["width"] <= frames.get("width", 0)
                    and f["y"] + f["height"] <= frames.get("height", 0) for f in fr.values())
    atlas_img_ok = False
    if frames.get("image"):
        from PIL import Image

        with Image.open(TMP_ROOT / "opt" / frames["image"]) as im:
            atlas_img_ok = im.size == (frames.get("width"), frames.get("height"))
    ok &= _assert("图集帧数=优化图数、两两不重叠、全部在界内",
                  atlas.get("packed") == n_images and len(fr) == n_images
                  and no_overlap and in_bounds,
                  f"packed={atlas.get('packed')}/{n_images} frames={len(fr)}")
    ok &= _assert("图集图可解码且尺寸与 atlas.json 一致", atlas_img_ok,
                  f"{frames.get('image')} {frames.get('width')}x{frames.get('height')}")

    optmap_path = TMP_ROOT / "opt" / "asset-optmap.json"
    optmap = json.loads(optmap_path.read_text(encoding="utf-8")) if optmap_path.is_file() else {}
    opt_keys = {e["key"] for e in optmap.get("entries", [])}
    expected = {e["key"] for e in (*mat["image"], *mat["audio"], *mat["font"]) if e.get("out")}
    ok &= _assert("asset-optmap.json 键与产出素材一一对应（spec 声明串为键）",
                  opt_keys == expected and len(opt_keys) > 0,
                  f"{len(opt_keys)} 键")

    print(f"[assetkit] selftest {'PASS' if ok else 'FAIL'}")
    if not ok or keep:
        print(f"  工作目录保留于 {TMP_ROOT}（供排查）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_selftest())
