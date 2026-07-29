r"""
DAgger: label the states the policy actually visits, not the ones the expert does.

    python python/dagger.py runs/policies/bc.npz runs/policies/dagger.npz
    python python/dagger.py --iterations 6 --rollouts 4 runs/policies/bc.npz out.npz

Why this module exists, measured rather than assumed. A policy cloned from the
reference controller reached 97.2% held-out per-frame accuracy and then served
**zero** groups: it picked up the meat, walked into an appliance, and pushed
against it for the rest of the day. The reference controller never stands in
that state, so the dataset contains no frame that says what to do about it, and
a 3% per-frame error compounds into a state the policy has never seen within a
few hundred ticks.

That failure is the entire argument for specification section 10.3 step 5, and
this is that step. Each iteration:

  1. runs the current policy in the model, while a shadow reference controller
     watches the same states and says what it would have done;
  2. records the expert's label for **every visited state**, including the ones
     the expert would never have reached;
  3. aggregates them into everything gathered so far; and
  4. retrains from scratch on the aggregate.

Execution is mixed: with probability beta the expert's action is taken instead
of the policy's, and beta decays each iteration. The first iterations therefore
stay near states worth learning while still collecting recovery labels, and the
last iterations are almost pure on-policy.

Each iteration is scored by playing, not by accuracy, and the checkpoint kept
is the best-scoring one rather than the last -- more data does not monotonically
help when the aggregate becomes dominated by recovery states.

Everything runs against `mockgame`. A policy trained here has learned the
model.
"""

import argparse
import json
import os
import sys

import numpy

import dataset as DATA
import encode
import env as ENV
import evaluate as EVAL
import mockgame
import policy as POLICY
from observe import ObservationClient

VERSION = "dagger_0.1"

MAX_SECONDS = 400.0


def _episode(policy, layout, seed, beta, generator, min_stage=1,
             mock_options=None):
    """One mixed rollout. Returns visited states and the expert's labels."""
    import service

    game = mockgame.MockPlateUp(layout, seed=seed, **(mock_options or {}))
    client = ObservationClient(announce=False)
    client.feed(game.dictionary)
    chain = game.chain
    encoder = encode.Encoder(chain)
    planner = service.SteakPlanner(chain, min_stage=min_stage)
    expert = service.Runner(planner, chain, driven_externally=True)

    goal_encoder = encode.GoalEncoder()
    observations = []
    goals = []
    actions = []
    frame = game.observation()
    expert_steps = 0

    for _ in range(int(MAX_SECONDS / mockgame.FRAME_SECONDS)):
        world = client.feed(frame)
        ctx = expert.context(world)

        # The expert is queried at the state the *policy* reached. Its own
        # option keeps re-planning from wherever the chef now is, which is
        # what makes the label a correction rather than a replay.
        expert_fields = expert.act(ctx)

        if world.start_day_warnings is None:
            encoded = encoder.encode(ctx)
            goal = goal_encoder.encode(expert.option, ctx)
            observations.append(encoded)
            goals.append(goal)
            actions.append(ENV.encode_action(expert_fields))
            inputs = numpy.concatenate([
                numpy.asarray(encoded), numpy.asarray(goal)])
        else:
            inputs = None

        if inputs is not None and generator.random() >= beta:
            fields = ENV.decode_action(policy.act(inputs))
        else:
            fields = expert_fields
            expert_steps += 1

        frame = game.step(fields)
        if game.day_finished or game.game_over:
            break

    board = game.scoreboard()
    board["expert_fraction"] = (
        expert_steps / max(1, len(observations)))
    return observations, goals, actions, board


def gather(policy, layout, iteration, rollouts, seed, beta, min_stage=1,
           mock_options=None, verbose=True):
    generator = numpy.random.default_rng(seed * 1000 + iteration)
    observations = []
    goals = []
    actions = []
    episodes = []
    steps = []
    boards = []

    for index in range(rollouts):
        one_obs, one_goal, one_act, board = _episode(
            policy, layout, seed + iteration * 100 + index, beta, generator,
            min_stage=min_stage, mock_options=mock_options)
        base = iteration * 1000 + index
        observations.extend(one_obs)
        goals.extend(one_goal)
        actions.extend(one_act)
        episodes.extend([base] * len(one_obs))
        steps.extend(range(len(one_obs)))
        boards.append(board)
        if verbose:
            print(f"    rollout {index}: {len(one_obs)} states, "
                  f"served {board['served']}, lost {board['lost']}, "
                  f"expert {board['expert_fraction']:.0%}")
    return observations, goals, actions, episodes, steps, boards


def concatenate(base, observations, goals, actions, episodes, steps):
    if base is None:
        return DATA.Dataset(observations, actions, episodes, steps, {
            "schema": DATA.VERSION,
            "source": "dagger",
            "obs_schema": encode.VERSION,
            "act_schema": ENV.VERSION,
            "buttons": list(ENV.BUTTONS),
            "move_values": list(ENV.MOVE_VALUES),
            "warning": (
                "aggregated against mockgame, a model of PlateUp."),
        }, goals=goals)
    manifest = dict(base.manifest)
    manifest["source"] = "dagger"
    return DATA.Dataset(
        numpy.concatenate(
            [base.observations, numpy.asarray(
                observations, dtype=numpy.float32)]),
        numpy.concatenate(
            [base.actions, numpy.asarray(actions, dtype=numpy.int8)]),
        numpy.concatenate(
            [base.episodes, numpy.asarray(episodes, dtype=numpy.int32)]),
        numpy.concatenate(
            [base.steps, numpy.asarray(steps, dtype=numpy.int32)]),
        manifest,
        goals=numpy.concatenate(
            [base.goals, numpy.asarray(goals, dtype=numpy.float32)]))


def run(seed_dataset, seed_policy, output, layout, iterations=5, rollouts=3,
        epochs=20, hidden=128, seed=0, evaluation_episodes=4, min_stage=1,
        mock_options=None, verbose=True):
    aggregate = DATA.Dataset.load(seed_dataset) if seed_dataset else None
    policy = POLICY.ClonedPolicy.load(seed_policy)

    def measure(candidate, label):
        results = EVAL.rollout_goal_policy(
            candidate, layout=layout, episodes=evaluation_episodes, seed=901,
            min_stage=min_stage)
        summary = EVAL.summarise(results)
        served = summary.get("served", {}).get("median", 0.0)
        lost = summary.get("lost", {}).get("median", 0.0)
        completed = summary["day_completion"]["completed"]
        if verbose:
            print(f"  {label}: median served {served}, median lost {lost}, "
                  f"day completed {completed}/{evaluation_episodes}")
        return {
            "label": label,
            "median_served": served,
            "median_lost": lost,
            "days_completed": completed,
            "attempts": evaluation_episodes,
        }

    history = [measure(policy, "iteration 0 (behaviour cloning)")]
    best = {"score": (history[0]["median_served"],
                      -history[0]["median_lost"]),
            "policy": policy, "iteration": 0}

    for iteration in range(1, iterations + 1):
        # Classic DAgger decay. Iteration 1 is half expert so the aggregate
        # gains useful states quickly; the last iterations are near-pure
        # on-policy, which is where the recovery labels come from.
        beta = 0.5 ** iteration
        if verbose:
            print(f"\niteration {iteration}  beta {beta:.3f}")
        observations, goals, actions, episodes, steps, boards = gather(
            policy, layout, iteration, rollouts, seed + 1, beta,
            min_stage=min_stage, mock_options=mock_options, verbose=verbose)
        aggregate = concatenate(
            aggregate, observations, goals, actions, episodes, steps)
        if verbose:
            print(f"    aggregate now {len(aggregate)} states")

        candidate = POLICY.ClonedPolicy(
            aggregate.inputs.shape[1], POLICY.head_sizes(),
            hidden=hidden, seed=seed)
        training, validation = aggregate.split(fraction=0.15, seed=seed)
        candidate.fit(
            training, epochs=epochs, seed=seed, validation=None,
            verbose=False)
        candidate.manifest = {
            "trained_from": "dagger",
            "seed_policy": os.path.normpath(seed_policy),
            "seed_dataset": (
                os.path.normpath(seed_dataset) if seed_dataset else None),
            "dataset_source": "dagger",
            "obs_schema": encode.VERSION,
            "act_schema": ENV.VERSION,
            "goal_conditioned": bool(aggregate.goal_conditioned),
            "iterations": iteration,
            "aggregate_states": len(aggregate),
            "epochs": epochs,
            "hidden": hidden,
            "warning": "trained against mockgame, a model of PlateUp.",
        }

        scores = candidate.score(validation)
        record = measure(candidate, f"iteration {iteration}")
        record.update({
            "beta": beta,
            "aggregate_states": len(aggregate),
            "validation_accuracy": scores["mean_accuracy"],
            "validation_balanced": scores["mean_balanced"],
            "rollout_served": [board["served"] for board in boards],
        })
        history.append(record)

        score = (record["median_served"], -record["median_lost"])
        if score > best["score"]:
            best = {"score": score, "policy": candidate,
                    "iteration": iteration}
            policy = candidate
        else:
            # Keep collecting from the newest policy even when it scored
            # worse: the point is coverage of states, and a worse policy
            # visits states the better one does not.
            policy = candidate

    best["policy"].manifest["selected_iteration"] = best["iteration"]
    if output:
        best["policy"].save(output)
    return best, aggregate, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed_policy")
    parser.add_argument("output")
    parser.add_argument("--dataset", default=os.path.join(
        "runs", "datasets", "reference-goal.npz"))
    parser.add_argument("--layout", default=os.path.join(
        "runs", "demos", "smoke.jsonl"))
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--rollouts", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--eval-episodes", type=int, default=4,
                        dest="evaluation_episodes")
    parser.add_argument("--aggregate", dest="aggregate_path")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()

    best, aggregate, history = run(
        args.dataset, args.seed_policy, args.output, args.layout,
        iterations=args.iterations, rollouts=args.rollouts,
        epochs=args.epochs, hidden=args.hidden, seed=args.seed,
        evaluation_episodes=args.evaluation_episodes)

    print()
    print(f"{VERSION}  best iteration {best['iteration']}, "
          f"median served {best['score'][0]}")
    print(f"aggregate {len(aggregate)} states")
    print("wrote " + os.path.normpath(args.output))
    if args.aggregate_path:
        print("wrote " + aggregate.save(args.aggregate_path))
    if args.json_path:
        os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump({
                "schema": VERSION,
                "selected_iteration": best["iteration"],
                "history": history,
                "aggregate_states": len(aggregate),
            }, output, indent=2, sort_keys=True)
        print("wrote " + os.path.normpath(args.json_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
