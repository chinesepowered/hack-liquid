"""Capy's voice: speaks tower radio calls on the board's speaker. Fully offline.

Backends (picked with --voice):
  lfm3    LiquidAI LFM3-Audio-2B. The tower phrasebook is pre-rendered on the board with llama.cpp's
          llama-tts (scripts/render_voice.py), because live synthesis runs at about 0.45x real time on
          the CPU. A call plays its LFM3-Audio clip instantly; if the exact wording is not in the
          phrasebook, the verified template of the same instruction is used; anything else goes to Piper.
  piper   Piper neural TTS (en_US-amy-medium, ONNX on the board CPU), about 1.3 s per call
  espeak  espeak-ng, tiny and instant, robotic
  off     silent

Speech runs on its own thread with a short queue, so it never blocks the decision loop.
"""

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def spoken(text):
    """Read callsigns and runways the way a controller says them."""
    return " ".join(text.replace("two-eight", "two eight").replace("-", " ").split())


class Voice(threading.Thread):
    def __init__(self, mode="lfm3", device="default", log=None, timeout=25,
                 phrasebook="~/models/capy-voice", piper_bin="~/.venvs/piper/bin/piper",
                 piper_model="~/models/piper/en_US-amy-medium.onnx"):
        super().__init__(daemon=True)
        self.mode, self.device, self.timeout, self.log = mode, device, timeout, log or (lambda r: None)
        self.book_dir = Path(os.path.expanduser(phrasebook))
        self.piper_bin, self.piper_model = os.path.expanduser(piper_bin), os.path.expanduser(piper_model)
        self.q = queue.Queue(maxsize=6)
        self.tmp = Path(tempfile.mkdtemp(prefix="capy-voice-"))
        self.speaking, self.last_voice = None, None
        self.has_piper = os.access(self.piper_bin, os.X_OK) and os.path.exists(self.piper_model)
        self.has_espeak = shutil.which("espeak-ng") is not None
        if self.mode == "lfm3" and not (self.book_dir / "index.json").exists():
            self.log({"event": "voice_fallback", "wanted": "lfm3", "reason": "no LFM3-Audio phrasebook yet"})
        if self.mode == "piper" and not self.has_piper:
            self.mode = "espeak"
        if self.mode == "espeak" and not self.has_espeak:
            self.mode = "off"

    def _book(self):
        try:  # re-read each time: the phrasebook may still be rendering in the background
            return json.loads((self.book_dir / "index.json").read_text())
        except (OSError, ValueError):
            return {}

    def info(self):
        names = {"lfm3": "LiquidAI LFM3-Audio-2B (pre-rendered on the board)", "piper": "Piper en_US-amy-medium",
                 "espeak": "espeak-ng"}
        return {"mode": self.mode, "model": names.get(self.mode), "speaking": self.speaking,
                "last_voice": self.last_voice, "phrasebook": len(self._book()) if self.mode == "lfm3" else None}

    def say(self, text, alt=None):
        """Speak `text`; `alt` is the verified template of the same instruction (phrasebook fallback)."""
        if self.mode == "off" or not text:
            return
        try:
            self.q.put_nowait((text, alt))
        except queue.Full:  # never let speech back up behind the tower
            self.log({"event": "voice_dropped", "text": text[:120]})

    # ---- synthesis ------------------------------------------------------------------------------

    def _piper(self, text, out):
        r = subprocess.run([self.piper_bin, "-m", self.piper_model, "-f", str(out)], input=spoken(text),
                           text=True, timeout=self.timeout, capture_output=True)
        if r.returncode or not out.exists():
            raise RuntimeError((r.stderr or "no audio")[-300:])

    def _espeak(self, text, out):
        subprocess.run(["espeak-ng", "-v", "en-us+f3", "-s", "150", "-a", "200", "-g", "4", "-w", str(out),
                        spoken(text)], check=True, timeout=10, capture_output=True)

    def _play(self, wav):
        subprocess.run(["aplay", "-q", "-D", self.device, str(wav)], timeout=30, capture_output=True)

    def _render(self, text, alt, wav):
        """Returns (wav path, voice used, spoken text)."""
        if self.mode == "lfm3":
            book = self._book()
            for t in (text, alt):
                if t and spoken(t) in book and (self.book_dir / book[spoken(t)]).exists():
                    return self.book_dir / book[spoken(t)], "lfm3-audio", t
        if self.mode in ("lfm3", "piper") and self.has_piper:
            self._piper(text, wav)
            return wav, "piper", text
        self._espeak(text, wav)
        return wav, "espeak", text

    def run(self):
        n = 0
        while True:
            text, alt = self.q.get()
            n += 1
            wav = self.tmp / f"call{n % 8}.wav"
            wav.unlink(missing_ok=True)
            t0 = time.perf_counter()
            try:
                self.speaking = text
                path, used, said = self._render(text, alt, wav)
                ready_ms = round((time.perf_counter() - t0) * 1000)
                self.last_voice = used
                self._play(path)
                self.log({"event": "spoke", "voice": used, "ready_ms": ready_ms, "text": said[:160]})
            except Exception as e:
                self.log({"event": "voice_error", "error": f"{type(e).__name__}: {e}"[:200]})
            finally:
                self.speaking = None
