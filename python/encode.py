r"""
Fixed-size observation encoding for the steak service policy.

The bridge deliberately emits flat entity lists and no tensors, so that the
representation can change without redeploying the mod. This is that
representation.

Two rules it obeys, both from the specification:

  No future information. Nothing here reads a scheduled arrival, a hidden
  order, or anything else the bridge does not publish, because the bridge does
  not publish them (section 6.4 "Fairness").

  No affordance oracle. Section 6.1 forbids a computed `can_grab`,
  `can_place`, `best_target` or gameplay action mask. Positions, contents,
  process state, capacity and timers are facts and are encoded. Whether a grab
  would succeed is not encoded, and has to be learned.

Relative geometry is used throughout: the policy sees where things are with
respect to the chef, not their absolute world coordinates, so a layout with
the same shape in a different corner of the map encodes the same way.

`seconds_to_next` is included because it is arithmetic on two published
fields, `progress` and `rate`, and not a hidden timer. It is the single most
informative number in the steak recipe, which is exactly why it is worth
stating that it is derived rather than privileged.
"""

import math

import kitchen as K
import steak as S

VERSION = "encode_0.2"

MAX_HOBS = 4
MAX_GROUPS = 4
MAX_SINKS = 2

# Egocentric occupancy patch, in tiles either side of the chef. A motor policy
# cannot route around something it cannot see, and the first goal-conditioned
# clone failed for exactly that reason: it knew where the sink was and nothing
# about the counter between them.
#
# This is a fact, not an oracle. Specification section 6.2 lists the occupancy
# layer and traversable tiles as part of the layout observation group, and
# section 6.1 forbids computed *legality*, not the map. Every value here is
# read from published appliance positions and layers.
PATCH_RADIUS = 3

# Held-item classes. Coarse on purpose: the policy needs to know what kind of
# thing is in hand, not which of 420 items it is.
HELD_CLASSES = (
    "nothing", "raw", "rare", "medium", "well_done", "waste",
    "clean_plate", "dirty_plate", "plated", "other",
)

# Normalisers. Distances are in world units and a starting kitchen is about
# ten units across, so ten keeps the common case inside [-1, 1] without
# clipping the far corner to a constant.
DISTANCE_SCALE = 10.0
SECONDS_SCALE = 20.0
MONEY_SCALE = 100.0


def held_class(chain, item):
    if item is None:
        return "nothing"
    name = item.get("name")
    if name == S.CLEAN_PLATE:
        return "clean_plate"
    if S.is_dirty_plate(name):
        return "dirty_plate"
    if name == chain.plated:
        return "plated"
    if chain.is_raw(name):
        return "raw"
    if chain.is_waste(name) or S.is_ruined(name):
        return "waste"
    stage = chain.stage_number(name)
    if stage == 1:
        return "rare"
    if stage == 2:
        return "medium"
    if stage == 3:
        return "well_done"
    return "other"


def one_hot(value, vocabulary):
    return [1.0 if value == entry else 0.0 for entry in vocabulary]


def _relative(origin, point):
    if origin is None or point is None:
        return [0.0, 0.0, 0.0]
    dx = (point[0] - origin[0]) / DISTANCE_SCALE
    dz = (point[1] - origin[1]) / DISTANCE_SCALE
    return [dx, dz, min(1.0, math.hypot(dx, dz))]


def _clip(value, low=-1.0, high=1.0):
    return max(low, min(high, value))


class Encoder:
    """Turns a `Context` into a flat float vector of constant length."""

    def __init__(self, chain, max_hobs=MAX_HOBS, max_groups=MAX_GROUPS,
                 max_sinks=MAX_SINKS):
        self.chain = chain
        self.max_hobs = max_hobs
        self.max_groups = max_groups
        self.max_sinks = max_sinks
        self._names = None

    # -- layout -----------------------------------------------------------

    def field_names(self):
        """Human-readable name per slot, so a vector can be debugged."""
        if self._names is not None:
            return self._names
        names = [
            "phase.in_service", "phase.preparation", "phase.paused",
            "phase.captured", "phase.game_over",
            "time.day_fraction", "time.seconds_remaining",
            "time.arrivals_closed",
            "run.money", "run.lives",
        ]
        names += [f"held.{cls}" for cls in HELD_CLASSES]
        names += ["chef.facing_x", "chef.facing_z"]
        span = range(-PATCH_RADIUS, PATCH_RADIUS + 1)
        for dz in span:
            for dx in span:
                names.append(f"blocked.{dx:+d}.{dz:+d}")
        for index in range(self.max_hobs):
            names += [
                f"hob{index}.present", f"hob{index}.occupied",
                f"hob{index}.raw", f"hob{index}.servable",
                f"hob{index}.waste", f"hob{index}.is_bad",
                f"hob{index}.stage", f"hob{index}.progress",
                f"hob{index}.seconds_to_next",
                f"hob{index}.dx", f"hob{index}.dz", f"hob{index}.range",
            ]
        for index in range(self.max_sinks):
            names += [
                f"sink{index}.present", f"sink{index}.dirty",
                f"sink{index}.clean", f"sink{index}.progress",
                f"sink{index}.dx", f"sink{index}.dz", f"sink{index}.range",
            ]
        names += [
            "stock.plate_provider_available", "stock.plate_provider_infinite",
            "stock.clean_plates", "stock.dirty_plates",
            "stock.plated_ready", "stock.free_surfaces",
            "stock.raw_provider_dx", "stock.raw_provider_dz",
            "stock.raw_provider_range",
            "stock.plate_provider_dx", "stock.plate_provider_dz",
            "stock.plate_provider_range",
            "stock.bin_dx", "stock.bin_dz", "stock.bin_range",
        ]
        for index in range(self.max_groups):
            names += [
                f"group{index}.present", f"group{index}.seated",
                f"group{index}.thinking", f"group{index}.ordering",
                f"group{index}.waiting", f"group{index}.eating",
                f"group{index}.patience", f"group{index}.unsatisfied",
                f"group{index}.size",
                f"group{index}.dx", f"group{index}.dz", f"group{index}.range",
            ]
        self._names = names
        return names

    @property
    def size(self):
        return len(self.field_names())

    # -- encoding ---------------------------------------------------------

    def encode(self, ctx):
        world = ctx.world
        chain = self.chain
        position = ctx.position
        vector = []

        vector += [
            1.0 if ctx.in_service else 0.0,
            1.0 if world.start_day_warnings is not None else 0.0,
            1.0 if world.paused else 0.0,
            1.0 if world.input_captured else 0.0,
            1.0 if world.game_over else 0.0,
        ]

        day_length = world.day_length or 1.0
        vector += [
            _clip(world.seconds_elapsed / day_length, 0.0, 2.0),
            _clip(world.seconds_remaining / SECONDS_SCALE, 0.0, 10.0),
            1.0 if world.seconds_elapsed >= day_length else 0.0,
            _clip((world.money or 0) / MONEY_SCALE, -10.0, 10.0),
            float(world.lives if world.lives is not None else 0),
        ]

        vector += one_hot(held_class(chain, ctx.held), HELD_CLASSES)

        rotation = (ctx.me or {}).get("rot", 0.0)
        facing = K.facing_vector(rotation)
        vector += [facing[0], facing[1]]

        vector += self._occupancy(ctx, position)
        vector += self._hobs(ctx, position)
        vector += self._sinks(ctx, position)
        vector += self._stock(ctx, position)
        vector += self._groups(ctx, position)
        return vector

    def _occupancy(self, ctx, position):
        """Which tiles around the chef are solid, in world axes.

        Out-of-bounds counts as blocked: the chef cannot walk off the map
        either, and a policy that treats the edge as open would push into it
        the same way it pushes into a counter.
        """
        if position is None:
            return [1.0] * ((2 * PATCH_RADIUS + 1) ** 2)
        origin = K.tile_of(*position)
        kitchen = ctx.kitchen
        block = []
        for dz in range(-PATCH_RADIUS, PATCH_RADIUS + 1):
            for dx in range(-PATCH_RADIUS, PATCH_RADIUS + 1):
                block.append(
                    0.0 if kitchen.free((origin[0] + dx, origin[1] + dz))
                    else 1.0)
        return block

    def _hobs(self, ctx, position):
        chain = self.chain
        hobs = sorted(
            ctx.kitchen.role("cook"),
            key=lambda a: K.distance((a["x"], a["z"]), position or (0, 0)))
        block = []
        for index in range(self.max_hobs):
            if index >= len(hobs):
                block += [0.0] * 12
                continue
            hob = hobs[index]
            item = hob.get("held")
            name = item.get("name") if item else None
            stage = chain.stage_number(name) if name else None
            remaining = chain.seconds_to_next(item) if item else None
            block += [
                1.0,
                1.0 if item is not None else 0.0,
                1.0 if name and chain.is_raw(name) else 0.0,
                1.0 if name and chain.is_servable(name) else 0.0,
                1.0 if name and chain.is_waste(name) else 0.0,
                1.0 if item and item.get("is_bad") else 0.0,
                (stage or 0) / max(1, len(chain.sequence) - 1),
                float(item.get("progress") or 0.0) if item else 0.0,
                _clip((remaining or 0.0) / SECONDS_SCALE, 0.0, 1.0),
            ]
            block += _relative(position, (hob["x"], hob["z"]))
        return block

    def _sinks(self, ctx, position):
        sinks = sorted(
            ctx.kitchen.role("wash"),
            key=lambda a: K.distance((a["x"], a["z"]), position or (0, 0)))
        block = []
        for index in range(self.max_sinks):
            if index >= len(sinks):
                block += [0.0] * 7
                continue
            sink = sinks[index]
            item = sink.get("held")
            name = item.get("name") if item else None
            block += [
                1.0,
                1.0 if name and S.is_dirty_plate(name) else 0.0,
                1.0 if name == S.CLEAN_PLATE else 0.0,
                float(item.get("progress") or 0.0) if item else 0.0,
            ]
            block += _relative(position, (sink["x"], sink["z"]))
        return block

    def _stock(self, ctx, position):
        inventory = ctx.inventory
        providers = inventory.plate_providers
        available = 0
        infinite = 0.0
        for provider in providers:
            maximum = provider.get("maximum") or 0
            if maximum == 0:
                infinite = 1.0
            else:
                available += provider.get("available") or 0
        free_surfaces = sum(
            1 for a in ctx.kitchen.role("surface") if a.get("held") is None)

        plate_provider = providers[0] if providers else None
        raw_provider = (
            inventory.raw_providers[0] if inventory.raw_providers else None)
        bins = [
            a for a in ctx.kitchen.role("bin")
            if not a.get("name", "").startswith("Wheelie")]

        block = [
            available / 8.0,
            infinite,
            len(inventory.clean_plates) / 8.0,
            len(inventory.dirty_plates) / 8.0,
            len(inventory.plated) / 8.0,
            free_surfaces / 8.0,
        ]
        block += _relative(
            position,
            (raw_provider["x"], raw_provider["z"]) if raw_provider else None)
        block += _relative(
            position,
            (plate_provider["x"], plate_provider["z"])
            if plate_provider else None)
        block += _relative(
            position, (bins[0]["x"], bins[0]["z"]) if bins else None)
        return block

    def _groups(self, ctx, position):
        groups = sorted(
            ctx.world.groups,
            key=lambda g: (g.get("patience_frac", 1.0),
                           K.distance((g["x"], g["z"]), position or (0, 0))))
        block = []
        for index in range(self.max_groups):
            if index >= len(groups):
                block += [0.0] * 12
                continue
            group = groups[index]
            reason = group.get("patience_reason")
            unsatisfied = sum(
                1 for order in group.get("orders", ())
                if not order.get("satisfied"))
            seated = ctx.kitchen.table_for_group(group) is not None
            block += [
                1.0,
                1.0 if seated else 0.0,
                1.0 if reason == 0 else 0.0,
                1.0 if reason == 3 else 0.0,
                1.0 if reason == 4 else 0.0,
                1.0 if reason == 1 else 0.0,
                _clip(group.get("patience_frac", 1.0), 0.0, 1.0),
                min(1.0, unsatisfied / 4.0),
                min(1.0, (group.get("size") or 1) / 4.0),
            ]
            block += _relative(position, (group["x"], group["z"]))
        return block

    # -- diagnostics ------------------------------------------------------

    def explain(self, ctx, threshold=1e-9):
        vector = self.encode(ctx)
        names = self.field_names()
        return {
            name: round(value, 4)
            for name, value in zip(names, vector)
            if abs(value) > threshold}


# --------------------------------------------------------------------------
# goals
# --------------------------------------------------------------------------

# The option vocabulary a motor policy has to be able to execute. Order is
# fixed because it becomes a one-hot slot; appending is safe, reordering is
# not.
GOAL_KINDS = (
    "none", "navigate", "acquire", "place", "bin", "operate", "serve",
    "watch_cook", "start_day", "dismiss_popup", "idle", "other",
)


class GoalEncoder:
    """Encodes what the chef is currently trying to do.

    Behaviour cloning from a hierarchical expert fails without this, and the
    failure is not subtle: a policy cloned from the reference controller on
    state alone reached 97% per-frame accuracy and served zero groups, because
    two identical kitchens can call for opposite movements depending on which
    appliance the planner picked. The target is not in the observation, so the
    policy is being asked to guess an intention it cannot see.

    Specification section 8.1 puts a goal-conditioned motor controller under
    the task planner for exactly this reason, and section 10.3 step 2 makes
    goal conditioning the second thing to do after cloning. The goal is the
    interface between the two layers.

    Nothing here is privileged information. The option kind is the agent's own
    decision, and the target's position is already published; this is the
    agent telling itself what it chose, not the bridge telling it what to do.
    """

    def __init__(self):
        self._names = None

    def field_names(self):
        if self._names is not None:
            return self._names
        names = [f"goal.{kind}" for kind in GOAL_KINDS]
        names += [
            "goal.has_target", "goal.dx", "goal.dz", "goal.range",
            "goal.in_reach", "goal.aim_x", "goal.aim_z",
            "goal.stand_dx", "goal.stand_dz", "goal.at_stance",
        ]
        self._names = names
        return names

    @property
    def size(self):
        return len(self.field_names())

    def encode(self, option, ctx):
        kind = self.kind_of(option)
        vector = one_hot(kind, GOAL_KINDS)

        target = self._target(option, ctx)
        position = ctx.position
        if target is None or position is None:
            return vector + [0.0] * 10

        goal = (target["x"], target["z"])
        span = math.hypot(goal[0] - position[0], goal[1] - position[1])
        aim = K.normalise(goal[0] - position[0], goal[1] - position[1])
        stand = getattr(option, "pose", None)
        if stand is not None:
            stand_dx = (stand.x - position[0]) / DISTANCE_SCALE
            stand_dz = (stand.z - position[1]) / DISTANCE_SCALE
            at_stance = 1.0 if math.hypot(
                stand.x - position[0], stand.z - position[1]) <= 0.2 else 0.0
        else:
            stand_dx = stand_dz = at_stance = 0.0

        return vector + [
            1.0,
            _clip((goal[0] - position[0]) / DISTANCE_SCALE),
            _clip((goal[1] - position[1]) / DISTANCE_SCALE),
            _clip(span / DISTANCE_SCALE, 0.0, 1.0),
            1.0 if span <= K.MAX_REACH else 0.0,
            aim[0], aim[1],
            _clip(stand_dx), _clip(stand_dz), at_stance,
        ]

    @staticmethod
    def kind_of(option):
        if option is None:
            return "none"
        name = getattr(option, "name", "")
        if name in GOAL_KINDS:
            return name
        # Composites are labelled by the child that is actually running, so a
        # wash and a fetch do not collapse into one indistinguishable goal.
        current = getattr(option, "current", None)
        if current is not None:
            return GoalEncoder.kind_of(current)
        return "other"

    @staticmethod
    def _target(option, ctx):
        if option is None:
            return None
        current = getattr(option, "current", None)
        if current is not None:
            return GoalEncoder._target(current, ctx)
        slot = getattr(option, "slot", None)
        if slot is not None:
            return ctx.appliance_at(slot)
        table_slot = getattr(option, "table_slot", None)
        if table_slot is not None:
            return ctx.appliance_at(table_slot)
        return None
