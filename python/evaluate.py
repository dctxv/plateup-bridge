r"""
Evaluation harness: run a policy for N episodes and report the required metrics.

    python python/evaluate.py reference --episodes 20
    python python/evaluate.py random    --episodes 20
    python python/evaluate.py policy runs/policies/bc.npz --episodes 20
    python python/evaluate.py compare  runs/policies/bc.npz --episodes 20

Specification section 17.4 fixes the metric list and section 17.5 fixes how it
is reported: typical performance is the result, and a best run is a separate
highlight with the number of attempts disclosed. Both are honoured here: the
summary leads with medians and confidence intervals, and the best episode is
printed separately and labelled.

Everything runs against `mockgame`, which is a **model** of PlateUp. A number
out of this harness describes the model. The harness itself is the piece that
transfers: point it at the live backend and the same metrics come out.

Three policies share one interface, so they are comparable by construction:

    reference   the scripted priority list. Not autonomy; the baseline.
    random      uniform over the action space. The floor.
    policy      a behaviour-cloned checkpoint. A goal-conditioned one runs
                under the scripted planner, which chooses options while the
                policy supplies every primitive action; a state-only one runs
                on the observation alone. `rollout_any` dispatches on the
                checkpoint's own manifest.
"""

import argparse
import json
import os
import statistics
import sys

import capability
import encode
import env as ENV
import mockgame
import options as O
import steak as S
from observe import ObservationClient

VERSION = "evaluate_0.1"

MAX_SECONDS = 400.0


# --------------------------------------------------------------------------
# per-episode metrics
# --------------------------------------------------------------------------


def _episode_metrics(game, runner, ticks, idle_ticks, reward):
    board = game.scoreboard()
    attempted = board["served"] + board["lost"]
    seconds = max(1e-6, board["seconds"])
    metrics = {
        "served": board["served"],
        "lost": board["lost"],
        "ruined": board["ruined"],
        "money": board["money"],
        "lives_remaining": board["lives"],
        "seconds": board["seconds"],
        "day_completed": bool(game.day_finished and not game.game_over),
        "groups_arrived": attempted,
        "completion_rate": (
            board["served"] / attempted if attempted else None),
        "meals_per_minute": board["served"] / (seconds / 60.0),
        "reward": round(reward, 4),
        "control_ticks": ticks,
        "idle_fraction": idle_ticks / ticks if ticks else None,
    }
    if runner is not None:
        history = runner.history
        successes = sum(
            1 for record in history if record["status"] == O.SUCCESS)
        durations = [
            record["seconds"] for record in history
            if record.get("seconds") is not None]
        metrics.update({
            "options": len(history),
            "option_success_rate": (
                successes / len(history) if history else None),
            "median_option_seconds": (
                statistics.median(durations) if durations else None),
            "interaction_attempts": sum(
                record.get("presses", 0) for record in history),
        })
    return metrics


def _is_idle(fields):
    move = fields.get("move", (0.0, 0.0))
    if abs(move[0]) > 1e-9 or abs(move[1]) > 1e-9:
        return False
    return not any(
        fields.get(name) for name in ENV.BUTTONS)


# --------------------------------------------------------------------------
# runners
# --------------------------------------------------------------------------


def _new_game(layout, seed, mock_options):
    game = mockgame.MockPlateUp(layout, seed=seed, **(mock_options or {}))
    client = ObservationClient(announce=False)
    client.feed(game.dictionary)
    return game, client


def rollout_reference(layout=None, episodes=10, seed=1, min_stage=1,
                      mock_options=None, **_ignored):
    import service

    layout = layout or os.path.join("runs", "demos", "smoke.jsonl")
    results = []
    for index in range(episodes):
        game, client = _new_game(layout, seed + index, mock_options)
        planner = service.SteakPlanner(game.chain, min_stage=min_stage)
        runner = service.Runner(planner, game.chain)
        frame = game.observation()
        ticks = idle = 0
        for _ in range(int(MAX_SECONDS / mockgame.FRAME_SECONDS)):
            world = client.feed(frame)
            fields = runner.act(runner.context(world))
            ticks += 1
            idle += _is_idle(fields)
            frame = game.step(fields)
            if game.day_finished or game.game_over:
                break
        runner._retire(runner.context(client.feed(frame)))
        results.append(
            _episode_metrics(game, runner, ticks, idle, 0.0))
        results[-1]["episode"] = index
        results[-1]["seed"] = seed + index
    return {"policy": "reference", "episodes": results}


def _rollout_env(name, choose, layout=None, episodes=10, seed=1,
                 mock_options=None):
    layout = layout or os.path.join("runs", "demos", "smoke.jsonl")
    results = []
    for index in range(episodes):
        environment = ENV.PlateUpSteakEnv(
            backend="mock", layout=layout, seed=seed + index - 1,
            mock_kwargs=mock_options or {})
        observation, _info = environment.reset(seed=seed + index - 1)
        total = 0.0
        ticks = idle = 0
        for _ in range(int(MAX_SECONDS / mockgame.FRAME_SECONDS)):
            action = choose(observation, index)
            fields = ENV.decode_action(action)
            ticks += 1
            idle += _is_idle(fields)
            observation, reward, terminated, truncated, _info = \
                environment.step(action)
            total += reward
            if terminated or truncated:
                break
        results.append(
            _episode_metrics(environment.game, None, ticks, idle, total))
        results[-1]["episode"] = index
        results[-1]["seed"] = seed + index
        environment.close()
    return {"policy": name, "episodes": results}


def rollout_random(layout=None, episodes=10, seed=1, mock_options=None,
                   **_ignored):
    import random as _random

    generator = _random.Random(seed)
    sizes = [len(ENV.MOVE_VALUES), len(ENV.MOVE_VALUES)] + [2] * len(
        ENV.BUTTONS)

    def choose(_observation, _episode):
        return [generator.randrange(size) for size in sizes]

    return _rollout_env(
        "random", choose, layout=layout, episodes=episodes, seed=seed,
        mock_options=mock_options)


def _policy_name(policy):
    manifest = getattr(policy, "manifest", None) or {}
    source = os.path.basename(str(manifest.get("trained_from", "unknown")))
    kind = "goal" if manifest.get("goal_conditioned") else "state"
    return f"policy[{kind}]({source})"


def rollout_any(policy, **kwargs):
    """Dispatch on how the checkpoint was trained.

    A goal-conditioned policy expects the goal appended to the state, so
    feeding it a bare observation is a shape error rather than a bad score.
    The manifest records which it is, so the caller does not have to.
    """
    manifest = getattr(policy, "manifest", None) or {}
    if manifest.get("goal_conditioned"):
        return rollout_goal_policy(policy, **kwargs)
    return rollout_policy(policy, **kwargs)


def rollout_policy(policy, layout=None, episodes=10, seed=1,
                   mock_options=None, temperature=0.0, **_ignored):
    """State-only rollout: the policy sees the kitchen and nothing else."""
    import numpy

    generator = numpy.random.default_rng(seed)

    def choose(observation, _episode):
        return policy.act(
            observation, generator=generator, temperature=temperature)

    return _rollout_env(
        _policy_name(policy), choose, layout=layout, episodes=episodes,
        seed=seed, mock_options=mock_options)


def rollout_goal_policy(policy, layout=None, episodes=10, seed=1,
                        min_stage=1, mock_options=None, temperature=0.0,
                        **_ignored):
    """Goal-conditioned rollout: the planner chooses, the policy drives.

    This is the specification section 8.1 split. The task planner selects an
    option and decides when it has ended; every movement axis and every button
    on every tick comes from the learned policy. The option's own motor code
    is run only so its termination logic still sees the frames, and its
    suggested action is discarded.

    The task layer being scripted is the stated Project 1 limitation: section
    10.4 trains the planner separately, in the surrogate, and until that is
    done this is a learned motor controller under a scripted planner rather
    than an autonomous agent.
    """
    import numpy
    import service

    layout = layout or os.path.join("runs", "demos", "smoke.jsonl")
    generator = numpy.random.default_rng(seed)
    goal_encoder = encode.GoalEncoder()
    results = []

    for index in range(episodes):
        game, client = _new_game(layout, seed + index, mock_options)
        encoder = encode.Encoder(game.chain)
        planner = service.SteakPlanner(game.chain, min_stage=min_stage)
        runner = service.Runner(planner, game.chain, driven_externally=True)

        frame = game.observation()
        ticks = idle = 0
        for _ in range(int(MAX_SECONDS / mockgame.FRAME_SECONDS)):
            world = client.feed(frame)
            ctx = runner.context(world)
            suggested = runner.act(ctx)
            if world.start_day_warnings is not None:
                # Preparation is not a motor problem and the policy was never
                # trained on it, so consent stays with the planner.
                fields = suggested
            else:
                inputs = numpy.concatenate([
                    numpy.asarray(encoder.encode(ctx)),
                    numpy.asarray(goal_encoder.encode(runner.option, ctx))])
                fields = ENV.decode_action(policy.act(
                    inputs, generator=generator, temperature=temperature))
            ticks += 1
            idle += _is_idle(fields)
            frame = game.step(fields)
            if game.day_finished or game.game_over:
                break

        runner._retire(runner.context(client.feed(frame)))
        results.append(_episode_metrics(game, runner, ticks, idle, 0.0))
        results[-1]["episode"] = index
        results[-1]["seed"] = seed + index
    return {"policy": _policy_name(policy) + "+planner", "episodes": results}


def rollout_split(policy, source="policy_moves", layout=None, episodes=3,
                  seed=1, min_stage=1, mock_options=None):
    """Split the action between the policy and the option layer.

    A single failing score says the policy is not good enough. This says which
    half. `policy_moves` takes movement from the policy and the buttons from
    the option layer; `policy_presses` does the reverse.

    Neither is an autonomy claim -- half the action is scripted in both -- and
    neither is meant to be. They are the diagnostic specification section 12
    asks for before choosing what to change.
    """
    import numpy
    import service

    layout = layout or os.path.join("runs", "demos", "smoke.jsonl")
    goal_encoder = encode.GoalEncoder()
    buttons_from_policy = source == "policy_presses"
    results = []

    for index in range(episodes):
        game, client = _new_game(layout, seed + index, mock_options)
        encoder = encode.Encoder(game.chain)
        planner = service.SteakPlanner(game.chain, min_stage=min_stage)
        runner = service.Runner(planner, game.chain, driven_externally=True)
        frame = game.observation()
        ticks = idle = 0

        for _ in range(int(MAX_SECONDS / mockgame.FRAME_SECONDS)):
            world = client.feed(frame)
            ctx = runner.context(world)
            expert = runner.act(ctx)
            if world.start_day_warnings is not None:
                fields = expert
            else:
                inputs = numpy.concatenate([
                    numpy.asarray(encoder.encode(ctx)),
                    numpy.asarray(goal_encoder.encode(runner.option, ctx))])
                learned = ENV.decode_action(policy.act(inputs))
                fields = dict(expert)
                if buttons_from_policy:
                    for name in ENV.BUTTONS:
                        fields[name] = learned[name]
                else:
                    fields["move"] = learned["move"]
            ticks += 1
            idle += _is_idle(fields)
            frame = game.step(fields)
            if game.day_finished or game.game_over:
                break

        runner._retire(runner.context(client.feed(frame)))
        results.append(_episode_metrics(game, runner, ticks, idle, 0.0))
        results[-1]["episode"] = index
        results[-1]["seed"] = seed + index
    return {"policy": f"split:{source}", "episodes": results}


def assist_sweep(policy, layout=None, episodes=3, seed=1, min_stage=1,
                 fractions=(0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0),
                 mock_options=None):
    """How much expert help does the policy need to finish the day?

    A pass/fail on the Phase G gate says the policy is not good enough. This
    says by how much. At each fraction, that share of ticks is taken from the
    scripted controller and the rest from the policy, and the day is scored.
    The fraction at which the day starts completing is a far more actionable
    number than a single failing score, because it separates "close" from
    "nowhere near".
    """
    import numpy
    import service

    layout = layout or os.path.join("runs", "demos", "smoke.jsonl")
    goal_encoder = encode.GoalEncoder()
    rows = []

    for fraction in fractions:
        served = []
        lost = []
        completed = 0
        for index in range(episodes):
            generator = numpy.random.default_rng(seed * 100 + index)
            game, client = _new_game(layout, seed + index, mock_options)
            encoder = encode.Encoder(game.chain)
            planner = service.SteakPlanner(game.chain, min_stage=min_stage)
            runner = service.Runner(
                planner, game.chain, driven_externally=True)
            frame = game.observation()
            for _ in range(int(MAX_SECONDS / mockgame.FRAME_SECONDS)):
                world = client.feed(frame)
                ctx = runner.context(world)
                expert = runner.act(ctx)
                if world.start_day_warnings is not None or                         generator.random() < fraction:
                    fields = expert
                else:
                    inputs = numpy.concatenate([
                        numpy.asarray(encoder.encode(ctx)),
                        numpy.asarray(
                            goal_encoder.encode(runner.option, ctx))])
                    fields = ENV.decode_action(policy.act(inputs))
                frame = game.step(fields)
                if game.day_finished or game.game_over:
                    break
            board = game.scoreboard()
            served.append(board["served"])
            lost.append(board["lost"])
            completed += bool(game.day_finished and not game.game_over)
        rows.append({
            "expert_fraction": fraction,
            "median_served": statistics.median(served),
            "median_lost": statistics.median(lost),
            "days_completed": completed,
            "episodes": episodes,
        })
    return rows


def describe_assist(rows):
    lines = [
        f"{VERSION}  expert-assistance sweep against the offline model",
        "",
        f"  {'expert share':>13}{'served':>9}{'lost':>7}{'days done':>12}",
    ]
    for row in rows:
        lines.append(
            f"  {row['expert_fraction']:>12.0%}"
            f"{row['median_served']:>9.1f}{row['median_lost']:>7.1f}"
            f"{row['days_completed']:>7}/{row['episodes']:<4}")
    lines.append("")
    lines.append("  The share of ticks taken from the scripted controller. 0% "
                 "is the policy alone,")
    lines.append("  100% is the baseline. Where the column turns is how far "
                 "the policy has to go.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------


NUMERIC = (
    "served", "lost", "ruined", "money", "seconds", "reward",
    "meals_per_minute", "idle_fraction", "options",
    "option_success_rate", "median_option_seconds", "interaction_attempts",
    "completion_rate",
)


def summarise(results):
    episodes = results["episodes"]
    summary = {"policy": results["policy"], "n": len(episodes)}

    for key in NUMERIC:
        values = [
            episode[key] for episode in episodes
            if episode.get(key) is not None]
        if not values:
            continue
        ordered = sorted(values)
        summary[key] = {
            "median": statistics.median(ordered),
            "mean": round(statistics.fmean(ordered), 4),
            "min": ordered[0],
            "max": ordered[-1],
            "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))],
        }

    completed = sum(1 for episode in episodes if episode["day_completed"])
    low, high = capability.wilson_interval(completed, len(episodes))
    summary["day_completion"] = {
        "completed": completed,
        "attempts": len(episodes),
        "rate": completed / len(episodes) if episodes else None,
        "confidence_low": round(low, 4),
        "confidence_high": round(high, 4),
    }

    survived = sum(1 for episode in episodes if episode["lost"] == 0)
    low, high = capability.wilson_interval(survived, len(episodes))
    summary["no_group_lost"] = {
        "episodes": survived,
        "attempts": len(episodes),
        "rate": survived / len(episodes) if episodes else None,
        "confidence_low": round(low, 4),
        "confidence_high": round(high, 4),
    }

    best = max(
        episodes,
        key=lambda episode: (episode["served"], -episode["lost"]),
        default=None)
    summary["best_episode"] = best
    summary["human_interventions"] = 0
    return summary


def describe(results):
    summary = summarise(results)
    lines = [
        f"{VERSION}  policy {summary['policy']}  "
        f"{summary['n']} episodes against the offline model",
        "",
        "typical (specification section 17.5: this is the result)",
    ]

    def row(label, key, digits=2):
        entry = summary.get(key)
        if entry is None:
            return
        lines.append(
            f"  {label:<26}median {entry['median']:>8.{digits}f}   "
            f"mean {entry['mean']:>8.{digits}f}   "
            f"range {entry['min']:.{digits}f}-{entry['max']:.{digits}f}")

    row("groups served", "served", 1)
    row("groups lost", "lost", 1)
    row("items ruined", "ruined", 1)
    row("money", "money", 1)
    row("meals per service minute", "meals_per_minute")
    row("idle fraction", "idle_fraction", 3)
    row("episode reward", "reward", 3)
    row("options used", "options", 1)
    row("option success rate", "option_success_rate", 3)
    row("interaction attempts", "interaction_attempts", 1)

    completion = summary["day_completion"]
    lines.append("")
    lines.append(
        f"  day completed             {completion['completed']}/"
        f"{completion['attempts']}  "
        f"95% CI [{completion['confidence_low']:.2f}, "
        f"{completion['confidence_high']:.2f}]")
    survived = summary["no_group_lost"]
    lines.append(
        f"  no group lost             {survived['episodes']}/"
        f"{survived['attempts']}  "
        f"95% CI [{survived['confidence_low']:.2f}, "
        f"{survived['confidence_high']:.2f}]")
    lines.append(
        f"  human interventions       {summary['human_interventions']}")

    best = summary["best_episode"]
    if best:
        lines.append("")
        lines.append(
            f"best single episode, out of {summary['n']} attempts "
            "(highlight, not the result)")
        lines.append(
            f"  seed {best['seed']}: served {best['served']}, "
            f"lost {best['lost']}, ruined {best['ruined']}, "
            f"money {best['money']}")
    lines.append("")
    lines.append("Measured against mockgame, a model of PlateUp. Not a "
                 "game result.")
    return "\n".join(lines)


def compare(reports):
    lines = [f"{VERSION}  policy comparison", ""]
    header = f"  {'policy':<28}{'served':>9}{'lost':>7}{'ruined':>8}" \
             f"{'day done':>10}{'idle':>8}"
    lines.append(header)
    for results in reports:
        summary = summarise(results)
        served = summary.get("served", {}).get("median", float("nan"))
        lost = summary.get("lost", {}).get("median", float("nan"))
        ruined = summary.get("ruined", {}).get("median", float("nan"))
        idle = summary.get("idle_fraction", {}).get("median", float("nan"))
        completion = summary["day_completion"]
        lines.append(
            f"  {summary['policy'][:27]:<28}{served:>9.1f}{lost:>7.1f}"
            f"{ruined:>8.1f}"
            f"{completion['completed']:>6}/{completion['attempts']:<3}"
            f"{idle:>8.3f}")
    lines.append("")
    lines.append("Medians over the same seeds, against the offline model.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_layout = os.path.join("runs", "demos", "smoke.jsonl")

    for name in ("reference", "random"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--episodes", type=int, default=10)
        sub.add_argument("--seed", type=int, default=1)
        sub.add_argument("--layout", default=default_layout)
        sub.add_argument("--json", dest="json_path")

    learned = subparsers.add_parser("policy")
    learned.add_argument("path")
    learned.add_argument("--episodes", type=int, default=10)
    learned.add_argument("--seed", type=int, default=1)
    learned.add_argument("--layout", default=default_layout)
    learned.add_argument("--temperature", type=float, default=0.0)
    learned.add_argument("--json", dest="json_path")

    split = subparsers.add_parser("split")
    split.add_argument("path")
    split.add_argument("--episodes", type=int, default=4)
    split.add_argument("--seed", type=int, default=1)
    split.add_argument("--layout", default=default_layout)
    split.add_argument("--json", dest="json_path")

    assist = subparsers.add_parser("assist")
    assist.add_argument("path")
    assist.add_argument("--episodes", type=int, default=3)
    assist.add_argument("--seed", type=int, default=1)
    assist.add_argument("--layout", default=default_layout)
    assist.add_argument("--json", dest="json_path")

    versus = subparsers.add_parser("compare")
    versus.add_argument("path")
    versus.add_argument("--episodes", type=int, default=10)
    versus.add_argument("--seed", type=int, default=1)
    versus.add_argument("--layout", default=default_layout)
    versus.add_argument("--json", dest="json_path")

    args = parser.parse_args()
    common = {"layout": args.layout, "episodes": args.episodes,
              "seed": args.seed}

    if args.command == "split":
        import policy as POLICY
        loaded = POLICY.ClonedPolicy.load(args.path)
        reports = [
            rollout_split(loaded, "policy_moves", **common),
            rollout_split(loaded, "policy_presses", **common),
            rollout_goal_policy(loaded, **common),
            rollout_reference(**common),
        ]
        print(compare(reports))
        print()
        print("  policy_moves:   movement learned, buttons from the option "
              "layer")
        print("  policy_presses: buttons learned, movement from the option "
              "layer")
        print("  Neither is autonomy. Both are diagnostics.")
        if args.json_path:
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as output:
                json.dump([summarise(r) for r in reports], output, indent=2,
                          sort_keys=True)
            print("\nwrote " + os.path.normpath(args.json_path))
        return 0

    if args.command == "assist":
        import policy as POLICY
        rows = assist_sweep(
            POLICY.ClonedPolicy.load(args.path), **common)
        print(describe_assist(rows))
        if args.json_path:
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as output:
                json.dump(rows, output, indent=2, sort_keys=True)
            print("\nwrote " + os.path.normpath(args.json_path))
        return 0

    if args.command == "reference":
        results = rollout_reference(**common)
    elif args.command == "random":
        results = rollout_random(**common)
    elif args.command == "policy":
        import policy as POLICY
        results = rollout_any(
            POLICY.ClonedPolicy.load(args.path),
            temperature=args.temperature, **common)
    else:
        import policy as POLICY
        reports = [
            rollout_random(**common),
            rollout_any(POLICY.ClonedPolicy.load(args.path), **common),
            rollout_reference(**common),
        ]
        print(compare(reports))
        if args.json_path:
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as output:
                json.dump(
                    [summarise(report) for report in reports], output,
                    indent=2, sort_keys=True)
            print("\nwrote " + os.path.normpath(args.json_path))
        return 0

    print(describe(results))
    if args.json_path:
        os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump(summarise(results), output, indent=2, sort_keys=True)
        print("\nwrote " + os.path.normpath(args.json_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
