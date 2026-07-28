r"""
PlateUp bridge client.

Transport: newline-delimited JSON over the Windows named pipe
\\.\pipe\plateup_bridge, via pywin32 CreateFile. Python's builtin open() raises
OSError EINVAL on named pipes, so win32file is required:

    pip install pywin32

Protocol:
    hello  (game -> here)  once on connect: build, schema, session identity
    obs    (game -> here)  observations
    dict   (game -> here)  id -> name maps
    <any>  (here -> game)  action frames

Action fields (all optional, default 0/False):
    move   [x, z]   continuous, magnitude <= 1. NOTE this is ALSO the aim vector:
                    AttemptInteraction projects the interaction point along it, so
                    the direction held at the press frame decides what you grab.
    grab            held-down state; the mod derives Pressed/Held/Released edges.
    interact        held-down state. Hold across ticks to chop/wash.
    stop            StopMoving -- rotate in place without walking.
    ready           Ready/Start alias for SecondaryAction1 (Interact3), which
                    StartDayWarningView consumes from captured CInputData.
    menu_*          Popup navigation: select, cancel, up, down, left, right.
    request         None | InLocalMenu | QuitSection | InstantJoin
                    | StartPractice
"""

import json
import math
import time

try:
    import win32file
    import win32pipe
except ImportError:  # pragma: no cover
    raise SystemExit("pywin32 required:  pip install pywin32")


PIPE = r"\\.\pipe\plateup_bridge"

# Schemas this client understands. A mismatch means the mod was rebuilt with a
# different contract -- refuse rather than silently writing incompatible data.
EXPECT_PROTOCOL = 1
EXPECT_OBS_SCHEMA = "obs_0.1"
EXPECT_ACT_SCHEMA = "act_0.1"


class SchemaMismatch(RuntimeError):
    pass


class PlateUpBridge:
    def __init__(self, path=PIPE, strict=True):
        self.path = path
        self.strict = strict
        self._h = None
        self._buf = b""
        self.tick = 0
        self.hello = None
        self._cmd_id = 0
        self.last_ack = 0
        self.dropped = 0

    # ---- connection -------------------------------------------------

    def connect(self, timeout=30.0):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                self._h = win32file.CreateFile(
                    self.path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None)
                win32pipe.SetNamedPipeHandleState(
                    self._h, win32pipe.PIPE_READMODE_BYTE, None, None)
                self._handshake()
                self._cmd_id = 0
                self.last_ack = 0
                self.dropped = 0
                return self.hello
            except SchemaMismatch:
                self.close()
                raise
            except Exception as exc:
                last = exc
                self.close()
                time.sleep(0.5)
        raise TimeoutError(
            f"no pipe after {timeout}s. Is PlateUp running with the bridge mod "
            f"loaded? last error: {last}")

    def _handshake(self):
        msg = self._recv_raw()
        if msg.get("kind") != "hello":
            raise SchemaMismatch(f"expected hello, got {msg.get('kind')!r}")
        self.hello = msg

        problems = []
        if msg.get("protocol") != EXPECT_PROTOCOL:
            problems.append(
                f"protocol {msg.get('protocol')} != {EXPECT_PROTOCOL}")
        if msg.get("obs_schema") != EXPECT_OBS_SCHEMA:
            problems.append(
                f"obs schema {msg.get('obs_schema')!r} != {EXPECT_OBS_SCHEMA!r}")
        if msg.get("act_schema") != EXPECT_ACT_SCHEMA:
            problems.append(
                f"act schema {msg.get('act_schema')!r} != {EXPECT_ACT_SCHEMA!r}")

        if problems:
            text = "bridge/client mismatch: " + "; ".join(problems)
            if self.strict:
                raise SchemaMismatch(text)
            print("WARNING: " + text)

        print(f"connected | game {msg.get('game_version')} "
              f"| bridge {msg.get('bridge_version')} "
              f"| mod {msg.get('mod_hash')} "
              f"| session {msg.get('session_id', '')[:8]}")

    def close(self):
        if self._h:
            try:
                win32file.CloseHandle(self._h)
            except Exception:
                pass
            self._h = None
        self._buf = b""

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ---- provenance for run manifests -------------------------------

    def manifest(self):
        """Everything needed to identify what produced a trajectory."""
        h = self.hello or {}
        return {
            "session_id": h.get("session_id"),
            "game_version": h.get("game_version"),
            "unity_version": h.get("unity"),
            "bridge_version": h.get("bridge_version"),
            "mod_hash": h.get("mod_hash"),
            "protocol": h.get("protocol"),
            "obs_schema": h.get("obs_schema"),
            "act_schema": h.get("act_schema"),
            "demo_schema": h.get("demo_schema"),
            "connected_at": time.time(),
        }

    # ---- io ---------------------------------------------------------

    def _recv_raw(self):
        while b"\n" not in self._buf:
            _, chunk = win32file.ReadFile(self._h, 4096)
            if not chunk:
                raise ConnectionError("pipe closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def recv(self):
        msg = self._recv_raw()
        if "tick" in msg:
            self.tick = msg["tick"]
        if "ack_command" in msg:
            self.last_ack = msg["ack_command"]
            self.dropped = msg.get("cmds_dropped", 0)
        return msg

    @property
    def unacked(self):
        """Number of sent commands not yet acknowledged by an observation."""
        return max(0, self._cmd_id - self.last_ack)

    def send(self, move=(0.0, 0.0), grab=False, interact=False,
             secondary1=False, secondary2=False, stop=False,
             ready=False, menu_select=False, menu_cancel=False,
             menu_up=False, menu_down=False, menu_left=False,
             menu_right=False, request="None"):
        self._cmd_id += 1
        frame = {
            "Tick": self.tick,
            "CommandId": self._cmd_id,
            "MoveX": float(move[0]),
            "MoveY": float(move[1]),
            "Grab": bool(grab),
            "Interact": bool(interact),
            "Secondary1": bool(secondary1),
            "Secondary2": bool(secondary2),
            "StopMoving": bool(stop),
            "Ready": bool(ready),
            "MenuSelect": bool(menu_select),
            "MenuCancel": bool(menu_cancel),
            "MenuUp": bool(menu_up),
            "MenuDown": bool(menu_down),
            "MenuLeft": bool(menu_left),
            "MenuRight": bool(menu_right),
            "Request": request,
        }
        win32file.WriteFile(self._h, (json.dumps(frame) + "\n").encode("utf-8"))
        return self._cmd_id

    def idle(self):
        return self.send()

    def set_demo_recording(self, enabled):
        """Enable/disable native IInputConsumer frames for this connection."""
        frame = {
            "kind": "demo_control",
            "enabled": bool(enabled),
        }
        win32file.WriteFile(
            self._h, (json.dumps(frame) + "\n").encode("utf-8"))


# ---- helpers --------------------------------------------------------


def player(obs, pid=None):
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
    Crude proportional controller -- enough to prove the loop, NOT the motor
    policy. The chef must rotate to face a direction before he accelerates
    (MaximumFacingSpread in PlayerWalkingComponent), so expect turn latency.
    """
    for _ in range(max_ticks):
        obs = bridge.recv()
        if obs.get("kind") != "obs":
            continue

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
            print(f"arrived ({p['x']:.2f}, {p['z']:.2f})")
            return True

        scale = min(1.0, dist / 0.8)
        bridge.send(move=(mx * scale, mz * scale))

    bridge.idle()
    print("gave up")
    return False


def main():
    with PlateUpBridge() as bridge:
        print(json.dumps(bridge.manifest(), indent=2))

        obs = bridge.recv()
        while obs.get("kind") != "obs":
            obs = bridge.recv()

        if not obs.get("override"):
            print("\n>>> press F9 in game to hand control to the bridge <<<\n")

        p = player(obs)
        if p is None:
            print("no player entity; are you in a restaurant?")
            return

        x0, z0 = p["x"], p["z"]
        for tx, tz in [(x0 + 2, z0), (x0 + 2, z0 + 2), (x0, z0 + 2), (x0, z0)]:
            print(f"-> ({tx:.2f}, {tz:.2f})")
            walk_to(bridge, tx, tz)

        bridge.idle()
        print("done")


if __name__ == "__main__":
    main()
