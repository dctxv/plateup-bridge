# Learning pipeline: demonstrations to a motor policy

**Status:** implemented and measured **against the offline model**; the Phase G
gate is **not** met and no learned policy has run in PlateUp
**Pinned game:** PlateUp `1.4.3-FF8F`
**Schemas:** `obs_0.1` / `act_0.1` / `demo_0.1` / `encode_0.2` / `env_0.2` /
`dataset_0.1` / `policy_0.1` / `dagger_0.1` / `evaluate_0.1` /
`manifest_0.1`

The Phase G method-change decision this produced is in
[`phase-g-decision.md`](phase-g-decision.md).

Specification section 10.3 fixes the motor training order: clone per-axis
movement and button edges, goal-condition on the target, randomise starts,
collect on-policy failures, add DAgger corrections, fine-tune with RL, freeze a
checkpoint. Steps 1, 2 and 5 are implemented here and measured. Steps 3, 4 and
6 are not.

Everything below was measured against `python/mockgame.py`, a **model** of
PlateUp. A policy trained here has learned the model.

---

## 1. The pipeline

```text
runs/demos/*.jsonl        human demonstrations, demo_0.1
        |                 dataset.from_demonstration
        +--> dataset_0.1 --+
        |                  |
mockgame + reference       |     policy.ClonedPolicy      evaluate.rollout_*
controller ----------------+---> factored MLP, NumPy ---> metrics with CIs
        dataset.from_model |            ^
                           |            |
                     dagger.run --------+  aggregate on-policy states
```

- `python/dataset.py` builds aligned `(state, goal, action)` tuples from either
  source and stores them with a provenance manifest.
- `python/policy.py` is a one-hidden-layer MLP with one softmax head per action
  component, trained with Adam. NumPy only, no framework.
- `python/dagger.py` aggregates labels at the states the policy actually
  reaches.
- `python/evaluate.py` scores by playing, and reports the section 17.4 metric
  set with Wilson intervals.

## 2. The measured progression

Every row is 6 evaluation episodes on the recorded steak layout, greedy (no
exploration noise), against the offline model. The reference controller is the
scripted baseline, not autonomy.

| Stage | Encoding | Episodes | Held-out acc. | Served | Days |
|---|---|---:|---:|---:|---:|
| Random actions | - | - | - | 0 | 0/8 |
| Cloning, state only | `encode_0.1` | 12 | 0.972 | **0** | 0/6 |
| + goal conditioning | `encode_0.1` | 12 | 0.986 | 1 | 3/6 |
| + occupancy patch | `encode_0.2` | 14 | 0.989 | 0 | 0/6 |
| + per-head balancing | `encode_0.2` | 14 | 0.990 | 1 | 6/6 |
| + masking unused classes | `encode_0.2` | 14 | 0.990 | 1 | 8/8 |
| + randomised starts | `encode_0.2` | 20 | 0.863 | - | - |
| + more episodes | `encode_0.2` | 60 | **0.969** | **0** | 0/8 |
| Reference controller (scripted) | - | - | - | **4** | 8/8 |

Read this table carefully, because its main lesson is negative.

It is **not** a clean ablation. The encoding and the episode count both change
down the column, so no two adjacent rows isolate one variable. It records the
sequence actually taken, each step motivated by a diagnosed failure rather than
by a sweep.

And **accuracy and play move in opposite directions three separate times**:
rows 3 to 4 (class balancing), and rows 6 to 8, where randomised starts plus
three times the data raised held-out accuracy to 0.969 and dropped play from 1
served to 0. The last of those is the important one: it is the standard remedy
for on-policy drift, applied properly, and it made the validation number better
and the behaviour worse.

The honest reading is that **per-frame supervised accuracy is not predictive of
play in this task**, and that behaviour cloning on this formulation is not
converging toward competent movement with more data. That is what
[`phase-g-decision.md`](phase-g-decision.md) acts on.

No variant comes close to the scripted baseline. The best observed was 1 group
of 4, and the best-validated is 0. That is the honest state of Phase G.

## 3. Findings, each of which cost a rebuild

These are the reason the table above has several rows instead of one, and each
is a measurement rather than a design preference.

### 3.1 Per-frame accuracy is not a proxy for playing

The first clone reached **97.2%** held-out per-frame accuracy and served
**zero** groups across every seed. It picked up the meat, walked into an
appliance, and pushed against it for the remaining ninety seconds of the day.

A 3% per-frame error rate over roughly 2,700 frames does not stay at 3%: the
policy leaves the states the expert visits, and the dataset contains no frame
that says what to do from outside them. This is why `evaluate.py` exists and
why `policy.py` says so in its own docstring.

### 3.2 Cloning a hierarchical expert needs the goal

The reference controller's action depends on which appliance its planner chose,
and that choice is not in the observation. Two identical kitchens call for
opposite movements. Quantising the recorded states showed 4.5% of repeated
states carrying conflicting movement labels — enough to matter, and the
underlying problem is worse than the number suggests, because the ambiguity is
concentrated exactly at the decision points.

Specification section 8.1 already puts a goal-conditioned motor controller
under the task planner, and section 10.3 step 2 makes goal conditioning the
second thing to do. `encode.GoalEncoder` supplies the option kind, the target's
relative position, the planned stance and whether the target is in reach.

Nothing in it is privileged: the option is the agent's own decision and the
target's position is published. It is the agent telling itself what it chose.

### 3.3 A motor policy cannot route around what it cannot see

The state encoding described appliances by relative position but carried no map,
so the policy could know where the sink was and nothing about the counter
between them. `encode_0.2` adds an egocentric 7×7 occupancy patch read from
published appliance positions and layers, with out-of-bounds counted as blocked.

Specification section 6.2 lists the occupancy layer and traversable tiles as
part of the layout observation group, and section 6.1 forbids a computed
*legality* oracle rather than the map, so this is a fact and not an affordance.

### 3.4 Class balancing destroys a button

Inverse-frequency class weighting is the standard remedy for the neutral
movement class dominating the data, and on the movement heads it works. Applied
to a button it is a disaster.

Grab is pressed in 1.9% of frames. Inverse-frequency weighting multiplies those
by roughly 26, and the policy learns to buy recall with false positives. The
measured result: grab fired in **36%** of frames instead of 2%, which put the
chef in a loop taking a plate off the stack and putting it straight back for an
entire modelled day — at **99.0% balanced accuracy**.

`ClonedPolicy.balanced_heads` now covers the two movement axes only, and
`policy.py report` prints the fires-versus-should ratio per head, because that
is the number balanced accuracy hides. After the fix grab fires at 1.3% against
a true 1.9%, and interact at 10.4% against 10.3%.

### 3.5 A class with no evidence behind it can still win

`StopMoving` never appears in the reference controller's data: its label is
constant zero across all 32,004 frames. Cross-entropy pushes the unused logit
down but nothing pins it, and at out-of-distribution states it won anyway — the
policy pressed StopMoving in **18%** of on-policy frames, which disables walking
entirely. A self-inflicted stall caused by a class the data never justified.

`ClonedPolicy` now records which classes were observed during training and
masks the rest at inference. This is a statement about the training
distribution, recorded in the checkpoint manifest, not an affordance oracle over
gameplay legality. Fixing it moved full parity from 20% expert assistance to
10%.

### 3.6 Measure the halves before choosing what to fix

The on-policy mismatch table said the press was the problem: interaction frames
are 4% of the day and the policy got half of them wrong. That reading was
wrong.

`evaluate.py split` hands one half of the action to the policy and the other to
the option layer. Buttons learned with a scripted route serves **4 of 4** —
parity. Movement learned with scripted buttons serves **2**. The press head is
already good enough; the feet are not.

The mistake is worth keeping because it is easy to repeat: mismatch measured
on-policy is measured at states the policy has already drifted into, so the
press head was being blamed for where the movement head had put it. The split
is what separates a symptom from a cause, and it is two dozen lines.

### 3.7 A held-out split of identical episodes measures nothing

Every episode in the first datasets began from the same spot with empty hands
and cold hobs, so holding out whole episodes held out nothing: training and
validation were the same distribution and validation accuracy tracked training
accuracy to three decimal places. It looked like a policy that generalised.

Adding curriculum randomisation to the starting pose and held item
(`--randomise-start`, specification section 10.3 step 3) made the split
meaningful, and the same architecture that reported **0.978** validation
accuracy on move_x reported **0.17** once the held-out episodes genuinely
differed, against **0.99** on training. The generalisation gap had always been
there; the split had been hiding it.

The lesson is about the split, not the model: a held-out set that shares its
initial conditions with training is not a held-out set. Specification section
17.2 asks for separate training, validation, development and sealed evaluation
partitions, and this is what happens when the partitions differ only in name.

### 3.8 Never train a head that has nothing to learn

`StopMoving`, `Ready` and `MenuCancel` are constant across a service-phase
dataset. Cross-entropy on a two-class head with one observed class drives the
unused logit toward negative infinity forever, and that gradient flows back
through the shared trunk. Three such heads out of seven meant roughly three
sevenths of the trunk's gradient was spent on a boundary that does not exist.

Measured: movement accuracy collapsed from 0.978 to **0.179** — below chance on
the dominant class — until degenerate heads were excluded from the loss
entirely. They are masked at inference regardless, so nothing is lost by not
training them.

### 3.9 The standard remedy, applied properly, made it worse

Curriculum randomisation of the starting pose and held item is specification
section 10.3 step 3 and the textbook fix for on-policy drift. It was
implemented (`mockgame(randomise_start=True)`), the dataset was regenerated at
three times the size (60 episodes, 187,950 states), and the result was:

| | Held-out accuracy | Served |
|---|---:|---:|
| Fixed starts, 14 episodes | 0.990 | 1 |
| Randomised starts, 20 episodes | 0.863 | - |
| Randomised starts, 60 episodes | **0.969** | **0** |

The middle row is the honest-split effect from section 3.7; the third row shows
the gap closing again with more data. Generalisation improved. Play did not.

Three of these, in one project, is enough to stop treating supervised accuracy
as a proxy. The split diagnostic in section 3.6 says the press head is already
at parity, so what is left is arriving at a pose - which is a property of a
trajectory, not of a frame, and a per-frame likelihood objective has no way to
express it. That is the argument for RL fine-tuning rather than more data, and
it is the argument the decision document makes.

## 4. What is scripted and what is learned

In the goal-conditioned rollout (`evaluate.rollout_goal_policy`):

| Layer | Who |
|---|---|
| Which option to run, and when it has ended | scripted `SteakPlanner` |
| Every movement axis, every tick | **learned policy** |
| Every Grab, Interact, StopMoving | **learned policy** |
| Preparation consent | scripted, and stated |

This is the section 8.1 split with the top half not yet trained. Section 10.4
trains the task planner separately, in the surrogate, and until that is done
the correct description is **a learned motor controller under a scripted
planner** — not an autonomous agent. Section 2.1 requires every service task
choice to come from the agent as well before a run can be scored.

## 5. The human-demonstration path

`dataset.from_demonstration` reconstructs the same tuples from a `demo_0.1`
recording, which is the path specification section 10.1 actually asks for. On
`runs/demos/smoke.jsonl` it produces **681** aligned pairs with movement spread
across all five bins, grab pressed in 12.8% of steps and interact in 2%.

Alignment: native input arrives at render cadence and observations at
simulation cadence, so each observation takes the input frames that arrived
after the previous observation and at or before its own tick, averaging
movement and OR-ing buttons. Observations with no input in their interval are
**dropped**, not filled with neutral, because a fabricated do-nothing label is
worse than a missing one.

That recording is a real steak Day 1 in which the demonstrator never cooked, so
it validates the pipeline and is not enough to train on. Training from human
demonstrations needs the recordings the benchmark protocol asks for.

## 6. Reward hacking

`python/antihack.py` implements specification section 11.3 as ten adversaries.
Twelve checks close against the model; two are marked OPEN because they are
properties of the live bridge — Practice-only reset state and duplicate command
receipts.

The design tries to make the exploits structurally impossible rather than
merely unprofitable, because an exploit that is only unprofitable becomes
profitable when a weight changes:

- no proximity, approach or facing term exists, so camping accumulates nothing;
- order credit comes from `money`, which the game increments once per order, so
  an order cannot pay twice;
- a lost life is negative and early termination earns nothing, so a fast loss
  is never cheaper than a slow one;
- elapsed time carries a small cost, so stalling is never free;
- binning is never rewarded.

## 7. What would move the numbers

Ordered by the split diagnostic rather than by preference, and written up as
the section 12 method-change decision in
[`phase-g-decision.md`](phase-g-decision.md):

1. **Curriculum randomisation of starting pose and held item** (section 10.3
   step 3). Every trajectory began from the same spot with empty hands and cold
   hobs, so the policy had never seen the states its own movement error takes
   it to. Implemented as `mockgame.MockPlateUp(randomise_start=True)` and
   `dataset.py model --randomise-start`.
2. **RL fine-tuning for precision and recovery** (section 10.3 step 6).
   Cloning optimises per-frame likelihood; what is wanted is arriving at a
   pose, and only a return expresses that. Environment, reward and
   anti-hacking suite are all in place.
3. **A learned task planner** trained in the surrogate (section 10.4), which is
   what removes the remaining scripted half.
4. **Real demonstrations and a real capability registry.** Everything above is
   measured on a model whose steak timings are knowledge-base priors that have
   never been observed on an actual steak.

Explicitly **not** on the list: more DAgger, more epochs, or a larger network.
Six DAgger iterations over 125,000 aggregated states produced no improvement,
and specification section 12 says not to simply run longer.

## 8. Commands

```powershell
python python\dataset.py model runs\datasets\reference-goal.npz --episodes 14
python python\dataset.py demo runs\datasets\human.npz runs\demos\smoke.jsonl
python python\policy.py train runs\datasets\reference-goal.npz runs\policies\bc-goal.npz
python python\dagger.py runs\policies\bc-goal.npz runs\policies\dagger-goal.npz
python python\evaluate.py compare runs\policies\dagger-goal.npz --episodes 20
python python\antihack.py
```
