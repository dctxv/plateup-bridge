r"""
The steak production chain, as a graph over observed item states.

Project 1 is fixed to steak by project-owner direction; see
docs/steak-decision.md. That decision is a scope choice, not the measured
outcome of docs/recipe-benchmark-protocol.md, which remains unrun.

Everything in here is named, never keyed on a raw game-data id. Item,
appliance and process ids are only stable within a pinned build and the
observation schema resolves them through the `dict` frame, so a table of
integers would be a build-specific landmine. Names are resolved once per
connection and the resolution is checked, so a renamed or missing item fails
loudly at startup instead of silently mis-cooking.

What is measured versus what is assumed:

  measured, from runs/golden and runs/demos
    - the order a steak restaurant serves is `Steak - Plated`, reward 5,
      leaving `Plate - Dirty` behind, and no doneness is requested;
    - `CItemUndergoingProcess.CurrentChange` is progress per second, so
      `(1 - progress) / rate` is the exact seconds left in the current stage,
      needing no recipe timings at all;
    - a starting hob and a starting sink both run at 0.375 progress per
      second, and `is_bad` turns true on the stage whose *next* transition
      ruins the item, which for burgers is the cooked patty and for steak is
      Well-done;
    - plating freezes the item: a plated dish carries no process.

  assumed, from the knowledge base and therefore a hypothesis
    - the per-stage base durations below. They are used only as a prior for
      the surrogate. The live controller reads `rate` and never needs them.

The chain, for the plain cut:

    Meat --Cook--> Steak - Rare --Cook--> Steak - Medium
         --Cook--> Steak - Well-done (is_bad) --Cook--> Steak - Burned

Rare, Medium and Well-done all plate to the same `Steak - Plated`, so the
doneness decision is a pure risk trade: leave it longer and it burns, take it
early and nothing is lost. The controller therefore lifts at the first
servable stage unless a later stage is already in hand.
"""

import re

RECIPE = "steak"

# Cuts. Each is the same graph with different item names and timings, so a
# card that swaps the cut does not need new code. Plain steak is Project 1.
CUTS = {
    "plain": {
        "raw": "Meat",
        "stages": ("Steak - Rare", "Steak - Medium", "Steak - Well-done"),
        "ruined": "Steak - Burned",
        "plated": "Steak - Plated",
        # Knowledge-base base seconds for raw->rare, rare->medium,
        # medium->well-done, well-done->burned. Hypotheses; see module docs.
        "base_seconds": (5.0, 2.0, 2.0, 10.0),
        "leftover": None,
    },
    "boned": {
        "raw": "Meat - Boned",
        "stages": ("Boned Steak - Rare", "Boned Steak - Medium",
                   "Boned Steak - Well-done"),
        "ruined": "Boned Steak - Burned",
        "plated": "Boned Steak - Plated",
        "base_seconds": (5.0, 3.0, 3.0, 4.0),
        "leftover": "Boned Steak - Bone",
    },
    "thick": {
        "raw": "Meat - Thick",
        "stages": ("Thick Steak - Rare", "Thick Steak - Medium",
                   "Thick Steak - Well-done"),
        "ruined": "Thick Steak - Burned",
        "plated": "Thick Steak - Plated",
        "base_seconds": (10.0, 8.0, 8.0, 8.0),
        "leftover": None,
    },
    "thin": {
        "raw": "Meat - Thin",
        "stages": ("Thin Steak - Rare", "Thin Steak - Medium",
                   "Thin Steak - Well-done"),
        "ruined": "Thin Steak - Burned",
        "plated": "Thin Steak - Plated",
        "base_seconds": (4.0, 1.0, 1.0, 1.0),
        "leftover": None,
    },
}

PLAIN = CUTS["plain"]

CLEAN_PLATE = "Plate"
DIRTY_PLATES = (
    "Plate - Dirty",
    "Plate - Dirty with food",
    "Plate - Dirty with Bone",
    "Plate - Dirty Soaked",
)
# A dirty plate still carrying leftovers is refused by the dish rack and by
# some sinks until the leftovers are binned, so it is tracked separately.
PLATES_WITH_LEFTOVERS = ("Plate - Dirty with food", "Plate - Dirty with Bone")

WATER = "Water"

COOK_PROCESS = "Cook"
CLEAN_PROCESS = "Clean"
SOAK_PROCESS = "Clean - Soak"

# Any item whose name says burned is waste, in either arm of the benchmark.
RUINED_PATTERN = re.compile(r"burn", re.IGNORECASE)

# The starting hob and the starting sink both run at this rate. Recorded in
# runs/golden: 0.019 -> 0.994 progress across 2.6 s on the hob, and
# 0.006 -> 0.979 across 2.594 s in the sink. Used only as a fallback when a
# process has not yet been observed running.
STARTING_APPLIANCE_RATE = 0.375

# A starting appliance is slower than its purchasable counterpart. The wiki's
# 2 s base for both a raw patty and a plate wash against a measured 2.667 s
# gives 0.75, which is the multiplier the surrogate applies to base_seconds.
STARTING_APPLIANCE_SPEED = 0.75


def is_ruined(name):
    return bool(name) and bool(RUINED_PATTERN.search(name))


def is_dirty_plate(name):
    return name in DIRTY_PLATES


def has_leftovers(name):
    return name in PLATES_WITH_LEFTOVERS


class Chain:
    """One cut's chain, plus the queries a policy actually asks of it."""

    def __init__(self, cut="plain"):
        if cut not in CUTS:
            raise KeyError(f"unknown steak cut {cut!r}")
        self.cut = cut
        spec = CUTS[cut]
        self.raw = spec["raw"]
        self.stages = tuple(spec["stages"])
        self.ruined = spec["ruined"]
        self.plated = spec["plated"]
        self.leftover = spec["leftover"]
        self.base_seconds = tuple(spec["base_seconds"])
        # Cooking order, from raw to waste.
        self.sequence = (self.raw,) + self.stages + (self.ruined,)
        self.index = {name: i for i, name in enumerate(self.sequence)}

    # -- membership -------------------------------------------------------

    def names(self):
        return set(self.sequence) | {self.plated} | (
            {self.leftover} if self.leftover else set())

    def is_servable(self, name):
        """Can this item state be plated and sold?"""
        return name in self.stages

    def is_raw(self, name):
        return name == self.raw

    def is_waste(self, name):
        return name == self.ruined

    def stage_number(self, name):
        """0 for raw, 1 for rare, up to len(sequence) - 1 for ruined."""
        return self.index.get(name)

    def next_state(self, name):
        position = self.index.get(name)
        if position is None or position + 1 >= len(self.sequence):
            return None
        return self.sequence[position + 1]

    # -- timing -----------------------------------------------------------

    def seconds_to_next(self, item):
        """Seconds until this item transitions, from published fields only.

        `progress` is 0-1 within the current stage and `rate` is progress per
        second, both straight out of `CItemUndergoingProcess`. No recipe table
        is consulted, so this stays correct if a card, an appliance upgrade or
        a patch changes the speed.
        """
        rate = item.get("rate")
        progress = item.get("progress")
        if not rate or progress is None or rate <= 0:
            return None
        return max(0.0, (1.0 - progress) / rate)

    def timescale(self, step, rate):
        """Real seconds per tabulated second, from one observed stage rate.

        A stage runs from progress 0 to 1 at `rate` per second, so it lasts
        `1 / rate` real seconds. Dividing by the tabulated duration for that
        stage gives the appliance's speed relative to the knowledge base. On a
        starting hob and a starting sink this comes out at 1.333, the
        reciprocal of the 0.75 starting-appliance multiplier, which is why
        those two independent measurements agree.
        """
        if not rate or rate <= 0 or step >= len(self.base_seconds):
            return None
        base = self.base_seconds[step]
        if base <= 0:
            return None
        return (1.0 / rate) / base

    def stage_seconds(self, step, timescale=None):
        """Prior duration of one stage, in real seconds."""
        if step >= len(self.base_seconds):
            return None
        if timescale is None:
            timescale = 1.0 / STARTING_APPLIANCE_SPEED
        return self.base_seconds[step] * timescale

    def seconds_to_ruin(self, item):
        """Seconds until this item becomes waste if nobody touches it.

        Returns `(seconds, estimated)`. The current stage is measured, because
        progress and rate are published. Every later stage is a knowledge-base
        prior rescaled by the measured stage, so `estimated` is true whenever
        more than the current stage had to be crossed.
        """
        name = item.get("name")
        position = self.index.get(name)
        last_safe = len(self.sequence) - 2
        if position is None or position > last_safe:
            return None, False

        remaining = self.seconds_to_next(item)
        if remaining is None:
            return None, False

        scale = self.timescale(position, item.get("rate"))
        if scale is None:
            scale = 1.0 / STARTING_APPLIANCE_SPEED

        total = remaining
        estimated = False
        for step in range(position + 1, last_safe + 1):
            total += self.base_seconds[step] * scale
            estimated = True
        return total, estimated

    def __repr__(self):
        return f"Chain({self.cut}: {' -> '.join(self.sequence)})"


# --------------------------------------------------------------------------
# menu inference
# --------------------------------------------------------------------------


def infer_cut(world):
    """Which cut this restaurant serves, from what is visible on screen.

    Two independent signals, both legitimate: the ingredient the provider
    hands out, and what customers have already ordered. Future orders are not
    consulted and cannot be: the order buffer only populates at WaitForFood.
    """
    provided = {
        appliance.get("provides_name") for appliance in world.appliances}
    for cut, spec in CUTS.items():
        if spec["raw"] in provided:
            return cut

    ordered = {
        order.get("name")
        for group in world.groups for order in group.get("orders", ())}
    for cut, spec in CUTS.items():
        if spec["plated"] in ordered:
            return cut
    return None


def is_steak_restaurant(world):
    return infer_cut(world) is not None


# --------------------------------------------------------------------------
# name resolution
# --------------------------------------------------------------------------


class Registry:
    """Checked view of the connection's name dictionary.

    A missing name means the pinned build changed under us. Failing here beats
    discovering it when the chef walks a plate into a sink that no longer
    accepts it.
    """

    def __init__(self, item_names, appliance_names, process_names, cut="plain"):
        self.items = dict(item_names)
        self.appliances = dict(appliance_names)
        self.processes = dict(process_names)
        self.chain = Chain(cut)

        self.item_ids = {name: iid for iid, name in self.items.items()}
        self.process_ids = {
            name: pid for pid, name in self.processes.items()}

        self.missing_items = sorted(
            name for name in self.chain.names() | {CLEAN_PLATE, WATER}
            | set(DIRTY_PLATES)
            if name not in self.item_ids)
        self.missing_processes = sorted(
            name for name in (COOK_PROCESS, CLEAN_PROCESS)
            if name not in self.process_ids)

    @property
    def complete(self):
        return not self.missing_items and not self.missing_processes

    def require(self):
        if self.complete:
            return self
        raise KeyError(
            "pinned-build name mismatch: missing items "
            f"{self.missing_items}, missing processes {self.missing_processes}")

    def item_id(self, name):
        return self.item_ids.get(name)

    def process_id(self, name):
        return self.process_ids.get(name)

    def describe(self):
        return {
            "cut": self.chain.cut,
            "items": len(self.items),
            "appliances": len(self.appliances),
            "processes": len(self.processes),
            "missing_items": self.missing_items,
            "missing_processes": self.missing_processes,
        }


def registry_from(client, cut=None):
    """Build a registry from an ObservationClient that has seen a dict."""
    resolved = cut or infer_cut(client.world) or "plain"
    return Registry(
        client.item_names, client.appliance_names, client.process_names,
        resolved)


# --------------------------------------------------------------------------
# kitchen state, in recipe terms
# --------------------------------------------------------------------------


class Inventory:
    """Everything the steak loop cares about, extracted from one frame."""

    def __init__(self, world, kitchen, chain):
        self.world = world
        self.kitchen = kitchen
        self.chain = chain

        self.held = None
        me = world.me
        if me and me.get("held"):
            self.held = me["held"]

        self.cooking = []          # items mid-chain, on any appliance
        self.servable = []         # cooked, unplated, not yet ruined
        self.plated = []           # finished dishes waiting to be carried
        self.clean_plates = []     # bare plates sitting on a surface
        self.dirty_plates = []     # dirty plates anywhere but the provider
        self.waste = []            # ruined items needing a bin
        self.raw = []              # raw cuts already fetched

        for appliance in kitchen.appliances:
            item = appliance.get("held")
            if item is None:
                continue
            self._classify(item, appliance)

        for item in world.loose_items:
            self._classify(item, None)

        self.plate_providers = [
            a for a in kitchen.appliances
            if a.get("provides_name") == CLEAN_PLATE]
        self.raw_providers = [
            a for a in kitchen.appliances
            if a.get("provides_name") == chain.raw]

    def _classify(self, item, appliance):
        name = item.get("name")
        record = {"item": item, "on": appliance}
        if name == self.chain.plated:
            self.plated.append(record)
        elif name == self.chain.ruined or is_ruined(name):
            self.waste.append(record)
        elif self.chain.is_servable(name):
            self.servable.append(record)
            if item.get("process") is not None:
                self.cooking.append(record)
        elif self.chain.is_raw(name):
            self.raw.append(record)
            if item.get("process") is not None:
                self.cooking.append(record)
        elif name == CLEAN_PLATE:
            self.clean_plates.append(record)
        elif is_dirty_plate(name):
            self.dirty_plates.append(record)

    # -- derived counts ---------------------------------------------------

    def plates_available(self):
        """Clean plates the chef can obtain without washing anything."""
        stocked = 0
        for provider in self.plate_providers:
            maximum = provider.get("maximum") or 0
            available = provider.get("available") or 0
            # maximum 0 means an infinite provider; facts.py settles this.
            stocked += 10 ** 6 if maximum == 0 else available
        return stocked + len(self.clean_plates)

    def at_risk(self):
        """Cooking items whose next transition ruins them, soonest first."""
        risky = []
        for record in self.cooking:
            item = record["item"]
            if not item.get("is_bad"):
                continue
            remaining = self.chain.seconds_to_next(item)
            risky.append((remaining if remaining is not None else 0.0, record))
        risky.sort(key=lambda entry: entry[0])
        return risky

    def outstanding(self):
        """Unsatisfied orders across all groups, most urgent first."""
        return self.world.outstanding_orders()

    def describe(self):
        return {
            "held": self.held.get("name") if self.held else None,
            "cooking": [r["item"].get("name") for r in self.cooking],
            "servable": [r["item"].get("name") for r in self.servable],
            "plated": len(self.plated),
            "clean_plates": len(self.clean_plates),
            "dirty_plates": len(self.dirty_plates),
            "waste": len(self.waste),
            "plates_available": min(self.plates_available(), 999),
            "outstanding": len(self.outstanding()),
        }
