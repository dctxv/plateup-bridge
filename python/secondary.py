"""
Identify what SecondaryAction1 and SecondaryAction2 actually do.

Known from decompilation:
    GrabAction       == Pressed          -> InteractionType.Grab
    InteractAction   == Pressed or Held  -> InteractionType.Act
    SecondaryAction2 == Pressed          -> InteractionType.Notify
    SecondaryAction1                    -> StartDayWarningView ready consent

AttemptInteraction does not consume SecondaryAction1, but StartDayWarningView
does: it is Controls.Interact3 and toggles player consent during preparation.
This harness still probes its behavior in other contexts:

    python python/secondary.py

Run in practice mode on open floor with an ingredient provider nearby. The
script prompts when it needs empty hands or a held item.
"""

import json
import os

from bridge import PlateUpBridge, player


ITEM_NAMES = {}


def next_obs(bridge):
    while True:
        message = bridge.recv()
        if message.get("kind") == "dict":
            ITEM_NAMES.update(
                {int(key): value for key, value
                 in message.get("items", {}).items()})
            continue
        if message.get("kind") == "obs" and message.get("in_restaurant"):
            return message


def settle(bridge, ticks=20):
    observation = None
    for _ in range(ticks):
        bridge.idle()
        observation = next_obs(bridge)
    return observation


def item_name(item):
    if not item:
        return None
    item_id = item.get("iid")
    return ITEM_NAMES.get(item_id, f"item:{item_id}")


def snapshot(observation):
    """Fields that a throw, drop, ping, or stop action could plausibly change."""
    p = player(observation)
    held = p.get("held") if p else None
    loose = observation.get("loose_items", [])
    return {
        "held": item_name(held),
        "held_e": (held or {}).get("e"),
        "pos": (round(p["x"], 2), round(p["z"], 2)) if p else None,
        "loose": len(loose),
        "loose_names": sorted(item_name(item) or "?" for item in loose),
        "captured": (
            (p or {}).get("captured")
            or observation.get("input_captured", False)
        ),
    }


def diff(before, after):
    changes = []
    for key in before:
        if before[key] != after[key]:
            changes.append(f"    {key}: {before[key]!r} -> {after[key]!r}")
    return changes


def press(bridge, field, hold_ticks=1, move=(0.0, 0.0)):
    """Press one button for N observation ticks, release it, then settle."""
    kwargs = {"move": move, field: True}
    for _ in range(hold_ticks):
        bridge.send(**kwargs)
        next_obs(bridge)
    for _ in range(10):
        bridge.send(move=move)
        next_obs(bridge)
    return settle(bridge, 15)


def trial(bridge, name, field, hold_ticks, move, need_item):
    print(f"\n--- {name} ---")

    before = snapshot(settle(bridge))

    if need_item and not before["held"]:
        print("  SKIP: need to be holding an item. Grab something and re-run.")
        return None
    if not need_item and before["held"]:
        print("  SKIP: need empty hands. Put the item down and re-run.")
        return None

    print(f"  before: held={before['held']} loose={before['loose']}")
    after = snapshot(press(bridge, field, hold_ticks, move))
    print(f"  after:  held={after['held']} loose={after['loose']}")

    changes = diff(before, after)
    if changes:
        print("  CHANGED:")
        print("\n".join(changes))
    else:
        print("  no observable change")

    return {
        "name": name,
        "field": field,
        "hold": hold_ticks,
        "move": move,
        "before": before,
        "after": after,
        "changed": changes,
    }


def main():
    results = []

    with PlateUpBridge() as bridge:
        observation = next_obs(bridge)
        if not observation.get("override"):
            raise SystemExit("press F9 in game first")

        print("Stand on open floor. Each trial reports what changed.\n")
        print("=" * 60)
        print("PART 1 -- empty hands")
        print("=" * 60)
        input("\nEmpty your hands, then press Enter...")

        for name, field, hold in [
            ("SecondaryAction1 tap", "secondary1", 1),
            ("SecondaryAction1 hold", "secondary1", 40),
            ("SecondaryAction2 tap", "secondary2", 1),
            ("SecondaryAction2 hold", "secondary2", 40),
            ("StopMoving + move", "stop", 30),
        ]:
            move = (1.0, 0.0) if "StopMoving" in name else (0.0, 0.0)
            result = trial(
                bridge, name, field, hold, move, need_item=False)
            if result:
                results.append(result)

        print("\n" + "=" * 60)
        print("PART 2 -- holding an item")
        print("=" * 60)
        input("\nPick up an ingredient, then press Enter...")

        for name, field, hold, move in [
            ("SecondaryAction1 tap (held item)", "secondary1", 1, (0.0, 0.0)),
            ("SecondaryAction1 hold (held item)", "secondary1", 40, (0.0, 0.0)),
            ("SecondaryAction1 + move (held)", "secondary1", 20, (1.0, 0.0)),
            ("SecondaryAction2 tap (held item)", "secondary2", 1, (0.0, 0.0)),
            ("Grab tap facing empty floor", "grab", 1, (1.0, 0.0)),
        ]:
            result = trial(
                bridge, name, field, hold, move, need_item=True)
            if result:
                results.append(result)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for result in results:
        status = "CHANGED" if result["changed"] else "no effect"
        print(f"  {result['name']:<38} {status}")

    path = os.path.join(
        os.path.dirname(__file__), "..", "docs", "secondary-actions.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as output:
        json.dump(results, output, indent=2)
    print(f"\nraw -> {os.path.normpath(path)}")

    print("""
Interpretation notes:

- SecondaryAction1 is confirmed as Ready/Start consent during preparation. A
  lack of change on open floor means only that no active view consumes it there.
- If a held item disappears and appears in loose_items, that is a throw.
- If a held item disappears with no loose item, it entered a holder or was
  destroyed; inspect nearby appliance contents in the raw observation.
- Throwing may be a Grab gesture while facing empty floor rather than a
  dedicated button. The final trial tests that.
- SecondaryAction2 maps to InteractionType.Notify in AttemptInteraction, which
  is probably ping. Expect no persistent state change in solo.
""")


if __name__ == "__main__":
    main()
