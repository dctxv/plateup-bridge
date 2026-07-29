r"""
Run manifests: what produced a result, in one file.

    python python/manifest.py runs/manifests/offline-gate.json \
        --artifact runs/selftest/offline-gate.json \
        --artifact runs/policies/bc-goal.npz
    python python/manifest.py --check runs/manifests/offline-gate.json

Specification section 1.1 lists what has to be recorded for every campaign and
section 24.2 requires a reproducible evidence bundle. This writes that bundle:
code identity, dependency versions, every schema version in play, the pinned
build the recordings came from, and a SHA-256 for each artifact named.

`--check` re-hashes the artifacts and reports anything that has moved since,
which is the only way to tell a stale number in the ledger from a current one.

What it deliberately does **not** do is decide whether a result is valid. It
records what was true when the result was produced. A manifest whose code was
dirty is still written, and says so.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

VERSION = "manifest_0.1"

# Every versioned contract in the project. A result that cannot say which of
# these it was produced under cannot be compared with another one.
SCHEMA_MODULES = (
    ("obs_schema", None, "obs_0.1"),
    ("act_schema", None, "act_0.1"),
    ("demo_schema", None, "demo_0.1"),
    ("encode_schema", "encode", "VERSION"),
    ("capability_schema", "capability", "VERSION"),
    ("env_schema", "env", "VERSION"),
    ("dataset_schema", "dataset", "VERSION"),
    ("policy_schema", "policy", "VERSION"),
    ("evaluate_schema", "evaluate", "VERSION"),
    ("manifest_schema", None, VERSION),
)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _git(*arguments):
    try:
        return subprocess.check_output(
            ("git",) + arguments, stderr=subprocess.DEVNULL,
            text=True).strip()
    except Exception:
        return None


def code_identity():
    dirty = _git("status", "--porcelain")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty),
        "dirty_files": (
            sorted(line[3:] for line in dirty.splitlines()) if dirty else []),
    }


def schema_versions():
    versions = {}
    for name, module_name, attribute in SCHEMA_MODULES:
        if module_name is None:
            versions[name] = attribute
            continue
        try:
            module = __import__(module_name)
            versions[name] = getattr(module, attribute)
        except Exception as exc:  # pragma: no cover - import-time only
            versions[name] = f"unavailable: {exc}"
    return versions


def dependencies():
    record = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    for name in ("numpy", "gymnasium", "win32file"):
        try:
            module = __import__(name)
            record[name] = getattr(module, "__version__", "present")
        except ImportError:
            record[name] = None
    return record


def pinned_build(recording):
    """Build identity, taken from a recording's handshake rather than typed."""
    if not recording or not os.path.exists(recording):
        return None
    with open(recording, encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            if message.get("kind") == "hello":
                return {
                    "source": os.path.normpath(recording),
                    "game_version": message.get("game_version"),
                    "unity": message.get("unity"),
                    "bridge_version": message.get("bridge_version"),
                    "mod_hash": message.get("mod_hash"),
                    "protocol": message.get("protocol"),
                }
    return None


def build(artifacts=(), recording=None, note=None, scenario=None):
    entries = []
    for path in artifacts:
        if not os.path.exists(path):
            entries.append({
                "path": os.path.normpath(path), "missing": True})
            continue
        entries.append({
            "path": os.path.normpath(path),
            "bytes": os.path.getsize(path),
            "sha256": sha256(path),
        })
    return {
        "schema": VERSION,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        "scenario": scenario,
        "code": code_identity(),
        "schemas": schema_versions(),
        "dependencies": dependencies(),
        "pinned_build": pinned_build(recording),
        "artifacts": entries,
        "evidence_class": (
            "offline: produced against mockgame and recorded artifacts, not "
            "the live game"),
    }


def check(path):
    with open(path, encoding="utf-8") as source:
        payload = json.load(source)
    if payload.get("schema") != VERSION:
        raise ValueError(
            f"{path}: manifest schema {payload.get('schema')!r} != {VERSION!r}")

    results = []
    for entry in payload.get("artifacts", ()):
        target = entry["path"]
        if not os.path.exists(target):
            results.append((target, "MISSING", entry.get("sha256", "")))
            continue
        current = sha256(target)
        if entry.get("missing"):
            results.append((target, "APPEARED", current))
        elif current != entry.get("sha256"):
            results.append((target, "CHANGED", current))
        else:
            results.append((target, "MATCH", current))
    return payload, results


def describe(payload):
    code = payload["code"]
    lines = [
        f"{payload['schema']}  written {payload['written_at']}",
        f"  commit    {code['commit']} on {code['branch']}"
        + ("  (working tree dirty)" if code["dirty"] else ""),
    ]
    if payload.get("scenario"):
        lines.append(f"  scenario  {payload['scenario']}")
    if payload.get("note"):
        lines.append(f"  note      {payload['note']}")
    build_info = payload.get("pinned_build")
    if build_info:
        lines.append(
            f"  game      {build_info['game_version']} / unity "
            f"{build_info['unity']} / bridge {build_info['bridge_version']}")
        lines.append(f"  mod       {build_info['mod_hash']}")
    lines.append("  schemas   " + ", ".join(
        f"{key}={value}" for key, value in
        sorted(payload["schemas"].items())))
    lines.append("  deps      " + ", ".join(
        f"{key}={value}" for key, value in
        sorted(payload["dependencies"].items())))
    lines.append(f"  {payload['evidence_class']}")
    lines.append("  artifacts:")
    for entry in payload["artifacts"]:
        if entry.get("missing"):
            lines.append(f"    MISSING  {entry['path']}")
        else:
            lines.append(
                f"    {entry['sha256'][:16]}  {entry['bytes']:>10}  "
                f"{entry['path']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--recording", default=os.path.join(
        "runs", "demos", "smoke.jsonl"))
    parser.add_argument("--note")
    parser.add_argument("--scenario")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        payload, results = check(args.path)
        print(describe(payload))
        print()
        drifted = 0
        for target, status, digest in results:
            if status != "MATCH":
                drifted += 1
            print(f"  {status:<9} {target}  {digest[:16]}")
        print()
        if drifted:
            print(f"FAIL: {drifted} of {len(results)} artifacts have moved "
                  "since this manifest was written")
            return 1
        print(f"OK -- all {len(results)} artifacts match the manifest")
        return 0

    payload = build(
        artifacts=args.artifact, recording=args.recording, note=args.note,
        scenario=args.scenario)
    os.makedirs(os.path.dirname(args.path) or ".", exist_ok=True)
    with open(args.path, "w", encoding="utf-8") as output:
        json.dump(payload, output, indent=2, sort_keys=True)
    print(describe(payload))
    print("\nwrote " + os.path.normpath(args.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
