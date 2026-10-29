# flightsim.to listing – copy & paste

**Title:** Landing Trainer – instant ILS approach practice

**Category:** Tools / Utilities

**Short description (one line):**
Spawn directly on the ILS final of any runway – aircraft configured, ILS tuned, autopilot armed. Practise landings over and over.

---

**Description:**

Want to practise landings without flying the whole route every time? Landing Trainer puts you straight on the final approach.

Enter an airport and a runway, click **Spawn on approach**, and the tool will:

- teleport your aircraft onto the extended runway centerline (3–30 NM out, slightly below the glideslope)
- find the runway's ILS automatically from the sim's own navigation data and tune NAV1/NAV3 + course
- configure the aircraft: flaps, gear, spoilers armed, landing lights, parking brake released
- set the autopilot: speed, heading, altitude, AP + A/THR on, APPR armed – it waits for the localizer signal and checks that APPR actually armed

Disconnect the autopilot whenever you like and land by hand. Click again to repeat the approach instantly.

**Features**
- Works at every airport in the world with a published runway
- Straight-in or 30° intercept from left/right (practise LOC capture)
- 5 configurations from clean to full landing configuration
- Optional: no autopilot – hand-fly the whole approach
- Airbus A320 family: Fenix A319/A320/A321 (ILS typed into the MCDU automatically), FlyByWire A32NX, LVFR A319/A321, default A320neo
- Remembers your last settings

**Installation**
1. Unzip the folder anywhere (NOT into the Community folder – this is an external app).
2. Start a flight in MSFS 2020 with engines running.
3. Run `LandingTrainer.exe`.

No install, no internet needed.

**Known limits**
- The MCDU flight plan is not entered; the approach is flown via the ILS radio and FCU/autopilot.
- A32NX: move the thrust levers to CLB if the FMA shows LVR CLB; press LS for ILS scales.
- Runways without ILS: you are still placed on the centerline – fly it visually.
- Windows may show a SmartScreen warning because the exe is not code-signed ("More info" → "Run anyway"). The full Python source code is included.

**Credits**
Runway data: OurAirports (public domain). SimConnect.dll © Microsoft (MSFS SDK).

---

**Changelog**
- 1.3.0 - Fenix A319/A320/A321 support: ILS entered in MCDU RAD NAV, FCU set up, APPR verified. LVFR support, better ILS detection.
- 1.1 – More reliable APPR: waits for localizer signal, re-tunes the ILS if the aircraft overrides it, verifies and retries APPR; clears the previous approach before a re-spawn. Folder build (fewer antivirus false positives).
- 1.0 – Initial release.

**Tags:** landing, ILS, approach, training, practice, autopilot, A32NX, A320, tool
