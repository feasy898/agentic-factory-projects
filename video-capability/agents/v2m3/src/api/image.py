"""生图/改图能力: API(OpenAI 兼容 /images/generations)优先, 本地 SDXL img2img 兜底。

本地实现 lazy import diffusers/torch; 测试可注入 pipeline stub。
"""

from __future__ import annotations

import base64
import json
import urllib.request

from .adapters import Adapter, BudgetGuard, Endpoint, http_post_json


def api_generate_image(endpoint: Endpoint, prompt: str, out_path: str, size: str = "1024x1536", http=http_post_json):
    """OpenAI 兼容图像接口: 返回 b64 或 url, 统一落盘到 out_path。"""
    payload = {"model": endpoint.model, "prompt": prompt, "n": 1, "size": size}
    data = http(f"{endpoint.base}/images/generations", endpoint.key, payload)
    item = data["data"][0]
    if item.get("b64_json"):
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        req = urllib.request.Request(item["url"])
        with urllib.request.urlopen(req, timeout=300) as resp, open(out_path, "wb") as f:
            f.write(resp.read())
    else:
        raise ValueError(f"图像 API 返回缺 b64_json/url 字段: {json.dumps(data)[:200]}")
    return {"path": out_path, "route_model": endpoint.model}


_SDXL_CACHE: dict = {}  # 进程级缓存(device→pipe): M5 生产每任务一次首帧风格化, 避免重复加载 6.9G 权重


def _sdxl_local_dir() -> str | None:
    """本地 SDXL 目录优先(M1 下载的 models/sdxl-base-1.0-fp16); 离线沙箱(HF_HUB_OFFLINE=1)必需。"""
    import os

    env_p = os.environ.get("CRADLE_SDXL_DIR", "")
    if env_p and os.path.isdir(env_p):
        return env_p
    try:
        from ..config import project_root

        local = project_root() / "models" / "sdxl-base-1.0-fp16"
        if (local / "model_index.json").exists():
            return str(local)
    except Exception:
        pass
    return None


def _load_sdxl_img2img(device: str):
    try:
        import torch  # noqa: F401
        from diffusers import StableDiffusionXLImg2ImgPipeline
    except Exception as e:  # pragma: no cover — 依赖缺失场景
        from .adapters import LocalUnavailable

        raise LocalUnavailable(f"SDXL img2img 本地依赖不可用: {e}") from e
    if device in _SDXL_CACHE:
        return _SDXL_CACHE[device]
    local_dir = _sdxl_local_dir()
    if local_dir:
        pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            local_dir, torch_dtype=torch.float16, variant="fp16", local_files_only=True,
        )
    else:
        # 无本地目录时回落 repo id(需 HF 可达, M2 资产生成同路径)
        pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0", torch_dtype=torch.float16, variant="fp16"
        )
    pipe = pipe.to(device)
    _SDXL_CACHE[device] = pipe
    return pipe


def local_sdxl_img2img(
    image_path: str,
    prompt: str,
    out_path: str,
    strength: float = 0.30,
    device: str = "cuda",
    seed: int = 0,
    negative_prompt: str = "",
    pipeline=None,
    loader=_load_sdxl_img2img,
):
    """SDXL img2img 低强度重绘 (Wan 首帧风格统一也复用, denoise 0.2-0.35)。

    pipeline 可注入(测试 stub); 缺省时 lazy 加载真实管线(本阶段不真正跑 GPU)。
    """
    from PIL import Image

    pipe = pipeline if pipeline is not None else loader(device)
    init = Image.open(image_path).convert("RGB")
    gen = None
    try:
        import torch

        gen = torch.Generator(device="cpu").manual_seed(seed)
    except Exception:
        gen = None
    result = pipe(
        prompt=prompt,
        image=init,
        strength=float(strength),
        negative_prompt=negative_prompt or None,
        generator=gen,
    )
    img = result.images[0]
    img.save(out_path)
    return {"path": out_path, "model": "sdxl_img2img", "strength": float(strength), "device": device}


def make_image_adapter(endpoint: Endpoint, budget: BudgetGuard, local_fn=None, log=None) -> Adapter:
    return Adapter(
        "image",
        endpoint,
        budget,
        api_fn=lambda prompt, out_path, **kw: api_generate_image(endpoint, prompt, out_path, **kw),
        local_fn=local_fn or local_sdxl_img2img,
        log=log,
    )
