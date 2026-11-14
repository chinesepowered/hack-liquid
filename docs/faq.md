# Capy Tower: questions judges might ask

## Why it has to be on-device

**Why not just call a cloud API?**
Because the network is the failure mode. Today's nationwide ground stop started with a communications failure; a safety system that needs the network fails with it. A go-around also cannot wait for a round trip, a rate limit or an outage. Watching a runway all day at thousands of airfields would mean a per-call bill and constant video upload; here the marginal cost is zero and the video never leaves the airfield.

**How do we know nothing leaves the board?**
The judge turned the Wi-Fi off in front of you, the board has no route out (`ip route` shows only the USB-C link), and the header reads the kernel routing table live. The app server, both model servers and the log bind to the board's loopback. The code makes no outside calls; the organizers can check the repo.

**What is the laptop doing?**
Only showing the screen and supplying camera frames. No inference runs on it. It reaches the board over a direct USB-C cable (a USB network gadget on the board) with no internet path.

## The models

**Which models, and where do they run?**
LiquidAI **d1-2B** (LFM3 family decision model, built on LFM3-VL-2B) on the IQ-9075's CPU through Transformers, and LiquidAI **LFM3-1.7B** (Q4_0 GGUF) on the **Hexagon NPU** through Qualcomm GenieX v0.10.0. The GenieX log confirms the NPU (`HTP0`).

**Why two models instead of one?**
Each does what it is built for. d1 answers typed questions in one forward pass with zero output tokens and returns probabilities, which code can threshold, log and audit. LFM3 is a small generator for natural language. The safety-critical judgement never depends on free text.

**Why is d1 on the CPU and not the NPU?**
The CPU route is the hackathon's verified path for d1 and we had two hours from a blank board. The next step is ZETIC's native `d1-2B-IQ9` package, which runs d1 on the NPU.

**7.6 seconds per decision is slow. Is that a problem?**
For the demo it is noticeable; for the use case it is workable, and we designed around it: a pixel-change gate means d1 only runs when the picture changes, and a hazard that walks onto a runway stays there for more than a few seconds. Moving d1 to the NPU is the obvious speed-up. The radio call itself takes about 0.6 s on the NPU.

**How accurate is it?**
We checked 8 realistic hazard photos on the board: all 8 closed the runway with the right category (78% to 96% confidence; deer 91%, baggage tug 96%, debris 95%). The empty runway scores 5% to 14%. A flock of distant geese was missed because the birds were only a few pixels each; that is a camera-placement problem a real install would solve with a zoomed runway camera. We have not calibrated on real runway footage yet.

**How is "blocked" decided?**
d1 answers two questions: "is anything on the runway?" (yes/no) and "what is it?" (capybara, wildlife, person, vehicle, debris, nothing). The runway counts as blocked by the stronger signal: the yes/no probability or 1 minus P(nothing). It closes at 0.6 and reopens at 0.4 so it does not flap, and an uncertain first reading closes it (fail safe).

## Safety

**What if the language model says something wrong?**
It cannot decide anything. Code picks every instruction from the d1 decision; LFM3 only phrases it. Before a call goes out, a checker requires the exact instruction ("go around"), the exact callsign, runway 28 only, no contradicting words (a go-around may never say "cleared"), a short length and no stray digits. Anything that fails is replaced by a fixed template and logged. In our offline rehearsal 11 of 11 generated calls passed.

**What can the system actually do?**
Only ten allowlisted actions: go around, cancel takeoff, close runway, hold short, dispatch wildlife crew, dispatch sweeper, alert security, reopen, clear to land, clear for takeoff. Anything else is logged as refused.

**Would this replace air traffic controllers?**
No. It is for the thousands of airports with no tower at all, where today nobody is watching. It is an advisory system: it alerts pilots and airport ops. Certification and FAA approval would be required before anything like this talks to real aircraft.

## Aircraft and traffic

**Does it detect aircraft too?**
The camera's job is obstacles on the runway. The two aircraft in the demo are the traffic Capy manages; their calls come from the pilot buttons. A real deployment would take traffic from the radio or ADS-B. d1's "vehicle" category includes aircraft, so a plane taxiing onto an active runway (a runway incursion) would be flagged as blocked, but we have not tuned for it yet.

**Can it understand real pilots on the radio?**
Not yet. LFM3-Audio could transcribe radio calls on the board; it is on our list next to spoken tower calls.

## The build

**What did you build during the event?**
Everything, starting from a freshly flashed board: NPU packages and GenieX, model staging, the USB-C network link, the agent loop, policy and safety checks, the tower screen, boot units, the deck and the video. The repo history shows it.

**What was hard?**
Venue Wi-Fi isolated devices from each other, so we turned the board's USB-C port into a USB network adapter. The board clock was wrong, which broke HTTPS. The default ARM torch wheels pulled gigabytes of CUDA libraries, so we installed CPU-only torch. And newer Transformers broke d1's bundled code, so we pinned 5.19.0.

**How much memory does it use?**
About 12 GB of the board's 36 GB, mostly d1 in fp32. LFM3-1.7B at 4 bits is about 1 GB.

**What would you do next?**
d1 on the NPU (ZETIC), a real outdoor runway camera with calibrated thresholds, spoken calls and radio transcription with LFM3-Audio, and ADS-B traffic input.

**Why a capybara?**
Capybaras are famously unbothered. When the network goes down, Capy stays chill.
