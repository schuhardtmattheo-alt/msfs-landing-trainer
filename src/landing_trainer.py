"""MSFS 2020 Landing Trainer.

Enter an airport and runway; the aircraft is teleported onto the ILS final
approach, configured, radios tuned and the autopilot armed for the approach.
"""
import json
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

# name -> (flap handle index 0..4, gear down, default speed kt)
CONFIGS = {
    "Clean (flaps 0, gear up)": (0, False, 210),
    "Flaps 1, gear up": (1, False, 180),
    "Flaps 2, gear down": (2, True, 160),
    "Flaps 3, gear down": (3, True, 150),
    "Landing (flaps FULL, gear down)": (4, True, 140),
}
INTERCEPTS = {"Straight-in on centerline": 0, "30° intercept from the left": -30, "30° intercept from the right": 30}
PROFILES = ["Auto-detect", "FlyByWire A32NX", "Generic / default aircraft"]


class Trainer:
    def __init__(self, log):
        self.log = log
        self.sc = None
        self.db = None

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

    # ------------------------------------------------------------------ main job
    def spawn(self, cfg):
        rwy = self.database().runway(cfg["icao"], cfg["runway"])
        self.log(f"Runway {rwy['icao']} {rwy['ident']}: course {rwy['course_true']:.1f}°T, "
                 f"elevation {rwy['elev_ft'] if rwy['elev_ft'] is not None else 'unknown'} ft")
        sc = self.connect()

        title = sc.get_title()
        profile = cfg["profile"]
        if profile == "Auto-detect":
            fbw = any(k in title.upper() for k in ("A32NX", "FLYBYWIRE", "FBW"))
            profile = "FlyByWire A32NX" if fbw else "Generic / default aircraft"
        self.log(f"Aircraft: {title or '?'}  ->  profile: {profile}")
        if not sc.get_var("GENERAL ENG COMBUSTION:1", "bool"):
            self.log("WARNING: engine 1 is not running. Start the engines before spawning (or the aircraft will glide).")

        flap_idx, gear_down, _ = CONFIGS[cfg["config"]]
        intercept = INTERCEPTS[cfg["intercept"]]
        dist, speed = float(cfg["distance"]), float(cfg["speed"])
        below = 150.0 if cfg["below_gs"] else 0.0

        self.disarm_previous_approach(sc, profile)
        sc.event("PAUSE_ON")
        elev =rwy["elev_ft"] if rwy["elev_ft"] is not None else 0.0

        # 1st teleport: get near the airport so the sim loads the local navaids (ILS).
        lat, lon, alt, hdg = rw.spawn_point(rwy, dist, intercept, 3.0, below, elev)
        sc.set_init_position(lat, lon, alt if rwy["elev_ft"] is not None else alt + 3000, hdg, speed)
        time.sleep(1.5)

        ils = None
        for attempt in range(5):
            navs = sc.nearby_navaids()
            ils = rw.pick_ils(rwy, navs)
            if ils:
                break
            time.sleep(1.0)

        gs_angle = 3.0
        freq_hz = None
        if ils:
            freq_hz = ils["freq_hz"]
            if ils["flags"] & 4 and 2.0 <= ils["gs_angle"] <= 4.5:
                gs_angle = ils["gs_angle"]
            if rwy["elev_ft"] is None and ils["flags"] & 4:
                elev = ils["gs_alt_m"] * 3.28084
            self.log(f"ILS found: {ils['ident']}  {freq_hz / 1e6:.2f} MHz, glideslope "
                     f"{gs_angle:.1f}°" + ("" if ils["flags"] & 4 else " (LOC only - no glideslope!)"))
        else:
            self.log("WARNING: no ILS found for this runway in the sim's navaid data.")
        if cfg["freq"].strip():
            freq_hz = int(round(float(cfg["freq"].replace(",", ".")) * 1e6))
            self.log(f"Using manual ILS frequency {freq_hz / 1e6:.2f} MHz")
        if rwy["elev_ft"] is None and not (ils and ils["flags"] & 4):
            ground = sc.get_var("GROUND ALTITUDE", "feet") or 0.0
            elev = ground
            self.log(f"Runway elevation unknown, using terrain height {ground:.0f} ft as estimate.")

        # 2nd teleport: exact position on the approach.
        lat, lon, alt, hdg = rw.spawn_point(rwy, dist, intercept, gs_angle, below, elev)
        pitch = 2.5 if flap_idx < 3 else 1.0
        sc.set_init_position(lat, lon, alt, hdg, speed, pitch)
        time.sleep(1.0)
        self.log(f"Teleported: {dist:.1f} NM from threshold, {alt:.0f} ft MSL "
                 f"({alt - elev:.0f} ft above runway), heading {hdg:.0f}°T, {speed:.0f} kt")

        hdg_true = sc.get_var("PLANE HEADING DEGREES TRUE", "degrees")
        hdg_mag = sc.get_var("PLANE HEADING DEGREES MAGNETIC", "degrees")
        magvar = rw.angle_diff(hdg_true, hdg_mag) if hdg_true is not None and hdg_mag is not None else 0.0
        course_mag = round((rwy["course_true"] - magvar) % 360) or 360
        hdg_bug = round((hdg - magvar) % 360) or 360
        alt_target = int(round(alt / 100.0) * 100)

        # Aircraft configuration
        if sc.get_var("BRAKE PARKING POSITION", "bool"):
            sc.event("PARKING_BRAKES")
        sc.event("GEAR_DOWN" if gear_down else "GEAR_UP")
        sc.event("FLAPS_SET", int(flap_idx * 16383 / 4))
        sc.event("SPOILERS_ARM_ON" if gear_down else "SPOILERS_ARM_OFF")
        sc.event("LANDING_LIGHTS_ON")

        # Radios: NAV1 (default aircraft) and NAV3 (A32NX MMR) on the ILS
        if freq_hz:
            if sc.get_var("GPS DRIVES NAV1", "bool"):
                sc.event("TOGGLE_GPS_DRIVES_NAV1")
            sc.event("NAV1_RADIO_SET_HZ", freq_hz)
            sc.event("NAV3_RADIO_SET_HZ", freq_hz)
            sc.event("VOR1_SET", course_mag)
            sc.event("VOR3_SET", course_mag)
        self.log(f"Final course {course_mag:03d}°M, heading bug {hdg_bug:03d}°M, ALT {alt_target} ft, SPD {speed:.0f} kt")

        sc.event("PAUSE_OFF")
        time.sleep(0.8)

        if cfg["autopilot"]:
            if profile == "FlyByWire A32NX":
                self._fbw_autopilot(sc, speed, hdg_bug, alt_target, freq_hz)
            else:
                self._generic_autopilot(sc, speed, hdg_bug, alt_target, freq_hz)
        self.log("Ready - you are on the approach. Disconnect the autopilot whenever you want and land!")
        if profile == "FlyByWire A32NX":
            self.log("A32NX: put thrust levers in CLB if A/THR shows LVR CLB; press LS on the EFIS for ILS scales.")
        else:
            self.log("Tip: if the autothrottle does not hold speed, move your throttle to the CLB detent / set thrust.")
        return rwy

    # ------------------------------------------------------------ ILS helpers
    def _wait_for_localizer(self, sc, idx, freq_hz, timeout=12.0):
        """After a teleport the NAV receiver needs a moment; pressing APPR before the
        localizer is received is silently ignored by most aircraft."""
        t0 = time.time()
        retuned = False
        while time.time() - t0 < timeout:
            cur = sc.get_var(f"NAV ACTIVE FREQUENCY:{idx}", "Hz", timeout=1.5)
            if cur is not None and abs(cur - freq_hz) > 2000 and not retuned:
                self.log(f"NAV{idx} was re-tuned to {cur / 1e6:.2f} MHz by the aircraft - setting the ILS again.")
                sc.event(f"NAV{idx}_RADIO_SET_HZ", freq_hz)
                retuned = True
            if sc.get_var(f"NAV HAS LOCALIZER:{idx}", "bool", timeout=1.5):
                self.log(f"Localizer signal received on NAV{idx} after {time.time() - t0:.1f} s.")
                return True
            time.sleep(0.5)
        self.log(f"WARNING: no localizer signal on NAV{idx} after {timeout:.0f} s - trying APPR anyway.")
        return False

    def _lvar(self, sc, name):
        """Read an A32NX L-var; None if this sim/aircraft does not expose it."""
        return sc.get_var(f"L:{name}", "number", timeout=1.5)

    def disarm_previous_approach(self, sc, profile):
        """On a re-spawn the old approach is often still armed/captured (LOC/G/S/LAND).
        Clear it first so the new APPR press arms a fresh capture."""
        sc.event("A32NX.FCU_AP_DISCONNECT_PUSH" if profile == "FlyByWire A32NX" else "AUTOPILOT_OFF")
        if profile == "FlyByWire A32NX":
            if self._lvar(sc, "A32NX_FCU_APPR_MODE_ACTIVE"):
                sc.event("A32NX.FCU_APPR_PUSH")
            elif self._lvar(sc, "A32NX_FCU_LOC_MODE_ACTIVE"):
                sc.event("A32NX.FCU_LOC_PUSH")
        else:
            sc.event("AP_APR_HOLD_OFF")
            sc.event("AP_LOC_HOLD_OFF")
        time.sleep(0.3)

    # -------------------------------------------------------------- autopilot
    def _generic_autopilot(self, sc, speed, hdg, alt, freq_hz):
        sc.event("HEADING_BUG_SET", hdg)
        sc.event("AP_ALT_VAR_SET_ENGLISH", alt)
        sc.event("AP_SPD_VAR_SET", int(speed))
        if not sc.get_var("AUTOPILOT MASTER", "bool"):
            sc.event("AUTOPILOT_ON")
        time.sleep(0.3)
        sc.event("AP_HDG_HOLD_ON")
        sc.event("AP_ALT_HOLD_ON")
        if not sc.get_var("AUTOPILOT THROTTLE ARM", "bool"):
            sc.event("AUTO_THROTTLE_ARM")
        sc.event("AP_AIRSPEED_ON")
        self.log("Autopilot: AP ON, HDG, ALT HOLD, A/THR.")
        if not freq_hz:
            return
        self._wait_for_localizer(sc, 1, freq_hz)
        for attempt in range(1, 4):
            sc.event("AP_APR_HOLD_ON")
            time.sleep(1.0)
            if any(sc.get_var(v, "bool") for v in ("AUTOPILOT APPROACH HOLD", "AUTOPILOT APPROACH ARM",
                                                    "AUTOPILOT APPROACH ACTIVE")):
                self.log(f"APPR armed (LOC + G/S){'' if attempt == 1 else f' on attempt {attempt}'}.")
                return
            time.sleep(1.0)
        self.log("WARNING: APPR did not arm - press APPR / APR yourself once the localizer is alive.")

    def _fbw_autopilot(self, sc, speed, hdg, alt, freq_hz):
        sc.event("A32NX.FCU_SPD_SET", int(speed))
        sc.event("A32NX.FCU_SPD_PULL")
        sc.event("A32NX.FCU_HDG_SET", hdg)
        sc.event("A32NX.FCU_HDG_PULL")
        sc.event("A32NX.FCU_ALT_SET", alt)
        time.sleep(0.3)
        ap1 = self._lvar(sc, "A32NX_AUTOPILOT_1_ACTIVE")
        if ap1 is None:
            ap1 = sc.get_var("AUTOPILOT MASTER", "bool")
        if not ap1:
            sc.event("A32NX.FCU_AP_1_PUSH")
        time.sleep(0.5)
        athr = self._lvar(sc, "A32NX_AUTOTHRUST_STATUS")  # 0 off, 1 armed, 2 active
        if not athr:
            sc.event("A32NX.FCU_ATHR_PUSH")
        self.log("Autopilot (A32NX FCU): selected SPD/HDG, ALT set, AP1, A/THR.")
        if not freq_hz:
            return
        self._wait_for_localizer(sc, 3, freq_hz)
        time.sleep(0.5)
        if self._lvar(sc, "A32NX_FCU_APPR_MODE_ACTIVE") is None:
            # L-vars not readable: we cannot verify, so press exactly once (it is a toggle).
            sc.event("A32NX.FCU_APPR_PUSH")
            self.log("APPR pushed (state cannot be verified on this setup - check the FMA for LOC/G/S blue).")
            return
        for attempt in range(1, 4):
            if self._lvar(sc, "A32NX_FCU_APPR_MODE_ACTIVE"):
                self.log(f"APPR armed (LOC + G/S){'' if attempt <= 2 else f' after {attempt - 1} presses'}.")
                return
            sc.event("A32NX.FCU_APPR_PUSH")
            time.sleep(1.5)
        if self._lvar(sc, "A32NX_FCU_APPR_MODE_ACTIVE"):
            self.log("APPR armed (LOC + G/S).")
        else:
            self.log("WARNING: APPR did not arm - check MCDU RAD NAV shows the ILS, then press APPR yourself.")


# ====================================================================== GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.resizable(True, True)
        self.minsize(560, 520)
        self.q = queue.Queue()
        self.trainer = Trainer(self.q.put)
        self.busy = False
        s = self._load()

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Landing practice: spawn on the ILS final, aircraft configured, AP armed.",
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.v = {k: tk.StringVar(value=str(s.get(k, d))) for k, d in {
            "icao": "EDDF", "runway": "25C", "distance": "10", "speed": "160",
            "config": "Flaps 2, gear down", "intercept": "Straight-in on centerline",
            "profile": "Auto-detect", "freq": ""}.items()}
        self.below = tk.BooleanVar(value=s.get("below_gs", True))
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
        ttk.Spinbox(frm, from_=3, to=30, increment=1, textvariable=self.v["distance"], width=8).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, text="Configuration:").grid(row=r, column=0, sticky="w", pady=3)
        cb = ttk.Combobox(frm, textvariable=self.v["config"], values=list(CONFIGS), state="readonly", width=32)
        cb.grid(row=r, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda _e: self.v["speed"].set(str(CONFIGS[self.v["config"].get()][2])))
        r += 1
        ttk.Label(frm, text="Speed (kt IAS):").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=100, to=250, increment=5, textvariable=self.v["speed"], width=8).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, text="Approach:").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.v["intercept"], values=list(INTERCEPTS), state="readonly", width=32).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, text="Aircraft profile:").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.v["profile"], values=PROFILES, state="readonly", width=32).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(frm, text="ILS frequency override (MHz):").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.v["freq"], width=10).grid(row=r, column=1, sticky="w")
        ttk.Label(frm, text="leave empty = automatic", foreground="gray").grid(row=r, column=1, sticky="w", padx=(90, 0))
        r += 1
        ttk.Checkbutton(frm, text="Start slightly below the glideslope (capture G/S from below)", variable=self.below).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        ttk.Checkbutton(frm, text="Engage autopilot + arm APPR (otherwise hand-fly from the start)", variable=self.ap).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self.btn = ttk.Button(frm, text="✈  Spawn on approach  (again = retry the approach)", command=self._spawn)
        self.btn.grid(row=r, column=0, columnspan=2, sticky="we", pady=10, ipady=6)
        r += 1
        self.log_txt = tk.Text(frm, height=14, wrap="word", font=("Consolas", 9), state="disabled")
        self.log_txt.grid(row=r, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(r, weight=1)

        self._log("Start a flight in MSFS (engines running, e.g. on a runway), then press Spawn.")
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)
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
        self.busy = True
        self.btn.configure(state="disabled")
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

    def _log(self, msg):
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", msg + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    self.busy = False
                    self.btn.configure(state="normal")
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _fill_runways(self):
        try:
            lst = self.trainer.database().runways(self.v["icao"].get().strip())
            self.rwy_cb.configure(values=lst)
        except Exception as ex:
            self._log(f"Runway database error: {ex}")

    def _cfg(self):
        c = {k: v.get().strip() for k, v in self.v.items()}
        c["icao"] = c["icao"].upper()
        c["below_gs"] = self.below.get()
        c["autopilot"] = self.ap.get()
        return c

    def _spawn(self):
        if self.busy:
            return
        cfg = self._cfg()
        self._save(cfg)
        self.busy = True
        self.btn.configure(state="disabled")
        self._log("-" * 60)

        def job():
            try:
                self.trainer.spawn(cfg)
            except (SimConnectError, ValueError) as ex:
                self.q.put(f"ERROR: {ex}")
            except Exception as ex:  # keep the app alive on anything unexpected
                self.q.put(f"ERROR ({type(ex).__name__}): {ex}")
                self.trainer.sc = None
            finally:
                self.q.put(None)

        threading.Thread(target=job, daemon=True).start()

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
