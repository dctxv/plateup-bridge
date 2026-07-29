# The steak production chain

**Status:** derived from recorded artifacts, with the assumed parts marked
**Pinned game:** PlateUp `1.4.3-FF8F`
**Bridge:** `0.3.0`
**Observation schema:** `obs_0.1`
**Implementation:** `python/steak.py`

Specification section 1.2 puts observed runtime data above the knowledge base,
and section 8.2 requires a recipe to be stored as a graph rather than as prose.
This file is that graph, with each fact carrying where it came from.

The rule applied throughout: **anything the bridge publishes is used directly;
anything from the knowledge base is a prior and is labelled.** The live
controller never needs a prior, because the two fields it depends on are
published.

---

## 1. The graph

```text
Source - Meat  --provides-->  Meat
Meat           --Cook-->      Steak - Rare
Steak - Rare   --Cook-->      Steak - Medium
Steak - Medium --Cook-->      Steak - Well-done      (is_bad becomes true)
Steak - Well-done --Cook-->   Steak - Burned         (waste)

Steak - Rare | Medium | Well-done  + Plate  -->  Steak - Plated
Steak - Plated --served-->  order satisfied, Plate - Dirty left on the table
Plate - Dirty  --Clean-->   Plate
```

Card variants keep the same shape with different names and timings and are
implemented alongside the plain cut: `Boned`, `Thick` and `Thin`. Only the
plain cut is in Project 1 scope. The boned cut additionally leaves
`Boned Steak - Bone` and `Plate - Dirty with Bone`, which the plate model
already treats as a leftover-carrying plate.

## 2. Measured facts

### 2.1 The order

From `runs/demos/smoke.jsonl`, a steak Day 1 on the pinned build, across 204
order-entry frames:

| Field | Value |
|---|---|
| `iid` | `Steak - Plated` |
| `is_side` | `false` |
| `reward` | `5` |
| `dirt` | `Plate - Dirty` |

**No doneness is requested.** There is one plated item and every servable
doneness produces it, which collapses the doneness chain to a single decision
and is the most important fact in this document. The reward of 5 matches the
knowledge base's base value for steak.

### 2.2 Process rate is published, so timings are not needed

`CItemUndergoingProcess.CurrentChange` is emitted as `rate` and is progress per
second. In `runs/golden/obs_0.1_day1.jsonl` a patty on a starting hob went from
`progress` 0.019 to 0.994 across 2.6 seconds at a constant `rate` of 0.375, and
a plate in a starting sink went from 0.006 to 0.979 across 2.594 seconds, also
at 0.375.

Therefore:

```text
seconds_left_in_this_stage = (1 - progress) / rate
```

This is arithmetic on two published fields. It needs no recipe table, and it
stays correct when a card, an appliance upgrade or a patch changes the speed.
`Chain.seconds_to_next` is exactly this expression, and it is what the
controller uses.

### 2.3 `is_bad` is the burn warning, one stage early

`is_bad` is a lookahead flag on the transition currently running. In the
recorded burger day it turned true on `Burger Patty - Cooked`, whose next
transition is `Burned Food`. For steak it turns true on `Steak - Well-done`,
which is **still servable**.

This is why `is_bad` is not counted as a failure anywhere in this project, and
why the controller treats it as a forced-lift signal rather than as damage.

### 2.4 Plating freezes the item

A plated dish carries no `process` field in any recorded frame, matching the
knowledge base's statement that plated food stops cooking. Plating is therefore
also the safe way to park a cooked steak.

The recorded plating route is: hold the cooked item, grab the plate provider,
end up holding the plated dish. In `runs/golden` a cooked patty in hand became
`Burger - Plated` with components `[Plate, Burger Patty - Cooked]`. Component
order varies between frames, so composition must be compared as a multiset.

### 2.5 Plates are the binding constraint

`Plate Stack - Starting` reports `maximum` 4 and an `available` count that
falls to 0 as plates are taken. Infinite providers — `Source - Meat`,
`Source - Burger Patty`, `Source - Burger Buns` and the sink's `Water` — report
`maximum` 0 and `available` 0. This corrects the earlier guess that a negative
value meant infinite; see `python/facts.py`.

A served plate returns as `Plate - Dirty` on the table, where it also blocks
the table for the next group, so clearing and washing is on the critical path
rather than being tidying-up.

### 2.6 Customer lifecycle, fitted from both recordings

| Phase | `PatienceReason` | Duration | Patience drain |
|---|---:|---|---:|
| Seating | 2 | 8.0–10.4 s observed | none |
| Thinking | 0 | 3.0 s | none |
| Service | 3 | 4.3–5.2 s | 0.00434 /s |
| WaitForFood | 4 | until served | 0.00722 /s |
| Eating | 1 | ~3.0 s | none |
| Complete | — | table released | — |

`patience_total` is always 1 and `patience_left` is the remaining fraction, so
the drain rates give roughly 230 s of Service patience and 139 s of
WaitForFood patience. Day 1 is 100 s long with four groups of one arriving
about 24.5 s apart, which is why Day 1 never stresses patience.

## 3. Assumed values: knowledge-base priors

These are **hypotheses** under specification section 1.2 and are used only by
the offline surrogate, never by the live controller.

| Transition | Base seconds | Source |
|---|---:|---|
| `Meat → Rare` | 5 | knowledge base |
| `Rare → Medium` | 2 | knowledge base |
| `Medium → Well-done` | 2 | knowledge base |
| `Well-done → Burned` | 10 | knowledge base |

The one measured bridge between the table and reality is the
**starting-appliance multiplier**. The knowledge base gives a plain sink a 2 s
plate wash and a starting sink about 2.66 s, and gives a raw patty a 2 s cook.
Both measured at 0.375 progress per second, which is 2.667 s. Two independent
appliances therefore agree on the same 0.75 speed multiplier, and
`Chain.timescale` recovers it from either.

Applying it to the table gives the priors used by the surrogate:

| Stage on a starting hob | Prior seconds |
|---|---:|
| `Meat → Rare` | 6.67 |
| `Rare → Medium` | 2.67 |
| `Medium → Well-done` | 2.67 |
| `Well-done → Burned` | 13.33 |

**None of these has been measured on a steak.** The smoke recording contains a
steak restaurant but no cooking: the demonstrator carried a piece of meat and
put it on a counter. The first live steak cook will replace all four, and
`Chain.timescale` is written so that one observed `rate` on any stage rescales
the rest.

## 4. The doneness decision

Because every servable stage plates to the same dish for the same reward:

> Lift at the first servable stage. Cooking on buys nothing and risks the burn.

`options.WatchCook` implements this with a `min_stage` parameter so that the
alternative can be measured rather than assumed, and `is_bad` forces the lift
whatever `min_stage` is set to.

Offline, on the model, waiting for Well-done cost throughput without reducing
losses: a saturated modelled day served 7 groups lifting at Rare and 6 lifting
at Well-done, with zero ruined items either way
(`runs/benchmark/mock-sweep.txt`). That is a result about the model, whose
steak timings are the section 3 priors, and not about PlateUp.

Zero ruined items at every doneness setting is the more interesting half of
it: `is_bad` gives roughly 13 seconds of warning on a starting hob, and a
rescue that outranks everything except waste disposal is enough to use it. The
question the model cannot answer is whether a *learned* motor policy, which
will miss grabs, still fits inside that window. That is a Phase G question and
a `steak-decision.md` §5 revisit trigger.

## 5. Failure modes and what the controller does about them

| Failure | Detection | Response |
|---|---|---|
| Steak about to burn | `is_bad` true on a servable item | lift immediately, ahead of serving |
| Steak burned | name matches the ruined pattern | carry to the bin; it cannot be plated |
| No clean plate | provider `available` 0 and no clean plate in the kitchen | clear a table and wash before cooking more |
| Table blocked by a dirty plate | dirty plate held by a table appliance | clear it; a blocked table takes no group |
| Hands full when a group is waiting | held item is not the plated dish | stash into the first accepting target |

There is no free drop in PlateUp, so every one of these is a contextual grab at
an accepting target. An option that cannot find one returns without pressing
rather than pressing at empty floor.

## 6. What is still unknown

- Steak cook durations have never been observed; section 3 is a prior.
- Whether a burned steak can be placed on a plate at all. The controller bins
  it, which is correct either way.
- Whether the plate stack accepts clean plates back. The controller prefers a
  free counter and only falls back to the stack when every counter is full.
- Whether combining in the other direction — holding a plate and grabbing a
  cooked steak — works. Only the provider route has recorded evidence, so that
  is the primary route and the other is a fallback.
- Fire. `on_fire` has never been observed and a starting hob does not produce
  it; burned food alone does not ignite.
