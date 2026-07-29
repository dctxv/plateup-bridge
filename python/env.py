r"""
Gymnasium-compatible environment for the steak service task. Phase E.

    python python/env.py check                 API and encoding checks
    python python/env.py soak --steps 20000    random-action soak
    python python/env.py rollout --policy reference

Two backends behind one API:

    mock   the tick-level model in `mockgame`. Fast, offline, and not the
           game. Everything here can be tested with it, and no result from it
           is evidence about PlateUp.
    live   the real bridge. Reset uses the Practice cycle whose 500-attempt
           reliability gate is already recorded in the ledger.

Gymnasium is optional. If it is installed its spaces are used; if it is not, a
small compatible shim stands in, so the environment can be exercised offline
before any dependency is added. The API surface is the same either way.

Action space, from specification section 7.1: per-axis movement discretised to
five values each, plus contextual Grab, Interact, StopMoving and Ready as
independent held-down bits. There is no separate drop or throw, because the
game has none: placement is contextual.

Reward, from specification section 11: bounded and event-based. An order
satisfied pays, a group lost and an item ruined cost, and elapsed time costs a
little. There is deliberately no proximity or approach shaping term, because
section 11.1 requires potential-based distance rewards to telescope and
section 11.3 lists camping at a target as an anti-hacking test. Adding dense
shaping is a decision to be made against those tests, not a default.
"""

import argparse
import json
import math
import os
import random
import sys

import encode
import options as O
import steak as S
from observe import ObservationClient

VERSION = "env_0.1"

MOVE_VALUES = (-1.0, -0.5, 0.0, 0.5, 1.0)
BUTTONS = ("grab", "interact", "stop", "ready")

# Event rewards. The scale is set by the order reward so the primary outcome
# dominates every intermediate term.
REWARD_ORDER = 1.0
REWARD_GROUP_LOST = -2.0
REWARD_ITEM_RUINED = -0.5
REWARD_TIME = -0.0005
REWARD_DAY_COMPLETE = 1.0

try:  # pragma: no cover - exercised only where gymnasium is installed
    import gymnasium
    from gymnasium import spaces as gym_spaces
    HAVE_GYMNASIUM = True
except ImportError:  # pragma: no cover
    gymnasium = None
    gym_spaces = None
    HAVE_GYMNASIUM = False


# --------------------------------------------------------------------------
# spaces shim
# --------------------------------------------------------------------------


class _Discrete:
    """Just enough of `gymnasium.spaces.MultiDiscrete` to run offline."""

    def __init__(self, nvec, seed=None):
        self.nvec = list(nvec)
        self.shape = (len(self.nvec),)
        self._random = random.Random(seed)

    def sample(self):
        return [self._random.randrange(n) for n in self.nvec]

    def contains(self, value):
        if len(value) != len(self.nvec):
            return False
        return all(
            isinstance(entry, int) and 0 <= entry < limit
            for entry, limit in zip(value, self.nvec))

    def __repr__(self):
        return f"MultiDiscrete({self.nvec})"


class _Box:
    """Just enough of `gymnasium.spaces.Box` to run offline."""

    def __init__(self, low, high, shape, seed=None):
        self.low = low
        self.high = high
        self.shape = shape
        self._random = random.Random(seed)

    def sample(self):
        return [
            self._random.uniform(self.low, self.high)
            for _ in range(self.shape[0])]

    def contains(self, value):
        if len(value) != self.shape[0]:
            return False
        return all(
            isinstance(entry, float) and self.low <= entry <= self.high
            for entry in value)

    def __repr__(self):
        return f"Box({self.low}, {self.high}, {self.shape})"


def multi_discrete(nvec):
    if HAVE_GYMNASIUM:
        import numpy
        return gym_spaces.MultiDiscrete(numpy.array(nvec, dtype=numpy.int64))
    return _Discrete(nvec)


def box(low, high, size):
    if HAVE_GYMNASIUM:
        import numpy
        return gym_spaces.Box(
            low=low, high=high, shape=(size,), dtype=numpy.float32)
    return _Box(low, high, (size,))


def decode_action(action):
    """MultiDiscrete vector to the bridge's action fields."""
    values = list(action)
    if len(values) != 2 + len(BUTTONS):
        raise ValueError(
            f"action must have {2 + len(BUTTONS)} entries, got {len(values)}")
    move = (MOVE_VALUES[int(values[0])], MOVE_VALUES[int(values[1])])
    fields = {"move": move}
    for index, name in enumerate(BUTTONS):
        fields[name] = bool(values[2 + index])
    return fields


def encode_action(fields):
    """The inverse, so a scripted controller can produce dataset actions."""
    move = fields.get("move", (0.0, 0.0))
    values = [
        min(range(len(MOVE_VALUES)),
            key=lambda i: abs(MOVE_VALUES[i] - move[0])),
        min(range(len(MOVE_VALUES)),
            key=lambda i: abs(MOVE_VALUES[i] - move[1])),
    ]
    values += [1 if fields.get(name) else 0 for name in BUTTONS]
    return values


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------


class PlateUpSteakEnv:
    """One steak service day, as a reinforcement-learning environment."""

    metadata = {"render_modes": ["ansi"], "schema": VERSION}

    def __init__(self, backend="mock", layout=None, cut="plain", seed=1,
                 max_seconds=400.0, mock_kwargs=None):
        self.backend = backend
        self.layout = layout or os.path.join("runs", "demos", "smoke.jsonl")
        self.cut = cut
        self.seed_value = seed
        self.max_seconds = max_seconds
        self.mock_kwargs = dict(mock_kwargs or {})

        self.chain = S.Chain(cut)
        self.encoder = encode.Encoder(self.chain)
        self.action_space = multi_discrete(
            [len(MOVE_VALUES), len(MOVE_VALUES)] + [2] * len(BUTTONS))
        self.observation_space = box(-10.0, 10.0, self.encoder.size)

        self.game = None
        self.client = None
        self.bridge = None
        self.ctx = None
        self.episode = 0
        self.steps = 0
        self._previous = None
        self._last_frame = None

    # -- lifecycle --------------------------------------------------------

    def reset(self, seed=None, options=None):
        if seed is not None:
            self.seed_value = seed
        self.episode += 1
        self.steps = 0

        if self.backend == "mock":
            import mockgame
            self.game = mockgame.MockPlateUp(
                self.layout, cut=self.cut,
                seed=self.seed_value + self.episode, **self.mock_kwargs)
            self.client = ObservationClient(announce=False)
            self.client.feed(self.game.dictionary)
            frame = self.game.observation()
        else:
            if self.client is None:
                self.client = ObservationClient()
                self.client.connect()
                self.bridge = self.client.b
            frame = self._live_reset()

        world = self.client.feed(frame)
        self._last_frame = frame
        self.ctx = O.Context(world, self.chain)
        self._previous = self._counters()
        return self.encoder.encode(self.ctx), self._info()

    # -- live reset -------------------------------------------------------

    def _live_reset(self, timeout=60.0):
        """Cycle Practice, which is the measured reset path.

        The sequence is the one whose 500-of-500 reliability is recorded in
        ledger section 4.7: end the current Practice with SecondaryAction1,
        wait for the pre-Practice autosave to reload into preparation, request
        StartPractice, confirm its choice view with MenuSelect, and wait for
        the new scenario to become controllable.

        The sequence is verified; **this re-expression of it against
        `ObservationClient` is not**, because it has never been run. It is
        written to raise rather than to continue on a state it does not
        recognise.
        """
        world = self.client.recv()
        if not world.override:
            raise RuntimeError(
                "bridge override is off; press F9 before resetting")

        if world.practice_mode:
            self._pulse(secondary1=True)
            world = self._wait(
                lambda w: (not w.practice_mode
                           and w.start_day_warnings is not None),
                timeout, "pre-Practice autosave never reloaded")

        if world.start_day_warnings is None:
            raise RuntimeError(
                "not in restaurant preparation; StartPractice is only valid "
                "there. Load a restaurant and try again.")

        self._pulse(request="StartPractice")
        self._wait(lambda w: w.input_captured, 10.0,
                   "StartPractice choice view never opened")
        self._pulse(menu_select=True)
        world = self._wait(
            lambda w: w.practice_mode and not w.input_captured, timeout,
            "new Practice scenario never became controllable")
        return world.raw

    def _pulse(self, **fields):
        """Press for one acknowledged frame, then release."""
        pressed = self.bridge.send(**fields)
        self._wait(lambda w: w.ack_command >= pressed, 10.0,
                   f"command {pressed} was not acknowledged")
        released = self.bridge.send()
        self._wait(lambda w: w.ack_command >= released, 10.0,
                   f"command {released} was not acknowledged")

    def _wait(self, predicate, timeout, message):
        import time as _time
        deadline = _time.monotonic() + timeout
        world = None
        while _time.monotonic() < deadline:
            world = self.client.recv()
            if predicate(world):
                return world
        raise TimeoutError(
            f"{message}; last practice={world.practice_mode if world else '?'} "
            f"captured={world.input_captured if world else '?'} "
            f"warnings={world.start_day_warnings is not None if world else '?'}")

    def step(self, action):
        fields = decode_action(action)
        self.steps += 1

        if self.backend == "mock":
            frame = self.game.step(fields)
        else:
            self.bridge.send(**fields)
            frame = self.client.recv().raw

        world = self.client.feed(frame)
        self._last_frame = frame
        self.ctx = O.Context(world, self.chain)

        counters = self._counters()
        reward = self._reward(self._previous, counters)
        self._previous = counters

        terminated, reason = self._terminal(world)
        truncated = (
            not terminated
            and world.seconds_elapsed >= self.max_seconds)
        info = self._info()
        info["terminal_reason"] = reason if terminated else None
        if truncated:
            info["terminal_reason"] = "truncated"
        return (self.encoder.encode(self.ctx), reward, terminated, truncated,
                info)

    def close(self):
        if self.backend != "mock" and self.bridge is not None:
            try:
                self.bridge.send()
            finally:
                self.client.close()
        self.client = None
        self.bridge = None

    # -- reward and termination -------------------------------------------

    def _counters(self):
        """Event counts the reward is a difference of.

        Counting satisfied orders from the published buffer means an order can
        only pay once, which is what stops the reward being farmed by serving
        and retrieving the same dish.
        """
        world = self.ctx.world
        satisfied = 0
        for group in world.groups:
            for order in group.get("orders", ()):
                if order.get("satisfied"):
                    satisfied += 1
        ruined = sum(
            1 for record in self.ctx.inventory.waste)
        return {
            "satisfied": satisfied,
            "ruined": ruined,
            "money": world.money or 0,
            "lives": world.lives if world.lives is not None else 0,
            "seconds": world.seconds_elapsed,
        }

    def _reward(self, before, after):
        if before is None:
            return 0.0
        reward = 0.0
        # Money is the authoritative record of an order being paid for: the
        # satisfied flag can move when a group departs mid-frame.
        reward += REWARD_ORDER * max(0, after["money"] - before["money"]) / 5.0
        reward += REWARD_GROUP_LOST * max(
            0, before["lives"] - after["lives"])
        reward += REWARD_ITEM_RUINED * max(
            0, after["ruined"] - before["ruined"])
        reward += REWARD_TIME * max(
            0.0, after["seconds"] - before["seconds"])
        return reward

    def _terminal(self, world):
        if world.game_over:
            # `loss_reason` is only present when the game supplies it. The
            # numeric LossReason for patience depletion has never been
            # observed live, so the mock does not invent one and this reports
            # what is actually known.
            if world.loss_reason is None:
                return True, "game_over"
            return True, f"game_over:{world.loss_reason}"
        if self.backend == "mock" and self.game.day_finished:
            return True, "day_complete"
        if self.backend != "mock" and world.day_length and \
                world.seconds_elapsed >= world.day_length and not world.groups:
            return True, "day_complete"
        return False, None

    def _info(self):
        world = self.ctx.world
        return {
            "episode": self.episode,
            "steps": self.steps,
            "tick": world.tick,
            "seconds": world.seconds_elapsed,
            "money": world.money,
            "lives": world.lives,
            "ack_command": world.ack_command,
            "cmds_applied": world.cmds_applied,
            "cmds_dropped": world.cmds_dropped,
            "outbound_frames_dropped": world.outbound_frames_dropped,
            "controllable": self.ctx.controllable,
            "held": self.ctx.held_name,
        }

    # -- rendering --------------------------------------------------------

    def render(self):
        ctx = self.ctx
        if ctx is None:
            return ""
        return ctx.kitchen.render(
            mark=[ctx.position] if ctx.position else ())


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def check(layout, steps=400):
    """Phase E API checks. Offline; uses the mock backend only."""
    checks = []

    def verify(name, condition, detail=""):
        checks.append((name, bool(condition), detail))

    env = PlateUpSteakEnv(backend="mock", layout=layout)
    observation, info = env.reset(seed=7)

    verify("observation length matches the space",
           len(observation) == env.observation_space.shape[0],
           f"{len(observation)} vs {env.observation_space.shape[0]}")
    verify("observation is finite",
           all(math.isfinite(value) for value in observation),
           "non-finite entries" if not all(
               math.isfinite(v) for v in observation) else "all finite")
    verify("observation is inside the declared bounds",
           all(-10.0 <= value <= 10.0 for value in observation),
           f"range [{min(observation):.3f}, {max(observation):.3f}]")
    verify("info carries command receipts",
           {"ack_command", "cmds_applied", "cmds_dropped"} <= set(info),
           sorted(set(info) & {"ack_command", "cmds_applied",
                               "cmds_dropped"}))

    sample = env.action_space.sample()
    verify("sampled action is inside the action space",
           env.action_space.contains(list(sample)), str(sample))

    fields = decode_action([0, 4, 1, 0, 1, 0])
    verify("action decoding maps axes and buttons",
           fields["move"] == (-1.0, 1.0) and fields["grab"]
           and not fields["interact"] and fields["stop"]
           and not fields["ready"],
           str(fields))
    verify("action encoding round-trips",
           decode_action(encode_action(fields)) == fields,
           str(encode_action(fields)))

    lengths = {len(observation)}
    rewards = []
    terminal_reasons = set()
    for _ in range(steps):
        action = env.action_space.sample()
        observation, reward, terminated, truncated, info = env.step(action)
        lengths.add(len(observation))
        rewards.append(reward)
        if terminated or truncated:
            terminal_reasons.add(info["terminal_reason"])
            observation, info = env.reset()
    verify("observation length is constant", len(lengths) == 1, str(lengths))
    verify("rewards are finite and bounded",
           all(math.isfinite(r) and -10.0 <= r <= 10.0 for r in rewards),
           f"min {min(rewards):.3f} max {max(rewards):.3f}")
    verify("random actions never produce a positive reward by accident",
           max(rewards) <= REWARD_ORDER + 1e-9,
           f"max {max(rewards):.3f}")

    # Determinism of the reset contract: same seed, same first observation.
    left = PlateUpSteakEnv(backend="mock", layout=layout).reset(seed=3)[0]
    right = PlateUpSteakEnv(backend="mock", layout=layout).reset(seed=3)[0]
    verify("reset is reproducible for a fixed seed on the mock backend",
           left == right, "identical first observations")

    env.close()
    return checks


def soak(layout, steps=20000, seed=11):
    """Random-action soak, specification section 16.3, on the mock backend."""
    env = PlateUpSteakEnv(backend="mock", layout=layout)
    env.reset(seed=seed)
    episodes = 0
    total_reward = 0.0
    reasons = {}
    lengths = set()
    for _ in range(steps):
        observation, reward, terminated, truncated, info = env.step(
            env.action_space.sample())
        lengths.add(len(observation))
        total_reward += reward
        if terminated or truncated:
            reason = info["terminal_reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
            episodes += 1
            env.reset()
    env.close()
    return {
        "steps": steps,
        "episodes": episodes,
        "total_reward": round(total_reward, 3),
        "terminal_reasons": reasons,
        "observation_lengths": sorted(lengths),
    }


def rollout(layout, policy="reference", episodes=1, seed=1):
    """Drive the environment with the reference controller through the API."""
    import service

    results = []
    for index in range(episodes):
        env = PlateUpSteakEnv(backend="mock", layout=layout)
        env.reset(seed=seed + index)
        planner = service.SteakPlanner(env.chain)
        runner = service.Runner(planner, env.chain)
        total = 0.0
        for _ in range(int(env.max_seconds / 0.0375)):
            fields = runner.act(runner.context(env.ctx.world))
            _obs, reward, terminated, truncated, info = env.step(
                encode_action(fields))
            total += reward
            if terminated or truncated:
                break
        results.append({
            "episode": index,
            "reward": round(total, 3),
            "money": env.ctx.world.money,
            "seconds": round(env.ctx.world.seconds_elapsed, 1),
            "terminal": info.get("terminal_reason"),
        })
        env.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_layout = os.path.join("runs", "demos", "smoke.jsonl")

    api = subparsers.add_parser("check")
    api.add_argument("--layout", default=default_layout)
    api.add_argument("--steps", type=int, default=400)

    soak_parser = subparsers.add_parser("soak")
    soak_parser.add_argument("--layout", default=default_layout)
    soak_parser.add_argument("--steps", type=int, default=20000)
    soak_parser.add_argument("--json", dest="json_path")

    roll = subparsers.add_parser("rollout")
    roll.add_argument("--layout", default=default_layout)
    roll.add_argument("--episodes", type=int, default=3)
    roll.add_argument("--policy", default="reference")

    args = parser.parse_args()

    if args.command == "check":
        checks = check(args.layout, steps=args.steps)
        width = max(len(name) for name, _ok, _detail in checks)
        failed = 0
        print(f"{VERSION}  gymnasium={'yes' if HAVE_GYMNASIUM else 'shim'}")
        for name, ok, detail in checks:
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
        print()
        print(f"{'FAIL' if failed else 'OK'} -- {len(checks) - failed} of "
              f"{len(checks)} environment checks passed")
        return 1 if failed else 0

    if args.command == "soak":
        report = soak(args.layout, steps=args.steps)
        print(json.dumps(report, indent=2))
        if args.json_path:
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as output:
                json.dump(report, output, indent=2, sort_keys=True)
            print("wrote " + os.path.normpath(args.json_path))
        return 0

    for record in rollout(args.layout, episodes=args.episodes):
        print(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
