"""Minimal ctypes wrapper around SimConnect.dll (MSFS 2020).

Only the calls Landing Trainer needs are wrapped: data definitions, set/request
SimVars, client events and the nearby-VOR facility list (which also contains
ILS localizers with frequency, course and glideslope position).
"""
import ctypes
import os
import struct
import sys
import time
from ctypes import wintypes

HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD

OBJECT_ID_USER = 0
UNUSED = 0xFFFFFFFF

DT_FLOAT64 = 4
DT_STRING256 = 9
DT_INITPOSITION = 12

RECV_EXCEPTION = 1
RECV_OPEN = 2
RECV_QUIT = 3
RECV_SIMOBJECT_DATA = 8
RECV_VOR_LIST = 19

PERIOD_ONCE = 1
FACILITY_LIST_VOR = 3
GROUP_PRIORITY_HIGHEST = 1
EVENT_FLAG_GROUPID_IS_PRIORITY = 0x10

VOR_HAS_NAV = 1
VOR_HAS_LOCALIZER = 2
VOR_HAS_GLIDESLOPE = 4

E_FAIL = -2147467259  # 0x80004005, returned by GetNextDispatch when the queue is empty


class SimConnectError(Exception):
    pass


class InitPosition(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("Latitude", ctypes.c_double),
        ("Longitude", ctypes.c_double),
        ("Altitude", ctypes.c_double),  # feet MSL
        ("Pitch", ctypes.c_double),
        ("Bank", ctypes.c_double),
        ("Heading", ctypes.c_double),  # degrees true
        ("OnGround", DWORD),
        ("Airspeed", DWORD),  # knots
    ]


def _base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def find_dll():
    candidates = [
        os.path.join(os.path.dirname(sys.executable), "SimConnect.dll"),
        os.path.join(_base_dir(), "SimConnect.dll"),
        os.path.join(_base_dir(), "data", "SimConnect.dll"),
    ]
    sdk = os.environ.get("MSFS_SDK")
    if sdk:
        candidates.append(os.path.join(sdk, "SimConnect SDK", "lib", "SimConnect.dll"))
    candidates.append(r"C:\MSFS SDK\SimConnect SDK\lib\SimConnect.dll")
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise SimConnectError("SimConnect.dll not found (it should be next to the program).")


class SimConnect:
    def __init__(self, name="Landing Trainer", log=print):
        self.log = log
        self.dll = ctypes.WinDLL(find_dll())
        self._declare()
        self.h = HANDLE()
        self._next_id = 100
        self._events = {}
        self._send_names = {}
        self.data = {}
        self.vors = []
        self.vor_list_done = False
        self.quit = False
        hr = self.dll.SimConnect_Open(ctypes.byref(self.h), name.encode(), None, 0, None, 0)
        if hr != 0:
            raise SimConnectError("Could not connect to MSFS. Is the simulator running and a flight loaded?")
        self._define_static()

    # ---------------------------------------------------------------- setup
    def _declare(self):
        d = self.dll
        sig = {
            "SimConnect_Open": [ctypes.POINTER(HANDLE), ctypes.c_char_p, wintypes.HWND, DWORD, HANDLE, DWORD],
            "SimConnect_Close": [HANDLE],
            "SimConnect_AddToDataDefinition": [HANDLE, DWORD, ctypes.c_char_p, ctypes.c_char_p, DWORD, ctypes.c_float, DWORD],
            "SimConnect_SetDataOnSimObject": [HANDLE, DWORD, DWORD, DWORD, DWORD, DWORD, ctypes.c_void_p],
            "SimConnect_RequestDataOnSimObject": [HANDLE, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD],
            "SimConnect_MapClientEventToSimEvent": [HANDLE, DWORD, ctypes.c_char_p],
            "SimConnect_TransmitClientEvent": [HANDLE, DWORD, DWORD, DWORD, DWORD, DWORD],
            "SimConnect_GetNextDispatch": [HANDLE, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(DWORD)],
            "SimConnect_RequestFacilitiesList": [HANDLE, DWORD, DWORD],
            "SimConnect_GetLastSentPacketID": [HANDLE, ctypes.POINTER(DWORD)],
        }
        for fn, args in sig.items():
            f = getattr(d, fn)
            f.argtypes = args
            f.restype = ctypes.c_long

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def _remember(self, what):
        pid = DWORD()
        if self.dll.SimConnect_GetLastSentPacketID(self.h, ctypes.byref(pid)) == 0:
            self._send_names[pid.value] = what

    def _define_static(self):
        self.DEF_INIT = self._new_id()
        self.dll.SimConnect_AddToDataDefinition(self.h, self.DEF_INIT, b"Initial Position", None, DT_INITPOSITION, 0, UNUSED)
        self.DEF_TITLE = self._new_id()
        self.dll.SimConnect_AddToDataDefinition(self.h, self.DEF_TITLE, b"TITLE", None, DT_STRING256, 0, UNUSED)
        self._num_defs = {}

    def close(self):
        try:
            self.dll.SimConnect_Close(self.h)
        except Exception:
            pass

    # ------------------------------------------------------------- dispatch
    def pump(self):
        p = ctypes.c_void_p()
        n = DWORD()
        while True:
            hr = self.dll.SimConnect_GetNextDispatch(self.h, ctypes.byref(p), ctypes.byref(n))
            if hr != 0 or not p.value:
                return
            raw = ctypes.string_at(p.value, n.value)
            size, _ver, rid = struct.unpack_from("<III", raw, 0)
            if rid == RECV_EXCEPTION:
                exc, send_id, idx = struct.unpack_from("<III", raw, 12)
                what = self._send_names.get(send_id, "?")
                if "L:" not in what:  # unreadable L-vars are expected on some setups
                    self.log(f"  (sim reported exception {exc} for: {what})")
            elif rid == RECV_QUIT:
                self.quit = True
            elif rid == RECV_SIMOBJECT_DATA:
                req = struct.unpack_from("<I", raw, 12)[0]
                self.data[req] = raw[40:]
            elif rid == RECV_VOR_LIST:
                self._parse_vor_list(raw)

    def _parse_vor_list(self, raw):
        _req, count, entry, out_of = struct.unpack_from("<IIII", raw, 12)
        if count:
            stride = max(77, (len(raw) - 28) // count)
            for i in range(count):
                o = 28 + i * stride
                ident = raw[o:o + 9].split(b"\0")[0].decode("ascii", "ignore").strip()
                lat, lon, alt = struct.unpack_from("<ddd", raw, o + 9)
                magvar, freq, flags, loc = struct.unpack_from("<fIIf", raw, o + 33)
                glat, glon, galt, gsa = struct.unpack_from("<dddf", raw, o + 49)
                self.vors.append(dict(ident=ident, lat=lat, lon=lon, alt_m=alt, magvar=magvar,
                                      freq_hz=freq, flags=flags, loc_hdg=loc,
                                      gs_lat=glat, gs_lon=glon, gs_alt_m=galt, gs_angle=gsa))
        if entry + 1 >= out_of:
            self.vor_list_done = True

    # ------------------------------------------------------------- simvars
    def set_init_position(self, lat, lon, alt_ft, hdg_true, airspeed_kt, pitch=0.0):
        ip = InitPosition(lat, lon, alt_ft, -pitch, 0.0, hdg_true % 360.0, 0, int(airspeed_kt))
        self.dll.SimConnect_SetDataOnSimObject(self.h, self.DEF_INIT, OBJECT_ID_USER, 0, 0,
                                               ctypes.sizeof(ip), ctypes.byref(ip))
        self._remember("teleport (Initial Position)")

    def _num_def(self, name, unit):
        key = (name, unit)
        if key not in self._num_defs:
            did = self._new_id()
            self.dll.SimConnect_AddToDataDefinition(self.h, did, name.encode(), unit.encode(), DT_FLOAT64, 0, UNUSED)
            self._remember(f"define {name}")
            self._num_defs[key] = did
        return self._num_defs[key]

    def set_var(self, name, unit, value):
        did = self._num_def(name, unit)
        v = ctypes.c_double(value)
        self.dll.SimConnect_SetDataOnSimObject(self.h, did, OBJECT_ID_USER, 0, 0, 8, ctypes.byref(v))
        self._remember(f"set {name}")

    def _request(self, did, timeout, what=""):
        req = self._new_id()
        self.dll.SimConnect_RequestDataOnSimObject(self.h, req, did, OBJECT_ID_USER, PERIOD_ONCE, 0, 0, 0, 0)
        self._remember(f"read {what}")
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.pump()
            if req in self.data:
                return self.data.pop(req)
            time.sleep(0.05)
        return None

    def get_var(self, name, unit, timeout=3.0):
        raw = self._request(self._num_def(name, unit), timeout, name)
        return struct.unpack_from("<d", raw, 0)[0] if raw and len(raw) >= 8 else None

    def get_title(self, timeout=3.0):
        raw = self._request(self.DEF_TITLE, timeout, "TITLE")
        return raw[:256].split(b"\0")[0].decode("utf-8", "ignore") if raw else ""

    # -------------------------------------------------------------- events
    def event(self, name, value=0):
        eid = self._events.get(name)
        if eid is None:
            eid = self._new_id()
            self.dll.SimConnect_MapClientEventToSimEvent(self.h, eid, name.encode())
            self._remember(f"map event {name}")
            self._events[name] = eid
        self.dll.SimConnect_TransmitClientEvent(self.h, OBJECT_ID_USER, eid, int(value) & 0xFFFFFFFF,
                                                GROUP_PRIORITY_HIGHEST, EVENT_FLAG_GROUPID_IS_PRIORITY)
        self._remember(f"event {name}")
        self.pump()

    # ---------------------------------------------------------- facilities
    def nearby_navaids(self, timeout=4.0):
        self.vors = []
        self.vor_list_done = False
        self.dll.SimConnect_RequestFacilitiesList(self.h, FACILITY_LIST_VOR, self._new_id())
        self._remember("request nearby VOR/ILS list")
        t0 = time.time()
        while time.time() - t0 < timeout and not self.vor_list_done:
            self.pump()
            time.sleep(0.05)
        return list(self.vors)
