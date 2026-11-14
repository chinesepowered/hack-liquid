# Capy Tower 🐾✈️

**An always-on control tower for runways nobody is watching.** Capy Tower watches a runway camera, spots a capybara (or anything else) on the runway, orders the go-around, closes the runway, dispatches the wildlife crew, and talks to pilots in FAA phraseology. It runs entirely on a **Qualcomm Dragonwing IQ-9075** with **LiquidAI LFM3-family models**: no cloud, no API keys, no network.

> On November 13, 2026, a communications failure at the FAA grounded every departure in the United States. That same evening we built a tower that does not need the network at all.

Built at the *On-Device AI Hackathon: Cleared for Takeoff* (LiquidAI × Qualcomm), San Francisco, by **Team chinese** ([@chinesepowered](https://x.com/chinesepowered) on X).

## What it does

- **Watches** the runway camera: a laptop camera, or a simulated runway, streams frames to the board.
- **Decides** with **d1-2B**, LiquidAI's decision model built on LFM3-VL-2B. One forward pass answers two typed questions per frame: *is anything on the runway?* (a calibrated probability) and *what is it?* (capybara, other wildlife, person, vehicle, debris, nothing). A cheap pixel-change gate skips frames where nothing moved.
- **Acts** through an allowlist of ten tower actions. When the runway becomes blocked it orders a **go-around** for traffic cleared to land, cancels a takeoff roll, **closes the runway**, and dispatches the **wildlife crew**, sweeper, or security.
- **Talks**: **LFM3-1.7B on the NPU** writes every radio call. Code chooses the instruction; the generated call must contain it (for example "go around" plus the callsign), or a fixed template is sent instead.
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
 ─────────────                                    ─────────────────────────────────────────────────────────
 laptop camera  ┐                                 observe   latest frame
 or SIM runway  ┴─ JPEG over the isolated  ──▶    gate      pixel change? (unchanged frames are skipped)
                   USB-C / SSH link               decide    d1-2B · CPU · Transformers system_one()
                                                            p(something on the runway), what is it
 tower screen  ◀── /api/state (poll) ─────────    policy    close at p ≥ 0.6, reopen at p ≤ 0.4, fail safe
                                                  act       allowlisted: go_around, close_runway, hold_short, …
                                                  talk      LFM3-1.7B Q4_0 · Hexagon NPU · GenieX → radio call,
                                                            checked for the mandatory instruction
                                                  log       logs/capy_tower.jsonl (flushed every iteration)
```

| Job | Model | Runtime | Compute |
|---|---|---|---|
| Runway decision | `LiquidAI/d1-2B`, pinned revision `10e7671d44e4` | Transformers `system_one()`, fp32 | IQ-9075 CPU |
| Radio calls | `LiquidAI/LFM3-1.7B-GGUF:Q4_0` (QAD) | GenieX v0.10.0, OpenAI-compatible server on `127.0.0.1:18181` | Hexagon NPU (`HTP0`) |

d1 and the LFM run one after the other in a single loop, as the hackathon's reference stack requires. The browser is only a sensor and a display: it never runs a model and never talks to anything but the board.

## Run it on the board

Prerequisites, from the [hackathon repo](https://github.com/heath0xFF/cleared-for-takeoff-hackathon): GenieX serving `LiquidAI/LFM3-1.7B-GGUF:Q4_0` on the NPU (`skills/iq9-geniex-lfm/scripts/serve.sh run`), the d1-2B snapshot at `~/models/d1-2B`, and the d1 venv at `~/.venvs/d1` (`examples/system-one-decision`).

```bash
git clone https://github.com/chinesepowered/hack-liquid && cd hack-liquid
scripts/run_board.sh
```

On the laptop, forward the screen over the USB-C link (no internet sharing on the laptop):

```bash
ssh -N -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@<board-usb-ip>
```

Open `http://127.0.0.1:8000` and pick **Simulated runway** or **Laptop camera** (browsers allow the camera on `127.0.0.1`).

- No d1 yet? `scripts/run_board.sh --gate rule` uses a pixel rule against an empty-runway baseline.
- Slow decisions? `--max-side 384` sends smaller images to d1.
- Screen test anywhere, no models: `python3 capy_tower/app.py --gate rule --no-lfm` (needs Pillow).

## The two-minute demo

1. Board console: `sudo nmcli radio wifi off`, then `nmcli -p device`. The header turns to **NO UPLINK · offline**.
2. **Cirrus 7CP: on final** → *"Cirrus seven-charlie-papa, runway two-eight, cleared to land."*
3. **Capybara wanders on** → d1 flags it → *"Cirrus seven-charlie-papa, go around, capybara on the runway."* The runway closes and the wildlife crew is called.
4. **Cessna 28A: ready for departure** → *"hold short runway two-eight, capybara on the runway."*
5. **Clear the runway** → the runway reopens, the Cirrus is cleared to land, then the Cessna is cleared for takeoff, with no further input.
6. Point at the decision log and the on-device numbers.

With the laptop camera, a capybara photo on a phone (`capy_tower/static/img/capybara.jpg`) held over a paper runway plays the capybara.

## On-device numbers

Measured on the IQ-9075 during our rehearsal; the live values are on the tower screen and in `logs/capy_tower.jsonl`.

| Metric | Value |
|---|---|
| d1-2B decision, CPU (one frame, two questions) | _filled in after the rehearsal_ |
| LFM3-1.7B radio call, NPU (end to end, ~20 tokens) | _filled in after the rehearsal_ |
| Frames skipped by the change gate | _filled in after the rehearsal_ |
| App memory (RSS, includes d1 in fp32) | _filled in after the rehearsal_ |

## Safety design

- **Fail safe.** An uncertain first reading closes the runway; hysteresis (close at 0.6, reopen at 0.4) stops flapping.
- **The language model never decides.** Code picks every instruction from the d1 decision; LFM3 only phrases it, and its text must contain the mandatory instruction and callsign or the template is sent.
- **Allowlist.** Only ten named actions can execute; anything else is logged as refused.
- **Errors are data.** Failed decisions or radio calls are logged and the loop keeps watching.

## Repository map

| Path | What |
|---|---|
| `capy_tower/app.py` | The always-on loop and the board-hosted web server (standard library) |
| `capy_tower/gates.py` | d1-2B gate (Transformers, CPU) and the pixel-rule fallback |
| `capy_tower/tower.py` | Runway policy, traffic, allowlisted actions, radio prompts and templates |
| `capy_tower/lfm_client.py` | Capped, validated GenieX client from the hackathon repo (MIT) |
| `capy_tower/static/` | The tower screen: plain HTML, CSS and JavaScript, no CDN |
| `scripts/run_board.sh` | Launcher with board checks |
| `logs/capy_tower.jsonl` | Decision log |

Code: MIT (see `LICENSE`). Third-party material and model licenses: see `THIRD_PARTY.md`.
