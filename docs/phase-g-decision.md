# Phase G method-change decision

**Status:** written decision, required by specification section 12
**Date:** 2026-07-30
**Gate:** Phase G, goal-conditioned motor controller
**Verdict:** **not met.** Stop revising the current method; the changes below
are what to do instead.

Specification section 12 is explicit: exceeding a stage budget "requires a
written method-change decision: alter representation, data, environment,
curriculum, algorithm, or scope. Do not simply run longer," and "after two
failed method revisions at one gate, reduce scope or redesign the interface
before continuing." Seven revisions have now been made at this gate, two of them after this
document was first written. This is that document, kept current.

Every measurement below is against `python/mockgame.py`, a model of PlateUp.

---

## 1. Where the gate stands

Eight evaluation episodes, greedy, on the recorded steak layout:

| Policy | Served | Lost | Ruined | Day completed | Idle |
|---|---:|---:|---:|---:|---:|
| Random | 0 | 1 | 0 | 0/8 | 0.001 |
| **Learned, goal-conditioned** | **1** | 1 | 0 | **8/8** | 0.512 |
| Reference (scripted) | 4 | 0 | 0 | 8/8 | 0.549 |

The policy is clearly above the floor and clearly below the baseline.

## 2. What was tried, and what each one bought

| Revision | Motivated by | Result |
|---|---|---|
| Goal conditioning (§10.3 step 2) | 4.5% of repeated states carried conflicting labels | 0 → 1 served |
| Egocentric occupancy patch | the policy could not see what blocked it | no direct gain; enabled the next finding |
| Per-head class balancing | grab fired in 36% of frames against a true 1.9% | 0 → 1 served, 0/6 → 6/6 days |
| Masking never-observed classes | StopMoving pressed in 18% of on-policy frames despite never appearing in the data | parity moved from 20% to 10% assistance |
| Excluding degenerate heads from the loss | three constant heads drove unused logits to -inf through the shared trunk | movement accuracy 0.179 -> 0.508 |
| DAgger, 6 iterations, 125k states (§10.3 step 5) | compounding covariate shift | **no improvement**; best checkpoint remained iteration 0 |
| Curriculum randomisation, 60 episodes (§10.3 step 3) | on-policy movement drift | accuracy 0.969, **served 1 -> 0** |

The DAgger result is the one that decides this document. Six iterations, four
rollouts each, an aggregate grown from 32k to 125k states, and every iteration
scored a median of 0 served against the seed policy's 1. Aggregating more
labels at the states the policy reaches is not what is missing.

## 3. The measurement that says what *is* missing

`python python\evaluate.py assist runs\policies\bc-goal.npz` takes a given
share of ticks from the scripted controller and the rest from the policy:

| Expert share | Served | Lost | Days completed |
|---:|---:|---:|---:|
| 0% | 1 | 1 | 3/3 |
| 5% | 3 | 1 | 3/3 |
| **10%** | **4** | **0** | 2/3 |
| 20% | 4 | 0 | 2/3 |
| 100% | 4 | 0 | 3/3 |

**One tick in ten reaches full parity.** The policy is not lost; it is failing
on a small, decisive minority of frames.

Which frames, measured on-policy over one modelled day:

| Situation | Frames | Grab mismatch | Movement mismatch |
|---|---:|---:|---:|
| Expert moving | 2,499 | 14.2% | 76.2% / 56.4% |
| Expert pressing a button | 101 | 49.5% | 48.5% / 70.3% |

The on-policy movement mismatch (76%) is twenty times the held-out mismatch
(2-4%), which is covariate shift measured directly rather than inferred.

## 4. The diagnosis, and the hypothesis it replaced

The table above suggested the press was the problem: the interaction frames are
4% of the day and the policy gets half of them wrong. That reading was wrong,
and the measurement that killed it is worth keeping.

`python python\evaluate.py split` hands one half of the action to the policy
and the other to the option layer:

| Split | Served | Lost | Days completed |
|---|---:|---:|---:|
| Movement learned, buttons scripted | 2 | 0 | 4/4 |
| **Buttons learned, movement scripted** | **4** | **0** | 4/4 |
| Both learned | 1 | 1 | 4/4 |
| Both scripted (reference) | 4 | 0 | 4/4 |

**The learned button policy already reaches parity.** Give it the buttons and a
scripted route and it serves 4 of 4, exactly like the baseline. Give it
movement and scripted buttons and it serves 2. The gap is **movement**, not the
press.

The earlier reading confused a symptom with a cause. High grab mismatch at
interaction frames is measured at states the policy has *already drifted into*:
if the chef is standing in the wrong place, the correct press is different, and
the press head is being blamed for the feet. Measuring the halves separately is
what separates them, and it is worth doing before choosing what to change --
which is the entire point of specification section 12 asking for a written
decision rather than another training run.

## 5. The decision

Do **not** continue with more DAgger iterations, more epochs, or a larger MLP
on the same formulation. In specification section 12's terms, alter the
**curriculum** first, then the **algorithm**:

1. ~~**Curriculum randomisation of starting pose and held item**~~ (§10.3
   step 3). **Done, and it did not work.** Implemented as
   `mockgame.MockPlateUp(randomise_start=True)`, dataset regenerated at three
   times the size (60 episodes, 187,950 states). Held-out accuracy rose to
   0.969 and groups served fell from 1 to **0**. Generalisation improved; play
   did not. Recorded rather than quietly dropped, because it is the textbook
   remedy and it is the third time in this project that accuracy and play moved
   in opposite directions.

2. **RL fine-tuning for precision and recovery** (§10.3 step 6) is therefore
   now first. The environment, the bounded event-based reward and the
   anti-hacking suite are all in place. The reasoning is no longer a
   preference: cloning optimises per-frame likelihood, the split diagnostic
   says the press head is already at parity, and what is left is *arriving at a
   pose* - a property of a trajectory, not of a frame. A per-frame likelihood
   objective has no way to express it, which is consistent with three
   independent observations of accuracy rising while play fell.

3. **If RL does not close it, change what the policy outputs.** Section 7.1
   keeps a small continuous movement head as the declared comparison baseline
   against the 5x5 discretisation. Quantising a proportional controller to five
   values per axis discards exactly the precision that arrival needs, and that
   is a representation problem no amount of data fixes.

4. **Only then revisit the press.** It is already at parity under a scripted
   route, so there is nothing to fix until movement stops being the binding
   constraint.

Deliberately **not** on the list: a bigger network, more DAgger, or more
epochs. Section 12 says not to simply run longer, and the split says the
problem is one specific half rather than general weakness, which is not what
more of the same fixes.

## 6. What this does not change

- The pipeline is complete and measured end to end: demonstrations and model
  rollouts to datasets, datasets to a policy, policy to metrics with intervals.
- The reference controller still serves 4 of 4 on the model and is unaffected.
- Nothing here has run in PlateUp, so all of it describes a model. The first
  live run is still the gate that turns any of it into evidence, and it would
  also replace the model's steak timings, which are knowledge-base priors that
  have never been observed on an actual steak.

## 7. Revisit

Item 1 has now been measured and failed, and this document was updated rather
than replaced. It is re-opened again when item 2 is measured: if RL
fine-tuning closes the movement gap, Phase G proceeds; if it does not, item 3
becomes the next change and the discretised action space itself is the
suspect.

A note on the shape of this record. Two of the seven revisions were the
*correct standard remedy* for a correctly diagnosed problem, and both made
things worse. Keeping them visible, with their numbers, is the difference
between a project that knows what it has ruled out and one that will try them
again in six months.
