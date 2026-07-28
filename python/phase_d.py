"""
Phase D acceptance harness -- episode automation.

    python python/phase_d.py ready
    python python/phase_d.py terminate
    python python/phase_d.py request X
    python python/phase_d.py reset N
    python python/phase_d.py timescale

Results append to docs/phase-d-results.md.

Two measurements determine the downstream training architecture:

1. Reset wall-clock time (median and p90).
2. Whether Time.timeScale above 1 preserves movement fidelity.
"""

import math
import os
import statistics
import sys
import time

from bridge import PlateUpBridge, player, unit_toward


RESULTS = os.path.join(
    os.path.dirname(__file__), "..", "docs", "phase-d-results.md")

# GameStateRequest values discovered in PlayerManager.HandleRequest. The mod
# intentionally permits only None, InLocalMenu, InstantJoin, StartPractice, and
# QuitSection. The last one still requires the game's confirmation popup.
REQUESTS = [
    "None",
    "InLocalMenu",
    "Disconnect",
    "QuitSection",
    "InstantJoin",
    "KickUser",
    "StartPractice",
    "QuitToLobby",
]


def next_obs(bridge, restaurant=True, timeout=30.0):
    started_at = time.time()
    while time.time() - started_at < timeout:
        message = bridge.recv()
        if message.get("kind") != "obs":
            continue
        if restaurant and not message.get("in_restaurant"):
            bridge.idle()
            continue
        return message
    raise TimeoutError("no matching observation")


def any_obs(bridge):
    while True:
        message = bridge.recv()
        if message.get("kind") == "obs":
            return message


def wait_for_ack(bridge, command_id, timeout=5.0):
    """Wait until an observation proves a command reached the Unity thread."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        observation = any_obs(bridge)
        if observation.get("ack_command", 0) >= command_id:
            return observation
    raise TimeoutError(f"command {command_id} was not acknowledged")


def pulse(bridge, **action):
    """Apply one action edge, then acknowledge its neutral release."""
    command_id = bridge.send(**action)
    observation = wait_for_ack(bridge, command_id)
    release_id = bridge.idle()
    return wait_for_ack(bridge, release_id)


def wait_for_state(bridge, predicate, description, timeout=10.0):
    """Keep the bridge heartbeat alive while waiting for an observed state."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        command_id = bridge.idle()
        last = wait_for_ack(bridge, command_id)
        if predicate(last):
            return last
    raise TimeoutError(f"timed out waiting for {description}; last={summarise(last or {})}")


def request_and_confirm(bridge, name, timeout=10.0):
    """
    Pulse a request that opens GenericChoiceView, wait for its input capture,
    and press MenuSelect. Both StartPractice and QuitSection use this path.
    """
    before = any_obs(bridge)
    if before.get("input_captured"):
        raise RuntimeError(
            "another popup already owns input; close it before issuing " + name)
    if name == "StartPractice" and "start_day_warnings" not in before:
        raise RuntimeError(
            "StartPractice is only valid during preparation, while "
            "SStartDayWarnings exists")

    pulse(bridge, request=name)
    popup = wait_for_state(
        bridge,
        lambda observation: observation.get("input_captured", False),
        f"{name} confirmation popup",
        timeout)
    after_select = pulse(bridge, menu_select=True)

    # QuitSection may replace the choice popup with game-over UI immediately,
    # so game_over is also a completed confirmation state.
    completed = wait_for_state(
        bridge,
        lambda observation: (
            observation.get("game_over", False)
            or not observation.get("input_captured", False)
            or not observation.get("in_restaurant", False)
        ),
        f"{name} confirmation to complete",
        timeout)
    return before, popup, after_select, completed


def require_override(observation):
    if not observation.get("override"):
        raise SystemExit(
            "press F9 in game to hand control to the bridge, then re-run")


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def log(section, lines):
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    with open(RESULTS, "a", encoding="utf-8") as output:
        output.write(f"\n## {section} -- {stamp}\n\n")
        for line in lines:
            output.write(line + "\n")
    print(f"\n-> appended to {os.path.normpath(RESULTS)}")


def summarise(observation):
    return (
        f"day={observation.get('day')} "
        f"t={observation.get('seconds_elapsed', 0):.0f}/"
        f"{observation.get('day_length', 0):.0f} "
        f"$={observation.get('money')} lives={observation.get('lives')} "
        f"over={observation.get('game_over')} "
        f"groups={len(observation.get('groups', []))}"
    )


# ------------------------------------------------------------------- ready


def run_ready():
    """Press Start through SecondaryAction1/Interact3 and observe service begin."""
    print("\nStand in the restaurant during PREPARATION.")
    print("The agent will hold Ready and watch for the day to begin.\n")

    with PlateUpBridge() as bridge:
        observation = next_obs(bridge)
        require_override(observation)

        before_day = observation.get("day")
        before_seconds = observation.get("seconds_elapsed", 0)
        print(f"before: {summarise(observation)}")

        started_at = time.time()
        elapsed = None
        for _ in range(400):
            bridge.send(ready=True)
            observation = any_obs(bridge)
            if observation.get("seconds_elapsed", 0) > before_seconds + 1.0:
                elapsed = time.time() - started_at
                break
        bridge.idle()
        print(f"after:  {summarise(observation)}")

    ok = elapsed is not None
    lines = [
        f"- day before: **{before_day}**, "
        f"seconds before: **{before_seconds:.1f}**",
        f"- day started: **{'yes in %.1fs' % elapsed if ok else 'NO'}**",
        f"- verdict: {'PASS' if ok else 'FAIL -- Ready did not start service'}",
    ]
    log("Phase D -- agent-initiated day start", lines)
    return ok


# --------------------------------------------------------------- terminate


def run_terminate():
    """
    Deliberately abandon the current restaurant and verify LossReason.Quitting.
    """
    print("\nTERMINATE abandons the current restaurant.")
    print("It will request QuitSection and accept the confirmation popup.\n")

    saw_game_over = False
    reason = None
    frames = 0
    left_restaurant = False
    before = None

    try:
        with PlateUpBridge() as bridge:
            observation = next_obs(bridge)
            require_override(observation)
            before = summarise(observation)
            print(f"before: {before}")

            _, _, _, observation = request_and_confirm(
                bridge, "QuitSection", timeout=12.0)

            deadline = time.time() + 12.0
            while time.time() < deadline:
                frames += 1
                if observation.get("game_over"):
                    saw_game_over = True
                    reason = observation.get("loss_reason")
                    print(f"\n  *** GAME OVER, loss_reason={reason} ***")
                    print(f"  {summarise(observation)}")
                    break
                if not observation.get("in_restaurant"):
                    left_restaurant = True
                    print("\n  *** RESTAURANT SECTION CLOSED ***")
                    break
                command_id = bridge.idle()
                observation = wait_for_ack(bridge, command_id)
    except KeyboardInterrupt:
        pass
    except (ConnectionError, OSError):
        # A scene/section teardown can close the client before one final obs.
        left_restaurant = True

    ok = saw_game_over or left_restaurant
    lines = [
        f"- before: `{before}`",
        f"- frames observed: **{frames}**",
        f"- SGameOver observed: **{saw_game_over}**",
        f"- restaurant section closed: **{left_restaurant}**",
        f"- loss_reason: **{reason}**",
        f"- verdict: {'PASS' if ok else 'FAIL -- quit was not applied'}",
    ]
    log("Phase D -- termination", lines)
    return ok


# ----------------------------------------------------------------- request


def run_request(name):
    """Apply one GameStateRequest and log observable phase changes."""
    if name not in REQUESTS:
        raise SystemExit(f"unknown request; choose: {', '.join(REQUESTS)}")

    print(f"\nProbing GameStateRequest.{name}")
    print("Watch the game. Ctrl+C when enough behavior has been observed.\n")

    frames = 0
    changes = []

    try:
        with PlateUpBridge() as bridge:
            observation = any_obs(bridge)
            require_override(observation)
            print(f"before: {summarise(observation)}")
            previous = (
                observation.get("in_restaurant"),
                observation.get("day"),
                observation.get("paused"),
                observation.get("input_captured"),
            )

            if name in ("StartPractice", "QuitSection"):
                _, _, _, observation = request_and_confirm(bridge, name)
                current = (
                    observation.get("in_restaurant"),
                    observation.get("day"),
                    observation.get("paused"),
                    observation.get("input_captured"),
                )
                if current != previous:
                    change = f"  confirmed: {previous} -> {current}"
                    changes.append(change)
                    print(change)
                    previous = current
            else:
                pulse(bridge, request=name)

            for _ in range(300):
                if (
                    name == "QuitSection"
                    and (
                        observation.get("game_over")
                        or not observation.get("in_restaurant")
                    )
                ):
                    break
                bridge.idle()
                observation = any_obs(bridge)
                frames += 1
                current = (
                    observation.get("in_restaurant"),
                    observation.get("day"),
                    observation.get("paused"),
                    observation.get("input_captured"),
                )
                if current != previous:
                    change = f"  frame {frames}: {previous} -> {current}"
                    changes.append(change)
                    print(change)
                    previous = current
    except KeyboardInterrupt:
        pass
    except (ConnectionError, OSError):
        if name != "QuitSection":
            raise
        change = "  connection closed while the restaurant section was unloading"
        changes.append(change)
        print(change)

    lines = [
        f"### `{name}`",
        f"- frames after pulse: **{frames}**",
        f"- state changes: **{len(changes)}**",
    ] + changes + [
        "- tuple is `(in_restaurant, day, paused, input_captured)`",
        "- StartPractice and QuitSection include their required MenuSelect "
        "confirmation",
    ]
    log(f"Phase D -- request probe: {name}", lines)


# ------------------------------------------------------------------- reset


def percentile90(values):
    """Nearest-rank p90 for an already sorted non-empty sequence."""
    index = max(0, math.ceil(0.9 * len(values)) - 1)
    return values[index]


def run_reset(n=20):
    """
    Time terminal/reset-to-first-controllable-tick cycles using StartPractice.
    """
    print(f"\n{n} reset cycles. This repeatedly requests practice mode.\n")

    times = []
    failures = 0

    with PlateUpBridge() as bridge:
        observation = next_obs(bridge)
        require_override(observation)

        for index in range(n):
            # StartPractice enters practice; it does not restart an existing
            # practice session. Interact3/SecondaryAction1 leaves practice and
            # reloads the pre-practice autosave before the next cycle.
            if "start_day_warnings" not in observation:
                pulse(bridge, secondary1=True)
                observation = wait_for_state(
                    bridge,
                    lambda frame: (
                        frame.get("in_restaurant")
                        and "start_day_warnings" in frame
                    ),
                    "practice autosave to reload",
                    timeout=45.0)

            started_at = time.time()

            _, _, _, observation = request_and_confirm(
                bridge, "StartPractice", timeout=12.0)
            observation = wait_for_state(
                bridge,
                lambda frame: "start_day_warnings" not in frame,
                "practice mode to start",
                timeout=20.0)

            controllable = False
            deadline = started_at + 30.0
            while time.time() < deadline:
                bridge.send(move=(0.3, 0.0))
                observation = any_obs(bridge)
                if (
                    observation.get("in_restaurant")
                    and not observation.get("input_captured")
                    and player(observation) is not None
                ):
                    p0 = player(observation)
                    start = (p0["x"], p0["z"])
                    for _ in range(15):
                        bridge.send(move=(0.3, 0.0))
                        observation = any_obs(bridge)
                    p1 = player(observation)
                    if dist((p1["x"], p1["z"]), start) > 0.05:
                        controllable = True
                        break

            elapsed = time.time() - started_at
            bridge.idle()

            if controllable:
                times.append(elapsed)
                print(f"  {index + 1}/{n}: {elapsed:.2f}s")
            else:
                failures += 1
                print(f"  {index + 1}/{n}: FAILED after {elapsed:.1f}s")

            time.sleep(1.0)

    if not times:
        log("Phase D -- reset throughput", [
            "- **all resets failed** — StartPractice semantics did not match "
            "the assumed reset path",
        ])
        return False

    times.sort()
    median = statistics.median(times)
    p90 = percentile90(times)

    steps_per_day = 2500
    day_seconds = 240
    seconds_per_episode = day_seconds + median
    episodes_per_hour = 3600 / seconds_per_episode
    steps_per_hour = episodes_per_hour * steps_per_day
    hours_for_5m = 5_000_000 / max(steps_per_hour, 1)

    lines = [
        f"- attempts: **{n}**, failures: **{failures}**",
        f"- median: **{median:.2f}s**",
        f"- p90: **{p90:.2f}s**",
        f"- min/max: **{times[0]:.2f}s / {times[-1]:.2f}s**",
        "",
        "### Implied throughput (one instance, 1x)",
        "",
        f"- assumed episode: {day_seconds}s game + {median:.0f}s reset "
        f"= **{seconds_per_episode:.0f}s**",
        f"- episodes/hour: **{episodes_per_hour:.1f}**",
        f"- steps/hour at 10 Hz: **{steps_per_hour:,.0f}**",
        f"- wall clock for 5M steps: **{hours_for_5m:,.0f} hours "
        f"({hours_for_5m / 24:.0f} days)**",
        "",
        "If this is measured in weeks, the semi-MDP surrogate is mandatory. "
        "Motor control can remain in-game while higher-level control trains "
        "against the capability-registry interface.",
    ]
    log("Phase D -- reset throughput", lines)
    print("\n" + "\n".join(lines))
    return failures == 0


# --------------------------------------------------------------- timescale


def approach_trial(bridge, target, timeout=10.0):
    started_at = time.time()
    error = float("inf")
    while time.time() - started_at < timeout:
        observation = next_obs(bridge)
        p = player(observation)
        current = (p["x"], p["z"])
        error = dist(current, target)
        if error < 0.2:
            bridge.idle()
            return True, time.time() - started_at, error
        mx, mz, remaining = unit_toward(
            current[0], current[1], target[0], target[1])
        scale = min(1.0, remaining / 0.8)
        bridge.send(move=(mx * scale, mz * scale))
    bridge.idle()
    return False, time.time() - started_at, error


def run_timescale():
    """
    Measure one manually configured Time.timeScale. Repeat at 1x and candidate
    accelerated values, then compare the appended result sections.
    """
    scale = input("\nCurrent Time.timeScale (set manually): ").strip()
    trials = 10
    hits = 0
    times = []
    errors = []

    with PlateUpBridge() as bridge:
        observation = next_obs(bridge)
        require_override(observation)
        p = player(observation)
        home = (p["x"], p["z"])
        print(f"home = ({home[0]:.2f}, {home[1]:.2f})\n")

        for index in range(trials):
            angle = 2 * math.pi * index / trials
            radius = 1.0 + (index % 3) * 0.3
            target = (
                home[0] + radius * math.cos(angle),
                home[1] + radius * math.sin(angle),
            )

            arrived, seconds, error = approach_trial(bridge, target)
            if arrived:
                hits += 1
                times.append(seconds)
            errors.append(error)
            print(f"  {index + 1}: {'ok' if arrived else 'MISS'} "
                  f"{seconds:.2f}s err {error:.3f}")

            approach_trial(bridge, home)

    lines = [
        f"### timeScale = {scale}",
        f"- arrivals: **{hits}/{trials}**",
        f"- median time: **{statistics.median(times):.2f}s**"
        if times else "- median time: n/a",
        f"- median error: **{statistics.median(errors):.3f}**",
        "",
        "Compare with 1x. Acceptance is an arrival rate within two percentage "
        "points of the 1x result. Degradation makes acceleration unsafe for "
        "motor training even if discrete timers still scale correctly.",
    ]
    log("Phase D -- time scale fidelity", lines)
    print("\n" + "\n".join(lines))


# -------------------------------------------------------------------- main


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if not arguments:
        print(__doc__)
        sys.exit(1)

    mode = arguments[0]
    if mode == "ready":
        sys.exit(0 if run_ready() else 1)
    if mode == "terminate":
        sys.exit(0 if run_terminate() else 1)
    if mode == "request":
        run_request(arguments[1] if len(arguments) > 1 else "None")
    elif mode == "reset":
        sys.exit(
            0 if run_reset(
                int(arguments[1]) if len(arguments) > 1 else 20
            ) else 1)
    elif mode == "timescale":
        run_timescale()
    else:
        print(__doc__)
        sys.exit(1)
