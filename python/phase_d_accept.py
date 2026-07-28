"""
Phase D acceptance harness -- reset throughput + timescale fidelity.

Commands:
    python python/phase_d_accept.py reset 20
    python python/phase_d_accept.py reset 500
    python python/phase_d_accept.py timescale x
    python python/phase_d_accept.py timescale -z
    python python/phase_d_accept.py all 20

Reset gate:
    >=99% successful Practice exit/reload/re-entry cycles. Records median,
    p90, p99, episodes/hour, and estimated wall time for 5M policy steps.

Timescale gate:
    The same compact one-tile shuttle at 1x/2x/3x. Choose a clear direction:
    x (right), -x (left), z (up), or -z (down). Arrival rate must remain
    within 2 percentage points of 1x and distance per scaled game-second must
    remain within 2%. Raw sampled trajectories are saved with the result.

Start inside an active Practice restaurant with bridge override enabled (F9).
F5/F6/F7 select the mod's measurement speed of 1x/2x/3x.

Why reset does not use QuitSection:
    QuitSection abandons the restaurant and transitions outside SLayout.
    StartPractice is only handled during restaurant preparation while
    SStartDayWarnings exists, so it cannot bootstrap a new restaurant from HQ.
    The sanctioned repeatable cycle is EndPractice (SecondaryAction1), load the
    pre-Practice autosave, then StartPractice and confirm.

Why timescale does not use seconds_elapsed:
    AdvanceTime deliberately freezes STime.SecondsSinceDayBegan in Practice.
    The harness uses the emitted SGameTime.TotalTime clock instead.
"""

import json
import math
import os
import statistics
import sys
import time

import win32file
import win32pipe


PIPE = r"\\.\pipe\plateup_bridge"
OBS_SCHEMA = "obs_0.1"
ACT_SCHEMA = "act_0.1"
PROTOCOL = 1
RESULTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "runs", "phase_d"))


# ---------------------------------------------------------------- pipe client


class PipeClient:
    def __init__(self, connect_timeout=30.0):
        self.handle = None
        self._buf = b""
        self._cmd_id = 0
        self.tick = -1
        self.hello = None
        self.names = None

        deadline = time.monotonic() + connect_timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                self.handle = win32file.CreateFile(
                    PIPE,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None)
                win32pipe.SetNamedPipeHandleState(
                    self.handle, win32pipe.PIPE_READMODE_BYTE, None, None)
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.5)
        if self.handle is None:
            raise TimeoutError("no bridge pipe after %.0fs: %s"
                               % (connect_timeout, last_error))

        self.hello = self._read_frame(timeout=5.0)
        if self.hello.get("kind") != "hello":
            raise RuntimeError("first frame was not hello: %r" % self.hello)
        for key, want in (
                ("protocol", PROTOCOL),
                ("obs_schema", OBS_SCHEMA),
                ("act_schema", ACT_SCHEMA)):
            if self.hello.get(key) != want:
                raise RuntimeError(
                    "schema mismatch %s: got %r want %r"
                    % (key, self.hello.get(key), want))

        self.names = self._read_frame(timeout=5.0)
        if self.names.get("kind") != "dict":
            raise RuntimeError("second frame was not dict: %r" % self.names)
        print("connected: session=%s game=%s bridge=%s mod=%s"
              % (self.hello.get("session_id", "?")[:8],
                 self.hello.get("game_version"),
                 self.hello.get("bridge_version"),
                 self.hello.get("mod_hash")))

    def close(self):
        if self.handle is not None:
            try:
                win32file.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _read_frame(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            newline = self._buf.find(b"\n")
            if newline >= 0:
                line, self._buf = (
                    self._buf[:newline], self._buf[newline + 1:])
                line = line.strip()
                if line:
                    return json.loads(line.decode("utf-8"))
                continue

            _, available, _ = win32pipe.PeekNamedPipe(self.handle, 0)
            if available:
                _, data = win32file.ReadFile(
                    self.handle, min(available, 65536))
                self._buf += data
            else:
                time.sleep(0.002)
        raise TimeoutError("no frame within %.1fs" % timeout)

    def recv_obs(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no obs within %.1fs" % timeout)
            frame = self._read_frame(remaining)
            if frame.get("kind") == "obs":
                self.tick = frame.get("tick", self.tick)
                return frame

    def send_action(
            self, move_x=0.0, move_y=0.0, grab=False, interact=False,
            secondary1=False, secondary2=False, ready=False,
            menu_select=False, menu_cancel=False, request="None"):
        self._cmd_id += 1
        frame = {
            "Tick": self.tick,
            "CommandId": self._cmd_id,
            "MoveX": float(move_x),
            "MoveY": float(move_y),
            "Grab": bool(grab),
            "Interact": bool(interact),
            "Secondary1": bool(secondary1),
            "Secondary2": bool(secondary2),
            "StopMoving": False,
            "Ready": bool(ready),
            "MenuSelect": bool(menu_select),
            "MenuCancel": bool(menu_cancel),
            "MenuUp": False,
            "MenuDown": False,
            "MenuLeft": False,
            "MenuRight": False,
            "Request": request,
        }
        win32file.WriteFile(
            self.handle, (json.dumps(frame) + "\n").encode("utf-8"))
        return self._cmd_id

    def neutral(self):
        return self.send_action()


# ---------------------------------------------------------------- helpers


def player_pos(obs):
    players = obs.get("players") or []
    if not players:
        return None
    return (players[0].get("x", 0.0), players[0].get("z", 0.0))


def controllable(obs):
    return (
        obs.get("in_restaurant") is True
        and obs.get("paused") is False
        and obs.get("input_captured") is False
        and obs.get("game_over") is False
        and bool(obs.get("players")))


def wait_for(client, predicate, timeout, label):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = client.recv_obs(
                timeout=min(1.0, max(0.1, deadline - time.monotonic())))
        except TimeoutError:
            continue
        if predicate(last):
            return last
    summary = None
    if last is not None:
        summary = {
            key: last.get(key)
            for key in (
                "tick", "in_restaurant", "practice_mode", "paused",
                "input_captured", "game_over", "game_speed")
        }
    raise TimeoutError("%s; last=%r" % (label, summary))


def wait_ack(client, command_id, timeout=5.0):
    return wait_for(
        client,
        lambda obs: obs.get("ack_command", 0) >= command_id,
        timeout,
        "command %d was not acknowledged" % command_id)


def pulse(client, **kwargs):
    pressed_id = client.send_action(**kwargs)
    wait_ack(client, pressed_id)
    released_id = client.neutral()
    return wait_ack(client, released_id)


def pct(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, math.ceil(percentile / 100.0 * len(ordered)) - 1))
    return ordered[index]


def finite_or_none(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def result_path(kind):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(RESULTS_DIR, "%s-%s.json" % (kind, stamp))


def save_result(kind, client, payload):
    path = result_path(kind)
    document = {
        "kind": "phase_d_%s" % kind,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "manifest": client.hello,
        **payload,
    }
    with open(path, "w", encoding="utf-8") as output:
        json.dump(document, output, indent=2, allow_nan=False)
        output.write("\n")
    print("saved: %s" % path)
    return path


# ---------------------------------------------------------------- reset


def one_reset(client):
    """
    Active Practice -> EndPractice -> autosave reload/preparation ->
    StartPractice confirmation -> first controllable Practice observation.
    """
    t0 = time.monotonic()

    # EndPracticeView consumes SecondaryAction1/Controls.Interact3.
    pulse(client, secondary1=True)

    wait_for(
        client,
        lambda obs: (
            controllable(obs)
            and obs.get("practice_mode") is False
            and "start_day_warnings" in obs),
        timeout=45.0,
        label="pre-Practice autosave never reloaded")

    pulse(client, request="StartPractice")
    wait_for(
        client,
        lambda obs: obs.get("input_captured") is True,
        timeout=8.0,
        label="StartPractice choice view never opened")
    pulse(client, menu_select=True)

    observation = wait_for(
        client,
        lambda obs: controllable(obs) and obs.get("practice_mode") is True,
        timeout=30.0,
        label="new Practice scenario never became controllable")
    return time.monotonic() - t0, observation


def run_reset(attempts):
    with PipeClient() as client:
        first = wait_for(
            client,
            lambda obs: controllable(obs) and obs.get("practice_mode") is True,
            timeout=10.0,
            label="start inside Practice with override ON")
        if not first.get("override"):
            raise RuntimeError("bridge override is OFF; press F9")

        day_length = float(first.get("day_length") or 180.0)
        times = []
        failures = []

        for index in range(attempts):
            try:
                duration, _ = one_reset(client)
                times.append(duration)
                print("  reset %3d/%d  %6.2fs"
                      % (index + 1, attempts, duration))
            except TimeoutError as exc:
                failures.append({"attempt": index + 1, "error": str(exc)})
                print("  reset %3d/%d  FAILED: %s"
                      % (index + 1, attempts, exc))
                print("  Recover manually to active Practice with F9 ON, "
                      "then press Enter.")
                input()
                wait_for(
                    client,
                    lambda obs: (
                        controllable(obs)
                        and obs.get("practice_mode") is True),
                    timeout=60.0,
                    label="manual recovery did not reach Practice")
            time.sleep(0.5)

        successes = len(times)
        success_rate = successes / float(attempts) if attempts else 0.0
        median = statistics.median(times) if times else None
        p90 = pct(times, 90)
        p99 = pct(times, 99)
        passed = bool(times) and success_rate >= 0.99

        throughput = None
        if median is not None:
            control_hz = 10.0
            episode_wall_1x = day_length + median
            episodes_hour_1x = 3600.0 / episode_wall_1x
            steps_episode = day_length * control_hz
            hours_5m_1x = 5e6 / (episodes_hour_1x * steps_episode)
            episode_wall_3x = day_length / 3.0 + median
            episodes_hour_3x = 3600.0 / episode_wall_3x
            hours_5m_3x = 5e6 / (episodes_hour_3x * steps_episode)
            throughput = {
                "day_game_seconds": day_length,
                "control_hz": control_hz,
                "steps_per_episode": steps_episode,
                "episodes_per_hour_1x": episodes_hour_1x,
                "hours_for_5m_steps_1x": hours_5m_1x,
                "episodes_per_hour_3x_if_approved": episodes_hour_3x,
                "hours_for_5m_steps_3x_if_approved": hours_5m_3x,
            }

        payload = {
            "attempts": attempts,
            "successes": successes,
            "failures": failures,
            "success_rate": success_rate,
            "durations_seconds": times,
            "median_seconds": median,
            "p90_seconds": p90,
            "p99_seconds": p99,
            "throughput": throughput,
            "gate": {"minimum_success_rate": 0.99, "passed": passed},
        }
        save_result("reset", client, payload)

        print("\n=== RESET RESULTS (n=%d) ===" % attempts)
        print("success rate : %5.1f%%  (gate: >=99%%)"
              % (success_rate * 100.0))
        if median is not None:
            print("median/p90/p99: %.2fs / %.2fs / %.2fs"
                  % (median, p90, p99))
            print("episodes/hour: %.1f at 1x"
                  % throughput["episodes_per_hour_1x"])
            print("5M steps     : %.0f hours at 1x; %.0f at 3x if approved"
                  % (throughput["hours_for_5m_steps_1x"],
                     throughput["hours_for_5m_steps_3x_if_approved"]))
        print("verdict      : %s" % ("PASS" if passed else "FAIL"))
        return passed


# ---------------------------------------------------------------- timescale


SHUTTLE_DISTANCE = 0.9
ARRIVE = 0.18
LAPS = 12


def shuttle_course(direction):
    vectors = {
        "x": (1.0, 0.0),
        "-x": (-1.0, 0.0),
        "z": (0.0, 1.0),
        "-z": (0.0, -1.0),
    }
    if direction not in vectors:
        raise ValueError("direction must be one of: x, -x, z, -z")
    dx, dz = vectors[direction]
    return [
        (dx * SHUTTLE_DISTANCE, dz * SHUTTLE_DISTANCE),
        (0.0, 0.0),
    ]


def drive_course(client, label, expected_speed, course):
    observation = wait_for(
        client,
        lambda obs: (
            controllable(obs)
            and obs.get("practice_mode") is True
            and abs(float(obs.get("game_speed", 0)) - expected_speed) < 0.01),
        timeout=10.0,
        label="not controllable at %s or game_speed was not applied" % label)

    origin = player_pos(observation)
    waypoints = [
        (origin[0] + offset_x, origin[1] + offset_z)
        for offset_x, offset_z in course
    ]
    trajectory = []
    lap_times = []
    arrivals = 0
    misses = 0
    distance = 0.0
    previous = origin
    game_start = float(observation.get("game_total_time", 0.0))

    for lap in range(LAPS):
        lap_start = float(observation.get("game_total_time", game_start))
        for waypoint_index, (waypoint_x, waypoint_z) in enumerate(waypoints):
            deadline = time.monotonic() + 8.0
            while True:
                observation = client.recv_obs(timeout=5.0)
                position = player_pos(observation)
                if position is None:
                    continue

                step_distance = math.hypot(
                    position[0] - previous[0],
                    position[1] - previous[1])
                distance += step_distance
                previous = position

                delta_x = waypoint_x - position[0]
                delta_z = waypoint_z - position[1]
                remaining = math.hypot(delta_x, delta_z)
                trajectory.append({
                    "tick": observation.get("tick"),
                    "game_time": observation.get("game_total_time"),
                    "real_time": observation.get("real_total_time"),
                    "lap": lap,
                    "waypoint": waypoint_index,
                    "x": position[0],
                    "z": position[1],
                    "distance_to_waypoint": remaining,
                })

                if remaining < ARRIVE:
                    arrivals += 1
                    client.neutral()
                    break
                if time.monotonic() > deadline:
                    misses += 1
                    client.neutral()
                    break

                magnitude = max(remaining, 1e-6)
                speed = min(1.0, remaining / 0.35)
                client.send_action(
                    move_x=delta_x / magnitude * speed,
                    move_y=delta_z / magnitude * speed)

        lap_end = float(observation.get("game_total_time", lap_start))
        lap_times.append(lap_end - lap_start)

    client.neutral()
    game_end = float(observation.get("game_total_time", game_start))
    game_seconds = game_end - game_start
    total_targets = arrivals + misses
    return {
        "label": label,
        "game_speed": expected_speed,
        "arrivals": arrivals,
        "misses": misses,
        "arrival_rate": (
            arrivals / float(total_targets) if total_targets else 0.0),
        "distance": distance,
        "game_seconds": game_seconds,
        "distance_per_game_second": finite_or_none(
            distance / game_seconds if game_seconds > 0 else float("nan")),
        "median_lap_game_seconds": (
            statistics.median(lap_times) if lap_times else None),
        "lap_game_seconds": lap_times,
        "trajectory": trajectory,
    }


def run_timescale(direction="x"):
    course = shuttle_course(direction)
    with PipeClient() as client:
        first = wait_for(
            client,
            lambda obs: controllable(obs) and obs.get("practice_mode") is True,
            timeout=10.0,
            label="start inside Practice with override ON")
        if not first.get("override"):
            raise RuntimeError("bridge override is OFF; press F9")

        print("Timescale fidelity: %.1f-unit %s shuttle, %d out/back laps "
              "per speed." % (SHUTTLE_DISTANCE, direction, LAPS))
        print("Stand with one adjacent floor tile clear in that direction.")

        results = []
        for label, speed, key in (
                ("1x", 1.0, "F5"),
                ("2x", 2.0, "F6"),
                ("3x", 3.0, "F7")):
            input("\nPress %s in PlateUp for %s, then press Enter here..."
                  % (key, label))
            result = drive_course(client, label, speed, course)
            results.append(result)
            print(
                "  %s: arrivals %d/%d (%.1f%%), %.3f units/game-s, "
                "median lap %.2f game-s"
                % (label, result["arrivals"],
                   result["arrivals"] + result["misses"],
                   result["arrival_rate"] * 100.0,
                   result["distance_per_game_second"] or -1.0,
                   result["median_lap_game_seconds"] or -1.0))

        # Always restore normal speed before releasing control.
        print("\nPress F5 in PlateUp to restore 1x.")

        baseline = results[0]
        comparisons = []
        passed = True
        for result in results[1:]:
            arrival_delta_pp = abs(
                result["arrival_rate"] - baseline["arrival_rate"]) * 100.0
            baseline_distance = baseline["distance_per_game_second"] or 0.0
            result_distance = result["distance_per_game_second"] or 0.0
            distance_delta_percent = (
                abs(result_distance - baseline_distance)
                / baseline_distance * 100.0
                if baseline_distance > 0 else float("inf"))
            comparison_passed = (
                arrival_delta_pp <= 2.0
                and distance_delta_percent <= 2.0)
            passed = passed and comparison_passed
            comparisons.append({
                "label": result["label"],
                "arrival_delta_percentage_points": arrival_delta_pp,
                "distance_delta_percent": finite_or_none(
                    distance_delta_percent),
                "passed": comparison_passed,
            })

        payload = {
            "course_type": "one_tile_shuttle",
            "course_direction": direction,
            "course_offsets": course,
            "shuttle_distance": SHUTTLE_DISTANCE,
            "arrival_tolerance": ARRIVE,
            "laps": LAPS,
            "results": results,
            "comparisons_to_1x": comparisons,
            "gate": {
                "max_arrival_delta_percentage_points": 2.0,
                "max_distance_delta_percent": 2.0,
                "passed": passed,
            },
        }
        save_result("timescale", client, payload)

        print("\n=== TIMESCALE RESULTS ===")
        for comparison in comparisons:
            print("  %s: arrival delta %.1fpp, distance delta %.1f%%  %s"
                  % (comparison["label"],
                     comparison["arrival_delta_percentage_points"],
                     comparison["distance_delta_percent"]
                     if comparison["distance_delta_percent"] is not None
                     else float("inf"),
                     "PASS" if comparison["passed"] else "FAIL"))
        print("verdict: %s" % ("PASS" if passed else "FAIL"))
        return passed


# ---------------------------------------------------------------- main


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    command = sys.argv[1].lower()
    if command == "reset":
        attempts = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        return 0 if run_reset(attempts) else 1
    if command == "timescale":
        direction = sys.argv[2].lower() if len(sys.argv) > 2 else "x"
        return 0 if run_timescale(direction) else 1
    if command == "all":
        attempts = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        reset_passed = run_reset(attempts)
        direction = sys.argv[3].lower() if len(sys.argv) > 3 else "x"
        timescale_passed = run_timescale(direction)
        print("\n=== PHASE D GATE ===")
        print("reset: %s  timescale: %s"
              % ("PASS" if reset_passed else "FAIL",
                 "PASS" if timescale_passed else "FAIL"))
        return 0 if reset_passed and timescale_passed else 1

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
