# Recipe benchmark protocol

**Status:** protocol declared and analyzer validated; no benchmark recordings taken
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
| 2 | **Interactions per completed meal** | Segmented interaction events (§4.4) that produced an observable change, divided by completed orders. | lower |
| 3 | **Process seconds per completed meal** | Item-seconds spent undergoing any process, divided by completed orders. | lower |

Ordering rationale: a chain a *human* cannot execute reliably will be worse for a
policy, so reliability outranks the rest. Interaction count outranks process time
because it is the motor and planner burden directly, whereas process time is
mostly unattended waiting that a policy can overlap with other work.

Metric 3 counts concurrent processes separately. Running two hobs at once is
demonstrator skill; the metric is meant to price the recipe, not the player.

Throughput is deliberately **not** a decisive metric. Raw meals per minute is not
comparable across arms when customer load may differ by design — that is what the
+30% claim asserts.

### 4.1.1 Why metric 3 is not a demand-pressure measure

An earlier draft of this protocol used **service slack**, the patience remaining
when a group is first served. Measurement against the existing artifacts killed
it, and the replacement was chosen from data rather than argument:

| Candidate | Measured on `runs/golden/obs_0.1_day1.jsonl` | Verdict |
|---|---|---|
| Patience at first delivery | 0.996, 0.997, 0.998 | No dynamic range. |
| Minimum patience per group | 0.977, 0.981, 0.998, 0.998 | No dynamic range. |
| Order latency | 0.3 s, 0.6 s, 0.7 s | Measures nothing; see below. |
| Process seconds per meal | 5.5 s | Usable. |

Patience barely moves on Day 1 because Day 1 is not demanding and patience resets
on every phase change, so any patience-derived metric saturates near 1.0 for both
arms. Order latency fails for a different reason: with a **single-dish menu**
every customer orders the same thing, so a competent demonstrator pre-plates and
delivers the instant the order appears. Latency then measures pre-plating, not
production.

The consequence is worth stating plainly: **Day 1 does not stress service
capacity**, so this benchmark cannot compare the two recipes on demand pressure.
It compares them on the intrinsic cost of the production chain instead. If the
recipe decision later needs a demand-pressure comparison, it needs a harder day
than Day 1 and a new protocol.

### 4.2 Reported, not decisive

Reported in the ledger for every session, but not used to pick the winner:

- groups per day and group-size distribution — **this is the +30% expected-group
  test**; report observed values for both arms with the wiki claim alongside;
- orders per day and meals completed per service minute;
- money at end of day and lives remaining;
- burn / wrong-doneness events specifically, separated from other failures;
- served-doneness distribution, read from the plated dish's component items;
- rejected-layout count and discarded-session count;
- service duration and total recording wall time;
- the saturating diagnostics from §4.1.1 (patience slack, minimum patience, and
  order latency), retained so a later day-2+ protocol can confirm they start
  discriminating once the day is genuinely demanding.

`is_bad` is **not** counted as a failure. The observation schema records it as a
lookahead flag that becomes true on Well-done steak, which is still servable.
Counting it would have handed the benchmark to burgers automatically. It is
reported as an at-risk count instead.

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

The window is set to 12 ticks, two observation intervals. Widening it changes
nothing: on `runs/demos/smoke.jsonl` the classification is identical at 6, 12,
24, 60, and 180 ticks. The null interactions in that recording are genuine
misfires — presses with nothing in reach — not a pairing artefact. The null rate
must still be reported per session, because a recipe whose interactions are
harder to aim will show it here.

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

Run with:

```powershell
python python\demo_analyze.py validate
```

| Check | Artifact | Requirement |
|---|---|---|
| Group, order, and satisfaction counts | `runs/golden/obs_0.1_day1.jsonl` | Matches ledger §2.3 exactly: 4 groups, 308 order entries, 3 satisfaction transitions. |
| Recipe derivation | `runs/golden/obs_0.1_day1.jsonl` | Derives `burger` from ordered item IDs. |
| Demo-free file | `runs/golden/obs_0.1_day1.jsonl` | Observation metrics computed; interaction metrics reported unavailable, **not** zero. |
| Provenance mismatch | `runs/demos/smoke.jsonl` | Declared `smoke`, derived `steak`; the mismatch rejects the session. |
| Incomplete day | `runs/demos/smoke.jsonl` | Rejected, with the point in the day the recording stopped. |
| Segmentation | `runs/demos/smoke.jsonl` | Interaction events found; null rate reported. |

The golden-trace counts are the load-bearing check: they are independently
recorded in the ledger, so a mismatch means the analyzer is wrong rather than the
trace.

Two of these checks were corrected by the data rather than written from
expectation, and both corrections are worth keeping visible:

- The smoke session was assumed to have no derivable recipe. It is in fact a
  **steak** Day 1, recorded with `--recipe smoke`. That makes it a live proof
  that the §4.5 provenance cross-check fires, which is stronger than the check
  originally specified.
- The golden trace was assumed to be a complete day. It stops at 94.6 s of a
  100 s day, so it is correctly rejected as a benchmark session. It remains
  valid as a schema-regression artifact, which is all the ledger ever claimed
  for it.

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

Confirm the analyzer still reproduces the ledger's recorded counts before a
benchmark run, and after any change to it:

```powershell
python python\demo_analyze.py validate
```

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
- **The two arms fail asymmetrically.** Steak has named doneness states
  (`Steak - Rare / Medium / Well-done / Burned`) but the item dictionary has no
  burger-specific burned variant: an overcooked patty becomes the generic
  `Burned Food`. Failure counting matches on the word "burned" so both arms are
  counted the same way, but §10.5's "wrong-doneness rate" is only separable for
  steak. For burgers there is no servable-but-suboptimal state at all, which is
  itself part of what this benchmark is measuring.
- Day 1 does not stress service capacity (§4.1.1), so this protocol cannot
  compare the recipes under load.
- Interaction attribution assumes a solo restaurant. `demo_input.player` is a
  native device source ID while `obs.players[].id` is `CPlayer.ID`, so changes
  are attributed to the single observed player. A two-player recording would
  need that mapping resolved first.
