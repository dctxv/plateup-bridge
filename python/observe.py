"""
Observation layer for the PlateUp bridge. Schema obs_0.1.

The mod emits two message kinds:
    dict  -- id -> name maps, once per connection
    obs   -- game state, ~12 Hz

This resolves ids to names and gives you a World object convenient to poke at from
a REPL. It deliberately does NOT build tensors -- do that in a separate encoder so
the representation can change without redeploying the mod.
"""

import json
import time

from bridge import PlateUpBridge


# --- enums, confirmed from decompiled KitchenData ---

PATIENCE_REASON = {
    0: "thinking",
    1: "eating",
    2: "seating",
    3: "service",            # waiting to order
    4: "wait_for_food",
    5: "get_food_delivered", # remaining items after the first
    6: "queue",
    7: "queue_darkness",
    8: "queue_rain",
    9: "queue_snow",
}

MENU_PHASE = {
    0: "starter",
    1: "main",
    2: "dessert",
    3: "side",
    4: "complete",
}

CUSTOMER_STATE = {0: "normal", 1: "queue", 2: "at_table"}

OCCUPANCY_LAYER = {0: "default", 1: "wall", 2: "floor", 3: "ceiling"}

# ItemCategory is a bit field.
ITEM_CATEGORY = {
    0: "generic", 1: "crates", 2: "documents", 4: "menu_choice",
    8: "layout_choice", 16: "provider_only", 32: "plant",
    64: "contract", 128: "non_loadout_crate",
}


class World:
    """Latest observation, with names resolved."""

    def __init__(self):
        self.raw = {}
        self.tick = 0
        self.ack_command = 0
        self.cmds_applied = 0
        self.cmds_dropped = 0
        self.day = 0
        self.seconds_elapsed = 0.0
        self.day_length = 0.0
        self.time_of_day = 0.0
        self.money = 0
        self.lives = None
        self.game_over = False
        self.loss_reason = None
        self.start_day_warnings = None
        self.in_restaurant = False
        self.paused = False
        self.override = False
        self.input_captured = False
        self.players = []
        self.appliances = []
        self.loose_items = []
        self.groups = []
        self.customers = []

    # --- convenience ---

    @property
    def me(self):
        return self.players[0] if self.players else None

    @property
    def tables(self):
        return [a for a in self.appliances if a.get("is_table")]

    @property
    def seconds_remaining(self):
        """Until the time bar fills. Customers can still be seated after this."""
        return max(0.0, self.day_length - self.seconds_elapsed)

    @property
    def accepting_customers(self):
        return self.seconds_elapsed < self.day_length

    def by_name(self, needle, collection=None):
        n = needle.lower()
        src = collection if collection is not None else self.appliances
        return [a for a in src if n in a.get("name", "").lower()]

    def nearest(self, entities, x=None, z=None):
        if x is None or z is None:
            me = self.me
            if me is None:
                return None
            x, z = me["x"], me["z"]
        if not entities:
            return None
        return min(entities, key=lambda e: (e["x"] - x) ** 2 + (e["z"] - z) ** 2)

    def outstanding_orders(self):
        """
        Every unsatisfied order across all groups, most urgent first.
        This is the service policy's task list.
        """
        out = []
        for g in self.groups:
            for o in g.get("orders", []):
                if o.get("satisfied"):
                    continue
                out.append({
                    **o,
                    "group": g["e"],
                    "table": g.get("table"),
                    "patience_frac": g.get("patience_frac", 1.0),
                    "patience_left": g.get("patience_left"),
                })
        out.sort(key=lambda o: o["patience_frac"])
        return out

    def cooking(self):
        """Every item currently undergoing a process, wherever it sits."""
        items = [i for i in self.loose_items if "process" in i]
        for a in self.appliances:
            h = a.get("held")
            if h and "process" in h:
                items.append({**h, "on": a.get("name")})
        for p in self.players:
            h = p.get("held")
            if h and "process" in h:
                items.append({**h, "on": "held"})
        return items

    def at_risk(self):
        """Items whose current process leads somewhere worse."""
        return [i for i in self.cooking() if i.get("is_bad")]


class ObservationClient:
    def __init__(self, bridge=None):
        self.b = bridge or PlateUpBridge()
        self.appliance_names = {}
        self.item_names = {}
        self.process_names = {}
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

    # --- io ---

    def step(self, **action):
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

    # --- parsing ---

    def _load_dict(self, msg):
        self.appliance_names = {int(k): v for k, v in msg.get("appliances", {}).items()}
        self.item_names = {int(k): v for k, v in msg.get("items", {}).items()}
        self.process_names = {int(k): v for k, v in msg.get("processes", {}).items()}
        print(
            f"dict: {len(self.appliance_names)} appliances, "
            f"{len(self.item_names)} items, {len(self.process_names)} processes"
        )

    def _load_obs(self, m):
        w = self.world
        w.raw = m
        w.tick = m.get("tick", 0)
        w.ack_command = m.get("ack_command", 0)
        w.cmds_applied = m.get("cmds_applied", 0)
        w.cmds_dropped = m.get("cmds_dropped", 0)
        w.day = m.get("day", 0)
        w.time_of_day = m.get("time_of_day", 0.0)
        w.seconds_elapsed = m.get("seconds_elapsed", 0.0)
        w.day_length = m.get("day_length", 0.0)
        w.money = m.get("money", 0)
        w.lives = m.get("lives")
        w.game_over = m.get("game_over", False)
        w.loss_reason = m.get("loss_reason")
        w.start_day_warnings = m.get("start_day_warnings")
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
        a["layer_name"] = OCCUPANCY_LAYER.get(a.get("layer"), "?")
        if a.get("held"):
            a["held"] = self._item(a["held"])
        if "provides" in a:
            a["provides_name"] = self.item_names.get(a["provides"], "?")
        if "accepts_only" in a:
            a["accepts_only_name"] = self.item_names.get(a["accepts_only"], "?")
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
        g["patience_reason_name"] = PATIENCE_REASON.get(g.get("patience_reason"), "?")
        g["meal_phase_name"] = MENU_PHASE.get(g.get("meal_phase"), "?")

        orders = []
        for o in g.get("orders", []):
            o = dict(o)
            o["name"] = self.item_names.get(o.get("iid"), f"item:{o.get('iid')}")
            if "dirt" in o:
                o["dirt_name"] = self.item_names.get(o["dirt"], "?")
            if "extra" in o:
                o["extra_name"] = self.item_names.get(o["extra"], "?")
            orders.append(o)
        g["orders"] = orders
        return g

    def _customer(self, c):
        c = dict(c)
        c["state_name"] = CUSTOMER_STATE.get(c.get("state"), "?")
        return c


# ---- verification harness ----


def watch():
    """
    Play a day by hand with this running and check the output against what you see
    on screen. Every mismatch here is a bug you would otherwise train against.
    """
    with ObservationClient() as c:
        last = None
        while True:
            w = c.step()

            bits = [f"d{w.day}", f"{w.seconds_elapsed:.0f}/{w.day_length:.0f}s",
                    f"${w.money}"]
            if w.lives is not None:
                bits.append(f"lives={w.lives}")
            if not w.accepting_customers:
                bits.append("CLOSED")
            if w.game_over:
                bits.append(f"GAME OVER({w.loss_reason})")

            me = w.me
            if me:
                held = me["held"]["name"] if me.get("held") else "-"
                bits.append(f"held={held}")

            pending = w.outstanding_orders()
            if pending:
                shown = ", ".join(
                    f"{o['name']}@t{o['table']}({o['patience_frac']:.0%})"
                    for o in pending[:3]
                )
                bits.append(f"want[{len(pending)}]: {shown}")

            risk = w.at_risk()
            if risk:
                bits.append("BAD:" + ",".join(
                    f"{i['name']}@{i['progress']:.0%}" for i in risk))

            line = " | ".join(bits)
            if line != last:
                print(line)
                last = line


def dump_once():
    """Print one full observation, for eyeballing the schema."""
    with ObservationClient() as c:
        w = c.step()
        print(json.dumps(w.raw, indent=2)[:6000])


def orders_only():
    """Focused view for verifying the order model."""
    with ObservationClient() as c:
        last = None
        while True:
            w = c.step()
            lines = []
            for g in w.groups:
                head = (f"group {g['e']} size={g.get('size')} "
                        f"table={g.get('table')} "
                        f"{g['meal_phase_name']}/{g['patience_reason_name']} "
                        f"{g['patience_frac']:.0%}")
                lines.append(head)
                for o in g.get("orders", []):
                    mark = "x" if o.get("satisfied") else " "
                    extra = ""
                    if "extra" in o:
                        extra = f" +{o['extra_name']}" + (
                            " (done)" if o.get("extra_done") else " (WANTED)")
                    lines.append(
                        f"  [{mark}] m{o['member']} {o['name']} "
                        f"${o['reward']}{extra}")
            out = "\n".join(lines)
            if out != last and out:
                print(out + "\n")
                last = out


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "watch"
    if mode == "dump":
        dump_once()
    elif mode == "orders":
        orders_only()
    else:
        watch()
