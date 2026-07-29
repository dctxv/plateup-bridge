r"""
Options: closed-loop skills over the primitive bridge action space.

An option is the unit the task planner chooses and the semi-MDP surrogate
prices: it runs for a variable number of ticks and ends in one of a small set
of outcomes. Specification section 8.2 fixes the vocabulary; this module
implements it.

    NavigateTo      stand somewhere useful
    AcquireItem     grab at a provider or holder to end up carrying something
    PlaceItem       grab at a holder to put down, store, combine or trash
    OperateProcess  hold interact until a process finishes
    ServeOrder      deliver a plated dish to a seated group
    ClearTable      take the dirty plate a group left behind
    WashPlate       place, wash and retrieve
    RescueItem      lift something off the heat before it is ruined
    BinWaste        dispose of a ruined item
    StartDay        consent to the day starting

The motor layer here is a proportional controller with a stuck detector. It is
**not** the learned policy the experiment contract requires: specification
section 2.3 explicitly disallows presenting deterministic pathfinding as
learned motor control. Its purposes are to collect option-outcome statistics
for the capability registry, to give the surrogate something calibrated to
copy, and to act as the scripted baseline every learned policy is compared
against. Anything scored as autonomous play must replace `_drive` and the
press logic with a policy.

Two facts shape the whole design:

  Movement is also the aim vector. `AttemptInteraction` projects the
  interaction point along `Movement`, so the direction held on the frame a
  button is pressed decides what is grabbed. Aiming is therefore not a
  separate channel and every press has to be preceded by holding the right
  direction.

  Grab fires on the `Pressed` edge only, while Interact acts on `Pressed` or
  `Held`. A grab therefore has to be released between attempts, and a wash has
  to be held down across ticks.
"""

import math

import kitchen as K
import steak as S

RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
TIMEOUT = "timeout"
INVALID = "invalidated"
PREEMPTED = "preempted"

TERMINAL = (SUCCESS, FAILED, TIMEOUT, INVALID, PREEMPTED)

# Motor tuning. These are control parameters of the reference controller, not
# game constants, and every one of them is a candidate for replacement by a
# learned policy.
ARRIVE_TOLERANCE = 0.15
WAYPOINT_TOLERANCE = 0.35
APPROACH_SPEED_RADIUS = 0.6
PRESS_TICKS = 1
RELEASE_TICKS = 2
SETTLE_TICKS = 3
MAX_PRESS_ATTEMPTS = 4
STUCK_WINDOW = 12
STUCK_DISTANCE = 0.08
MAX_REPLANS = 3
MAX_AIM_RECOVERIES = 12

# Keep the press inside the reach limit with room for control error. Every
# planned pose is at most kitchen.PLAN_REACH (1.10) from its target, so an
# arrival error up to ARRIVE_TOLERANCE still lands inside this gate.
PRESS_REACH = K.MAX_REACH - 0.12

NEUTRAL = {
    "move": (0.0, 0.0),
    "grab": False,
    "interact": False,
    "stop": False,
    "ready": False,
}


def neutral():
    return dict(NEUTRAL)


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------


class Context:
    """One observation, plus everything derived from it.

    Rebuilt per frame. Appliance entity ids are recycled when the day starts,
    so nothing derived from a frame may outlive it; only the learned blocked
    tiles are carried forward, and those are keyed on the tile grid.
    """

    def __init__(self, world, chain, blocked_hints=()):
        self.world = world
        self.chain = chain
        self.kitchen = K.Kitchen(world, blocked_hints=blocked_hints)
        self.inventory = S.Inventory(world, self.kitchen, chain)
        self.tick = world.tick
        self.clock = world.game_total_time
        self.me = world.me

    @property
    def position(self):
        if self.me is None:
            return None
        return self.me["x"], self.me["z"]

    @property
    def held(self):
        return self.inventory.held

    @property
    def held_name(self):
        return self.held.get("name") if self.held else None

    @property
    def controllable(self):
        """Is it meaningful to send gameplay input this frame?"""
        world = self.world
        return bool(
            world.in_restaurant
            and not world.paused
            and not world.input_captured
            and not world.game_over
            and self.me is not None)

    @property
    def in_service(self):
        return bool(
            self.world.in_restaurant
            and self.world.start_day_warnings is None
            and self.world.day_length > 0)

    def soft_obstacles(self):
        """Tiles a route should prefer to avoid: customers get in the way."""
        tiles = set()
        for customer in self.world.customers:
            tiles.add(K.tile_of(customer["x"], customer["z"]))
        for mess in self.kitchen.messes():
            tiles.add(K.tile_of(mess["x"], mess["z"]))
        return tiles

    def appliance_at(self, slot):
        return self.kitchen.by_slot.get(slot)


# --------------------------------------------------------------------------
# base option
# --------------------------------------------------------------------------


class Option:
    """A skill with a variable duration and a classified outcome."""

    name = "option"
    timeout = 25.0

    def __init__(self):
        self.status = RUNNING
        self.detail = ""
        self.started_clock = None
        self.started_tick = None
        self.ticks = 0
        self.presses = 0
        self.replans = 0
        self.route = None
        self.route_length = 0
        self.pose = None
        self._press_counter = 0
        self._history = []
        self._blocked_learned = set()
        self._aim_recoveries = 0
        # Whether to hold `StopMoving` while aiming.
        #
        # Off by default, which is what a human does: hold the direction, walk
        # into the appliance, let it block you, and press. That is certain to
        # put the right vector in `Movement` on the press frame, which is what
        # `AttemptInteraction` reads.
        #
        # `StopMoving` is documented as rotate-without-walking and would stop
        # a diagonal approach sliding along an appliance edge, but whether it
        # leaves `Movement` intact has never been tested. So it is the
        # fallback, tried only after presses have already failed, rather than
        # the default that everything depends on.
        self._use_stop = False

    # -- lifecycle --------------------------------------------------------

    @property
    def done(self):
        return self.status in TERMINAL

    def start(self, ctx):
        self.started_clock = ctx.clock
        self.started_tick = ctx.tick
        self.plan(ctx)
        return self

    def plan(self, ctx):
        """Validate the goal and choose an approach. Override."""

    def act(self, ctx):
        """Advance one control tick and return the action to send."""
        if self.done:
            return neutral()
        self.ticks += 1
        if self.started_clock is not None and ctx.clock and \
                ctx.clock - self.started_clock > self.timeout:
            return self.finish(TIMEOUT, f"after {self.timeout:.0f}s")
        if not ctx.controllable:
            # Menus, pauses and phase changes are not option failures. Hold
            # everything neutral so nothing leaks into the popup.
            return neutral()
        return self.run(ctx)

    def run(self, ctx):
        return self.finish(FAILED, "option has no behaviour")

    def finish(self, status, detail=""):
        self.status = status
        self.detail = detail
        return neutral()

    # -- shared motor primitives ------------------------------------------

    def _target_point(self, ctx):
        """Where the interaction should land. Override for moving goals."""
        return None

    def _drive(self, ctx, point, tolerance=ARRIVE_TOLERANCE):
        """Proportional approach to a world point along a planned route.

        Returns an action while travelling, or None once arrived. Replans
        around whatever the chef actually walks into, because the occupancy
        prior is derived from appliance layers and a wrong entry there would
        otherwise stall the option indefinitely.
        """
        position = ctx.position
        if position is None:
            return neutral()

        self._history.append(position)
        if len(self._history) > STUCK_WINDOW:
            self._history.pop(0)

        if K.distance(position, point) <= tolerance:
            self._history.clear()
            return None

        waypoint = self._next_waypoint(ctx, position, point)
        if waypoint is None:
            return neutral()

        if self._stuck(position):
            self._history.clear()
            if not self._recover(ctx, position, waypoint):
                self.finish(FAILED, "blocked; no route after replanning")
                return neutral()
            waypoint = self._next_waypoint(ctx, position, point)
            if waypoint is None:
                return neutral()

        dx, dz = waypoint[0] - position[0], waypoint[1] - position[1]
        span = math.hypot(dx, dz)
        if span < 1e-6:
            return neutral()
        scale = min(1.0, max(0.35, span / APPROACH_SPEED_RADIUS))
        return dict(neutral(), move=(dx / span * scale, dz / span * scale))

    def _next_waypoint(self, ctx, position, point):
        if not self.route:
            self.route = self._plan_route(ctx, position, point)
            if self.route is None:
                return None
        while self.route and K.distance(
                position, self.route[0]) <= WAYPOINT_TOLERANCE:
            self.route.pop(0)
        return self.route[0] if self.route else point

    def _plan_route(self, ctx, position, point):
        start = K.tile_of(*position)
        goal = K.tile_of(*point)
        tiles = ctx.kitchen.route(start, goal, avoid=ctx.soft_obstacles())
        if tiles is None:
            tiles = ctx.kitchen.route(start, goal)
        if tiles is None:
            return None
        route = [(float(x), float(z)) for x, z in tiles[1:]]
        route.append(point)
        return route

    def _stuck(self, position):
        if len(self._history) < STUCK_WINDOW:
            return False
        return all(
            K.distance(position, past) < STUCK_DISTANCE
            for past in self._history)

    def _recover(self, ctx, position, waypoint):
        """Learn the obstruction, then find another way around it."""
        self.replans += 1
        if self.replans > MAX_REPLANS:
            return False
        blocked = K.tile_of(*waypoint)
        if blocked != K.tile_of(*position):
            self._blocked_learned.add(blocked)
            ctx.kitchen.blocked.add(blocked)
        self.route = None
        return True

    def _aim(self, ctx, target, accepted=None):
        """Hold the direction that makes `target` the selected interaction.

        The aim is recomputed from the chef's real position every tick rather
        than from the planned pose, so arrival error does not become aim
        error, and the reach check is against where he actually is.
        """
        position = ctx.position
        goal = (target["x"], target["z"])
        span = K.distance(position, goal)
        if span > PRESS_REACH:
            return None, span
        ax, az = K.normalise(goal[0] - position[0], goal[1] - position[1])
        point = (position[0] + K.INTERACTION_OFFSET * ax,
                 position[1] + K.INTERACTION_OFFSET * az)
        keys = accepted if accepted is not None else {target["e"]}
        clearance = ctx.kitchen.aim_clearance(point, keys)
        if clearance <= 0.0:
            return None, span
        return (ax, az), span

    def _approach(self, ctx):
        """Drive to the planned stance, or re-plan it if aiming still fails.

        Arriving at a stance that no longer aims cleanly is normal: customers
        walk through, appliances get filled, and the pose was chosen from an
        older frame. Re-planning is the fix, but it has to be bounded or a
        genuinely unreachable target would spin until the timeout.
        """
        if self.pose is None:
            return self.finish(FAILED, "no stance planned")
        action = self._drive(ctx, (self.pose.x, self.pose.z))
        if action is not None:
            return action
        self._aim_recoveries += 1
        if self._aim_recoveries > MAX_AIM_RECOVERIES:
            return self.finish(FAILED, "arrived but could not aim cleanly")
        self.route = None
        self.plan(ctx)
        return neutral()

    def _press_grab(self, ctx, aim):
        """One Pressed edge, then a release, then a settle window.

        Grab only fires on the rising edge, so holding it does nothing after
        the first tick, and the outcome is not visible until the simulation
        has run. The cycle is press, release, wait, then let the caller check.
        """
        self._press_counter += 1
        cycle = PRESS_TICKS + RELEASE_TICKS + SETTLE_TICKS
        phase = (self._press_counter - 1) % cycle
        if phase == 0:
            self.presses += 1
            if self.presses == 3:
                self._use_stop = True
        pressing = phase < PRESS_TICKS
        return dict(neutral(), move=aim, stop=self._use_stop, grab=pressing)

    def _press_settled(self):
        cycle = PRESS_TICKS + RELEASE_TICKS + SETTLE_TICKS
        return self._press_counter % cycle == 0

    def _hold_interact(self, aim):
        return dict(neutral(), move=aim, stop=self._use_stop, interact=True)

    # -- reporting --------------------------------------------------------

    def _adopt_route(self, pose, tiles):
        """Store a planned stance and its route.

        `route_length` is kept separately because `route` is consumed as the
        chef walks it, and the capability registry buckets on how far the
        option had to travel, not on how far was left when it ended.
        """
        self.pose = pose
        self.route = [(float(x), float(z)) for x, z in tiles[1:]]
        self.route.append((pose.x, pose.z))
        self.route_length = max(self.route_length, len(self.route))

    def summary(self, ctx=None):
        record = {
            "option": self.name,
            "status": self.status,
            "detail": self.detail,
            "ticks": self.ticks,
            "presses": self.presses,
            "replans": self.replans,
            "route_length": self.route_length,
        }
        if ctx is not None and self.started_clock is not None and ctx.clock:
            record["seconds"] = round(ctx.clock - self.started_clock, 3)
        return record

    def __repr__(self):
        return f"{self.name}({self.status})"


# --------------------------------------------------------------------------
# targeted options
# --------------------------------------------------------------------------


class TargetedOption(Option):
    """An option aimed at one appliance slot.

    The slot key is `(game-data id, tile)` rather than an entity id, because
    fixed appliances are destroyed and recreated when the day starts and an
    entity reference taken during preparation is dangling during service.
    """

    def __init__(self, appliance):
        super().__init__()
        self.slot = K.slot_key(appliance)
        self.target_name = appliance.get("name")
        self.goal = (appliance["x"], appliance["z"])

    def resolve(self, ctx):
        return ctx.appliance_at(self.slot)

    def accepted_entities(self, ctx, target):
        return {target["e"]}

    def plan(self, ctx):
        target = self.resolve(ctx)
        if target is None:
            return self.finish(INVALID, f"{self.target_name} is gone")
        routed = ctx.kitchen.poses_by_route(
            target, soft=ctx.soft_obstacles(),
            extra_targets=self.extra_targets(ctx, target))
        if not routed:
            return self.finish(
                FAILED, f"no reachable stance for {self.target_name}")
        self._adopt_route(*routed[0])

    def extra_targets(self, ctx, target):
        return ()

    def run(self, ctx):
        target = self.resolve(ctx)
        if target is None:
            return self.finish(INVALID, f"{self.target_name} is gone")

        outcome = self.check(ctx, target)
        if outcome is not None:
            return self.finish(*outcome)

        accepted = self.accepted_entities(ctx, target)
        aim, span = self._aim(ctx, target, accepted)
        if aim is None:
            return self._approach(ctx)

        if self.presses >= MAX_PRESS_ATTEMPTS and self._press_settled():
            return self.finish(
                FAILED,
                f"{self.presses} presses at {self.target_name} changed nothing")
        return self.interact(ctx, target, aim)

    def interact(self, ctx, target, aim):
        return self._press_grab(ctx, aim)

    def check(self, ctx, target):
        """Return (status, detail) when the goal has been reached."""
        return None


class NavigateTo(TargetedOption):
    """Stand within reach of an appliance without touching it."""

    name = "navigate"
    timeout = 30.0

    def run(self, ctx):
        target = self.resolve(ctx)
        if target is None:
            return self.finish(INVALID, f"{self.target_name} is gone")
        action = self._drive(ctx, (self.pose.x, self.pose.z))
        if action is None:
            return self.finish(SUCCESS, f"at {self.target_name}")
        return action


class AcquireItem(TargetedOption):
    """Grab at a holder or provider until the chef is carrying `want`."""

    name = "acquire"

    def __init__(self, appliance, want=None, require_empty=True):
        super().__init__(appliance)
        self.want = want
        self.require_empty = require_empty
        self.initial_held = None

    def plan(self, ctx):
        if self.require_empty and ctx.held is not None:
            return self.finish(
                INVALID, f"hands full: {ctx.held_name}")
        self.initial_held = ctx.held.get("e") if ctx.held else None
        super().plan(ctx)

    def check(self, ctx, target):
        held = ctx.held
        if held is None:
            return None
        if held.get("e") == self.initial_held:
            return None
        if self.want and held.get("name") != self.want:
            return FAILED, f"picked up {held.get('name')}, wanted {self.want}"
        return SUCCESS, f"holding {held.get('name')}"


class PlaceItem(TargetedOption):
    """Grab at a holder to put down, store, combine or trash what is held.

    Placement is contextual: PlateUp has no free drop, so this succeeds only
    when the faced target actually accepts the item. Success is defined as the
    held item changing, which covers combining as well as putting down.
    """

    name = "place"

    def __init__(self, appliance, expect_held=None):
        super().__init__(appliance)
        self.expect_held = expect_held
        self.initial_held = None

    def plan(self, ctx):
        if ctx.held is None:
            return self.finish(INVALID, "nothing held")
        self.initial_held = ctx.held.get("e")
        super().plan(ctx)

    def check(self, ctx, target):
        held = ctx.held
        if held is not None and held.get("e") == self.initial_held:
            return None
        if self.expect_held is None:
            if held is None:
                return SUCCESS, f"placed on {self.target_name}"
            return SUCCESS, f"combined into {held.get('name')}"
        if held is not None and held.get("name") == self.expect_held:
            return SUCCESS, f"combined into {held.get('name')}"
        return FAILED, (
            f"expected to be holding {self.expect_held}, holding "
            f"{held.get('name') if held else None}")


class BinWaste(PlaceItem):
    """Dispose of a ruined item. Separate from PlaceItem so the capability
    registry prices trashing on its own: specification section 12 gate C4
    requires no accidental trashing, which needs the two counted apart."""

    name = "bin"


class OperateProcess(TargetedOption):
    """Hold Interact on an appliance until its contents reach a state.

    Interact acts on both `Pressed` and `Held`, so this holds the button
    rather than pulsing it. Progress is stored on the item and resumes after
    an interruption, which is why a wash that is broken off is not a failure.
    """

    name = "operate"
    timeout = 30.0

    # Roughly two seconds at the observed 25-30 Hz observation cadence.
    STALLED_TICKS = 60

    def __init__(self, appliance, until, describe="process"):
        super().__init__(appliance)
        self.until = until
        self.describe = describe
        self.progressed = False
        self.last_progress = None
        self._stalled = 0

    def interact(self, ctx, target, aim):
        item = target.get("held")
        if item is not None:
            progress = item.get("progress")
            if progress is not None:
                if self.last_progress is not None and \
                        progress > self.last_progress + 1e-6:
                    self.progressed = True
                self.last_progress = progress
        # Holding a button that is doing nothing is the one failure this
        # option cannot see from its own state, so if nothing has moved after
        # a couple of seconds, try the other aiming mode before timing out.
        self._stalled = 0 if self.progressed else self._stalled + 1
        if self._stalled > self.STALLED_TICKS:
            self._use_stop = not self._use_stop
            self._stalled = 0
        return self._hold_interact(aim)

    def check(self, ctx, target):
        if self.until(ctx, target):
            return SUCCESS, f"{self.describe} complete"
        if target.get("held") is None:
            return FAILED, f"nothing left on {self.target_name}"
        return None


# --------------------------------------------------------------------------
# service options
# --------------------------------------------------------------------------


class ServeOrder(Option):
    """Deliver whatever is held to a seated group's table.

    The group is tracked by entity id within the day, but the table is located
    by the group's own position, because `groups[].table` names an entity the
    appliance query never publishes. Both recorded delivery styles are
    accepted: two of the three in `runs/golden` aimed at the table and one at
    an occupied chair, and all three put the plate on the table.
    """

    name = "serve"
    timeout = 30.0

    def __init__(self, group, dish=None):
        super().__init__()
        self.group_entity = group["e"]
        self.dish = dish
        self.table_slot = None
        self.satisfied_before = None

    def _group(self, ctx):
        for group in ctx.world.groups:
            if group["e"] == self.group_entity:
                return group
        return None

    def _table(self, ctx, group):
        if self.table_slot is not None:
            table = ctx.appliance_at(self.table_slot)
            if table is not None:
                return table
        table = ctx.kitchen.table_for_group(group)
        if table is not None:
            self.table_slot = K.slot_key(table)
        return table

    @staticmethod
    def _unsatisfied(group):
        return sum(
            1 for order in group.get("orders", ())
            if not order.get("satisfied"))

    def plan(self, ctx):
        if ctx.held is None:
            return self.finish(INVALID, "nothing to serve")
        group = self._group(ctx)
        if group is None:
            return self.finish(INVALID, "group left")
        table = self._table(ctx, group)
        if table is None:
            return self.finish(INVALID, "group is not seated yet")
        self.satisfied_before = self._unsatisfied(group)
        routed = ctx.kitchen.poses_by_route(
            table, soft=ctx.soft_obstacles(),
            extra_targets=ctx.kitchen.chairs_around(table))
        if not routed:
            return self.finish(FAILED, "no reachable stance at the table")
        self._adopt_route(*routed[0])

    def run(self, ctx):
        group = self._group(ctx)
        if group is None:
            if ctx.held is None:
                return self.finish(SUCCESS, "served as the group departed")
            return self.finish(INVALID, "group left before delivery")
        table = self._table(ctx, group)
        if table is None:
            return self.finish(INVALID, "group is no longer seated")

        if self._unsatisfied(group) < self.satisfied_before:
            return self.finish(SUCCESS, "order satisfied")
        if ctx.held is None:
            return self.finish(SUCCESS, "dish left on the table")

        accepted = {table["e"]} | {
            chair["e"] for chair in ctx.kitchen.chairs_around(table)}
        aim, _span = self._aim(ctx, table, accepted)
        if aim is None:
            return self._approach(ctx)

        if self.presses >= MAX_PRESS_ATTEMPTS and self._press_settled():
            return self.finish(FAILED, f"{self.presses} presses, no delivery")
        return self._press_grab(ctx, aim)


class StartDay(Option):
    """Consent to the day starting.

    `StartDayWarningView` reads `SecondaryAction1` from the captured input, so
    this is a held button rather than a menu confirm, and it must keep being
    sent while the view owns input, which is exactly when `controllable` is
    false. That is why this option overrides `act` instead of `run`.
    """

    name = "start_day"
    timeout = 45.0

    def act(self, ctx):
        if self.done:
            return neutral()
        self.ticks += 1
        if self.started_clock is not None and ctx.clock and \
                ctx.clock - self.started_clock > self.timeout:
            return self.finish(TIMEOUT, "day did not start")
        if ctx.world.game_over:
            return self.finish(INVALID, "game over")
        if ctx.world.start_day_warnings is None:
            if ctx.in_service:
                return self.finish(SUCCESS, "service started")
            # Some other view owns the screen. Consent is only meaningful
            # while the start-day warning is up, and SecondaryAction1 means
            # something else to other popups, so wait rather than press.
            return neutral()
        return dict(neutral(), ready=True)


class Idle(Option):
    """Do nothing for a bounded time.

    Waiting is a real decision in this game: standing beside a hob until a
    steak reaches the doneness you want beats walking away and coming back.
    Kept as an explicit option so the surrogate prices it like any other.
    """

    name = "idle"

    def __init__(self, seconds=1.0, until=None):
        super().__init__()
        self.seconds = seconds
        self.until = until

    def run(self, ctx):
        if self.until is not None and self.until(ctx):
            return self.finish(SUCCESS, "condition met")
        if self.started_clock is not None and ctx.clock and \
                ctx.clock - self.started_clock >= self.seconds:
            return self.finish(SUCCESS, f"waited {self.seconds:.1f}s")
        return neutral()


class WatchCook(Option):
    """Stand at a hob and lift the item at the chosen doneness.

    This is the steak-specific decision the whole recipe turns on. The lift
    time comes from published fields only: `progress` and `rate` give the
    seconds left in the current stage exactly, so no recipe timing table is
    consulted and a changed appliance speed needs no new constant.
    """

    name = "watch_cook"
    timeout = 45.0

    def __init__(self, appliance, chain, min_stage=1):
        super().__init__()
        self.slot = K.slot_key(appliance)
        self.target_name = appliance.get("name")
        self.chain = chain
        self.min_stage = max(1, min(min_stage, len(chain.stages)))
        self.pose = None

    def resolve(self, ctx):
        return ctx.appliance_at(self.slot)

    def plan(self, ctx):
        if ctx.held is not None:
            return self.finish(INVALID, f"hands full: {ctx.held_name}")
        target = self.resolve(ctx)
        if target is None:
            return self.finish(INVALID, f"{self.target_name} is gone")
        routed = ctx.kitchen.poses_by_route(target, soft=ctx.soft_obstacles())
        if not routed:
            return self.finish(FAILED, f"no stance at {self.target_name}")
        self._adopt_route(*routed[0])

    def should_lift(self, item):
        """Take it now, or leave it on the heat for one more stage?

        Rare, Medium and Well-done all plate to the same `Steak - Plated`,
        which the order names and which pays the same either way, so cooking
        on buys nothing and only risks the burn. The default is therefore to
        lift at the first servable stage. `min_stage` exists so the choice can
        be varied and measured rather than assumed, and `is_bad` forces the
        lift whatever it is set to, because that flag means the transition now
        running ends in waste.
        """
        name = item.get("name")
        if not self.chain.is_servable(name):
            return False
        if item.get("is_bad"):
            return True
        stage = self.chain.stage_number(name)
        return stage is not None and stage >= self.min_stage

    def run(self, ctx):
        target = self.resolve(ctx)
        if target is None:
            return self.finish(INVALID, f"{self.target_name} is gone")

        if ctx.held is not None:
            name = ctx.held_name
            if self.chain.is_servable(name):
                return self.finish(SUCCESS, f"lifted {name}")
            return self.finish(FAILED, f"picked up {name}")

        item = target.get("held")
        if item is None:
            return self.finish(INVALID, f"{self.target_name} is empty")
        if self.chain.is_waste(item.get("name")):
            return self.finish(FAILED, f"{item.get('name')} on the hob")

        aim, _span = self._aim(ctx, target)
        if aim is None:
            return self._approach(ctx)

        if not self.should_lift(item):
            # In position, waiting. Keep the aim held so the press that
            # follows cannot pick up a neighbouring appliance's contents.
            return dict(neutral(), move=aim, stop=True)

        if self.presses >= MAX_PRESS_ATTEMPTS and self._press_settled():
            return self.finish(FAILED, f"{self.presses} presses, nothing lifted")
        return self._press_grab(ctx, aim)


# --------------------------------------------------------------------------
# composites
# --------------------------------------------------------------------------


class Sequence(Option):
    """Run child options in order; any non-success ends the sequence.

    Composites exist because the capability registry prices whole jobs, not
    just their first leg. Washing a plate is three interactions with one
    outcome, and the planner needs the outcome.
    """

    name = "sequence"

    def __init__(self, name, factories, timeout=90.0):
        super().__init__()
        self.name = name
        self.factories = list(factories)
        self.timeout = timeout
        self.index = 0
        self.current = None
        self.children = []

    def plan(self, ctx):
        self._advance(ctx)

    def _advance(self, ctx):
        while self.index < len(self.factories):
            factory = self.factories[self.index]
            self.index += 1
            option = factory(ctx)
            if option is None:
                continue
            option.start(ctx)
            self.children.append(option)
            self.current = option
            if not option.done:
                return
            if option.status != SUCCESS:
                self.finish(option.status, f"{option.name}: {option.detail}")
                return
        self.current = None
        if not self.done:
            self.finish(SUCCESS, f"{len(self.children)} steps")

    def act(self, ctx):
        if self.done:
            return neutral()
        self.ticks += 1
        if self.started_clock is not None and ctx.clock and \
                ctx.clock - self.started_clock > self.timeout:
            return self.finish(TIMEOUT, f"after {self.timeout:.0f}s")
        if not ctx.controllable:
            return neutral()
        if self.current is None:
            self._advance(ctx)
            if self.done:
                return neutral()
        action = self.current.act(ctx)
        if self.current.done:
            self.presses += self.current.presses
            self.replans += self.current.replans
            # A composite's route length is how far the whole job walked, so
            # the capability registry buckets it by the same distance bands as
            # a primitive option.
            self.route_length += self.current.route_length
            if self.current.status != SUCCESS:
                return self.finish(
                    self.current.status,
                    f"{self.current.name}: {self.current.detail}")
            self.current = None
            self._advance(ctx)
            if self.done:
                return neutral()
            return neutral()
        return action

    def summary(self, ctx=None):
        record = super().summary(ctx)
        record["steps"] = [child.summary() for child in self.children]
        return record


def wash_plate(sink, chain):
    """Place a dirty plate in a sink, wash it, and pick it back up."""

    def place(ctx):
        return PlaceItem(sink)

    def scrub(ctx):
        target = ctx.appliance_at(K.slot_key(sink))
        if target is None:
            return None

        def clean(_ctx, appliance):
            item = appliance.get("held")
            return item is not None and item.get("name") == S.CLEAN_PLATE

        return OperateProcess(sink, clean, describe="wash")

    def collect(ctx):
        return AcquireItem(sink, want=S.CLEAN_PLATE)

    return Sequence("wash_plate", (place, scrub, collect))


def start_cook(hob, provider, chain):
    """Fetch a raw cut and put it on the heat, then hand control back.

    Deliberately stops at the hob rather than waiting there. A steak takes
    several seconds to reach Rare and the chef has plates to wash and dishes to
    carry in the meantime; the priority list picks the lift up again through
    its own rescue and lift rules, which also means a second hob can be
    loaded. Standing and watching is safer but strictly slower, and
    `cook_one` below keeps that variant so the two can be compared.
    """

    def fetch(ctx):
        return AcquireItem(provider, want=chain.raw)

    def load(ctx):
        return PlaceItem(hob)

    return Sequence("start_cook", (fetch, load), timeout=60.0)


def cook_one(hob, provider, chain, min_stage=1):
    """Fetch, load, and stand at the hob until the steak is servable."""

    def fetch(ctx):
        return AcquireItem(provider, want=chain.raw)

    def load(ctx):
        return PlaceItem(hob)

    def watch(ctx):
        return WatchCook(hob, chain, min_stage=min_stage)

    return Sequence("cook_one", (fetch, load, watch), timeout=120.0)


def plate_held(plate_provider, chain):
    """Combine the cooked item in hand with a clean plate."""

    def combine(ctx):
        return PlaceItem(plate_provider, expect_held=chain.plated)

    return Sequence("plate_held", (combine,), timeout=45.0)
