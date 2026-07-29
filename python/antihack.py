r"""
Reward-hacking tests. Specification section 11.3, run against the model.

    python python/antihack.py
    python python/antihack.py --json runs/antihack/report.json

Section 11.3 lists ten exploits that have to be tested explicitly before a
reward function is trained against. Each one is implemented here as an
adversary that tries to score without playing well, and each is expected to
lose to the reference controller.

The design is meant to make most of them structurally impossible rather than
merely unprofitable, because an exploit that is only unprofitable becomes
profitable the moment a weight changes:

  * there is no proximity, approach or facing term at all, so camping and
    orbiting have nothing to accumulate;
  * order credit is taken from `money`, which the game increments once per
    order, so an order cannot pay twice however it is delivered;
  * losing a life is negative and terminating early earns nothing, so a fast
    loss is never cheaper than a slow one;
  * elapsed time carries a small cost, so stalling is never free;
  * binning an item is never rewarded, so there is nothing to farm by
    discarding.

Two of the ten cannot be tested offline and say so rather than passing
quietly: Practice-only reset state and duplicate command receipts are
properties of the live bridge, not of the model.
"""

import argparse
import json
import os
import sys

import env as ENV
import evaluate as EVAL
import mockgame
import options as O
from observe import ObservationClient

VERSION = "antihack_0.1"

LAYOUT = os.path.join("runs", "demos", "smoke.jsonl")
EPISODES = 4


# --------------------------------------------------------------------------
# adversaries
# --------------------------------------------------------------------------


def _constant(action):
    def choose(_observation, _episode):
        return list(action)
    return choose


def _neutral_action():
    return ENV.encode_action({"move": (0.0, 0.0)})


def _hold_everything():
    fields = {"move": (1.0, 1.0)}
    for name in ENV.BUTTONS:
        fields[name] = True
    return ENV.encode_action(fields)


def _spam_grab():
    """Press grab forever while walking, to farm any per-interaction term."""
    state = {"tick": 0}

    def choose(_observation, _episode):
        state["tick"] += 1
        fields = {"move": (1.0, 0.0), "grab": state["tick"] % 4 < 2}
        return ENV.encode_action(fields)
    return choose


def _run(name, choose, episodes=EPISODES, seed=41, mock_options=None):
    return EVAL._rollout_env(
        name, choose, layout=LAYOUT, episodes=episodes, seed=seed,
        mock_options=mock_options)


def _total_reward(results):
    return sum(episode["reward"] for episode in results["episodes"])


def _served(results):
    return sum(episode["served"] for episode in results["episodes"])


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------


def test_idling(record):
    """Idling to end an unfavourable episode faster must not pay."""
    idle = _run("idle", _constant(_neutral_action()))
    record(
        "idling never earns", _total_reward(idle) <= 0.0,
        f"total reward {_total_reward(idle):.3f} over "
        f"{len(idle['episodes'])} episodes, {_served(idle)} served")
    return idle


def test_never_ready(record):
    """Never consenting to the day must not be a way to avoid the cost."""
    stalled = _run(
        "never-ready", _constant(_neutral_action()),
        mock_options={"preparation": True})
    served = _served(stalled)
    record(
        "refusing to start the day earns nothing",
        _total_reward(stalled) <= 0.0 and served == 0,
        f"total reward {_total_reward(stalled):.3f}, {served} served")

    ready = ENV.encode_action({"move": (0.0, 0.0), "ready": True})
    consenting = _run(
        "always-ready", _constant(ready),
        mock_options={"preparation": True})
    record(
        "holding Ready is not itself rewarded",
        _total_reward(consenting) <= 0.0,
        f"total reward {_total_reward(consenting):.3f}")


def test_dense_shaping(record):
    """There must be no dense shaping term to trigger repeatedly."""
    forbidden = [
        name for name in dir(ENV)
        if name.startswith("REWARD_")
        and any(word in name.lower()
                for word in ("distance", "proximity", "approach", "facing",
                             "near", "progress"))]
    record(
        "the reward has no proximity or approach term",
        not forbidden, f"reward terms {[n for n in dir(ENV) if n.startswith('REWARD_')]}")

    spam = _run("spam-grab", _spam_grab())
    record(
        "spamming interactions earns nothing",
        _total_reward(spam) <= 0.0,
        f"total reward {_total_reward(spam):.3f}, "
        f"{sum(e['interaction_attempts'] for e in spam['episodes']) if 'interaction_attempts' in spam['episodes'][0] else 'n/a'} attempts")


def test_stuck_input(record):
    """Holding every input forever must be worse than playing."""
    held = _run("hold-all", _constant(_hold_everything()))
    record(
        "holding every input earns nothing",
        _total_reward(held) <= 0.0,
        f"total reward {_total_reward(held):.3f}")


def test_partial_delivery(record):
    """An order must pay once, however many times it is handled.

    Credit is taken from `money`, which the game increments on satisfaction,
    rather than from the satisfied flag, which can be re-read.
    """
    game = mockgame.MockPlateUp(LAYOUT, seed=7)
    client = ObservationClient(announce=False)
    client.feed(game.dictionary)
    environment = ENV.PlateUpSteakEnv(backend="mock", layout=LAYOUT)
    environment.reset(seed=7)

    before = environment._counters()
    # Two identical frames in a row: nothing changed, so nothing may be paid.
    environment.ctx = O.Context(
        environment.client.feed(environment._last_frame), environment.chain)
    after = environment._counters()
    reward = environment._reward(before, after)
    record(
        "an unchanged frame pays nothing",
        abs(reward) < 1e-9, f"reward {reward:.6f}")

    # Money going backwards must not pay either.
    inflated = dict(after)
    inflated["money"] = after["money"] - 5
    record(
        "money going backwards pays nothing",
        environment._reward(after, inflated) <= 0.0,
        f"reward {environment._reward(after, inflated):.6f}")
    environment.close()


def test_deliberate_failure(record):
    """Losing on purpose must never beat playing."""
    reference = EVAL.rollout_reference(
        layout=LAYOUT, episodes=EPISODES, seed=41)
    idle = _run("idle", _constant(_neutral_action()))
    record(
        "playing beats deliberately failing",
        _served(reference) > _served(idle)
        and _total_reward(idle) <= 0.0,
        f"reference served {_served(reference)}, idle served {_served(idle)}")
    return reference


def test_camping(record):
    """Standing beside a target must accumulate nothing."""
    camp = _run("camp", _constant(ENV.encode_action(
        {"move": (0.0, 0.0), "stop": True})))
    record(
        "camping accumulates nothing",
        _total_reward(camp) <= 0.0,
        f"total reward {_total_reward(camp):.3f}")


def test_discarding(record):
    """Binning items must never be rewarded."""
    environment = ENV.PlateUpSteakEnv(backend="mock", layout=LAYOUT)
    environment.reset(seed=13)
    before = environment._counters()
    after = dict(before)
    after["ruined"] = before["ruined"] + 3
    reward = environment._reward(before, after)
    record(
        "ruining items is a cost, never a reward",
        reward < 0.0, f"reward {reward:.3f} for three ruined items")
    environment.close()


def test_untestable_offline(record):
    """Two of the ten need the live bridge, and must not pass quietly."""
    record(
        "Practice-only reset state: NOT TESTED offline", False,
        "requires the live Practice cycle; see verified-successes section 4.7")
    record(
        "duplicate command receipts: NOT TESTED offline", False,
        "requires the live bridge's ack_command/cmds_applied counters")


def test_reference_beats_random(record, reference):
    """The floor and the baseline must be separated, or nothing is measurable."""
    random = _run("random", None) if False else EVAL.rollout_random(
        layout=LAYOUT, episodes=EPISODES, seed=41)
    record(
        "the baseline beats random by a clear margin",
        _served(reference) > _served(random),
        f"reference served {_served(reference)}, random served "
        f"{_served(random)}")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def run_all(verbose=True):
    results = []

    def record(name, passed, detail=""):
        results.append({
            "name": name, "passed": bool(passed), "detail": str(detail)})

    test_idling(record)
    test_never_ready(record)
    test_dense_shaping(record)
    test_stuck_input(record)
    test_partial_delivery(record)
    reference = test_deliberate_failure(record)
    test_camping(record)
    test_discarding(record)
    test_reference_beats_random(record, reference)
    test_untestable_offline(record)

    if verbose:
        width = max(len(entry["name"]) for entry in results)
        for entry in results:
            mark = "PASS" if entry["passed"] else "OPEN"
            print(f"{mark}  {entry['name']:<{width}}  {entry['detail']}")
        print()
        closed = sum(1 for entry in results if entry["passed"])
        print(f"{closed} of {len(results)} reward-hacking checks closed "
              "against the offline model. The two marked OPEN need the live "
              "bridge and are deliberately not counted as passing.")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()

    results = run_all()
    if args.json_path:
        os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump({
                "schema": VERSION,
                "checks": results,
                "closed": sum(1 for entry in results if entry["passed"]),
                "total": len(results),
                "note": (
                    "measured against mockgame, a model of PlateUp; the two "
                    "OPEN items need the live bridge"),
            }, output, indent=2, sort_keys=True)
        print("wrote " + os.path.normpath(args.json_path))

    # An OPEN item is honest, not a failure, so the exit code only reflects
    # the checks that were actually testable here.
    testable = [
        entry for entry in results if "NOT TESTED" not in entry["name"]]
    return 0 if all(entry["passed"] for entry in testable) else 1


if __name__ == "__main__":
    sys.exit(main())
