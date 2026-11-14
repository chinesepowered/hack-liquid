"""Decision gates for Capy Tower.

d1   LiquidAI d1-2B through Transformers on the CPU (the hackathon's reference d1 route).
     One forward pass answers typed questions about the camera frame, with no generated tokens.
rule A pixel-difference fallback against an empty-runway baseline, used if d1 is unavailable.

Both return the same keys: gate, p_blocked, what, what_conf, what_probs, gate_ms.
"""

import os
import time

from PIL import Image, ImageChops, ImageStat

STATE = ("Fixed tower camera picture of runway 28 at a small airport. The runway is the long grey "
         "paved strip with white markings; grass is on both sides.")

WHAT = {
    "capybara": "A capybara, a large brown rodent",
    "wildlife": "Another animal, such as a deer, dog, goose or bird",
    "person": "A person on foot",
    "vehicle": "A car, truck or aircraft",
    "debris": "A loose object, such as a traffic cone, bottle, phone, bag or tool",
    "nothing": "Nothing, the runway is empty",
}

QUESTIONS = {
    "blocked": {
        "type": "noul",
        "instructions": "Is there an animal, a person, a vehicle or an object on the runway right now?",
        "criteria": {"true": "Something is on the runway, so it is not safe to use",
                     "false": "The runway is empty and safe to use"},
    },
    "what": {
        "type": "choice",
        "instructions": "What is on the runway?",
        "criteria": WHAT,
    },
}


def small_gray(img, size=(64, 40)):
    return img.convert("L").resize(size, Image.BILINEAR)


def mean_abs_diff(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def changed_share(a, b, delta=25):
    """Share of pixels that changed by more than `delta` (0-255): a small animal still registers."""
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > delta else 0)
    return ImageStat.Stat(diff).mean[0] / 255


def downscale(img, max_side):
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    r = max_side / max(w, h)
    return img.resize((max(1, round(w * r)), max(1, round(h * r))), Image.BILINEAR)


def _probs(answer, keys):
    p = answer.get("probabilities")
    if isinstance(p, dict):
        return {k: round(float(v), 4) for k, v in p.items()}
    if isinstance(p, (list, tuple)) and len(p) == len(keys):
        return {k: round(float(v), 4) for k, v in zip(keys, p)}
    return {}


class D1Gate:
    name = "d1"

    def __init__(self, model_dir, max_side=512, threads=0):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        import torch
        from transformers import AutoModel

        self.torch = torch
        if threads:
            torch.set_num_threads(threads)
        model_dir = os.path.expanduser(str(model_dir))
        if not os.path.isdir(model_dir):
            raise FileNotFoundError(f"d1 snapshot not found at {model_dir}")
        t0 = time.perf_counter()
        self.model = AutoModel.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True,
                                               dtype=torch.float32).to("cpu").eval()
        self.load_s = round(time.perf_counter() - t0, 1)
        self.max_side = max_side
        self.decide(Image.new("RGB", (160, 100), (110, 110, 110)))  # warm-up: first call pays setup costs

    def decide(self, img):
        img = downscale(img, self.max_side)
        t0 = time.perf_counter()
        with self.torch.inference_mode():
            res = self.model.system_one(STATE, QUESTIONS, media=[img])
        ms = (time.perf_counter() - t0) * 1000
        a = res["answers"]
        what = a["what"]
        usage = res.get("usage") or {}
        return {"gate": "d1", "p_blocked": round(float(a["blocked"]["noul"]), 4),
                "what": what.get("choice"), "what_conf": round(float(what.get("confidence") or 0), 4),
                "what_probs": _probs(what, list(WHAT)), "gate_ms": round(ms, 1),
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}


class RuleGate:
    """Fallback: the share of pixels that differ from an empty-runway baseline."""
    name = "rule"

    def __init__(self, pixel_delta=40, full_share=0.02):
        self.baseline = None
        self.pixel_delta, self.full_share = pixel_delta, full_share

    def set_baseline(self, img):
        self.baseline = small_gray(img, (128, 80))

    def decide(self, img):
        t0 = time.perf_counter()
        cur = small_gray(img, (128, 80))
        if self.baseline is None:
            self.baseline = cur
        diff = ImageChops.difference(cur, self.baseline).point(lambda v: 255 if v > self.pixel_delta else 0)
        share = ImageStat.Stat(diff).mean[0] / 255
        p = max(0.0, min(1.0, share / self.full_share))
        return {"gate": "rule", "p_blocked": round(p, 4), "what": "unknown" if p >= 0.5 else "nothing",
                "what_conf": None, "what_probs": {}, "gate_ms": round((time.perf_counter() - t0) * 1000, 1),
                "changed_share": round(share, 4)}
