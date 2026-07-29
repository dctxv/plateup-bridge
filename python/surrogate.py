r"""
Semi-MDP surrogate for steak service.

    python python/surrogate.py demo
    python python/surrogate.py calibrate runs/capability/mock.json
    python python/surrogate.py compare runs/capability/mock.json

Specification section 9 makes this mandatory from Project 1 task-planner work
onward, not a fallback: real PlateUp yields roughly 35 episodes an hour at 1x
(ledger section 4.7), which is nowhere near enough to train a planner. The
surrogate replaces continuous motion with option outcomes drawn from the
capability registry, so a decision costs one sampled duration instead of
several hundred simulated frames.

It is semi-Markov because options have variable duration: `step` advances the
clock by however long the chosen option took, and every timer, patience bar
and cook stage advances by that same amount.

Honesty about calibration. A registry row measured against `mockgame` prices
the *model*, not PlateUp. Rows carry their source, `Surrogate.support` reports
how many transitions fell outside the calibrated contexts, and a comparison
run states plainly which side it was calibrated against. Nothing here becomes
evidence about the game until the registry is refilled from real trials.
"""

import argparse
import json
import os
import random
import statistics
import sys

import capability
import steak as S

# Option vocabulary at the planner's level of abstraction. These map onto the
# options in `options.py`; the names are shared so a registry row measured by
# the runner is found by the surrogate without a translation table.
FETCH_RAW = "acquire"
LOAD_HOB = "place"
COOK_LIFT = "acquire"
PLATE_DISH = "place"
SERVE = "serve"
CLEAR_TABLE = "acquire"
WASH = "wash_plate"
BIN = "bin"
IDLE = "idle"

# Priors used when the registry has no row for a context. Deliberately
# pessimistic on duration and success so an uncalibrated plan never looks
# better than a measured one.
PRIORS = {
    "acquire": {"seconds": 2.5, "spread": 0.8, "success": 0.90},
    "place": {"seconds": 2.5, "spread": 0.8, "success": 0.90},
    "watch_cook": {"seconds": 8.0, "spread": 2.0, "success": 0.90},
    "serve": {"seconds": 3.0, "spread": 1.0, "success": 0.90},
    "wash_plate": {"seconds": 5.0, "spread": 1.5, "success": 0.90},
    "bin": {"seconds": 3.0, "spread": 1.0, "success": 0.95},
    "idle": {"seconds": 0.4, "spread": 0.0, "success": 1.0},
}

# Customer model, fitted from the two recorded days. See mockgame for the
# provenance of each number; they are shared so the two models cannot drift.
SEATING_SECONDS = 9.0
THINKING_SECONDS = 3.0
SERVICE_SECONDS = 4.5
EATING_SECONDS = 3.0
PATIENCE_DRAIN = {"service": 0.00434, "wait_for_food": 0.00722}
ORDER_REWARD = 5


class Group:
    __slots__ = ("gid", "phase", "timer", "patience", "served", "done",
                 "table")

    def __init__(self, gid, table):
        self.gid = gid
        self.table = table
        self.phase = "seating"
        self.timer = SEATING_SECONDS
        self.patience = 1.0
        self.served = False
        self.done = False


class Surrogate:
    """Discrete-event steak service over options."""

    def __init__(self, registry=None, chain=None, seed=1, tables=2,
                 hobs=2, plates=4, day_length=100.0, arrival_interval=24.5,
                 groups=4):
        self.registry = registry
        self.chain = chain or S.Chain("plain")
        self.random = random.Random(seed)
        self.tables = tables
        self.hobs = hobs
        self.plate_capacity = plates
        self.day_length = day_length
        self.arrival_interval = arrival_interval
        self.total_groups = groups
        self.reset()

    # -- state ------------------------------------------------------------

    def reset(self):
        self.clock = 0.0
        self.groups = []
        self.next_group = 0
        self.next_arrival = 0.1
        self.held = None
        self.on_heat = []          # [{"stage": int, "remaining": float}]
        self.buffered = 0          # plated dishes on counters
        self.clean_plates = self.plate_capacity
        self.dirty_plates = 0      # anywhere in the kitchen
        self.dirty_on_tables = 0
        self.money = 0
        self.served = 0
        self.lost = 0
        self.ruined = 0
        self.lives = 1
        self.out_of_support = 0
        self.transitions = 0
        self.calibrated_transitions = 0
        self.history = []
        return self.state()

    def state(self):
        return {
            "clock": round(self.clock, 2),
            "held": self.held,
            "on_heat": [dict(item) for item in self.on_heat],
            "buffered": self.buffered,
            "clean_plates": self.clean_plates,
            "dirty_plates": self.dirty_plates,
            "dirty_on_tables": self.dirty_on_tables,
            "waiting": sum(
                1 for group in self.groups
                if group.phase == "wait_for_food"),
            "seated": sum(
                1 for group in self.groups
                if not group.done and group.phase != "seating"),
            "money": self.money,
            "served": self.served,
            "lost": self.lost,
            "ruined": self.ruined,
            "lives": self.lives,
        }

    @property
    def terminated(self):
        return self.lives <= 0

    @property
    def finished(self):
        return (
            self.terminated
            or (self.clock >= self.day_length
                and self.next_group >= self.total_groups
                and all(group.done for group in self.groups)))

    # -- option sampling --------------------------------------------------

    def sample(self, option, target=None, route_tiles=None):
        """Duration and success for one option, from the registry if possible."""
        row, exact = (None, False)
        if self.registry is not None:
            row, exact = self._lookup(option, target, route_tiles)
        # Waiting is not a capability and is never measured, so counting it
        # against calibration support would report a number about the policy's
        # idleness rather than about the registry's coverage.
        counted = option != IDLE
        if row is None:
            self.out_of_support += counted
            prior = PRIORS.get(option, PRIORS["acquire"])
            seconds = max(
                0.05, self.random.gauss(prior["seconds"], prior["spread"]))
            return seconds, self.random.random() < prior["success"]

        if not exact:
            self.out_of_support += counted
        mean = row.get("mean_seconds") or row.get("median_seconds")
        if mean is None:
            mean = PRIORS.get(option, PRIORS["acquire"])["seconds"]
        spread = row.get("stdev_seconds") or 0.0
        seconds = max(0.05, self.random.gauss(mean, spread))
        # Sample against the lower confidence bound, not the point estimate.
        # Specification section 9.3 requires uncertainty to cost something, or
        # a plan validated on three samples outranks one validated on thirty.
        success = self.random.random() < row.get(
            "success_low", row.get("success_rate", 0.9))
        return seconds, success

    def _lookup(self, option, target, route_tiles):
        """Find a row, and say whether the context was the one asked for.

        Asking without a route length is not an out-of-support transition: the
        surrogate abstracts travel away, so there is no distance to match on
        and any row for the option is exactly as specific as the question.
        """
        band = capability.band_of(route_tiles)
        summaries = getattr(self.registry, "summaries", None)
        if summaries is None:
            return self.registry.lookup(option, target, route_tiles)

        for key in (
            (option, target or "any", band),
            (option, target or "any", "any"),
            (option, "any", band),
        ):
            row = summaries.get(key)
            if row:
                return row, True
        matching = [row for key, row in summaries.items() if key[0] == option]
        if matching:
            # Pool every distance band for this option: with travel
            # abstracted, the band split carries no information here.
            return self._pool(matching), route_tiles is None
        return None, False

    @staticmethod
    def _pool(rows):
        attempts = sum(row["attempts"] for row in rows)
        successes = sum(row["successes"] for row in rows)
        weighted = [
            (row["mean_seconds"], row["attempts"]) for row in rows
            if row.get("mean_seconds") is not None]
        mean = (
            sum(value * weight for value, weight in weighted)
            / sum(weight for _value, weight in weighted)
            if weighted else None)
        low, high = capability.wilson_interval(successes, attempts)
        return {
            "attempts": attempts,
            "successes": successes,
            "success_rate": successes / attempts if attempts else 0.0,
            "success_low": low,
            "success_high": high,
            "mean_seconds": mean,
            "median_seconds": mean,
            "stdev_seconds": max(
                (row.get("stdev_seconds") or 0.0) for row in rows),
        }

    # -- transition -------------------------------------------------------

    def step(self, option, target=None, route_tiles=None):
        """Apply one option and advance every clock by its duration."""
        seconds, ok = self.sample(option, target, route_tiles)
        before = self.state()
        self.transitions += 1
        if option != IDLE:
            self.calibrated_transitions += 1

        self._advance(seconds)
        reward = 0.0
        if ok:
            reward = self._apply(option)

        self.history.append({
            "option": option,
            "target": target,
            "seconds": round(seconds, 3),
            "success": ok,
            "reward": reward,
            "clock": round(self.clock, 2),
        })
        return self.state(), reward, self.terminated, {
            "seconds": seconds,
            "success": ok,
            "before": before,
        }

    def _apply(self, option):
        """Effects, expressed in the same vocabulary the planner uses."""
        if option == "fetch_raw":
            self.held = "raw"
        elif option == "load_hob":
            if self.held == "raw" and len(self.on_heat) < self.hobs:
                self.held = None
                self.on_heat.append({"stage": 0, "remaining": self._stage(0)})
        elif option == "lift":
            # Whether the item is still servable is judged after the option's
            # duration has elapsed, so an item that burned during the walk is
            # correctly found ruined rather than retroactively saved.
            ready = [
                item for item in self.on_heat
                if 1 <= item["stage"] <= len(self.chain.stages)]
            if ready:
                ready.sort(key=lambda item: item["remaining"])
                self.on_heat.remove(ready[0])
                self.held = "cooked"
        elif option == "plate":
            if self.held == "cooked" and self.clean_plates > 0:
                self.clean_plates -= 1
                self.held = "plated"
        elif option == "buffer":
            if self.held == "plated":
                self.held = None
                self.buffered += 1
        elif option == "collect":
            if self.held is None and self.buffered > 0:
                self.buffered -= 1
                self.held = "plated"
        elif option == "serve":
            return self._serve()
        elif option == "clear_table":
            if self.held is None and self.dirty_on_tables > 0:
                self.dirty_on_tables -= 1
                self.held = "dirty"
        elif option == "wash_plate":
            if self.held == "dirty":
                self.held = None
                self.dirty_plates = max(0, self.dirty_plates - 1)
                self.clean_plates += 1
        elif option == "bin":
            if self.held in ("waste", "cooked", "raw"):
                if self.held == "waste":
                    self.ruined += 1
                self.held = None
        return 0.0

    def _serve(self):
        if self.held != "plated":
            return 0.0
        waiting = [
            group for group in self.groups if group.phase == "wait_for_food"]
        if not waiting:
            return 0.0
        waiting.sort(key=lambda group: group.patience)
        group = waiting[0]
        group.phase = "eating"
        group.timer = EATING_SECONDS
        group.patience = 1.0
        group.served = True
        self.held = None
        self.money += ORDER_REWARD
        self.served += 1
        return float(ORDER_REWARD)

    def _stage(self, index):
        seconds = self.chain.stage_seconds(index)
        return seconds if seconds is not None else 1.0

    # -- world clock ------------------------------------------------------

    def _advance(self, seconds):
        remaining = seconds
        # Sub-step so a long option cannot skip a burn or a walk-out.
        while remaining > 1e-6:
            step = min(remaining, 0.5)
            remaining -= step
            self.clock += step
            self._advance_cooking(step)
            self._advance_customers(step)

    def _advance_cooking(self, step):
        for item in list(self.on_heat):
            item["remaining"] -= step
            while item["remaining"] <= 0.0:
                item["stage"] += 1
                if item["stage"] >= len(self.chain.stages) + 1:
                    self.on_heat.remove(item)
                    self.ruined += 1
                    break
                item["remaining"] += self._stage(item["stage"])

    def _advance_customers(self, step):
        while (self.next_group < self.total_groups
               and self.clock >= self.next_arrival
               and self.clock < self.day_length):
            occupied = sum(1 for group in self.groups if not group.done)
            if occupied >= self.tables:
                break
            self.groups.append(Group(self.next_group, occupied))
            self.next_group += 1
            self.next_arrival += self.arrival_interval

        for group in self.groups:
            if group.done:
                continue
            drain = PATIENCE_DRAIN.get(group.phase, 0.0)
            if drain:
                group.patience -= drain * step
                if group.patience <= 0.0:
                    group.done = True
                    self.lost += 1
                    self.lives -= 1
                    continue
            group.timer -= step
            if group.timer > 0.0:
                continue
            if group.phase == "seating":
                group.phase, group.timer = "thinking", THINKING_SECONDS
                group.patience = 1.0
            elif group.phase == "thinking":
                group.phase, group.timer = "service", SERVICE_SECONDS
                group.patience = 1.0
            elif group.phase == "service":
                group.phase, group.timer = "wait_for_food", float("inf")
                group.patience = 1.0
            elif group.phase == "eating":
                group.done = True
                self.dirty_plates += 1
                self.dirty_on_tables += 1

    # -- reporting --------------------------------------------------------

    def scoreboard(self):
        return {
            "served": self.served,
            "lost": self.lost,
            "ruined": self.ruined,
            "money": self.money,
            "lives": self.lives,
            "seconds": round(self.clock, 1),
            "transitions": self.transitions,
            "calibrated_transitions": self.calibrated_transitions,
            "out_of_support": self.out_of_support,
            "support_rate": self.support,
        }

    @property
    def support(self):
        """Share of measurable transitions that had a calibrated row."""
        if not self.calibrated_transitions:
            return None
        return 1.0 - self.out_of_support / self.calibrated_transitions


# --------------------------------------------------------------------------
# a planner over the surrogate's own vocabulary
# --------------------------------------------------------------------------


def reference_policy(sim):
    """The same priority list as `service.SteakPlanner`, in surrogate terms.

    Keeping the two in step is what makes a surrogate-versus-model comparison
    meaningful: a gap then measures the abstraction, not two different
    policies. The order matches `SteakPlanner.choose` rule for rule.
    """
    waiting = [g for g in sim.groups if g.phase == "wait_for_food"]
    seated = [
        g for g in sim.groups
        if not g.done and not g.served and g.phase != "seating"]
    demand = max(1, len(seated))
    last_servable = len(sim.chain.stages)
    at_risk = [
        item for item in sim.on_heat if item["stage"] == last_servable]
    ready = [
        item for item in sim.on_heat
        if 1 <= item["stage"] <= last_servable]

    if sim.held == "waste":
        return "bin"
    if at_risk and sim.held is None:
        return "lift"
    if sim.held == "plated" and waiting:
        return "serve"
    if waiting and sim.buffered > 0 and sim.held is None:
        return "collect"
    if sim.held == "cooked":
        return "plate" if sim.clean_plates > 0 else "bin"
    if sim.held == "plated":
        return "buffer"
    if sim.held == "dirty":
        return "wash_plate"
    if sim.held == "raw":
        return "load_hob" if len(sim.on_heat) < sim.hobs else "bin"

    if ready:
        return "lift"
    if sim.dirty_on_tables > 0:
        return "clear_table"
    if (sim.buffered + len(sim.on_heat) <= demand
            and len(sim.on_heat) < sim.hobs
            and sim.clean_plates + sim.buffered > 0):
        return "fetch_raw"
    return "idle"


OPTION_TO_REGISTRY = {
    "fetch_raw": "acquire",
    "load_hob": "place",
    # A lift is a walk plus one grab. The `watch_cook` option in `options.py`
    # also contains the wait for the steak to reach doneness, and that wait is
    # already on the surrogate's own clock, so pricing a lift from that row
    # would charge the cooking time twice.
    "lift": "acquire",
    "plate": "place",
    "buffer": "place",
    "collect": "acquire",
    "serve": "serve",
    "clear_table": "acquire",
    "wash_plate": "wash_plate",
    "bin": "bin",
    "idle": "idle",
}


def rollout(sim, policy=reference_policy, max_transitions=4000):
    sim.reset()
    for _ in range(max_transitions):
        if sim.finished:
            break
        choice = policy(sim)
        registry_name = OPTION_TO_REGISTRY.get(choice, choice)
        seconds, ok = sim.sample(registry_name)
        sim.transitions += 1
        if registry_name != IDLE:
            sim.calibrated_transitions += 1
        sim._advance(seconds)
        if ok:
            sim._apply(choice)
        sim.history.append({
            "option": choice,
            "registry_option": registry_name,
            "seconds": round(seconds, 3),
            "success": ok,
            "clock": round(sim.clock, 2),
        })
    return sim.scoreboard()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def _load_registry(path):
    if path is None:
        return None
    return capability.Registry.load(path)


def summarise(boards, key):
    values = [board[key] for board in boards if board.get(key) is not None]
    if not values:
        return None
    return {
        "median": statistics.median(values),
        "mean": round(statistics.fmean(values), 3),
        "min": min(values),
        "max": max(values),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo")
    demo.add_argument("--episodes", type=int, default=20)
    demo.add_argument("--seed", type=int, default=1)
    demo.add_argument("--capability")

    compare = subparsers.add_parser("compare")
    compare.add_argument("capability")
    compare.add_argument("--episodes", type=int, default=20)
    compare.add_argument("--layout",
                         default=os.path.join("runs", "demos", "smoke.jsonl"))
    compare.add_argument("--json", dest="json_path")

    args = parser.parse_args()

    if args.command == "demo":
        registry = _load_registry(args.capability)
        boards = []
        for episode in range(args.episodes):
            sim = Surrogate(registry=registry, seed=args.seed + episode)
            boards.append(rollout(sim))
        print(f"surrogate, {args.episodes} episodes, "
              f"registry {args.capability or 'none (priors only)'}")
        for key in ("served", "lost", "ruined", "money", "transitions"):
            print(f"  {key:<12} {summarise(boards, key)}")
        support = summarise(boards, "support_rate")
        print(f"  {'support':<12} {support}")
        return 0

    registry = _load_registry(args.capability)
    import service

    surrogate_boards = []
    for episode in range(args.episodes):
        sim = Surrogate(registry=registry, seed=1 + episode)
        surrogate_boards.append(rollout(sim))

    model_boards = service.run_mock(
        args.layout, episodes=args.episodes, seed=1, verbose=False)

    report = {
        "registry": os.path.normpath(args.capability),
        "registry_source": registry.source if registry else None,
        "episodes": args.episodes,
        "surrogate": {
            key: summarise(surrogate_boards, key)
            for key in ("served", "lost", "ruined", "money", "transitions",
                        "support_rate")},
        "model": {
            key: summarise(model_boards, key)
            for key in ("served", "lost", "ruined", "money", "options")},
    }

    print("surrogate versus the tick-level model")
    print(f"  registry source: {report['registry_source']}")
    print()
    for key in ("served", "lost", "ruined", "money"):
        left = report["surrogate"][key]
        right = report["model"][key]
        print(f"  {key:<8} surrogate median {left['median']:<8} "
              f"model median {right['median']}")
    print()
    print("  This compares the option abstraction against the tick-level")
    print("  model it was calibrated on. It is not a real-game validation,")
    print("  and specification section 9.4 is not satisfied by it.")

    if args.json_path:
        os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump(report, output, indent=2, sort_keys=True)
        print("\nwrote " + os.path.normpath(args.json_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
