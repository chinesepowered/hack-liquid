# Capy Tower 🐾✈️

**An always-on control tower for runways nobody is watching.** Capy Tower watches a runway camera, spots a capybara (or anything else) on the runway, orders the go-around, closes the runway, dispatches the wildlife crew, and talks to pilots in FAA phraseology. It runs entirely on a **Qualcomm Dragonwing IQ-9075** with **LiquidAI LFM3-family models**: no cloud, no API keys, no network.

> On November 13, 2026, a communications failure at the FAA grounded every departure in the United States. That same evening we built a tower that does not need the network at all.

Built at the *On-Device AI Hackathon: Cleared for Takeoff* (LiquidAI x Qualcomm), San Francisco, by **Team chinese** ([@chinesepowered](https://x.com/chinesepowered) on X).

## What it does

- **Watches** the runway camera: a laptop camera, or a simulated runway, streams frames to the board.
- **Decides** with **d1-2B**, LiquidAI's decision model built on LFM3-VL-2B. One forward pass answers two typed questions per frame: *is anything on the runway?* (a calibrated probability) and *what is it?* (capybara, other wildlife, person, vehicle, debris, nothing). A cheap pixel-change gate skips frames where nothing moved.
- **Acts** through an allowlist of ten tower actions. When the runway becomes blocked it orders a **go-around** for traffic cleared to land, cancels a takeoff roll, **closes the runway**, and dispatches the **wildlife crew**, sweeper, or security.
- **Talks**: **LFM3-1.7B on the Hexagon NPU** writes every radio call. Code chooses the instruction; the generated call must contain it, must use the exact callsign, and must not contain words that contradict it (a go-around may never say "cleared"), or a fixed template is sent instead.
- **Acts on its own**: aircraft told to hold or go around are cleared automatically once the runway is clear again, arrivals first.
- **Logs** every decision, action and radio call to `logs/capy_tower.jsonl`, and shows them live on the tower screen together with on-device timings.

## Why not a cloud API call?

1. **The network is the failure mode.** The FAA's nationwide ground stop on November 13, 2026 started with a communications failure. A safety system that needs a network goes down with it. Capy Tower makes no off-board calls: the judge turns the board's Wi-Fi off and it keeps working.
2. **Seconds matter.** A go-around has to be called as soon as something wanders onto the runway, with no round trip, rate limit or outage in the path.
3. **Most US airports have no control tower**, and many have poor connectivity. Streaming runway video to a cloud model around the clock costs bandwidth and per-call fees; here the marginal cost is zero, and the change gate keeps the model idle while nothing moves.
4. **Privacy.** Camera frames never leave the board.

## How it works

```
 laptop browser                                   Qualcomm Dragonwing IQ-9075 (everything below runs here)
 --------------                                   ---------------------------------------------------------
 laptop camera  ┐                                 observe   latest frame
 or SIM runway  ┴─ JPEG over the isolated  ──▶    gate      pixel change? (unchanged frames are skipped)
                   USB-C link (USB NCM)           decide    d1-2B · CPU · Transformers system_one()
                                                            p(something on the runway), what is it
 tower screen  ◀── /api/state (poll) ─────────    policy    close at p >= 0.6, reopen at p <= 0.4, fail safe
                                                  act       allowlisted: go_around, close_runway, hold_short, ...
                                                  talk      LFM3-1.7B Q4_0 · Hexagon NPU · GenieX -> radio call,
                                                            checked for the mandatory instruction
                                                  log       logs/capy_tower.jsonl (flushed every iteration)
```

| Job | Model | Runtime | Compute |
|---|---|---|---|
| Runway decision | `LiquidAI/d1-2B`, pinned revision `10e7671d44e4` | Transformers 5.19.0 `system_one()`, fp32 | IQ-9075 CPU (8 cores) |
| Radio calls | `LiquidAI/LFM3-1.7B-GGUF:Q4_0` (QAD) | GenieX v0.10.0 (QAIRT 2.50), OpenAI-compatible server on `127.0.0.1:18181` | Hexagon NPU (`HTP0`) |

d1 and the LFM run one after the other in a single loop, as the hackathon's reference stack requires. The browser is only a sensor and a display: it never runs a model and never talks to anything but the board.

## On-device numbers

Measured on the IQ-9075 during our rehearsal (simulated runway, full demo script). Live values are on the tower screen and in `logs/capy_tower.jsonl`.

| Metric | Value |
|---|---|
| d1-2B decision, CPU, fp32 (one 640x400 frame, two questions, 352 input tokens, 0 output tokens) | 7.6 s median |
| d1-2B capybara detection | p(blocked) 0.99, "capybara" 0.99; empty runway p(blocked) 0.05 |
| d1-2B model load | 3.9 s |
| LFM3-1.7B radio call, NPU, end to end | 0.61 s median, 18 tokens median |
| Generated calls that passed the safety check | 7 of 7 (0 template fallbacks) |
| App memory (RSS, includes d1 in fp32) | 11.9 GB of 36 GB |
| Off-board network calls | none |

The 7.6 s decision is the slow part: d1 runs in fp32 on the CPU, which is the hackathon's verified d1 route. The change gate means it only runs when the picture changes. Next step: d1 on the NPU through ZETIC's native `d1-2B-IQ9` package.

## Run it on the board

The board starts as a fresh Ubuntu 24.04 image. While it has internet:

```bash
SUDO_PW=... scripts/board_setup.sh geniex   # NPU packages, fastrpc group, GenieX v0.10.0, LFM3-1.7B Q4_0
scripts/board_setup.sh d1                   # uv, d1 venv with CPU-only torch, pinned d1-2B snapshot
~/.local/bin/uv pip install --python ~/.venvs/d1/bin/python "transformers==5.19.0"
```

Pin Transformers to 5.19.0: newer releases break d1-2B's bundled model code (`can_use_lfm3_conv`). Install CPU-only torch: the default aarch64 wheels pull gigabytes of CUDA libraries.

Then, with GenieX serving (`skills/iq9-geniex-lfm/scripts/serve.sh run` from the [hackathon repo](https://github.com/heath0xFF/cleared-for-takeoff-hackathon)):

```bash
sudo scripts/usb_link.sh a600000.usb   # USB-C network link to the laptop, board at 169.254.7.2
scripts/run_board.sh                   # Capy Tower on 127.0.0.1:8000
```

On the laptop, with a USB-C cable to the board's USB-C port (Windows 11 binds its inbox NCM driver and takes a 169.254.x.x address on its own):

```bash
ssh -N -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@169.254.7.2
```

Open `http://127.0.0.1:8000` and pick **Simulated runway** or **Laptop camera** (browsers allow the camera on `127.0.0.1`).

- No d1 yet? `scripts/run_board.sh --gate rule` uses a pixel rule against an empty-runway baseline.
- Screen test anywhere, no models: `python3 capy_tower/app.py --gate rule --no-lfm` (needs Pillow).

## The two-minute demo

1. Board console: `sudo nmcli radio wifi off`, then `nmcli -p device`. The header turns to **NO UPLINK · offline**.
2. **Cirrus 7CP: on final**: *"Cirrus seven-charlie-papa, runway two-eight, cleared to land."*
3. **Capybara wanders on**: d1 flags it, then *"Cirrus seven-charlie-papa, go around, capybara on the runway."* The runway closes and the wildlife crew is called.
4. **Cessna 28A: ready for departure**: *"Cessna two-eight-alpha, hold short runway two-eight, a capybara on the runway."*
5. **Clear the runway**: the runway reopens, then the Cirrus is cleared to land with no further input.
6. Point at the decision log and the on-device numbers.

With the laptop camera, a capybara photo on a phone (`capy_tower/static/img/capybara.jpg`) held over a paper runway plays the capybara.

## Safety design

- **Fail safe.** An uncertain first reading closes the runway; hysteresis (close at 0.6, reopen at 0.4) stops flapping.
- **The language model never decides.** Code picks every instruction from the d1 decision; LFM3 only phrases it, and its text must carry the instruction and exact callsign, and no contradicting words, or the template is sent.
- **Allowlist.** Only ten named actions can execute; anything else is logged as refused.
- **Errors are data.** Failed decisions or radio calls are logged and the loop keeps watching.

## Repository map

| Path | What |
|---|---|
| `capy_tower/app.py` | The always-on loop and the board-hosted web server (standard library) |
| `capy_tower/gates.py` | d1-2B gate (Transformers, CPU) and the pixel-rule fallback |
| `capy_tower/tower.py` | Runway policy, traffic, allowlisted actions, radio prompts, templates and checks |
| `capy_tower/lfm_client.py` | Capped, validated GenieX client from the hackathon repo (MIT) |
| `capy_tower/static/` | The tower screen: plain HTML, CSS and JavaScript, no CDN |
| `scripts/board_setup.sh` | Fresh-board setup: NPU packages, GenieX, LFM3, d1 |
| `scripts/usb_link.sh` | Isolated USB-C network link (USB NCM gadget) |
| `scripts/run_board.sh` | Launcher with board checks |
| `logs/capy_tower.jsonl` | Decision log |

Code: MIT (see `LICENSE`). Third-party material and model licenses: see `THIRD_PARTY.md`.
