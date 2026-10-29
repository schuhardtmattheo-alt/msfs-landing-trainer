MSFS LANDING TRAINER  (Microsoft Flight Simulator 2020)
==============================================================

What it does
------------
You enter a destination airport (ICAO) and a runway. The tool then
  1. teleports your aircraft onto the ILS final approach (default 10 NM out,
     slightly below the glideslope, aligned with the runway),
  2. finds the ILS of that runway in the sim's own navaid data
     (frequency, glideslope angle) and tunes NAV1 + NAV3 and the course,
  3. configures the aircraft (flaps, gear, spoilers armed, landing lights,
     parking brake released),
  4. sets the autopilot: speed, heading, altitude, AP ON, A/THR, APPR armed.
     It waits until the localizer signal is received, re-tunes the ILS if the
     aircraft changed it, and checks that APPR really armed (retries if not).
     The aircraft captures LOC and G/S on its own. Disconnect the AP whenever
     you like and land by hand.
Press the button again to repeat the same approach as often as you want.

Installation
------------
Nothing to install. Unzip anywhere (NOT into the Community folder - this is an
external app) and start LandingTrainer\LandingTrainer.exe.
(Windows SmartScreen may warn because the exe is not signed:
 "More info" -> "Run anyway".)

How to use
----------
1. Start MSFS 2020 and begin a flight at ANY airport (e.g. on a runway),
   engines running. Best aircraft: FlyByWire A32NX or the default A320neo
   (other aircraft work with the "Generic" profile).
2. Start LandingTrainer.exe (MSFS can stay in the foreground / full screen
   is fine; alt-tab to the tool).
3. Enter airport (e.g. EDDF), choose runway (e.g. 25C), distance, configuration.
4. Click "Spawn on approach". The sim pauses briefly, you are teleported,
   everything is set up, the sim resumes. Done.

Options
-------
Distance           start point from the runway threshold (3-30 NM)
Configuration      Clean / Flaps 1 / Flaps 2 + gear / Flaps 3 + gear / Landing
Speed              target speed (filled automatically per configuration)
Approach           straight-in, or a 30 deg intercept from left/right
                   (practise LOC capture)
Aircraft profile   Auto-detect (A32NX is recognised by the aircraft title),
                   FlyByWire A32NX (uses A32NX FCU events), Generic
ILS freq override  only needed if the ILS is not found automatically
Below glideslope   start ~150 ft below the G/S so it is captured from below
Engage autopilot   untick to hand-fly the whole approach

Notes / limits
--------------
* A32NX: if the FMA shows LVR CLB, move the thrust levers to the CLB detent.
  Press LS on the EFIS to see the ILS scales. The MCDU flight plan itself is
  NOT entered (the A32NX MCDU cannot be programmed from outside the sim);
  the approach is flown via the ILS radio + FCU, which is what matters here.
  If the A32NX re-tunes the ILS itself, enter the frequency in MCDU RAD NAV.
* If no ILS exists for the runway, the tool still spawns you on the extended
  centerline; then fly it visually.
* Engines must be running before you spawn (the tool warns you).
* On start the app checks for a new version and offers to update itself.
* Settings are remembered in %APPDATA%\LandingTrainer\settings.json

Changelog
---------
1.2  Auto-update: the app checks GitHub Releases on start and updates itself.
1.1  More reliable APPR arming, previous approach cleared before re-spawn,
     folder build.
1.0  Initial release.

Credits: runway data from OurAirports (public domain).
SimConnect.dll (c) Microsoft, from the MSFS SDK.
