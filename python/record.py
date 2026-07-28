"""
Record a golden trace, and replay one to check the schema still parses.

Record a hand-played day:
    python python/record.py runs/golden/obs_0.1_day1.jsonl

Check a recorded trace against the current parser:
    python python/record.py --verify runs/golden/obs_0.1_day1.jsonl

The verify path is the regression test for obs_0.1: it asserts the customer
lifecycle transitions confirmed during Phase B still parse and still occur in
order. If a schema change breaks it, that is the signal to bump the version.
"""

import json
import os
import sys
import time

from bridge import PlateUpBridge
from observe import ObservationClient


def record(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with PlateUpBridge() as bridge, open(path, "w", encoding="utf-8") as output:
        # Manifest first: a trace without provenance is not reproducible data.
        output.write(json.dumps({"kind": "manifest", **bridge.manifest()}) + "\n")
        output.write(json.dumps(bridge.hello) + "\n")

        count = 0
        start = time.time()
        print(f"recording to {path} -- Ctrl+C to stop")
        try:
            while True:
                msg = bridge.recv()
                output.write(json.dumps(msg) + "\n")
                count += 1
                if msg.get("kind") == "obs" and count % 120 == 0:
                    print(f"  {count} frames, day {msg.get('day')}, "
                          f"{msg.get('seconds_elapsed', 0):.0f}s")
                bridge.idle()
        except KeyboardInterrupt:
            pass

        duration = time.time() - start
        print(f"\n{count} messages in {duration:.0f}s "
              f"({count / max(duration, 1):.1f}/s) -> {path}")


class _Replay:
    """Feeds recorded messages through the live parser."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as source:
            self.lines = [json.loads(line) for line in source if line.strip()]
        self.i = 0
        self.tick = 0

    def recv(self):
        while self.i < len(self.lines):
            msg = self.lines[self.i]
            self.i += 1
            if msg.get("kind") in ("manifest", "hello"):
                continue
            return msg
        raise StopIteration

    def send(self, **_):
        pass

    def manifest(self):
        for msg in self.lines:
            if msg.get("kind") == "manifest":
                return msg
        return {}


def verify(path):
    client = ObservationClient(bridge=_Replay(path))

    seen_reasons = set()
    seen_phases = set()
    lifecycles = {}
    orders_seen = 0
    satisfactions = 0
    tables_assigned = 0
    frames = 0
    previous_orders = {}

    try:
        while True:
            world = client.recv()
            frames += 1

            for group in world.groups:
                group_id = group["e"]
                reason = group.get("patience_reason_name")
                if reason:
                    seen_reasons.add(reason)
                    sequence = lifecycles.setdefault(group_id, [])
                    if not sequence or sequence[-1] != reason:
                        sequence.append(reason)

                phase = group.get("meal_phase_name")
                if phase:
                    seen_phases.add(phase)

                if group.get("table"):
                    tables_assigned += 1

                for order in group.get("orders", []):
                    key = (group_id, order["member"], order["iid"])
                    orders_seen += 1
                    was_satisfied = previous_orders.get(key)
                    if was_satisfied is False and order["satisfied"]:
                        satisfactions += 1
                    previous_orders[key] = order["satisfied"]
    except StopIteration:
        pass

    print(f"manifest: {json.dumps(client.b.manifest())}")
    print(f"frames:   {frames}")
    print(f"groups:   {len(lifecycles)}")
    print(f"orders:   {orders_seen} entries, {satisfactions} satisfied")
    print(f"tables:   {tables_assigned} frames with an assignment")
    print(f"reasons:  {sorted(seen_reasons)}")
    print(f"phases:   {sorted(seen_phases)}")

    problems = []

    required = {"seating", "thinking", "service", "wait_for_food", "eating"}
    missing = required - seen_reasons
    if missing:
        problems.append(f"patience reasons never seen: {sorted(missing)}")

    if "main" not in seen_phases:
        problems.append("MenuPhase.Main never seen")

    if satisfactions == 0:
        problems.append("no order ever transitioned unsatisfied -> satisfied")

    if tables_assigned == 0:
        problems.append("no group was ever assigned a table")

    # Orders must not become visible before the ordinary seating-to-order flow.
    for group_id, sequence in lifecycles.items():
        if "seating" in sequence and "wait_for_food" in sequence:
            if sequence.index("seating") > sequence.index("wait_for_food"):
                problems.append(
                    f"group {group_id}: wait_for_food preceded seating")

    if problems:
        print("\nFAIL")
        for problem in problems:
            print("  - " + problem)
        return 1

    print("\nOK -- obs_0.1 parses and the confirmed lifecycle is intact")
    return 0


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if not arguments:
        print(__doc__)
        sys.exit(1)
    if arguments[0] == "--verify":
        if len(arguments) != 2:
            print("usage: record.py --verify TRACE.jsonl")
            sys.exit(2)
        sys.exit(verify(arguments[1]))
    record(arguments[0])
