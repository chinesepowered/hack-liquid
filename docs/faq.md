# Capy Tower: questions judges might ask

## Why it has to be on-device

**Why not just call a cloud API?**
Because the network is the failure mode. Today's nationwide ground stop started with a communications failure; a safety system that needs the network fails with it. A go-around also cannot wait for a round trip, a rate limit or an outage. Watching a runway all day at thousands of airfields would mean a per-call bill and constant video upload; here the marginal cost is zero and the video never leaves the airfield.

**How do we know nothing leaves the board?**
The judge turned the Wi-Fi off in front of you, the board has no route out (`ip route` shows only the USB-C link), and the header reads the kernel routing table live. The app server, the model servers and the log bind to the board's loopback. The code makes no outside calls; the organizers can check the repo. Even the voice is generated and played on the board.

**What is the laptop doing?**
Only showing the screen and supplying camera frames. No inference runs on it. It reaches the board over a direct USB-C cable (a USB network gadget on the board) with no internet path.

## The models

**Which models, and where do they run?**
Three LiquidAI LFM3-family models, all on the IQ-9075:
- **d1-2B** (decision model, built on LFM3-VL-2B) decides what is on the runway. CPU, through Transformers.
- **LFM3-1.7B** (Q4_0 GGUF) writes each radio call. **Hexagon NPU**, through Qualcomm GenieX v0.10.0; the GenieX log confirms `HTP0`.
- **LFM3-Audio-2B** is Capy's voice on the board's speaker. CPU, through llama.cpp.

**Why separate models instead of one?**
Each does what it is built for. d1 answers typed questions in one forward pass with zero output tokens and returns probabilities, which code can threshold, log and audit. LFM3-1.7B is a small generator for natural language. LFM3-Audio turns the call into speech. The safety-critical judgement never depends on free text.

**Why is d1 on the CPU and not the NPU?**
The CPU route is the hackathon's verified path for d1 and we had two hours from a blank board. The next step is ZETIC's native `d1-2B-IQ9` package, which runs d1 on the NPU.

**7.6 seconds per decision is slow. Is that a problem?**
For the demo it is noticeable; for the use case it is workable, and we designed around it: a pixel-change gate means d1 only runs when the picture changes, and a hazard that walks onto a runway stays there for more than a few seconds. Moving d1 to the NPU is the real fix. The radio call itself takes about 0.6 s on the NPU.

**Couldn't you just send smaller images to d1?**
We measured it on the board. Shrinking frames from 512 px to 384 or 256 px only saved 1 to 2 s (about 7.7 s down to about 6 s), because most of d1's input is the question text, not the image. It also pushed the empty runway's score from about 0.23 up to 0.42 to 0.55, close to the 0.6 closing threshold, which would mean false closures. We kept 512 px.

**How accurate is it?**
We checked 8 realistic runway hazards on the board, the kinds that actually close runways: wildlife, debris, ground vehicles, people and drones. All 8 closed the runway with the right category:

| Hazard | P(blocked) | d1's answer |
|---|---|---|
| Baggage tug | 96% | vehicle 77% |
| Stray dog | 95% | wildlife 88% |
| Debris (traffic cone) | 95% | debris 93% |
| Coyote | 92% | wildlife 78% |
| Deer | 91% | wildlife 87% |
| Canada goose | 91% | wildlife 59% |
| Drone | 88% | vehicle 74% |
| Person on foot | 78% | person 69% |

The empty runway scores 5% to 25%. A distant flock of geese was missed because each bird was only a few pixels; a real install would use a zoomed runway camera. We have not calibrated on real runway footage yet.

**How is "blocked" decided?**
d1 answers two questions: "is anything on the runway?" (yes/no) and "what is it?" (capybara, wildlife, person, vehicle, debris, nothing). The runway counts as blocked by the stronger signal: the yes/no probability or 1 minus P(nothing). It closes at 0.6 and reopens at 0.4 so it does not flap, and an uncertain first reading closes it (fail safe).

## The voice

**Is that voice generated on the board?**
Yes. Capy speaks with LiquidAI **LFM3-Audio-2B**, generated on the IQ-9075 with llama.cpp and played on the board's speaker. Nothing is streamed from anywhere.

**Why are the calls pre-rendered?**
Live LFM3-Audio runs at about 0.45x real time on the board's CPU: a 5-second call took about 16 s, including loading the model. A go-around cannot wait that long. So we render the tower's standard calls once on the board (about 35 phrases, `scripts/render_voice.py`) and play the matching clip instantly. The clip carries the safety-checked instruction, so the words you hear can differ slightly from the LFM3-1.7B text on screen, but the instruction is always the same.

**What if a call is not in the phrasebook?**
It is spoken by Piper, a small neural text-to-speech model that also runs on the board (about 1.3 s per call), with espeak-ng as a last resort. Speech runs on its own thread, so it never delays a decision.

**How would you make LFM3-Audio live?**
Keep the model resident in a llama.cpp server instead of reloading it per call, and move it to the NPU. Then the phrasebook becomes a cache rather than a requirement.

## Safety

**What if the language model says something wrong?**
It cannot decide anything. Code picks every instruction from the d1 decision; LFM3 only phrases it. Before a call goes out, a checker requires the exact instruction ("go around"), the exact callsign, runway 28 only, no contradicting words (a go-around may never say "cleared"), a short length and no stray digits. Anything that fails is replaced by a fixed template and logged. In our offline rehearsal 11 of 11 generated calls passed.

**What can the system actually do?**
Only ten allowlisted actions: go around, cancel takeoff, close runway, hold short, dispatch wildlife crew, dispatch sweeper, alert security, reopen, clear to land, clear for takeoff. Anything else is logged as refused.

**What if two cameras or screens send pictures at once?**
Only one screen owns the runway camera: whichever loaded or was clicked most recently. Frames from any other screen are ignored, so conflicting pictures cannot make the runway flap. We found this case while recording our own demo video.

**Would this replace air traffic controllers?**
No. It is for the thousands of airports with no tower at all, where today nobody is watching. It is an advisory system: it alerts pilots and airport ops. Certification and FAA approval would be required before anything like this talks to real aircraft.

## Aircraft and traffic

**Does it detect aircraft too?**
The camera's job is obstacles on the runway. The two aircraft in the demo are the traffic Capy manages; their calls come from the pilot buttons. A real deployment would take traffic from the radio or ADS-B. d1's "vehicle" category includes aircraft, so a plane taxiing onto an active runway (a runway incursion) would likely be flagged as blocked, but we have not tested that case.

**Can it understand real pilots on the radio?**
Not yet. LFM3-Audio can also transcribe speech, and it is already on the board, so radio transcription is the natural next step.

## The build

**What did you build during the event?**
Everything, starting from a freshly flashed board: NPU packages and GenieX, model staging, the USB-C network link, the agent loop, policy and safety checks, the tower screen, preset hazards checked on the board, Capy's on-board voice, boot units, the deck and two demo videos. The repo history shows it.

**What was hard?**
Venue Wi-Fi isolated devices from each other, so we turned the board's USB-C port into a USB network adapter. The board clock was wrong, which broke HTTPS. The default ARM torch wheels pulled gigabytes of CUDA libraries, so we installed CPU-only torch. Newer Transformers broke d1's bundled code, so we pinned 5.19.0. And LFM3-Audio was too slow to speak live, so we pre-render its phrasebook on the board.

**How much memory does it use?**
About 12 GB of the board's 36 GB for the app, mostly d1 in fp32. LFM3-1.7B at 4 bits is about 1 GB. LFM3-Audio peaks at about 4 GB while rendering.

**What would you do next?**
d1 on the NPU (ZETIC), LFM3-Audio resident and live, radio transcription with LFM3-Audio, a real outdoor runway camera with calibrated thresholds, and ADS-B traffic input.

**Why a capybara?**
Capybaras are famously unbothered. When the network goes down, Capy stays chill.
