"""Runway database (OurAirports, public domain) and approach geometry."""
import csv
import math
import os
import sys

EARTH_NM = 3440.065
FT_PER_NM = 6076.12


def _data_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", name)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ geometry
def destination(lat, lon, brg_deg, dist_nm):
    d = dist_nm / EARTH_NM
    b = math.radians(brg_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def distance_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_NM * math.asin(math.sqrt(a))


def angle_diff(a, b):
    return (a - b + 180) % 360 - 180


# ------------------------------------------------------------------ database
class RunwayDB:
    def __init__(self, path=None):
        self.by_airport = {}
        with open(path or _data_path("runways.csv"), newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("closed") == "1":
                    continue
                self.by_airport.setdefault(row["airport_ident"].upper(), []).append(row)

    def runways(self, icao):
        """List of landing-runway idents that have coordinates."""
        out = []
        for row in self.by_airport.get(icao.upper(), []):
            for end in ("le", "he"):
                if row[f"{end}_ident"] and _f(row[f"{end}_latitude_deg"]) is not None:
                    out.append(row[f"{end}_ident"].upper())
        return sorted(set(out), key=lambda s: (int("".join(c for c in s if c.isdigit()) or 0), s))

    def runway(self, icao, ident):
        ident = normalize_ident(ident)
        for row in self.by_airport.get(icao.upper(), []):
            for end, other in (("le", "he"), ("he", "le")):
                if normalize_ident(row[f"{end}_ident"]) != ident:
                    continue
                lat, lon = _f(row[f"{end}_latitude_deg"]), _f(row[f"{end}_longitude_deg"])
                olat, olon = _f(row[f"{other}_latitude_deg"]), _f(row[f"{other}_longitude_deg"])
                if lat is None or olat is None:
                    raise ValueError(f"Runway {ident} at {icao} has no coordinates in the database.")
                hdg = bearing(lat, lon, olat, olon)
                disp_ft = _f(row[f"{end}_displaced_threshold_ft"]) or 0.0
                if disp_ft:
                    lat, lon = destination(lat, lon, hdg, disp_ft / FT_PER_NM)
                return dict(icao=icao.upper(), ident=ident, thr_lat=lat, thr_lon=lon, course_true=hdg,
                            elev_ft=_f(row[f"{end}_elevation_ft"]),
                            length_ft=_f(row["length_ft"]) or distance_nm(lat, lon, olat, olon) * FT_PER_NM)
        if icao.upper() not in self.by_airport:
            raise ValueError(f"Airport {icao.upper()} not found in the runway database.")
        raise ValueError(f"Runway {ident} not found at {icao.upper()}. Available: {', '.join(self.runways(icao))}")


def normalize_ident(s):
    s = (s or "").strip().upper()
    num = "".join(c for c in s if c.isdigit())
    suffix = "".join(c for c in s if c.isalpha())
    return (num.zfill(2) if num else "") + suffix


# ------------------------------------------------------------------ approach
def pick_ils(rwy, navaids, relaxed=False):
    """Choose the localizer that serves this runway from the sim's nearby-navaid list.

    relaxed: wider limits, for airports whose database threshold is a bit off from the sim's.
    """
    max_cross, extra_nm = (1.0, 6) if relaxed else (0.35, 3)
    best = None
    for n in navaids:
        if not n["flags"] & 2:  # has localizer
            continue
        d = distance_nm(rwy["thr_lat"], rwy["thr_lon"], n["lat"], n["lon"])
        if d > rwy["length_ft"] / FT_PER_NM + extra_nm:
            continue
        brg = bearing(rwy["thr_lat"], rwy["thr_lon"], n["lat"], n["lon"])
        along = d * math.cos(math.radians(angle_diff(brg, rwy["course_true"])))
        cross = abs(d * math.sin(math.radians(angle_diff(brg, rwy["course_true"]))))
        if along <= 0 or cross > max_cross:
            continue
        if best is None or cross < best[0]:
            best = (cross, n)
    return best[1] if best else None


FT_PER_M = 3.28084


def final_course(rwy, ils=None):
    """True course of the final approach, and a point on it (the localizer antenna if known).

    The sim's localizer antenna defines the centerline more precisely than the runway database;
    its heading is used when it agrees with the runway (otherwise it may be magnetic)."""
    crs = rwy["course_true"]
    if ils and ils["flags"] & 2:
        if abs(angle_diff(ils["loc_hdg"], crs)) < 2.0:
            crs = ils["loc_hdg"] % 360
        return crs, (ils["lat"], ils["lon"])
    return crs, (rwy["thr_lat"], rwy["thr_lon"])


def spawn_point(rwy, dist_nm, intercept, ils=None, elev_ft=0.0):
    """Return dict(lat, lon, alt, hdg, crs, on_gs) for the start of the approach.

    The aircraft is placed exactly on the localizer centerline, dist_nm before the threshold,
    exactly on the glideslope (computed from the sim's glideslope antenna when available).
    intercept: 0 = straight in, -30 = from the left, +30 = from the right (level, on G/S height).
    """
    crs, anchor = final_course(rwy, ils)
    # distance from the anchor back to the threshold, measured along the course
    d = distance_nm(anchor[0], anchor[1], rwy["thr_lat"], rwy["thr_lon"])
    brg = bearing(anchor[0], anchor[1], rwy["thr_lat"], rwy["thr_lon"]) if d > 0.01 else crs + 180
    back_to_thr = d * math.cos(math.radians(angle_diff(brg, crs + 180)))

    def on_centerline(dist):
        return destination(anchor[0], anchor[1], crs + 180, back_to_thr + dist)

    plat, plon = on_centerline(dist_nm)
    has_gs = bool(ils and ils["flags"] & 4)
    gs_angle = ils["gs_angle"] if has_gs and 2.0 <= ils["gs_angle"] <= 4.5 else 3.0
    if has_gs:
        d_gs = distance_nm(ils["gs_lat"], ils["gs_lon"], plat, plon)
        alt = ils["gs_alt_m"] * FT_PER_M + d_gs * FT_PER_NM * math.tan(math.radians(gs_angle))
    else:
        alt = elev_ft + 50 + dist_nm * FT_PER_NM * math.tan(math.radians(gs_angle))

    if not intercept:
        return dict(lat=plat, lon=plon, alt=alt, hdg=crs, crs=crs, on_gs=True, gs_angle=gs_angle)
    offset = 2.0  # NM beside the centerline
    lat, lon = on_centerline(dist_nm + offset / math.tan(math.radians(abs(intercept))))
    lat, lon = destination(lat, lon, crs - 90 if intercept < 0 else crs + 90, offset)
    hdg = (crs + 30 if intercept < 0 else crs - 30) % 360
    return dict(lat=lat, lon=lon, alt=alt, hdg=hdg, crs=crs, on_gs=False, gs_angle=gs_angle)
