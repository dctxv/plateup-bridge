# PlateUp Autonomous AI Agent

## Revised Creation, Training, and Evaluation Specification

**Document status:** Build-ready engineering and experiment specification (Markdown edition)  
**Revision:** 2.0  
**Research baseline:** 27 July 2026  
**Target game:** PlateUp on Steam for Windows, public stable branch, stable 1.4.3 baseline  
**Target machine:** NVIDIA RTX 5060 Ti 16 GB, AMD Ryzen 5 5600, 16 GB DDR4  
**Primary languages:** C# for the in-game bridge/mod; Python for environments, training, surrogate simulation, evaluation, optimisation, and evidence tooling  
**Current project position:** Phase C - Primitive Action Bridge, in progress  

> **Primary outcome:** build an autonomous agent that controls the PlateUp player, prepares a restaurant it can actually operate, and advances without human gameplay intervention.

---

# Executive summary

This revision converts the original methodology-heavy plan into an ECS-first engineering programme. It keeps the original autonomy standard while changing the implementation where the review and current evidence require it.

The decisive changes are:

1. **Use PlateUp's ECS as the bridge boundary.** Read entities, components, buffers, and singletons directly from an `IModSystem`. KitchenLib is optional and should be used only when its content/UI helpers are genuinely needed. Harmony is not the default state-reading mechanism.
2. **Treat input injection as the highest-risk integration point.** The discovered `IInputConsumer` and `LocalInputSourceConsumers.Consumers` path is the preferred first implementation. Phase C is not complete until movement and button press/release semantics are proven under load.
3. **Train motor control in the real game; train the task planner and higher layers in a surrogate.** The surrogate is a semi-Markov decision process over options. It uses measured option duration and failure distributions from the real motor policy.
4. **Do not emit per-tick action affordances.** The bridge exposes factual state - positions, contents, filters, process state, capacity, timers, and phase - but does not provide a legality oracle.
5. **Use Practice mode as the primary training harness.** Reset wall-clock time and time-scale fidelity are first-class architecture measurements.
6. **Auto-label demonstrations from interaction events.** The next entity interacted with supplies the goal label for the preceding movement segment.
7. **Replace 8-way movement with per-axis control.** The baseline is 5 x 5 discretised axes, with a small continuous alternative retained for comparison. Throw/drop behaviour must be represented and verified.
8. **Make determinism a Phase A decision.** Deterministic replay is either supported for the pinned build and scenario, or it is explicitly replaced by seeded statistical regression.
9. **Sequence the programme into separate publishable projects.** Autonomous Day 1 on a chosen layout is Project 1 and a valid video result. Layout generalisation and preparation are Project 2. Research, automation, menu generalisation, and headquarters autonomy are later projects.
10. **Apply wall-clock stop rules.** Exceeding a curriculum budget triggers a method review, not indefinite additional training.

The supplied telemetry establishes a strong read-only observation baseline. Customer groups, per-course state, orders, patience, tables, money, lives, process risk, and termination are legible. The remaining immediate engineering work is to freeze `obs_0.1`, correct entity identity handling, and close the primitive-input gate.

# 0. Purpose and success condition

## 0.1 Purpose

This specification defines an autonomous system that plays PlateUp rather than advising a human player. The system eventually covers:

- run setup;
- restaurant preparation and rearrangement;
- purchasing, research, cards, and other long-horizon choices;
- movement and interaction during service;
- adaptation of strategic and preparation decisions to the service controller's measured abilities;
- autonomous continuation until the declared endpoint or restaurant failure; and
- reproducible evidence of what was controlled, how the agent learned, and how reliable it is.

The first project is intentionally narrower: one supported recipe, one chosen layout family, no garage items, no franchise, no unsupported cards, and a publishable target of autonomous Day 1 completion.

## 0.2 What "AI" means here

The system may combine:

- behavioural cloning from human demonstrations;
- DAgger-style recovery data;
- reinforcement learning for motor and service policies;
- goal-conditioned neural policies;
- learned value and success models;
- search or cross-entropy/evolutionary optimisation;
- a semi-MDP surrogate over learned options; and
- a capability registry measured from the current motor and service policies.

A large language model is not required and is excluded from the scored real-time gameplay loop. Development assistance by an LLM must not be confused with gameplay control.

## 0.3 Core premise

> I trained an AI to operate its own PlateUp restaurant. It had to design a restaurant that its own learned controller could run. How far could it get without human control?

## 0.4 Success principle

A theoretically efficient restaurant is not enough. The project succeeds only when the proposed restaurant is valid, can be physically constructed through normal controls, and is reliably operable by the current learned service controller.

# 1. Version, evidence, and branch policy

## 1.1 Pinned baseline

For each training campaign, record:

- game semantic version;
- Steam build ID;
- Steam branch;
- platform;
- bridge version and Git commit;
- mod DLL hash;
- dependency versions;
- save/profile identifier;
- scenario and seed;
- observation/action schema versions; and
- model checkpoint identifiers.

Use the public stable Steam branch for Project 1. Do not mix Taste-Test data into stable training or evaluation. Back up the PlateUp save and disable unrelated Workshop mods before integration testing.

## 1.2 Evidence precedence

When information conflicts, use this order:

1. observed runtime component/event data from the pinned build;
2. inspected compiled assemblies or decompiled source from that build;
3. official patch notes for that branch;
4. current mechanics references such as the supplied knowledge base and its sources;
5. old guides, videos, or remembered behaviour; then
6. inference.

The knowledge base is useful but contains wiki-derived values and visible extraction defects. Numeric recipe, timing, card, and appliance facts from it are hypotheses until confirmed in GameData, assemblies, or a controlled probe. Do not hardcode a damaged recipe transcription merely because it appears in the PDF.

## 1.3 Determinism decision

Determinism is resolved during Phase A. The test must answer:

- Can an identical initial state, seed, fixed time step, and input sequence reproduce the same state trajectory within defined tolerances?
- Which subsystems diverge first?
- Does acceleration change the trajectory?
- Can a recorded demonstration be replayed closely enough to support DAgger and regression?

The result is binary at the programme level:

- **Deterministic path:** use exact replay and state hashes where supported.
- **Statistical path:** use fixed seeds, tolerance bands, repeated trials, and distributional regression. Never describe this path as deterministic replay.

## 1.4 Change-control rule

Any game, bridge, dependency, or schema change invalidates the previous integration certificate. Re-run component discovery, input tests, state probes, reset tests, and the policy regression suite before resuming training.

# 2. Experiment contract

## 2.1 Required autonomy in a scored run

During an active scored episode:

- every movement axis value comes from a learned policy;
- every Grab, Interact/Act, Ready/Start, and supported throw/drop gesture comes from the agent;
- every service task choice comes from the agent;
- every layout, preparation, purchase, card, research, reroll, storage, and discard decision in scope comes from the agent;
- no human rescues the restaurant; and
- infrastructure may detect termination and reset only after the episode has ended.

For Project 1, fixed setup variables that are outside the declared scope are allowed only if disclosed before evaluation.

## 2.2 Allowed infrastructure

Allowed infrastructure includes:

- structured observation of currently observable state;
- component-derived factual fields;
- automatic logging, watchdogs, resets, and checkpoint loading;
- Practice-mode scenario setup;
- accelerated training when fidelity has been measured;
- human demonstrations during training;
- curriculum scenarios;
- a physical layout validator;
- a goal planner that delegates to a learned motor policy;
- a surrogate simulator calibrated from real-game trials; and
- fixed seeds or statistically controlled evaluation partitions.

## 2.3 Disallowed hidden assistance

Disallowed assistance includes:

- human gameplay takeover;
- human card, purchase, or layout choices inside an autonomous category;
- scripted cook-plate-serve control of the character;
- deterministic pathfinding presented as learned motor control;
- teleportation or direct mutation of appliance contents;
- future information unavailable to a human;
- a bridge-supplied per-action legality or affordance oracle;
- cherry-picked continuation after manual restarts; and
- reporting only the best run without typical results.

## 2.4 Structured-state disclosure

Use this exact disclosure or a substantively equivalent one:

> The agent received a machine-readable representation of information available in the current game state. Neural policies selected the gameplay actions. The bridge did not reveal future random outcomes or provide a per-action legality oracle.

# 3. Programme scope and publishable projects

The work is one technical programme but not one practical project.

## 3.1 Project 1 - Autonomous Day 1

Scope:

- public stable branch;
- fresh solo restaurant;
- fixed or chosen known layout;
- one empirically selected base recipe;
- no garage items or franchise;
- fixed starting appliances;
- structured observations;
- learned movement, interaction, meal execution, customer loop, dish loop, and day-start action; and
- autonomous Day 1 evaluation with no human rescue.

This is the first publishable result.

## 3.2 Project 2 - Layout generalisation and preparation

Scope:

- held-out layouts within a defined map family;
- preparation planner;
- physical appliance/table movement;
- service-conditioned layout selection;
- surrogate layout search; and
- real-game validation of only the top three to five candidates.

## 3.3 Later projects

Keep these separate unless earlier gates demonstrate spare capacity:

- **Project 3:** purchases, blueprints, cards, and multi-day strategy;
- **Project 4:** research desks, copying/discount, and research scheduling;
- **Project 5:** automation appliances and configuration;
- **Project 6:** menu generalisation, map selection, and headquarters setup;
- **Project 7:** overtime and optional franchise lifecycle.

Claims must name the project boundary. "Autonomous PlateUp agent" does not imply every later project is complete.

# 4. PlateUp lifecycle model

## 4.1 Phase state machine

```text
HEADQUARTERS
  -> select fixed or agent-controlled setup
  -> enter restaurant

PREPARATION
  -> observe layout and inventory
  -> choose target arrangement
  -> physically move items/appliances
  -> agent sends Ready/Start

CUSTOMER_SERVICE
  -> arrival and seating
  -> thinking and service/order acquisition
  -> waiting for food
  -> partial or complete delivery
  -> eating
  -> optional later course
  -> table release
  -> day success or restaurant failure

POST_DAY
  -> blueprint/economy decisions
  -> card/theme decision when applicable
  -> preparation for next day

RUN_COMPLETE
  -> declared endpoint, failure, overtime decision, or later franchise extension
```

Practice is a training phase, not an evaluation claim. It is the preferred harness for repeatable scenarios and low-cost resets.

## 4.2 Confirmed customer lifecycle

Current telemetry confirms an end-to-end group lifecycle of:

```text
Starter/Seating
  -> Main/Thinking
  -> Main/Service
  -> Main/WaitForFood
  -> Main/GetFoodDelivered
  -> Main/Eating
  -> Dessert/Thinking
  -> Complete
  -> table released
```

Not every group orders every course. `MenuPhase.Complete` is a real terminal course state. Orders become observable in `CWaitingForItem` during `WaitForFood`, after the Service phase; they are not available at seating. A planner may prepare safe generic inventory, but it must not act as though a specific hidden order is known early.

The first delivery changes `WaitForFood` to `GetFoodDelivered` and resets patience. Partial satisfaction can therefore buy time. Satisfaction is per buffer entry/member, not merely per group.

## 4.3 Time semantics

The observed `t` value represents the normalised arrival-time bar. Values at or above 1.0 mean that scheduled arrivals have finished; they do not mean the service has terminated. Service continues until remaining customers and groups clear or the restaurant fails.

Use `STime` for the authoritative time fields:

- `TimeOfDay`;
- `TimeOfDayUnbounded`;
- `SecondsSinceDayBegan`;
- `DayLength`; and
- `ForcePause`.

Never infer episode termination from the time bar alone.

# 5. ECS-first game bridge

## 5.1 Integration model

PlateUp uses Unity DOTS/ECS for game state and systems. The bridge should be a small first-party-mod-loader-compatible assembly whose core is one or more `IModSystem` implementations.

The read path is:

```text
Entity queries and singleton reads
  -> immutable bridge snapshot
  -> versioned transport
  -> Python environment adapter
```

The write path is:

```text
Policy action
  -> command envelope
  -> bridge tick synchronisation
  -> IInputConsumer / InputState path
  -> receipt plus subsequent observed state
```

KitchenLib is not required for ordinary ECS state extraction. Use it only for a feature it materially supplies, such as content registration or UI. Harmony is a contingency for an integration point that cannot be reached through supported systems or consumers; it is not the default.

## 5.2 Highest-risk item: input

The inspected assemblies expose:

- `IInputConsumer.TakeInput(int player_id, InputState state)`; and
- `LocalInputSourceConsumers.Consumers`, a public static list of input consumers.

The first Phase C implementation should register a dedicated consumer and test the complete lifecycle of each command. Do not assume that finding this type proves safe control. The gate requires:

- correct player routing;
- movement magnitude and direction;
- facing behaviour;
- button down, hold, and release;
- simultaneous movement plus interaction;
- no sticky inputs after timeout, disconnect, pause, or episode end;
- behaviour at 1x and approved accelerated time scales; and
- no race with other local input sources.

If consumer registration cannot provide authoritative control, inspect the system ordering and the player input component path before considering a Harmony patch.

## 5.3 Snapshot timing and consistency

Each observation includes:

- monotonically increasing bridge sequence;
- game tick/frame identifier where available;
- phase;
- time-scale;
- wall-clock timestamp;
- schema version;
- build/version metadata; and
- an explicit stale/partial flag.

Build a snapshot from one consistent ECS update boundary. Do not combine customer data from one tick with player or order data from another.

## 5.4 Entity identity

Unity `Entity` identity includes index and version. The current logs appear to print a packed 64-bit representation in some group/table fields. Before freezing `obs_0.1`:

- expose `index` and `version` separately;
- use the pair as the within-session identity;
- do not treat the index alone as permanently stable;
- do not compare packed decimal display strings across runs; and
- add tests for destruction and index reuse.

Human-readable log labels may use `index:version`, for example `1542:3`.

# 6. Observation contract

## 6.1 Design rule

Emit facts, not answers. The bridge may state what an entity contains, accepts, blocks, or is currently doing because these are component-derived facts. It must not compute a synthetic `can_grab`, `can_place`, `best_target`, or action mask that reimplements the game's legality rules for the policy.

The policy must learn legal interaction from:

- positions and facing;
- holder capacity and contents;
- item/category traits;
- current process and progress;
- component filters;
- occupancy and reachability;
- previous actions and observed outcomes; and
- phase and timers.

Action masks may be used only for transport-level impossibilities such as an absent player slot, never for gameplay legality.

## 6.2 Observation groups

`obs_0.1` contains the following groups.

### Run and phase

- branch, build, scenario, seed, player count;
- day and overtime;
- current phase/subphase;
- practice flag;
- time scale;
- `SDay.Day`;
- `STime` fields; and
- current expected-arrival information where observable.

### Player

- entity identity;
- position, facing, and velocity or recent motion estimate;
- held item and tool/tray state;
- current input echo;
- dirty-shoe state;
- slow-player radius/factor where present; and
- active interaction/process state.

### Layout

- `CLayoutInfo.Layout`, `Setting`, and `Seed`;
- `CLayoutRoomTile.Position`, `RoomID`, `RoomType`, `HasFeature`, and `Reachability`;
- occupancy layer (`Default`, `Wall`, `Floor`, `Ceiling`);
- doors, walls, counters, appliances, holders, tables, chairs, and traversable tiles; and
- component-derived table and holder relationships.

The grid is derived from ECS queries. Do not maintain a hand-authored parallel map that can drift from the entity state.

### Items and processes

- item/GDO identity and traits;
- holder and slot;
- process ID, progress, duration where observable, next-result ID, and burn/spoil risk;
- portions and remainder;
- plated/combined contents;
- trash/dirt output; and
- fire state.

`ProcessType` is not an enum in the inspected build. `CItemUndergoingProcess.Process` is an integer ID referring to a Process ScriptableObject. Use a versioned registry resolved from live GameData; do not invent enum values.

`is_bad` is interpreted as a look-ahead property of the active transition. In the observed steak chain it becomes true at the transition whose result would be Burned; it is not a generic "already damaged" flag. Preserve raw process facts so this interpretation can be retested.

### Customers, groups, orders, and tables

- group and member identities;
- `CGroupMealPhase.Phase`;
- patience value, maximum, normalised fraction, and `PatienceReason`;
- `CAssignedTable.Table`;
- table identity and location;
- `CTableSet.IsWaitingTable` and `ChairCount`;
- each `CTablePlace` seat position, table position, and chair entity;
- all `CWaitingForItem` buffer entries; and
- course completion and table release.

For each `CWaitingForItem` entry expose:

- `ItemID`;
- `Item`;
- `Satisfied`;
- `Reward`;
- `MemberIndex`;
- `IsSide`;
- `DirtItem`;
- `SourceMenuItem`;
- `Extra`;
- `ExtraRequested`;
- `ExtraSatisfied`; and
- `SatisfiedBySharer`.

The observed enum names are:

- `MenuPhase`: Starter, Main, Dessert, Side, Complete.
- `PatienceReason`: Thinking, Eating, Seating, Service, WaitForFood, GetFoodDelivered, Queue, QueueInDarkness, QueueInRain, QueueInSnow.

Record numeric values from the pinned build and validate them through observation. Do not infer a numeric mapping from declaration order without checking.

### Economy and preparation

- `SMoney.Amount`;
- blueprint entities;
- `CApplianceBlueprint.Appliance` and `IsCopy`;
- `CForSale.Price`;
- cabinet/research state;
- reroll availability and request events;
- owned and movable appliances;
- holder filters and placement constraints; and
- active cards and menu items.

### Termination

- `SKitchenStatus.RemainingLives`;
- presence and contents of `SGameOver`;
- `LossReason`;
- day success transition;
- bridge/watchdog termination; and
- a normalised reason code.

`CheckGameOverFromLife` creates `SGameOver` with `LossReason.Patience` when remaining lives reach zero, subject to practice/rescue conditions. Termination detection must observe the actual state rather than guess from patience bars.

## 6.3 Holder and placement components

Use these inspected facts where present:

- `CItemHolderFilter.Category`, `AllowAny`, `NoDirectInsertion`;
- `CItemHolderOnlySpecificItem.ItemID`;
- `CItemHolderPreventTransfer.PreventInsertingInto`, `PreventTakingFrom`; and
- `ItemList.Components` plus `Size`.

Portable items normally cannot be placed on an empty floor tile. A sparse `loose_items` list is therefore expected and should not be treated as a bridge defect without a counterexample.

## 6.4 Known observation gaps

- Ordinary burning on a starter hob does not establish the fire observation path. Fire probes require a supported hazard such as a Danger Hob or relevant Microwave misuse in a controlled scenario.
- Fire mechanics and exact recipe timings taken only from the knowledge base remain unverified until probed.
- `on_fire` remains a logged known gap, not a silently passing field.
- Mess spawning requires additional inspection of `SpawnTableDirt`/`CreateNewMesses`; current supporting components include `CPlayerDirtyShoes`, `CSlowPlayer`, and `STimeTracker` use in event-specific systems.

# 7. Action and bridge protocol

## 7.1 Primitive action space

The default motor action at control tick `t` is:

```text
movement_x in {-1.0, -0.5, 0.0, 0.5, 1.0}
movement_y in {-1.0, -0.5, 0.0, 0.5, 1.0}
grab in {up, down/held}
interact in {up, down/held}
ready in {up, down/held}
stand_still in {up, down/held}, if the build/input path supports it
throw_or_drop gesture, represented using the verified InputState semantics
```

This is a 25-way movement grid before buttons. A small continuous `[-1, 1]^2` movement head is the comparison baseline. The choice is made by precision, stability, and visual quality in counter-approach tests, not by preference.

Do not model throwing as an invented key if the game implements it as a timed or contextual Grab gesture. The bridge action schema should describe intent, while the verified adapter maps that intent to the actual `InputState` sequence.

## 7.2 Control frequency

Begin evaluation at 12 Hz only as a measurement point. Test 10, 12, 15, and 20 Hz at 1x using:

- arrival-position error;
- counter-facing error;
- successful first-attempt Grab/Interact rate;
- overshoot;
- stuck-input incidents;
- CPU/IPC overhead; and
- policy smoothness.

Choose the lowest rate that meets the motor gate. The environment may repeat movement outputs between policy decisions, but button edge timing must remain exact.

## 7.3 Command envelope

Every command contains:

- command ID;
- policy step;
- expected snapshot sequence;
- player ID;
- action values;
- hold duration or explicit release;
- expiry tick; and
- model/checkpoint ID.

Every receipt contains:

- command ID;
- accepted/rejected transport status;
- applied tick;
- observed input echo;
- expiry/release status; and
- any bridge-level fault.

A receipt proves delivery to the input adapter, not successful gameplay. Gameplay success is inferred from the next factual observations.

## 7.4 Safety behaviour

On heartbeat loss, stale command, episode termination, pause transition, or Python disconnect:

- immediately release all buttons;
- set axes to zero;
- stop accepting commands from the stale session;
- emit a fault record; and
- require a fresh handshake before control resumes.

# 8. Coordinated hierarchical agent

## 8.1 Layers

```text
Run Setup Planner                    [later projects]
        |
Long-Horizon Strategy Planner        [later projects]
        |
Preparation / Layout Planner         [Project 2]
        |
Service Task Planner                 [semi-MDP policy]
        |
Goal-Conditioned Motor Controller    [real-game learned policy]
        |
Primitive PlateUp inputs
```

The hierarchy is coordinated through one ontology, one capability registry, shared map/recipe encodings, and real rollout evidence.

## 8.2 Option interface

The service task planner chooses an option such as:

- navigate to entity or interaction pose;
- acquire item;
- place/combine item;
- operate process;
- prepare a specified meal state;
- serve a specified order entry;
- clear a table;
- wash a plate;
- rescue a burning item;
- clean a blocking mess; or
- start the day.

Each option terminates on success, timeout, invalidated goal, emergency pre-emption, or policy failure. The motor policy remains responsible for movement and primitive interactions.

## 8.3 Capability registry

The registry is the explicit sim-to-real interface. For each option type and context, store:

- goal/object class;
- layout and local geometry features;
- held-item and appliance state;
- distance/path complexity;
- motor checkpoint;
- attempt count;
- success probability with confidence interval;
- duration distribution;
- interaction count;
- common failure categories;
- recovery probability;
- last validation build; and
- out-of-distribution score.

The surrogate consumes these distributions. The preparation and strategy layers use them to reject or penalise plans the current controller cannot reliably execute.

## 8.4 Pre-emption and emergency handling

The task planner may pre-empt a normal option for:

- imminent burn/spoil transition;
- critical patience;
- fire;
- blocked route or stuck policy;
- no clean plates when an order is ready; or
- an invalidated target.

Pre-emption is learned or value-based at task level. The bridge does not select the emergency action.

# 9. Semi-MDP surrogate

## 9.1 Purpose

Real PlateUp throughput is insufficient for task-planner, layout, and long-horizon training at useful scale. The surrogate is mandatory from Project 1 task-planner work onward, not a fallback.

## 9.2 State

The surrogate models the discrete operational state:

- phase and service clock;
- scheduled/active groups;
- per-group course, patience state, table, and order buffers;
- item and recipe graph states;
- appliance/holder contents;
- clean/dirty plate inventory;
- process timers;
- player option location/context;
- money and supported later-project decisions; and
- terminal conditions.

Continuous player motion is not simulated frame by frame. It is replaced by context-conditioned option outcomes from the capability registry.

## 9.3 Transition model

When an option is chosen:

1. sample or predict success/failure from the calibrated model;
2. sample duration and resource effects;
3. advance all timers and customer processes;
4. apply the observed option result;
5. produce the next decision state and reward; and
6. record whether the transition is inside the calibration support.

This is a semi-Markov process because options have variable duration.

## 9.4 Calibration and validation

For every major motor checkpoint:

- collect real option trials across distance and geometry strata;
- fit duration and failure models;
- compare surrogate and real service metrics;
- measure calibration error and survival-curve error;
- flag unsupported contexts; and
- invalidate old registry rows when build, observation, action, or motor versions change.

The surrogate is accepted only if it predicts held-out real service outcomes within predefined tolerances. It must not be tuned on the final evaluation seeds.

## 9.5 Layout search

Search hundreds or thousands of candidates in the surrogate. Use physical validation first, then risk-adjusted surrogate scoring. Validate only the top three to five diverse candidates in real-game services. Feed those real results back into the capability and layout-value models.

# 10. Demonstrations and learning

## 10.1 Demonstration recording

Record at bridge tick resolution:

- observation snapshot;
- raw player `InputState`;
- entity interactions;
- held-item changes;
- process changes;
- course/order changes;
- episode/scenario metadata; and
- dropped or delayed tick indicators.

## 10.2 Automatic goal labelling

Segment a human trajectory on interaction events. For each segment ending in an interaction:

- label the interacted entity and interaction type as the primary goal;
- retain the terminal held-item and target state;
- include a short post-interaction window to capture outcome;
- split or discard segments containing ambiguous multiple targets; and
- allow manual correction for a sampled quality set.

This produces goal-conditioned motor data without requiring full manual intent annotation. Non-interaction navigation and recovery segments may use future nearest interaction or explicitly mined subgoals.

## 10.3 Motor training

Training order:

1. behavioural clone per-axis movement and button edges;
2. goal-condition on target entity/interaction pose;
3. add curriculum randomisation in starting pose and held item;
4. collect on-policy failures;
5. add DAgger-style corrective demonstrations;
6. fine-tune with RL for precision, efficiency, and recovery; and
7. freeze a motor checkpoint before capability calibration.

## 10.4 Service task planner

Train the task planner primarily in the surrogate:

1. build option traces from demonstrations and scripted scenario labels used only for training data construction;
2. behavioural clone option selection;
3. train with RL or offline RL against service outcomes;
4. randomise option duration/failure within confidence bounds;
5. validate on real services;
6. update calibration; and
7. repeat until the real/surrogate gap passes.

Scripted scenario setup is allowed; scripted control during evaluation is not.

## 10.5 Recipe selection

Do not lock burgers or steak by argument alone.

- Burgers have a simpler preparation chain but the supplied mechanics reference reports a +30% expected-group modifier.
- Steak has no equivalent expected-group increase in the supplied reference but introduces a multi-stage doneness chain and narrow timing decisions.

Run a short controlled benchmark for each candidate using identical layout scale and human demonstrations. Compare:

- complete-meal demonstration error;
- order throughput;
- burn/wrong-doneness rate;
- customer load;
- option count per meal;
- Day 1 human baseline; and
- early policy learning curve.

Choose the recipe with the lower measured Project 1 difficulty. Record the choice as a capability decision.

# 11. Reward and anti-hacking specification

## 11.1 Motor rewards

Use bounded, potential-based or event-based terms for:

- decrease in target-pose distance;
- correct facing and interaction range;
- successful intended interaction;
- option completion;
- low collision/oscillation;
- prompt recovery after a failed interaction; and
- elapsed option time.

Do not reward proximity indefinitely. Potential-based distance rewards must telescope so orbiting a target cannot accumulate return.

## 11.2 Service rewards

Primary outcomes:

- group/order satisfaction;
- table turnover;
- day completion;
- lives remaining;
- elapsed service time;
- correctly completed recipe state;
- plate and appliance availability; and
- avoidance of burn, discard, fire, and patience failure.

Intermediate rewards are diagnostic aids, not substitutes for day completion.

## 11.3 Required anti-hacking tests

Explicitly test:

- idling to end an unfavourable episode faster;
- never pressing Ready/Start;
- repeatedly triggering a dense shaping event;
- holding an input forever;
- serving partial orders only to reset patience without completing them;
- deliberately failing to reach a cheaper reset;
- camping at a target for proximity reward;
- throwing or discarding useful items for event rewards;
- exploiting Practice-only reset state; and
- exploiting stale observations or duplicate command receipts.

Mitigations include a bounded episode cost, a start-decision deadline, no reward for failed termination, unique event IDs, per-event caps, and evaluation without exploration noise.

# 12. Curriculum and wall-clock stop rules

Each stage has a pass gate and a budget. The budget is cumulative elapsed training/engineering time after the relevant bridge is stable. Exceeding it requires a written method-change decision: alter representation, data, environment, curriculum, algorithm, or scope. Do not simply run longer.

| Stage | Target | Initial wall-clock budget | Pass gate |
|---|---|---:|---|
| C1 | Input transport and release | 2 engineering days | 100,000-command soak; zero sticky inputs; correct player routing |
| C2 | Counter approach and facing | 12 real-game training hours | >=98% target-pose arrival; <=2% overshoot failures |
| C3 | Grab/place/interact | 18 real-game training hours | >=95% first-or-second-attempt success on held-out starts |
| C4 | Throw/drop gesture | 6 real-game training hours | >=95% intended outcome; no accidental destructive use |
| D1 | Practice reset automation | 3 engineering days | 500 resets; >=99% success; reset-time distribution recorded |
| D2 | Time-scale fidelity | 2 engineering days | approved scale preserves motor success within 2 percentage points |
| E | Environment and logging | 3 engineering days | API checks, random-action soak, reproducible episode records |
| F | Demonstration pipeline | 5 engineering days | auto-label audit >=95% on sampled segments |
| G | Goal-conditioned motor | 7 calendar days / 24 GPU-hours | option gates pass across held-out starts |
| H | One complete meal | 5 calendar days / 20 real-game hours | >=90% completion across 100 fixed-scenario trials |
| I | One full customer loop | 5 calendar days / 20 real-game hours | >=85% across 100 trials, including dish reuse |
| J | Autonomous Day 1 | 10 calendar days / 40 real-game hours | declared evaluation threshold met before publish |

Budgets are planning controls, not claims that success is guaranteed within them. After two failed method revisions at one gate, reduce scope or redesign the interface before continuing.

# 13. Preparation and layout optimisation

## 13.1 Plan representation

A plan specifies:

- appliance/table positions and orientations;
- active chairs;
- holder contents that persist into service where legal;
- route clearances;
- intended work cells;
- expected option graph;
- future expansion reservations; and
- construction action sequence.

## 13.2 Physical validator

Reject candidates that violate:

- tile occupancy and wall constraints;
- door/customer/player reachability;
- interaction-side access;
- required chair/table linkage;
- ingredient-to-process-to-plate reachability;
- sink and dirty-dish loop access;
- legal placement and holder filters; or
- the agent's declared minimum route width.

The validator may reject physically invalid arrangements. It must not choose among valid layouts on behalf of the learned planner.

## 13.3 Service-conditioned score

Score valid candidates using:

- expected Day 1 success;
- lower confidence bound of success;
- expected option duration;
- patience-failure probability;
- burn/waste risk;
- recovery access;
- construction cost;
- capability out-of-distribution penalty; and
- sensitivity to timing/model error.

Do not use shortest theoretical travel distance as the primary objective.

## 13.4 Real-game validation

For each search round:

1. generate candidates;
2. reject invalid candidates;
3. score in the surrogate;
4. select three to five diverse finalists;
5. execute real services;
6. update the layout-value model and capability registry; and
7. retain the most robust candidate, not merely the best single rollout.

# 14. Strategy, cards, and later-project logic

The long-horizon planner evaluates:

- supported mechanics;
- service-policy capability;
- predicted survival value;
- money opportunity cost;
- layout disruption;
- retraining cost;
- future recipe/menu complexity; and
- uncertainty.

A card or appliance that is strong for an expert human may be invalid for the current agent. Unsupported content is filtered before value comparison and logged as unsupported rather than assigned an arbitrary negative value.

Research, copying, discount, automation, decoration effects, headquarters selection, and franchise decisions are outside Project 1. Their observation vocabulary may be logged early, but they do not block the first publishable endpoint.

# 15. Practice mode, reset throughput, and acceleration

## 15.1 Practice as the harness

Practice mode is the default controlled-training environment because it permits repeated setup without consuming a scored run. Record whether a scenario setup used direct infrastructure state construction or physical preparation; only the latter can support an autonomous-preparation claim.

## 15.2 Reset metrics

Measure from terminal detection to the first controllable tick of the next scenario:

- median;
- p90 and p99;
- failure rate;
- wrong-scenario rate;
- stale-state rate; and
- human intervention count.

Reset wall-clock time, not render FPS, is the primary throughput metric for early architecture.

## 15.3 Time-scale test

At each candidate time scale, compare against 1x:

- movement distance per game second;
- acceleration/deceleration and overshoot;
- interaction success;
- process duration ratios;
- customer/patience timing;
- input edge recognition; and
- option outcome distributions.

Approve acceleration separately for motor training and task-planner data collection. A scale acceptable for discrete rule collection may still be unsuitable for motor training.

# 16. Testing and verification

## 16.1 Bridge tests

- component queries return expected entity counts;
- singleton absence is handled without stale data;
- dynamic buffers are copied safely;
- snapshot sequence is monotonic;
- entity index/version identity survives creation/destruction;
- commands are applied once;
- expiry releases all controls;
- disconnect releases all controls;
- pause and phase transitions do not leak input; and
- build/schema handshake rejects incompatible clients.

## 16.2 Game invariant probes

- `CWaitingForItem.Satisfied` flips only for the correct order entry;
- partial delivery changes patience phase as observed;
- table assignment appears at seating and clears at completion;
- orders are absent before the observable ordering transition;
- `t >= 1.0` does not terminate while customers remain;
- `SGameOver` and `LossReason` match life depletion;
- `SMoney.Amount` matches observed purchase/revenue events;
- process IDs resolve to the correct live ScriptableObjects;
- portable floor placement behaves as represented; and
- fire logging is tested only in an appropriate hazard scenario.

## 16.3 Random-action soak

Run at least 100,000 commands across phase transitions and resets. Fail on:

- crash;
- hung bridge;
- sticky input;
- duplicate action application;
- malformed snapshot;
- unbounded queue growth;
- stale session continuing control; or
- entity reference causing an exception after destruction.

## 16.4 Policy regression

Maintain fixed scenario suites for:

- navigation;
- counter approach;
- Grab and place;
- Interact/Act;
- throw/drop;
- one meal;
- one customer;
- dish wash/reuse;
- emergency burn rescue; and
- Day 1.

On a statistical determinism path, compare confidence intervals and distribution shifts rather than exact trajectories.

# 17. Evaluation protocol

## 17.1 Categories

Report separately:

- fixed-layout motor tasks;
- fixed-layout service;
- held-out-layout service;
- autonomous preparation;
- multi-day strategy; and
- full-scope autonomous run.

Never merge results from categories with different human-fixed inputs.

## 17.2 Partitions

Use:

- training scenarios/seeds;
- validation scenarios;
- development test scenarios; and
- sealed final evaluation scenarios.

The final set is not used for reward tuning, layout choice, capability calibration, or video attempt selection.

## 17.3 Baselines

At minimum compare:

- human baseline on the declared scenario;
- behavioural-cloning-only motor/service baseline;
- RL-fine-tuned system;
- task planner without capability uncertainty;
- calibrated semi-MDP task planner; and
- shortest-distance or simple heuristic layout score versus service-conditioned layout score in Project 2.

## 17.4 Required metrics

- episode and day completion rate with confidence intervals;
- median and best highest day where applicable;
- lives remaining;
- orders/groups served;
- patience failures;
- burn/waste/wrong-item rate;
- option success and duration;
- interaction attempts;
- idle time;
- reset time;
- wall-clock training time;
- real-game environment hours;
- surrogate steps;
- human demonstration minutes; and
- human interventions during scored runs (required value: zero).

## 17.5 Reporting rule

Show typical performance as the primary result. A best run may be shown as a separate highlight if the number of attempts and the distribution are disclosed.

# 18. Video evidence specification

Capture from the beginning:

- bridge and game build identifiers;
- observation/action schema versions;
- training curves and wall-clock;
- reset and time-scale experiments;
- representative failures;
- input/action overlay;
- option/task overlay;
- current phase, day, lives, and orders;
- model checkpoint;
- human intervention counter; and
- uninterrupted final evaluation footage where practical.

Use precise claim language:

- "learned motor controller" only when movement and primitive interactions are policy-generated;
- "autonomous Day 1" only when the agent also presses Start and no human rescues it;
- "autonomous preparation" only when the agent selects and physically executes the layout;
- "full run" only for the exact declared lifecycle scope; and
- "structured state" rather than "vision" when pixels are not the observation.

# 19. Build phases and stop/go gates

## Phase A - Version, ECS, mod, and determinism feasibility

**Gate:** pinned build loads the bridge; ECS queries work; save is backed up; determinism classification is documented; input path candidate is identified.

## Phase B - Read-only bridge and `obs_0.1`

**Gate:** complete, consistent snapshots cover player, layout, holders/items, processes, customers/groups, orders, tables, money, lives, time, phase, and termination.

**Current evidence:** substantially complete. Telemetry has demonstrated two concurrent groups, per-course transitions, satisfaction, patience resets, table assignment/release, late order appearance, money/lives, and a terminal reason. Before formal closure, fix entity identity representation and publish the frozen field list and enum mappings.

## Phase C - Primitive Action Bridge

**Status:** in progress.

**Known:** `IInputConsumer` and `LocalInputSourceConsumers.Consumers` provide a credible injection/recording route.

**Not yet proven by the supplied evidence:** reliable autonomous movement, Grab, Interact/Act, Ready, throw/drop semantics, and clean release across timeouts and phase transitions.

**Gate:**

- per-axis movement is controllable;
- button edge/hold/release behaviour is correct;
- throw/drop behaviour is mapped to real input semantics;
- control targets the correct player;
- acknowledgement and input echo work;
- disconnect/expiry releases inputs;
- 100,000-command soak passes; and
- action frequency is selected from measured precision.

## Phase D - Episode automation

**Gate:**

- agent can start a day using the verified input path;
- `SGameOver` and day-success transitions terminate correctly;
- Practice scenario reset succeeds >=99% across 500 attempts;
- reset wall-clock distribution is recorded; and
- time-scale fidelity decision is documented.

Reset may use `InputState.Request` only after its exact semantics are confirmed for the pinned build.

## Phase E - Gymnasium-compatible environment

**Gate:** deterministic or statistical reset contract, observation/action validation, command receipts, timeouts, terminal reasons, and random-action soak all pass.

## Phase F - Demonstration and auto-labelling pipeline

**Gate:** raw demonstrations replay/align within the determinism classification; interaction segmentation works; sampled goal labels meet the quality threshold.

## Phase G - Goal-conditioned motor controller

**Gate:** held-out navigation, facing, Grab, place, Interact, and recovery thresholds pass at 1x.

## Phase H - One complete meal

**Gate:** the selected recipe is completed and plated at the declared success rate across held-out starts.

## Phase I - One complete customer and dish loop

**Gate:** order acquisition, preparation, serving, table clearing, washing, and plate reuse complete without hidden scripting.

## Phase J - Autonomous Day 1

**Gate:** evaluation threshold is set before final trials; the agent presses Ready/Start; no human input occurs; typical and best results are reported.

**Project 1 ends here.**

## Phases K-L - Project 2

- **K:** layout-family generalisation.
- **L:** autonomous preparation and service-conditioned layout optimisation.

## Phases M onward - later projects

- **M:** purchases and supported cards.
- **N:** research and multi-day strategy.
- **O:** automation appliances.
- **P:** menu generalisation.
- **Q:** headquarters setup and run selection.
- **R:** overtime/franchise extension.

Each phase receives a separate experiment contract and evaluation category.

# 20. Current project status

## 20.1 Confirmed complete or near-complete

- stable 1.4.3 knowledge baseline exists;
- relevant assemblies have been inspected directly with Mono.Cecil where ordinary decompilation was incomplete;
- ECS structures for orders, tables, day/time, money, layout, shop, placement, and input consumers have been identified;
- customer lifecycle is observable end to end;
- concurrent groups are disambiguated;
- order entries and partial satisfaction are visible;
- patience phase resets are visible;
- table assignment and release are visible;
- time-bar semantics are understood;
- process risk and held/appliance state are available;
- money, lives, and termination reason are available; and
- `obs_0.1` is sufficient to begin environment work after the freeze checks.

## 20.2 Required corrections before the freeze

1. replace packed entity display values with explicit `index` and `version`;
2. document every `obs_0.1` field and unit;
3. record numeric enum mappings from the pinned build;
4. mark untested fire state as a known gap;
5. document `is_bad` as a transition-risk interpretation, retaining raw facts;
6. document `t` as an arrival-bar value, not a terminal flag;
7. remove any per-tick affordance/legality fields;
8. add schema/build hashes to each episode; and
9. commit a representative golden trace.

## 20.3 Immediate next work

1. register a controlled `IInputConsumer`;
2. prove one-axis and diagonal movement;
3. prove Grab and Interact down/up edges;
4. prove Ready/Start;
5. identify and prove throw/drop semantics;
6. add command expiry and forced release;
7. measure candidate control rates;
8. run the input soak test;
9. close Phase C only after the evidence is logged; then
10. begin Phase D reset and time-scale measurement.

# 21. Component and term register

## 21.1 Orders and groups

- `CGroupMealPhase { MenuPhase Phase; }`
- `CWaitingForItem` dynamic buffer: actual per-order entries and satisfaction state
- `CRequestItemOf { Entity Group; }`
- `CSatisfyAnyOrder`: tag property
- `CAssignedTable { Entity Table; }`

## 21.2 Tables

- `CTableSet { bool IsWaitingTable; int ChairCount; }`
- `CTablePlace { CPosition SeatPosition; Vector3 TablePosition; Entity Chair; }`

Do not use the obsolete/non-existent names `CApplianceTable` or `CApplianceChair` for this build.

## 21.3 Day, time, readiness, and failure

- `CPlayersReadyToStart { bool Ready; }`
- `SDay { int Day; }`
- `STime { float TimeOfDay; float TimeOfDayUnbounded; float SecondsSinceDayBegan; float DayLength; bool ForcePause; }`
- `SKitchenStatus.RemainingLives`
- `SGameOver` with `LossReason`

## 21.4 Economy and shop

- `SMoney { int Amount; }`
- `CMoneyTrackEvent { int Identifier; int Amount; }`
- `CApplianceBlueprint { int Appliance; bool IsCopy; }`
- `CForSale { int Price; }`
- `CShopRerollRequest`: tag request

## 21.5 Layout and items

- `CLayoutRoomTile { Vector3 Position; int RoomID; RoomType Type; bool HasFeature; Reachability Reachability; }`
- `CLayoutInfo { Entity Layout; int Setting; Seed Seed; }`
- `ItemList { FixedListInt64 Components; int Size; }`
- `OccupancyLayer`: Default, Wall, Floor, Ceiling
- `InteractionType`: Look, Grab, Act, Notify

## 21.6 Mess and movement effects

- `CPlayerDirtyShoes { float TimeUntil; int MessID; }`
- `CSlowPlayer { float Radius; float Factor; }`
- `ConstantMess` uses `STimeTracker` for its event-specific interval; ordinary mess creation requires further inspection.

## 21.7 Input

- `IInputConsumer.TakeInput(int player_id, InputState state)`
- `LocalInputSourceConsumers.Consumers`

# 22. Repository and configuration

Recommended repository shape:

```text
plateup-agent/
  bridge/
    Components/
    Queries/
    Input/
    Transport/
    Tests/
  schemas/
    observation/obs_0.1.json
    action/act_0.1.json
    protocol/bridge_0.1.json
  python/
    env/
    data/
    motor/
    surrogate/
    planner/
    capability/
    evaluation/
  scenarios/
    practice/
    regression/
    evaluation/
  docs/
    observation-schema.md
    action-schema.md
    component-register.md
    determinism-report.md
    evidence-log.md
  runs/
    manifests/
    metrics/
  video/
    overlays/
    run-index/
```

Configuration must separate:

- game/build identity;
- bridge transport;
- control frequency;
- time scale;
- observation/action schema;
- scenario/reset method;
- motor checkpoint;
- capability registry version;
- surrogate version;
- reward configuration; and
- evaluation partition.

# 23. Risk register

## R1 - Input consumer does not provide authoritative control

**Impact:** blocks the entire learned-action programme.  
**Mitigation:** system-order inspection, input echo, controlled single-source tests, then component/Harmony contingency only if required.  
**Stop rule:** do not build higher-layer training until primitive control is reliable.

## R2 - Real-game throughput is too low

**Impact:** planner training becomes infeasible.  
**Mitigation:** mandatory semi-MDP surrogate; measure reset cost; accelerate only after fidelity tests; calibrate options from real trials.

## R3 - Surrogate exploits model error

**Impact:** high simulated performance fails in game.  
**Mitigation:** uncertainty penalties, held-out calibration, domain randomisation of option outcomes, regular real validation, top-candidate-only real testing.

## R4 - Observation becomes a legality oracle

**Impact:** compromises the experiment and increases brittle C# logic.  
**Mitigation:** factual component fields only; no action masks for gameplay legality; audit schema before freeze.

## R5 - Entity identity is unstable

**Impact:** group/order/table associations silently corrupt.  
**Mitigation:** index plus version, lifecycle tests, no cross-run entity assumptions.

## R6 - Wiki-derived constants are wrong or damaged

**Impact:** invalid recipes, timings, or rewards.  
**Mitigation:** live GameData/process registry and controlled probes outrank the knowledge base.

## R7 - Reward hacking

**Impact:** apparent learning without useful restaurant play.  
**Mitigation:** explicit anti-hacking suite, event deduplication, start deadline, real outcome evaluation.

## R8 - Scope collapse

**Impact:** years of work hidden inside one "full agent" milestone.  
**Mitigation:** independent Project 1 and Project 2 publishable endpoints; later capabilities get separate contracts.

# 24. Definition of done

## 24.1 Phase C done

Primitive control is reliable, acknowledged, non-sticky, and passes the soak test.

## 24.2 Project 1 done

The agent:

- observes through frozen structured state;
- starts the day itself;
- uses learned motor control for every gameplay input;
- completes the declared meal, customer, and dish loops;
- attempts Day 1 without human rescue;
- meets the predeclared evaluation threshold; and
- produces a reproducible evidence bundle with typical results.

## 24.3 Project 2 done

The agent selects a valid layout from a defined search space, physically constructs it, and completes evaluation services on held-out layouts at the declared threshold. The chosen layout is scored with the actual policy/capability model and verified in real game.

## 24.4 Full vision done

The system autonomously handles setup, preparation, service, supported cards, purchases, research, automation, menu changes, and the declared run endpoint, with each capability evaluated separately and together.

# Appendix A. `obs_0.1` freeze checklist

- [ ] Schema ID and semantic version present.
- [ ] Steam build and bridge hash present.
- [ ] Snapshot sequence and tick boundary documented.
- [ ] Units and coordinate system documented.
- [ ] Entity index/version separated.
- [ ] Player, layout, holder, item, process, group, order, table, economy, phase, time, and termination groups documented.
- [ ] Enum numeric mappings captured from the pinned build.
- [ ] Missing component semantics defined.
- [ ] No future information.
- [ ] No synthetic affordance or gameplay action mask.
- [ ] `t` semantics documented.
- [ ] `is_bad` interpretation documented with raw process fallback.
- [ ] Fire field marked unverified until a valid hazard probe.
- [ ] Golden trace stored with expected field transitions.
- [ ] Backward/forward compatibility policy documented.

# Appendix B. Phase C acceptance script

Run in a controlled Practice scenario:

1. handshake and verify build/schema;
2. acquire control of the intended player;
3. apply each movement axis value independently;
4. apply diagonals and measure normalisation;
5. press and release Grab for one tick, then held durations;
6. press and release Interact/Act;
7. press and release Ready;
8. perform movement plus interaction;
9. verify throw/drop intent mapping;
10. expire a command while every button is held;
11. disconnect while moving;
12. pause and change phase while moving;
13. reset and ensure no prior input leaks;
14. test at each candidate policy frequency;
15. repeat with other local input sources disabled and enabled as a diagnostic;
16. run 100,000 random but bounded commands; and
17. archive logs, hashes, faults, and the acceptance summary.

# Appendix C. Provenance notes

This revision uses four evidence classes:

- **Runtime telemetry supplied with the request:** customer lifecycle, order visibility, partial satisfaction, patience resets, time-bar behaviour, process-risk observations, placement observations, and current observation coverage.
- **Assembly/ECS findings supplied with the request:** component, buffer, singleton, enum, layout, shop, holder, and input-consumer types.
- **PlateUp AI Knowledge Base Stable 1.4.3:** mechanics context and candidate values, treated as secondary when not independently verified.
- **Engineering review supplied with the request:** ECS-first bridge, input-risk focus, semi-MDP surrogate, Practice reset economics, automatic goal labelling, per-axis movement, determinism gate, reward-hack additions, wall-clock budgets, and project sequencing.

The document deliberately rejects the knowledge base's recommendation for a required per-tick affordance field. Factual component fields remain; a computed legality oracle does not.
