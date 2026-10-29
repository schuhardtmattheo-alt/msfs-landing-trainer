# MSFS Landing Trainer

External tool for Microsoft Flight Simulator 2020: enter an airport and runway, and you are spawned on the ILS final with the aircraft configured, ILS tuned and the autopilot armed. Made for practising landings.

**Download:** see [Releases](../../releases/latest). Unzip anywhere (not into the Community folder) and run `LandingTrainer\LandingTrainer.exe`. See `package/README.txt` for usage.

## Auto-update

On start the app asks the GitHub API for the latest release of this repository. If it is newer than the running version and has a `.zip` attached, the user is offered the update; the app downloads it, closes, replaces its files and restarts.

## Publishing a new version

1. Commit and push your changes.
2. On GitHub: **Releases → Draft a new release**, create a new tag such as `v1.3.0` (always higher than the last one), add release notes, **Publish release**.
3. The workflow `.github/workflows/release.yml` builds the app (version taken from the tag) and attaches `MSFS-LandingTrainer-1.3.0.zip` to the release, which takes about 3–5 minutes.
4. From then on, every installed copy offers the update when it is opened.

The workflow also downloads the latest OurAirports runway data and `SimConnect.dll`, so neither has to be committed.

## Layout

- `src/`: Python source (`landing_trainer.py` GUI, `simconnect_lite.py`, `runways.py`, `updater.py`, `version.py`)
- `package/`: README and license that ship in the zip
- `docs/`: flightsim.to listing text

## Credits

Runway data: OurAirports (public domain). SimConnect.dll © Microsoft (MSFS SDK). Code: MIT License.
