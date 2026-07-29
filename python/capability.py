r"""
Capability registry: what the current controller can actually do, measured.

Specification section 8.3 makes this the explicit sim-to-real interface. The
surrogate samples option durations and failure rates from here rather than
inventing them, and the preparation and strategy layers use it to reject plans
the current controller cannot execute. A registry row is only meaningful
alongside the controller that produced it, so every row carries the controller
identity and the build it ran against, and rows are never merged across them.

Contexts are coarse on purpose. Splitting by exact geometry would give one
sample per bucket and a confidence interval as wide as the prior, so an option
is bucketed by its name, its target class, and a route-length band.
"""

import json
import math
import os
import statistics
import time

VERSION = "capability_0.1"

# Route-length bands, in tiles. Chosen so a starting-layout kitchen produces
# three populated buckets rather than one crowded one and two empty ones.
DISTANCE_BANDS = ((0, 2), (2, 5), (5, 9), (9, 10 ** 6))


def band_of(tiles):
    if tiles is None:
        return "unknown"
    for low, high in DISTANCE_BANDS:
        if low <= tiles < high:
            return f"{low}-{high}" if high < 10 ** 6 else f"{low}+"
    return "unknown"


def wilson_interval(successes, trials, z=1.96):
    """Binomial confidence interval that behaves at small n.

    A normal approximation gives [1.0, 1.0] after three successes, which would
    tell the planner an option never fails. Wilson does not.
    """
    if trials <= 0:
        return 0.0, 1.0
    phat = successes / trials
    denominator = 1 + z * z / trials
    centre = phat + z * z / (2 * trials)
    spread = z * math.sqrt(
        (phat * (1 - phat) + z * z / (4 * trials)) / trials)
    return (max(0.0, (centre - spread) / denominator),
            min(1.0, (centre + spread) / denominator))


class Registry:
    def __init__(self, controller="reference_v1", build=None, source="unknown"):
        self.controller = controller
        self.build = build or {}
        self.source = source
        self.rows = {}

    # -- recording --------------------------------------------------------

    def record(self, option, seconds, route_tiles=None, target=None,
               status=None, presses=0, replans=0):
        key = (
            option,
            target or "any",
            band_of(route_tiles),
        )
        row = self.rows.setdefault(key, {
            "option": key[0],
            "target": key[1],
            "distance_band": key[2],
            "attempts": 0,
            "successes": 0,
            "durations": [],
            "failure_reasons": {},
            "presses": [],
            "replans": [],
        })
        row["attempts"] += 1
        if status == "success":
            row["successes"] += 1
            if seconds is not None:
                row["durations"].append(round(seconds, 3))
        else:
            reasons = row["failure_reasons"]
            reasons[status or "unknown"] = reasons.get(status or "unknown", 0) + 1
        row["presses"].append(presses)
        row["replans"].append(replans)

    def record_option(self, option, ctx=None, route_tiles=None, target=None):
        """Convenience for the runner: read the fields off a finished option."""
        summary = option.summary(ctx)
        self.record(
            option=summary["option"],
            seconds=summary.get("seconds"),
            route_tiles=route_tiles,
            target=target,
            status=summary["status"],
            presses=summary.get("presses", 0),
            replans=summary.get("replans", 0),
        )
        return summary

    # -- querying ---------------------------------------------------------

    def lookup(self, option, target="any", route_tiles=None):
        """Best matching row, widening the context until something is found.

        An unmatched context is reported, not silently replaced by a global
        average: specification section 9.3 requires the surrogate to know when
        a transition is outside its calibration support.
        """
        for key in (
            (option, target or "any", band_of(route_tiles)),
            (option, target or "any", "any"),
            (option, "any", band_of(route_tiles)),
            (option, "any", "any"),
        ):
            row = self.rows.get(key)
            if row and row["attempts"]:
                return self.summarise(row), key == (
                    option, target or "any", band_of(route_tiles))
        return None, False

    def summarise(self, row):
        durations = row["durations"]
        low, high = wilson_interval(row["successes"], row["attempts"])
        return {
            "option": row["option"],
            "target": row["target"],
            "distance_band": row["distance_band"],
            "attempts": row["attempts"],
            "successes": row["successes"],
            "success_rate": row["successes"] / row["attempts"],
            "success_low": low,
            "success_high": high,
            "median_seconds": (
                statistics.median(durations) if durations else None),
            "p90_seconds": (
                sorted(durations)[int(len(durations) * 0.9)]
                if durations else None),
            "mean_seconds": (
                statistics.fmean(durations) if durations else None),
            "stdev_seconds": (
                statistics.pstdev(durations) if len(durations) > 1 else 0.0),
            "mean_presses": (
                statistics.fmean(row["presses"]) if row["presses"] else 0.0),
            "mean_replans": (
                statistics.fmean(row["replans"]) if row["replans"] else 0.0),
            "failure_reasons": dict(row["failure_reasons"]),
        }

    def table(self):
        return [self.summarise(row) for row in self.rows.values()]

    # -- persistence ------------------------------------------------------

    def payload(self):
        return {
            "schema": VERSION,
            "controller": self.controller,
            "source": self.source,
            "build": self.build,
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rows": sorted(
                self.table(),
                key=lambda row: (row["option"], row["target"],
                                 row["distance_band"])),
        }

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as output:
            json.dump(self.payload(), output, indent=2, sort_keys=True)
        return os.path.normpath(path)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
        if payload.get("schema") != VERSION:
            raise ValueError(
                f"{path}: capability schema {payload.get('schema')!r} "
                f"!= {VERSION!r}")
        registry = cls(
            controller=payload.get("controller", "unknown"),
            build=payload.get("build", {}),
            source=payload.get("source", "unknown"))
        registry.summaries = {
            (row["option"], row["target"], row["distance_band"]): row
            for row in payload.get("rows", ())}
        return registry

    # -- reporting --------------------------------------------------------

    def report(self):
        lines = [
            f"capability registry {VERSION}",
            f"  controller {self.controller}   source {self.source}",
            "",
            f"  {'option':<14}{'target':<22}{'band':<7}{'n':>4}"
            f"{'ok':>7}{'lo':>7}{'med s':>8}{'p90 s':>8}",
        ]
        for row in sorted(
                self.table(),
                key=lambda row: (row["option"], row["target"],
                                 row["distance_band"])):
            median = row["median_seconds"]
            p90 = row["p90_seconds"]
            lines.append(
                f"  {row['option']:<14}{row['target'][:21]:<22}"
                f"{row['distance_band']:<7}{row['attempts']:>4}"
                f"{row['success_rate']:>7.2f}{row['success_low']:>7.2f}"
                f"{(f'{median:.2f}' if median is not None else '-'):>8}"
                f"{(f'{p90:.2f}' if p90 is not None else '-'):>8}")
            if row["failure_reasons"]:
                lines.append(f"        failures {row['failure_reasons']}")
        return "\n".join(lines)
