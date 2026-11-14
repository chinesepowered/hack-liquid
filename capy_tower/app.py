#!/usr/bin/env python3
"""Capy Tower: an always-on runway monitor that runs entirely on a Qualcomm Dragonwing IQ-9075.

  browser (laptop camera or simulated runway) --JPEG, isolated USB-C/SSH link--> this app on the board
  observe -> change gate -> d1-2B decision (CPU) -> policy -> allowlisted actions
          -> LFM3-1.7B radio calls (NPU, GenieX) -> JSONL log -> tower screen

On the board (see README.md):
  ~/.venvs/d1/bin/python capy_tower/app.py
UI test without any model:
  python3 capy_tower/app.py --gate rule --no-lfm
"""

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import argparse  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import queue  # noqa: E402
import resource  # noqa: E402
import statistics  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from collections import deque  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gates  # noqa: E402
import voice as vc  # noqa: E402
import tower as tw  # noqa: E402
from lfm_client import DEFAULT_MODEL, DEFAULT_SERVER, LFM  # noqa: E402

STATIC = HERE / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon"}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def network_status():
    """Is there any route off the board? Read straight from the kernel, no network calls."""
    default_route = False
    try:
        with open("/proc/net/route") as f:
            next(f)
            for line in f:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000" and parts[0] != "lo":
                    default_route = True
    except (OSError, StopIteration):
        pass
    wifi = []
    for p in sorted(Path("/sys/class/net").glob("*")):
        if (p / "wireless").exists() or p.name.startswith("wl"):
            try:
                wifi.append({"if": p.name, "state": (p / "operstate").read_text().strip()})
            except OSError:
                pass
    return {"uplink": default_route, "wifi": wifi}


def rss_mb():
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None            # (jpeg bytes, arrival time, source)
        self.frames_in = 0
        self.decided_jpeg = None
        self.requests = queue.Queue()
        self.baseline = False
        self.status, self.detail = "starting", "loading models"
        self.gate_name, self.gate_info, self.lfm_info = None, {}, {}
        self.radio = deque(maxlen=40)
        self.events = deque(maxlen=40)
        self.decision = None
        self.busy = None             # "d1" while deciding, "lfm" while writing a radio call
        self.n_decisions = self.n_skipped = self.n_radio = self.n_fallback = self.iteration = 0
        self.gate_ms, self.lfm_ms, self.lfm_tokens, self.loop_ms = (deque(maxlen=50) for _ in range(4))
        self.started = time.time()


class Agent(threading.Thread):
    def __init__(self, shared, tower, args):
        super().__init__(daemon=True)
        self.s, self.tower, self.args = shared, tower, args
        self.gate = None
        self.lfm = None if args.no_lfm else LFM(server=args.server, model=args.llm, compute=args.compute, timeout=30)
        self.last_t = None
        self.decided_small = None
        self.last_decision_t = 0.0
        self.log_path = Path(args.log)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.voice = vc.Voice(mode=args.voice, log=self._log)
        self.voice.start()
        self.frames_dir = Path(args.save_frames) if args.save_frames else None
        if self.frames_dir:
            self.frames_dir.mkdir(parents=True, exist_ok=True)

    # ---- setup ------------------------------------------------------------------------------------

    def load_gate(self):
        if self.args.gate == "d1":
            try:
                self._set_status("starting", "loading d1-2B on the CPU")
                g = gates.D1Gate(self.args.model_dir, max_side=self.args.max_side, threads=self.args.threads)
                info = {"model": "LiquidAI/d1-2B", "device": "CPU (Transformers, fp32)", "load_s": g.load_s}
                self._log({"event": "gate_loaded", "gate": "d1", **info})
                return g, info
            except Exception as e:  # keep the tower running: fall back to the pixel rule
                msg = f"{type(e).__name__}: {e}"[:300]
                self._log({"event": "gate_failed", "gate": "d1", "error": msg, "fallback": "rule"})
                print("d1 failed, using the rule gate:", msg, file=sys.stderr)
                g = gates.RuleGate()
                return g, {"model": "pixel rule (d1 failed: " + msg[:120] + ")", "device": "CPU"}
        return gates.RuleGate(), {"model": "pixel rule", "device": "CPU"}

    def check_lfm(self):
        if not self.lfm:
            return {"model": "templates only (--no-lfm)", "ready": False}
        ready = self.lfm.ready()
        info = {"model": self.args.llm, "server": self.args.server, "compute": self.args.compute, "ready": ready}
        if ready and self.args.warmup:
            r = self.lfm.sentence("Say: Capy Tower is online.", system=tw.SYSTEM_PROMPT, max_tokens=24)
            info.update(warmup_ok=r["ok"], warmup_ms=r["ms"])
        return info

    def _set_status(self, status, detail=""):
        with self.s.lock:
            self.s.status, self.s.detail = status, detail

    # ---- loop -------------------------------------------------------------------------------------

    def run(self):
        gate, ginfo = self.load_gate()
        self.gate = gate
        linfo = self.check_lfm()
        with self.s.lock:
            self.s.gate_name, self.s.gate_info, self.s.lfm_info = gate.name, ginfo, linfo
            self.s.status, self.s.detail = "ready", ""
        self._log({"event": "tower_online", "gate": ginfo, "lfm": linfo, "threshold": self.tower.threshold})
        last_lfm_check = time.time()
        while True:
            try:
                self.step()
                if self.lfm and not self.s.lfm_info.get("ready") and time.time() - last_lfm_check > 10:
                    last_lfm_check = time.time()
                    info = self.check_lfm()
                    with self.s.lock:
                        self.s.lfm_info = info
            except Exception as e:  # errors are data: log and keep monitoring
                self._log({"event": "error", "error": f"{type(e).__name__}: {e}"[:300]})
                traceback.print_exc()
                time.sleep(1)
            time.sleep(self.args.poll)

    def step(self):
        t_loop = time.perf_counter()
        with self.s.lock:
            auto = self.tower.tick()
        if auto:
            self._run_actions(auto, {"trigger": "auto"}, t_loop)

        req = None
        try:
            req = self.s.requests.get_nowait()
        except queue.Empty:
            pass

        with self.s.lock:
            fr = self.s.frame
            baseline = self.s.baseline
            self.s.baseline = False

        trigger, img, obs = None, None, {}
        if fr is not None and (fr[1] != self.last_t or req):
            jpeg, ft, source = fr
            self.last_t = ft
            img = Image.open(io.BytesIO(jpeg))
            img.load()
            if baseline and isinstance(self.gate, gates.RuleGate):
                self.gate.set_baseline(img)
            small = gates.small_gray(img)
            diff = None if self.decided_small is None else round(gates.changed_share(small, self.decided_small), 4)
            if req:
                trigger = "request"
            elif diff is None or diff >= self.args.change:
                trigger = "change"
            elif time.time() - self.last_decision_t >= self.args.heartbeat:
                trigger = "heartbeat"
            obs = {"source": source, "frame_age_ms": round((time.time() - ft) * 1000), "diff": diff}
            if trigger:
                self.decided_small = small
            else:
                with self.s.lock:
                    self.s.n_skipped += 1

        actions, pilot, decision = [], None, None
        if trigger:
            with self.s.lock:
                self.s.busy = "d1"
            try:
                decision = self.gate.decide(img, obs.get("source", "sim"))
            finally:
                with self.s.lock:
                    self.s.busy = None
            self.last_decision_t = time.time()
            with self.s.lock:
                self.s.n_decisions += 1
                self.s.gate_ms.append(decision["gate_ms"])
                self.s.decision = decision | {"t": now_iso()}
                actions += self.tower.on_decision(decision)
                buf = io.BytesIO()
                gates.downscale(img, 512).save(buf, "JPEG", quality=80)
                self.s.decided_jpeg = buf.getvalue()
            if self.frames_dir:
                self._save_frame(img)
        if req:
            with self.s.lock:
                pilot, more = self.tower.on_request(req)
                actions += more
            if pilot:
                self._radio("PILOT", pilot, {"source": "pilot", "request": req})
            else:
                self._log({"event": "request_ignored", "request": req})
        if trigger or actions:
            self._run_actions(actions, obs | {"trigger": trigger or "request"}, t_loop, decision)

    def _run_actions(self, actions, obs, t_loop, decision=None):
        done = []
        for act in actions:
            if act["action"] not in tw.ALLOWED_ACTIONS:
                done.append({"action": act["action"], "executed": False, "refused": True})
                continue
            with self.s.lock:
                self.tower.apply(act)
            radio = self.radio_call(act)
            who = {"PILOT_CALL": "TOWER", "OPS": "TOWER→OPS", "ALL": "TOWER→ALL"}[tw.station(act)]
            self._radio(who, radio["text"], radio | {"action": act["action"]})
            self.voice.say(radio["text"])
            done.append({"action": act["action"], "target": act.get("target"), "auto": act.get("auto"),
                         "executed": True, "radio": radio})
        loop_ms = round((time.perf_counter() - t_loop) * 1000, 1)
        with self.s.lock:
            self.s.iteration += 1
            self.s.loop_ms.append(loop_ms)
            it = self.s.iteration
            view = self.tower.view()
        self._log({"iteration": it, "obs": obs, "decision": decision, "runway": view["status"],
                   "obstruction": view["what"], "actions": done, "loop_ms": loop_ms})

    def radio_call(self, act):
        template = tw.template(act)
        base = {"template": template}
        if not self.lfm:
            return {"text": template, "source": "template", "ok": True, "ms": 0, "tokens": 0} | base
        with self.s.lock:
            self.s.busy = "lfm"
        try:
            r = self.lfm.sentence(tw.prompt(act), system=tw.SYSTEM_PROMPT, max_tokens=self.args.max_radio_tokens)
        finally:
            with self.s.lock:
                self.s.busy = None
        text = tw.clean(r.get("text"))
        with self.s.lock:
            self.s.n_radio += 1
            if r.get("ms"):
                self.s.lfm_ms.append(r["ms"])
            if r.get("tokens"):
                self.s.lfm_tokens.append(r["tokens"])
        if r.get("ok") and tw.valid(text, act):
            return {"text": text, "source": "lfm3", "ok": True, "ms": r.get("ms"), "tokens": r.get("tokens"),
                    "retried": r.get("retried")} | base
        with self.s.lock:
            self.s.n_fallback += 1
        return {"text": template, "source": "template", "ok": False, "lfm_text": text[:200],
                "error": r.get("error") or "generated call missed the required instruction",
                "ms": r.get("ms"), "tokens": r.get("tokens")} | base

    # ---- output -----------------------------------------------------------------------------------

    def _radio(self, who, text, meta):
        with self.s.lock:
            self.s.radio.append({"t": now_iso(), "who": who, "text": text, **{k: meta.get(k) for k in (
                "source", "ms", "tokens", "action", "ok")}})

    def _log(self, record):
        record = {"t": now_iso()} | record
        line = json.dumps(record, default=str)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")
            f.flush()
        with self.s.lock:
            self.s.events.append(record)

    def _save_frame(self, img):
        try:
            name = self.frames_dir / f"{int(time.time() * 1000)}.jpg"
            gates.downscale(img, 512).save(name, "JPEG", quality=80)
            files = sorted(self.frames_dir.glob("*.jpg"))
            for old in files[:-self.args.keep_frames]:
                old.unlink(missing_ok=True)
        except OSError as e:
            self._log({"event": "frame_save_failed", "error": str(e)[:200]})


def snapshot(s, t):
    def med(d):
        return round(statistics.median(d), 1) if d else None

    with s.lock:
        frames, dec = s.frames_in, s.n_decisions
        out = {
            "time": now_iso(), "status": s.status, "detail": s.detail, "busy": s.busy,
            "gate": s.gate_name, "gate_info": s.gate_info, "lfm": s.lfm_info,
            "runway": t.view(), "decision": s.decision,
            "radio": list(s.radio)[-14:], "events": list(s.events)[-8:],
            "metrics": {
                "frames_in": frames, "decisions": dec, "skipped": s.n_skipped,
                "gate_ms_last": s.gate_ms[-1] if s.gate_ms else None, "gate_ms_median": med(s.gate_ms),
                "lfm_ms_last": s.lfm_ms[-1] if s.lfm_ms else None, "lfm_ms_median": med(s.lfm_ms),
                "lfm_tokens_median": med(s.lfm_tokens), "radio_calls": s.n_radio, "fallbacks": s.n_fallback,
                "loop_ms_last": s.loop_ms[-1] if s.loop_ms else None,
                "rss_mb": rss_mb(), "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                "uptime_s": round(time.time() - s.started),
            },
        }
    out["network"] = network_status()
    agent = getattr(s, "agent", None)
    out["voice"] = agent.voice.info() if agent else None
    return out


def make_handler(s, t):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CapyTower/1.0"

        def log_message(self, fmt, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/state":
                return self._send(200, snapshot(s, t))
            if path == "/api/decided.jpg":
                with s.lock:
                    jpg = s.decided_jpeg
                return self._send(200, jpg, "image/jpeg") if jpg else self._send(404, {"error": "no frame yet"})
            rel = "index.html" if path in ("/", "/index.html") else path[len("/static/"):] if path.startswith("/static/") else None
            if rel is None:
                return self._send(404, {"error": "not found"})
            f = (STATIC / rel).resolve()
            if STATIC not in f.parents or not f.is_file():
                return self._send(404, {"error": "not found"})
            return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            if n > 4_000_000:
                return self._send(413, {"error": "too large"})
            body = self.rfile.read(n)
            if u.path == "/api/frame":
                if not body.startswith(b"\xff\xd8"):
                    return self._send(400, {"error": "expected a JPEG"})
                source = parse_qs(u.query).get("source", ["camera"])[0][:16]
                with s.lock:
                    s.frame = (body, time.time(), source)
                    s.frames_in += 1
                return self._send(200, {"ok": True})
            if u.path == "/api/request":
                try:
                    kind = json.loads(body or b"{}").get("kind")
                except ValueError:
                    kind = None
                if kind not in ("takeoff", "landing"):
                    return self._send(400, {"error": "kind must be takeoff or landing"})
                s.requests.put(kind)
                return self._send(200, {"ok": True, "queued": kind})
            if u.path == "/api/baseline":
                with s.lock:
                    s.baseline = True
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="bind address; keep loopback and use SSH port forwarding")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--gate", choices=["d1", "rule"], default="d1")
    ap.add_argument("--model-dir", default="~/models/d1-2B", help="pinned d1-2B Transformers snapshot")
    ap.add_argument("--max-side", type=int, default=512, help="longest image side sent to d1 (smaller is faster)")
    ap.add_argument("--threads", type=int, default=0, help="torch CPU threads (0 = default)")
    ap.add_argument("--threshold", type=float, default=0.6, help="p_blocked at or above which the runway closes")
    ap.add_argument("--clear-threshold", type=float, default=0.4, help="p_blocked at or below which it reopens")
    ap.add_argument("--change", type=float, default=0.01, help="share of changed pixels that triggers a decision")
    ap.add_argument("--heartbeat", type=float, default=20.0, help="seconds between decisions when nothing changes")
    ap.add_argument("--poll", type=float, default=0.25, help="seconds between loop iterations")
    ap.add_argument("--server", default=DEFAULT_SERVER, help="GenieX OpenAI-compatible server")
    ap.add_argument("--llm", default=DEFAULT_MODEL)
    ap.add_argument("--compute", default="npu")
    ap.add_argument("--max-radio-tokens", type=int, default=48)
    ap.add_argument("--voice", choices=["lfm3", "espeak", "off"], default="espeak",
                    help="speak tower calls on the board speaker (lfm3 = LiquidAI LFM3-Audio via llama.cpp)")
    ap.add_argument("--no-lfm", action="store_true", help="template radio calls only (UI testing)")
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.add_argument("--log", default=str(HERE.parent / "logs" / "capy_tower.jsonl"))
    ap.add_argument("--save-frames", default=str(HERE.parent / "logs" / "frames"), help="'' to disable")
    ap.add_argument("--keep-frames", type=int, default=400)
    args = ap.parse_args()

    shared, tower = Shared(), tw.Tower(args.threshold, args.clear_threshold)
    agent = Agent(shared, tower, args)
    shared.agent = agent
    agent.start()
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(shared, tower))
    print(f"Capy Tower on http://{args.host}:{args.port}  (gate={args.gate}, log={args.log})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCapy Tower stopping.")


if __name__ == "__main__":
    main()
