#!/usr/bin/env python3
# Vendored unchanged from heath0xFF/cleared-for-takeoff-hackathon (skills/iq9-geniex-lfm/scripts/lfm_client.py),
# MIT License, Copyright (c) 2026 On-Device AI Hackathon contributors. See THIRD_PARTY.md.
"""Minimal client for LFM models behind `geniex serve` on the IQ-9075. Standard library only.

Copy this file into your app. It handles the board-specific traps:
  - every request is capped (max_completion_tokens on chat, max_tokens on completions)
  - zero-token or unusable replies are retried once with a unique tag
  - raw prompts are unique before the first request (opt out only for diagnostics)
  - sentence() uses a raw completion with LFM3's default reasoning block already closed
  - errors come back as data (ok=False, error=...), so a loop can log them and keep running

    from lfm_client import LFM
    lfm = LFM()                                    # http://127.0.0.1:18181, LFM3-1.7B Q4_0
    r = lfm.sentence("Explain this alert in one sentence: SoC 74 C, up 13 C in a minute.")
    r = lfm.chat([{"role": "user", "content": "Say hi."}], max_tokens=32)
    r = lfm.chat(messages, tools=[...])

CLI:
    python3 lfm_client.py --check                  # server up? which models?
    python3 lfm_client.py --sentence "Explain: SoC at 74 C, up from 61 C one minute ago."
    python3 lfm_client.py --chat "Say hello in five words." --max-tokens 32
"""

import argparse
import copy
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_SERVER = "http://127.0.0.1:18181"
DEFAULT_MODEL = "LiquidAI/LFM3-1.7B-GGUF:Q4_0"

# ChatML, as used by LFM3. The empty <think></think> block asks it to answer directly.
# Verify output and timing on the board before relying on this shortcut.
_TEMPLATE = ("<|startoftext|><|im_start|>system\n{SYSTEM}<|im_end|>\n"
             "<|im_start|>user\n{USER}<|im_end|>\n"
             "<|im_start|>assistant\n")
_CLOSED_THINK = "<think>\n\n</think>\n\n"
DEFAULT_SYSTEM = "You write one short, factual sentence. Reply with the sentence only."


class LFM:
    def __init__(self, server=DEFAULT_SERVER, model=DEFAULT_MODEL, compute="npu", timeout=60):
        self.server = server.rstrip("/")
        self.model = model
        self.compute = compute
        self.timeout = timeout

    # ---- server -----------------------------------------------------------------------------------

    def ready(self):
        try:
            with urllib.request.urlopen(self.server + "/v1/models", timeout=3) as r:
                return r.status == 200
        except OSError:
            return False

    def models(self):
        with urllib.request.urlopen(self.server + "/v1/models", timeout=5) as r:
            return [m["id"] for m in json.load(r)["data"]]

    def _post(self, path, body):
        cap = body.get("max_tokens" if path == "/v1/completions" else "max_completion_tokens")
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise ValueError("max_tokens must be a positive integer")
        req = urllib.request.Request(self.server + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.load(r)
        return data, round((time.perf_counter() - t0) * 1000, 1)

    # ---- requests ---------------------------------------------------------------------------------

    def chat(self, messages, max_tokens=128, tools=None, model=None, retry_zero=True, **extra):
        """POST /v1/chat/completions. Returns a dict: ok, text, tool_calls, tokens, finish, ms, retried, error.

        Reasoning alone is not an answer. Try enable_think=False for direct chat answers,
        or sentence() for the reference LFM3 template. Tool-call envelopes are checked here;
        the app must still validate argument schemas, allowlists, and action policy.
        """
        body = {**extra, "model": model or self.model, "messages": copy.deepcopy(messages),
                "max_completion_tokens": max_tokens, "compute": self.compute, "stream": False}
        if tools:
            body["tools"] = tools

        def parse(d, ms):
            c = d["choices"][0]
            m = c.get("message") or {}
            return {"text": (m.get("content") or "").strip(), "tool_calls": m.get("tool_calls") or [],
                    "tokens": d.get("usage", {}).get("completion_tokens", 0), "finish": c.get("finish_reason"),
                    "ms": ms, "raw_message": m}

        return self._with_retry(lambda: parse(*self._post("/v1/chat/completions", body)),
                                lambda: self._tag_messages(body), retry_zero, allow_tools=bool(tools))

    def complete(self, prompt, max_tokens=80, model=None, retry_zero=True, unique=True, **extra):
        """Raw completion. unique=False is for intentional repeated-prompt diagnostics only.

        retry_zero is retained for compatibility; it now retries unusable output too.
        """
        body = {**extra, "model": model or self.model, "prompt": self._tag_prompt(prompt) if unique else prompt,
                "max_tokens": max_tokens, "compute": self.compute, "stream": False}

        def parse(d, ms):
            c = d["choices"][0]
            return {"text": (c.get("text") or "").strip(), "tool_calls": [],
                    "tokens": d.get("usage", {}).get("completion_tokens", 0), "finish": c.get("finish_reason"),
                    "ms": ms}

        def tag():
            body["prompt"] = self._tag_prompt(body["prompt"])

        return self._with_retry(lambda: parse(*self._post("/v1/completions", body)), tag, retry_zero)

    def sentence(self, user, system=DEFAULT_SYSTEM, max_tokens=80, close_think=True, model=None, unique=True):
        """One direct sentence from a raw ChatML completion. close_think=True closes LFM3's
        default reasoning block. unique=False is for repeated-prompt diagnostics only."""
        prompt = _TEMPLATE.replace("{SYSTEM}", system).replace("{USER}", user)
        if close_think:
            prompt += _CLOSED_THINK
        return self.complete(prompt, max_tokens=max_tokens, model=model, unique=unique)

    # ---- internals --------------------------------------------------------------------------------

    @staticmethod
    def _tag_prompt(prompt):
        """Tag the last user turn before the assistant prefix; also works on plain prompts."""
        tag = f" [request:{uuid.uuid4().hex}]"
        head, sep, tail = prompt.rpartition("<|im_start|>assistant")
        if sep and "<|im_end|>" in head:
            user, end, suffix = head.rpartition("<|im_end|>")
            return user + tag + end + suffix + sep + tail
        return f"Request {uuid.uuid4().hex}\n" + prompt

    @staticmethod
    def _tag_messages(body):
        """Make the request unique for the zero-token retry: tag the last user message."""
        for m in reversed(body["messages"]):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                m["content"] += f" [request:{uuid.uuid4().hex}]"
                return
        for m in body["messages"]:
            if m.get("role") == "system" and isinstance(m.get("content"), str):
                m["content"] += f" [request:{uuid.uuid4().hex}]"
                return
        body["messages"].insert(0, {"role": "system", "content": f"Request {uuid.uuid4().hex}."})

    @staticmethod
    def _output_error(r, allow_tools=False):
        tokens = r.get("tokens")
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
            return "zero or missing completion tokens"
        calls = r.get("tool_calls") or []
        if calls:
            if not allow_tools or not isinstance(calls, list):
                return "unexpected or malformed tool_calls"
            ids = set()
            for call in calls:
                if not isinstance(call, dict):
                    return "malformed tool call"
                fn, cid = call.get("function"), call.get("id")
                if (call.get("type") != "function" or not isinstance(cid, str) or not cid
                        or cid in ids or not isinstance(fn, dict)
                        or not isinstance(fn.get("name"), str) or not fn["name"].strip()
                        or not isinstance(fn.get("arguments"), str)):
                    return "malformed tool-call envelope"
                ids.add(cid)
            return None  # Argument schemas and policy belong to the app, before execution.
        if not isinstance(r.get("text"), str) or not r["text"].strip():
            return "empty answer (reasoning alone is not usable output)"
        return None

    @staticmethod
    def _with_retry(call, make_unique, retry_zero, allow_tools=False):
        out = {"ok": False, "text": "", "tool_calls": [], "tokens": 0, "finish": None, "ms": None,
               "retried": False, "error": None}
        try:
            r = call()
            error = LFM._output_error(r, allow_tools)
            if retry_zero and error:
                out["retried"] = True
                make_unique()
                r = call()
                error = LFM._output_error(r, allow_tools)
            out.update(r)
            out["ok"] = error is None
            if error:
                out["error"] = error + (" after retry" if out["retried"] else "")
        except urllib.error.HTTPError as e:
            out["error"] = f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
        except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError, IndexError, AttributeError) as e:
            out["error"] = f"{type(e).__name__}: {e}"[:200]
        return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-tokens", type=int, default=80)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="is the server up, and which models does it list")
    g.add_argument("--sentence", metavar="TEXT", help="one direct sentence (raw completion, closed think block)")
    g.add_argument("--chat", metavar="TEXT", help="one chat request (LFM3 replies may include reasoning)")
    args = ap.parse_args()

    lfm = LFM(args.server, args.model)
    if args.check:
        if not lfm.ready():
            sys.exit(f"no GenieX server at {args.server}. Start one: geniex serve --compute npu")
        print(f"server up at {args.server}")
        for m in lfm.models():
            print(f"  {m}")
        return
    if not lfm.ready():
        sys.exit(f"no GenieX server at {args.server}. Start one: geniex serve --compute npu")
    if args.sentence:
        r = lfm.sentence(args.sentence, max_tokens=args.max_tokens)
    else:
        r = lfm.chat([{"role": "user", "content": args.chat}], max_tokens=args.max_tokens)
    print(r["text"] or "(empty)")
    print(json.dumps({k: r[k] for k in ("ok", "tokens", "finish", "ms", "retried", "error")}))
    sys.exit(0 if r["ok"] else 2)


if __name__ == "__main__":
    main()
