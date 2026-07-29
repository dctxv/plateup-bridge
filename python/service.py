r"""
Reference steak service controller, and the loop that runs it.

    python python/service.py mock                  offline, against mockgame
    python python/service.py mock --episodes 5 --capability runs/capability/mock.json
    python python/service.py run                   live, needs PlateUp and F9

**This is a scripted baseline, not the agent.** Specification section 2.3
disallows scripted cook-plate-serve control and deterministic pathfinding
inside a scored run, so nothing this module produces may be reported as
autonomous play. It exists for three legitimate jobs:

  * generating option traces to behaviour-clone from (section 10.4 step 1
    permits scripted scenario labels used only to construct training data);
  * measuring option duration and failure distributions for the capability
    registry, which is what the semi-MDP surrogate is calibrated on; and
  * being the baseline every learned policy is scored against (section 17.3).

The policy itself is deliberately plain, because a complicated baseline is
harder to beat for reasons that have nothing to do with learning. It is a
priority list with pre-emption, which is the shape specification section 8.4
describes for the task planner, so a learned planner can be dropped in behind
the same option interface.

Day-1 steak reasoning, in the order the list applies it:

  1. consent to the day starting, because nothing else can happen first;
  2. get rid of waste, because carrying it blocks every other option;
  3. rescue anything about to burn, because that loss is unrecoverable;
  4. finish what is in hand, because a half-finished dish is worth nothing;
  5. serve a group that is waiting, because patience only drains then;
  6. keep one plated steak buffered, because orders arrive without warning
     and a single-dish menu makes the safe inventory obvious;
  7. recycle plates, because four starting plates is the real constraint;
  8. otherwise stand still, which is a decision and not a gap.
"""

import argparse
import json
import os
import sys
import time

import capability
import kitchen as K
import options as O
import steak as S
from observe import ObservationClient

# One plated steak ready and one on the heat. Orders are not visible until
# WaitForFood, so preparing generic inventory is the only legal way to be
# ready; specification section 6.2 permits exactly that and forbids acting on
# a specific hidden order.
TARGET_BUFFER = 1


class SteakPlanner:
    """Chooses the next option. Stateless apart from the buffer surface."""

    def __init__(self, chain, min_stage=1, target_buffer=TARGET_BUFFER,
                 watch_hob=False):
        self.chain = chain
        self.min_stage = min_stage
        self.target_buffer = target_buffer
        # Whether to stand at the hob for the whole cook. Off by default: the
        # priority list can lift through its own rules, which frees the chef
        # to wash and carry while a steak cooks and lets a second hob be
        # loaded. `--watch-hob` keeps the safer variant available so the two
        # can be measured rather than argued about.
        self.watch_hob = watch_hob
        self.last_reason = ""

    # -- helpers ----------------------------------------------------------

    def _hobs(self, ctx):
        return ctx.kitchen.role("cook")

    def _sinks(self, ctx):
        return ctx.kitchen.role("wash")

    def _bins(self, ctx):
        return [
            a for a in ctx.kitchen.role("bin")
            if not a.get("name", "").startswith("Wheelie")]

    def _plate_provider(self, ctx):
        """A plate stack that will actually hand out a plate.

        A stack with something resting on its surface is not one: the grab
        picks the surface item up instead of drawing a plate.
        """
        for appliance in ctx.inventory.plate_providers:
            if appliance.get("held") is not None:
                continue
            maximum = appliance.get("maximum") or 0
            if maximum == 0 or (appliance.get("available") or 0) > 0:
                return appliance
        return None

    def _raw_provider(self, ctx):
        providers = ctx.inventory.raw_providers
        return providers[0] if providers else None

    def _free_surface(self, ctx, near=None):
        """An empty countertop, preferring one close to a reference point."""
        free = [
            a for a in ctx.kitchen.role("surface") if a.get("held") is None]
        if not free:
            return None
        if near is None:
            near = ctx.position or (0.0, 0.0)
        return min(free, key=lambda a: K.distance((a["x"], a["z"]), near))

    def _free_hob(self, ctx):
        for hob in self._hobs(ctx):
            if hob.get("held") is None:
                return hob
        return None

    def _hob_with_servable(self, ctx):
        for hob in self._hobs(ctx):
            item = hob.get("held")
            if item is None:
                continue
            if self.chain.is_servable(item.get("name")):
                return hob, item
        return None, None

    def _hob_with_waste(self, ctx):
        for hob in self._hobs(ctx):
            item = hob.get("held")
            if item is not None and self.chain.is_waste(item.get("name")):
                return hob
        return None

    def _waiting_groups(self, ctx):
        """Seated groups with an unsatisfied order, least patience first."""
        waiting = []
        for group in ctx.world.groups:
            for order in group.get("orders", ()):
                if order.get("satisfied"):
                    continue
                if order.get("name") != self.chain.plated:
                    continue
                if ctx.kitchen.table_for_group(group) is None:
                    continue
                waiting.append(group)
                break
        waiting.sort(key=lambda g: g.get("patience_frac", 1.0))
        return waiting

    def _seated_unserved(self, ctx):
        """Groups already at a table that have not been fed.

        Their order is not in the buffer yet, and the planner is forbidden to
        act as though a hidden order were known. It does not have to: the menu
        has one dish, the group is visible on screen, and a human cooks ahead
        on exactly that basis. What is being anticipated is demand, not a
        specific hidden choice.
        """
        pending = 0
        for group in ctx.world.groups:
            if ctx.kitchen.table_for_group(group) is None:
                continue
            orders = group.get("orders", ())
            if not orders:
                pending += 1
                continue
            if any(not order.get("satisfied") for order in orders):
                pending += 1
        return pending

    def _demand(self, ctx):
        return max(self.target_buffer, self._seated_unserved(ctx))

    def _stash(self, ctx):
        """Put whatever is in hand somewhere sensible so hands are free.

        Every branch is a legal contextual grab: PlateUp has no free drop, so
        an option that cannot find an accepting target has to return None and
        let the planner try something else rather than press at empty floor.
        """
        held = ctx.held
        if held is None:
            return None
        name = held.get("name")

        if self.chain.is_waste(name) or S.is_ruined(name):
            bins = self._bins(ctx)
            return O.BinWaste(bins[0]) if bins else None

        if self.chain.is_raw(name):
            hob = self._free_hob(ctx)
            if hob is not None:
                return O.PlaceItem(hob)

        if self.chain.is_servable(name):
            provider = self._plate_provider(ctx)
            if provider is not None:
                return O.PlaceItem(provider, expect_held=self.chain.plated)

        if S.is_dirty_plate(name):
            sinks = self._sinks(ctx)
            if sinks and sinks[0].get("held") is None:
                return O.PlaceItem(sinks[0])

        surface = self._free_surface(ctx)
        if surface is not None:
            return O.PlaceItem(surface)

        if name == S.CLEAN_PLATE:
            # A plate stack takes its own plates back, which is the only
            # capacity that reappears when every counter is full. It has to be
            # empty first: a provider that is already holding something on its
            # surface refuses the next item, and an earlier version of this
            # branch kept aiming at a full stack until the option gave up.
            for provider in ctx.inventory.plate_providers:
                if provider.get("held") is not None:
                    continue
                maximum = provider.get("maximum") or 0
                if maximum == 0 or (provider.get("available") or 0) < maximum:
                    return O.PlaceItem(provider)

        # Last resort: a spare hob. For a plate or a plated dish this is free,
        # because neither has a cook transition. For a cooked steak it is not:
        # the chain carries on toward Burned. It is still the right move,
        # because the alternative is standing still holding the steak forever,
        # which is what an earlier version of this method did when every
        # counter was full and there was no clean plate. `_rule_rescue`
        # outranks everything except waste disposal, so a steak parked on a
        # hob is lifted again on `is_bad` rather than left to burn.
        hob = self._free_hob(ctx)
        if hob is not None:
            return O.PlaceItem(hob)

        sink = next(
            (s for s in self._sinks(ctx) if s.get("held") is None), None)
        if sink is not None and not S.is_dirty_plate(name):
            return O.PlaceItem(sink)
        return None

    def _buffered_dishes(self, ctx):
        return [
            record for record in ctx.inventory.plated
            if record["on"] is not None
            and not record["on"].get("name", "").startswith("Table")]

    def _dirty_plates(self, ctx):
        """Dirty plates the chef can pick up, nearest first."""
        reachable = [
            record for record in ctx.inventory.dirty_plates
            if record["on"] is not None]
        position = ctx.position or (0.0, 0.0)
        reachable.sort(key=lambda record: K.distance(
            (record["on"]["x"], record["on"]["z"]), position))
        return reachable

    # -- the list ---------------------------------------------------------

    def choose(self, ctx):
        for rule in (
            self._rule_start_day,
            self._rule_dump_waste,
            self._rule_rescue,
            self._rule_serve,
            self._rule_deliver,
            self._rule_finish_held,
            self._rule_lift_cooked,
            self._rule_recycle_plates,
            self._rule_cook,
            self._rule_tidy,
        ):
            option = rule(ctx)
            if option is not None:
                self.last_reason = rule.__name__[len("_rule_"):]
                return option
        self.last_reason = "idle"
        return O.Idle(0.4)

    def _rule_start_day(self, ctx):
        if ctx.world.start_day_warnings is not None:
            return O.StartDay()
        return None

    def _rule_dump_waste(self, ctx):
        held = ctx.held_name
        if held is None:
            return None
        if not (self.chain.is_waste(held) or S.is_ruined(held)):
            return None
        bins = self._bins(ctx)
        if not bins:
            return None
        return O.BinWaste(bins[0])

    def _rule_rescue(self, ctx):
        """Lift anything whose next transition is waste.

        `is_bad` is a lookahead flag, so it is true while the item is still
        servable. That is exactly the moment to act, and it is why the flag is
        not counted as a failure anywhere in this project. A burn is the only
        loss in this recipe that cannot be recovered, so it outranks serving.
        """
        at_risk = None
        for hob in self._hobs(ctx):
            item = hob.get("held")
            if item is None or not item.get("is_bad"):
                continue
            if self.chain.is_servable(item.get("name")):
                at_risk = hob
                break
        if at_risk is None:
            if ctx.held is not None:
                return None
            waste_hob = self._hob_with_waste(ctx)
            if waste_hob is not None:
                return O.AcquireItem(waste_hob)
            return None
        if ctx.held is not None:
            return self._stash(ctx)
        return O.WatchCook(at_risk, self.chain, min_stage=1)

    def _rule_finish_held(self, ctx):
        """Turn whatever is in hand into something more useful."""
        held = ctx.held
        if held is None:
            return None
        name = held.get("name")

        if self.chain.is_servable(name):
            provider = self._plate_provider(ctx)
            if provider is not None:
                return O.PlaceItem(provider, expect_held=self.chain.plated)
            plate = next(
                (record for record in ctx.inventory.clean_plates
                 if record["on"] is not None), None)
            if plate is not None:
                return O.PlaceItem(plate["on"], expect_held=self.chain.plated)
            return self._stash(ctx)

        if S.is_dirty_plate(name):
            sinks = self._sinks(ctx)
            if sinks and sinks[0].get("held") is None:
                return O.wash_plate(sinks[0], self.chain)
            return self._stash(ctx)

        if name == S.CLEAN_PLATE:
            hob, _item = self._hob_with_servable(ctx)
            if hob is not None:
                return O.PlaceItem(hob, expect_held=self.chain.plated)
            return self._stash(ctx)

        if self.chain.is_raw(name):
            hob = self._free_hob(ctx)
            if hob is not None:
                if not self.watch_hob:
                    return O.PlaceItem(hob)
                return O.Sequence(
                    "cook_one",
                    (lambda ctx_: O.PlaceItem(hob),
                     lambda ctx_: O.WatchCook(
                         hob, self.chain, min_stage=self.min_stage)),
                    timeout=120.0)
            return self._stash(ctx)

        if name == self.chain.plated:
            # Nobody is waiting yet. Buffer it rather than stand holding it,
            # so the next order can be delivered immediately.
            return self._stash(ctx)

        return self._stash(ctx)

    def _rule_serve(self, ctx):
        held = ctx.held
        if held is None or held.get("name") != self.chain.plated:
            return None
        waiting = self._waiting_groups(ctx)
        if not waiting:
            return None
        return O.ServeOrder(waiting[0], dish=self.chain.plated)

    def _rule_deliver(self, ctx):
        """A group is waiting and a finished dish exists somewhere.

        Whatever is in hand comes second to this: patience only drains while a
        group waits, so anything that delays delivery is paid for directly.
        """
        if not self._waiting_groups(ctx):
            return None
        buffered = self._buffered_dishes(ctx)
        if not buffered:
            return None
        if ctx.held is not None:
            return self._stash(ctx)
        return O.AcquireItem(buffered[0]["on"], want=self.chain.plated)

    def _rule_lift_cooked(self, ctx):
        if ctx.held is not None:
            return None
        hob, _item = self._hob_with_servable(ctx)
        if hob is None:
            return None
        return O.WatchCook(hob, self.chain, min_stage=self.min_stage)

    def _rule_recycle_plates(self, ctx):
        """Four starting plates is the binding constraint on a steak day.

        Clearing a table also frees it for the next group, so this runs ahead
        of starting another steak rather than behind it.
        """
        if ctx.held is not None:
            return None
        dirty = self._dirty_plates(ctx)
        if not dirty:
            return None
        sinks = self._sinks(ctx)
        record = dirty[0]
        holder = record["on"]
        if holder is not None and "Sink" in holder.get("name", ""):
            if sinks:
                return O.wash_plate(sinks[0], self.chain)
            return None
        if not sinks or sinks[0].get("held") is not None:
            return None
        return O.AcquireItem(holder)

    def _rule_cook(self, ctx):
        if ctx.held is not None:
            return None
        # Work in progress is anything already on its way to being a meal: a
        # finished dish, a cooked steak waiting for a plate, or a cut on the
        # heat. Counting only finished dishes let the counters silently fill
        # with cooked steaks that no plate would ever arrive for, and counting
        # a Rare steak as finished stalled the kitchen whenever the doneness
        # target was set higher than Rare.
        ready = len(self._buffered_dishes(ctx))
        on_heat = 0
        for record in ctx.inventory.servable + ctx.inventory.raw:
            holder = record["on"]
            on_hob = holder is not None and "Hob" in holder.get("name", "")
            stage = self.chain.stage_number(record["item"].get("name")) or 0
            if on_hob and stage < self.min_stage:
                on_heat += 1
            else:
                ready += 1
        if ready + on_heat > self._demand(ctx):
            return None
        hob = self._free_hob(ctx)
        provider = self._raw_provider(ctx)
        if hob is None or provider is None:
            return None
        if ctx.inventory.plates_available() <= 0:
            # Nothing this steak could ever be plated on. Wash first.
            return None
        if self.watch_hob:
            return O.cook_one(
                hob, provider, self.chain, min_stage=self.min_stage)
        return O.start_cook(hob, provider, self.chain)

    def _rule_tidy(self, ctx):
        if ctx.held is None:
            return None
        return self._stash(ctx)


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------


class Runner:
    """Drives one planner against one world source.

    The source is either the live bridge or `mockgame`. Both hand back
    obs_0.1 frames and take act_0.1 fields, so the agent code below cannot
    tell them apart, which is the point: what runs offline is what runs live.
    """

    def __init__(self, planner, chain, registry=None, verbose=False):
        self.planner = planner
        self.chain = chain
        self.registry = registry
        self.verbose = verbose
        self.option = None
        self.blocked = set()
        self.history = []
        self.ticks = 0

    def act(self, ctx):
        if self.option is None or self.option.done:
            self._retire(ctx)
            self.option = self.planner.choose(ctx).start(ctx)
            if self.verbose:
                print(f"  t={ctx.tick} {self.planner.last_reason} -> "
                      f"{self.option.name}")
        action = self.option.act(ctx)
        if self.option.done:
            self._retire(ctx)
        self.ticks += 1
        return action

    def _retire(self, ctx):
        option = self.option
        if option is None:
            return
        self.option = None
        if not option.done:
            # Retired mid-flight, which is what pre-emption looks like from
            # the registry's point of view. Recording it as `running` would
            # invent an outcome the option never reached.
            option.finish(O.PREEMPTED, "retired before completing")
        # Carry learned obstructions forward: they are keyed on tiles, which
        # survive the entity rebuild at the day boundary.
        self.blocked |= getattr(option, "_blocked_learned", set())
        summary = option.summary(ctx)
        self.history.append(summary)
        # Waiting is a decision, not a capability, and recording it would bury
        # every real row under thousands of identical idle samples.
        if self.registry is not None and summary["option"] != O.Idle.name:
            self.registry.record(
                option=summary["option"],
                seconds=summary.get("seconds"),
                route_tiles=summary.get("route_length", 0),
                target=getattr(option, "target_name", None),
                status=summary["status"],
                presses=summary.get("presses", 0),
                replans=summary.get("replans", 0))
        if self.verbose and summary["status"] != O.SUCCESS:
            print(f"     {summary['option']}: {summary['status']} "
                  f"({summary['detail']})")

    def context(self, world):
        return O.Context(world, self.chain, blocked_hints=self.blocked)

    def outcome_counts(self):
        counts = {}
        for record in self.history:
            key = (record["option"], record["status"])
            counts[key] = counts.get(key, 0) + 1
        return counts


# --------------------------------------------------------------------------
# offline episode
# --------------------------------------------------------------------------


def run_mock(path, episodes=1, seed=1, min_stage=1, verbose=False,
             registry=None, max_seconds=400.0, plates=None, groups=None,
             day_length=None, interval=None, watch_hob=False):
    """Play whole days against the model. Offline; nothing here is evidence."""
    import mockgame

    results = []
    for episode in range(episodes):
        game = mockgame.MockPlateUp(
            path, seed=seed + episode, plates=plates, groups=groups,
            day_length=day_length, interval=interval)
        client = ObservationClient(announce=False)
        client.feed(game.dictionary)
        chain = game.chain
        planner = SteakPlanner(chain, min_stage=min_stage,
                               watch_hob=watch_hob)
        runner = Runner(planner, chain, registry=registry, verbose=verbose)

        frame = game.observation()
        action = {}
        guard = int(max_seconds / mockgame.FRAME_SECONDS)
        for _ in range(guard):
            world = client.feed(frame)
            ctx = runner.context(world)
            action = runner.act(ctx)
            frame = game.step(action)
            if game.day_finished or game.game_over:
                break

        runner._retire(runner.context(client.feed(frame)))
        board = game.scoreboard()
        board["episode"] = episode
        board["seed"] = seed + episode
        board["options"] = len(runner.history)
        board["failures"] = sum(
            1 for record in runner.history
            if record["status"] != O.SUCCESS)
        board["outcomes"] = {
            f"{option}:{status}": count
            for (option, status), count in sorted(
                runner.outcome_counts().items())}
        results.append(board)
        if verbose:
            print(json.dumps(board, indent=2))
    return results


# --------------------------------------------------------------------------
# live episode
# --------------------------------------------------------------------------


def run_live(min_stage=1, verbose=True, registry=None, max_minutes=30.0,
             force_cut=None, status_every=300, watch_hob=False):
    """Drive the real game. Requires PlateUp, the mod, and F9 override on.

    Nothing in this stack has been run against PlateUp, so the loop is written
    to fail loudly and stop cleanly rather than to push through: it refuses a
    kitchen that is not serving the configured recipe, waits for override
    instead of sending commands nobody is listening to, and always releases
    every control on the way out.
    """
    with ObservationClient() as client:
        world = client.recv()

        cut = force_cut or S.infer_cut(world)
        if cut is None:
            raise SystemExit(
                "this restaurant does not provide a steak ingredient and no "
                "steak dish has been ordered. Refusing to run a steak planner "
                "in it; pass --cut to override.")
        chain = S.Chain(cut)
        S.Registry(
            client.item_names, client.appliance_names, client.process_names,
            chain.cut).require()
        print(f"recipe: {chain}")

        if not world.override:
            print(">>> press F9 in game to hand control to the bridge <<<")
            while not world.override:
                client.b.send()
                world = client.recv()
            print("override on")

        planner = SteakPlanner(chain, min_stage=min_stage,
                               watch_hob=watch_hob)
        runner = Runner(planner, chain, registry=registry, verbose=verbose)

        started = time.monotonic()
        deadline = started + max_minutes * 60.0
        reason = "time limit"
        try:
            while time.monotonic() < deadline:
                ctx = runner.context(world)
                client.b.send(**runner.act(ctx))
                world = client.recv()

                if status_every and runner.ticks % status_every == 0:
                    print(f"  t={world.tick} day {world.day} "
                          f"{world.seconds_elapsed:.0f}/{world.day_length:.0f}s "
                          f"${world.money} lives={world.lives} "
                          f"held={ctx.held_name} "
                          f"opts={len(runner.history)} "
                          f"dropped={world.cmds_dropped}/"
                          f"{world.outbound_frames_dropped}")

                if world.game_over:
                    reason = f"game over (loss reason {world.loss_reason})"
                    break
                if not world.override:
                    reason = "override switched off"
                    break
        except KeyboardInterrupt:
            reason = "interrupted"
        finally:
            # Specification section 7.4: release everything on the way out,
            # whatever ended the run.
            runner._retire(runner.context(world))
            for _ in range(3):
                client.b.send()

        print(f"stopped: {reason} after "
              f"{(time.monotonic() - started) / 60.0:.1f} minutes, "
              f"{len(runner.history)} options")
    return runner


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    mock = subparsers.add_parser("mock")
    mock.add_argument(
        "--layout", default=os.path.join("runs", "demos", "smoke.jsonl"))
    mock.add_argument("--episodes", type=int, default=1)
    mock.add_argument("--seed", type=int, default=1)
    mock.add_argument("--min-stage", type=int, default=1)
    mock.add_argument("--plates", type=int)
    mock.add_argument("--groups", type=int)
    mock.add_argument("--day-length", type=float, dest="day_length")
    mock.add_argument("--interval", type=float)
    mock.add_argument("--watch-hob", action="store_true", dest="watch_hob")
    mock.add_argument("--capability")
    mock.add_argument("--json", dest="json_path")
    mock.add_argument("--quiet", action="store_true")

    live = subparsers.add_parser("run")
    live.add_argument("--min-stage", type=int, default=1)
    live.add_argument("--minutes", type=float, default=30.0)
    live.add_argument("--cut", choices=sorted(S.CUTS))
    live.add_argument("--watch-hob", action="store_true", dest="watch_hob")
    live.add_argument("--capability")

    args = parser.parse_args()

    if args.command == "mock":
        registry = capability.Registry(
            controller="reference_v1",
            source=f"mockgame:{os.path.normpath(args.layout)}")
        results = run_mock(
            args.layout, episodes=args.episodes, seed=args.seed,
            min_stage=args.min_stage, verbose=not args.quiet,
            registry=registry, plates=args.plates, groups=args.groups,
            day_length=args.day_length, interval=args.interval,
            watch_hob=args.watch_hob)
        print()
        for board in results:
            print(f"episode {board['episode']}: served {board['served']}, "
                  f"lost {board['lost']}, ruined {board['ruined']}, "
                  f"money {board['money']}, options {board['options']}, "
                  f"failures {board['failures']}")
        print()
        print(registry.report())
        if args.capability:
            print("\nwrote " + registry.save(args.capability))
        if args.json_path:
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as output:
                json.dump(results, output, indent=2, sort_keys=True)
            print("wrote " + os.path.normpath(args.json_path))
        return 0 if all(board["served"] > 0 for board in results) else 1

    registry = capability.Registry(
        controller="reference_v1", source="live")
    run_live(min_stage=args.min_stage, registry=registry,
             max_minutes=args.minutes, force_cut=args.cut,
             watch_hob=args.watch_hob)
    print(registry.report())
    if args.capability:
        print("\nwrote " + registry.save(args.capability))
    return 0


if __name__ == "__main__":
    sys.exit(main())
