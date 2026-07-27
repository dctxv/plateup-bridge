r"""
PlateUp bridge client.

Protocol: newline-delimited JSON over the Windows named pipe \\.\pipe\plateup_bridge.

Inbound  (game -> here):  observation frames, ~12 Hz
Outbound (here -> game):  action frames, sent whenever you like

Action frame fields (all optional, default 0/False):
    move   [x, z]   continuous, magnitude <= 1. NOTE this is also the aim vector:
                    AttemptInteraction projects the interaction point along it, so
                    the direction you hold at the moment you press Grab decides
                    what you grab.
    grab            bool, held-down state. The mod converts to Pressed/Held edges.
    interact        bool, held-down state. Hold across ticks to chop/wash.
    stop            bool, StopMoving (rotate in place without walking).
    request         one of: None, InLocalMenu, Disconnect, QuitSection,
                    InstantJoin, KickUser, StartPractice, QuitToLobby
"""

import json
import math
import time

import win32file
import win32pipe


PIPE = r"\\.\pipe\plateup_bridge"


class PlateUpBridge:
    def __init__(self, path=PIPE):
        self.path = path
        self._h = None
        self._buf = b""
        self.tick = 0

    # ---- connection -------------------------------------------------

    def connect(self, timeout=30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._h = win32file.CreateFile(
                    self.path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None)
                win32pipe.SetNamedPipeHandleState(
                    self._h, win32pipe.PIPE_READMODE_BYTE, None, None)
                return
            except Exception:
                time.sleep(0.5)
        raise TimeoutError("no pipe")

    def close(self):
        if getattr(self, "_h", None):
            win32file.CloseHandle(self._h)
            self._h = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ---- io ---------------------------------------------------------

    def _read_raw(self, n=4096):
        _, data = win32file.ReadFile(self._h, n)
        return data

    def _write_raw(self, data):
        win32file.WriteFile(self._h, data)

    def recv(self):
        """Block until one observation frame arrives. Returns a dict."""
        while b"\n" not in self._buf:
            chunk = self._read_raw()
            if not chunk:
                raise ConnectionError("pipe closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        obs = json.loads(line.decode("utf-8"))
        self.tick = obs.get("tick", 0)
        return obs

    def send(self, move=(0.0, 0.0), grab=False, interact=False,
             secondary1=False, secondary2=False, stop=False, request="None"):
        frame = {
            "Tick": self.tick,
            "MoveX": float(move[0]),
            "MoveY": float(move[1]),
            "Grab": bool(grab),
            "Interact": bool(interact),
            "Secondary1": bool(secondary1),
            "Secondary2": bool(secondary2),
            "StopMoving": bool(stop),
            "Request": request,
        }
        self._write_raw((json.dumps(frame) + "\n").encode("utf-8"))

    def idle(self):
        self.send()


# ---- helpers --------------------------------------------------------


def player(obs, pid=None):
    """First player, or the one with the given id."""
    ps = obs.get("players", [])
    if not ps:
        return None
    if pid is None:
        return ps[0]
    return next((p for p in ps if p["id"] == pid), None)


def unit_toward(px, pz, tx, tz):
    dx, dz = tx - px, tz - pz
    d = math.hypot(dx, dz)
    if d < 1e-6:
        return 0.0, 0.0, 0.0
    return dx / d, dz / d, d


# ---- demo -----------------------------------------------------------


def walk_to(bridge, tx, tz, tol=0.25, max_ticks=600):
    """
    Crude proportional controller. Good enough to prove the loop; it is NOT the
    motor policy. Note the chef must rotate to face a direction before he
    accelerates (MaximumFacingSpread in PlayerWalkingComponent), so expect
    turn latency on direction changes.
    """
    for _ in range(max_ticks):
        obs = bridge.recv()

        if not obs.get("in_restaurant") or obs.get("paused"):
            bridge.idle()
            continue

        p = player(obs)
        if p is None:
            bridge.idle()
            continue

        mx, mz, dist = unit_toward(p["x"], p["z"], tx, tz)
        if dist < tol:
            bridge.idle()
            print(f"arrived at ({p['x']:.2f}, {p['z']:.2f}) after {dist:.2f} to go")
            return True

        # ease off near the target so we do not oscillate
        scale = max(0.55, min(1.0, dist / 0.8))
        bridge.send(move=(mx * scale, mz * scale))

    bridge.idle()
    print("gave up")
    return False


def main():
    with PlateUpBridge() as b:
        print("connected. waiting for a frame...")
        obs = b.recv()
        print(json.dumps(obs, indent=2)[:800])

        if not obs.get("override"):
            print("\n>>> press F9 in game to hand control to the bridge <<<\n")

        p = player(obs)
        if p is None:
            print("no player entity; are you in a restaurant?")
            return

        # Walk a 2x2 box around the spawn point.
        x0, z0 = p["x"], p["z"]
        for tx, tz in [(x0 + 2, z0), (x0 + 2, z0 + 2), (x0, z0 + 2), (x0, z0)]:
            print(f"-> ({tx:.2f}, {tz:.2f})")
            walk_to(b, tx, tz)

        b.idle()
        print("done")


if __name__ == "__main__":
    main()
