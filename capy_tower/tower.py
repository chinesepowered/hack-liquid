"""Capy Tower policy: runway state, traffic, allowlisted actions, and radio phraseology.

The safety decision (which instruction to give) is made here, in plain code, from the
runway decision. LFM3-1.7B only phrases the radio call, and its text is checked for the
mandatory instruction before it is used; otherwise the template below is sent instead.
"""

import time

RUNWAY = "28"
TAKEOFF_S, LANDING_S, GO_AROUND_S = 12, 14, 10  # demo timings; the screen animates over the same spans
RWY = "two-eight"

ALLOWED_ACTIONS = (
    "close_runway", "reopen_runway",
    "clear_for_takeoff", "hold_short", "cancel_takeoff",
    "clear_to_land", "go_around",
    "dispatch_wildlife_crew", "dispatch_sweeper", "alert_security",
)

THING = {
    "capybara": "a capybara", "wildlife": "an animal", "person": "a person",
    "vehicle": "a vehicle", "debris": "debris", "unknown": "an obstruction",
}
DISPATCH = {
    "capybara": "dispatch_wildlife_crew", "wildlife": "dispatch_wildlife_crew",
    "debris": "dispatch_sweeper", "person": "alert_security", "vehicle": "alert_security",
}
# Words the generated radio call must contain, or the template is used instead.
REQUIRED = {
    "clear_for_takeoff": ["cleared for takeoff"], "hold_short": ["hold short"],
    "cancel_takeoff": ["cancel"], "clear_to_land": ["cleared to land"], "go_around": ["go around"],
    "close_runway": ["closed"], "reopen_runway": ["open"], "dispatch_wildlife_crew": ["wildlife"],
    "dispatch_sweeper": ["sweep"], "alert_security": ["security"],
}
PILOT_ACTIONS = {"clear_for_takeoff", "hold_short", "cancel_takeoff", "clear_to_land", "go_around"}
OPS_ACTIONS = {"dispatch_wildlife_crew", "dispatch_sweeper", "alert_security"}

SYSTEM_PROMPT = (
    "You are Capy, the automated control tower at a small airport with no human controller on duty. "
    "Write exactly one radio transmission in standard FAA air traffic control phraseology, under 25 words. "
    "Start with the station you are calling. Say runway numbers digit by digit, like two-eight. "
    "Reply with the transmission only."
)


class Tower:
    def __init__(self, threshold=0.6, clear_threshold=0.4):
        self.threshold, self.clear_threshold = threshold, clear_threshold
        now = time.time()
        self.status, self.what, self.p, self.since = "unknown", None, None, now
        self.dep = {"role": "departure", "callsign": "Cessna 28A", "spoken": "Cessna two-eight-alpha",
                    "phase": "holding_short", "pending": False, "t": now}
        self.arr = {"role": "arrival", "callsign": "Cirrus 7CP", "spoken": "Cirrus seven-charlie-papa",
                    "phase": "inbound", "pending": False, "t": now}

    # ---- helpers ----------------------------------------------------------------------------------

    def ac(self, role):
        return self.dep if role == "departure" else self.arr if role == "arrival" else None

    def _act(self, name, role=None, reason=None, auto=False):
        ac = self.ac(role)
        return {"action": name, "target": ac["callsign"] if ac else None, "role": role,
                "spoken": ac["spoken"] if ac else None, "auto": auto, "reason": reason,
                "runway": self.status, "what": self.what, "p_blocked": self.p}

    def obstruction(self):
        return THING.get(self.what or "unknown", "an obstruction")

    # ---- inputs -----------------------------------------------------------------------------------

    def on_decision(self, d, now=None):
        """Update the runway from one gate decision. Returns the actions the change requires."""
        now = now or time.time()
        p = float(d["p_blocked"])
        prev = self.status
        if p >= self.threshold:
            new = "closed"
        elif p <= self.clear_threshold:
            new = "clear"
        else:  # uncertain: keep the last state; with no history, fail safe
            new = prev if prev != "unknown" else "closed"
        self.p = round(p, 4)
        what = d.get("what")
        what = what if what in THING else "unknown"
        acts = []
        if new == "closed":
            if prev != "closed":
                self.status, self.what, self.since = "closed", what, now
                # Most urgent first: nobody may land or roll on a blocked runway.
                if self.arr["phase"] == "cleared_land":
                    acts.append(self._act("go_around", "arrival", reason="obstruction"))
                if self.dep["phase"] == "cleared_takeoff" and now - self.dep["t"] < TAKEOFF_S * 0.6:
                    acts.append(self._act("cancel_takeoff", "departure", reason="obstruction"))
                acts.append(self._act("close_runway"))
                if what in DISPATCH:
                    acts.append(self._act(DISPATCH[what]))
            elif what != "unknown":
                self.what = what
        elif prev != "clear":
            self.status, self.since = "clear", now
            if prev == "closed":
                acts.append(self._act("reopen_runway"))
            self.what = None
            acts += self.auto_clearances()
        return acts

    def on_request(self, kind):
        """A pilot request from the screen. Returns (pilot transmission, actions)."""
        if kind == "takeoff":
            d = self.dep
            if d["phase"] not in ("holding_short", "waiting"):
                return None, []
            pilot = f"Capy Tower, {d['spoken']}, holding short runway {RWY}, ready for departure."
            if self.status == "clear" and self.arr["phase"] != "cleared_land":
                return pilot, [self._act("clear_for_takeoff", "departure")]
            reason = "landing traffic" if self.status == "clear" else "obstruction"
            return pilot, [self._act("hold_short", "departure", reason=reason)]
        if kind == "landing":
            a = self.arr
            if a["phase"] not in ("inbound", "holding"):
                return None, []
            pilot = f"Capy Tower, {a['spoken']}, three-mile final runway {RWY}."
            if self.status == "clear" and self.dep["phase"] != "cleared_takeoff":
                return pilot, [self._act("clear_to_land", "arrival")]
            reason = "departing traffic" if self.status == "clear" else "obstruction"
            return pilot, [self._act("go_around", "arrival", reason=reason)]
        return None, []

    def auto_clearances(self):
        """Autonomy: aircraft that were told to wait are cleared as soon as the runway is usable."""
        if self.status != "clear":
            return []
        if self.arr["pending"] and self.arr["phase"] == "holding" and self.dep["phase"] != "cleared_takeoff":
            return [self._act("clear_to_land", "arrival", auto=True)]
        if self.dep["pending"] and self.dep["phase"] == "waiting" and self.arr["phase"] != "cleared_land":
            return [self._act("clear_for_takeoff", "departure", auto=True)]
        return []

    def tick(self, now=None):
        """Time-based traffic progress, so the demo can repeat. Returns any automatic actions."""
        now = now or time.time()
        d, a = self.dep, self.arr
        if d["phase"] == "cleared_takeoff" and now - d["t"] > TAKEOFF_S:
            d.update(phase="departed", t=now, pending=False)
        elif d["phase"] == "departed" and now - d["t"] > 12:
            d.update(phase="holding_short", t=now, pending=False)
        if a["phase"] == "cleared_land" and now - a["t"] > LANDING_S:
            a.update(phase="landed", t=now, pending=False)
        elif a["phase"] == "landed" and now - a["t"] > 12:
            a.update(phase="inbound", t=now, pending=False)
        elif a["phase"] == "go_around" and now - a["t"] > GO_AROUND_S:
            a.update(phase="holding", t=now)  # circling, still wants to land
        return self.auto_clearances()

    def apply(self, act, now=None):
        """Execute an allowlisted action on the tower's own state."""
        now = now or time.time()
        n, ac = act["action"], self.ac(act.get("role"))
        if n == "clear_for_takeoff":
            ac.update(phase="cleared_takeoff", pending=False, t=now)
        elif n in ("hold_short", "cancel_takeoff"):
            ac.update(phase="waiting", pending=True, t=now)
        elif n == "clear_to_land":
            ac.update(phase="cleared_land", pending=False, t=now)
        elif n == "go_around":
            ac.update(phase="go_around", pending=True, t=now)

    # ---- views ------------------------------------------------------------------------------------

    def view(self, now=None):
        now = now or time.time()
        traffic = []
        for ac in (self.dep, self.arr):
            traffic.append({k: ac[k] for k in ("role", "callsign", "phase", "pending")} | {"age_s": round(now - ac["t"], 2)})
        return {"status": self.status, "what": self.what, "obstruction": self.obstruction() if self.status == "closed" else None,
                "p_blocked": self.p, "since_s": round(now - self.since, 1), "threshold": self.threshold,
                "clear_threshold": self.clear_threshold, "traffic": traffic}


# ---- radio phraseology ----------------------------------------------------------------------------

def _reason_text(act):
    r = act.get("reason")
    if r in ("landing traffic", "departing traffic"):
        return r
    return f"{THING.get(act.get('what') or 'unknown', 'an obstruction')} on the runway"


def station(act):
    if act["action"] in PILOT_ACTIONS:
        return "PILOT_CALL"
    return "OPS" if act["action"] in OPS_ACTIONS else "ALL"


def template(act):
    cs, why, thing = act.get("spoken"), _reason_text(act), THING.get(act.get("what") or "unknown", "an obstruction")
    return {
        "clear_for_takeoff": f"{cs}, runway {RWY}, cleared for takeoff.",
        "hold_short": f"{cs}, hold short runway {RWY}, {why}.",
        "cancel_takeoff": f"{cs}, cancel takeoff clearance, hold position, {why}.",
        "clear_to_land": f"{cs}, runway {RWY}, cleared to land.",
        "go_around": f"{cs}, go around, {why}.",
        "close_runway": f"All traffic, Capy Tower, runway {RWY} closed, {thing} on the runway.",
        "reopen_runway": f"All traffic, Capy Tower, runway {RWY} is clear and open.",
        "dispatch_wildlife_crew": f"Airport ops, Capy Tower, {thing} on runway {RWY}, send the wildlife crew.",
        "dispatch_sweeper": f"Airport ops, Capy Tower, debris on runway {RWY}, send the sweeper.",
        "alert_security": f"Airport ops, Capy Tower, {thing} on runway {RWY}, send security.",
    }[act["action"]]


def prompt(act):
    n, cs = act["action"], act.get("spoken")
    why = _reason_text(act)
    conf = f" (runway camera confidence {round(act['p_blocked'] * 100)}%)" if act.get("p_blocked") is not None else ""
    task = {
        "clear_for_takeoff": f"Call {cs}. The runway is clear. Clear them for takeoff on runway {RWY}.",
        "hold_short": f"Call {cs}, who is ready for departure. Tell them to hold short of runway {RWY} because of {why}{conf}.",
        "cancel_takeoff": f"Call {cs}, who was cleared for takeoff. Cancel the takeoff clearance and tell them to hold position because of {why}{conf}.",
        "clear_to_land": f"Call {cs} on final. The runway is clear. Clear them to land on runway {RWY}.",
        "go_around": f"Call {cs} on final. Tell them to go around because of {why}{conf}.",
        "close_runway": f"Call all traffic. Runway {RWY} is closed because of {why}{conf}.",
        "reopen_runway": f"Call all traffic. Runway {RWY} is clear again and open.",
        "dispatch_wildlife_crew": f"Call airport ops. There is {why} on runway {RWY}. Ask them to send the wildlife crew.",
        "dispatch_sweeper": f"Call airport ops. There is debris on runway {RWY}. Ask them to send the sweeper.",
        "alert_security": f"Call airport ops. There is {why} on runway {RWY}. Ask them to send security.",
    }[n]
    return task + " Identify yourself as Capy Tower when calling all traffic or airport ops."


def clean(text):
    text = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    return text.strip(" \"'`*").strip()[:240]


def valid(text, act):
    low = text.lower()
    if len(text) < 8:
        return False
    if not all(w in low for w in REQUIRED[act["action"]]):
        return False
    if act["action"] in PILOT_ACTIONS and act.get("target"):
        return act["target"].split()[0].lower() in low  # "cessna" / "cirrus"
    return True
