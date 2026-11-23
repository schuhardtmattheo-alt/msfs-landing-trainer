"""MSFS 2020 Landing Trainer.

Step 1 "Spawn on final": the aircraft is placed exactly on the localizer and glideslope of
the chosen runway, configured for landing and frozen in the air (its systems keep running).
The pilot tunes the ILS and sets the thrust levers.
Step 2 "Start approach": the freeze is released with the correct speed and descent rate,
and the autopilot, autothrust and APPR mode are engaged and verified.
"""
import json
import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import runways as rw
import updater
from simconnect_lite import SimConnect, SimConnectError
from version import VERSION

APP_NAME = "MSFS Landing Trainer"
SETTINGS = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LandingTrainer", "settings.json")
KT_TO_FPS = 1.68781

# name -> (flap handle index 0..4, gear down, default speed kt)
CONFIGS = {
    "Flaps 1, gear up": (1, False, 180),
    "Flaps 2, gear down": (2, True, 160),
    "Flaps 3, gear down": (3, True, 150),
    "Landing (flaps FULL, gear down)": (4, True, 140),
}
INTERCEPTS = {"Straight-in on localizer + glideslope": 0,
              "30° intercept from the left": -30, "30° intercept from the right": 30}
FENIX = "Fenix A319 / A320 / A321"
FBW = "FlyByWire A32NX / LVFR A319 / A321"
GENERIC = "Default A320neo / generic aircraft"
PROFILES = ["Auto-detect", FENIX, FBW, GENERIC]
FREEZES = ("FREEZE_LATITUDE_LONGITUDE_SET", "FREEZE_ALTITUDE_SET", "FREEZE_ATTITUDE_SET")


def detect_profile(title):
    t = (title or "").upper()
    if "FENIX" in t or "FNX" in t:
        return FENIX
    if any(k in t for k in ("A32NX", "FLYBYWIRE", "FBW", "LVFR")):
        return FBW
    return GENERIC


class Trainer:
    def __init__(self, log):
        self.log = log
        self.sc = None
        self.db = None
        self.state = None  # set by spawn(), used by start()
        self.lock = threading.Lock()

    def connect(self):
        if self.sc and not self.sc.quit:
            return self.sc
        self.log("Connecting to MSFS ...")
        self.sc = SimConnect(log=self.log)
        self.log("Connected.")
        return self.sc

    def database(self):
        if self.db is None:
            self.db = rw.RunwayDB()
        return self.db

    def freeze(self, sc, on):
        for ev in FREEZES:
            sc.event(ev, 1 if on else 0)

    # ------------------------------------------------------------ step 1: spawn
    def spawn(self, cfg):
        with self.lock:
            return self._spawn(cfg)

    def _spawn(self, cfg):
        self.state = None
        rwy = self.database().runway(cfg["icao"], cfg["runway"])
        self.log(f"Runway {rwy['icao']} {rwy['ident']}: course {rwy['course_true']:.1f}°T")
        sc = self.connect()

        title = sc.get_title()
        profile = cfg["profile"] if cfg["profile"] in PROFILES[1:] else detect_profile(title)
        self.log(f"Aircraft: {title or '?'}  ->  profile: {profile}")
        if profile == FENIX and self._lvar(sc, "I_FCU_AP1") is None:
            raise SimConnectError("Cannot access the Fenix cockpit controls (L-vars). Update MSFS 2020 to the latest "
                                  "Sim Update and make sure the Fenix is fully loaded (cockpit powered).")
        if not sc.get_var("GENERAL ENG COMBUSTION:1", "bool"):
            self.log("WARNING: engine 1 is not running. Start the engines first, or the aircraft will glide.")

        flap_idx, gear_down, _ = CONFIGS[cfg["config"]]
        intercept = INTERCEPTS[cfg["intercept"]]
        dist, speed = float(cfg["distance"]), float(cfg["speed"])

        self.disarm_previous_approach(sc, profile)
        self.freeze(sc, True)
        elev = rwy["elev_ft"] if rwy["elev_ft"] is not None else 0.0

        # 1st teleport: near the airport so the sim loads the local navaids (ILS data).
        p = rw.spawn_point(rwy, dist, intercept, None, elev)
        sc.set_init_position(p["lat"], p["lon"], p["alt"] + (0 if rwy["elev_ft"] is not None else 3000), p["hdg"], 0)
        time.sleep(1.5)
        ils = self._find_ils(sc, rwy)
        if rwy["elev_ft"] is None and not (ils and ils["flags"] & 4):
            elev = sc.get_var("GROUND ALTITUDE", "feet") or 0.0
            self.log(f"Runway elevation unknown - using terrain height {elev:.0f} ft.")

        # 2nd teleport: exactly on localizer + glideslope, frozen.
        p = rw.spawn_point(rwy, dist, intercept, ils, elev)
        pitch = 2.5 if flap_idx < 3 else 1.5
        sc.set_init_position(p["lat"], p["lon"], p["alt"], p["hdg"], 0, pitch)
        time.sleep(1.0)

        hdg_true = sc.get_var("PLANE HEADING DEGREES TRUE", "degrees")
        hdg_mag = sc.get_var("PLANE HEADING DEGREES MAGNETIC", "degrees")
        magvar = rw.angle_diff(hdg_true, hdg_mag) if hdg_true is not None and hdg_mag is not None else 0.0
        course_mag = round((p["crs"] - magvar) % 360) or 360
        hdg_bug = round((p["hdg"] - magvar) % 360) or 360
        vs_fps = -speed * KT_TO_FPS * math.tan(math.radians(p["gs_angle"])) if p["on_gs"] else 0.0

        if profile == FENIX:
            self._fnx_configure(sc, flap_idx, gear_down)
        else:
            if sc.get_var("BRAKE PARKING POSITION", "bool"):
                sc.event("PARKING_BRAKES")
            sc.event("GEAR_DOWN" if gear_down else "GEAR_UP")
            sc.event("FLAPS_SET", int(flap_idx * 16383 / 4))
            sc.event("SPOILERS_ARM_ON" if gear_down else "SPOILERS_ARM_OFF")
            sc.event("LANDING_LIGHTS_ON")

        frozen = sc.get_var("IS LATITUDE LONGITUDE FREEZE ON", "bool")
        self.state = dict(profile=profile, rwy=rwy, ils=ils, p=p, pitch=pitch, speed=speed, vs_fps=vs_fps,
                          course_mag=course_mag, hdg_bug=hdg_bug,
                          alt_missed=int(math.ceil((p["alt"] + 1000) / 1000.0) * 1000))
        self.log(f"Placed {dist:.1f} NM before the threshold at {p['alt']:.0f} ft MSL "
                 f"({'on the glideslope' if p['on_gs'] else 'level, glideslope above'}), "
                 f"{'FROZEN' if frozen or frozen is None else 'NOT frozen (!)'}.")
        return self.state

    def _find_ils(self, sc, rwy):
        ils, navs = None, []
        for _ in range(6):
            navs = sc.nearby_navaids()
            ils = rw.pick_ils(rwy, navs)
            if ils:
                break
            time.sleep(1.0)
        if not ils:
            ils = rw.pick_ils(rwy, navs, relaxed=True)
        if ils:
            self.log(f"ILS in sim data: {ils['ident']} {ils['freq_hz'] / 1e6:.2f} MHz"
                     + ("" if ils["flags"] & 4 else " (LOC only, no glideslope)"))
        else:
            locs = sum(1 for n in navs if n["flags"] & 2)
            self.log(f"No ILS found for this runway in the sim data ({locs} localizers nearby). "
                     "Placed on the runway centerline with a 3° path.")
        return ils

    def ils_status(self):
        """(loc, gs, freq) as seen by the sim's NAV1/NAV3 receivers, or None if busy/unknown."""
        if not self.sc or not self.lock.acquire(blocking=False):
            return None
        try:
            for idx in (1, 3):
                if self.sc.get_var(f"NAV HAS LOCALIZER:{idx}", "bool", timeout=1.0):
                    gs = bool(self.sc.get_var(f"NAV HAS GLIDE SLOPE:{idx}", "bool", timeout=1.0))
                    freq = self.sc.get_var(f"NAV ACTIVE FREQUENCY:{idx}", "MHz", timeout=1.0)
                    return True, gs, freq
            return False, False, None
        finally:
            self.lock.release()

    # ---------------------------------------------------- step 2: start approach
    def start(self, cfg):
        with self.lock:
            return self._start(cfg)

    def _start(self, cfg):
        st = self.state
        if not st:
            raise ValueError("Spawn on final first.")
        sc, p = self.connect(), st["p"]
        # Release the freeze and give the aircraft its approach speed and descent rate at once.
        self.freeze(sc, False)
        sc.set_init_position(p["lat"], p["lon"], p["alt"], p["hdg"], st["speed"], st["pitch"])
        if st["vs_fps"]:
            sc.set_var("VELOCITY WORLD Y", "feet per second", st["vs_fps"])
        self.log(f"Approach started: {st['speed']:.0f} kt, {st['vs_fps'] * 60:.0f} ft/min.")
        if cfg["autopilot"]:
            time.sleep(0.3)
            {FENIX: self._fnx_autopilot, FBW: self._fbw_autopilot}.get(st["profile"], self._generic_autopilot)(sc, st)
        else:
            self.log("Autopilot not engaged - you have control.")
        self.state = None
        return True

    # ------------------------------------------------------------------ helpers
    def _lvar(self, sc, name):
        """Read a cockpit L-var; None if this sim does not allow L-var access over SimConnect."""
        return sc.get_var(f"L:{name}", "number", timeout=1.5)

    def _on(self, sc, name):
        v = self._lvar(sc, name)
        return v is not None and v > 0.5

    def disarm_previous_approach(self, sc, profile):
        """On a re-spawn the old approach is often still armed/captured (LOC/G/S/LAND) and the
        autopilot still on. Clear it so nothing fights the teleport."""
        if profile == FENIX:
            if self._on(sc, "I_FCU_APPR"):
                self._fnx_press(sc, "S_FCU_APPR")
            elif self._on(sc, "I_FCU_LOC"):
                self._fnx_press(sc, "S_FCU_LOC")
            for ap in ("AP1", "AP2"):
                if self._on(sc, f"I_FCU_{ap}"):
                    self._fnx_press(sc, f"S_FCU_{ap}")
        elif profile == FBW:
            sc.event("A32NX.FCU_AP_DISCONNECT_PUSH")
            if self._lvar(sc, "A32NX_FCU_APPR_MODE_ACTIVE"):
                sc.event("A32NX.FCU_APPR_PUSH")
            elif self._lvar(sc, "A32NX_FCU_LOC_MODE_ACTIVE"):
                sc.event("A32NX.FCU_LOC_PUSH")
        else:
            sc.event("AUTOPILOT_OFF")
            sc.event("AP_APR_HOLD_OFF")
            sc.event("AP_LOC_HOLD_OFF")
        time.sleep(0.3)

    def _verify(self, check, press, label, tries=4, wait=1.5):
        for attempt in range(tries):
            if check():
                self.log(f"{label}: ON")
                return True
            press()
            time.sleep(wait)
        ok = check()
        self.log(f"{label}: {'ON' if ok else 'FAILED - please engage it yourself'}")
        return ok

    # --------------------------------------------------------- default aircraft
    def _generic_autopilot(self, sc, st):
        sc.event("HEADING_BUG_SET", st["hdg_bug"])
        sc.event("AP_SPD_VAR_SET", int(st["speed"]))
        sc.event("AP_ALT_VAR_SET_ENGLISH", st["alt_missed"])
        sc.event("AP_VS_VAR_SET_ENGLISH", int(round(st["vs_fps"] * 60 / 100.0) * 100))
        self._verify(lambda: sc.get_var("AUTOPILOT MASTER", "bool"), lambda: sc.event("AUTOPILOT_ON"), "Autopilot")
        sc.event("AP_HDG_HOLD_ON")
        sc.event("AP_VS_ON")
        self._verify(lambda: sc.get_var("AUTOPILOT THROTTLE ARM", "bool"),
                     lambda: sc.event("AUTO_THROTTLE_ARM"), "Autothrust", tries=1)
        sc.event("AP_AIRSPEED_ON")
        self._verify(lambda: any(sc.get_var(v, "bool") for v in (
            "AUTOPILOT APPROACH HOLD", "AUTOPILOT APPROACH ARM", "AUTOPILOT APPROACH ACTIVE")),
            lambda: sc.event("AP_APR_HOLD_ON"), "APPR (LOC + G/S)")

    # ------------------------------------------------------------ FlyByWire A32NX
    def _fbw_autopilot(self, sc, st):
        sc.event("A32NX.FCU_SPD_SET", int(st["speed"]))
        sc.event("A32NX.FCU_SPD_PULL")
        sc.event("A32NX.FCU_HDG_SET", st["hdg_bug"])
        sc.event("A32NX.FCU_HDG_PULL")
        sc.event("A32NX.FCU_ALT_SET", st["alt_missed"])
        if self._lvar(sc, "A32NX_AUTOPILOT_1_ACTIVE") is None:  # no L-var access: press each once
            for ev in ("A32NX.FCU_AP_1_PUSH", "A32NX.FCU_ATHR_PUSH", "A32NX.FCU_APPR_PUSH"):
                sc.event(ev)
                time.sleep(0.5)
            self.log("AP1, A/THR, APPR pressed (cannot verify on this setup - check the FMA).")
            return
        self._verify(lambda: self._on(sc, "A32NX_AUTOPILOT_1_ACTIVE"),
                     lambda: sc.event("A32NX.FCU_AP_1_PUSH"), "AP1")
        self._verify(lambda: (self._lvar(sc, "A32NX_AUTOTHRUST_STATUS") or 0) > 0,
                     lambda: sc.event("A32NX.FCU_ATHR_PUSH"), "A/THR", tries=2)
        self._verify(lambda: self._on(sc, "A32NX_FCU_APPR_MODE_ACTIVE"),
                     lambda: sc.event("A32NX.FCU_APPR_PUSH"), "APPR (LOC + G/S)")

    # ------------------------------------------------------------------ Fenix
    # Cockpit L-vars from the Fenix's own FNX32X_Interior.xml / Interactions.xml:
    #   momentary buttons: +1 = pressed, +1 again = released (odd value = held down)
    #   FCU knobs S_FCU_*: +1 = pull (selected), -1 = push (managed)
    def _fnx_set(self, sc, var, value):
        sc.set_var(f"L:{var}", "number", value)

    def _fnx_press(self, sc, var):
        v = self._lvar(sc, var) or 0.0
        if int(v) % 2:  # left "held down" - release first
            v += 1
            self._fnx_set(sc, var, v)
            time.sleep(0.1)
        self._fnx_set(sc, var, v + 1)
        time.sleep(0.12)
        self._fnx_set(sc, var, v + 2)
        time.sleep(0.15)

    def _fnx_pull(self, sc, var):
        self._fnx_set(sc, var, (self._lvar(sc, var) or 0.0) + 1)
        time.sleep(0.3)

    def _fnx_configure(self, sc, flap_idx, gear_down):
        self._fnx_set(sc, "S_FC_FLAPS", flap_idx)
        self._fnx_set(sc, "S_OH_EXT_LT_LANDING_BOTH", 2)
        self._fnx_set(sc, "S_MIP_GEAR", 1 if gear_down else 0)
        self._fnx_set(sc, "S_MIP_PARKING_BRAKE", 0)
        time.sleep(2.0)
        # Verify against the sim's own state and flip if the lever convention is the other way round.
        gear = sc.get_var("GEAR HANDLE POSITION", "bool")
        if gear is not None and bool(gear) != gear_down:
            self._fnx_set(sc, "S_MIP_GEAR", 0 if gear_down else 1)
        if sc.get_var("BRAKE PARKING POSITION", "bool"):
            self._fnx_set(sc, "S_MIP_PARKING_BRAKE", 1)
        for efis in ("LS", "FD"):
            if not self._on(sc, f"I_FCU_EFIS1_{efis}"):
                self._fnx_press(sc, f"S_FCU_EFIS1_{efis}")

    def _fnx_autopilot(self, sc, st):
        # Pull SPD and HDG: selected speed / heading = current values (the approach speed and course).
        self._fnx_pull(sc, "S_FCU_SPEED")
        self._fnx_pull(sc, "S_FCU_HEADING")
        self._verify(lambda: self._on(sc, "I_FCU_AP1"), lambda: self._fnx_press(sc, "S_FCU_AP1"), "AP1")
        self._verify(lambda: self._on(sc, "I_FCU_ATHR"), lambda: self._fnx_press(sc, "S_FCU_ATHR"), "A/THR", tries=2)
        self._verify(lambda: self._on(sc, "I_FCU_APPR"), lambda: self._fnx_press(sc, "S_FCU_APPR"),
                     "APPR (LOC + G/S)", wait=2.0)


# ====================================================================== GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.minsize(600, 640)
        self.q = queue.Queue()
        self.trainer = Trainer(self.q.put)
        self.busy = False
        s = self._load()

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        ttk.Label(frm, text="Landing practice: start on the ILS final, autopilot flies the approach.",
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        defaults = {"icao": "EDDF", "runway": "25C", "distance": "10", "speed": "160",
                    "config": "Flaps 2, gear down", "intercept": list(INTERCEPTS)[0], "profile": "Auto-detect"}
        self.v = {k: tk.StringVar(value=str(s.get(k, d))) for k, d in defaults.items()}
        for key, allowed in (("profile", PROFILES), ("config", list(CONFIGS)), ("intercept", list(INTERCEPTS))):
            if self.v[key].get() not in allowed:
                self.v[key].set(defaults[key])
        self.ap = tk.BooleanVar(value=s.get("autopilot", True))

        r = 1
        ttk.Label(frm, text="Destination airport (ICAO):").grid(row=r, column=0, sticky="w", pady=3)
        e = ttk.Entry(frm, textvariable=self.v["icao"], width=10)
        e.grid(row=r, column=1, sticky="w")
        e.bind("<FocusOut>", lambda _e: self._fill_runways())
        e.bind("<Return>", lambda _e: self._fill_runways())
        r += 1
        ttk.Label(frm, text="Runway:").grid(row=r, column=0, sticky="w", pady=3)
        self.rwy_cb = ttk.Combobox(frm, textvariable=self.v["runway"], width=8)
        self.rwy_cb.grid(row=r, column=1, sticky="w")
        self.rwy_cb.bind("<Button-1>", lambda _e: self._fill_runways())
        r += 1
        ttk.Label(frm, text="Distance from threshold (NM):").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=3, to=25, increment=1, textvariable=self.v["distance"], width=8).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, text="Configuration:").grid(row=r, column=0, sticky="w", pady=3)
        cb = ttk.Combobox(frm, textvariable=self.v["config"], values=list(CONFIGS), state="readonly", width=36)
        cb.grid(row=r, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda _e: self.v["speed"].set(str(CONFIGS[self.v["config"].get()][2])))
        r += 1
        ttk.Label(frm, text="Speed (kt IAS):").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=120, to=220, increment=5, textvariable=self.v["speed"], width=8).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, text="Approach:").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.v["intercept"], values=list(INTERCEPTS), state="readonly",
                     width=36).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, text="Aircraft profile:").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.v["profile"], values=PROFILES, state="readonly",
                     width=36).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Checkbutton(frm, text="Autopilot flies the approach (AP + A/THR + APPR)",
                        variable=self.ap).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))
        r += 1
        btns = ttk.Frame(frm)
        btns.grid(row=r, column=0, columnspan=2, sticky="we", pady=10)
        btns.columnconfigure((0, 1), weight=1)
        self.btn_spawn = ttk.Button(btns, text="1  Spawn on final (frozen)", command=self._spawn)
        self.btn_spawn.grid(row=0, column=0, sticky="we", padx=(0, 4), ipady=6)
        self.btn_start = ttk.Button(btns, text="2  Start approach", command=self._start, state="disabled")
        self.btn_start.grid(row=0, column=1, sticky="we", padx=(4, 0), ipady=6)
        r += 1
        self.ready = tk.StringVar(value="")
        self.ready_lbl = ttk.Label(frm, textvariable=self.ready, justify="left", wraplength=560,
                                   font=("Segoe UI", 10))
        self.ready_lbl.grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 8))
        r += 1
        self.log_txt = tk.Text(frm, height=12, wrap="word", font=("Consolas", 9), state="disabled")
        self.log_txt.grid(row=r, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(r, weight=1)

        self._log("Start a flight in MSFS (engines running, e.g. on a runway), then press 1.")
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)
        threading.Thread(target=self._status_loop, daemon=True).start()
        if updater.enabled():
            threading.Thread(target=self._check_update, daemon=True).start()

    # ---------------------------------------------------------------- updates
    def _check_update(self):
        try:
            rel = updater.check()
        except Exception as ex:
            self.q.put(f"(Update check failed: {ex})")
            return
        if rel:
            self.after(0, lambda: self._offer_update(rel))

    def _offer_update(self, rel):
        notes = rel["notes"][:600] + ("..." if len(rel["notes"]) > 600 else "")
        if not messagebox.askyesno(
                "Update available",
                f"Version {rel['version']} is available (you have {VERSION}).\n\n{notes}\n\nUpdate now? "
                "The app restarts automatically.", parent=self):
            self._log(f"Update {rel['version']} skipped - you will be asked again next start.")
            return
        self._set_busy(True)
        self._log(f"Downloading update {rel['version']} ...")

        def job():
            try:
                last = [-1]

                def progress(pct):
                    if pct // 20 != last[0]:
                        last[0] = pct // 20
                        self.q.put(f"  {pct}%")

                tmp, new_dir = updater.download_and_extract(rel["url"], progress)
                updater.install_and_restart(tmp, new_dir)
                self.q.put("Installing update - restarting ...")
                self.after(500, self._close)
            except Exception as ex:
                self.q.put(f"ERROR: update failed: {ex}")
                self.q.put(None)

        threading.Thread(target=job, daemon=True).start()

    # --------------------------------------------------------------- plumbing
    def _log(self, msg):
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", msg + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def _set_busy(self, busy):
        self.busy = busy
        self.btn_spawn.configure(state="disabled" if busy else "normal")
        self.btn_start.configure(state="normal" if not busy and self.trainer.state else "disabled")

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    self._set_busy(False)
                elif isinstance(item, tuple):
                    self.ready.set(item[1])
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _status_loop(self):
        """While frozen on final, show live whether the ILS is received."""
        while True:
            time.sleep(1.0)
            st = self.trainer.state
            if not st or self.busy:
                continue
            s = self.trainer.ils_status()
            if s is None or self.trainer.state is not st or self.busy:
                continue  # approach started meanwhile - don't show a stale panel
            self.q.put(("ready", self._ready_text(st, s)))

    def _ready_text(self, st, status=None):
        ils = st["ils"]
        if ils:
            tune = f"ILS {ils['ident']}  {ils['freq_hz'] / 1e6:.2f} MHz   course {st['course_mag']:03d}°"
        else:
            tune = f"No ILS in sim data - look up the frequency on the chart.   Course {st['course_mag']:03d}°"
        where = {FENIX: "MCDU RAD NAV (ILS/FREQ, then CRS)", FBW: "MCDU RAD NAV (LS/FREQ, then CRS)"}.get(
            st["profile"], "NAV1 (and MCDU RAD NAV on the A320)")
        lines = ["FROZEN ON FINAL - get ready:",
                 f"  1. Tune  {tune}  in {where}",
                 "  2. Thrust levers to CLB (Airbus) - the aircraft is frozen, nothing happens yet",
                 "  3. Press  '2  Start approach'"]
        if status is not None:
            loc, gs, freq = status
            if loc:
                lines.append(f"Signal: LOC received {'and G/S received' if gs else '(no G/S yet)'}"
                             + (f" on {freq:.2f} MHz" if freq else "") + " - ready.")
            elif st["profile"] == FENIX:
                lines.append("Signal: check the PFD - LOC and G/S scales must show diamonds.")
            else:
                lines.append("Signal: no localizer received yet - check the frequency.")
        return "\n".join(lines)

    def _fill_runways(self):
        try:
            self.rwy_cb.configure(values=self.trainer.database().runways(self.v["icao"].get().strip()))
        except Exception as ex:
            self._log(f"Runway database error: {ex}")

    def _cfg(self):
        c = {k: v.get().strip() for k, v in self.v.items()}
        c["icao"] = c["icao"].upper()
        c["autopilot"] = self.ap.get()
        return c

    def _run(self, fn, cfg, after=None):
        self._set_busy(True)

        def job():
            try:
                res = fn(cfg)
                if after:
                    after(res)
            except (SimConnectError, ValueError) as ex:
                self.q.put(f"ERROR: {ex}")
            except Exception as ex:  # keep the app alive on anything unexpected
                self.q.put(f"ERROR ({type(ex).__name__}): {ex}")
                self.trainer.sc = None
            finally:
                self.q.put(None)

        threading.Thread(target=job, daemon=True).start()

    def _spawn(self):
        if self.busy:
            return
        cfg = self._cfg()
        self._save(cfg)
        self.ready.set("")
        self._log("-" * 60)
        self._run(self.trainer.spawn, cfg,
                  after=lambda st: st and self.q.put(("ready", self._ready_text(st))))

    def _start(self):
        if self.busy or not self.trainer.state:
            return
        self.ready.set("")
        self._run(self.trainer.start, self._cfg(),
                  after=lambda _r: self.q.put("Have a good landing! Press 1 to fly the approach again."))

    def _load(self):
        try:
            with open(SETTINGS, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save(self, cfg):
        try:
            os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
            with open(SETTINGS, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
        except Exception:
            pass

    def _close(self):
        if self.trainer.sc:
            self.trainer.sc.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
