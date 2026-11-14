# Arduino Project Hub post (paste-ready)

**Title:** Capy Tower: an offline AI control tower on the Qualcomm Dragonwing IQ-9075

**One-line description (the "Description" field):** An always-on runway monitor that spots a capybara on the runway, orders the go-around and talks to pilots, with every model running on a Dragonwing IQ-9075 and zero network.

**Tags:** on-device AI, Qualcomm Dragonwing, IQ-9075, LiquidAI, LFM3, d1-2B, edge AI, aviation, offline

**Difficulty:** Advanced · **Time:** 2 hours (hackathon build)

**Components and supplies:**
- Qualcomm Dragonwing IQ-9075 EVK (QCS9075, Hexagon v73 NPU, 36 GB LPDDR5), Ubuntu 24.04 ×1
- USB-C cable (board USB-C port to laptop: isolated control and UI link) ×1
- Micro-USB cable (board debug UART, used for setup) ×1
- Laptop with a browser (screen and optional camera only; no inference) ×1

**Apps and platforms:** Qualcomm GenieX v0.10.0, LiquidAI LFM3-1.7B (GGUF Q4_0), LiquidAI d1-2B, Hugging Face Transformers, Python 3.12

**Cover image:** `docs/img/board_closed.png`

---

## The story

On November 13, 2026, a communications failure at the FAA grounded every departure in the United States. That same evening, at the LiquidAI × Qualcomm "Cleared for Takeoff" hackathon, we asked what an airport safety system looks like if it cannot depend on the network at all.

Most US airports have no control tower. Nobody is watching the runway when a deer, a dog, a loose cone, or a capybara wanders onto it. **Capy Tower** is an always-on tower in a box: it watches a runway camera, decides whether the runway is blocked, orders the go-around, closes the runway, calls the wildlife crew, and reopens and clears traffic on its own once the runway is clear. Every model runs on the Dragonwing IQ-9075. Turn the Wi-Fi off and it keeps working.

## What it does

1. **Watch.** A laptop camera or a simulated runway streams frames to the board over an isolated USB-C link. A pixel-change gate skips frames where nothing moved.
2. **Decide.** LiquidAI **d1-2B**, a decision model built on LFM3-VL-2B, answers two typed questions in one forward pass with zero generated tokens: *is anything on the runway?* (a probability) and *what is it?* (capybara, wildlife, person, vehicle, debris, nothing).
3. **Act.** Plain code turns the decision into allowlisted tower actions: go around, cancel takeoff, close runway, hold short, dispatch the wildlife crew, sweeper or security, reopen, clear to land, clear for takeoff. Close at p ≥ 0.6, reopen at p ≤ 0.4, and an uncertain first reading fails safe.
4. **Talk.** **LFM3-1.7B on the Hexagon NPU** (GenieX) writes each radio call in FAA phraseology. The language model never decides: every call must contain the required instruction and exact callsign and no contradicting words (a go-around may never say "cleared"), or a fixed template is sent.
5. **Log.** Every decision, action and radio call goes to a flushed JSONL log and the live tower screen.

## Why not a cloud API?

- **The network is the failure mode.** The FAA ground stop began with a communications failure. A safety system that needs the network fails with it.
- **Seconds matter.** A go-around call cannot wait on a round trip, a rate limit or an outage.
- **Cost and bandwidth.** Streaming runway video to a cloud model all day at thousands of untowered airports is expensive; here the marginal cost is zero.
- **Privacy.** Camera frames never leave the board.

## Architecture

| Job | Model | Runtime | Compute |
|---|---|---|---|
| Runway decision | LiquidAI d1-2B (rev 10e7671d44e4) | Transformers 5.19.0, `system_one()`, fp32 | IQ-9075 CPU |
| Radio calls | LiquidAI LFM3-1.7B-GGUF Q4_0 (QAD) | GenieX v0.10.0, QAIRT 2.50, loopback server | Hexagon NPU (HTP0) |

The browser is only a sensor and a display. The app server, both models and the log all live on the board, bound to loopback and reached from the laptop through an SSH tunnel over a USB NCM gadget link (`scripts/usb_link.sh`).

## Measured on the IQ-9075

| Metric | Value |
|---|---|
| d1-2B decision, CPU fp32, one frame, two questions | 7.6 s median |
| d1-2B on the capybara frame | p(blocked) 0.99, "capybara" 0.99 |
| d1-2B on the empty runway | p(blocked) 0.05 |
| LFM3-1.7B radio call, NPU, end to end | 0.61 s median, 18 tokens |
| Generated calls passing the safety check (offline run) | 11 of 11 |
| App memory | 11.9 GB of 36 GB |
| Off-board network calls | none (verified with Wi-Fi off, no route) |

## The offline demo

1. On the board: `sudo nmcli radio wifi off`. The screen shows **NO UPLINK · offline**.
2. The Cirrus on final is cleared to land.
3. A capybara wanders onto the runway. d1 flags it at 99%. *"Cirrus seven-charlie-papa, go around, capybara on the runway."* The runway closes and the wildlife crew is called.
4. The Cessna asks to depart and is told to hold short.
5. The capybara leaves. The runway reopens and traffic is cleared automatically, with no human input.

## Build it

Everything is in the repository: https://github.com/chinesepowered/hack-liquid

```bash
SUDO_PW=... scripts/board_setup.sh geniex   # NPU packages, GenieX v0.10.0, LFM3-1.7B Q4_0
scripts/board_setup.sh d1                   # d1 venv (CPU torch), pinned d1-2B snapshot
~/.local/bin/uv pip install --python ~/.venvs/d1/bin/python "transformers==5.19.0"
sudo scripts/usb_link.sh a600000.usb        # USB-C link, board at 169.254.7.2
scripts/run_board.sh                        # Capy Tower on 127.0.0.1:8000
```

Laptop: `ssh -N -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@169.254.7.2`, then open http://127.0.0.1:8000.

Lessons from a fresh board: set the clock before HTTPS works, install CPU-only torch (the default aarch64 wheels pull gigabytes of CUDA libraries), pin Transformers 5.19.0 for d1-2B's bundled code, and use the board's USB-C port as an NCM gadget when the venue Wi-Fi isolates clients.

## What's next

- d1-2B on the NPU through ZETIC's native `d1-2B-IQ9` package, to cut the 7.6 s decision.
- A real outdoor camera, and spoken calls with LFM3-Audio on the board.
- Thresholds calibrated on labeled runway footage instead of a simulated runway.

## Code

The full source code is attached (main files below) and on GitHub: https://github.com/chinesepowered/hack-liquid. Attach `capy_tower/app.py`, `capy_tower/gates.py`, `capy_tower/tower.py`, `capy_tower/static/app.js` and `scripts/usb_link.sh` in the Code section.

**Team chinese** · [@chinesepowered](https://x.com/chinesepowered) on X
