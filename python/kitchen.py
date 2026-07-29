r"""
Kitchen geometry: facing, reach, occupancy, routes, and approach poses.

Everything here is derived from published obs_0.1 fields plus two constants
read out of the game (`Player.CompleteJoining`). Nothing consults the bridge
for legality. The bridge states where things are; this module works out where
the chef has to stand and which way to point, which is the policy's problem,
not the bridge's.

Conventions, each settled from recorded artifacts by `python/facts.py`:

    rot = 0 faces +z, rot = 90 faces +x.
    Action MoveX is world +x and MoveY is world +z, unswapped and unflipped.
    OccupancyLayer.Default blocks the chef; OccupancyLayer.Floor does not.
    A group whose patience reason is no longer Seating stands exactly on its
    assigned table, which is the only usable way to locate that table because
    groups[].table names an entity the appliance query never publishes.
    Fixed appliances are destroyed and rebuilt when the day starts, so they
    are keyed by (game-data id, tile) rather than by entity id.

Reach model. `AttemptInteraction` projects an interaction point
`InteractionOffset` ahead of the chef along the movement vector, falling back
to the facing rotation when movement is neutral, and takes the nearest
interactive within `InteractionRadius` of that point. Both constants are 0.7,
so the furthest a target can be is 1.4, and a pose is only useful if the
intended target is also the *nearest* thing to the projected point.
"""

import heapq
import math

# Player.CompleteJoining, pinned build 1.4.3-FF8F.
INTERACTION_OFFSET = 0.7
INTERACTION_RADIUS = 0.7
MAX_REACH = INTERACTION_OFFSET + INTERACTION_RADIUS

# Plan poses inside the reach limit rather than on it. The furthest stance a
# tile-inset pose can produce is a diagonal one at 1.061, and the three
# recorded deliveries in runs/golden stood at 0.88, 0.91 and 1.02, so 1.10
# keeps every legal pose while leaving the whole remaining 0.34 as headroom
# for arrival error. `options.PRESS_REACH` is the matching press-time gate.
PLAN_REACH = 1.10

# How close to a tile edge the chef may stand. The furthest recorded delivery
# pose sat 0.22 units inside its tile, so a 0.25 inset reproduces a stance a
# human actually held rather than an idealised tile centre.
TILE_INSET = 0.25

# The intended target must beat every competitor by this margin at the
# projected interaction point, so a small control error cannot flip which
# entity `AttemptInteraction` selects.
AIM_MARGIN = 0.15

OCCUPANCY_DEFAULT = 0
OCCUPANCY_WALL = 1
OCCUPANCY_FLOOR = 2
OCCUPANCY_CEILING = 3

# Default-layer appliances the chef nonetheless walks through. Ghost chairs
# are the placement preview for a seat that does not exist yet. This is a
# prior, not a measurement: `Route` demotes any tile the chef demonstrably
# fails to enter, so a wrong entry here costs one replan rather than a stall.
WALKABLE_DEFAULT_LAYER = ("Ghost Chair",)

# Structure the chef can never enter and never interact with.
STRUCTURE = (
    "Wall Piece",
    "Internal Wall Piece",
    "Street Piece",
    "Outdoor Movement Blocker",
)

# Roles are a prior keyed on appliance name. `Kitchen.confirmed_roles` upgrades
# them from observation: an appliance that has been seen running a process is
# known to support it, whatever it is called.
ROLE_PATTERNS = (
    ("cook", ("Hob", "Oven", "Microwave")),
    ("wash", ("Sink", "Wash Basin", "Dish Washer")),
    ("dish_return", ("Dish Rack",)),
    ("bin", ("Bin - Starting", "Bin", "Compactor Bin", "Expanded Bin")),
    ("outdoor_bin", ("Wheelie Bin",)),
    ("surface", ("Countertop", "Counter", "Workstation", "Prep Station",
                 "Freezer", "Frozen Prep Station")),
    ("table", ("Table",)),
    ("chair", ("Chair",)),
    ("cabinet", ("Blueprint Cabinet",)),
    ("mess", ("Mess", "Mop Water")),
)

# Names that look like a role but are not that role.
ROLE_EXCLUSIONS = {
    "chair": ("Ghost Chair",),
    "table": ("Table Setting",),
}


# --------------------------------------------------------------------------
# scalar geometry
# --------------------------------------------------------------------------


def facing_vector(rot):
    """Unit (x, z) the chef points at for a Y-euler rotation in degrees."""
    radians = math.radians(rot)
    return math.sin(radians), math.cos(radians)


def heading_degrees(dx, dz):
    """Rotation, in degrees, that faces along (dx, dz)."""
    return math.degrees(math.atan2(dx, dz)) % 360.0


def angle_error(a, b):
    """Signed smallest difference between two headings, in degrees."""
    return (a - b + 180.0) % 360.0 - 180.0


def interaction_point(x, z, rot):
    """Where `AttemptInteraction` looks when the chef stands here."""
    ax, az = facing_vector(rot)
    return x + INTERACTION_OFFSET * ax, z + INTERACTION_OFFSET * az


def tile_of(x, z):
    return int(round(x)), int(round(z))


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def normalise(dx, dz):
    length = math.hypot(dx, dz)
    if length < 1e-9:
        return 0.0, 0.0
    return dx / length, dz / length


def clamp_to_tile(point, tile, inset=TILE_INSET):
    """Nearest stance inside a tile, keeping clear of its edges."""
    half = 0.5 - inset
    return (
        min(max(point[0], tile[0] - half), tile[0] + half),
        min(max(point[1], tile[1] - half), tile[1] + half),
    )


# --------------------------------------------------------------------------
# appliance helpers
# --------------------------------------------------------------------------


def slot_key(appliance):
    """Identity that survives the preparation-to-service entity rebuild."""
    return appliance.get("aid"), int(round(appliance["x"])), int(
        round(appliance["z"]))


def name_matches(name, patterns):
    return any(pattern in name for pattern in patterns)


def role_of(name):
    for role, patterns in ROLE_PATTERNS:
        if name_matches(name, ROLE_EXCLUSIONS.get(role, ())):
            continue
        if name_matches(name, patterns):
            return role
    return None


def is_structure(name):
    return name_matches(name, STRUCTURE)


def blocks_movement(appliance):
    """Does this appliance stop the chef entering its tile?"""
    if appliance.get("layer") != OCCUPANCY_DEFAULT:
        return False
    return not name_matches(appliance.get("name", ""), WALKABLE_DEFAULT_LAYER)


def is_interactive(appliance):
    """Can `AttemptInteraction` select this entity?

    Structure cannot. Floor-layer entities are excluded because they belong to
    a different interaction class (mopping) and have never been observed to
    steal a grab; that exclusion is an assumption, recorded here so a
    counterexample has somewhere to land.
    """
    name = appliance.get("name", "")
    if is_structure(name):
        return False
    if appliance.get("layer") != OCCUPANCY_DEFAULT:
        return False
    return not name_matches(name, WALKABLE_DEFAULT_LAYER)


# --------------------------------------------------------------------------
# poses
# --------------------------------------------------------------------------


class Pose:
    """Somewhere to stand and something to point at."""

    __slots__ = ("x", "z", "rot", "tile", "target", "reach", "clearance",
                 "aim_point")

    def __init__(self, x, z, rot, tile, target, reach, clearance, aim_point):
        self.x = x
        self.z = z
        self.rot = rot
        self.tile = tile
        self.target = target
        self.reach = reach
        self.clearance = clearance
        self.aim_point = aim_point

    def as_dict(self):
        return {
            "x": round(self.x, 3),
            "z": round(self.z, 3),
            "rot": round(self.rot, 2),
            "tile": list(self.tile),
            "reach": round(self.reach, 3),
            "clearance": round(self.clearance, 3),
        }

    def __repr__(self):
        return (f"Pose(({self.x:.2f}, {self.z:.2f}) rot {self.rot:.0f} "
                f"reach {self.reach:.2f} clearance {self.clearance:+.2f})")


# --------------------------------------------------------------------------
# kitchen
# --------------------------------------------------------------------------


class Kitchen:
    """A queryable view of one observation's layout.

    Rebuilt whenever the layout changes rather than mutated, because appliance
    entity ids are recycled at the day boundary and a cache keyed on them
    would silently point at the wrong slot.
    """

    def __init__(self, world, blocked_hints=()):
        self.world = world
        self.appliances = list(world.appliances)
        self.by_entity = {a["e"]: a for a in self.appliances}
        self.by_slot = {slot_key(a): a for a in self.appliances}

        self.blocked = set(blocked_hints)
        self.interactive = []
        self.roles = {}
        for appliance in self.appliances:
            name = appliance.get("name", "")
            tile = tile_of(appliance["x"], appliance["z"])
            if blocks_movement(appliance):
                self.blocked.add(tile)
            if is_interactive(appliance):
                self.interactive.append(appliance)
            role = role_of(name)
            if role:
                self.roles.setdefault(role, []).append(appliance)

        floors = [
            tile_of(a["x"], a["z"]) for a in self.appliances
            if not is_structure(a.get("name", ""))]
        if floors:
            self.min_x = min(t[0] for t in floors) - 2
            self.max_x = max(t[0] for t in floors) + 2
            self.min_z = min(t[1] for t in floors) - 2
            self.max_z = max(t[1] for t in floors) + 2
        else:
            self.min_x = self.min_z = -1
            self.max_x = self.max_z = 1

    # -- queries ----------------------------------------------------------

    def role(self, role):
        return list(self.roles.get(role, ()))

    def providers_of(self, item_name):
        """Appliances whose CItemProvider hands out this item."""
        return [
            a for a in self.appliances
            if a.get("provides_name") == item_name]

    def free(self, tile):
        if not (self.min_x <= tile[0] <= self.max_x
                and self.min_z <= tile[1] <= self.max_z):
            return False
        return tile not in self.blocked

    def occupant(self, tile):
        for appliance in self.appliances:
            if tile_of(appliance["x"], appliance["z"]) == tile and \
                    blocks_movement(appliance):
                return appliance
        return None

    def held_by(self, appliance):
        return appliance.get("held")

    def messes(self):
        return [
            a for a in self.appliances
            if a.get("layer") == OCCUPANCY_FLOOR
            and a.get("name", "").startswith("Mess")]

    def tables(self):
        """Dining tables, by name.

        `CTableSet` is emitted by the bridge but never appears, because the
        table-set entity is not in the appliance query. Name is therefore the
        only available classifier, and `groups[].x/z` is the only available
        group-to-table link.
        """
        return self.role("table")

    def table_for_group(self, group, seated_only=True):
        """The table a seated group occupies, located by its own position."""
        if seated_only and group.get("patience_reason") == 2:
            return None
        tables = self.tables()
        if not tables:
            return None
        nearest = min(
            tables,
            key=lambda a: (a["x"] - group["x"]) ** 2
            + (a["z"] - group["z"]) ** 2)
        if distance((nearest["x"], nearest["z"]),
                    (group["x"], group["z"])) > 0.5:
            return None
        return nearest

    def chairs_around(self, appliance):
        origin = (appliance["x"], appliance["z"])
        return [
            c for c in self.role("chair")
            if distance((c["x"], c["z"]), origin) <= 1.01]

    # -- routing ----------------------------------------------------------

    def route(self, start, goal, avoid=()):
        """Tile route from start to goal, or None.

        Eight-connected, but a diagonal step is only allowed when both of its
        orthogonal components are also free: the chef is a disc, and cutting a
        corner between two appliances wedges him.
        """
        start = tuple(start)
        goal = tuple(goal)
        if start == goal:
            return [start]
        if not self.free(goal):
            return None

        soft = set(avoid)
        open_heap = [(0.0, 0.0, start, None)]
        came = {}
        best = {start: 0.0}

        while open_heap:
            _priority, cost, tile, parent = heapq.heappop(open_heap)
            if tile in came:
                continue
            came[tile] = parent
            if tile == goal:
                path = []
                node = tile
                while node is not None:
                    path.append(node)
                    node = came[node]
                path.reverse()
                return path

            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (tile[0] + dx, tile[1] + dz)
                if nxt in came or not self.free(nxt):
                    continue
                if dx and dz:
                    if not self.free((tile[0] + dx, tile[1])) or \
                            not self.free((tile[0], tile[1] + dz)):
                        continue
                    step = 1.4142135623730951
                else:
                    step = 1.0
                if nxt in soft:
                    step += 3.0
                candidate = cost + step
                if candidate >= best.get(nxt, float("inf")):
                    continue
                best[nxt] = candidate
                estimate = _octile(nxt, goal)
                heapq.heappush(
                    open_heap, (candidate + estimate, candidate, nxt, tile))
        return None

    def reachable(self, start, goal, avoid=()):
        return self.route(start, goal, avoid) is not None

    # -- approach poses ---------------------------------------------------

    def approach_poses(self, target, from_point=None, avoid=(),
                       plan_reach=PLAN_REACH, extra_targets=()):
        """Every stance from which `target` is the interaction the game picks.

        `extra_targets` names entities that are an acceptable outcome as well,
        which is how table delivery is handled: two of the three recorded
        deliveries aimed at the table and one at the occupied chair beside it,
        and both put the plate on the table.
        """
        accepted = {target["e"]} | {a["e"] for a in extra_targets}
        goal = (target["x"], target["z"])
        centre = tile_of(*goal)
        origin = from_point
        if origin is None:
            me = self.world.me
            origin = (me["x"], me["z"]) if me else goal

        excluded = set(avoid)
        poses = []
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                tile = (centre[0] + dx, centre[1] + dz)
                if not self.free(tile) or tile in excluded:
                    continue
                stand = clamp_to_tile(goal, tile)
                reach = distance(stand, goal)
                if reach < 1e-6 or reach > plan_reach:
                    continue
                aim_x, aim_z = normalise(goal[0] - stand[0], goal[1] - stand[1])
                rot = heading_degrees(aim_x, aim_z)
                point = (stand[0] + INTERACTION_OFFSET * aim_x,
                         stand[1] + INTERACTION_OFFSET * aim_z)
                clearance = self.aim_clearance(point, accepted)
                if clearance <= AIM_MARGIN:
                    continue
                poses.append(Pose(stand[0], stand[1], rot, tile, target,
                                  reach, clearance, point))

        poses.sort(key=lambda p: (
            _octile(tile_of(*origin), p.tile), p.reach, -p.clearance))
        return poses

    def aim_clearance(self, point, accepted):
        """How much nearer the accepted target is than the best competitor.

        Positive means `AttemptInteraction` selects something in `accepted`.
        A competitor outside the interaction radius cannot be selected at all,
        so it is scored against the radius rather than against its own range.
        """
        best_accepted = float("inf")
        best_other = INTERACTION_RADIUS
        for appliance in self.interactive:
            gap = distance(point, (appliance["x"], appliance["z"]))
            if appliance["e"] in accepted:
                best_accepted = min(best_accepted, gap)
            elif gap < best_other:
                best_other = gap
        if best_accepted > INTERACTION_RADIUS:
            return -1.0
        return best_other - best_accepted

    def poses_by_route(self, target, from_point=None, soft=(), **kwargs):
        """Approach poses ordered by real route length; unroutable dropped.

        `approach_poses` orders by straight-line distance, which happily
        recommends a stance inside a pocket the chef cannot enter. There are
        never more than nine candidates, so routing all of them is cheap and
        removes a whole class of stuck options.
        """
        origin = from_point
        if origin is None:
            me = self.world.me
            if me is None:
                return []
            origin = (me["x"], me["z"])
        start = tile_of(*origin)

        scored = []
        for pose in self.approach_poses(target, from_point=origin, **kwargs):
            route = self.route(start, pose.tile, avoid=soft)
            if route is None:
                continue
            scored.append((len(route), pose.reach, -pose.clearance,
                           pose, route))
        scored.sort(key=lambda entry: entry[:3])
        return [(entry[3], entry[4]) for entry in scored]

    def best_pose(self, target, **kwargs):
        poses = self.approach_poses(target, **kwargs)
        return poses[0] if poses else None

    # -- diagnostics ------------------------------------------------------

    def describe(self):
        counts = {}
        for role, appliances in sorted(self.roles.items()):
            counts[role] = len(appliances)
        return {
            "appliances": len(self.appliances),
            "interactive": len(self.interactive),
            "blocked_tiles": len(self.blocked),
            "bounds": [self.min_x, self.max_x, self.min_z, self.max_z],
            "roles": counts,
        }

    def render(self, mark=()):
        """ASCII map. Debugging aid; not used by any decision."""
        marks = {tile_of(*m): "@" for m in mark}
        rows = []
        for z in range(self.max_z, self.min_z - 1, -1):
            row = []
            for x in range(self.min_x, self.max_x + 1):
                tile = (x, z)
                if tile in marks:
                    row.append(marks[tile])
                elif tile in self.blocked:
                    row.append("#")
                else:
                    row.append(".")
            rows.append("".join(row))
        return "\n".join(rows)


def _octile(a, b):
    dx = abs(a[0] - b[0])
    dz = abs(a[1] - b[1])
    return (dx + dz) + (1.4142135623730951 - 2) * min(dx, dz)
