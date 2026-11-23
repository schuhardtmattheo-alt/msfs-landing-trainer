MSFS LANDING TRAINER  (Microsoft Flight Simulator 2020)
==============================================================

What it does
------------
Practise ILS approaches and landings without flying the whole route.
You pick an airport and runway, and the tool works in two steps:

  1  SPAWN ON FINAL
     Your aircraft is placed exactly on the localizer and exactly on the
     glideslope of that runway (default 10 NM out), configured for landing
     (flaps, gear, landing lights, parking brake released) and FROZEN in the
     air. The aircraft's systems keep running while it is frozen.
     The tool shows the ILS frequency and course from the sim's own data.
     You now tune the ILS yourself and set the thrust levers to CLB.

  2  START APPROACH
     The freeze is released with the correct approach speed and descent rate,
     and the autopilot, autothrust and APPR mode are switched on. The tool
     checks that each one really is ON (and tries again if not).
     The autopilot now flies the ILS. Take over whenever you like and land.

Press 1 again to fly the approach as often as you want.

Installation
------------
Nothing to install. Unzip anywhere (NOT into the Community folder - this is an
external app) and start LandingTrainer\LandingTrainer.exe.
(Windows SmartScreen may warn because the exe is not signed:
 "More info" -> "Run anyway".)

How to use
----------
1. Start MSFS 2020 and begin a flight at ANY airport (e.g. on a runway),
   engines running. Supported: Fenix A319/A320/A321, FlyByWire A32NX,
   LVFR A319/A321 and the default A320neo (others: "generic" profile).
2. Start LandingTrainer.exe, enter airport (e.g. EDDF) and runway (e.g. 25C).
3. Press "1  Spawn on final". The aircraft is now frozen on the approach.
4. Tune the ILS shown in the tool:
     Airbus: MCDU RAD NAV -> ILS/FREQ (LSK 3L), then CRS (LSK 4L)
     Default aircraft: NAV1
   The tool shows live whether the localizer and glideslope are received.
5. Thrust levers to the CLB detent (Airbus). Nothing moves yet.
6. Press "2  Start approach". AP, A/THR and APPR come on, the aircraft flies
   down the glideslope.

Options
-------
Distance           start point from the runway threshold (3-25 NM)
Configuration      Flaps 1 / Flaps 2 + gear / Flaps 3 + gear / Landing (FULL)
Speed              approach speed (filled in automatically per configuration)
Approach           straight-in on LOC + G/S, or a 30 deg intercept from
                   left/right (level, the G/S is captured from below)
Aircraft profile   Auto-detect (by aircraft title), Fenix, FlyByWire/LVFR,
                   default A320neo / generic
Autopilot          untick to hand-fly the approach from the start

Notes / limits
--------------
* Fenix: needs a current MSFS 2020 (Sim Update 12 or newer).
* If the FMA shows LVR CLB, move the thrust levers to the CLB detent.
* If no ILS exists for the runway, you are placed on the runway centerline
  on a 3 degree path; fly it visually.
* Engines must be running before you spawn (the tool warns you).
* On start the app checks for a new version and offers to update itself.
* Settings are remembered in %APPDATA%\LandingTrainer\settings.json

Changelog
---------
1.4  New two-step flow: spawn exactly on localizer + glideslope, frozen
     while you tune the ILS and set thrust; then the approach starts with
     correct speed and descent rate, AP + A/THR + APPR engaged and verified.
     ILS is no longer tuned automatically.
1.3  Fenix A319/A320/A321 support, LVFR, better ILS detection.
1.2  Auto-update: the app checks GitHub Releases on start and updates itself.
1.1  More reliable APPR arming, previous approach cleared before re-spawn,
     folder build.
1.0  Initial release.

Credits: runway data from OurAirports (public domain).
SimConnect.dll (c) Microsoft, from the MSFS SDK.
