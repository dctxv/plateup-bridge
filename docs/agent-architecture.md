# Steak agent architecture

**Status:** implemented and passing the offline gate; **no live-game run yet**
**Pinned game:** PlateUp `1.4.3-FF8F`
**Bridge:** `0.3.0`
**Schemas:** `obs_0.1` / `act_0.1` / `demo_0.1` / `encode_0.2` /
`capability_0.1` / `env_0.2` / `dataset_0.1` / `policy_0.1` / `dagger_0.1` /
`evaluate_0.1` / `manifest_0.1`

This describes the layers between the bridge and a policy, what each one is
allowed to claim, and where the scripted parts stop and the learned parts have
to start.

---

## 1. The stack

```text
                              docs/steak-decision.md
                                       |
python/steak.py       recipe graph, doneness policy, name resolution
python/kitchen.py     geometry: reach, aim, occupancy, routes, roles
                                       |
python/options.py     options: navigate, acquire, place, operate, serve,
                      watch_cook, bin, start_day, and composites
                                       |
python/service.py     SteakPlanner: a priority list with pre-emption
                      Runner: drives one planner against one world source
                                       |
        +------------------------------+------------------------------+
        |                                                             |
python/mockgame.py                                          the live bridge
tick-level model of the game                                PlateUp + the mod
        |                                                             |
python/capability.py  option durations and failure rates, measured
python/surrogate.py   semi-MDP over options, calibrated from the registry
python/encode.py      fixed-size observation vector, and the goal encoding
python/env.py         Gymnasium-compatible environment, both backends
                                       |
python/dataset.py     (state, goal, action) tuples from demonstrations or the
                      model
python/policy.py      goal-conditioned cloned policy, NumPy only
python/dagger.py      labels at the states the policy actually reaches
python/evaluate.py    the specification's metric set, with intervals
python/antihack.py    the specification's reward-hacking adversaries
python/manifest.py    run manifests: code, schemas, build, artifact hashes
python/selftest.py    the offline gate over all of it
```

`Runner` and every option consume `obs_0.1` frames and emit `act_0.1` fields,
so they cannot tell the model from the game. That is the point: what runs
offline is what runs live.

## 2. What is scripted, and why that is allowed

`service.SteakPlanner` and the motor control inside `options.py` are
**scripted**. Specification section 2.3 disallows scripted cook-plate-serve
control and disallows presenting deterministic pathfinding as learned motor
control. Nothing produced by these may be reported as autonomous play.

Their three permitted jobs:

1. **Training-data construction.** Section 10.4 step 1 allows scripted
   scenario labels used only to build option traces to clone from.
2. **Capability measurement.** Section 8.3 requires option duration and
   failure distributions measured from the current controller, and section 9
   makes the surrogate consume them.
3. **A baseline.** Section 17.3 requires the learned system to be compared
   against something, and a plain priority list is a fairer opponent than a
   clever one, because a clever baseline is hard to beat for reasons that have
   nothing to do with learning.

Replacing them with a policy means replacing two things: `Option._drive` and
the press logic (the motor layer), and `SteakPlanner.choose` (the task layer).
Everything else — the recipe graph, the geometry, the option boundaries, the
registry, the environment — stays.

**The motor half is now done and measured.**
`evaluate.rollout_goal_policy` runs the scripted planner over a learned motor
policy: the planner chooses options and decides when they end, and every
movement axis and every button on every tick comes from the policy. It
completes the modelled day but serves one group where the baseline serves four,
so the Phase G gate is not met. The measured progression and the four findings
behind it are in [`learning-pipeline.md`](learning-pipeline.md). The task half
is still scripted; specification section 10.4 trains it in the surrogate.

### 2.1 What the baseline manages, on the model

`runs/benchmark/mock-sweep.txt`, regenerable and **not game evidence**:

| Configuration | Served | Lost | Ruined |
|---|---|---:|---:|
| Day 1 as recorded | 4 of 4 | 0 | 0 |
| Day 1, one plate | 4 of 4 | 0 | 0 |
| Day 1, lift at Well-done | 4 of 4 | 0 | 0 |
| Saturated, 10 groups every 9 s | 7 | 0 | 0 |
| Saturated, one plate | 6 | 0 | 0 |
| Saturated, standing at the hob | 6 | 0 | 0 |
| Overloaded, 12 groups every 5 s, one plate, Well-done | 3 | 1 | 0 |

Two things this measures. Working while a steak cooks beats standing at the
hob under saturation, which is why `SteakPlanner` defaults to it and
`--watch-hob` keeps the other variant available. And the overloaded row is a
plate-throughput limit rather than a stall: one plate serialises the whole
kitchen, so the chef genuinely has nothing to do while it is out on a table.

Three planner bugs were found by pushing these knobs, all of which would have
been near-invisible on a comfortable Day 1 and expensive to diagnose in the
live game:

- a cooked steak in hand with no clean plate and every counter full left the
  chef standing still forever, because `_stash` had no fallback;
- a clean plate in hand with every counter full made the planner aim at a
  plate stack that was already holding something, which never accepts, so the
  option failed and was immediately re-chosen — 158 times in one modelled day;
- counting only finished dishes as work-in-progress let the counters fill with
  cooked steaks that no plate would ever arrive for.

## 3. Geometry, and the one rule that shapes everything

`AttemptInteraction` projects an interaction point `InteractionOffset` (0.7)
ahead of the chef **along the movement vector**, and takes the nearest
interactive within `InteractionRadius` (0.7) of that point. Two consequences:

- movement and aim are the same channel, so every press has to be preceded by
  holding the right direction;
- a stance is only useful if the intended target is also the *nearest* thing to
  the projected point, which is what `Kitchen.aim_clearance` scores.

`Kitchen.approach_poses` enumerates the eight tiles around a target, takes the
closest point inside each that keeps `TILE_INSET` (0.25) clear of the tile
edges, rejects any stance beyond `PLAN_REACH` (1.10) or without a positive aim
clearance, and `poses_by_route` then orders what survives by real route length
so an unreachable pocket is not recommended.

Both constants are calibrated against recorded human behaviour: the three
deliveries in `runs/golden` stood 0.88, 0.91 and 1.02 units from the table, the
furthest of them 0.22 units inside its tile, and all three pass the aim model —
which the offline gate checks.

The occupancy model is `OccupancyLayer.Default` blocks and
`OccupancyLayer.Floor` does not, which puts mess, mop water, nameplates and the
practice trigger on the walkable side. Ghost chairs are treated as walkable as
a prior, and `Option._recover` demotes any tile the chef demonstrably fails to
enter, so a wrong entry costs one replan rather than a stall.

## 4. Options

An option runs for a variable number of ticks and ends in exactly one of
`success`, `failed`, `timeout`, `invalidated` or `preempted`. The distinction
that matters for the registry: **invalidated** means the planner asked for
something impossible (the target is gone, hands were already full), whereas
**failed** means the controller could not do a possible thing. Only the second
is a capability problem.

Buttons follow the game's own edge machine. Grab fires on `Pressed` only, so
`_press_grab` runs a press, a release and a settle window and counts attempts;
Interact acts on `Pressed` or `Held`, so `_hold_interact` holds it down.
`StopMoving` is held while aiming so a diagonal approach cannot slide along an
appliance, and after three failed presses the controller drops it and walks
into the target the way a human does.

## 5. Capability registry

`capability_0.1` buckets by `(option, target class, route-length band)` and
stores attempts, successes, a Wilson confidence interval, duration statistics,
press counts and failure reasons. Wilson rather than a normal approximation
because three successes must not report certainty.

A row is meaningless without the controller that produced it, so every registry
carries `controller`, `source` and `build`, and rows are never merged across
them. `lookup` widens the context until it finds a row and reports whether the
match was exact; the surrogate penalises an inexact match by counting it
against calibration support.

## 6. Semi-MDP surrogate

`surrogate.py` replaces continuous motion with sampled option outcomes.
Choosing an option costs one sampled duration, and every timer, patience bar
and cook stage advances by that amount. Duration comes from the registry's
mean and standard deviation; success is sampled against the registry's **lower**
confidence bound, so a plan validated on three samples does not outrank one
validated on thirty.

`surrogate.reference_policy` mirrors `SteakPlanner.choose` rule for rule, so a
surrogate-versus-model gap measures the abstraction rather than two different
policies.

One modelling trap worth recording: `options.WatchCook` includes the wait for
the steak to reach doneness, and that wait is already on the surrogate's own
clock. Pricing a surrogate lift from the `watch_cook` row would charge the
cooking time twice, so a lift is priced from the `acquire` row instead.

## 7. Environment

`env_0.2` exposes a Gymnasium-compatible API over either backend. Gymnasium
itself is optional: its spaces are used when installed and a compatible shim
stands in when not, so nothing here needs a dependency added before it can be
exercised.

Action space is specification section 7.1's baseline: per-axis movement
discretised to five values each, plus Grab, Interact, StopMoving, Ready and
MenuCancel as independent held bits. There is no drop or throw because the game
has none, and there is no MenuSelect on purpose: Cancel can only dismiss a
popup, whereas Select would confirm whatever it offers, which during
preparation can be a purchase or a card. Those are Project 3 scope, and an
interface that cannot express the choice cannot make it by accident.

Reward is bounded and event-based, per section 11: an order paid for earns, a
lost life and a ruined item cost, and elapsed time costs a little. There is
deliberately **no** proximity or approach shaping, because section 11.1
requires distance rewards to telescope and section 11.3 lists camping at a
target as an anti-hacking test. Order credit is taken from `money` rather than
from the satisfied flag, so an order cannot pay twice.

## 8. The offline model, and what it is not

`mockgame.py` is a tick-level model of the steak loop built from the two
recordings. Its measured inputs are listed in its module docstring: observation
cadence, top speed, turn rate, process rate, patience drain, lifecycle
durations, arrival cadence, and the layout itself, taken verbatim from a
recorded frame.

Its stated simplifications: customers walk straight to their seat and do not
collide with the chef; there is no mess, fire, dessert course or dish rack;
every group orders one main; appliance contents are one item deep.

**A pass against the model is not evidence about PlateUp.** It shows the agent
code is internally consistent and agrees with the recordings. Every claim
derived from it says so, in the module, in the ledger and here.

The model refuses a layout that provides another recipe's ingredients, so a
burger recording cannot be silently simulated as steak.

## 9. Running it

```powershell
python python\selftest.py                 # the whole offline gate
python python\facts.py                    # facts re-derived from recordings
python python\service.py mock --episodes 8
python python\env.py check
python python\env.py soak --steps 20000
python python\surrogate.py compare runs\capability\mock-reference.json
```

Live, once PlateUp is running with the mod and F9 is on:

```powershell
python python\service.py run --capability runs\capability\live.json
```

## 9A. Preparation

The first thing a live run meets is day 0, not service. `start_day_warnings` is
published exactly during preparation — 378 frames on day 0 in the golden trace,
123 in the smoke recording, and gone the instant day 1 begins — with
`players_not_ready` at Error until the chef consents and everything else at
Safe.

Two details that would each have cost a live session to find:

- **Consent toggles on the `Pressed` edge.** Holding the button is one toggle;
  releasing and pressing again turns consent back off. `StartDay` releases once
  `players_ready` reports true rather than continuing to hold.
- **The day will not start under an open popup.** `popups_open` goes to Error
  exactly while `input_captured` is true, so `DismissPopup` clears it first —
  with `MenuCancel` only. Cancel can dismiss; Select would confirm.

The other warnings are read and reported but not acted on. Rearranging the
restaurant is Project 2 and choosing from a popup is Project 3, and a
controller that improvises outside its remit is worse than one that stops and
says what it found.

## 10. What has to happen before any of this is a result

1. A live run of `service.py run` inside Practice, with the capability registry
   written from real trials rather than from the model.
2. Comparison of the real registry against the model's, which is the first
   honest measurement of how wrong the model is.
3. Re-running the surrogate against the real registry, which is what
   specification section 9.4 actually asks for.
4. The 100,000-command soak, still FAIL/PENDING after one 600-frame position
   freeze, before any unattended run. Two of the section 11.3 reward-hacking
   checks are also live-only and are marked OPEN rather than passing.

Until step 1, the correct description of this work is: **built, internally
consistent, and unverified in the game.**
