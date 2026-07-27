"""
Observation layer for the PlateUp bridge.

The mod emits two message kinds:
    dict  -- id -> name maps, once per connection
    obs   -- game state, ~12 Hz

This module handles the dict/obs split, resolves ids to names, and gives you a
World object that is convenient to poke at from a REPL. It deliberately does NOT
build tensors -- do that in a separate encoder so the representation can change
without redeploying the mod.
"""

import json
import time
from dataclasses import dataclass, field

from bridge import PlateUpBridge


# CCustomerState.State
CUSTOMER_STATE = {0: "normal", 1: "queue", 2: "at_table"}

# KitchenData.MenuPhase -- verify against the enum before relying on it
MEAL_PHASE = {
    0: "starter",
    1: "main",
    2: "dessert",
    3: "side",
    4: "complete",
}


@dataclass
class World:
    tick: int = 0
    act_tick: int = -1
    input_queue_depth: int = 0
    dropped_frames: int = 0
    day: int = 0
    time_of_day: float = 0.0
    in_restaurant: bool = False
    paused: bool = False
    override: bool = False
    input_captured: bool = False
    players: list = field(default_factory=list)
    appliances: list = field(default_factory=list)
    loose_items: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    customers: list = field(default_factory=list)

    @property
    def me(self):
        return self.players[0] if self.players else None

    def appliance_by_name(self, needle):
        n = needle.lower()
        return [a for a in self.appliances if n in a.get("name", "").lower()]

    def nearest(self, entities, x=None, z=None):
        if x is None or z is None:
            me = self.me
            if me is None:
                return None
            x, z = me["x"], me["z"]
        if not entities:
            return None
        return min(entities, key=lambda e: (e["x"] - x) ** 2 + (e["z"] - z) ** 2)

    def urgent_group(self):
        """Group with the least patience remaining, as a fraction."""
        active = [g for g in self.groups if g.get("patience_active")]
        if not active:
            return None
        return min(active, key=lambda g: g.get("patience_frac", 1.0))


class ObservationClient:
    def __init__(self, bridge=None):
        self.b = bridge or PlateUpBridge()
        self.appliance_names = {}
        self.item_names = {}
        self.process_names = {}
        self.camera_forward = None
        self.camera_right = None
        self.world = World()

    def connect(self, timeout=30.0):
        self.b.connect(timeout)

    def close(self):
        self.b.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ---- io ----

    def step(self, **action):
        """Send an action, block for the next observation, return the World."""
        self.b.send(**action)
        return self.recv()

    def recv(self):
        while True:
            msg = self.b.recv()
            kind = msg.get("kind")
            if kind == "dict":
                self._load_dict(msg)
                continue
            if kind == "obs":
                self._load_obs(msg)
                return self.world
            # unknown kind: ignore

    # ---- parsing ----

    def _load_dict(self, msg):
        self.appliance_names = {int(k): v for k, v in msg.get("appliances", {}).items()}
        self.item_names = {int(k): v for k, v in msg.get("items", {}).items()}
        self.process_names = {int(k): v for k, v in msg.get("processes", {}).items()}
        self.camera_forward = msg.get("camera_forward")
        self.camera_right = msg.get("camera_right")
        print(
            f"dict: {len(self.appliance_names)} appliances, "
            f"{len(self.item_names)} items, {len(self.process_names)} processes"
        )

    def _load_obs(self, m):
        w = self.world
        w.tick = m.get("tick", 0)
        w.act_tick = m.get("act_tick", -1)
        w.input_queue_depth = m.get("input_queue_depth", 0)
        w.dropped_frames = m.get("dropped_frames", 0)
        w.day = m.get("day", 0)
        w.time_of_day = m.get("time_of_day", 0.0)
        w.in_restaurant = m.get("in_restaurant", False)
        w.paused = m.get("paused", False)
        w.override = m.get("override", False)
        w.input_captured = m.get("input_captured", False)

        w.players = [self._player(p) for p in m.get("players", [])]
        w.appliances = [self._appliance(a) for a in m.get("appliances", [])]
        w.loose_items = [self._item(i) for i in m.get("loose_items", [])]
        w.groups = [self._group(g) for g in m.get("groups", [])]
        w.customers = [self._customer(c) for c in m.get("customers", [])]

    def _player(self, p):
        p = dict(p)
        if p.get("held"):
            p["held"] = self._item(p["held"])
        return p

    def _appliance(self, a):
        a = dict(a)
        a["name"] = self.appliance_names.get(a.get("aid"), f"appliance:{a.get('aid')}")
        if a.get("held"):
            a["held"] = self._item(a["held"])
        if "stored" in a:
            a["stored"] = [self._item(i) for i in a["stored"]]
        if "provides" in a:
            a["provides_name"] = self.item_names.get(a["provides"], "?")
        return a

    def _item(self, i):
        i = dict(i)
        i["name"] = self.item_names.get(i.get("iid"), f"item:{i.get('iid')}")
        if "items" in i:
            i["component_names"] = [self.item_names.get(c, "?") for c in i["items"]]
        if "process" in i:
            i["process_name"] = self.process_names.get(i["process"], "?")
        return i

    def _group(self, g):
        g = dict(g)
        total = g.get("patience_total", 1.0) or 1.0
        g["patience_frac"] = g.get("patience_left", 1.0) / total
        g["meal_phase_name"] = MEAL_PHASE.get(g.get("meal_phase"), "?")
        return g

    def _customer(self, c):
        c = dict(c)
        c["state_name"] = CUSTOMER_STATE.get(c.get("state"), "?")
        return c


# ---- verification harness ----


def watch():
    """
    Play a day by hand with this running and check the output against what you
    see on screen. Every mismatch here is a bug you would otherwise train
    against for a month.
    """
    with ObservationClient() as c:
        last = None
        last_print = 0.0
        while True:
            w = c.step()   # idle action; you keep control while override is off

            summary = (
                f"day={w.day} t={w.time_of_day:.1f} "
                f"appliances={len(w.appliances)} loose={len(w.loose_items)} "
                f"groups={len(w.groups)} customers={len(w.customers)}"
            )
            me = w.me
            if me:
                held = me["held"]["name"] if me.get("held") else "-"
                summary += f" | pos=({me['x']:.1f},{me['z']:.1f}) held={held}"

            if w.override:
                lag = w.tick - w.act_tick if w.act_tick >= 0 else -1
                summary += (
                    f" | act_tick={w.act_tick} lag={lag}"
                    f" queue={w.input_queue_depth}"
                )
            if w.dropped_frames:
                summary += f" | dropped={w.dropped_frames}"

            g = w.urgent_group()
            if g:
                summary += f" | urgent={g['patience_frac']:.0%}"

            cooking = [i for i in w.loose_items if "process" in i]
            for a in w.appliances:
                if a.get("held") and "process" in a["held"]:
                    cooking.append(a["held"])
            if cooking:
                bits = [
                    f"{i['name']}:{i['process_name']}@{i['progress']:.0%}"
                    + ("!BAD" if i.get("is_bad") else "")
                    for i in cooking
                ]
                summary += " | " + " ".join(bits)

            now = time.monotonic()
            changed = summary != last
            if changed or now - last_print >= 2.0:
                print(summary + ("" if changed else " | alive"), flush=True)
                last = summary
                last_print = now


def dump_once():
    """Print one full observation, for eyeballing the schema."""
    with ObservationClient() as c:
        w = c.step()
        print(json.dumps(
            {
                "day": w.day,
                "players": w.players,
                "appliances": w.appliances[:10],
                "loose_items": w.loose_items[:10],
                "groups": w.groups,
                "customers": w.customers,
            },
            indent=2,
        ))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "dump":
        dump_once()
    else:
        watch()
