# Project 1 recipe: steak

**Status:** scope decision by the project owner. **Not** a benchmark result.
**Date:** 2026-07-29
**Pinned game:** PlateUp `1.4.3-FF8F`
**Bridge:** `0.3.0`
**Protocol / schemas:** `1` / `obs_0.1` / `act_0.1` / `demo_0.1`

---

## 1. What was decided, and by whom

Project 1 is fixed to the **steak** base recipe. The decision was made by the
project owner as a scope choice so that the agent layers could be built, not by
running the benchmark in
[`recipe-benchmark-protocol.md`](recipe-benchmark-protocol.md).

This file exists so that distinction survives. Specification section 10.5 says
"do not lock burgers or steak by argument alone", and the benchmark protocol
was written specifically to stop the recipe being chosen by preference. That
protocol has **not** been run: no benchmark session has been recorded for
either arm, and the ledger's "Recipe benchmark result" row remains PENDING.

Nothing downstream may describe steak as the *measured* easier recipe. The
correct description is: **steak was selected as the Project 1 scope; the
comparative measurement is outstanding.**

## 2. What this does and does not change

Unchanged:

- the benchmark protocol stays as written, including its decision rule and its
  §5.1 tiebreak, so it can still be run later without being adjusted after the
  fact;
- the ledger keeps the benchmark as PENDING rather than recording a result;
- the analyzer keeps the burger patterns and its provenance cross-check, so a
  burger arm can still be measured.

Changed:

- Phase E's observation encoding, the option vocabulary, and the Phase H
  success definition are all built against the steak chain
  ([`steak-recipe.md`](steak-recipe.md));
- the offline model, the reference controller and the surrogate all target
  steak, and the offline model refuses a layout that provides another
  recipe's ingredients rather than pretending to simulate it.

## 3. Why this is a defensible place to be

Three things make the missing measurement less costly than it first looks.

**The benchmark could not have compared the recipes under load anyway.**
Protocol section 4.1.1 already established, from the existing recordings, that
Day 1 saturates every demand-pressure proxy: patience at first delivery sat at
0.996 to 0.998 and minimum patience at 0.977 to 0.998. The benchmark measures
intrinsic production-chain cost, and a load comparison would need a harder day
and a new protocol regardless.

**One of the two arms already has a recorded day.** `runs/demos/smoke.jsonl` is
a steak Day 1 on the pinned build. It supplied the layout, the item chain, the
provider conventions and the customer-lifecycle timings that the offline model
and the surrogate are built on. The burger arm has `runs/golden`, so both
recipes have one observational anchor each; what neither has is the six to
eight matched sessions the protocol requires.

**The decision is explicitly revisable.** Protocol section 7 already lists the
revisit triggers, and a scope decision is weaker evidence than a tiebreak,
which is itself weaker than a measurement. Section 5 below tightens what would
re-open it.

## 4. What steak costs, stated plainly

The protocol named the risk in advance and it has not gone away:

- steak has a **multi-stage doneness chain**, `Meat → Rare → Medium →
  Well-done → Burned`, where burgers have one cook step;
- `is_bad` becomes true on Well-done, which is **still servable**, so the
  failure mode is a timing decision rather than a missing step;
- there is a real burn state with a distinct item name, where an overcooked
  patty just becomes the generic `Burned Food`.

Two things blunt this in practice, both of which are measured rather than
argued, and both recorded in [`steak-recipe.md`](steak-recipe.md):

1. Rare, Medium and Well-done all plate to the same `Steak - Plated`, which is
   what the order names and what it pays for. Cooking past Rare buys nothing,
   so the controller lifts at the first servable stage and the doneness chain
   collapses to a single decision: take it now.
2. `(1 - progress) / rate` gives the exact seconds left in the current stage
   from two published fields, so the burn deadline is observable rather than
   inferred from a recipe table.

The residual risk is real and unmeasured: a *learned* motor policy that misses
a grab has a narrower recovery window on steak than on burgers, and the
knowledge base puts that window at roughly 13 s on a starting hob. That is a
Phase G and Phase H question and it is one of the revisit triggers below.

## 5. Revisit triggers

In addition to the protocol's section 7 triggers, this decision is re-opened
when any of the following happens:

- Phase G shows a first-attempt grab success rate low enough that the
  Well-done-to-Burned window is regularly missed;
- Phase H meal completion falls below its gate specifically because of burn
  losses rather than for reasons common to both recipes;
- the benchmark is later run and returns a burger win under section 5 of the
  protocol;
- the pinned build changes the steak chain or its timings.

A revisit produces a new ledger entry. This entry is retained either way.

## 6. Consequences already committed

| Area | Committed to steak |
|---|---|
| Recipe graph | [`steak-recipe.md`](steak-recipe.md), `python/steak.py` |
| Option vocabulary | `python/options.py` |
| Reference controller | `python/service.py` |
| Offline model | `python/mockgame.py` |
| Semi-MDP surrogate | `python/surrogate.py` |
| Observation encoding | `python/encode.py` |
| Environment | `python/env.py` |

Every one of these resolves item, appliance and process identities by **name**
through the connection's `dict` frame rather than by hardcoded id, and
`steak.Registry.require()` fails loudly if a name is missing. Swapping the
recipe means writing a new chain definition, not rewriting the layers.
