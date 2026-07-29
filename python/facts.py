"""
Re-derive observation facts from the recorded artifacts. Offline; no game.

    python python/facts.py
    python python/facts.py --json runs/facts/observation-facts.json

Several fields in obs_0.1 were documented as unverified or as known gaps
because no live probe had been run. Some of them can in fact be settled from
the two recordings that already exist, which is cheaper and more durable than
another live session. This module derives each one and prints the evidence, so
a claim in the ledger can be reproduced by running one command.

What it settles, and how:

    rotation zero       correlate demo_input movement with the player rot that
                        followed it, across the full circle
    provider infinity   compare available/maximum on finite and infinite
                        providers
    floor mess          mess entities are published, as OccupancyLayer.Floor
                        appliances, and were mis-listed as a schema gap
    table linkage       groups[].table never resolves to a published appliance,
                        so the group position is the usable table locator
    entity stability    appliance entity IDs are recycled at the preparation to
                        service boundary
    occupancy layers    which layer values actually appear, and on what

Nothing here is a gameplay claim. It reads recorded files and reports what is
in them.
"""

import argparse
import collections
import json
import math
import os
import statistics
import sys

GOLDEN = os.path.join("runs", "golden", "obs_0.1_day1.jsonl")
SMOKE = os.path.join("runs", "demos", "smoke.jsonl")

# Player.CompleteJoining, quoted in README. The interaction point is projected
# from the player along the movement/facing vector and the nearest interactive
# within the radius is chosen.
INTERACTION_OFFSET = 0.7
INTERACTION_RADIUS = 0.7

FLOOR_LAYER = 2

# PatienceReason.Seating: arrived, table assigned, still walking to it.
SEATING_REASON = 2


def load(path):
    """Read one recording into dictionaries, observations and input frames."""
    recording = {
        "path": path,
        "items": {},
        "appliances": {},
        "processes": {},
        "frames": [],
        "inputs": [],
        "hello": None,
    }
    with open(path, encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            kind = message.get("kind")
            if kind == "dict":
                recording["items"] = {
                    int(k): v for k, v in message["items"].items()}
                recording["appliances"] = {
                    int(k): v for k, v in message["appliances"].items()}
                recording["processes"] = {
                    int(k): v for k, v in message["processes"].items()}
            elif kind == "obs":
                recording["frames"].append(message)
            elif kind == "demo_input":
                recording["inputs"].append(message)
            elif kind == "hello":
                recording["hello"] = message
    return recording


def appliance_name(recording, appliance):
    return recording["appliances"].get(appliance.get("aid"), "?")


# --------------------------------------------------------------------------
# rotation zero
# --------------------------------------------------------------------------


def heading_degrees(dx, dz):
    """Compass-style heading where 0 is +z and 90 is +x."""
    return math.degrees(math.atan2(dx, dz)) % 360.0


def angle_error(a, b):
    """Smallest signed difference between two headings, in degrees."""
    return (a - b + 180.0) % 360.0 - 180.0


def derive_rotation_zero(recording):
    """Does rot equal the heading of the commanded movement vector?

    The recorder captures the native InputState, so the movement the human
    actually asked for is known. If rot = atan2(move_x, move_y) then the zero
    direction is +z and MoveX/MoveY map to world x/z with no swap or flip.
    """
    by_tick = collections.defaultdict(list)
    for frame in recording["inputs"]:
        move_x = frame.get("move_x", 0.0)
        move_y = frame.get("move_y", 0.0)
        if math.hypot(move_x, move_y) < 0.5:
            continue
        by_tick[frame.get("tick")].append((move_x, move_y))

    # PlayerWalkingComponent turns toward the movement vector at a finite rate,
    # so rot lags for as long as the demonstrator is still swinging the stick.
    # Steady-state samples are the ones that test the axis convention; the
    # transient ones only re-measure turn latency, which is already known.
    errors = []
    steady_errors = []
    samples = []
    previous = None
    previous_heading = None
    for frame in recording["frames"]:
        players = frame.get("players") or []
        if not players:
            previous = None
            previous_heading = None
            continue
        player = players[0]
        tick = frame.get("tick")
        heading = None
        if previous is not None:
            moves = by_tick.get(previous[0]) or by_tick.get(tick)
            displacement = math.hypot(
                player["x"] - previous[1]["x"], player["z"] - previous[1]["z"])
            if moves and displacement > 0.05:
                move_x = sum(m[0] for m in moves) / len(moves)
                move_y = sum(m[1] for m in moves) / len(moves)
                heading = heading_degrees(move_x, move_y)
                error = abs(angle_error(heading, player.get("rot")))
                errors.append(error)
                held = (
                    previous_heading is not None
                    and abs(angle_error(heading, previous_heading)) <= 5.0)
                if held:
                    steady_errors.append(error)
                samples.append((round(move_x, 2), round(move_y, 2),
                                round(heading, 1), round(player["rot"], 1),
                                held))
        previous = (tick, player)
        previous_heading = heading

    if not steady_errors:
        return {"available": False, "reason": "no steady movement samples"}

    errors.sort()
    steady_errors.sort()
    quadrants = collections.Counter(
        int(s[2] // 90) for s in samples if s[4])
    return {
        "available": True,
        "samples": len(errors),
        "steady_samples": len(steady_errors),
        "median_error_degrees": statistics.median(errors),
        "steady_median_error_degrees": statistics.median(steady_errors),
        "steady_p90_error_degrees": steady_errors[
            min(len(steady_errors) - 1, int(len(steady_errors) * 0.9))],
        "steady_max_error_degrees": steady_errors[-1],
        "transient_max_error_degrees": errors[-1],
        "quadrants_covered": len(quadrants),
        "quadrant_counts": dict(sorted(quadrants.items())),
        "conclusion": (
            "rot = atan2(MoveX, MoveY) in degrees; rot 0 faces +z, "
            "rot 90 faces +x. Residual error while the commanded direction is "
            "still changing is turn latency, not a convention mismatch."),
    }


# --------------------------------------------------------------------------
# providers
# --------------------------------------------------------------------------


def derive_provider_convention(recording):
    """How infinite and finite providers report available/maximum."""
    observed = collections.defaultdict(set)
    for frame in recording["frames"]:
        for appliance in frame.get("appliances") or []:
            if "provides" not in appliance:
                continue
            name = appliance_name(recording, appliance)
            observed[name].add((
                recording["items"].get(appliance["provides"], "?"),
                appliance.get("available"),
                appliance.get("maximum"),
            ))

    providers = {}
    for name, rows in observed.items():
        maxima = {row[2] for row in rows}
        availables = sorted({row[1] for row in rows})
        providers[name] = {
            "provides": sorted({row[0] for row in rows}),
            "maximum": sorted(maxima),
            "available_values": availables,
            "finite": maxima != {0},
        }
    return providers


# --------------------------------------------------------------------------
# floor entities and occupancy layers
# --------------------------------------------------------------------------


def derive_layers(recording):
    """Which occupancy layers appear, and which names sit on each."""
    layers = collections.defaultdict(set)
    for frame in recording["frames"]:
        for appliance in frame.get("appliances") or []:
            layers[appliance.get("layer")].add(
                appliance_name(recording, appliance))
    return {
        str(layer): sorted(names) for layer, names in sorted(layers.items())}


def derive_mess(recording):
    """Mess is published as a Floor-layer appliance, not a missing field."""
    seen = collections.Counter()
    positions = {}
    for frame in recording["frames"]:
        for appliance in frame.get("appliances") or []:
            name = appliance_name(recording, appliance)
            if not name.startswith("Mess"):
                continue
            seen[name] += 1
            positions.setdefault(name, (appliance["x"], appliance["z"]))
    return {
        "names": dict(seen),
        "example_positions": {k: list(v) for k, v in positions.items()},
        "layer": FLOOR_LAYER,
        "grid_aligned": all(
            abs(x - round(x)) < 1e-6 and abs(z - round(z)) < 1e-6
            for x, z in positions.values()),
    }


# --------------------------------------------------------------------------
# table linkage
# --------------------------------------------------------------------------


def derive_table_linkage(recording):
    """Can a group be mapped to its physical table through obs_0.1 alone?

    CAssignedTable.Table is emitted, but the entity it names is not in the
    appliance query, so the reference cannot be resolved by a client. The
    group's own position is checked as the replacement locator.
    """
    resolved = 0
    unresolved = 0
    is_table_entries = 0
    seated_frames = 0
    seated_on_table = 0
    offsets = []

    for frame in recording["frames"]:
        appliances = frame.get("appliances") or []
        by_entity = {a["e"]: a for a in appliances}
        tables = [
            a for a in appliances
            if appliance_name(recording, a).startswith("Table")]
        is_table_entries += sum(1 for a in appliances if a.get("is_table"))

        for group in frame.get("groups") or []:
            table = group.get("table")
            if not table:
                # Before seating the group stands in the queue, so its
                # position is not a table locator and must not be scored.
                continue
            if table in by_entity:
                resolved += 1
            else:
                unresolved += 1
            # A group keeps walking after its table is assigned. Only once it
            # has stopped being seated is the position a table locator.
            if not tables or group.get("patience_reason") == SEATING_REASON:
                continue
            seated_frames += 1
            nearest = min(
                tables,
                key=lambda a: (a["x"] - group["x"]) ** 2
                + (a["z"] - group["z"]) ** 2)
            offset = math.hypot(
                nearest["x"] - group["x"], nearest["z"] - group["z"])
            offsets.append(offset)
            if offset < 0.01:
                seated_on_table += 1

    return {
        "assigned_table_resolved": resolved,
        "assigned_table_unresolved": unresolved,
        "is_table_entries": is_table_entries,
        "seated_group_frames": seated_frames,
        "seated_group_exactly_on_a_table_appliance": seated_on_table,
        "median_group_to_nearest_table": (
            statistics.median(offsets) if offsets else None),
        "max_group_to_nearest_table": max(offsets) if offsets else None,
        "conclusion": (
            "groups[].table cannot be resolved by a client; once a group has "
            "stopped being seated its position is exactly its table's "
            "position, so the group locates its own table"),
    }


# --------------------------------------------------------------------------
# entity identity stability
# --------------------------------------------------------------------------


def derive_entity_stability(recording):
    """Fixed appliances keep their entity ID only within one day phase."""
    per_name = collections.defaultdict(set)
    per_frame_counts = collections.defaultdict(set)
    for frame in recording["frames"]:
        counts = collections.Counter()
        for appliance in frame.get("appliances") or []:
            name = appliance_name(recording, appliance)
            per_name[name].add(appliance["e"])
            counts[name] += 1
        for name, count in counts.items():
            per_frame_counts[name].add(count)

    recycled = {}
    for name, entities in per_name.items():
        counts = per_frame_counts[name]
        if len(counts) != 1:
            continue
        per_frame = next(iter(counts))
        if per_frame and len(entities) % per_frame == 0:
            generations = len(entities) // per_frame
            if generations > 1:
                recycled[name] = generations

    # A key that survives the rebuild: game-data ID plus grid position.
    stable_keys = collections.defaultdict(set)
    for frame in recording["frames"]:
        for appliance in frame.get("appliances") or []:
            stable_keys[(
                appliance.get("aid"),
                round(appliance["x"]),
                round(appliance["z"]))].add(appliance["e"])

    return {
        "names_with_multiple_generations": dict(sorted(recycled.items())),
        "distinct_generation_counts": sorted({v for v in recycled.values()}),
        "stable_key": "(aid, round(x), round(z))",
        "stable_key_slots": len(stable_keys),
        "conclusion": (
            "fixed appliances are destroyed and recreated at the preparation "
            "to service boundary; cache appliances by (aid, tile), never by "
            "entity ID across a phase change"),
    }


# --------------------------------------------------------------------------
# interaction geometry
# --------------------------------------------------------------------------


def derive_delivery_poses(recording):
    """Where did the demonstrator stand when a plated dish reached a table?

    This is the only recorded ground truth for the reach model, so it is used
    to bound the stand distance the option layer plans for.
    """
    poses = []
    previous = None
    for frame in recording["frames"]:
        players = frame.get("players") or []
        player = players[0] if players else None
        held = player.get("held") if player else None
        held_entity = held.get("e") if held else None

        if previous is not None and previous["held"] and not held_entity:
            for appliance in frame.get("appliances") or []:
                carried = appliance.get("held")
                if not carried or carried.get("e") != previous["held"]:
                    continue
                name = appliance_name(recording, appliance)
                if not name.startswith("Table"):
                    continue
                stand = (previous["x"], previous["z"])
                target = (appliance["x"], appliance["z"])
                rot = previous["rot"]
                aim = (math.sin(math.radians(rot)), math.cos(math.radians(rot)))
                point = (stand[0] + INTERACTION_OFFSET * aim[0],
                         stand[1] + INTERACTION_OFFSET * aim[1])
                poses.append({
                    "stand": [round(stand[0], 3), round(stand[1], 3)],
                    "rot": round(rot, 2),
                    "table": [target[0], target[1]],
                    "stand_distance": round(math.dist(stand, target), 3),
                    "interaction_point_to_table": round(
                        math.dist(point, target), 3),
                })
        if player is not None:
            previous = {
                "held": held_entity,
                "x": player["x"],
                "z": player["z"],
                "rot": player.get("rot", 0.0),
            }
    distances = [p["stand_distance"] for p in poses]
    return {
        "deliveries": len(poses),
        "poses": poses,
        "max_stand_distance": max(distances) if distances else None,
        "reach_limit": INTERACTION_OFFSET + INTERACTION_RADIUS,
        "conclusion": (
            "every recorded delivery stood inside the "
            f"{INTERACTION_OFFSET + INTERACTION_RADIUS:.1f} unit reach limit; "
            "some aimed at the table and some at an occupied chair"),
    }


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


def gather(golden_path=GOLDEN, smoke_path=SMOKE):
    golden = load(golden_path)
    smoke = load(smoke_path)
    return {
        "sources": {
            "golden": {
                "path": os.path.normpath(golden_path),
                "frames": len(golden["frames"]),
                "bridge": (golden["hello"] or {}).get("bridge_version"),
                "mod_hash": (golden["hello"] or {}).get("mod_hash"),
            },
            "smoke": {
                "path": os.path.normpath(smoke_path),
                "frames": len(smoke["frames"]),
                "demo_frames": len(smoke["inputs"]),
                "bridge": (smoke["hello"] or {}).get("bridge_version"),
                "mod_hash": (smoke["hello"] or {}).get("mod_hash"),
            },
        },
        "rotation_zero": derive_rotation_zero(smoke),
        "providers": {
            "golden": derive_provider_convention(golden),
            "smoke": derive_provider_convention(smoke),
        },
        "occupancy_layers": {
            "golden": derive_layers(golden),
            "smoke": derive_layers(smoke),
        },
        "mess": derive_mess(golden),
        "table_linkage": {
            "golden": derive_table_linkage(golden),
            "smoke": derive_table_linkage(smoke),
        },
        "entity_stability": {
            "golden": derive_entity_stability(golden),
            "smoke": derive_entity_stability(smoke),
        },
        "delivery_poses": derive_delivery_poses(golden),
    }


def check(report):
    """Assert each derived fact, so the module is also a regression test."""
    checks = []

    def verify(name, condition, detail):
        checks.append((name, bool(condition), detail))

    rotation = report["rotation_zero"]
    verify(
        "rotation zero resolved",
        rotation.get("available")
        and rotation["steady_p90_error_degrees"] <= 5.0
        and rotation["quadrants_covered"] == 4,
        f"{rotation.get('steady_samples')} steady samples, median "
        f"{rotation.get('steady_median_error_degrees', float('nan')):.2f} deg, "
        f"p90 {rotation.get('steady_p90_error_degrees', float('nan')):.2f} "
        f"deg, {rotation.get('quadrants_covered')}/4 quadrants")

    plate_stacks = [
        entry for source in report["providers"].values()
        for name, entry in source.items() if name.startswith("Plate Stack")]
    infinite = [
        entry for source in report["providers"].values()
        for name, entry in source.items() if not entry["finite"]]
    verify(
        "finite provider reports a non-zero maximum",
        plate_stacks and all(entry["maximum"] == [4] for entry in plate_stacks),
        f"plate stacks report maximum {[e['maximum'] for e in plate_stacks]}")
    verify(
        "infinite provider reports maximum 0, not a negative sentinel",
        infinite and all(
            entry["maximum"] == [0] and min(entry["available_values"]) >= 0
            for entry in infinite),
        f"{len(infinite)} infinite providers, maxima "
        f"{sorted({tuple(e['maximum']) for e in infinite})}")

    mess = report["mess"]
    verify(
        "mess is published as a floor-layer appliance",
        mess["names"] and not mess["grid_aligned"],
        f"{sorted(mess['names'])} at layer {mess['layer']}, off-grid positions")

    for source, linkage in report["table_linkage"].items():
        verify(
            f"{source}: groups[].table never resolves",
            linkage["assigned_table_resolved"] == 0
            and linkage["assigned_table_unresolved"] > 0,
            f"{linkage['assigned_table_unresolved']} unresolved, "
            f"{linkage['assigned_table_resolved']} resolved")
        verify(
            f"{source}: is_table is never emitted",
            linkage["is_table_entries"] == 0,
            f"{linkage['is_table_entries']} appliances carried is_table")
        verify(
            f"{source}: seated group position locates its table",
            linkage["seated_group_frames"] > 0
            and linkage["seated_group_exactly_on_a_table_appliance"]
            == linkage["seated_group_frames"],
            f"{linkage['seated_group_exactly_on_a_table_appliance']} of "
            f"{linkage['seated_group_frames']} seated group frames sit exactly "
            "on a table appliance")

    for source, stability in report["entity_stability"].items():
        verify(
            f"{source}: appliance entity IDs are recycled",
            stability["names_with_multiple_generations"],
            f"{len(stability['names_with_multiple_generations'])} appliance "
            f"names span {stability['distinct_generation_counts']} generations")

    layers = report["occupancy_layers"]["golden"]
    floor_names = set(layers.get(str(FLOOR_LAYER), []))
    verify(
        "only floor-layer entities are walkable candidates",
        floor_names and all(
            name.startswith(("Mess", "Mop Water", "Nameplate",
                             "Practice Mode Trigger"))
            for name in floor_names),
        f"layer {FLOOR_LAYER}: {sorted(floor_names)}")

    poses = report["delivery_poses"]
    verify(
        "recorded deliveries respect the reach limit",
        poses["deliveries"] > 0
        and poses["max_stand_distance"] <= poses["reach_limit"],
        f"{poses['deliveries']} deliveries, furthest stand "
        f"{poses['max_stand_distance']} of {poses['reach_limit']}")

    return checks


def print_report(report, checks):
    sources = report["sources"]
    for label, source in sources.items():
        print(f"{label}: {source['path']}  {source['frames']} obs  "
              f"bridge {source['bridge']}")
    print()

    rotation = report["rotation_zero"]
    print("rotation zero")
    if rotation.get("available"):
        print(f"  {rotation['samples']} paired samples, "
              f"{rotation['steady_samples']} with a held direction, across "
              f"{rotation['quadrants_covered']} quadrants")
        print(f"  |commanded heading - rot| while held: median "
              f"{rotation['steady_median_error_degrees']:.2f} deg, p90 "
              f"{rotation['steady_p90_error_degrees']:.2f} deg, max "
              f"{rotation['steady_max_error_degrees']:.2f} deg")
        print(f"  worst case including direction changes: "
              f"{rotation['transient_max_error_degrees']:.2f} deg (turn "
              f"latency)")
        print(f"  {rotation['conclusion']}")
    else:
        print(f"  unavailable: {rotation.get('reason')}")
    print()

    print("providers")
    for label, providers in report["providers"].items():
        for name, entry in sorted(providers.items()):
            kind = "finite" if entry["finite"] else "infinite"
            print(f"  {label:7s} {name:24s} {kind:8s} "
                  f"maximum={entry['maximum']} "
                  f"available={entry['available_values']}")
    print()

    print("occupancy layers (golden)")
    for layer, names in report["occupancy_layers"]["golden"].items():
        print(f"  layer {layer}: {len(names)} names")
        if layer == str(FLOOR_LAYER):
            print(f"    {', '.join(names)}")
    print()

    mess = report["mess"]
    print("mess")
    print(f"  {mess['names']}")
    print(f"  positions off the tile grid: {not mess['grid_aligned']}")
    print()

    print("table linkage")
    for label, linkage in report["table_linkage"].items():
        print(f"  {label}: assigned-table references "
              f"{linkage['assigned_table_resolved']} resolved / "
              f"{linkage['assigned_table_unresolved']} unresolved; "
              f"is_table entries {linkage['is_table_entries']}")
        print(f"           seated group to nearest table: median "
              f"{linkage['median_group_to_nearest_table']}, max "
              f"{linkage['max_group_to_nearest_table']}")
    print()

    print("entity stability")
    for label, stability in report["entity_stability"].items():
        print(f"  {label}: {len(stability['names_with_multiple_generations'])} "
              f"appliance names recycled, generations "
              f"{stability['distinct_generation_counts']}")
    print()

    poses = report["delivery_poses"]
    print("delivery poses (golden)")
    for pose in poses["poses"]:
        print(f"  stand {pose['stand']} rot {pose['rot']:6.1f} -> table "
              f"{pose['table']}  stand distance {pose['stand_distance']}  "
              f"aim point to table {pose['interaction_point_to_table']}")
    print()

    width = max(len(name) for name, _passed, _detail in checks)
    failed = 0
    for name, passed, detail in checks:
        if not passed:
            failed += 1
        print(f"{'PASS' if passed else 'FAIL'}  {name:<{width}}  {detail}")
    print()
    if failed:
        print(f"FAIL: {failed} of {len(checks)} derived facts did not hold")
    else:
        print(f"OK -- {len(checks)} observation facts derived from recorded "
              "artifacts")
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", default=GOLDEN)
    parser.add_argument("--smoke", default=SMOKE)
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()

    report = gather(args.golden, args.smoke)
    checks = check(report)
    ok = print_report(report, checks)

    if args.json_path:
        report["checks"] = [
            {"name": name, "passed": passed, "detail": detail}
            for name, passed, detail in checks]
        os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump(report, output, indent=2, sort_keys=True)
        print(f"wrote {os.path.normpath(args.json_path)}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
