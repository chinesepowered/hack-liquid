"""Capy's voice: speaks tower radio calls on the board's speaker. Fully offline.

Backends (picked with --voice):
  lfm3    LiquidAI LFM3-Audio-2B text-to-speech through llama.cpp's llama-tts, on the board CPU
  espeak  espeak-ng, tiny and instant, sounds like a radio
  off     silent

Speech runs on its own thread with a short queue, so it never blocks the decision loop. If the
LFM3 voice fails or takes too long, that call falls back to espeak-ng and the failure is logged.
"""

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class Voice(threading.Thread):
    def __init__(self, mode="espeak", device="default", tts_bin="~/llama.cpp/build/bin/llama-tts",
                 model_dir="~/models/lfm3-audio", tts_voice="female", timeout=25, log=None, radio_fx=False):
        super().__init__(daemon=True)
        self.mode, self.device, self.timeout, self.log = mode, device, timeout, log or (lambda r: None)
        self.tts_bin = os.path.expanduser(tts_bin)
        md = Path(os.path.expanduser(model_dir))
        self.model, self.mmproj = md / "LFM3-Audio-2B-Q4_K_M.gguf", md / "mmproj-LFM3-Audio-2B-Q8_0.gguf"
        self.tts_voice = tts_voice
        self.radio_fx = radio_fx and shutil.which("sox") is not None
        self.q = queue.Queue(maxsize=6)
        self.tmp = Path(tempfile.mkdtemp(prefix="capy-voice-"))
        self.speaking = None
        if self.mode == "lfm3" and not (os.access(self.tts_bin, os.X_OK) and self.model.exists() and self.mmproj.exists()):
            self.log({"event": "voice_fallback", "reason": "llama-tts or LFM3-Audio files missing", "voice": "espeak"})
            self.mode = "espeak"
        if self.mode == "espeak" and not shutil.which("espeak-ng"):
            self.mode = "off"

    def info(self):
        return {"mode": self.mode, "speaking": self.speaking,
                "model": "LiquidAI/LFM3-Audio-2B (llama.cpp, CPU)" if self.mode == "lfm3" else
                         "espeak-ng" if self.mode == "espeak" else None}

    def say(self, text):
        if self.mode == "off" or not text:
            return
        try:
            self.q.put_nowait(text)
        except queue.Full:  # never let speech back up behind the tower
            self.log({"event": "voice_dropped", "text": text[:120]})

    # ---- synthesis ------------------------------------------------------------------------------

    def _espeak(self, text, out):
        subprocess.run(["espeak-ng", "-v", "en-us+f3", "-s", "150", "-a", "200", "-w", str(out), text],
                       check=True, timeout=10, capture_output=True)

    def _lfm3(self, text, out):
        cmd = [self.tts_bin, "-m", str(self.model), "-mm", str(self.mmproj), "-p", text,
               "--tts-voice", self.tts_voice, "-o", str(out)]
        r = subprocess.run(cmd, timeout=self.timeout, capture_output=True, text=True)
        if r.returncode or not out.exists() or out.stat().st_size < 2000:
            raise RuntimeError((r.stderr or "no audio")[-300:])

    def _fx(self, wav):
        if not self.radio_fx:
            return wav
        out = wav.with_name(wav.stem + "_fx.wav")
        # tower radio: band-limited, a touch of drive, short squelch tail
        subprocess.run(["sox", str(wav), str(out), "highpass", "300", "lowpass", "3400", "gain", "-n", "-0.5", "pad", "0.05", "0.15"], timeout=10, capture_output=True)
        return out if out.exists() else wav

    def _play(self, wav):
        subprocess.run(["aplay", "-q", "-D", self.device, str(wav)], timeout=30, capture_output=True)

    def run(self):
        n = 0
        while True:
            text = self.q.get()
            n += 1
            wav = self.tmp / f"call{n % 8}.wav"
            wav.unlink(missing_ok=True)
            t0 = time.perf_counter()
            used, err = self.mode, None
            try:
                self.speaking = text
                if self.mode == "lfm3":
                    try:
                        self._lfm3(text, wav)
                    except Exception as e:  # keep talking: this call goes out on espeak
                        err, used = f"{type(e).__name__}: {e}"[:200], "espeak"
                        self._espeak(text, wav)
                else:
                    self._espeak(text, wav)
                synth_ms = round((time.perf_counter() - t0) * 1000)
                self._play(self._fx(wav))
                self.log({"event": "spoke", "voice": used, "synth_ms": synth_ms, "text": text[:160],
                          **({"lfm3_error": err} if err else {})})
            except Exception as e:
                self.log({"event": "voice_error", "error": f"{type(e).__name__}: {e}"[:200]})
            finally:
                self.speaking = None
