# Recipe benchmark protocol

**Status:** protocol declared, no recordings taken
**Pinned game:** PlateUp `1.4.3-FF8F`
**Bridge:** `0.3.0`
**Protocol / schemas:** `1` / `obs_0.1` / `act_0.1` / `demo_0.1`

This document fixes the procedure, the sample size, the metrics, and the
decision rule for the burger-versus-steak benchmark required by
[`plateup_specification.md`](plateup_specification.md) §10.5, **before** any
demonstration is recorded. It exists so the recipe choice is a measurement and
not a post-hoc reading of whichever numbers happened to look favourable.

Nothing in this file is a result. Results are logged in
[`verified-successes.md`](verified-successes.md).

---

## 1. Why this is gated

Specification §10.5 forbids locking the recipe by argument alone. The two
candidates fail in different ways:

- **Burger** has the shorter preparation chain, but the supplied mechanics
  reference reports a **+30% expected-group modifier**. That number is
  knowledge-base derived and therefore a hypothesis under §1.2's evidence
  hierarchy. This benchmark measures it rather than assuming it.
- **Steak** carries no reported group increase but adds a multi-stage doneness
  chain (`Meat → Rare → Medium → Well-done → Burned`) in which `is_bad` becomes
  true while the item is still servable. The failure mode is a timing decision,
  not a missing step.

The choice constrains Phase E's observation encoding, Phase G's motor goals, and
Phase H's success definition, so it must be closed before the Gymnasium wrapper
is designed.

## 2. Ordering note against the phase list

Specification §19 places interaction segmentation under **Phase F**, but the
recipe decision is a prerequisite for **Phase E**. The benchmark therefore pulls
the segmentation half of Phase F forward. This is deliberate and is recorded
here so the phase list is not silently violated.

What is pulled forward is the *offline analyzer only*: segmentation of recorded
demonstrations into interaction events, and the metrics below. Auto-labelling of
goals, DAgger correction, and surrogate calibration remain Phase F work and are
**not** required to close this gate.

---

## 3. Matched conditions

Both arms must differ only in the recipe. Every condition below is mandatory;
a recording that violates one is discarded, not adjusted.

| Condition | Requirement |
|---|---|
| Branch | Steam public stable, PlateUp `1.4.3-FF8F`. |
| Bridge | One bridge version for the whole benchmark. Record its `mod_hash`. |
| Players | Solo restaurant. **One** human demonstrator across all sessions. |
| Day | Day 1 service only. No later days, no franchise, no garage items. |
| Cards | No cards beyond the fixed Day 1 starting set. |
| Layout | Accepted under §3.1 below. |
| Override | F9 off for the entire recording. |
| Focus | PlateUp focused for the entire recording. |
| Speed | `game_speed == 1` throughout. F5/F6/F7 must not be pressed. |
| Pause | No deliberate pause during service. |
| Coverage | Recorder started during preparation and stopped after end of day. |

### 3.1 Layout acceptance

PlateUp generates the restaurant, so layouts cannot be made identical. They are
instead constrained to the same scale and rejected otherwise:

- exactly **one** table set;
- table `chairs` count equal across every accepted session;
- the appliance multiset required by the recipe present and reachable;
- no automation appliance (conveyor, grabber, or similar);
- no appliance that removes a required step for one recipe only.

The accepted table size is fixed by the **first** accepted session and every
later session must match it. Record the chosen value in the ledger entry.

Regenerating the restaurant until a layout is accepted is permitted and expected.
The count of rejected layouts is reported, because a recipe that is hard to get a
legal layout for is itself a finding.

### 3.2 Session interleaving

Sessions alternate `burger, steak, burger, steak, …`. The demonstrator improves
with practice and tires within a sitting; alternating spreads both effects across
arms instead of confounding one of them. The arm that goes first is chosen once,
before recording, and stated in the ledger entry.

### 3.3 Sample size

- **Minimum:** 6 accepted sessions per recipe.
- **Target:** 8 accepted sessions per recipe.

Below 6 accepted sessions per arm the benchmark is a quick sample and must not be
recorded as a formal gate. Discarded sessions are counted and reported; they are
not silently replaced.

This sample is small on purpose. The decision it supports is explicitly revisable
under §7, so the cost of being wrong is a re-run, not a dead project.

---

## 4. Metrics

All metrics are computed by the offline analyzer from the recorded file. None are
entered by hand.

### 4.1 Decisive metrics, in lexicographic order

The decision uses these three **in order**. Metric 2 is consulted only if metric
1 is a tie under §5, and metric 3 only if both 1 and 2 tie. Lexicographic order
is used instead of a weighted composite because weights chosen after seeing the
data are indistinguishable from a preference.

| # | Metric | Definition | Easier means |
|---:|---|---|---|
| 1 | **Demonstration failure rate** | Ruined-item events plus orders never satisfied before the group departed, divided by attempted meals. | lower |
| 2 | **Interactions per completed meal** | Segmented interaction events (§4.4) attributed to a completed order, divided by completed orders. | lower |
| 3 | **Service slack** | Median `patience_frac` remaining at each group's first delivery. | higher |

Ordering rationale: a chain a *human* cannot execute reliably will be worse for a
policy, so reliability outranks length; length outranks slack because it drives
both motor and planner difficulty, while slack is partly a property of the
generated demand.

Throughput is deliberately **not** a top-level decisive metric. Raw meals per
minute is not comparable across arms when customer load may differ by design —
that is what the +30% claim asserts. Service slack measures the same pressure
after demand is accounted for.

### 4.2 Reported, not decisive

Reported in the ledger for every session, but not used to pick the winner:

- groups per day and group-size distribution — **this is the +30% expected-group
  test**; report observed values for both arms with the wiki claim alongside;
- orders per day and meals completed per service minute;
- money at end of day and lives remaining;
- burn / wrong-doneness events specifically, separated from other failures;
- rejected-layout count and discarded-session count;
- service duration and total recording wall time.

### 4.3 Excluded

**Early policy learning curve** (§10.5's last criterion) is excluded from the
initial decision. It cannot be measured before a Gymnasium environment exists,
and the environment design depends on the recipe choice, so including it would
make the gate circular. It is demoted to a §7 revisit trigger.

### 4.4 Interaction events

An interaction event is a `Pressed` edge on `grab` or `interact` in the
`demo_input` stream, paired with the observation change it caused. The analyzer
pairs an edge with the nearest following observation delta within a bounded tick
window and classifies it. Edges that produce no observable change are retained as
`null_interaction` — a human misfire is real difficulty signal and must not be
filtered out.

The pairing window, the classification set, and the measured null rate are
defined by the analyzer and must be validated under §6 before any benchmark
recording is analyzed.

### 4.5 Recipe provenance

`--recipe` is a command-line string and is therefore not evidence. The analyzer
independently derives the recipe from the item IDs appearing in
`groups[].orders[].iid`, resolved through `dict.items`, and compares that against
`manifest.metadata.recipe`.

A mismatch **rejects the recording**. Canonical tokens are `burger` and `steak`.

---

## 5. Decision rule

Declared before recording:

1. Compute each decisive metric per session, giving one value per session.
2. For metric *n* in order, recipe A beats recipe B when **both** hold:
   - the difference in medians is at least **15%** of the larger median; and
   - the two arms' interquartile ranges across sessions do **not** overlap.
3. The first metric that produces a winner decides. Later metrics are not
   consulted.
4. If no decisive metric produces a winner, the benchmark result is
   **INCONCLUSIVE** and the tiebreak in §5.1 applies.

Both conditions are required because with six to eight sessions per arm a median
gap alone is easy to produce by chance; requiring separated interquartile ranges
is a crude but honest guard that does not pretend to a significance test the
sample cannot support.

### 5.1 Tiebreak

On INCONCLUSIVE, select **burger**, on the stated ground that the shorter
preparation chain carries lower Phase G and Phase H risk.

The ledger entry must then state plainly that the choice was made on the
tiebreak and **not** on measurement. A tiebreak selection is a weaker result than
a measured one and lowers the bar for the §7 revisit.

---

## 6. Analyzer validation

The analyzer must be validated before it is trusted to decide anything. It is
validated against artifacts that already exist, so this requires no game time.

| Check | Artifact | Requirement |
|---|---|---|
| Parses a real demo recording | `runs/demos/smoke.jsonl` | No crash; reports frame counts matching `demo_record.py verify`. |
| Parses a real full day | `runs/golden/obs_0.1_day1.jsonl` | Order and group counts match §2.3 of the ledger: 4 groups, 308 order entries, 3 satisfaction transitions. |
| Handles a demo-free file | `runs/golden/obs_0.1_day1.jsonl` | Observation metrics computed; interaction metrics reported as unavailable, not zero. |
| Rejects the smoke recording | `runs/demos/smoke.jsonl` | Rejected as a benchmark session: `--recipe smoke`, no derivable recipe, no completed day. |
| Segmentation sanity | `runs/demos/smoke.jsonl` | Interaction events found; null rate reported and stated in the ledger. |

The golden-trace numbers are the load-bearing check: they are independently
recorded in the ledger, so a mismatch means the analyzer is wrong rather than the
trace.

Passing these checks is logged as its own ledger entry, separate from the
benchmark result.

---

## 7. Revisit triggers

The recipe choice is a **revisable capability decision**, not a frozen constant.
It is re-opened when any of the following occurs:

- the choice was made on the §5.1 tiebreak, and Phase G or Phase H evidence
  favours the other recipe;
- early policy learning curves (§4.3) contradict the demonstration measurement;
- the observed expected-group behaviour contradicts the +30% claim strongly
  enough to change the §5 outcome;
- the pinned build changes.

A revisit produces a new ledger entry. The original entry is retained.

---

## 8. Procedure

```powershell
# Preparation, per session. Restaurant regenerated until §3.1 accepts it.
python python\demo_record.py record runs\demos\burger\day1-01.jsonl --recipe burger --scenario day1
python python\demo_record.py record runs\demos\steak\day1-01.jsonl  --recipe steak  --scenario day1
```

Each recording is verified for transport integrity, then analyzed:

```powershell
python python\demo_record.py verify runs\demos\burger\day1-01.jsonl
python python\demo_analyze.py session runs\demos\burger\day1-01.jsonl
```

The benchmark is decided in one pass over both arms:

```powershell
python python\demo_analyze.py benchmark runs\demos\burger runs\demos\steak
```

The benchmark command applies §5 exactly as written and reports the winner, the
deciding metric, or INCONCLUSIVE. It must not accept a threshold or weighting
argument — the rule is fixed by this document, not by the invocation.

---

## 9. Known limitations

- Layouts are matched by scale, not made identical. Residual layout variance is
  absorbed by the sample rather than eliminated.
- One demonstrator means the result carries that person's skill profile. It is a
  relative comparison between recipes, not an absolute human baseline.
- Discarding an item cannot be reliably attributed from observations alone;
  an item leaving the world has several causes. Failure counting therefore leans
  on ruined-item states and unsatisfied departed orders, which undercounts
  deliberate discards.
- Six to eight sessions per arm cannot support a significance claim. §5 states a
  margin rule rather than a *p*-value on purpose.
- `on_fire` has never been observed (`observation-schema.md` known gaps), so
  fire is out of scope for the failure metric.
