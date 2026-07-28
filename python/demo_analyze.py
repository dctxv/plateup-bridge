"""
Offline analysis of recorded demonstrations for the recipe benchmark.

The procedure, metrics, and decision rule are fixed by
docs/recipe-benchmark-protocol.md. This module implements that document and
deliberately exposes no threshold or weighting arguments: the rule belongs to
the protocol, not to the invocation.

Analyse one recording:
    python python/demo_analyze.py session runs/demos/burger/day1-01.jsonl
    python python/demo_analyze.py session runs/demos/burger/day1-01.jsonl \
        --json runs/benchmark/burger-day1-01.json

Decide the benchmark over two directories of recordings:
    python python/demo_analyze.py benchmark runs/demos/burger runs/demos/steak

Self-check the analyzer against existing artifacts (no game required):
    python python/demo_analyze.py validate

Reads only. Nothing here connects to the bridge or needs PlateUp running.
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

DEMO_SCHEMA = "demo_0.1"
OBS_SCHEMA = "obs_0.1"

# Protocol section 5.
MARGIN = 0.15
MINIMUM_SESSIONS_PER_ARM = 6

# Observations publish every 6th simulation tick, so two observation intervals
# is 12 ticks. An interaction that has produced no visible change within two
# intervals is recorded as null rather than attributed to a later change.
INTERACTION_WINDOW_TICKS = 12

# A plated dish identifies the recipe. Steak has card variants (Boned, Thick,
# Thin) that are still the steak chain.
RECIPE_PATTERNS = (
    ("burger", re.compile(r"^Burger - ")),
    ("steak", re.compile(r"^(?:Boned |Thick |Thin )?Steak - ")),
)

# Burgers have no named burned variant; an overcooked patty becomes the generic
# "Burned Food". Matching the word keeps the two arms symmetric.
RUINED_PATTERN = re.compile(r"burn", re.IGNORECASE)

# Steak doneness states, in chain order. Rare and Medium are the intended
# results; Well-done is servable but sets is_bad, and Burned is ruined.
DONENESS_PATTERN = re.compile(r"\b(Rare|Medium|Well-done|Burned)$")

BUTTON_PRESSED = 3


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def _item_summary(item):
    """Reduce an item object to the fields the metrics need."""
    return {
        "iid": item.get("iid"),
        "process": item.get("process"),
        "progress": item.get("progress"),
        "is_bad": bool(item.get("is_bad")),
        "components": tuple(item.get("items") or ()),
    }


def _summarise_observation(message):
    """Keep only what the metrics read.

    Full frames carry roughly a hundred appliances each. A full day at 10 Hz
    would hold hundreds of thousands of appliance dictionaries in memory for no
    benefit, so appliances are reduced here to the items they hold plus the
    table facts the layout check needs.
    """
    items = {}
    holders = {}
    player_held = {}
    tables = []

    for player in message.get("players") or []:
        held = player.get("held")
        player_id = player.get("id")
        if held is None:
            player_held[player_id] = None
            continue
        entity = held.get("e")
        player_held[player_id] = entity
        items[entity] = _item_summary(held)
        holders[entity] = ("player", player_id)

    for appliance in message.get("appliances") or []:
        if appliance.get("is_table"):
            tables.append((appliance.get("e"), appliance.get("chairs")))
        held = appliance.get("held")
        if held is None:
            continue
        entity = held.get("e")
        items[entity] = _item_summary(held)
        holders[entity] = ("appliance", appliance.get("e"))

    for loose in message.get("loose_items") or []:
        entity = loose.get("e")
        items[entity] = _item_summary(loose)
        holders[entity] = ("loose", None)

    groups = {}
    for group in message.get("groups") or []:
        total = group.get("patience_total") or 0.0
        left = group.get("patience_left")
        groups[group.get("e")] = {
            "size": group.get("size"),
            "phase": group.get("meal_phase"),
            "patience_frac": (
                left / total if total and left is not None else None),
            "orders": [
                (
                    order.get("member"),
                    order.get("iid"),
                    bool(order.get("is_side")),
                    bool(order.get("satisfied")),
                    order.get("reward"),
                )
                for order in group.get("orders") or []
            ],
        }

    return {
        "tick": message.get("tick"),
        "day": message.get("day"),
        "seconds": message.get("seconds_elapsed"),
        "day_length": message.get("day_length"),
        "unbounded": message.get("time_unbounded"),
        "money": message.get("money"),
        "lives": message.get("lives"),
        "paused": bool(message.get("paused")),
        "override": bool(message.get("override")),
        "speed": message.get("game_speed"),
        "practice": bool(message.get("practice_mode")),
        "in_restaurant": bool(message.get("in_restaurant")),
        "captured": bool(message.get("input_captured")),
        "game_over": bool(message.get("game_over")),
        "player_held": player_held,
        "items": items,
        "holders": holders,
        "groups": groups,
        "tables": tables,
    }


def load(path):
    """Stream one recording into compact per-frame summaries."""
    recording = {
        "path": path,
        "manifest": None,
        "hello": None,
        "dictionary": None,
        "frames": [],
        "edges": [],
        "demo_frames": 0,
        "demo_status_enabled": False,
        "unknown_kinds": Counter(),
    }

    with open(path, encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}: invalid JSON on line {line_number}: {exc}")

            kind = message.get("kind")
            if kind == "manifest":
                recording["manifest"] = message
            elif kind == "hello":
                recording["hello"] = message
            elif kind == "dict":
                recording["dictionary"] = message
            elif kind == "obs":
                recording["frames"].append(_summarise_observation(message))
            elif kind == "demo_status":
                if message.get("enabled"):
                    recording["demo_status_enabled"] = True
            elif kind == "demo_input":
                recording["demo_frames"] += 1
                for field in ("grab", "interact"):
                    if message.get(field) == BUTTON_PRESSED:
                        recording["edges"].append({
                            "tick": message.get("tick"),
                            "button": field,
                            "player": message.get("player"),
                            "seq": message.get("seq"),
                        })
            else:
                recording["unknown_kinds"][kind] += 1

    return recording


def item_names(recording):
    dictionary = recording.get("dictionary") or {}
    return dictionary.get("items") or {}


def name_of(names, iid):
    if iid is None:
        return None
    return names.get(str(iid))


# --------------------------------------------------------------------------
# recipe derivation
# --------------------------------------------------------------------------


def classify_dish(name):
    if not name:
        return None
    for token, pattern in RECIPE_PATTERNS:
        if pattern.search(name):
            return token
    return None


def derive_recipe(recording):
    """Derive the recipe from what customers actually ordered.

    The --recipe flag is free text typed at the command line and is therefore
    not evidence. Protocol section 4.5 requires the recipe to come from the
    ordered item IDs instead, with the flag used only as a cross-check.
    """
    names = item_names(recording)
    mains = Counter()
    sides = Counter()

    for frame in recording["frames"]:
        for group in frame["groups"].values():
            for _member, iid, is_side, _satisfied, _reward in group["orders"]:
                name = name_of(names, iid)
                if name is None:
                    continue
                (sides if is_side else mains)[name] += 1

    tokens = {classify_dish(name) for name in mains}
    tokens.discard(None)

    if not mains:
        derived = "unknown"
    elif len(tokens) == 1:
        derived = tokens.pop()
    elif tokens:
        derived = "mixed"
    else:
        derived = "unrecognised"

    declared = ((recording.get("manifest") or {})
                .get("metadata") or {}).get("recipe")

    return {
        "derived": derived,
        "declared": declared,
        "matches": derived == declared,
        "main_dishes": dict(mains),
        "side_dishes": dict(sides),
    }


# --------------------------------------------------------------------------
# order and service metrics
# --------------------------------------------------------------------------


def analyse_service(recording):
    """Track orders, satisfaction, service slack, and ruined items.

    Orders are keyed by (group, buffer index) because the schema states nested
    buffers preserve their game-provided order and courses append to the
    buffer. Identity drift on a key is counted rather than assumed away.
    """
    names = item_names(recording)

    orders = {}
    order_identity_changes = 0
    order_entry_frames = 0
    satisfaction_transitions = 0
    slack_at_first_delivery = []

    groups_seen = {}
    group_last_patience = {}
    group_minimum_patience = {}
    group_delivered = set()
    live_groups = set()
    order_latencies = []

    ruined_items = {}
    at_risk_items = set()
    served_doneness = Counter()

    # Item-seconds spent undergoing any process. Concurrent processes are
    # counted separately on purpose: parallelising two hobs is demonstrator
    # skill, and the metric is meant to price the recipe, not the player.
    process_item_seconds = 0.0
    previous_seconds = None

    service_frames = 0
    first_service_seconds = None
    last_service_seconds = None
    money_start = None
    money_end = None
    lives_end = None

    for frame in recording["frames"]:
        in_service = frame["day"] is not None and frame["day"] >= 1
        if in_service:
            service_frames += 1
            if frame["seconds"] is not None:
                if first_service_seconds is None:
                    first_service_seconds = frame["seconds"]
                last_service_seconds = frame["seconds"]
            if money_start is None:
                money_start = frame["money"]
            money_end = frame["money"]
            if frame["lives"] is not None:
                lives_end = frame["lives"]

        # Elapsed service time since the previous frame. Guarded against the
        # day rollover, which resets seconds_elapsed to zero.
        delta = 0.0
        if frame["seconds"] is not None:
            if previous_seconds is not None and frame["seconds"] >= previous_seconds:
                delta = frame["seconds"] - previous_seconds
            previous_seconds = frame["seconds"]

        # Ruined items and doneness, counted once per item entity.
        for entity, item in frame["items"].items():
            if item["process"] is not None:
                process_item_seconds += delta
            name = name_of(names, item["iid"])
            if name and RUINED_PATTERN.search(name):
                ruined_items.setdefault(entity, name)
            if item["is_bad"]:
                at_risk_items.add(entity)
            for component in item["components"]:
                component_name = name_of(names, component)
                if component_name:
                    match = DONENESS_PATTERN.search(component_name)
                    if match:
                        served_doneness[match.group(1)] += 1

        current_groups = set(frame["groups"])
        departed = live_groups - current_groups
        for group_entity in departed:
            live_groups.discard(group_entity)
        live_groups |= current_groups

        for group_entity, group in frame["groups"].items():
            groups_seen.setdefault(group_entity, group["size"])

            for index, entry in enumerate(group["orders"]):
                member, iid, is_side, satisfied, reward = entry
                order_entry_frames += 1
                key = (group_entity, index)
                record = orders.get(key)
                if record is None:
                    record = {
                        "group": group_entity,
                        "member": member,
                        "iid": iid,
                        "name": name_of(names, iid),
                        "is_side": is_side,
                        "reward": reward,
                        "satisfied": satisfied,
                        "ever_satisfied": satisfied,
                        "first_seen": frame["seconds"],
                    }
                    orders[key] = record
                else:
                    if (record["member"], record["iid"], record["is_side"]) != (
                        member, iid, is_side
                    ):
                        order_identity_changes += 1
                        record["member"] = member
                        record["iid"] = iid
                        record["name"] = name_of(names, iid)
                        record["is_side"] = is_side
                    if satisfied and not record["satisfied"]:
                        satisfaction_transitions += 1
                        record["ever_satisfied"] = True
                        if (
                            record["first_seen"] is not None
                            and frame["seconds"] is not None
                        ):
                            order_latencies.append(
                                frame["seconds"] - record["first_seen"])
                        if group_entity not in group_delivered:
                            group_delivered.add(group_entity)
                            # Patience resets to full on the first delivery, so
                            # the slack that mattered is the previous frame's.
                            previous = group_last_patience.get(group_entity)
                            if previous is not None:
                                slack_at_first_delivery.append(previous)
                    record["satisfied"] = satisfied
                    record["ever_satisfied"] = (
                        record["ever_satisfied"] or satisfied)

            if group["patience_frac"] is not None:
                group_last_patience[group_entity] = group["patience_frac"]
                group_minimum_patience[group_entity] = min(
                    group_minimum_patience.get(group_entity, 1.0),
                    group["patience_frac"])

    unsatisfied = [
        record for record in orders.values() if not record["ever_satisfied"]]
    completed = [
        record for record in orders.values() if record["ever_satisfied"]]

    attempted = len(orders)
    failures = len(ruined_items) + len(unsatisfied)

    service_seconds = None
    if first_service_seconds is not None and last_service_seconds is not None:
        service_seconds = max(0.0, last_service_seconds - first_service_seconds)

    return {
        "groups": len(groups_seen),
        "group_sizes": dict(Counter(
            size for size in groups_seen.values() if size is not None)),
        "orders_attempted": attempted,
        "orders_completed": len(completed),
        "orders_unsatisfied": len(unsatisfied),
        "order_entry_frames": order_entry_frames,
        "order_identity_changes": order_identity_changes,
        "satisfaction_transitions": satisfaction_transitions,
        "ruined_items": len(ruined_items),
        "ruined_item_names": dict(Counter(ruined_items.values())),
        "at_risk_items": len(at_risk_items),
        "served_doneness": dict(served_doneness),
        "failure_events": failures,
        "failure_rate": (failures / attempted) if attempted else None,
        "process_item_seconds": process_item_seconds,
        "process_seconds_per_meal": (
            process_item_seconds / len(completed) if completed else None),
        # Both of the following saturate on day 1 and are reported as
        # diagnostics only. See docs/recipe-benchmark-protocol.md section 4.2.
        "service_slack": (
            statistics.median(slack_at_first_delivery)
            if slack_at_first_delivery else None),
        "slack_samples": len(slack_at_first_delivery),
        "minimum_patience": (
            statistics.median(group_minimum_patience.values())
            if group_minimum_patience else None),
        "order_latency": (
            statistics.median(order_latencies) if order_latencies else None),
        "service_frames": service_frames,
        "service_seconds": service_seconds,
        "meals_per_service_minute": (
            len(completed) / (service_seconds / 60.0)
            if service_seconds else None),
        "money_start": money_start,
        "money_end": money_end,
        "lives_end": lives_end,
    }


# --------------------------------------------------------------------------
# interaction segmentation
# --------------------------------------------------------------------------


def _classify_change(before, after, player):
    """Name the observable change a Pressed edge produced, if any."""
    held_before = before["player_held"].get(player)
    held_after = after["player_held"].get(player)

    if held_before is None and held_after is not None:
        return "pickup"
    if held_before is not None and held_after is None:
        return "place"
    if (
        held_before is not None
        and held_after is not None
        and held_before != held_after
    ):
        return "swap"

    for entity, item in after["items"].items():
        previous = before["items"].get(entity)
        if item["process"] is not None and (
            previous is None or previous["process"] is None
        ):
            return "process_start"
        if (
            previous is not None
            and item["process"] is not None
            and previous["process"] == item["process"]
            and item["progress"] is not None
            and previous["progress"] is not None
            and item["progress"] > previous["progress"]
        ):
            return "process_advance"
        if previous is not None and previous["iid"] != item["iid"]:
            return "transform"

    return None


def analyse_interactions(recording):
    """Pair Pressed edges with the observation change that followed them.

    Native input is sampled at render cadence and observations at simulation
    cadence, so an edge is matched to the first observation after it within the
    window. Edges with no visible effect are kept as null interactions: a human
    misfire is real difficulty signal, and filtering it would flatter whichever
    recipe is harder to aim in.
    """
    frames = recording["frames"]
    if not frames:
        return {"available": False, "reason": "no observations"}
    if not recording["edges"]:
        return {
            "available": False,
            "reason": "no demo_input Pressed edges (observation-only file)",
        }

    ticks = [frame["tick"] for frame in frames]
    classified = Counter()
    unresolved = 0
    ambiguous = 0
    total = 0

    # Player IDs differ between the two streams: demo_input carries a native
    # device source ID while observations carry CPlayer.ID. Solo recordings have
    # exactly one observed player, so changes are attributed to it.
    observed_players = set()
    for frame in frames:
        observed_players |= set(frame["player_held"])
    solo_player = (
        next(iter(observed_players)) if len(observed_players) == 1 else None)

    previous_edge_tick = None
    for edge in recording["edges"]:
        tick = edge["tick"]
        if tick is None:
            unresolved += 1
            continue
        total += 1

        before_index = _last_index_at_or_before(ticks, tick)
        after_index = _first_index_after(ticks, tick)
        if before_index is None or after_index is None:
            unresolved += 1
            previous_edge_tick = tick
            continue
        if ticks[after_index] - tick > INTERACTION_WINDOW_TICKS:
            classified["null_interaction"] += 1
            previous_edge_tick = tick
            continue

        if (
            previous_edge_tick is not None
            and tick - previous_edge_tick <= INTERACTION_WINDOW_TICKS
        ):
            ambiguous += 1

        change = _classify_change(
            frames[before_index], frames[after_index], solo_player)
        classified[change or "null_interaction"] += 1
        previous_edge_tick = tick

    effective = total - classified["null_interaction"]
    return {
        "available": True,
        "pressed_edges": len(recording["edges"]),
        "paired": total,
        "unresolved": unresolved,
        "ambiguous_window": ambiguous,
        "classified": dict(classified),
        "null_interactions": classified["null_interaction"],
        "null_rate": (
            classified["null_interaction"] / total if total else None),
        "effective_interactions": effective,
        "solo_player_attribution": solo_player is not None,
    }


def _last_index_at_or_before(ticks, tick):
    low, high = 0, len(ticks) - 1
    found = None
    while low <= high:
        middle = (low + high) // 2
        if ticks[middle] <= tick:
            found = middle
            low = middle + 1
        else:
            high = middle - 1
    return found


def _first_index_after(ticks, tick):
    low, high = 0, len(ticks) - 1
    found = None
    while low <= high:
        middle = (low + high) // 2
        if ticks[middle] > tick:
            found = middle
            high = middle - 1
        else:
            low = middle + 1
    return found


# --------------------------------------------------------------------------
# session acceptance
# --------------------------------------------------------------------------


def check_acceptance(recording, service, recipe):
    """Apply the protocol section 3 conditions to one recording."""
    frames = recording["frames"]
    problems = []
    notes = []

    manifest = recording.get("manifest") or {}
    hello = recording.get("hello") or {}
    if manifest.get("recording") != "human_demonstration":
        problems.append("not a human demonstration recording")
    if recording["dictionary"] is None:
        problems.append("missing name dictionary")
    if hello.get("obs_schema") != OBS_SCHEMA:
        problems.append(f"obs_schema={hello.get('obs_schema')!r}")
    if hello.get("demo_schema") != DEMO_SCHEMA:
        problems.append(f"demo_schema={hello.get('demo_schema')!r}")
    if not frames:
        problems.append("no observations")
        return {"accepted": False, "problems": problems, "notes": notes}

    if any(frame["override"] for frame in frames):
        problems.append("F9 override was active")
    if any(frame["practice"] for frame in frames):
        problems.append("recorded inside Practice")
    speeds = {frame["speed"] for frame in frames if frame["speed"] is not None}
    if speeds - {1, 1.0}:
        problems.append(f"game_speed varied: {sorted(speeds)}")

    service_frames = [
        frame for frame in frames
        if frame["day"] is not None and frame["day"] >= 1]
    if not service_frames:
        problems.append("no day 1 service frames")
    else:
        paused = sum(1 for frame in service_frames if frame["paused"])
        if paused:
            problems.append(f"paused during service in {paused} frames")

    days = {frame["day"] for frame in frames if frame["day"] is not None}
    if 0 not in days:
        notes.append("recording did not cover day 0 preparation")

    completed, detail = _day_completed(frames)
    if not completed:
        problems.append(f"day 1 did not run to completion ({detail})")

    table_counts = {len(frame["tables"]) for frame in frames if frame["tables"]}
    chair_counts = {
        chairs for frame in frames for _entity, chairs in frame["tables"]
        if chairs is not None}
    if table_counts - {1}:
        problems.append(f"table sets observed: {sorted(table_counts)}")
    if len(chair_counts) > 1:
        problems.append(f"table size varied: {sorted(chair_counts)}")

    if recording["demo_frames"] == 0:
        problems.append("no demo_input frames")
    elif not recording["demo_status_enabled"]:
        problems.append("no enabled demo_status")

    if recipe["derived"] in ("unknown", "mixed", "unrecognised"):
        problems.append(f"recipe not derivable from orders: {recipe['derived']}")
    elif not recipe["matches"]:
        problems.append(
            f"declared recipe {recipe['declared']!r} does not match "
            f"derived {recipe['derived']!r}")

    if service["order_identity_changes"]:
        notes.append(
            f"{service['order_identity_changes']} order buffer identity "
            "changes; keying assumption may not hold")

    return {
        "accepted": not problems,
        "problems": problems,
        "notes": notes,
        "table_size": sorted(chair_counts)[0] if chair_counts else None,
    }


def _day_completed(frames):
    """Day 1 ran out, or the run moved past it.

    time_unbounded is the day clock normalised by day_length, so reaching 1.0
    means arrivals have closed. Customers already seated keep eating past that
    point, so the day is only complete once they have also left. Neither signal
    is a game-stated end-of-day flag; both are read from published fields.
    """
    days = [frame["day"] for frame in frames if frame["day"] is not None]
    if not days:
        return False, "no day field"
    if max(days) > 1:
        return True, f"reached day {max(days)}"
    for frame in reversed(frames):
        if frame["day"] != 1:
            continue
        unbounded = frame["unbounded"]
        remaining = len(frame["groups"])
        if unbounded is None:
            return False, "no time_unbounded on the final day 1 frame"
        if unbounded < 1.0:
            return False, (
                f"recording stopped at {unbounded:.1%} of the day; "
                "keep recording until the day ends")
        if remaining:
            return False, f"{remaining} group(s) still present at the end"
        return True, "arrivals closed and all groups departed"
    return False, "no day 1 frames"


# --------------------------------------------------------------------------
# per-session report
# --------------------------------------------------------------------------


def analyse_session(path):
    recording = load(path)
    recipe = derive_recipe(recording)
    service = analyse_service(recording)
    interactions = analyse_interactions(recording)
    acceptance = check_acceptance(recording, service, recipe)

    completed = service["orders_completed"]
    per_meal = None
    if interactions.get("available") and completed:
        per_meal = interactions["effective_interactions"] / completed

    return {
        "path": os.path.normpath(path),
        "manifest": recording.get("manifest"),
        "bridge_version": (recording.get("hello") or {}).get("bridge_version"),
        "mod_hash": (recording.get("hello") or {}).get("mod_hash"),
        "recipe": recipe,
        "service": service,
        "interactions": interactions,
        "acceptance": acceptance,
        "metrics": {
            "failure_rate": service["failure_rate"],
            "interactions_per_meal": per_meal,
            "process_seconds_per_meal": service["process_seconds_per_meal"],
        },
        "observations": len(recording["frames"]),
        "demo_frames": recording["demo_frames"],
    }


def _format(value, digits=3):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def print_session(result):
    service = result["service"]
    recipe = result["recipe"]
    interactions = result["interactions"]
    acceptance = result["acceptance"]

    print(f"file:     {result['path']}")
    print(f"bridge:   {result['bridge_version']}  mod={result['mod_hash']}")
    print(f"frames:   {result['observations']} obs, "
          f"{result['demo_frames']} demo_input")
    print(f"recipe:   derived={recipe['derived']} "
          f"declared={recipe['declared']!r} match={recipe['matches']}")
    if recipe["main_dishes"]:
        print(f"  mains:  {recipe['main_dishes']}")
    if recipe["side_dishes"]:
        print(f"  sides:  {recipe['side_dishes']}")

    print()
    print("service:")
    print(f"  groups              {service['groups']} "
          f"sizes={service['group_sizes']}")
    print(f"  orders              {service['orders_completed']} completed / "
          f"{service['orders_attempted']} attempted "
          f"({service['orders_unsatisfied']} unsatisfied)")
    print(f"  order entry frames  {service['order_entry_frames']}")
    print(f"  satisfaction edges  {service['satisfaction_transitions']}")
    print(f"  ruined items        {service['ruined_items']} "
          f"{service['ruined_item_names'] or ''}")
    print(f"  at-risk (is_bad)    {service['at_risk_items']} "
          "(lookahead flag, not a failure)")
    if service["served_doneness"]:
        print(f"  served doneness     {service['served_doneness']}")
    print(f"  service seconds     {_format(service['service_seconds'], 1)}")
    print(f"  process item-sec    {_format(service['process_item_seconds'], 1)}")
    print(f"  meals/service min   "
          f"{_format(service['meals_per_service_minute'], 2)}")
    print(f"  money               {service['money_start']} -> "
          f"{service['money_end']}   lives={service['lives_end']}")
    print("  saturating diagnostics (not decisive):")
    print(f"    patience slack    {_format(service['service_slack'])} "
          f"at first delivery, {_format(service['minimum_patience'])} minimum")
    print(f"    order latency     {_format(service['order_latency'], 1)} s")

    print()
    print("interactions:")
    if not interactions.get("available"):
        print(f"  unavailable: {interactions.get('reason')}")
    else:
        print(f"  pressed edges       {interactions['pressed_edges']}")
        print(f"  paired              {interactions['paired']} "
              f"(unresolved {interactions['unresolved']}, "
              f"ambiguous window {interactions['ambiguous_window']})")
        print(f"  null rate           "
              f"{_format(interactions['null_rate'])}")
        print(f"  classified          {interactions['classified']}")

    print()
    print("decisive metrics:")
    metrics = result["metrics"]
    print(f"  1 failure rate         {_format(metrics['failure_rate'])}")
    print(f"  2 interactions/meal    "
          f"{_format(metrics['interactions_per_meal'], 2)}")
    print(f"  3 process sec/meal     "
          f"{_format(metrics['process_seconds_per_meal'], 1)}")

    print()
    if acceptance["accepted"]:
        print("ACCEPTED as a benchmark session")
    else:
        print("REJECTED as a benchmark session")
        for problem in acceptance["problems"]:
            print("  - " + problem)
    for note in acceptance["notes"]:
        print("  note: " + note)


# --------------------------------------------------------------------------
# benchmark decision
# --------------------------------------------------------------------------


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


DECISIVE_METRICS = (
    ("failure_rate", "demonstration failure rate", False),
    ("interactions_per_meal", "interactions per completed meal", False),
    ("process_seconds_per_meal", "process seconds per completed meal", False),
)


def compare_metric(values_a, values_b, higher_is_better):
    """Protocol section 5 step 2, for one metric."""
    if len(values_a) < 2 or len(values_b) < 2:
        return {
            "winner": None,
            "reason": "fewer than two sessions with this metric",
        }

    median_a = statistics.median(values_a)
    median_b = statistics.median(values_b)
    larger = max(abs(median_a), abs(median_b))
    margin = abs(median_a - median_b) / larger if larger else 0.0

    low_a, high_a = percentile(values_a, 0.25), percentile(values_a, 0.75)
    low_b, high_b = percentile(values_b, 0.25), percentile(values_b, 0.75)
    separated = high_a < low_b or high_b < low_a

    result = {
        "median_a": median_a,
        "median_b": median_b,
        "iqr_a": [low_a, high_a],
        "iqr_b": [low_b, high_b],
        "margin": margin,
        "margin_met": margin >= MARGIN,
        "iqr_separated": separated,
        "winner": None,
        "reason": None,
    }

    if not result["margin_met"]:
        result["reason"] = f"median gap {margin:.1%} below the {MARGIN:.0%} margin"
        return result
    if not separated:
        result["reason"] = "interquartile ranges overlap"
        return result

    a_wins = median_a > median_b if higher_is_better else median_a < median_b
    result["winner"] = "a" if a_wins else "b"
    result["reason"] = "margin met and interquartile ranges separated"
    return result


def run_benchmark(directory_a, directory_b):
    arm_a = _analyse_directory(directory_a)
    arm_b = _analyse_directory(directory_b)

    name_a = _arm_name(arm_a, directory_a)
    name_b = _arm_name(arm_b, directory_b)

    accepted_a = [r for r in arm_a if r["acceptance"]["accepted"]]
    accepted_b = [r for r in arm_b if r["acceptance"]["accepted"]]

    comparisons = []
    winner = None
    deciding = None
    for key, label, higher_is_better in DECISIVE_METRICS:
        values_a = [
            r["metrics"][key] for r in accepted_a
            if r["metrics"][key] is not None]
        values_b = [
            r["metrics"][key] for r in accepted_b
            if r["metrics"][key] is not None]
        comparison = compare_metric(values_a, values_b, higher_is_better)
        comparison.update({
            "metric": key,
            "label": label,
            "higher_is_better": higher_is_better,
            "n_a": len(values_a),
            "n_b": len(values_b),
        })
        comparisons.append(comparison)
        if winner is None and comparison["winner"]:
            winner = name_a if comparison["winner"] == "a" else name_b
            deciding = label

    formal = (
        len(accepted_a) >= MINIMUM_SESSIONS_PER_ARM
        and len(accepted_b) >= MINIMUM_SESSIONS_PER_ARM)

    if winner is None:
        verdict = "INCONCLUSIVE"
        selection = "burger"
        basis = "protocol section 5.1 tiebreak, not measurement"
    else:
        verdict = "DECIDED"
        selection = winner
        basis = f"deciding metric: {deciding}"

    return {
        "arms": {name_a: directory_a, name_b: directory_b},
        "sessions": {
            name_a: {"total": len(arm_a), "accepted": len(accepted_a)},
            name_b: {"total": len(arm_b), "accepted": len(accepted_b)},
        },
        "comparisons": comparisons,
        "verdict": verdict,
        "selection": selection,
        "basis": basis,
        "formal": formal,
        "minimum_sessions_per_arm": MINIMUM_SESSIONS_PER_ARM,
        "rejected": {
            name_a: _rejections(arm_a),
            name_b: _rejections(arm_b),
        },
        "reported": {
            name_a: _reported(accepted_a),
            name_b: _reported(accepted_b),
        },
    }


def _analyse_directory(directory):
    paths = sorted(
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.endswith(".jsonl"))
    if not paths:
        raise ValueError(f"no .jsonl recordings in {directory}")
    return [analyse_session(path) for path in paths]


def _arm_name(results, directory):
    derived = {
        r["recipe"]["derived"] for r in results
        if r["acceptance"]["accepted"]}
    if len(derived) == 1:
        return derived.pop()
    return os.path.basename(os.path.normpath(directory))


def _rejections(results):
    return [
        {"path": r["path"], "problems": r["acceptance"]["problems"]}
        for r in results if not r["acceptance"]["accepted"]]


def _reported(results):
    """Protocol section 4.2. Reported for the ledger, not used to decide."""
    if not results:
        return {}
    group_sizes = Counter()
    doneness = Counter()
    for result in results:
        for size, count in result["service"]["group_sizes"].items():
            group_sizes[size] += count
        for state, count in result["service"]["served_doneness"].items():
            doneness[state] += count

    def median_of(path):
        values = [
            _dig(result, path) for result in results
            if _dig(result, path) is not None]
        return statistics.median(values) if values else None

    return {
        "sessions": len(results),
        "median_groups_per_day": median_of(("service", "groups")),
        "group_size_distribution": dict(group_sizes),
        "median_orders_per_day": median_of(("service", "orders_attempted")),
        "median_meals_per_service_minute": median_of(
            ("service", "meals_per_service_minute")),
        "median_money_end": median_of(("service", "money_end")),
        "median_service_seconds": median_of(("service", "service_seconds")),
        "total_ruined_items": sum(
            r["service"]["ruined_items"] for r in results),
        "served_doneness": dict(doneness),
        "median_null_interaction_rate": median_of(
            ("interactions", "null_rate")),
        "median_minimum_patience": median_of(("service", "minimum_patience")),
        "median_order_latency": median_of(("service", "order_latency")),
    }


def _dig(mapping, path):
    for key in path:
        if not isinstance(mapping, dict):
            return None
        mapping = mapping.get(key)
    return mapping


def print_benchmark(result):
    print("Recipe benchmark - docs/recipe-benchmark-protocol.md")
    print()
    for name, directory in result["arms"].items():
        counts = result["sessions"][name]
        print(f"arm {name}: {counts['accepted']} accepted / "
              f"{counts['total']} recorded   ({directory})")
    print()

    names = list(result["arms"])
    for comparison in result["comparisons"]:
        direction = "higher" if comparison["higher_is_better"] else "lower"
        print(f"metric: {comparison['label']}  ({direction} is easier)")
        if comparison.get("median_a") is None:
            print(f"  no comparison: {comparison['reason']}")
            print()
            continue
        print(f"  {names[0]:<8} median {_format(comparison['median_a'])}  "
              f"IQR [{_format(comparison['iqr_a'][0])}, "
              f"{_format(comparison['iqr_a'][1])}]  n={comparison['n_a']}")
        print(f"  {names[1]:<8} median {_format(comparison['median_b'])}  "
              f"IQR [{_format(comparison['iqr_b'][0])}, "
              f"{_format(comparison['iqr_b'][1])}]  n={comparison['n_b']}")
        print(f"  margin {comparison['margin']:.1%} "
              f"(need {MARGIN:.0%}), "
              f"IQR separated: {comparison['iqr_separated']}")
        if comparison["winner"]:
            print(f"  -> {names[0] if comparison['winner'] == 'a' else names[1]}")
        else:
            print(f"  -> no winner: {comparison['reason']}")
        print()

    for name in names:
        rejections = result["rejected"][name]
        if rejections:
            print(f"rejected in arm {name}:")
            for rejection in rejections:
                print(f"  {rejection['path']}")
                for problem in rejection["problems"]:
                    print(f"    - {problem}")
            print()

    print("reported, not decisive:")
    for name in names:
        print(f"  {name}: {json.dumps(result['reported'][name])}")
    print()

    print(f"verdict:   {result['verdict']}")
    print(f"selection: {result['selection']}")
    print(f"basis:     {result['basis']}")
    if not result["formal"]:
        print(f"NOTE: fewer than {result['minimum_sessions_per_arm']} accepted "
              "sessions per arm. This is a quick sample, not a formal gate.")


# --------------------------------------------------------------------------
# analyzer self-validation, protocol section 6
# --------------------------------------------------------------------------

GOLDEN_TRACE = os.path.join("runs", "golden", "obs_0.1_day1.jsonl")
SMOKE_DEMO = os.path.join("runs", "demos", "smoke.jsonl")

# Independently recorded in docs/verified-successes.md section 2.3.
GOLDEN_EXPECTED = {
    "groups": 4,
    "order_entry_frames": 308,
    "satisfaction_transitions": 3,
}


def validate():
    checks = []

    def check(name, condition, detail):
        checks.append((name, bool(condition), detail))

    if not os.path.exists(GOLDEN_TRACE):
        print(f"FAIL: missing {GOLDEN_TRACE}")
        return False
    if not os.path.exists(SMOKE_DEMO):
        print(f"FAIL: missing {SMOKE_DEMO}")
        return False

    golden = analyse_session(GOLDEN_TRACE)
    service = golden["service"]
    for key, expected in GOLDEN_EXPECTED.items():
        check(
            f"golden trace {key}",
            service[key] == expected,
            f"got {service[key]}, ledger section 2.3 records {expected}")

    check(
        "golden trace recipe derived",
        golden["recipe"]["derived"] == "burger",
        f"derived {golden['recipe']['derived']!r} from "
        f"{golden['recipe']['main_dishes']}")

    check(
        "demo-free file reports interactions unavailable",
        golden["interactions"].get("available") is False
        and golden["metrics"]["interactions_per_meal"] is None,
        f"available={golden['interactions'].get('available')}, "
        f"per-meal={golden['metrics']['interactions_per_meal']}")

    check(
        "demo-free file still yields observation metrics",
        service["failure_rate"] is not None
        and golden["metrics"]["process_seconds_per_meal"] is not None,
        f"failure_rate={service['failure_rate']}, "
        f"process sec/meal="
        f"{_format(golden['metrics']['process_seconds_per_meal'], 1)}")

    smoke = analyse_session(SMOKE_DEMO)
    check(
        "smoke recording rejected as a benchmark session",
        not smoke["acceptance"]["accepted"],
        "; ".join(smoke["acceptance"]["problems"]) or "unexpectedly accepted")

    # The smoke session was played on a steak restaurant but recorded with
    # --recipe smoke. That makes it the live proof that protocol section 4.5
    # catches a declared/derived mismatch instead of trusting the flag.
    check(
        "declared/derived recipe mismatch is caught",
        smoke["recipe"]["derived"] == "steak"
        and smoke["recipe"]["declared"] == "smoke"
        and not smoke["recipe"]["matches"]
        and any(
            "does not match" in problem
            for problem in smoke["acceptance"]["problems"]),
        f"declared {smoke['recipe']['declared']!r}, "
        f"derived {smoke['recipe']['derived']!r}")

    check(
        "incomplete day is caught",
        any(
            "did not run to completion" in problem
            for problem in smoke["acceptance"]["problems"]),
        "; ".join(smoke["acceptance"]["problems"]))

    interactions = smoke["interactions"]
    check(
        "smoke segmentation produced events",
        interactions.get("available") and interactions["paired"] > 0,
        f"paired {interactions.get('paired')} of "
        f"{interactions.get('pressed_edges')} pressed edges, "
        f"null rate {_format(interactions.get('null_rate'))}")

    width = max(len(name) for name, _passed, _detail in checks)
    failed = 0
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            failed += 1
        print(f"{status}  {name:<{width}}  {detail}")

    print()
    if failed:
        print(f"FAIL: {failed} of {len(checks)} analyzer checks failed")
        return False
    print(f"OK -- {len(checks)} analyzer checks passed against recorded "
          "artifacts")
    return True


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    session_parser = subparsers.add_parser("session")
    session_parser.add_argument("path")
    session_parser.add_argument("--json", dest="json_path")

    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("directory_a")
    benchmark_parser.add_argument("directory_b")
    benchmark_parser.add_argument("--json", dest="json_path")

    subparsers.add_parser("validate")
    return parser.parse_args()


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as output:
        json.dump(payload, output, indent=2, sort_keys=True)
    print(f"\nwrote {os.path.normpath(path)}")


def main():
    args = parse_args()

    if args.command == "session":
        result = analyse_session(args.path)
        print_session(result)
        if args.json_path:
            _write_json(args.json_path, result)
        return 0 if result["acceptance"]["accepted"] else 1

    if args.command == "benchmark":
        result = run_benchmark(args.directory_a, args.directory_b)
        print_benchmark(result)
        if args.json_path:
            _write_json(args.json_path, result)
        return 0 if result["verdict"] == "DECIDED" else 1

    return 0 if validate() else 1


if __name__ == "__main__":
    sys.exit(main())
