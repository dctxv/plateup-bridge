"""
Record and verify human demonstrations from the native IInputConsumer stream.

Record:
    python python/demo_record.py record runs/demos/smoke.jsonl --recipe smoke
    python python/demo_record.py record runs/demos/burgers/day1-01.jsonl \
        --recipe burgers --scenario day1

Verify:
    python python/demo_record.py verify runs/demos/smoke.jsonl

Requirements:
    - PlateUp is in a restaurant.
    - F9 bridge override is OFF; play normally with keyboard/controller.
    - Keep PlateUp focused while demonstrating. InputSource does not offer raw
      device input to IInputConsumer while the game is unfocused.

The file is newline-delimited JSON and shares the bridge transport:
manifest, hello, dict, obs, demo_status, and demo_input frames.
"""

import argparse
import json
import math
import os
import sys
import time

from bridge import PlateUpBridge


DEMO_SCHEMA = "demo_0.1"
BUTTON_STATES = {0, 1, 2, 3, 4}
BUTTON_FIELDS = (
    "interact",
    "grab",
    "secondary1",
    "secondary2",
    "stop",
    "menu_trigger",
    "menu_up",
    "menu_down",
    "menu_left",
    "menu_right",
    "menu_select",
    "menu_cancel",
)


def receive_initial_state(bridge, timeout=15.0):
    deadline = time.monotonic() + timeout
    frames = []
    observation = None
    while time.monotonic() < deadline:
        message = bridge.recv()
        frames.append(message)
        if message.get("kind") == "obs":
            observation = message
            break
    if observation is None:
        raise TimeoutError("no initial observation")
    return frames, observation


def record(path, recipe=None, scenario=None, note=None):
    if os.path.exists(path):
        raise FileExistsError(
            f"refusing to overwrite demonstration: {os.path.normpath(path)}")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with PlateUpBridge() as bridge:
        demo_schema = bridge.hello.get("demo_schema")
        if demo_schema != DEMO_SCHEMA:
            raise RuntimeError(
                f"demo schema mismatch: got {demo_schema!r}, "
                f"want {DEMO_SCHEMA!r}. Restart PlateUp with bridge 0.3.0+.")

        initial_frames, observation = receive_initial_state(bridge)
        if observation.get("override"):
            raise RuntimeError(
                "F9 override is ON. Turn it OFF before recording human input.")
        if not observation.get("in_restaurant"):
            raise RuntimeError("start the recorder inside a restaurant")

        metadata = {
            "recipe": recipe,
            "scenario": scenario,
            "note": note,
        }
        metadata = {
            key: value for key, value in metadata.items()
            if value is not None
        }
        manifest = {
            "kind": "manifest",
            "recording": "human_demonstration",
            "demo_schema": DEMO_SCHEMA,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "metadata": metadata,
            **bridge.manifest(),
        }

        with open(path, "x", encoding="utf-8", buffering=1) as output:
            output.write(json.dumps(manifest, separators=(",", ":")) + "\n")
            output.write(
                json.dumps(bridge.hello, separators=(",", ":")) + "\n")
            for frame in initial_frames:
                output.write(json.dumps(frame, separators=(",", ":")) + "\n")

            bridge.set_demo_recording(True)

            counts = {
                "messages": len(initial_frames) + 2,
                "obs": sum(
                    frame.get("kind") == "obs"
                    for frame in initial_frames),
                "demo": 0,
                "status": 0,
                "sequence_gaps": 0,
                "override_obs": 0,
            }
            last_sequence = None
            started = time.monotonic()
            enabled = False

            print(f"recording to {os.path.normpath(path)}")
            print("F9 must remain OFF. Focus PlateUp and play normally.")
            print("Return here and press Ctrl+C when finished.\n")

            try:
                while True:
                    message = bridge.recv()
                    output.write(
                        json.dumps(message, separators=(",", ":")) + "\n")
                    counts["messages"] += 1

                    kind = message.get("kind")
                    if kind == "obs":
                        counts["obs"] += 1
                        if message.get("override"):
                            counts["override_obs"] += 1
                    elif kind == "demo_status":
                        counts["status"] += 1
                        if message.get("enabled"):
                            enabled = True
                            print(
                                "native recorder enabled at bridge tick "
                                f"{message.get('tick')}")
                    elif kind == "demo_input":
                        counts["demo"] += 1
                        sequence = message.get("seq")
                        if (
                            last_sequence is not None
                            and sequence != last_sequence + 1
                        ):
                            counts["sequence_gaps"] += max(
                                1, sequence - last_sequence - 1)
                        last_sequence = sequence

                        if counts["demo"] % 600 == 0:
                            elapsed = time.monotonic() - started
                            print(
                                f"  {counts['demo']} input frames, "
                                f"{counts['obs']} observations, "
                                f"{counts['sequence_gaps']} sequence gaps, "
                                f"{elapsed:.0f}s")
            except KeyboardInterrupt:
                pass
            finally:
                try:
                    bridge.set_demo_recording(False)
                except Exception:
                    pass

            duration = time.monotonic() - started
            print(
                f"\nrecorded {counts['demo']} input frames and "
                f"{counts['obs']} observations in {duration:.1f}s")
            print(f"sequence gaps: {counts['sequence_gaps']}")
            if counts["override_obs"]:
                print(
                    "WARNING: F9 override was active in "
                    f"{counts['override_obs']} observation frames; "
                    "verification will reject this recording")
            if not enabled:
                print("WARNING: demo_status enabled was never received")
            print(f"saved: {os.path.normpath(path)}")
            print(
                "verify with:\n  python python/demo_record.py verify "
                + os.path.normpath(path))


def verify(path):
    manifest = None
    hello = None
    dictionary = None
    observations = 0
    demo_frames = 0
    enabled_status = 0
    disabled_status = 0
    sequence_gaps = 0
    invalid_buttons = 0
    invalid_numbers = 0
    invalid_requests = 0
    invalid_demo_schemas = 0
    override_observations = 0
    movement_frames = 0
    pressed_edges = 0
    released_edges = 0
    players = set()
    active_players = set()
    observed_players = set()
    last_sequence = None
    min_obs_tick = None
    max_obs_tick = None
    min_demo_tick = None
    max_demo_tick = None

    with open(path, encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"FAIL: invalid JSON on line {line_number}: {exc}")
                return False

            kind = message.get("kind")
            if kind == "manifest":
                manifest = message
            elif kind == "hello":
                hello = message
            elif kind == "dict":
                dictionary = message
            elif kind == "obs":
                observations += 1
                if message.get("override"):
                    override_observations += 1
                for player in message.get("players") or []:
                    player_id = player.get("id")
                    if isinstance(player_id, int):
                        observed_players.add(player_id)
                tick = message.get("tick")
                if isinstance(tick, int):
                    min_obs_tick = (
                        tick if min_obs_tick is None
                        else min(min_obs_tick, tick))
                    max_obs_tick = (
                        tick if max_obs_tick is None
                        else max(max_obs_tick, tick))
            elif kind == "demo_status":
                if message.get("enabled"):
                    enabled_status += 1
                else:
                    disabled_status += 1
            elif kind == "demo_input":
                demo_frames += 1
                if message.get("demo_schema") != DEMO_SCHEMA:
                    invalid_demo_schemas += 1
                sequence = message.get("seq")
                if (
                    last_sequence is not None
                    and sequence != last_sequence + 1
                ):
                    sequence_gaps += max(
                        1, sequence - last_sequence - 1)
                last_sequence = sequence

                tick = message.get("tick")
                if isinstance(tick, int):
                    min_demo_tick = (
                        tick if min_demo_tick is None
                        else min(min_demo_tick, tick))
                    max_demo_tick = (
                        tick if max_demo_tick is None
                        else max(max_demo_tick, tick))

                players.add(message.get("player"))
                move_x = message.get("move_x")
                move_y = message.get("move_y")
                frame_active = False
                if not (
                    isinstance(move_x, (int, float))
                    and isinstance(move_y, (int, float))
                    and math.isfinite(move_x)
                    and math.isfinite(move_y)
                ):
                    invalid_numbers += 1
                elif abs(move_x) > 1e-4 or abs(move_y) > 1e-4:
                    movement_frames += 1
                    frame_active = True

                for field in BUTTON_FIELDS:
                    value = message.get(field)
                    if value not in BUTTON_STATES:
                        invalid_buttons += 1
                    else:
                        if value != 0:
                            frame_active = True
                        if value == 3:
                            pressed_edges += 1
                        elif value == 1:
                            released_edges += 1

                request = message.get("request")
                if not isinstance(request, int) or not 0 <= request <= 7:
                    invalid_requests += 1
                elif request != 0:
                    frame_active = True
                if frame_active:
                    active_players.add(message.get("player"))

    problems = []
    if manifest is None:
        problems.append("missing manifest")
    elif manifest.get("demo_schema") != DEMO_SCHEMA:
        problems.append(
            f"manifest demo_schema={manifest.get('demo_schema')!r}")
    if hello is None:
        problems.append("missing hello")
    elif hello.get("demo_schema") != DEMO_SCHEMA:
        problems.append(f"hello demo_schema={hello.get('demo_schema')!r}")
    if dictionary is None:
        problems.append("missing dictionary")
    if observations < 2:
        problems.append(f"too few observations: {observations}")
    if enabled_status < 1:
        problems.append("no enabled demo_status")
    if demo_frames < 30:
        problems.append(f"too few demo_input frames: {demo_frames}")
    if invalid_demo_schemas:
        problems.append(
            f"demo frames with wrong schema: {invalid_demo_schemas}")
    if demo_frames and last_sequence != demo_frames:
        problems.append(
            "demo sequence must start at 1 and be contiguous: "
            f"{demo_frames} frames ended at {last_sequence!r}")
    if sequence_gaps:
        problems.append(f"demo sequence gaps: {sequence_gaps}")
    if invalid_buttons:
        problems.append(f"invalid button values: {invalid_buttons}")
    if invalid_numbers:
        problems.append(f"invalid movement numbers: {invalid_numbers}")
    if invalid_requests:
        problems.append(f"invalid request values: {invalid_requests}")
    if override_observations:
        problems.append(
            f"F9 override active in {override_observations} observations")
    if movement_frames < 1:
        problems.append("no non-neutral movement frame")
    if pressed_edges < 1:
        problems.append("no Pressed button edge; press Grab or Interact")
    if released_edges < 1:
        problems.append("no Released button edge")
    if not players or None in players:
        problems.append(f"invalid player identities: {sorted(players)}")
    if not active_players:
        problems.append("no active native-input player")
    unmatched_active = active_players - observed_players
    if unmatched_active:
        problems.append(
            "active input player absent from observations: "
            f"{sorted(unmatched_active)}")
    if (
        min_obs_tick is not None
        and max_obs_tick is not None
        and min_demo_tick is not None
        and max_demo_tick is not None
        and (
            max_demo_tick < min_obs_tick
            or min_demo_tick > max_obs_tick
        )
    ):
        problems.append("demo and observation tick ranges do not overlap")

    print(f"manifest: {json.dumps(manifest or {})}")
    print(f"hello:    bridge={(hello or {}).get('bridge_version')} "
          f"mod={(hello or {}).get('mod_hash')}")
    print(f"frames:   {demo_frames} demo, {observations} obs")
    print(f"sources:  {sorted(players)}")
    print(f"players:  active={sorted(active_players)} "
          f"observed={sorted(observed_players)}")
    print(f"motion:   {movement_frames} frames")
    print(f"edges:    {pressed_edges} pressed, {released_edges} released")
    print(f"sequence: {sequence_gaps} gaps")
    print(f"ticks:    demo {min_demo_tick}..{max_demo_tick}, "
          f"obs {min_obs_tick}..{max_obs_tick}")

    if problems:
        print("\nFAIL")
        for problem in problems:
            print("  - " + problem)
        return False

    print("\nOK -- native input and observations are aligned and gap-free")
    return True


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("path")
    record_parser.add_argument("--recipe")
    record_parser.add_argument("--scenario")
    record_parser.add_argument("--note")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "record":
        record(
            args.path,
            recipe=args.recipe,
            scenario=args.scenario,
            note=args.note)
        return 0
    return 0 if verify(args.path) else 1


if __name__ == "__main__":
    sys.exit(main())
