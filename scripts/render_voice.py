#!/usr/bin/env python3
"""Pre-render Capy's tower phrasebook with LiquidAI LFM3-Audio-2B on the board (llama.cpp llama-tts).

LFM3-Audio runs at about 0.45x real time on the IQ-9075 CPU, too slow to speak a go-around live.
So every standard tower call is rendered once here, and capy_tower/voice.py plays the matching clip
instantly. Demo-critical calls render first. Safe to re-run: existing clips are kept.

    python3 scripts/render_voice.py            # writes ~/models/capy-voice/*.wav and index.json
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capy_tower"))
import tower as tw  # noqa: E402
from voice import spoken  # noqa: E402

OUT = Path(os.path.expanduser("~/models/capy-voice"))
TTS = os.path.expanduser("~/llama.cpp/build/bin/llama-tts")
MD = Path(os.path.expanduser("~/models/lfm3-audio"))


def acts():
    dep = {"spoken": "Cessna two-eight-alpha", "target": "Cessna 28A"}
    arr = {"spoken": "Cirrus seven-charlie-papa", "target": "Cirrus 7CP"}
    order = ["wildlife", "debris", "vehicle", "person", "capybara", "unknown"]
    seen = []
    for a in [{"action": "clear_to_land", **arr}, {"action": "clear_for_takeoff", **dep}, {"action": "reopen_runway"}]:
        seen.append(a)
    for what in order:
        seen += [{"action": "go_around", "what": what, **arr}, {"action": "close_runway", "what": what},
                 {"action": tw.DISPATCH.get(what, "alert_security"), "what": what},
                 {"action": "hold_short", "what": what, **dep}, {"action": "cancel_takeoff", "what": what, **dep}]
    seen += [{"action": "hold_short", "reason": "landing traffic", **dep},
             {"action": "go_around", "reason": "departing traffic", **arr}]
    return seen


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    idx_path = OUT / "index.json"
    index = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    texts = []
    for a in acts():
        if a["action"] not in tw.ALLOWED_ACTIONS:
            continue
        t = spoken(tw.template(a))
        if t not in texts:
            texts.append(t)
    print(f"{len(texts)} phrases, {sum(t in index for t in texts)} already rendered", flush=True)
    for t in texts:
        if t in index and (OUT / index[t]).exists():
            continue
        name = hashlib.sha1(t.encode()).hexdigest()[:12] + ".wav"
        t0 = time.time()
        r = subprocess.run([TTS, "-m", str(MD / "LFM3-Audio-2B-Q4_K_M.gguf"), "-mm", str(MD / "mmproj-LFM3-Audio-2B-Q8_0.gguf"),
                            "-p", t, "--tts-voice", "female", "-o", str(OUT / name)], capture_output=True, text=True)
        if r.returncode or not (OUT / name).exists():
            print("FAILED", t, r.stderr[-200:], flush=True)
            continue
        index[t] = name
        idx_path.write_text(json.dumps(index, indent=1))
        print(f"{time.time() - t0:5.1f}s  {t}", flush=True)
    print("RENDER_DONE", flush=True)


if __name__ == "__main__":
    main()
