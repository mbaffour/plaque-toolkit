"""
Inference helper for the plaque-vs-texture classifier.

Loads _research/clf/plaque_clf.pt and exposes:
    load_model(path=None, device='cpu') -> (model, meta)
    prob_plaque(model, meta, patch_bgr) -> float in [0,1]      # single 48x48 BGR patch
    prob_plaque_batch(model, meta, patches_bgr) -> np.ndarray   # list/array of patches

A "patch" is a 48x48x3 BGR uint8 image (same convention as the mined data:
cv2.imread default).  Non-48x48 input is resized.  The classifier is the
lightweight verifier that sits behind PST/PlaqSeg detection: feed it a
scale-normalized crop centered on a candidate and it returns P(real plaque).

Run in the plaqseg env (torch CPU + torchvision).
"""
import os
import numpy as np
import cv2
import torch
import torch.nn as nn
from torchvision.models import resnet18

_DEF = os.path.join(os.path.dirname(__file__), "plaque_clf.pt")


def _build(arch):
    m = resnet18(weights=None)
    m.fc = nn.Linear(m.fc.in_features, 2)
    return m


def load_model(path=None, device="cpu"):
    path = path or _DEF
    # weights_only=True is the safe default (torch >= 2.6): it forbids arbitrary
    # code execution during unpickling. plaque_clf.pt is a plain state_dict
    # checkpoint (an OrderedDict of tensors + scalar metadata), which loads fine
    # under this restriction. If you ever ship a checkpoint that stores a full
    # pickled model or custom classes this will refuse to load it -- do NOT flip
    # this back to False. TODO: keep saving checkpoints as {"state_dict": ...}
    # (never torch.save(model)) so this stays safe.
    ckpt = torch.load(path, map_location=device, weights_only=True)
    model = _build(ckpt.get("arch", "resnet18_imagenet_ft_2class"))
    model.load_state_dict(ckpt["state_dict"])
    model.to(device).eval()
    meta = {
        "patch": ckpt.get("patch", 48),
        "mean": np.array(ckpt.get("mean", [0.485, 0.456, 0.406]), np.float32),
        "std":  np.array(ckpt.get("std",  [0.229, 0.224, 0.225]), np.float32),
        "default_thr": ckpt.get("default_thr", 0.5),
        "tuned_thr": ckpt.get("tuned_thr", 0.5),
        "device": device,
    }
    return model, meta


def _prep(patch_bgr, meta):
    im = patch_bgr
    P = meta["patch"]
    if im.shape[:2] != (P, P):
        im = cv2.resize(im, (P, P), interpolation=cv2.INTER_AREA)
    rgb = im[:, :, ::-1].astype(np.float32) / 255.0
    rgb = (rgb - meta["mean"]) / meta["std"]
    return np.ascontiguousarray(rgb.transpose(2, 0, 1))


@torch.no_grad()
def prob_plaque(model, meta, patch_bgr):
    x = torch.from_numpy(_prep(patch_bgr, meta)).unsqueeze(0).to(meta["device"])
    return float(torch.softmax(model(x), 1)[0, 1])


@torch.no_grad()
def prob_plaque_batch(model, meta, patches_bgr, bs=128):
    arr = np.stack([_prep(p, meta) for p in patches_bgr]) if len(patches_bgr) else \
          np.zeros((0, 3, meta["patch"], meta["patch"]), np.float32)
    out = np.zeros(len(arr), np.float32)
    for i in range(0, len(arr), bs):
        xb = torch.from_numpy(arr[i:i+bs]).to(meta["device"])
        out[i:i+bs] = torch.softmax(model(xb), 1)[:, 1].cpu().numpy()
    return out


if __name__ == "__main__":
    import glob, random
    model, meta = load_model()
    print("loaded", _DEF, "| tuned_thr", meta["tuned_thr"])
    # quick smoke test: score a few stored pos and neg patches
    pos = glob.glob(os.path.join(os.path.dirname(__file__), "data", "pos", "*.png"))
    neg = glob.glob(os.path.join(os.path.dirname(__file__), "data", "neg", "*.png"))
    random.seed(0)
    for lab, files in (("pos", random.sample(pos, 5)), ("neg", random.sample(neg, 5))):
        for f in files:
            p = prob_plaque(model, meta, cv2.imread(f))
            print(f"{lab}  p_plaque={p:.3f}  {os.path.basename(f)}")
