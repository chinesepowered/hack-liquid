# Capy Tower: demo script (2 minutes + 1 question)

## Before the judges arrive

- [ ] Both cables in: **USB-C** (screen and SSH link) and **micro-USB debug** (backup console).
- [ ] Tunnel running on the laptop:
      `ssh -N -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@169.254.7.2`
- [ ] Browser on **http://127.0.0.1:8000**, reloaded, **Simulated runway** selected.
- [ ] Header shows **LFM3-1.7B · NPU · GenieX** and **d1-2B · CPU** in green.
- [ ] Runway reads **CLEAR**. If not, click **Clear the runway** and wait about 8 s.
- [ ] Second tab: **http://127.0.0.1:8000/static/slides.html** (works offline).
- [ ] Terminal ready to cut Wi-Fi (password `liquidxqualcomm`):
      `ssh -t ubuntu@169.254.7.2 'sudo nmcli radio wifi off; nmcli device'`

## The script

| Time | Do | Say |
|---|---|---|
| 0:00 | Slide 1 | "Today a communications failure grounded every flight in America. Most US airports don't even have a control tower. Safety that needs a network fails when the network does." |
| 0:15 | Run the Wi-Fi-off command; point at the **✈ OFFLINE · no route off the board** badge | "Wi-Fi is off. The only cable is a USB-C link to this screen. Everything you see runs on the Qualcomm IQ-9075." |
| 0:30 | Click **🛬 Cirrus 7CP: on final** | "A plane calls in. LiquidAI's LFM3 on the Hexagon NPU writes the clearance, in about half a second." |
| 0:40 | Tap the **Deer** preset | "A deer walks onto the runway, one of the most common wildlife hazards. d1-2B looks at the frame on the CPU." Point at the pipeline strip and the progress bar while it decides (about 8 s). |
| 0:55 | Point at the red ribbon, Capy, and the radio panel | "Go around. Runway closed. Wildlife crew called. Code makes the safety decision; the language model only words it, and every call is checked before it goes out." |
| 1:10 | Click **✈ Cessna 28A: ready for departure** | "The Cessna wants to go: hold short." |
| 1:20 | Click **🧹 Clear the runway** | "When the deer is gone, the runway reopens and both aircraft are cleared automatically, arrivals first. No human, no network." |
| 1:40 | Point at **On-device numbers** and the **Decision log** | "Every decision is logged on the board. 7.6 s per d1 decision on the CPU, 0.6 s per LFM3 call on the NPU, zero network calls." |
| 1:50 | Close | "When the network goes down, Capy stays chill." |

**Encore if there is time:** let the judge tap **Baggage tug** or **Debris: traffic cone** (both 95%+ on the board), or click **Capybara wanders on** for our mascot's cameo. Avoid **Person on foot** (weakest preset, 78%).

## Pacing notes

- Each d1 decision takes about 8 s. Talk through it: point at the pipeline strip (d1 lights up) and the progress bar.
- Do not click a second hazard while the runway is still closed; clear first.
- If the judge asks to see the laptop camera: switch to **Laptop camera**, fill the view with a plain surface, then hold a phone showing a preset photo. Expect about 8 s per decision.

## If something goes wrong

| Problem | Fix |
|---|---|
| Screen says "board unreachable" | Restart the tunnel command above. |
| Header shows **LFM3 server not reachable** | `ssh ubuntu@169.254.7.2 'sudo systemctl restart capy-geniex'`, wait 20 s. Calls fall back to templates meanwhile, so the demo still works. |
| Runway stuck closed | Click **Clear the runway** and wait for one decision (about 8 s). |
| App frozen | `ssh ubuntu@169.254.7.2 'pkill -f "[c]apy_tower/app.py"; cd ~/hack-liquid && setsid nohup scripts/run_board.sh > ~/capy.out 2>&1 < /dev/null &'`, wait 20 s, reload. |
| Board rebooted | Wait about 60 s: the USB link, GenieX and Capy Tower start on their own. Then restart the tunnel and reload. |
| USB-C link gone | Use the micro-USB console (COM6, 115200, user `ubuntu`) and run `sudo ~/hack-liquid/scripts/usb_link.sh a600000.usb`. |
| Everything is on fire | Play `docs/video/capy_tower_demo.mp4`: the same demo recorded on this board with Wi-Fi off. |

After judging: `ssh -t ubuntu@169.254.7.2 'sudo nmcli radio wifi on'`.
