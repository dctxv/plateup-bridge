r"""
Behaviour-cloning datasets for the steak service task.

    python python/dataset.py model runs/datasets/reference.npz --episodes 24
    python python/dataset.py demo  runs/datasets/human.npz runs/demos/smoke.jsonl
    python python/dataset.py inspect runs/datasets/reference.npz

Two sources, one format.

**model** rolls the reference controller out against `mockgame` and records
what it saw and what it did. Specification section 10.4 step 1 permits
scripted labels used only to construct training data, which is exactly this.
It is a dataset about a model of the game, and a policy cloned from it has
learned the model, not PlateUp.

**demo** reads a `demo_0.1` human recording and reconstructs the same pairs
from the native `InputState` stream. This is the path specification section
10.1 actually asks for. It works today on `runs/demos/smoke.jsonl`, which is a
real steak Day 1 but a short one in which the demonstrator never cooked, so it
is enough to validate the pipeline and not enough to train on.

Alignment, for the demo path. Native input arrives at render cadence and
observations at simulation cadence, so several input frames share one bridge
tick and many fall between two observations. Each observation is paired with
the input frames that arrived at or before its tick and after the previous
one, and their movement is averaged while their buttons are OR-ed: a press
anywhere inside the interval is a press for that step. Observations with no
input in their interval are dropped rather than filled with neutral, because a
fabricated "do nothing" label is worse than a missing one.

The stored arrays are:

    observations  (n, encoder.size) float32
    goals         (n, goal_encoder.size) float32, what the chef was trying to
                  do; empty when the dataset is state-only
    actions       (n, 2 + len(env.BUTTONS)) int8, MultiDiscrete indices
    episodes      (n,) int32, so trajectories can be split without leakage
    steps         (n,) int32, index within the episode

A state-only dataset is kept possible on purpose: cloning from one is what
demonstrated that the goal is necessary, and that measurement is worth being
able to reproduce.

plus a JSON manifest describing provenance, schema versions and the encoder
field names, so a saved dataset can be read back without guessing.
"""

import argparse
import json
import os
import sys

import numpy

import encode
import env as ENV
import options as O
import steak as S
from observe import ObservationClient

VERSION = "dataset_0.1"

# Two observation intervals, matching the interaction pairing window the
# demonstration analyzer already uses.
INPUT_WINDOW_TICKS = 12

BUTTON_PRESSED = 3
BUTTON_HELD = 2


def _blank(size, actions):
    return {
        "observations": numpy.zeros((0, size), dtype=numpy.float32),
        "actions": numpy.zeros((0, actions), dtype=numpy.int8),
        "episodes": numpy.zeros((0,), dtype=numpy.int32),
        "steps": numpy.zeros((0,), dtype=numpy.int32),
    }


class Dataset:
    """Aligned observation and action pairs, with their provenance."""

    def __init__(self, observations, actions, episodes, steps, manifest,
                 goals=None):
        self.observations = numpy.asarray(observations, dtype=numpy.float32)
        self.actions = numpy.asarray(actions, dtype=numpy.int8)
        self.episodes = numpy.asarray(episodes, dtype=numpy.int32)
        self.steps = numpy.asarray(steps, dtype=numpy.int32)
        self.manifest = dict(manifest)
        if goals is None:
            goals = numpy.zeros((len(self.observations), 0),
                                dtype=numpy.float32)
        self.goals = numpy.asarray(goals, dtype=numpy.float32)

    @property
    def inputs(self):
        """What the policy actually sees: state, then goal."""
        if self.goals.shape[1] == 0:
            return self.observations
        return numpy.concatenate([self.observations, self.goals], axis=1)

    @property
    def goal_conditioned(self):
        return self.goals.shape[1] > 0

    def __len__(self):
        return len(self.observations)

    @property
    def heads(self):
        return self.actions.shape[1]

    def split(self, fraction=0.2, seed=0):
        """Hold out whole episodes, never individual steps.

        Consecutive frames inside an episode are almost identical, so a random
        step-level split leaks the answer across the boundary and reports a
        validation score that means nothing.
        """
        unique = numpy.unique(self.episodes)
        generator = numpy.random.default_rng(seed)
        shuffled = unique.copy()
        generator.shuffle(shuffled)
        held = max(1, int(round(len(shuffled) * fraction)))
        validation = set(shuffled[:held].tolist())
        mask = numpy.array(
            [episode in validation for episode in self.episodes])
        return self._subset(~mask), self._subset(mask)

    def _subset(self, mask):
        return Dataset(
            self.observations[mask], self.actions[mask],
            self.episodes[mask], self.steps[mask], self.manifest,
            goals=self.goals[mask])

    def head_distribution(self):
        """How often each value of each head appears.

        A head that is one value 99% of the time is a head a classifier can
        win on by never predicting anything else, so the numbers matter before
        any accuracy is quoted.
        """
        rows = []
        for head in range(self.heads):
            values, counts = numpy.unique(
                self.actions[:, head], return_counts=True)
            rows.append({
                int(value): int(count)
                for value, count in zip(values, counts)})
        return rows

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        numpy.savez_compressed(
            path,
            observations=self.observations,
            goals=self.goals,
            actions=self.actions,
            episodes=self.episodes,
            steps=self.steps,
            manifest=json.dumps(self.manifest, sort_keys=True))
        return os.path.normpath(path)

    @classmethod
    def load(cls, path):
        with numpy.load(path, allow_pickle=False) as payload:
            manifest = json.loads(str(payload["manifest"]))
            if manifest.get("schema") != VERSION:
                raise ValueError(
                    f"{path}: dataset schema {manifest.get('schema')!r} "
                    f"!= {VERSION!r}")
            goals = (
                payload["goals"] if "goals" in payload.files else None)
            return cls(
                payload["observations"], payload["actions"],
                payload["episodes"], payload["steps"], manifest,
                goals=goals)


# --------------------------------------------------------------------------
# from the reference controller against the model
# --------------------------------------------------------------------------


def from_model(layout, episodes=16, seed=1, min_stage=1, verbose=False,
               skip_preparation=True, goal_conditioned=True, **mock_kwargs):
    import mockgame
    import service

    encoder = None
    goal_encoder = encode.GoalEncoder()
    observations = []
    goals = []
    actions = []
    episode_ids = []
    steps = []
    scoreboards = []

    for index in range(episodes):
        game = mockgame.MockPlateUp(
            layout, seed=seed + index, **mock_kwargs)
        client = ObservationClient(announce=False)
        client.feed(game.dictionary)
        chain = game.chain
        if encoder is None:
            encoder = encode.Encoder(chain)
        planner = service.SteakPlanner(chain, min_stage=min_stage)
        runner = service.Runner(planner, chain)

        frame = game.observation()
        step = 0
        guard = int(400.0 / mockgame.FRAME_SECONDS)
        for _ in range(guard):
            world = client.feed(frame)
            ctx = runner.context(world)
            fields = runner.act(ctx)
            # Preparation is a different problem from service and its labels
            # would teach a motor policy to hold Ready in the kitchen.
            if not (skip_preparation and world.start_day_warnings is not None):
                observations.append(encoder.encode(ctx))
                goals.append(goal_encoder.encode(runner.option, ctx))
                actions.append(ENV.encode_action(fields))
                episode_ids.append(index)
                steps.append(step)
                step += 1
            frame = game.step(fields)
            if game.day_finished or game.game_over:
                break
        scoreboards.append(game.scoreboard())
        if verbose:
            print(f"  episode {index}: {step} steps, "
                  f"{game.scoreboard()['served']} served")

    manifest = {
        "schema": VERSION,
        "source": "model",
        "layout": os.path.normpath(layout),
        "episodes": episodes,
        "seed": seed,
        "min_stage": min_stage,
        "mock_options": {k: v for k, v in mock_kwargs.items()},
        "controller": "reference_v1",
        "obs_schema": encode.VERSION,
        "act_schema": ENV.VERSION,
        "fields": encoder.field_names() if encoder else [],
        "goal_fields": goal_encoder.field_names(),
        "buttons": list(ENV.BUTTONS),
        "move_values": list(ENV.MOVE_VALUES),
        "served": [board["served"] for board in scoreboards],
        "lost": [board["lost"] for board in scoreboards],
        "warning": (
            "recorded against mockgame, a model of PlateUp. A policy cloned "
            "from this has learned the model."),
    }
    return Dataset(
        observations, actions, episode_ids, steps, manifest,
        goals=goals if goal_conditioned else None)


# --------------------------------------------------------------------------
# from a human demonstration
# --------------------------------------------------------------------------


def _button_index(states):
    """One held-down bit for an interval of native button states."""
    return 1 if any(
        state in (BUTTON_PRESSED, BUTTON_HELD) for state in states) else 0


def from_demonstration(path, cut=None, skip_preparation=True):
    """Rebuild observation/action pairs from a `demo_0.1` recording."""
    client = ObservationClient(announce=False)
    frames = []
    inputs = []
    hello = None
    manifest_frame = None

    with open(path, encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            kind = message.get("kind")
            if kind == "demo_input":
                inputs.append(message)
                continue
            if kind == "hello":
                hello = message
            elif kind == "manifest":
                manifest_frame = message
            world = client.feed(message)
            if world is not None:
                frames.append(message)

    if not frames:
        raise ValueError(f"{path}: no observations")
    if not inputs:
        raise ValueError(
            f"{path}: no demo_input frames; this is an observation-only "
            "recording and carries no actions to clone")

    # The active demonstrator is the source that actually did something. A
    # second, neutral device source appears in recordings and must not be
    # averaged in.
    active = {}
    for frame in inputs:
        moved = abs(frame.get("move_x", 0.0)) + abs(frame.get("move_y", 0.0))
        pressed = any(
            frame.get(name) in (BUTTON_PRESSED, BUTTON_HELD)
            for name in ("grab", "interact", "secondary1", "stop"))
        if moved > 0.01 or pressed:
            active[frame.get("player")] = active.get(frame.get("player"), 0) + 1
    if not active:
        raise ValueError(f"{path}: no active input source")
    player = max(active, key=active.get)
    inputs = [frame for frame in inputs if frame.get("player") == player]
    inputs.sort(key=lambda frame: (frame.get("tick") or 0,
                                   frame.get("seq") or 0))

    replay = ObservationClient(announce=False)
    chain = None
    encoder = None
    observations = []
    actions = []
    episode_ids = []
    steps = []
    dropped = 0

    cursor = 0
    previous_tick = None
    for message in frames:
        world = replay.feed(message)
        if world is None:
            continue
        if chain is None:
            chain = S.Chain(cut or S.infer_cut(world) or "plain")
            encoder = encode.Encoder(chain)
        if skip_preparation and world.start_day_warnings is not None:
            previous_tick = world.tick
            continue

        window = []
        while cursor < len(inputs) and (inputs[cursor].get("tick") or 0) <= \
                world.tick:
            if previous_tick is None or \
                    (inputs[cursor].get("tick") or 0) > previous_tick:
                window.append(inputs[cursor])
            cursor += 1
        previous_tick = world.tick
        if not window:
            dropped += 1
            continue

        move_x = sum(f.get("move_x", 0.0) for f in window) / len(window)
        move_y = sum(f.get("move_y", 0.0) for f in window) / len(window)
        fields = {"move": (move_x, move_y)}
        for name in ENV.BUTTONS:
            source_name = "stop" if name == "stop" else name
            fields[name] = bool(_button_index(
                [f.get(source_name) for f in window]))

        ctx = O.Context(world, chain)
        observations.append(encoder.encode(ctx))
        actions.append(ENV.encode_action(fields))
        episode_ids.append(0)
        steps.append(len(steps))

    manifest = {
        "schema": VERSION,
        "source": "demonstration",
        "path": os.path.normpath(path),
        "recorded_at": (manifest_frame or {}).get("recorded_at"),
        "declared_recipe": (
            (manifest_frame or {}).get("metadata") or {}).get("recipe"),
        "derived_cut": chain.cut if chain else None,
        "bridge_version": (hello or {}).get("bridge_version"),
        "mod_hash": (hello or {}).get("mod_hash"),
        "demo_schema": (hello or {}).get("demo_schema"),
        "obs_schema": encode.VERSION,
        "act_schema": ENV.VERSION,
        "fields": encoder.field_names() if encoder else [],
        "buttons": list(ENV.BUTTONS),
        "move_values": list(ENV.MOVE_VALUES),
        "input_player": player,
        "input_frames": len(inputs),
        "observations_without_input": dropped,
    }
    return Dataset(observations, actions, episode_ids, steps, manifest)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def describe(data):
    lines = [
        f"{data.manifest.get('schema')}  source "
        f"{data.manifest.get('source')}",
        f"  samples      {len(data)}",
        f"  episodes     {len(set(data.episodes.tolist()))}",
        f"  observation  {data.observations.shape[1]} floats "
        f"({data.manifest.get('obs_schema')})",
        f"  goal         {data.goals.shape[1]} floats"
        + ("" if data.goal_conditioned else "  (state-only dataset)"),
        f"  action heads {data.heads} ({data.manifest.get('act_schema')})",
    ]
    names = ["move_x", "move_y"] + list(data.manifest.get("buttons", ()))
    for name, counts in zip(names, data.head_distribution()):
        total = sum(counts.values()) or 1
        share = max(counts.values()) / total
        lines.append(
            f"    {name:<12} {counts}   most common {share:.1%}")
    if data.manifest.get("warning"):
        lines.append(f"  note: {data.manifest['warning']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_layout = os.path.join("runs", "demos", "smoke.jsonl")

    model = subparsers.add_parser("model")
    model.add_argument("output")
    model.add_argument("--layout", default=default_layout)
    model.add_argument("--episodes", type=int, default=16)
    model.add_argument("--seed", type=int, default=1)
    model.add_argument("--min-stage", type=int, default=1)
    model.add_argument("--groups", type=int)
    model.add_argument("--interval", type=float)
    model.add_argument("--plates", type=int)
    model.add_argument("--randomise-start", action="store_true",
                       dest="randomise_start",
                       help="specification section 10.3 step 3")
    model.add_argument("--state-only", action="store_true",
                       help="omit goals, reproducing the cloning failure that "
                            "motivated goal conditioning")

    demo = subparsers.add_parser("demo")
    demo.add_argument("output")
    demo.add_argument("recording")
    demo.add_argument("--cut", choices=sorted(S.CUTS))

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("path")

    args = parser.parse_args()

    if args.command == "inspect":
        print(describe(Dataset.load(args.path)))
        return 0

    if args.command == "model":
        options = {
            key: value
            for key, value in (("groups", args.groups),
                               ("interval", args.interval),
                               ("plates", args.plates))
            if value is not None}
        if args.randomise_start:
            options["randomise_start"] = True
        data = from_model(
            args.layout, episodes=args.episodes, seed=args.seed,
            min_stage=args.min_stage, verbose=True,
            goal_conditioned=not args.state_only, **options)
    else:
        data = from_demonstration(args.recording, cut=args.cut)

    print(describe(data))
    print("\nwrote " + data.save(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
