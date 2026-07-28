"""
Phase C acceptance harness.

Three test groups, run independently:

    python python/phase_c.py safety
    python python/phase_c.py frequency
    python python/phase_c.py soak N

Results append to docs/phase-c-results.md. These tests are interactive and
require PlateUp to be running in a restaurant. Override must be ON (F9).
"""

import math
import os
import random
import statistics
import subprocess
import sys
import time

from bridge import PlateUpBridge, player, unit_toward


RESULTS = os.path.join(
    os.path.dirname(__file__), "..", "docs", "phase-c-results.md")


# ---------------------------------------------------------------- utilities


def next_obs(bridge, want_restaurant=True):
    """Return the next observation frame, skipping dictionary frames."""
    while True:
        message = bridge.recv()
        if message.get("kind") != "obs":
            continue
        if want_restaurant and not message.get("in_restaurant"):
            bridge.idle()
            continue
        return message


def require_override(observation):
    if not observation.get("override"):
        raise SystemExit(
            "press F9 in game to hand control to the bridge, then re-run")


def log(section, lines):
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    with open(RESULTS, "a", encoding="utf-8") as output:
        output.write(f"\n## {section} -- {stamp}\n\n")
        for line in lines:
            output.write(line + "\n")
    print(f"\n-> appended to {os.path.normpath(RESULTS)}")


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ------------------------------------------------------------------- safety


def test_expiry(bridge):
    """
    Hold movement, then stop sending. The mod's watchdog should zero the axes
    after approximately 120 simulation ticks of silence.
    """
    print("\n[expiry] holding movement, then going silent...")

    for _ in range(30):
        bridge.send(move=(1.0, 0.0))
        next_obs(bridge)

    observation = next_obs(bridge)
    p = player(observation)
    start = (p["x"], p["z"])
    started_at = time.time()

    # Keep reading so the outbound pipe cannot back up, but send no actions.
    stopped_at = None
    last = start
    for _ in range(400):
        observation = next_obs(bridge)
        p = player(observation)
        current = (p["x"], p["z"])
        if dist(current, last) < 0.005 and stopped_at is None:
            stopped_at = time.time() - started_at
        last = current
        if stopped_at and time.time() - started_at - stopped_at > 1.0:
            break

    drift = dist(start, last)
    ok = stopped_at is not None and drift < 3.0

    print(f"[expiry] stopped after {stopped_at}s, "
          f"drifted {drift:.2f} units")
    return ok, [
        f"- watchdog stop: **{stopped_at:.2f}s** after last command"
        if stopped_at else "- watchdog stop: **NEVER** (FAIL)",
        f"- drift after last command: **{drift:.2f}** world units",
        f"- verdict: {'PASS' if ok else 'FAIL'}",
    ]


def test_phase_transitions(bridge):
    """
    Hold movement across input-capture boundaries. Interactively open and close
    the pause menu, then press Ctrl+C after captured frames have been observed.
    """
    print("\n[phase] holding movement. Open and close the pause menu now.")
    print("        Ctrl+C when done.\n")

    captured_frames = 0
    moved_while_captured = 0
    total = 0
    last = None

    try:
        while True:
            bridge.send(move=(1.0, 0.0))
            observation = next_obs(bridge, want_restaurant=False)
            total += 1

            p = player(observation)
            if p is None:
                continue
            current = (p["x"], p["z"])

            if observation.get("input_captured"):
                captured_frames += 1
                if last and dist(current, last) > 0.02:
                    moved_while_captured += 1
            last = current

            if total % 60 == 0:
                print(f"  {total} frames, {captured_frames} captured, "
                      f"{moved_while_captured} moved-while-captured")
    except KeyboardInterrupt:
        pass

    bridge.idle()
    ok = captured_frames > 0 and moved_while_captured == 0
    note = (
        "" if captured_frames else
        "  (no capture observed -- test inconclusive, open a menu next time)")

    print(f"\n[phase] {captured_frames} captured frames, "
          f"{moved_while_captured} with motion{note}")
    return ok, [
        f"- frames observed: **{total}**",
        f"- frames with input captured: **{captured_frames}**",
        f"- motion while captured: **{moved_while_captured}** (want 0)",
        f"- verdict: "
        f"{'PASS' if ok else 'INCONCLUSIVE' if not captured_frames else 'FAIL'}",
    ]


def test_disconnect():
    """
    Spawn a child that starts moving and exits without cleanup. Reconnect and
    confirm that the chef is stationary.
    """
    print("\n[disconnect] spawning child to move and die...")

    child = os.path.join(os.path.dirname(__file__), "_disconnect_child.py")
    with open(child, "w", encoding="utf-8") as output:
        output.write(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
            "from bridge import PlateUpBridge\n"
            "b = PlateUpBridge(); b.connect()\n"
            "for _ in range(60):\n"
            "    b.send(move=(1.0, 0.0))\n"
            "    b.recv()\n"
            "os._exit(1)\n"
        )

    try:
        process = subprocess.Popen([sys.executable, child])
        process.wait()
        print("[disconnect] child died. reconnecting...")
        time.sleep(1.5)

        with PlateUpBridge() as bridge:
            observation = next_obs(bridge)
            p = player(observation)
            start = (p["x"], p["z"])
            for _ in range(40):
                bridge.idle()
                observation = next_obs(bridge)
            p = player(observation)
            end = (p["x"], p["z"])
    finally:
        if os.path.exists(child):
            os.remove(child)

    drift = dist(start, end)
    ok = drift < 0.15

    print(f"[disconnect] drift after reconnect: {drift:.3f} units")
    return ok, [
        f"- drift after hard client kill: **{drift:.3f}** world units",
        f"- verdict: {'PASS' if ok else 'FAIL -- inputs left held'}",
    ]


def run_safety():
    lines = []
    with PlateUpBridge() as bridge:
        observation = next_obs(bridge)
        require_override(observation)
        ok_expiry, expiry_lines = test_expiry(bridge)
        lines += ["### Command expiry"] + expiry_lines

    ok_disconnect, disconnect_lines = test_disconnect()
    lines += ["", "### Hard disconnect"] + disconnect_lines

    with PlateUpBridge() as bridge:
        next_obs(bridge)
        ok_phase, phase_lines = test_phase_transitions(bridge)
        lines += ["", "### Phase transitions"] + phase_lines

    log("Phase C safety", lines)
    return all([ok_expiry, ok_disconnect, ok_phase])


# ---------------------------------------------------------------- frequency


def walk_trial(bridge, target, hz, timeout=12.0):
    """
    Approach one target at a fixed decision rate.

    Returns (arrived, seconds, closest_error, overshoot).
    """
    period = 1.0 / hz
    started_at = time.time()
    next_decision = started_at
    best = 1e9
    overshoot = 0.0
    move = (0.0, 0.0)

    while time.time() - started_at < timeout:
        observation = next_obs(bridge)
        p = player(observation)
        current = (p["x"], p["z"])
        distance = dist(current, target)

        if distance < best:
            best = distance
        elif best < 0.5:
            overshoot = max(overshoot, distance - best)

        now = time.time()
        if now >= next_decision:
            next_decision = now + period
            mx, mz, remaining = unit_toward(
                current[0], current[1], target[0], target[1])
            scale = min(1.0, remaining / 0.8)
            move = (mx * scale, mz * scale)

        bridge.send(move=move)

        if distance < 0.2:
            bridge.idle()
            return True, time.time() - started_at, distance, overshoot

    bridge.idle()
    return False, time.time() - started_at, best, overshoot


def run_frequency():
    """
    Measure arrival accuracy and time at candidate policy decision rates.
    """
    rates = [10, 12, 15, 20]
    trials = 8
    rows = []

    with PlateUpBridge() as bridge:
        observation = next_obs(bridge)
        require_override(observation)
        p = player(observation)
        home = (p["x"], p["z"])

        print(f"\nhome = ({home[0]:.2f}, {home[1]:.2f})")
        print("running approach trials at each rate...\n")

        for hz in rates:
            times = []
            errors = []
            overshoots = []
            hits = 0

            for i in range(trials):
                angle = 2 * math.pi * i / trials
                radius = 2.0 + (i % 3) * 0.5
                target = (
                    home[0] + radius * math.cos(angle),
                    home[1] + radius * math.sin(angle),
                )

                arrived, seconds, error, overshoot = walk_trial(
                    bridge, target, hz)
                if arrived:
                    hits += 1
                    times.append(seconds)
                errors.append(error)
                overshoots.append(overshoot)

                walk_trial(bridge, home, hz)

            if times:
                row = (
                    f"| {hz} | {hits}/{trials} | "
                    f"{statistics.median(times):.2f} | ")
            else:
                row = f"| {hz} | {hits}/{trials} | - | "
            row += (
                f"{statistics.median(errors):.3f} | "
                f"{max(overshoots):.3f} |")
            rows.append(row)

            print(f"  {hz:>2} Hz: {hits}/{trials} arrived, "
                  f"median err {statistics.median(errors):.3f}, "
                  f"max overshoot {max(overshoots):.3f}")

    lines = [
        "| Hz | arrived | median s | median err | max overshoot |",
        "|---:|---:|---:|---:|---:|",
    ] + rows + [
        "",
        "Choose the lowest rate meeting the motor gate: >=98% arrival, "
        "<=2% overshoot failures. Lower rates mean fewer policy evaluations "
        "per game second.",
        "",
        "This uses a proportional controller, not a learned policy. It measures "
        "the control channel, not final motor quality.",
    ]
    log("Phase C control frequency", lines)


# --------------------------------------------------------------------- soak


def run_soak(n=100000):
    """
    Send random bounded commands while watching for stuck input, desync, and
    unbounded latency.
    """
    print(f"\nsoak: {n} commands. Ctrl+C to stop early.\n")

    sent = 0
    received = 0
    max_gap = 0.0
    stalls = 0
    errors = []
    bridge_dropped = 0
    bridge_unacked = 0
    started_at = time.time()
    last_pos = None
    frozen = 0
    blocked_frames = 0

    # Pause requests are deliberately excluded from a random soak.
    requests = ["None"]

    try:
        with PlateUpBridge() as bridge:
            observation = next_obs(bridge)
            require_override(observation)

            while sent < n:
                bridge.send(
                    move=(
                        random.uniform(-1, 1),
                        random.uniform(-1, 1),
                    ),
                    grab=random.random() < 0.05,
                    interact=random.random() < 0.05,
                    secondary1=random.random() < 0.01,
                    secondary2=random.random() < 0.01,
                    stop=random.random() < 0.02,
                    request=random.choice(requests),
                )
                sent += 1

                wait_started = time.time()
                try:
                    message = bridge.recv()
                except Exception as exc:
                    errors.append(f"{sent}: {exc}")
                    break
                gap = time.time() - wait_started
                max_gap = max(max_gap, gap)
                if gap > 1.0:
                    stalls += 1

                if message.get("kind") == "obs":
                    received += 1
                    p = player(message)
                    if p:
                        current = (p["x"], p["z"])
                        blocked = (
                            message.get("input_captured")
                            or message.get("paused")
                            or p.get("captured")
                        )
                        if blocked:
                            frozen = 0
                            blocked_frames += 1
                        elif last_pos and dist(current, last_pos) < 1e-4:
                            frozen += 1
                        else:
                            frozen = 0
                        last_pos = current

                        if frozen > 600:
                            errors.append(
                                f"{sent}: position frozen 600 frames while "
                                f"input was not captured")
                            break

                if sent % 5000 == 0:
                    elapsed = time.time() - started_at
                    print(f"  {sent} sent, {received} obs, "
                          f"{sent / elapsed:.0f}/s, "
                          f"max gap {max_gap * 1000:.0f}ms, stalls {stalls}")

                bridge_dropped = bridge.dropped
                bridge_unacked = bridge.unacked
    except KeyboardInterrupt:
        print("\ninterrupted")

    elapsed = time.time() - started_at
    ok = not errors and stalls < sent / 1000

    lines = [
        f"- commands sent: **{sent}**",
        f"- observations received: **{received}**",
        f"- duration: **{elapsed:.0f}s** "
        f"({sent / max(elapsed, 1):.0f} cmd/s)",
        f"- max round-trip gap: **{max_gap * 1000:.0f}ms**",
        f"- stalls >1s: **{stalls}**",
        f"- frames with input blocked: **{blocked_frames}**",
        f"- commands dropped by mod: **{bridge_dropped}**",
        f"- unacknowledged at end: **{bridge_unacked}**",
        f"- errors: **{len(errors)}**",
    ] + [f"  - {error}" for error in errors[:10]] + [
        f"- verdict: {'PASS' if ok else 'FAIL'}",
    ]

    log("Phase C soak", lines)
    print("\n" + "\n".join(lines))
    return ok


# --------------------------------------------------------------------- main


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if not arguments:
        print(__doc__)
        sys.exit(1)

    mode = arguments[0]
    if mode == "safety":
        sys.exit(0 if run_safety() else 1)
    if mode == "frequency":
        run_frequency()
    elif mode == "soak":
        sys.exit(
            0 if run_soak(
                int(arguments[1]) if len(arguments) > 1 else 100000
            ) else 1)
    else:
        print(__doc__)
        sys.exit(1)
