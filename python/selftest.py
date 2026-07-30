r"""
Offline gate for the steak agent. No PlateUp, no bridge, no network.

    python python/selftest.py
    python python/selftest.py --json runs/selftest/latest.json

Every check runs against either a recorded artifact or the tick-level model in
`mockgame`. A pass means the code is internally consistent and agrees with the
two recordings that exist. It is **not** evidence that the chef behaves this
way in PlateUp; that requires a live run and its own ledger entry.

The suite is deliberately grouped so a failure names the layer that broke:

    facts        the derived observation facts still hold in the recordings
    geometry     reach, aim and routing against the recorded layouts
    steak        the recipe graph, timings and menu inference
    options      option lifecycles and their termination classification
    model        the tick-level model's own mechanics
    service      whole days played by the reference controller
    capability   registry statistics and persistence
    surrogate    the semi-MDP against the model it was calibrated on
    env          the Gymnasium-compatible API and its reward rules
    preparation  getting through day 0 and consenting to the day
    learning     dataset construction, cloning, and the evaluation harness
    antihack     the specification's reward-hacking tests
    manifest     run manifests and their artifact re-check
    livecheck    the live verifier, replayed against both recordings
"""

import argparse
import json
import os
import sys
import tempfile

import antihack
import capability
import dataset as DATA
import encode
import env as ENV
import evaluate as EVAL
import facts
import kitchen as K
import livecheck
import manifest
import mockgame
import options as O
import policy as POLICY
import service
import steak as S
import surrogate as SUR
from observe import ObservationClient

GOLDEN = os.path.join("runs", "golden", "obs_0.1_day1.jsonl")
SMOKE = os.path.join("runs", "demos", "smoke.jsonl")


class Suite:
    def __init__(self):
        self.results = []
        self.group = "general"

    def section(self, name):
        self.group = name

    def check(self, name, condition, detail=""):
        self.results.append((self.group, name, bool(condition), str(detail)))
        return bool(condition)

    @property
    def failed(self):
        return sum(1 for _g, _n, ok, _d in self.results if not ok)

    def report(self):
        width = max(len(name) for _g, name, _ok, _d in self.results)
        current = None
        for group, name, ok, detail in self.results:
            if group != current:
                print(f"\n[{group}]")
                current = group
            print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
        print()
        total = len(self.results)
        if self.failed:
            print(f"FAIL -- {self.failed} of {total} offline checks failed")
        else:
            print(f"OK -- {total} offline checks passed. This is an offline "
                  "gate and not live-game evidence.")
        return self.failed == 0

    def payload(self):
        return {
            "total": len(self.results),
            "failed": self.failed,
            "checks": [
                {"group": g, "name": n, "passed": ok, "detail": d}
                for g, n, ok, d in self.results],
        }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def worlds(path, limit=None):
    """Replay a recording through the live resolution path."""
    client = ObservationClient(announce=False)
    produced = 0
    with open(path, encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            world = client.feed(json.loads(line))
            if world is None:
                continue
            produced += 1
            yield client, world
            if limit and produced >= limit:
                return


def first_service_world(path):
    """A frame with a seated group, which is where geometry gets interesting."""
    latest = None
    for client, world in worlds(path):
        latest = (client, world)
        if world.groups and any(
                group.get("patience_reason") != 2 for group in world.groups):
            return client, world
    return latest


# --------------------------------------------------------------------------
# groups
# --------------------------------------------------------------------------


def test_facts(suite):
    suite.section("facts")
    report = facts.gather(GOLDEN, SMOKE)
    for name, passed, detail in facts.check(report):
        suite.check(name, passed, detail)


def test_geometry(suite):
    suite.section("geometry")

    suite.check("rot 0 faces +z",
                all(abs(a - b) < 1e-6
                    for a, b in zip(K.facing_vector(0), (0.0, 1.0))),
                str(tuple(round(v, 6) for v in K.facing_vector(0))))
    suite.check("rot 90 faces +x",
                all(abs(a - b) < 1e-6
                    for a, b in zip(K.facing_vector(90), (1.0, 0.0))),
                str(tuple(round(v, 6) for v in K.facing_vector(90))))
    suite.check("heading inverts facing",
                abs(K.angle_error(K.heading_degrees(*K.facing_vector(217)),
                                  217)) < 1e-6,
                "round trip within 1e-6 degrees")
    suite.check("interaction point sits one offset ahead",
                abs(K.distance(K.interaction_point(3.0, -1.0, 90),
                               (3.0, -1.0)) - K.INTERACTION_OFFSET) < 1e-9,
                f"{K.INTERACTION_OFFSET}")

    client, world = first_service_world(SMOKE)
    kitchen = K.Kitchen(world)
    suite.check("steak layout resolves its roles",
                {"cook", "wash", "bin", "surface", "table", "chair"}
                <= set(kitchen.roles),
                sorted(kitchen.roles))
    suite.check("meat and plate providers are found",
                kitchen.providers_of("Meat") and
                kitchen.providers_of(S.CLEAN_PLATE),
                f"{len(kitchen.providers_of('Meat'))} meat, "
                f"{len(kitchen.providers_of(S.CLEAN_PLATE))} plate")

    targets = (kitchen.role("cook") + kitchen.role("wash")
               + kitchen.role("bin") + kitchen.role("surface")
               + kitchen.providers_of("Meat")
               + kitchen.providers_of(S.CLEAN_PLATE))
    posed = [a for a in targets if kitchen.best_pose(a) is not None]
    suite.check("every working appliance has an approach pose",
                len(posed) == len(targets),
                f"{len(posed)} of {len(targets)}")

    routed = [
        a for a in targets
        if kitchen.poses_by_route(a, soft=()) ]
    suite.check("every working appliance is routable",
                len(routed) == len(targets),
                f"{len(routed)} of {len(targets)}")

    reaches = [kitchen.best_pose(a).reach for a in posed]
    suite.check("planned poses stay inside the reach limit",
                max(reaches) <= K.PLAN_REACH + 1e-9,
                f"max {max(reaches):.3f} of {K.PLAN_REACH}")

    clearances = [kitchen.best_pose(a).clearance for a in posed]
    suite.check("planned poses disambiguate their target",
                min(clearances) > K.AIM_MARGIN,
                f"min {min(clearances):.3f} above {K.AIM_MARGIN}")

    group = world.groups[0]
    table = kitchen.table_for_group(group)
    suite.check("a seated group resolves to a table appliance",
                table is not None and table.get("name", "").startswith("Table"),
                table.get("name") if table else "none")
    chairs = kitchen.chairs_around(table) if table else []
    suite.check("the table has adjacent chairs",
                len(chairs) >= 1, f"{len(chairs)} chairs")

    # The golden trace's recorded human delivery stances must be accepted by
    # the same aim model the planner uses, or the model is wrong about reach.
    gclient, gworld = first_service_world(GOLDEN)
    gkitchen = K.Kitchen(gworld)
    report = facts.derive_delivery_poses(facts.load(GOLDEN))
    accepted = 0
    for pose in report["poses"]:
        tables = [
            a for a in gkitchen.appliances
            if a.get("name", "").startswith("Table")]
        if not tables:
            continue
        target = min(tables, key=lambda a: K.distance(
            (a["x"], a["z"]), tuple(pose["table"])))
        keys = {target["e"]} | {
            c["e"] for c in gkitchen.chairs_around(target)}
        point = K.interaction_point(
            pose["stand"][0], pose["stand"][1], pose["rot"])
        if gkitchen.aim_clearance(point, keys) > 0:
            accepted += 1
    suite.check("recorded human delivery stances pass the aim model",
                accepted == len(report["poses"]),
                f"{accepted} of {len(report['poses'])}")

    blocked = next(iter(kitchen.blocked))
    suite.check("a blocked tile is not routable as a goal",
                kitchen.route((0, 0), blocked) is None,
                f"tile {blocked}")


def test_steak(suite):
    suite.section("steak")
    chain = S.Chain("plain")
    suite.check("chain runs raw to burned",
                chain.sequence == (
                    "Meat", "Steak - Rare", "Steak - Medium",
                    "Steak - Well-done", "Steak - Burned"),
                " -> ".join(chain.sequence))
    suite.check("only the three doneness states are servable",
                [chain.is_servable(name) for name in chain.sequence]
                == [False, True, True, True, False],
                str(chain.stages))
    suite.check("every cut is a well-formed chain",
                all(len(S.Chain(cut).base_seconds)
                    == len(S.Chain(cut).sequence) - 1 for cut in S.CUTS),
                sorted(S.CUTS))

    # The starting hob and starting sink both ran at 0.375 progress per second
    # in runs/golden, and the knowledge base gives both a 2 s base, so the
    # timescale derived from either must be the same 0.75 multiplier.
    scale = chain.timescale(1, S.STARTING_APPLIANCE_RATE)
    suite.check("measured rate reproduces the starting-appliance multiplier",
                abs(scale - 1.0 / S.STARTING_APPLIANCE_SPEED) < 1e-9,
                f"{scale:.4f} versus {1.0 / S.STARTING_APPLIANCE_SPEED:.4f}")

    item = {"name": "Steak - Rare", "progress": 0.5, "rate": 0.375}
    suite.check("seconds to the next stage is progress arithmetic",
                abs(chain.seconds_to_next(item) - (0.5 / 0.375)) < 1e-9,
                f"{chain.seconds_to_next(item):.4f}")
    seconds, estimated = chain.seconds_to_ruin(item)
    suite.check("time to ruin sums the remaining stages and says it is a prior",
                estimated and seconds > chain.seconds_to_next(item),
                f"{seconds:.2f}s, estimated={estimated}")
    suite.check("a plated dish has no time to ruin",
                chain.seconds_to_ruin({"name": chain.plated}) == (None, False),
                "None")

    client, world = first_service_world(SMOKE)
    suite.check("the recorded steak day is recognised as steak",
                S.infer_cut(world) == "plain", str(S.infer_cut(world)))
    gclient, gworld = first_service_world(GOLDEN)
    suite.check("the recorded burger day is not recognised as steak",
                S.infer_cut(gworld) is None, str(S.infer_cut(gworld)))

    registry = S.Registry(
        client.item_names, client.appliance_names, client.process_names)
    suite.check("every steak name resolves on the pinned build",
                registry.complete,
                f"missing {registry.missing_items} "
                f"{registry.missing_processes}")

    broken = S.Registry({}, {}, {})
    suite.check("a missing name is a loud failure",
                not broken.complete
                and _raises(broken.require, KeyError),
                f"{len(broken.missing_items)} missing items")

    kitchen = K.Kitchen(world)
    inventory = S.Inventory(world, kitchen, chain)
    suite.check("the plate stack reports finite stock",
                0 < inventory.plates_available() < 10 ** 6,
                str(inventory.plates_available()))

    infinite_world = _world_with_infinite_plates(world)
    infinite = S.Inventory(
        infinite_world, K.Kitchen(infinite_world), chain)
    suite.check("an infinite provider is not treated as empty",
                infinite.plates_available() >= 10 ** 6,
                str(infinite.plates_available()))


def _world_with_infinite_plates(world):
    import copy
    clone = copy.deepcopy(world)
    for appliance in clone.appliances:
        if appliance.get("provides_name") == S.CLEAN_PLATE:
            appliance["maximum"] = 0
            appliance["available"] = 0
    return clone


def _raises(callable_, exception):
    try:
        callable_()
    except exception:
        return True
    except Exception:
        return False
    return False


def test_options(suite):
    suite.section("options")
    game = mockgame.MockPlateUp(SMOKE, seed=5)
    client = ObservationClient(announce=False)
    client.feed(game.dictionary)
    chain = game.chain

    def context():
        return O.Context(client.feed(game.observation()), chain)

    def drive(option, limit=1200):
        option.start(context())
        for _ in range(limit):
            if option.done:
                break
            game.step(option.act(context()))
        return option

    provider = [
        a for a in context().kitchen.appliances
        if a.get("provides_name") == chain.raw][0]
    acquire = drive(O.AcquireItem(provider, want=chain.raw))
    suite.check("acquire picks up the raw cut",
                acquire.status == O.SUCCESS
                and context().held_name == chain.raw,
                f"{acquire.status}: {acquire.detail}")

    hob = context().kitchen.role("cook")[0]
    place = drive(O.PlaceItem(hob))
    suite.check("place puts the cut on the hob",
                place.status == O.SUCCESS
                and context().kitchen.by_slot[
                    K.slot_key(hob)].get("held") is not None,
                f"{place.status}: {place.detail}")

    watch = drive(O.WatchCook(hob, chain, min_stage=1), limit=2000)
    suite.check("watch_cook lifts at the first servable stage",
                watch.status == O.SUCCESS
                and context().held_name == chain.stages[0],
                f"{watch.status}: {context().held_name}")

    plates = [
        a for a in context().kitchen.appliances
        if a.get("provides_name") == S.CLEAN_PLATE][0]
    plate = drive(O.PlaceItem(plates, expect_held=chain.plated))
    suite.check("plating a cooked steak yields the plated dish",
                plate.status == O.SUCCESS
                and context().held_name == chain.plated,
                f"{plate.status}: {context().held_name}")

    # Hands have to be free before the next checks, and stashing the dish is
    # itself the contextual-placement path.
    surface = [
        a for a in context().kitchen.role("surface")
        if a.get("held") is None][0]
    stash = drive(O.PlaceItem(surface))
    suite.check("a finished dish can be buffered on a counter",
                stash.status == O.SUCCESS and context().held is None,
                f"{stash.status}: {stash.detail}")

    # An option whose goal has already gone is invalidated rather than failed:
    # the planner asked for something impossible, the controller did not fail.
    empty_hob = [
        a for a in context().kitchen.role("cook")
        if a.get("held") is None][0]
    invalid = drive(O.WatchCook(empty_hob, chain), limit=400)
    suite.check("watching an empty hob is invalidated, not failed",
                invalid.status == O.INVALID and "empty" in invalid.detail,
                f"{invalid.status}: {invalid.detail}")

    # An option asked to place with nothing in hand is invalid at plan time.
    nothing = O.PlaceItem(surface).start(context())
    suite.check("placing with empty hands is invalid at plan time",
                nothing.status == O.INVALID,
                f"{nothing.status}: {nothing.detail}")

    # Timeouts are classified separately from failures.
    slow = O.Idle(seconds=10 ** 6)
    slow.timeout = 0.05
    drive(slow, limit=50)
    suite.check("a timed-out option reports timeout",
                slow.status == O.TIMEOUT, f"{slow.status}: {slow.detail}")

    neutral = O.neutral()
    suite.check("the neutral action releases every control",
                neutral["move"] == (0.0, 0.0)
                and not any(neutral[key] for key in
                            ("grab", "interact", "stop", "ready")),
                str(neutral))

    # A press cycle has to contain a release, because Grab only fires on the
    # rising edge.
    option = O.Option()
    presses = [option._press_grab(None, (1.0, 0.0))["grab"]
               for _ in range(O.PRESS_TICKS + O.RELEASE_TICKS
                              + O.SETTLE_TICKS)]
    suite.check("a grab cycle presses then releases",
                presses[0] and not presses[-1],
                "".join("1" if p else "0" for p in presses))

    # An uncontrollable frame must produce neutral input, not option progress.
    ctx = context()
    ctx.world.paused = True
    held = O.Idle(1.0).start(ctx)
    action = held.act(ctx)
    suite.check("a paused frame produces neutral input",
                action == O.neutral(), str(action))


def test_model(suite):
    suite.section("model")
    game = mockgame.MockPlateUp(SMOKE, seed=2)
    frame = game.observation()
    suite.check("the model emits an obs_0.1-shaped frame",
                {"kind", "tick", "players", "appliances", "groups",
                 "customers", "day_length"} <= set(frame),
                f"{len(frame)} fields")
    suite.check("the model refuses a layout for another recipe",
                _raises(lambda: mockgame.MockPlateUp(GOLDEN), ValueError),
                "burger layout rejected")

    # Cooking must reach every stage in order and finally burn.
    hob = game.hobs[0]
    item = game._new_item(game.chain.raw)
    game.contents[hob["e"]] = item
    seen = []
    for _ in range(4000):
        game._advance_processes()
        if not seen or seen[-1] != item.name:
            seen.append(item.name)
        if game.chain.is_waste(item.name):
            break
    suite.check("the cook chain visits every stage in order",
                seen == list(game.chain.sequence), " -> ".join(seen))

    # Collision: the chef cannot walk into an appliance tile.
    blocked = next(iter(game.blocked))
    suite.check("blocked tiles reject the chef",
                game._collides(float(blocked[0]), float(blocked[1])),
                f"tile {blocked}")

    game.reset()
    start = (game.player["x"], game.player["z"])
    tile = K.tile_of(*start)
    # Pick a direction with room in it: the chef starts beside the hobs and a
    # walk straight into an appliance measures the collision model, not the
    # movement model.
    direction = next(
        (step for step in ((1, 0), (-1, 0), (0, 1), (0, -1))
         if all((tile[0] + step[0] * n, tile[1] + step[1] * n)
                not in game.blocked for n in (1, 2))),
        None)
    suite.check("the chef starts somewhere with room to walk",
                direction is not None, f"start tile {tile}")
    if direction is not None:
        for _ in range(60):
            game.step({"move": (float(direction[0]), float(direction[1]))})
        moved = K.distance(start, (game.player["x"], game.player["z"]))
        suite.check("holding a direction moves the chef",
                    moved > 0.5,
                    f"{moved:.2f} units in 60 frames going {direction}")
        speed = moved / (60 * mockgame.FRAME_SECONDS)
        suite.check("modelled speed is inside the measured envelope",
                    speed <= mockgame.MAX_SPEED + 1e-6,
                    f"{speed:.2f} of {mockgame.MAX_SPEED} units/s")

    # Walking into an appliance must stop the chef rather than pass through.
    game.reset()
    before = (game.player["x"], game.player["z"])
    toward = None
    tile = K.tile_of(*before)
    for step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if (tile[0] + step[0], tile[1] + step[1]) in game.blocked:
            toward = step
            break
    if toward is not None:
        for _ in range(120):
            game.step({"move": (float(toward[0]), float(toward[1]))})
        travelled = K.distance(before, (game.player["x"], game.player["z"]))
        suite.check("an appliance stops the chef",
                    travelled < 1.0, f"{travelled:.2f} units into {toward}")


def test_service(suite):
    suite.section("service")
    boards = service.run_mock(SMOKE, episodes=3, seed=1, verbose=False)
    suite.check("the reference controller serves every group",
                all(board["served"] >= 4 for board in boards),
                str([board["served"] for board in boards]))
    suite.check("no group is lost",
                all(board["lost"] == 0 for board in boards),
                str([board["lost"] for board in boards]))
    suite.check("nothing is ruined",
                all(board["ruined"] == 0 for board in boards),
                str([board["ruined"] for board in boards]))

    scarce = service.run_mock(SMOKE, episodes=2, seed=4, plates=1,
                              verbose=False)
    suite.check("one plate still completes the day through the wash loop",
                all(board["served"] >= 4 and board["lost"] == 0
                    for board in scarce),
                str([board["served"] for board in scarce]))

    busy = service.run_mock(SMOKE, episodes=2, seed=9, groups=10, interval=9,
                            verbose=False)
    suite.check("a saturated day loses nobody",
                all(board["lost"] == 0 for board in busy),
                str([(board["served"], board["lost"]) for board in busy]))

    late = service.run_mock(SMOKE, episodes=2, seed=6, min_stage=3,
                            verbose=False)
    suite.check("cooking to well-done never burns a steak",
                all(board["ruined"] == 0 for board in late),
                str([board["ruined"] for board in late]))

    # Pressure combinations that have each produced a real planner bug:
    # a scarce plate under saturation deadlocked the chef holding a cooked
    # steak with every counter full, and a clean plate with nowhere to go
    # made the planner aim at an already-occupied plate stack forever.
    for label, options in (
        ("scarce plates under saturation",
         dict(groups=10, interval=9, plates=1)),
        ("scarce plates while watching the hob",
         dict(groups=10, interval=9, plates=1, watch_hob=True)),
        ("a short crowded day",
         dict(day_length=60.0, groups=8, interval=7)),
    ):
        boards = service.run_mock(
            SMOKE, episodes=2, seed=11, verbose=False, **options)
        suite.check(
            f"{label}: nothing lost, nothing ruined, no option storm",
            all(board["lost"] == 0 and board["ruined"] == 0
                and board["failures"] <= 1 for board in boards),
            str([(board["served"], board["lost"], board["ruined"],
                  board["failures"]) for board in boards]))

    # Working while a steak cooks should beat standing at the hob, and the
    # comparison is a property of the model, not of PlateUp.
    busy_default = service.run_mock(
        SMOKE, episodes=2, seed=21, groups=10, interval=9, verbose=False)
    busy_watching = service.run_mock(
        SMOKE, episodes=2, seed=21, groups=10, interval=9, watch_hob=True,
        verbose=False)
    suite.check("working while a steak cooks serves at least as many",
                min(b["served"] for b in busy_default)
                >= min(b["served"] for b in busy_watching),
                f"{[b['served'] for b in busy_default]} versus "
                f"{[b['served'] for b in busy_watching]} watching")


def test_capability(suite):
    suite.section("capability")
    registry = capability.Registry(controller="test", source="selftest")
    for _ in range(9):
        registry.record("acquire", 1.0, route_tiles=1, target="Hob",
                        status="success")
    registry.record("acquire", None, route_tiles=1, target="Hob",
                    status="failed")
    row, exact = registry.lookup("acquire", "Hob", 1)
    suite.check("an exact context is reported as exact", exact, str(row["distance_band"]))
    suite.check("the success rate is the measured one",
                abs(row["success_rate"] - 0.9) < 1e-9,
                f"{row['success_rate']:.3f}")
    suite.check("the confidence bound is below the point estimate",
                row["success_low"] < row["success_rate"],
                f"{row['success_low']:.3f} < {row['success_rate']:.3f}")

    low, high = capability.wilson_interval(3, 3)
    suite.check("three successes do not imply certainty",
                low < 1.0, f"[{low:.3f}, {high:.3f}]")

    missing, exact = registry.lookup("serve", "Table", 4)
    suite.check("an unmeasured option reports nothing rather than a guess",
                missing is None and not exact, str(missing))

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "registry.json")
        registry.save(path)
        loaded = capability.Registry.load(path)
        suite.check("a saved registry round-trips",
                    len(loaded.summaries) == len(registry.rows),
                    f"{len(loaded.summaries)} rows")

        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
        payload["schema"] = "capability_0.0"
        with open(path, "w", encoding="utf-8") as output:
            json.dump(payload, output)
        suite.check("a mismatched registry schema is refused",
                    _raises(lambda: capability.Registry.load(path),
                            ValueError),
                    "capability_0.0 rejected")


def test_surrogate(suite):
    suite.section("surrogate")
    registry = capability.Registry(controller="reference_v1", source="model")
    runner_registry = capability.Registry(
        controller="reference_v1", source="model")
    service.run_mock(SMOKE, episodes=3, seed=1, verbose=False,
                     registry=runner_registry)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "capability.json")
        runner_registry.save(path)
        loaded = capability.Registry.load(path)

    boards = []
    for episode in range(10):
        sim = SUR.Surrogate(registry=loaded, seed=1 + episode)
        boards.append(SUR.rollout(sim))

    suite.check("the surrogate serves the same number of groups as the model",
                all(board["served"] == 4 for board in boards),
                str(sorted({board["served"] for board in boards})))
    suite.check("the surrogate loses nobody",
                all(board["lost"] == 0 for board in boards),
                str(sorted({board["lost"] for board in boards})))
    suite.check("every transition is inside the calibrated support",
                all(board["support_rate"] == 1.0 for board in boards),
                str(sorted({board["support_rate"] for board in boards})))

    bare = SUR.Surrogate(registry=None, seed=1)
    SUR.rollout(bare)
    suite.check("an uncalibrated surrogate reports zero support",
                bare.support == 0.0, str(bare.support))

    # Uncertainty must cost something: a row with one sample has a lower
    # confidence bound than the same rate with many samples.
    few = capability.wilson_interval(1, 1)[0]
    many = capability.wilson_interval(30, 30)[0]
    suite.check("more evidence buys a higher confidence bound",
                few < many, f"{few:.3f} < {many:.3f}")


def test_env(suite):
    suite.section("env")
    for name, passed, detail in ENV.check(SMOKE, steps=300):
        suite.check(name, passed, detail)

    report = ENV.soak(SMOKE, steps=12000, seed=3)
    suite.check("the random-action soak keeps one observation shape",
                report["observation_lengths"] == [len(
                    encode.Encoder(S.Chain("plain")).field_names())],
                str(report["observation_lengths"]))
    suite.check("the random-action soak reaches a terminal state",
                report["episodes"] > 0
                and all(reason for reason in report["terminal_reasons"]),
                f"{report['episodes']} episodes, "
                f"{report['terminal_reasons']}")
    suite.check("random play does not complete the day",
                "day_complete" not in report["terminal_reasons"],
                str(sorted(report["terminal_reasons"])))

    results = ENV.rollout(SMOKE, episodes=2)
    suite.check("the reference controller finishes the day through the API",
                all(record["terminal"] == "day_complete"
                    for record in results),
                str([record["terminal"] for record in results]))
    suite.check("the reference controller scores above random",
                all(record["reward"] > 0 for record in results),
                str([record["reward"] for record in results]))

    # The encoder must not leak anything the bridge withholds.
    client, world = first_service_world(SMOKE)
    encoder = encode.Encoder(S.Chain("plain"))
    ctx = O.Context(world, S.Chain("plain"))
    names = encoder.field_names()
    suite.check("the encoding has one name per slot",
                len(names) == len(encoder.encode(ctx)),
                f"{len(names)} names, {len(encoder.encode(ctx))} values")
    forbidden = [
        name for name in names
        if any(word in name for word in
               ("can_", "legal", "mask", "best_", "scheduled", "next_arrival"))]
    suite.check("the encoding carries no affordance or future field",
                not forbidden, str(forbidden))


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def test_preparation(suite):
    suite.section("preparation")

    game = mockgame.MockPlateUp(SMOKE, seed=3, preparation=True,
                                popup_seconds=2.0)
    client = ObservationClient(announce=False)
    client.feed(game.dictionary)
    world = client.feed(game.observation())
    suite.check("a preparation frame publishes the start-day checklist",
                world.start_day_warnings is not None and world.day == 0,
                f"day {world.day}, warnings "
                f"{sorted(world.start_day_warnings or {})}")
    suite.check("an open popup captures input and flags an error",
                world.input_captured
                and world.start_day_warnings["popups_open"]
                >= O.WARNING_WARNING,
                f"captured={world.input_captured}, popups_open="
                f"{world.start_day_warnings['popups_open']}")

    # Consent must not be given underneath a popup.
    ctx = O.Context(world, game.chain)
    blocked = O.StartDay().start(ctx)
    blocked.act(ctx)
    suite.check("consent is refused while a popup is open",
                blocked.status == O.INVALID,
                f"{blocked.status}: {blocked.detail}")

    boards = service.run_mock(
        SMOKE, episodes=2, seed=3, verbose=False, preparation=True,
        popup_seconds=2.0)
    suite.check("the controller clears the popup, starts the day and serves",
                all(board["served"] >= 4 and board["lost"] == 0
                    for board in boards),
                str([(board["served"], board["lost"]) for board in boards]))

    # Consent toggles, so pressing twice must un-ready. The model reproduces
    # that, and a controller that re-presses would stall the day forever.
    game = mockgame.MockPlateUp(SMOKE, seed=3, preparation=True)
    ready = ENV.decode_action(
        ENV.encode_action({"move": (0.0, 0.0), "ready": True}))
    idle = ENV.decode_action(ENV.encode_action({"move": (0.0, 0.0)}))
    game.step(ready)
    first = game.ready
    game.step(idle)
    game.step(ready)
    suite.check("consent toggles rather than latching",
                first and not game.ready,
                f"after one press {first}, after two {game.ready}")


def test_learning(suite):
    suite.section("learning")

    human = DATA.from_demonstration(SMOKE)
    suite.check("a human recording yields aligned pairs",
                len(human) > 100
                and human.observations.shape[1] == len(
                    encode.Encoder(S.Chain("plain")).field_names()),
                f"{len(human)} samples of width "
                f"{human.observations.shape[1]}")
    suite.check("the human dataset carries real movement, not a constant",
                len(human.head_distribution()[0]) > 1,
                str(human.head_distribution()[0]))
    suite.check("an observation-only recording is refused, not silently empty",
                _raises(lambda: DATA.from_demonstration(GOLDEN), ValueError),
                "the golden trace has no demo_input frames")

    small = DATA.from_model(SMOKE, episodes=2, seed=500, verbose=False)
    suite.check("a model dataset carries goals",
                small.goal_conditioned
                and small.goals.shape[1] == encode.GoalEncoder().size,
                f"{small.goals.shape[1]} goal features")
    suite.check("policy input is state then goal",
                small.inputs.shape[1]
                == small.observations.shape[1] + small.goals.shape[1],
                f"{small.inputs.shape[1]} inputs")

    training, validation = small.split(fraction=0.5, seed=0)
    overlap = set(training.episodes.tolist()) & set(
        validation.episodes.tolist())
    suite.check("the validation split shares no episode with training",
                not overlap, f"overlap {sorted(overlap)}")

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "data.npz")
        small.save(path)
        reloaded = DATA.Dataset.load(path)
        suite.check("a dataset round-trips",
                    len(reloaded) == len(small)
                    and reloaded.goals.shape == small.goals.shape,
                    f"{len(reloaded)} samples")

        policy = POLICY.ClonedPolicy(
            small.inputs.shape[1], POLICY.head_sizes(), hidden=16, seed=0)
        history = policy.fit(training, epochs=4, seed=0, verbose=False)
        suite.check("training reduces the loss",
                    history[-1]["loss"] < history[0]["loss"],
                    f"{history[0]['loss']:.4f} -> {history[-1]['loss']:.4f}")

        scores = policy.score(validation)
        suite.check("scoring reports one entry per action head",
                    len(scores["per_head"]) == len(POLICY.head_sizes()),
                    f"{len(scores['per_head'])} heads")

        checkpoint = os.path.join(directory, "policy.npz")
        policy.save(checkpoint)
        loaded = POLICY.ClonedPolicy.load(checkpoint)
        sample = small.inputs[0]
        suite.check("a policy round-trips to the same action",
                    loaded.act(sample) == policy.act(sample),
                    str(policy.act(sample)))
        suite.check("greedy action selection is deterministic",
                    policy.act(sample) == policy.act(sample),
                    "same action twice")

    results = EVAL.rollout_reference(layout=SMOKE, episodes=2, seed=77)
    summary = EVAL.summarise(results)
    completion = summary["day_completion"]
    suite.check("the harness reports a day-completion interval",
                completion["confidence_low"] <= completion["rate"]
                <= completion["confidence_high"],
                f"{completion['rate']:.2f} in "
                f"[{completion['confidence_low']:.2f}, "
                f"{completion['confidence_high']:.2f}]")
    suite.check("the harness reports zero human interventions",
                summary["human_interventions"] == 0, "0")
    suite.check("the harness separates the best episode from the typical",
                summary["best_episode"] is not None
                and summary["best_episode"]["served"]
                >= summary["served"]["median"],
                f"best {summary['best_episode']['served']} versus median "
                f"{summary['served']['median']}")


def test_antihack(suite):
    suite.section("antihack")
    for entry in antihack.run_all(verbose=False):
        if "NOT TESTED" in entry["name"]:
            continue
        suite.check(entry["name"], entry["passed"], entry["detail"])


def test_manifest(suite):
    suite.section("manifest")
    payload = manifest.build(
        artifacts=[SMOKE], recording=SMOKE, note="selftest",
        scenario="offline")
    suite.check("a manifest records the pinned build from the recording",
                payload["pinned_build"]["game_version"] == "1.4.3-FF8F"
                and payload["pinned_build"]["mod_hash"],
                payload["pinned_build"]["bridge_version"])
    suite.check("a manifest records every schema version",
                all(payload["schemas"].values())
                and payload["schemas"]["encode_schema"] == encode.VERSION,
                f"{len(payload['schemas'])} schemas")
    suite.check("a manifest hashes its artifacts",
                len(payload["artifacts"][0]["sha256"]) == 64,
                payload["artifacts"][0]["sha256"][:16])
    suite.check("a manifest states its evidence class",
                "offline" in payload["evidence_class"],
                payload["evidence_class"][:40])

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "manifest.json")
        copy = os.path.join(directory, "artifact.txt")
        with open(copy, "w", encoding="utf-8") as handle:
            handle.write("original")
        written = manifest.build(artifacts=[copy], recording=SMOKE)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(written, handle)

        _payload, results = manifest.check(path)
        suite.check("an unchanged artifact matches its manifest",
                    all(status == "MATCH" for _t, status, _d in results),
                    str([status for _t, status, _d in results]))

        with open(copy, "w", encoding="utf-8") as handle:
            handle.write("tampered")
        _payload, results = manifest.check(path)
        suite.check("a changed artifact is detected",
                    any(status == "CHANGED" for _t, status, _d in results),
                    str([status for _t, status, _d in results]))


def _replay_livecheck(path, interval):
    """Drive the live checker from a recording, as the live loop would."""
    checker = livecheck.LiveCheck()
    client = ObservationClient(announce=False)
    clock = 0.0
    with open(path, encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            if message.get("kind") == "hello":
                class _Shim:
                    pass
                client.b = _Shim()
                client.b.hello = message
                checker.handshake(client)
                continue
            world = client.feed(message)
            if world is None:
                if message.get("kind") == "dict":
                    checker.dictionary(client)
                continue
            clock += interval
            checker.observe(world, clock)
    return checker


def test_livecheck(suite):
    suite.section("livecheck")

    steak = _replay_livecheck(SMOKE, 0.035)
    states = {key: check.state for key, check in steak.checks.items()}
    suite.check("the live checker finds no contradiction in the steak day",
                livecheck.FAIL not in states.values(),
                str({k: v for k, v in states.items()
                     if v == livecheck.FAIL}) or "no failures")
    suite.check("it confirms the rotation convention from displacement alone",
                states["rotation_zero"] == livecheck.PASS,
                steak.checks["rotation_zero"].detail)
    suite.check("it confirms the provider and table findings live",
                states["provider_infinity"] == livecheck.PASS
                and states["table_unresolvable"] == livecheck.PASS
                and states["group_locates_table"] == livecheck.PASS,
                "provider, table linkage and group position")
    suite.check("it confirms entity recycling across the day boundary",
                states["entity_recycling"] == livecheck.PASS,
                steak.checks["entity_recycling"].detail)
    suite.check("it leaves untriggered checks PENDING rather than passing them",
                states["cook_timings"] == livecheck.PENDING
                and states["wash_rate"] == livecheck.PENDING,
                "the smoke recording never cooked or washed")

    # The golden trace was recorded with bridge 0.2.4, so the provenance check
    # must fail on it. A checker that passed everything would be useless.
    burger = _replay_livecheck(GOLDEN, 0.044)
    suite.check("it rejects a recording made with a different mod build",
                burger.checks["mod_hash"].state == livecheck.FAIL,
                burger.checks["mod_hash"].detail[:60])
    suite.check("it still confirms the build-independent findings",
                burger.checks["floor_mess"].state == livecheck.PASS
                and burger.checks["group_locates_table"].state
                == livecheck.PASS,
                "floor mess and group position hold on the burger day too")
    suite.check("its report and payload are well formed",
                "livecheck_0.1" in steak.report()
                and len(steak.payload()["checks"]) == len(steak.checks),
                f"{len(steak.payload()['checks'])} checks serialised")


GROUPS = (
    ("facts", test_facts),
    ("geometry", test_geometry),
    ("steak", test_steak),
    ("options", test_options),
    ("model", test_model),
    ("service", test_service),
    ("capability", test_capability),
    ("surrogate", test_surrogate),
    ("env", test_env),
    ("preparation", test_preparation),
    ("learning", test_learning),
    ("antihack", test_antihack),
    ("manifest", test_manifest),
    ("livecheck", test_livecheck),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--only", action="append")
    args = parser.parse_args()

    suite = Suite()
    for name, function in GROUPS:
        if args.only and name not in args.only:
            continue
        function(suite)
    ok = suite.report()

    if args.json_path:
        os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump(suite.payload(), output, indent=2, sort_keys=True)
        print("wrote " + os.path.normpath(args.json_path))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
