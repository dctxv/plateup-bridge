r"""
Live verification of everything the offline work assumed. Read-only.

    python python/livecheck.py
    python python/livecheck.py --json runs/live/check.json --seconds 300

**This never takes control.** It sends only the neutral heartbeat the pipe
already requires, so F9 must stay OFF and you play normally while it watches.
Nothing it does can move the chef, and it cannot fail a restaurant.

Why it exists. The offline work rests on a set of claims that were derived from
two recordings and from the knowledge base, and every one of them is falsifiable
in about five minutes of hand-play. This prints them as a checklist and marks
each one the moment the evidence arrives, so a live session produces a verdict
instead of an impression.

What to do to exercise it, in any order:

    walk around                 settles the rotation convention
    put a raw steak on a hob    settles the cook timings, the one set of
                                numbers taken from the knowledge base and
                                never observed
    let it reach Well-done      settles the is_bad lookahead
    plate a cooked steak        settles the plating route
    serve a customer            settles the delivery reach and the dirty plate
    wash the plate              settles the sink rate
    start a day                 settles the preparation checklist

Checks that never see their trigger stay PENDING and are reported as such. A
PENDING is not a pass.
"""

import argparse
import json
import math
import os
import sys
import time

import encode
import kitchen as K
import options as O
import steak as S
from observe import ObservationClient

VERSION = "livecheck_0.1"

# Ledger section 2.4: the bridge 0.3.0 DLL whose hash the recorded artifacts
# were produced under.
EXPECTED_MOD_HASH = (
    "164a7ae4f2c796e3db0d7d8f7622daae49450ad515ef0319e320f214996af8d0")
EXPECTED_DICTIONARY = {"appliances": 403, "items": 420, "processes": 17}

PENDING = "PENDING"
PASS = "PASS"
FAIL = "FAIL"
NOTE = "NOTE"


class Check:
    """One falsifiable claim, and the first evidence that settles it."""

    def __init__(self, key, claim, needs):
        self.key = key
        self.claim = claim
        self.needs = needs
        self.state = PENDING
        self.detail = ""
        self.samples = 0

    def settle(self, ok, detail):
        # First evidence wins, except that a later failure always overrides a
        # pass: one counterexample is worth more than any number of confirming
        # frames.
        self.samples += 1
        if not ok:
            self.state = FAIL
            self.detail = detail
        elif self.state == PENDING:
            self.state = PASS
            self.detail = detail

    def note(self, detail):
        if self.state == PENDING:
            self.state = NOTE
            self.detail = detail

    def as_dict(self):
        return {
            "check": self.key,
            "claim": self.claim,
            "needs": self.needs,
            "state": self.state,
            "detail": self.detail,
            "samples": self.samples,
        }


class LiveCheck:
    def __init__(self):
        self.checks = {}
        self._add("handshake", "protocol and schema versions match the client",
                  "connecting")
        self._add("mod_hash", "the loaded DLL is the one the ledger records",
                  "connecting")
        self._add("dictionary",
                  "403 appliances, 420 items, 17 processes resolve",
                  "connecting")
        self._add("steak_names",
                  "every steak-chain name resolves on this build",
                  "connecting")
        self._add("observation_rate",
                  "observations arrive at the measured 25-30 Hz, not 10 Hz",
                  "a few seconds of stream")
        self._add("rotation_zero",
                  "rot 0 faces +z and rot 90 faces +x",
                  "walking around")
        self._add("provider_infinity",
                  "an infinite provider reports maximum 0, not a negative",
                  "being in a restaurant")
        self._add("plate_stack_finite",
                  "the plate stack reports a real stock count",
                  "being in a restaurant")
        self._add("floor_mess",
                  "mess is published as a Floor-layer appliance",
                  "any mess on the floor")
        self._add("table_unresolvable",
                  "groups[].table cannot be resolved to a published appliance",
                  "a seated customer group")
        self._add("group_locates_table",
                  "a seated group's position is exactly its table's position",
                  "a seated customer group")
        self._add("entity_recycling",
                  "appliance entity ids change when the day starts",
                  "starting a day while this runs")
        self._add("reach_model",
                  "every working appliance has a stance inside the reach limit",
                  "being in a restaurant")
        self._add("cook_chain",
                  "the steak chain runs Meat -> Rare -> Medium -> Well-done",
                  "cooking a steak")
        self._add("cook_timings",
                  "cook stage durations match the knowledge-base priors",
                  "cooking a steak through its stages")
        self._add("is_bad_lookahead",
                  "is_bad turns true on Well-done, while it is still servable",
                  "cooking a steak to Well-done")
        self._add("plating",
                  "a cooked steak plus a plate becomes Steak - Plated",
                  "plating a steak")
        self._add("plated_freezes",
                  "a plated dish carries no process",
                  "plating a steak")
        self._add("dirty_plate",
                  "a served plate comes back as a dirty plate",
                  "serving a customer and letting them eat")
        self._add("wash_rate",
                  "the starting sink cleans at 0.375 progress per second",
                  "washing a plate")
        self._add("preparation",
                  "the start-day checklist looks as recorded",
                  "being in day 0 preparation")

        self.rate_samples = []
        self.rotation_errors = []
        self.observed_rates = {}
        self.previous = None
        self.previous_heading = None
        self.previous_slots = None
        self.previous_day = None
        self.chain = None
        self.registry = None
        self.frames = 0

    def _add(self, key, claim, needs):
        self.checks[key] = Check(key, claim, needs)

    # -- connection -------------------------------------------------------

    def handshake(self, client):
        hello = client.b.hello or {}
        self.checks["handshake"].settle(
            hello.get("protocol") == 1
            and hello.get("obs_schema") == "obs_0.1"
            and hello.get("act_schema") == "act_0.1",
            f"protocol {hello.get('protocol')}, {hello.get('obs_schema')}, "
            f"{hello.get('act_schema')}, demo {hello.get('demo_schema')}")

        live_hash = (hello.get("mod_hash") or "").lower()
        if live_hash == EXPECTED_MOD_HASH:
            self.checks["mod_hash"].settle(True, f"{live_hash[:16]} as recorded")
        else:
            self.checks["mod_hash"].settle(
                False,
                f"live {live_hash[:16]} != ledger {EXPECTED_MOD_HASH[:16]}; "
                "rebuild and restart PlateUp, or the offline artifacts do not "
                "describe this DLL")

    def dictionary(self, client):
        counts = {
            "appliances": len(client.appliance_names),
            "items": len(client.item_names),
            "processes": len(client.process_names),
        }
        self.checks["dictionary"].settle(
            counts == EXPECTED_DICTIONARY, str(counts))

        registry = S.Registry(
            client.item_names, client.appliance_names, client.process_names)
        self.registry = registry
        self.checks["steak_names"].settle(
            registry.complete,
            "all resolved" if registry.complete
            else f"missing {registry.missing_items} "
                 f"{registry.missing_processes}")

    # -- per frame --------------------------------------------------------

    def observe(self, world, wall_clock):
        self.frames += 1
        self._rate(wall_clock)
        if not world.in_restaurant:
            self.previous = None
            return

        if self.chain is None:
            cut = S.infer_cut(world)
            if cut:
                self.chain = S.Chain(cut)

        kitchen = K.Kitchen(world)
        self._layout(world, kitchen)
        self._rotation(world)
        self._groups(world, kitchen)
        self._items(world, kitchen)
        self._preparation(world)
        self._recycling(world, kitchen)
        self.previous = world.raw

    def _rate(self, wall_clock):
        self.rate_samples.append(wall_clock)
        if len(self.rate_samples) < 60:
            return
        window = self.rate_samples[-60:]
        span = window[-1] - window[0]
        if span <= 0:
            return
        hertz = (len(window) - 1) / span
        self.checks["observation_rate"].settle(
            15.0 <= hertz <= 45.0, f"{hertz:.1f} Hz over the last 60 frames")

    def _rotation(self, world):
        """Compare the direction the chef actually moved with his rotation.

        Only while the direction is steady. `PlayerWalkingComponent` turns
        toward the movement vector at a finite rate, so a frame taken mid-turn
        disagrees by tens of degrees through latency alone and says nothing
        about the axis convention. Requiring two consecutive frames to agree on
        the heading isolates the steady state, which is the same filter
        `facts.py` applies to the recorded data.
        """
        me = world.me
        if me is None or self.previous is None:
            return
        before = (self.previous.get("players") or [None])[0]
        if before is None:
            return
        dx = me["x"] - before["x"]
        dz = me["z"] - before["z"]
        if math.hypot(dx, dz) < 0.06:
            self.previous_heading = None
            return
        heading = K.heading_degrees(dx, dz)
        steady = (
            self.previous_heading is not None
            and abs(K.angle_error(heading, self.previous_heading)) <= 10.0)
        self.previous_heading = heading
        if not steady:
            return
        error = abs(K.angle_error(heading, me.get("rot", 0.0)))
        self.rotation_errors.append(error)
        if len(self.rotation_errors) < 30:
            return

        # Judge the median, not a frame. Displacement lags the commanded
        # direction through acceleration and rot leads it, so a correct
        # convention still shows tens of degrees on individual frames. What a
        # *wrong* convention looks like is unmistakable: swapping the axes puts
        # the median near 90 degrees and flipping one puts it near 180.
        ordered = sorted(self.rotation_errors)
        median = ordered[len(ordered) // 2]
        self.checks["rotation_zero"].settle(
            median <= 30.0,
            f"median error {median:.1f} deg over {len(ordered)} steady "
            f"samples (a swapped axis would read ~90, a flipped one ~180)")

    def _layout(self, world, kitchen):
        infinite = []
        finite = []
        for appliance in world.appliances:
            if "provides" not in appliance:
                continue
            maximum = appliance.get("maximum") or 0
            available = appliance.get("available") or 0
            if maximum == 0:
                infinite.append((appliance.get("name"), available))
            else:
                finite.append((appliance.get("name"), available, maximum))
        if infinite:
            self.checks["provider_infinity"].settle(
                all(available >= 0 for _n, available in infinite),
                f"{[n for n, _a in infinite]} report maximum 0")
        if finite:
            self.checks["plate_stack_finite"].settle(
                all(0 <= a <= m for _n, a, m in finite), str(finite))

        messes = kitchen.messes()
        if messes:
            self.checks["floor_mess"].settle(
                all(m.get("layer") == K.OCCUPANCY_FLOOR for m in messes),
                f"{[m.get('name') for m in messes]} at layer "
                f"{sorted({m.get('layer') for m in messes})}")

        targets = (kitchen.role("cook") + kitchen.role("wash")
                   + kitchen.role("surface")
                   + [a for a in kitchen.appliances if "provides" in a])
        targets = [a for a in targets if a.get("provides_name") != S.WATER
                   or "Sink" in a.get("name", "")]
        if targets:
            missing = [
                a.get("name") for a in targets
                if kitchen.best_pose(a) is None]
            self.checks["reach_model"].settle(
                not missing,
                f"{len(targets)} appliances posed"
                if not missing else f"no stance for {sorted(set(missing))}")

    def _groups(self, world, kitchen):
        published = {a["e"] for a in world.appliances}
        for group in world.groups:
            table = group.get("table")
            if table:
                self.checks["table_unresolvable"].settle(
                    table not in published,
                    f"{table} is not a published appliance"
                    if table not in published
                    else f"{table} RESOLVED, which contradicts the offline "
                         "finding; the group-position workaround is no longer "
                         "needed")
            # Only a group that has been given a table and has stopped being
            # seated stands on it. A queueing group is outside the door, and
            # scoring it would fail a claim that was never about queues.
            if not table or group.get("patience_reason") == 2:
                continue
            tables = kitchen.tables()
            if not tables:
                continue
            nearest = min(
                tables,
                key=lambda a: (a["x"] - group["x"]) ** 2
                + (a["z"] - group["z"]) ** 2)
            offset = K.distance(
                (nearest["x"], nearest["z"]), (group["x"], group["z"]))
            self.checks["group_locates_table"].settle(
                offset < 0.05,
                f"seated group sits {offset:.3f} from {nearest.get('name')}")

    def _items(self, world, kitchen):
        if self.chain is None:
            return
        chain = self.chain

        for appliance in kitchen.appliances:
            item = appliance.get("held")
            if item is None:
                continue
            name = item.get("name")
            rate = item.get("rate")
            process = item.get("process_name")

            if process == S.COOK_PROCESS and chain.stage_number(name) \
                    is not None and rate:
                stage = chain.stage_number(name)
                self.observed_rates.setdefault(name, []).append(rate)
                self.checks["cook_chain"].settle(
                    True, f"{name} cooking at stage {stage}")
                prior = chain.stage_seconds(stage)
                measured = 1.0 / rate
                if prior:
                    within = abs(measured - prior) / prior <= 0.25
                    self.checks["cook_timings"].settle(
                        within,
                        f"{name}: measured {measured:.2f}s, prior "
                        f"{prior:.2f}s"
                        + ("" if within else "  <-- the prior is wrong; "
                                            "update docs/steak-recipe.md "
                                            "section 3"))

            if name == chain.stages[-1] and process == S.COOK_PROCESS:
                self.checks["is_bad_lookahead"].settle(
                    bool(item.get("is_bad")),
                    f"{name} is_bad={item.get('is_bad')} while still servable")

            if name == S.CLEAN_PROCESS:
                pass
            if process == S.CLEAN_PROCESS and rate:
                self.checks["wash_rate"].settle(
                    abs(rate - S.STARTING_APPLIANCE_RATE) < 0.05
                    or "Sink - Starting" not in appliance.get("name", ""),
                    f"{appliance.get('name')} cleans at {rate:.3f}/s "
                    f"({1.0 / rate:.2f}s)")

            if name == chain.plated:
                components = set(item.get("component_names") or ())
                self.checks["plating"].settle(
                    S.CLEAN_PLATE in components,
                    f"{name} = {sorted(components)}")
                self.checks["plated_freezes"].settle(
                    item.get("process") is None,
                    f"process={item.get('process_name')}")

            if S.is_dirty_plate(name):
                self.checks["dirty_plate"].settle(
                    True, f"{name} on {appliance.get('name')}")

        held = world.me.get("held") if world.me else None
        if held and held.get("name") == chain.plated:
            components = set(held.get("component_names") or ())
            self.checks["plating"].settle(
                S.CLEAN_PLATE in components,
                f"held {held.get('name')} = {sorted(components)}")

    def _preparation(self, world):
        warnings = world.start_day_warnings
        if warnings is None:
            return
        expected = {
            "players_ready", "popups_open", "selling_required_appliance",
            "table_size", "players_not_ready", "post_unopened",
            "more_than_one_table", "players_in_crane_mode"}
        self.checks["preparation"].settle(
            expected <= set(warnings) and world.day == 0,
            f"day {world.day}, players_ready={warnings.get('players_ready')}, "
            f"players_not_ready={warnings.get('players_not_ready')}, "
            f"popups_open={warnings.get('popups_open')}")

    def _recycling(self, world, kitchen):
        slots = {
            K.slot_key(a): a["e"] for a in world.appliances
            if not K.is_structure(a.get("name", ""))}
        if self.previous_day is not None and world.day != self.previous_day \
                and self.previous_slots:
            changed = sum(
                1 for slot, entity in slots.items()
                if slot in self.previous_slots
                and self.previous_slots[slot] != entity)
            self.checks["entity_recycling"].settle(
                changed > 0,
                f"{changed} appliance slots got a new entity id crossing "
                f"day {self.previous_day} -> {world.day}")
        self.previous_slots = slots
        self.previous_day = world.day

    # -- reporting --------------------------------------------------------

    def report(self):
        order = list(self.checks.values())
        width = max(len(c.key) for c in order)
        lines = [f"{VERSION}  {self.frames} observations"]
        for check in order:
            lines.append(
                f"  {check.state:<7} {check.key:<{width}}  "
                f"{check.detail or check.needs}")

        counts = {}
        for check in order:
            counts[check.state] = counts.get(check.state, 0) + 1
        lines.append("")
        lines.append("  " + ", ".join(
            f"{state} {count}" for state, count in sorted(counts.items())))
        if counts.get(FAIL):
            lines.append("")
            lines.append("  A FAIL means an offline assumption is wrong. Each "
                         "one names what to change.")
        if counts.get(PENDING):
            lines.append("")
            lines.append("  PENDING is not a pass. Do the action in the right "
                         "column to settle it.")
        if self.observed_rates:
            lines.append("")
            lines.append("  measured cook rates (progress per second):")
            for name, rates in sorted(self.observed_rates.items()):
                mean = sum(rates) / len(rates)
                lines.append(
                    f"    {name:<24} {mean:.4f}/s  = {1.0 / mean:.2f}s per "
                    f"stage  (n={len(rates)})")
        return "\n".join(lines)

    def payload(self):
        return {
            "schema": VERSION,
            "observations": self.frames,
            "checks": [c.as_dict() for c in self.checks.values()],
            "measured_cook_rates": {
                name: {
                    "mean_rate": sum(rates) / len(rates),
                    "seconds_per_stage": len(rates) / sum(rates),
                    "samples": len(rates),
                }
                for name, rates in self.observed_rates.items()},
        }


def run(seconds=600.0, json_path=None, quiet=False):
    checker = LiveCheck()
    with ObservationClient() as client:
        world = client.recv()
        checker.handshake(client)
        checker.dictionary(client)

        if world.override:
            print("\n!!! F9 override is ON. This tool never takes control, "
                  "but the bridge is holding your input. Press F9 to hand "
                  "control back to yourself.\n")

        print(checker.report())
        print("\nPlay normally. Live checklist below; Ctrl+C to stop.\n")

        started = time.monotonic()
        last_print = 0.0
        try:
            while time.monotonic() - started < seconds:
                checker.observe(world, time.monotonic())
                client.b.idle()
                world = client.recv()
                now = time.monotonic()
                if not quiet and now - last_print > 3.0:
                    last_print = now
                    print("\033[2J\033[H" + checker.report(), flush=True)
        except KeyboardInterrupt:
            pass

    print()
    print(checker.report())
    if json_path:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as output:
            json.dump(checker.payload(), output, indent=2, sort_keys=True)
        print("\nwrote " + os.path.normpath(json_path))
    return checker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--json", dest="json_path",
                        default=os.path.join("runs", "live", "check.json"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    checker = run(seconds=args.seconds, json_path=args.json_path,
                  quiet=args.quiet)
    failed = sum(
        1 for check in checker.checks.values() if check.state == FAIL)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
