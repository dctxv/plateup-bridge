r"""
A tick-level model of the PlateUp steak loop, for running the agent offline.

This is a **model of the game, not the game**. Nothing it produces is evidence
about PlateUp. What it is for is exercising `kitchen`, `steak`, `options` and
`service` end to end without a running copy of PlateUp: routing, reach, aim
disambiguation, press edges, the cook chain, plating, delivery, washing and
the day clock all run against a responsive world instead of a frozen
recording. A pass here means the agent code is coherent; it does not mean the
chef behaves this way on screen.

Every modelled rule below is either taken from the recorded artifacts or is a
stated simplification. The measured ones:

    obs cadence         0.033-0.044 game seconds between frames, so roughly
                        25-30 Hz, not the 10 Hz the tick divisor suggests
    top speed           3.7 units/s at the 99th percentile of 0.5 s windows,
                        4.1 units/s at the maximum
    turn rate           ~770 deg/s at the 90th percentile, 1360 at the maximum
    process rate        0.375 progress/s on a starting hob and a starting sink
    patience drain      0.00434/s while waiting to order, 0.00722/s while
                        waiting for food, and zero in every other phase
    lifecycle           seating 8-10 s, thinking 3.0 s, service 4.3-5.2 s,
                        eating ~3.0 s
    arrivals            four groups of one across a 100 s day 1, about 24.5 s
                        apart
    layout              taken verbatim from a recorded observation frame

The stated simplifications, none of which the agent may rely on:

    customers walk straight to their seat and do not collide with the chef;
    there is no mess, no fire, no dessert course and no dirty-plate rack;
    every group orders exactly one main;
    appliance contents are one item deep, which matches the starting set.
"""

import json
import math
import random

import kitchen as K
import steak as S

FRAME_SECONDS = 0.0375        # midpoint of the observed 0.033-0.044 s cadence
MAX_SPEED = 4.0               # units/s
TURN_RATE = 800.0             # deg/s
MOVEMENT_DEADZONE = 0.10
FACING_SPREAD = 60.0          # degrees; force applies once inside this
PLAYER_RADIUS = 0.32

PATIENCE_DRAIN = {3: 0.00434, 4: 0.00722}
THINKING_SECONDS = 3.0
SERVICE_SECONDS = 4.5
EATING_SECONDS = 3.0
SEATING_SECONDS = 9.0
ARRIVAL_INTERVAL = 24.5
FIRST_ARRIVAL = 0.1

BUTTON_UP = 0
BUTTON_RELEASED = 1
BUTTON_HELD = 2
BUTTON_PRESSED = 3


class Item:
    __slots__ = ("entity", "name", "process", "progress", "is_bad", "rate",
                 "components")

    def __init__(self, entity, name, components=None):
        self.entity = entity
        self.name = name
        self.process = None
        self.progress = None
        self.is_bad = False
        self.rate = None
        self.components = list(components or [name])


class Group:
    __slots__ = ("entity", "size", "table", "phase", "reason", "patience",
                 "timer", "orders", "arrived", "seat", "position", "done")

    def __init__(self, entity, size, table, arrived):
        self.entity = entity
        self.size = size
        self.table = table
        self.phase = 0            # MenuPhase.Starter
        self.reason = 2           # PatienceReason.Seating
        self.patience = 1.0
        self.timer = SEATING_SECONDS
        self.orders = []
        self.arrived = arrived
        self.position = None
        self.done = False


class MockPlateUp:
    """Replays a recorded layout as a live world the agent can act in."""

    def __init__(self, path, cut="plain", seed=1, day_length=None,
                 groups=None, plates=None, interval=None,
                 preparation=False, popup_seconds=0.0, randomise_start=False):
        self.path = path
        self.chain = S.Chain(cut)
        self.random = random.Random(seed)
        self.dictionary = None
        self.items_by_id = {}
        self.appliance_names = {}
        self.process_ids = {}
        self.layout = []
        self._load(path)

        self.day_length = day_length if day_length is not None else 100.0
        self.total_groups = 4 if groups is None else groups
        self.plate_capacity = plates
        self.arrival_interval = (
            ARRIVAL_INTERVAL if interval is None else interval)
        # Preparation is the phase the live agent meets first, so the model
        # can start there. Day 0 in both recordings published
        # `start_day_warnings` with `players_not_ready` at Error and
        # everything else Safe, and the block vanished the moment day 1 began.
        self.start_in_preparation = bool(preparation)
        self.popup_seconds = float(popup_seconds)
        # Specification section 10.3 step 3: randomise the starting pose and
        # held item. Without it every trajectory in a cloned dataset begins
        # from the same spot with empty hands, and the policy has never seen
        # the states it drifts into.
        self.randomise_start = bool(randomise_start)

        self._next_entity = 100000
        self.reset()

    # -- construction -----------------------------------------------------

    def _load(self, path):
        """Take the name dictionary and one service frame from a recording."""
        best = None
        with open(path, encoding="utf-8") as source:
            for line in source:
                line = line.strip()
                if not line:
                    continue
                message = json.loads(line)
                kind = message.get("kind")
                if kind == "dict":
                    self.dictionary = message
                    self.items_by_id = {
                        int(k): v for k, v in message["items"].items()}
                    self.appliance_names = {
                        int(k): v for k, v in message["appliances"].items()}
                    self.process_ids = {
                        v: int(k) for k, v in message["processes"].items()}
                elif kind == "obs" and message.get("in_restaurant"):
                    if best is None or len(message.get("appliances", ())) > \
                            len(best.get("appliances", ())):
                        best = message
        if self.dictionary is None or best is None:
            raise ValueError(f"{path}: no dictionary or restaurant frame")

        self.item_ids = {v: k for k, v in self.items_by_id.items()}
        self.frame = best
        self.layout = [dict(a) for a in best.get("appliances", ())]

        provided = {
            self.items_by_id.get(a.get("provides"))
            for a in self.layout if "provides" in a}
        if self.chain.raw not in provided:
            raise ValueError(
                f"{path}: this layout provides {sorted(n for n in provided if n)}"
                f", not {self.chain.raw}; it is not a {self.chain.cut} steak "
                "restaurant")

    def _entity(self):
        self._next_entity += 1
        return f"{self._next_entity}:1"

    def _named(self, appliance):
        return self.appliance_names.get(appliance.get("aid"), "?")

    # -- reset ------------------------------------------------------------

    def reset(self):
        self.tick = 0
        self.clock = 0.0
        self.seconds = 0.0
        self.phase = "preparation" if self.start_in_preparation else "service"
        self.ready = False
        self.ready_at = None
        self.popup_until = (
            self.popup_seconds if self.start_in_preparation else 0.0)
        self.money = 0
        self.lives = 1
        self.game_over = False
        self.served = 0
        self.lost = 0
        self.ruined = 0
        self.items = {}
        self.contents = {}          # appliance entity -> Item
        self.groups = []
        self.pending_arrivals = []
        self.command_id = 0
        self.previous_buttons = {
            "grab": BUTTON_UP, "interact": BUTTON_UP,
            "ready": BUTTON_UP, "menu_cancel": BUTTON_UP}

        self.appliances = []
        for source in self.layout:
            appliance = dict(source)
            appliance["e"] = self._entity()
            appliance.pop("held", None)
            self.appliances.append(appliance)
        self.by_entity = {a["e"]: a for a in self.appliances}

        self.tables = [
            a for a in self.appliances if self._named(a).startswith("Table")]
        self.chairs = [
            a for a in self.appliances
            if self._named(a) == "Chair"]
        self.hobs = [
            a for a in self.appliances if "Hob" in self._named(a)]
        self.sinks = [
            a for a in self.appliances if "Sink" in self._named(a)]
        self.bins = [
            a for a in self.appliances
            if self._named(a).startswith("Bin")]

        for appliance in self.appliances:
            if "provides" not in appliance:
                continue
            if self.items_by_id.get(appliance["provides"]) == S.CLEAN_PLATE \
                    and self.plate_capacity is not None:
                appliance["available"] = self.plate_capacity
                appliance["maximum"] = self.plate_capacity

        self.blocked = {
            K.tile_of(a["x"], a["z"]) for a in self.appliances
            if a.get("layer") == K.OCCUPANCY_DEFAULT
            and not K.name_matches(self._named(a), K.WALKABLE_DEFAULT_LAYER)}

        self.player = {
            "x": 0.0, "z": 0.0, "rot": 0.0, "held": None, "id": 1}
        self._place_player()
        if self.randomise_start:
            self._randomise_start()

        arrival = FIRST_ARRIVAL
        for _ in range(self.total_groups):
            if arrival >= self.day_length:
                break
            self.pending_arrivals.append(arrival)
            arrival += self.arrival_interval * self.random.uniform(0.9, 1.1)

        return self.observation()

    def _randomise_start(self):
        """Scatter the chef, what he is holding, and what is already cooking.

        Everything placed here is reachable through normal play, so a policy
        trained on it is not being shown an impossible world -- only a wider
        slice of the possible one.
        """
        free = sorted(
            tile for tile in self._free_tiles()
            if abs(tile[0]) < 12 and abs(tile[1]) < 12)
        if free:
            tile = free[self.random.randrange(len(free))]
            self.player["x"] = float(tile[0]) + self.random.uniform(-0.2, 0.2)
            self.player["z"] = float(tile[1]) + self.random.uniform(-0.2, 0.2)
        self.player["rot"] = self.random.uniform(0.0, 360.0)

        roll = self.random.random()
        if roll < 0.25:
            self.player["held"] = self._new_item(self.chain.raw)
        elif roll < 0.40:
            self.player["held"] = self._new_item(self.chain.stages[0])
        elif roll < 0.50:
            self.player["held"] = self._new_item(S.CLEAN_PLATE)
        elif roll < 0.58:
            self.player["held"] = self._new_item("Plate - Dirty")

        for hob in self.hobs:
            if self.random.random() < 0.3:
                stage = self.random.randrange(0, len(self.chain.stages) + 1)
                item = self._new_item(self.chain.sequence[stage])
                item.progress = self.random.random()
                self.contents[hob["e"]] = item

        surfaces = [
            a for a in self.appliances
            if "Countertop" in self._named(a)]
        for surface in surfaces:
            if self.random.random() < 0.2:
                self.contents[surface["e"]] = self._new_item(
                    self.chain.plated,
                    components=[S.CLEAN_PLATE, self.chain.stages[0]])

    def _free_tiles(self):
        tiles = set()
        for appliance in self.appliances:
            origin = K.tile_of(appliance["x"], appliance["z"])
            for dx in range(-1, 2):
                for dz in range(-1, 2):
                    tile = (origin[0] + dx, origin[1] + dz)
                    if tile not in self.blocked:
                        tiles.add(tile)
        return tiles

    def _place_player(self):
        """Start on a free tile near the kitchen appliances."""
        anchor = self.hobs[0] if self.hobs else self.appliances[0]
        for radius in range(1, 8):
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    tile = (int(round(anchor["x"])) + dx,
                            int(round(anchor["z"])) + dz)
                    if tile not in self.blocked:
                        self.player["x"] = float(tile[0])
                        self.player["z"] = float(tile[1])
                        return
        raise RuntimeError("no free tile to start on")

    # -- stepping ---------------------------------------------------------

    def step(self, action=None):
        action = action or {}
        self.tick += 1
        self.clock += FRAME_SECONDS
        self.seconds += FRAME_SECONDS

        self._move(action)
        buttons = self._edges(action)

        if self.phase == "preparation":
            self._advance_preparation(buttons)
            return self.observation()

        if buttons["grab"] == BUTTON_PRESSED:
            self._grab(action)
        if buttons["interact"] in (BUTTON_PRESSED, BUTTON_HELD):
            self._interact(action)

        self._advance_processes()
        self._advance_customers()
        return self.observation()

    # -- preparation ------------------------------------------------------

    def _advance_preparation(self, buttons):
        """Day 0: clear any popup, take consent, then open the restaurant.

        Consent toggles on the `Pressed` edge, matching the note in the
        observation schema that `StartDayWarningView` toggles when
        SecondaryAction1 is pressed. A controller that releases and presses
        again therefore un-readies itself, which is worth modelling because it
        is a mistake that would be invisible until a live run stalled.
        """
        if self.popup_until > 0.0:
            if buttons["menu_cancel"] == BUTTON_PRESSED:
                self.popup_until = 0.0
            else:
                self.popup_until = max(0.0, self.popup_until - FRAME_SECONDS)
            return

        if buttons["ready"] == BUTTON_PRESSED:
            self.ready = not self.ready
            self.ready_at = self.clock if self.ready else None

        if self.ready and self.ready_at is not None and                 self.clock - self.ready_at >= 0.5:
            self.phase = "service"
            self.seconds = 0.0

    def _edges(self, action):
        state = {}
        for name in ("grab", "interact", "ready", "menu_cancel"):
            down = bool(action.get(name))
            old = self.previous_buttons[name]
            if down:
                new = BUTTON_HELD if old in (
                    BUTTON_HELD, BUTTON_PRESSED) else BUTTON_PRESSED
            else:
                new = BUTTON_UP if old in (
                    BUTTON_UP, BUTTON_RELEASED) else BUTTON_RELEASED
            state[name] = new
            self.previous_buttons[name] = new
        return state

    # -- movement ---------------------------------------------------------

    def _move(self, action):
        move_x, move_z = action.get("move", (0.0, 0.0))
        magnitude = math.hypot(move_x, move_z)
        if magnitude < MOVEMENT_DEADZONE:
            return
        if magnitude > 1.0:
            move_x, move_z = move_x / magnitude, move_z / magnitude
            magnitude = 1.0

        desired = K.heading_degrees(move_x, move_z)
        error = K.angle_error(desired, self.player["rot"])
        step = TURN_RATE * FRAME_SECONDS
        if abs(error) <= step:
            self.player["rot"] = desired
        else:
            self.player["rot"] = (
                self.player["rot"] + math.copysign(step, error)) % 360.0

        if action.get("stop"):
            return
        if abs(K.angle_error(desired, self.player["rot"])) > FACING_SPREAD:
            return

        ax, az = K.facing_vector(self.player["rot"])
        distance = MAX_SPEED * magnitude * FRAME_SECONDS
        self._translate(ax * distance, az * distance)

    def _translate(self, dx, dz):
        """Axis-separated sliding collision against blocked tiles."""
        x, z = self.player["x"], self.player["z"]
        if not self._collides(x + dx, z):
            x += dx
        if not self._collides(x, z + dz):
            z += dz
        self.player["x"], self.player["z"] = x, z

    def _collides(self, x, z):
        for tile_x in (int(math.floor(x - PLAYER_RADIUS + 0.5)),
                       int(math.floor(x + PLAYER_RADIUS + 0.5))):
            for tile_z in (int(math.floor(z - PLAYER_RADIUS + 0.5)),
                           int(math.floor(z + PLAYER_RADIUS + 0.5))):
                if (tile_x, tile_z) not in self.blocked:
                    continue
                nearest_x = min(max(x, tile_x - 0.5), tile_x + 0.5)
                nearest_z = min(max(z, tile_z - 0.5), tile_z + 0.5)
                if math.hypot(x - nearest_x, z - nearest_z) < PLAYER_RADIUS:
                    return True
        return False

    # -- interaction ------------------------------------------------------

    def _aim_target(self, action):
        move_x, move_z = action.get("move", (0.0, 0.0))
        if math.hypot(move_x, move_z) >= MOVEMENT_DEADZONE:
            ax, az = K.normalise(move_x, move_z)
        else:
            ax, az = K.facing_vector(self.player["rot"])
        point = (self.player["x"] + K.INTERACTION_OFFSET * ax,
                 self.player["z"] + K.INTERACTION_OFFSET * az)

        best = None
        best_gap = K.INTERACTION_RADIUS
        for appliance in self.appliances:
            if appliance.get("layer") != K.OCCUPANCY_DEFAULT:
                continue
            name = self._named(appliance)
            if K.is_structure(name) or K.name_matches(
                    name, K.WALKABLE_DEFAULT_LAYER):
                continue
            gap = K.distance(point, (appliance["x"], appliance["z"]))
            if gap < best_gap:
                best, best_gap = appliance, gap
        return best

    def _grab(self, action):
        target = self._aim_target(action)
        if target is None:
            return
        name = self._named(target)
        held = self.player["held"]
        contents = self.contents.get(target["e"])

        if held is None:
            if contents is not None:
                self.player["held"] = contents
                del self.contents[target["e"]]
                return
            provided = self._provide(target)
            if provided is not None:
                self.player["held"] = provided
            return

        if name.startswith("Bin"):
            if self.chain.is_waste(held.name) or S.is_ruined(held.name):
                self.ruined += 1
            self.player["held"] = None
            del self.items[held.entity]
            return

        if name.startswith("Table"):
            if self._serve(target, held):
                return

        if contents is None:
            combined = self._combine_with_provider(target, held)
            if combined is not None:
                self.player["held"] = combined
                return
            if self._accepts(target, held):
                self.contents[target["e"]] = held
                self.player["held"] = None
            return

        combined = self._combine(held, contents)
        if combined is not None:
            del self.items[contents.entity]
            del self.contents[target["e"]]
            self.player["held"] = combined

    def _accepts(self, appliance, item):
        name = self._named(appliance)
        if name.startswith("Source") or name.startswith("Plate Stack"):
            # A provider takes back only what it hands out.
            return self.items_by_id.get(appliance.get("provides")) == item.name
        return True

    def _provide(self, appliance):
        if "provides" not in appliance:
            return None
        provided = self.items_by_id.get(appliance["provides"])
        if provided in (None, S.WATER):
            return None
        maximum = appliance.get("maximum") or 0
        if maximum:
            if (appliance.get("available") or 0) <= 0:
                return None
            appliance["available"] -= 1
        return self._new_item(provided)

    def _combine_with_provider(self, appliance, held):
        """Grabbing a plate stack while holding food plates the food.

        This is the route the recorded burger day used, and it is the only
        plating route with recorded evidence behind it.
        """
        if "provides" not in appliance:
            return None
        if self.items_by_id.get(appliance["provides"]) != S.CLEAN_PLATE:
            return None
        if not self.chain.is_servable(held.name):
            return None
        maximum = appliance.get("maximum") or 0
        if maximum:
            if (appliance.get("available") or 0) <= 0:
                return None
            appliance["available"] -= 1
        del self.items[held.entity]
        return self._new_item(
            self.chain.plated, components=[S.CLEAN_PLATE, held.name])

    def _combine(self, held, contents):
        if held.name == S.CLEAN_PLATE and self.chain.is_servable(contents.name):
            del self.items[held.entity]
            return self._new_item(
                self.chain.plated, components=[S.CLEAN_PLATE, contents.name])
        if contents.name == S.CLEAN_PLATE and self.chain.is_servable(held.name):
            del self.items[held.entity]
            return self._new_item(
                self.chain.plated, components=[S.CLEAN_PLATE, held.name])
        return None

    def _serve(self, table, held):
        if held.name != self.chain.plated:
            return False
        for group in self.groups:
            if group.table is not table or group.done:
                continue
            for order in group.orders:
                if order["satisfied"] or order["iid"] != self.item_ids.get(
                        self.chain.plated):
                    continue
                order["satisfied"] = True
                self.player["held"] = None
                del self.items[held.entity]
                self.money += order["reward"]
                self.served += 1
                group.reason = 1              # Eating
                group.patience = 1.0
                group.timer = EATING_SECONDS
                return True
        return False

    def _interact(self, action):
        target = self._aim_target(action)
        if target is None:
            return
        contents = self.contents.get(target["e"])
        if contents is None:
            return
        if "Sink" not in self._named(target):
            return
        if not S.is_dirty_plate(contents.name):
            return
        contents.process = self.process_ids.get(S.CLEAN_PROCESS)
        contents.rate = S.STARTING_APPLIANCE_RATE
        if contents.progress is None:
            contents.progress = 0.0
        contents.progress += S.STARTING_APPLIANCE_RATE * FRAME_SECONDS
        if contents.progress >= 1.0:
            contents.name = S.CLEAN_PLATE
            contents.components = [S.CLEAN_PLATE]
            contents.process = None
            contents.progress = None
            contents.rate = None
            contents.is_bad = False

    # -- processes --------------------------------------------------------

    def _advance_processes(self):
        for appliance in self.hobs:
            item = self.contents.get(appliance["e"])
            if item is None:
                continue
            self._cook(item)

    def _cook(self, item):
        step = self.chain.stage_number(item.name)
        if step is None or step >= len(self.chain.sequence) - 1:
            item.process = None
            item.progress = None
            item.rate = None
            return
        duration = self.chain.stage_seconds(step)
        rate = 1.0 / duration
        item.process = self.process_ids.get(S.COOK_PROCESS)
        item.rate = rate
        item.progress = (item.progress or 0.0) + rate * FRAME_SECONDS
        item.is_bad = self.chain.is_waste(self.chain.next_state(item.name))
        while item.progress is not None and item.progress >= 1.0:
            nxt = self.chain.next_state(item.name)
            if nxt is None:
                item.progress = 1.0
                break
            item.progress -= 1.0
            item.name = nxt
            item.components = [nxt]
            step = self.chain.stage_number(item.name)
            if step is None or step >= len(self.chain.sequence) - 1:
                item.process = None
                item.progress = None
                item.rate = None
                item.is_bad = False
                break
            item.rate = 1.0 / self.chain.stage_seconds(step)
            item.is_bad = self.chain.is_waste(self.chain.next_state(item.name))

    # -- customers --------------------------------------------------------

    def _advance_customers(self):
        while self.pending_arrivals and \
                self.seconds >= self.pending_arrivals[0]:
            self.pending_arrivals.pop(0)
            self._arrive()

        for group in list(self.groups):
            if group.done:
                continue
            drain = PATIENCE_DRAIN.get(group.reason, 0.0)
            if drain:
                group.patience = max(0.0, group.patience - drain * FRAME_SECONDS)
                if group.patience <= 0.0:
                    self._walk_out(group)
                    continue
            group.timer -= FRAME_SECONDS
            if group.timer > 0.0:
                continue
            self._advance_phase(group)

        if self.seconds >= self.day_length and not any(
                not group.done for group in self.groups) and \
                not self.pending_arrivals:
            self.game_over = False

    def _free_table(self):
        taken = {
            group.table["e"] for group in self.groups
            if not group.done and group.table is not None}
        for table in self.tables:
            if table["e"] in taken:
                continue
            if self.contents.get(table["e"]) is not None:
                continue
            return table
        return None

    def _arrive(self):
        table = self._free_table()
        if table is None:
            return
        group = Group(self._entity(), 1, table, self.seconds)
        group.position = (table["x"], table["z"])
        self.groups.append(group)

    def _advance_phase(self, group):
        if group.reason == 2:                       # Seating -> Thinking
            group.phase = 1                         # MenuPhase.Main
            group.reason = 0
            group.patience = 1.0
            group.timer = THINKING_SECONDS
        elif group.reason == 0 and not group.orders:
            group.reason = 3                        # Service
            group.patience = 1.0
            group.timer = SERVICE_SECONDS
        elif group.reason == 3:                     # -> WaitForFood
            group.reason = 4
            group.patience = 1.0
            group.timer = float("inf")
            group.orders = [{
                "iid": self.item_ids.get(self.chain.plated),
                "member": 0,
                "satisfied": False,
                "is_side": False,
                "reward": 5,
                "dirt": self.item_ids.get("Plate - Dirty"),
            }]
        elif group.reason == 1:                     # Eating -> Complete
            self._complete(group)

    def _complete(self, group):
        group.phase = 4                             # MenuPhase.Complete
        group.done = True
        dirty = self._new_item("Plate - Dirty")
        self.contents[group.table["e"]] = dirty

    def _walk_out(self, group):
        group.done = True
        self.lost += 1
        self.lives -= 1
        if self.lives <= 0:
            self.game_over = True

    # -- items ------------------------------------------------------------

    def _new_item(self, name, components=None):
        item = Item(self._entity(), name, components)
        self.items[item.entity] = item
        return item

    # -- serialisation ----------------------------------------------------

    def _item_json(self, item):
        payload = {
            "e": item.entity,
            "iid": self.item_ids.get(item.name, 0),
            "cat": 0,
        }
        if item.components:
            payload["items"] = [
                self.item_ids.get(name, 0) for name in item.components]
        if item.process is not None:
            payload["process"] = item.process
            payload["progress"] = round(item.progress or 0.0, 3)
            payload["is_bad"] = bool(item.is_bad)
            payload["rate"] = round(item.rate or 0.0, 3)
        return payload

    def observation(self):
        appliances = []
        for appliance in self.appliances:
            payload = {
                key: value for key, value in appliance.items()
                if key not in ("held",)}
            contents = self.contents.get(appliance["e"])
            if contents is not None:
                payload["held"] = self._item_json(contents)
            appliances.append(payload)

        groups = []
        customers = []
        for group in self.groups:
            if group.done:
                continue
            groups.append({
                "e": group.entity,
                "x": group.position[0],
                "z": group.position[1],
                "patience_active": True,
                "patience_left": round(group.patience, 3),
                "patience_total": 1,
                "patience_reason": group.reason,
                "patience_rate": 1 if group.reason in PATIENCE_DRAIN else 0,
                "meal_phase": group.phase,
                "table": group.table["e"],
                "size": group.size,
                "orders": [dict(order) for order in group.orders],
            })
            customers.append({
                "e": group.entity.replace(":", "0:"),
                "x": group.position[0],
                "z": group.position[1],
                "state": 2 if group.reason != 2 else 0,
                "group": group.entity,
                "idx": 0,
            })

        held = self.player["held"]
        preparing = self.phase == "preparation"
        frame = {
            "kind": "obs",
            "protocol": 1,
            "tick": self.tick,
            "in_restaurant": True,
            "practice_mode": False,
            "paused": False,
            "override": True,
            "input_captured": preparing and self.popup_until > 0.0,
            "ack_command": self.command_id,
            "cmds_applied": self.command_id,
            "cmds_dropped": 0,
            "outbound_frames_dropped": 0,
            "game_speed": 1,
            "game_total_time": round(self.clock, 3),
            "real_total_time": round(self.clock, 3),
            "day": 0 if preparing else 1,
            "time_of_day": (
                0 if preparing
                else round(min(1.0, self.seconds / self.day_length), 3)),
            "time_unbounded": (
                0 if preparing else round(self.seconds / self.day_length, 3)),
            "seconds_elapsed": 0 if preparing else round(self.seconds, 3),
            "day_length": self.day_length,
            "money": self.money,
            "lives": self.lives,
            "game_over": self.game_over,
            "players": [{
                "id": 1,
                "x": round(self.player["x"], 3),
                "z": round(self.player["z"], 3),
                "rot": round(self.player["rot"], 3),
                "held": self._item_json(held) if held else None,
                "captured": False,
            }],
            "appliances": appliances,
            "loose_items": [],
            "groups": [] if preparing else groups,
            "customers": [] if preparing else customers,
        }
        if preparing:
            # Levels copied from the recorded day 0 checklist: everything Safe
            # except consent, which is Error until given, and an open popup,
            # which is Error while it is up.
            frame["start_day_warnings"] = {
                "players_ready": self.ready,
                "popups_open": 3 if self.popup_until > 0.0 else 1,
                "selling_required_appliance": 1,
                "table_size": 1,
                "players_not_ready": 1 if self.ready else 3,
                "post_unopened": 1,
                "more_than_one_table": 1,
                "players_in_crane_mode": 1,
            }
        return frame

    # -- convenience ------------------------------------------------------

    @property
    def in_preparation(self):
        return self.phase == "preparation"

    @property
    def day_finished(self):
        if self.phase == "preparation":
            return False
        return (
            self.seconds >= self.day_length
            and not self.pending_arrivals
            and all(group.done for group in self.groups))

    def scoreboard(self):
        return {
            "served": self.served,
            "lost": self.lost,
            "ruined": self.ruined,
            "money": self.money,
            "lives": self.lives,
            "seconds": round(self.seconds, 1),
            "groups": len(self.groups),
            "pending": len(self.pending_arrivals),
            "game_over": self.game_over,
        }
