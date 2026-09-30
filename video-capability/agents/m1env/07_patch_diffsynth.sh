#!/usr/bin/env bash
# M1-ENV step 07: patch broken patchify in repacked diffsynth 1.1.9 wheel (D-009)
set -x
F=~/cradle/.venv/lib/python3.12/site-packages/diffsynth/models/wan_video_dit.py
cp $F ${F}.bak
python3 - <<'EOF'
path = "/root/cradle/.venv/lib/python3.12/site-packages/diffsynth/models/wan_video_dit.py"
src = open(path).read()
old = """    def patchify(self, x: torch.Tensor, control_camera_latents_input: Optional[torch.Tensor] = None):
        x = self.patch_embedding(x)
        if self.control_adapter is not None and control_camera_latents_input is not None:
            y_camera = self.control_adapter(control_camera_latents_input)
            x = [u + v for u, v in zip(x, y_camera)]
            x = x[0].unsqueeze(0)
        return x
"""
new = """    def patchify(self, x: torch.Tensor, control_camera_latents_input: Optional[torch.Tensor] = None):
        x = self.patch_embedding(x)
        if self.control_adapter is not None and control_camera_latents_input is not None:
            y_camera = self.control_adapter(control_camera_latents_input)
            x = [u + v for u, v in zip(x, y_camera)]
            x = x[0].unsqueeze(0)
        grid_size = x.shape[2:]
        x = x.flatten(2).transpose(1, 2)
        return x, grid_size
"""
assert old in src, "patchify body not found!"
src = src.replace(old, new, 1)
open(path, "w").write(src)
print("PATCHED OK")
EOF
~/cradle/.venv/bin/python -c "
import inspect
from diffsynth.models.wan_video_dit import WanModel
src = inspect.getsource(WanModel.patchify)
assert 'grid_size' in src and 'flatten' in src
print('verify: patched patchify in effect')
"
echo "STEP07_DONE rc=$?"
