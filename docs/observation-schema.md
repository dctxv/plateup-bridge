# Observation schema `obs_0.1`

**Status:** frozen  
**Pinned build:** PlateUp 1.4.3-FF8F, Unity 2020.3.48f1, Steam public stable  
**Bridge:** 0.3.0
**Transport:** newline-delimited JSON over `\\.\pipe\plateup_bridge`  
**Rate:** every 6th simulation tick, approximately 10 Hz

Any change to a field's name, type, units, or meaning requires a new schema
version. Additive optional fields do not.

---

## Design rule

**The bridge emits facts, not answers.**

It reports what an entity contains, accepts, blocks, or is currently doing,
because those are component-derived facts a human can also see. It does **not**
compute `can_grab`, `can_place`, `best_target`, or an action mask over gameplay
legality. Learning what may be placed where is part of the task.

---

## Message kinds

### `hello` — once, on connect

| Field | Type | Notes |
|---|---|---|
| `kind` | `"hello"` | |
| `protocol` | int | Wire protocol, currently `1`. |
| `bridge_version` | string | Mod semantic version. |
| `obs_schema` | string | `"obs_0.1"`. |
| `act_schema` | string | `"act_0.1"`. |
| `demo_schema` | string | `"demo_0.1"`; native-input demonstration frames. |
| `session_id` | string | New GUID per game launch. |
| `game_version` | string | `Application.version`. |
| `mod_hash` | string | Full lowercase hexadecimal SHA-256 of the loaded/deployed mod DLL. |
| `unity` | string | `Application.unityVersion`. |

The client validates `protocol`, `obs_schema`, and `act_schema` and refuses to
proceed on mismatch. Every stored trajectory must carry this block.

### `dict` — once, on connect

```json
{
  "kind": "dict",
  "protocol": 1,
  "appliances": {"id": "name"},
  "items": {"id": "name"},
  "processes": {"id": "name"}
}
```

Sent once so per-tick frames can carry bare integer game-data IDs. JSON object
keys are strings. IDs are stable within a pinned build and must be re-read after
any game update.

| Field | Type | Notes |
|---|---|---|
| `kind` | `"dict"` | |
| `protocol` | int | Wire protocol, currently `1`. |
| `appliances` | object | Appliance game-data ID to name. |
| `items` | object | Item game-data ID to name. |
| `processes` | object | Process game-data ID to name. |

### `obs` — the observation

The remaining sections define the repeated observation frame.

### Action frame `act_0.1`

Python sends one newline-delimited action object. All control booleans are
held-down states; the mod derives `Pressed`, `Held`, and `Released` edges.

| Wire field | Python argument | Type | Meaning |
|---|---|---|---|
| `Tick` | automatic | int | Most recently received observation tick. |
| `CommandId` | automatic | int | Connection-local monotonically increasing receipt ID. |
| `MoveX` | `move[0]` | float | World-space x movement and aim. |
| `MoveY` | `move[1]` | float | World-space z movement and aim. |
| `Grab` | `grab` | bool | Grab/place held state; placement remains contextual. |
| `Interact` | `interact` | bool | Act/chop/wash held state. |
| `Secondary1` | `secondary1` | bool | Secondary action 1; empirical role still under test. |
| `Secondary2` | `secondary2` | bool | Notify interaction. |
| `StopMoving` | `stop` | bool | Rotate/aim without translational movement. |
| `Ready` | `ready` | bool | Semantic alias for `SecondaryAction1`/`Controls.Interact3`, consumed by `StartDayWarningView`. |
| `MenuSelect` | `menu_select` | bool | Confirm the current menu selection. |
| `MenuCancel` | `menu_cancel` | bool | Cancel/back. |
| `MenuUp` | `menu_up` | bool | Menu navigation. |
| `MenuDown` | `menu_down` | bool | Menu navigation. |
| `MenuLeft` | `menu_left` | bool | Menu navigation. |
| `MenuRight` | `menu_right` | bool | Menu navigation. |
| `Request` | `request` | string | `GameStateRequest` name. |

The mod deliberately accepts only `None`, `InLocalMenu`, `StartPractice`,
`InstantJoin`, and `QuitSection`. `StartPractice` and `QuitSection` open
confirmation popups; pulse `MenuSelect` after `input_captured` becomes true.
`QuitToLobby`, `Disconnect`, `KickUser`, and unknown requests are converted to
`None`.

---

## Entity identity

Emitted as the string **`"index:version"`**, for example `"1542:3"`.

Unity recycles entity indices after destruction, so an index alone is not a
stable identifier: a destroyed customer group's index can reappear as an
unrelated entity within the same day. The pair is unique within one session.

**Never compare entity IDs across sessions.**

Fields carrying an entity ID are `e`, `table`, `group`, and the members of
`stored`.

## Coordinates and units

- `x` and `z` are Unity world coordinates. `y` is not emitted; PlateUp is
  functionally two-dimensional and player `y` is pinned by the movement system.
- `rot` is Y-axis Euler degrees. The zero direction has not been verified.
- Positions are floats and are not grid-aligned. Grid derivation belongs in the
  encoder, not the bridge.
- Times are seconds unless explicitly described otherwise.
- `progress` is in the range 0–1.
- Floats are serialized with at most three decimal places.

---

## Global fields

| Field | Type | Source | Notes |
|---|---|---|---|
| `kind` | string | | Always `"obs"`. |
| `protocol` | int | | Currently `1`. |
| `tick` | int | bridge | Monotonic; increments every simulation tick. |
| `in_restaurant` | bool | `SLayout` singleton exists | False in HQ and menus. |
| `practice_mode` | bool | `SPracticeMode` singleton exists | True only inside an active Practice session. |
| `paused` | bool | `Time.IsPaused` | |
| `override` | bool | bridge | True when bridge input override is enabled. |
| `input_captured` | bool | `CCaptureInput` without `CCapturePassthrough` | A menu owns input. |
| `ack_command` | int | bridge | Most recent `CommandId` accepted by the input system. |
| `cmds_applied` | int | bridge | Commands selected for application since this pipe connection began. |
| `cmds_dropped` | int | bridge | Commands superseded by a newer command in the same simulation tick. |
| `outbound_frames_dropped` | int | bridge | Frames discarded because the outbound pipe queue exceeded its backpressure limit; cumulative for the game process. |
| `game_speed` | float | `SGameTime.GameSpeed` | Debug/measurement multiplier; normally `1`. |
| `game_total_time` | float | `SGameTime.TotalTime` | Scaled game clock; continues in Practice even though `seconds_elapsed` does not. |
| `real_total_time` | float | `SGameTime.RealTotalTime` | Unscaled game-process clock. |
| `day` | int | `SDay.Day` | Increments at service start; preparation carries the previous day's number. |
| `time_of_day` | float | `STime.TimeOfDay` | |
| `time_unbounded` | float | `STime.TimeOfDayUnbounded` | Arrival bar; ≥1 means no new arrivals, not that the day ended. |
| `seconds_elapsed` | float | `STime.SecondsSinceDayBegan` | |
| `day_length` | float | `STime.DayLength` | |
| `money` | int | `SMoney.Amount` | |
| `lives` | int | `SKitchenStatus.RemainingLives` | Absent outside a run. |
| `game_over` | bool | `SGameOver` singleton exists | |
| `loss_reason` | int | `SGameOver.Reason` | `LossReason`; only present when `game_over` is true. |
| `start_day_warnings` | object | `SStartDayWarnings` | Preparation checklist; absent outside the start-day warning phase. |

`day`, time fields, `money`, and `lives` are omitted if their singleton is not
present. Phase detection requires combining fields: `day` alone cannot
distinguish preparation from service.

The three command-receipt fields (`ack_command`, `cmds_applied`, and
`cmds_dropped`) reset on every pipe connection. Clients send monotonically
increasing `CommandId` values starting at 1, and can calculate pending work as:

```text
unacked = max(0, last_sent_command_id - ack_command)
```

`cmds_dropped` counts valid commands drained from the inbound queue but
superseded before the Unity tick applied one. It does not count malformed JSON.
`outbound_frames_dropped` separately reports observation or dictionary frames
discarded because a client stopped reading quickly enough.

### `start_day_warnings`

This object exposes the game's preparation checklist. Warning values use
`WarningLevel`: `0 Unknown`, `1 Safe`, `2 Warning`, `3 Error`.

| Field | Type | Source |
|---|---|---|
| `players_ready` | bool | `CPlayersReadyToStart.Ready` |
| `popups_open` | int | `SStartDayWarnings.PopupsOpen` |
| `selling_required_appliance` | int | `SStartDayWarnings.SellingRequiredAppliance` |
| `table_size` | int | `SStartDayWarnings.TableSize` |
| `players_not_ready` | int | `SStartDayWarnings.PlayersNotReady` |
| `post_unopened` | int | `SStartDayWarnings.PostUnopened` |
| `more_than_one_table` | int | `SStartDayWarnings.MoreThanOneTable` |
| `players_in_crane_mode` | int | `SStartDayWarnings.PlayersInCraneMode` |

`CCapturedUserInput` contains only player entity references. `GatherInputs`
follows each reference and reads that player's `CInputData`. The start-day view
then toggles consent when `SecondaryAction1` is `Pressed`; it does not consume
`MenuTrigger`.

---

## `players[]`

| Field | Type | Source | Notes |
|---|---|---|---|
| `id` | int | `CPlayer.ID` | PlateUp player ID, not an ECS entity ID. |
| `x`, `z`, `rot` | float | `CPosition` | |
| `held` | object or null | `CItemHolder.HeldItem` | Full item object, or explicit `null`. |
| `captured` | bool | `CInputData.IsCaptured` | Omitted when `CInputData` is absent. |
| `dirty_shoes` | float | `CPlayerDirtyShoes.TimeUntil` | Only present when greater than zero. |

---

## `appliances[]`

| Field | Type | Source | Notes |
|---|---|---|---|
| `e` | entity ID | | |
| `aid` | int | `CAppliance.ID` | Resolve through `dict.appliances`. |
| `layer` | int | `CAppliance.Layer` | `OccupancyLayer`. |
| `x`, `z`, `rot` | float | `CPosition` | |
| `held` | object | `CItemHolder.HeldItem` | Absent if empty. |
| `provides` | int | `CItemProvider.ProvidedItem` | Ingredient source. |
| `available` | int | `CItemProvider.Available` | Negative appears to mean infinite; unverified. |
| `maximum` | int | `CItemProvider.Maximum` | |
| `is_table` | true | `CTableSet` present | |
| `chairs` | int | `CTableSet.ChairCount` | |
| `waiting_table` | bool | `CTableSet.IsWaitingTable` | |
| `accepts_any` | bool | `CItemHolderFilter.AllowAny` | |
| `accepts_cat` | int | `CItemHolderFilter.Category` | `ItemCategory` bit field. |
| `accepts_only` | int | `CItemHolderOnlySpecificItem.ItemID` | |
| `stored` | entity ID array | `CItemStored` buffer | Cupboards, dish racks, and other storage. |
| `on_fire` | true | `CIsOnFire` | Untested; see Known gaps. |
| `broken` | true | `CIsBroken` | Untested. |
| `inactive` | true | `CIsInactive` | Untested. |

Conditional fields are omitted when their component is absent. The appliance
count is not constant during service: it has varied from approximately 95–101,
probably because chair appliances are spawned and destroyed as groups arrive
and leave. That explanation is not yet confirmed by name-difference logging.

The holder-filter fields are component facts, not a complete placement-legality
oracle. Capacity, interaction state, and recipe systems may impose additional
constraints.

---

## Items

Item objects appear as `players[].held`, `appliances[].held`, and
`loose_items[]`.

| Field | Type | Source | Notes |
|---|---|---|---|
| `e` | entity ID | | |
| `iid` | int | `CItem.ID` | Resolve through `dict.items`. |
| `cat` | int | `CItem.Category` | `ItemCategory`. |
| `partial` | true | `CItem.IsPartial` | Omitted when false. |
| `items` | int array | `CItem.Items` | Composite contents; a plated steak is a plate containing component IDs. |
| `process` | int | `CItemUndergoingProcess.Process` | Resolve through `dict.processes`. |
| `progress` | float | `CItemUndergoingProcess.Progress` | 0–1. |
| `is_bad` | bool | `CItemUndergoingProcess.IsBad` | Lookahead flag; see below. |
| `rate` | float | `CItemUndergoingProcess.CurrentChange` | |
| `x`, `z` | float | `CPosition` | Present only on `loose_items`. |

### `progress` resets at every stage

Cooking is a chain of item transitions, not one scalar. Observed:

```text
Meat:Cook@100%
  → Steak-Rare:Cook@1%
  → …
  → Steak-Medium:Cook@100%
  → Steak-Well-done:Cook@0%
  → …
  → Steak-Burned
```

The meaningful state is `(iid, progress)`. Progress alone reaches 100% multiple
times without identifying the last safe transition.

### `is_bad` is a lookahead flag

It means the transition currently running leads somewhere worse, not that the
item is already ruined. For steak it becomes true at Well-done—still
servable—because the next transition produces Burned.

This is an observed interpretation rather than a game-stated contract. Raw
`process` and `progress` remain available so it can be retested. Chop and wash
have not yet been checked for the flag.

### Partial process progress persists

Observed: with two plates in a sink, one plate remained at `Clean@8%` while the
other completed. Progress is stored on the item and resumes; it does not decay.

### `loose_items` is normally empty

PlateUp does not permit placing portable items on the bare floor. This list
covers only items that are neither held (`CHeldBy`) nor stored (`CStoredBy`), so
it normally contains only in-flight or transient items.

---

## `groups[]`

| Field | Type | Source | Notes |
|---|---|---|---|
| `e` | entity ID | | |
| `x`, `z` | float | `CPosition` | |
| `patience_active` | bool | `CPatience.Active` | |
| `patience_left` | float | `CPatience.RemainingTime` | Seconds. |
| `patience_total` | float | `CPatience.StartTime` | Seconds; resets on phase change. |
| `patience_reason` | int | `CPatience.Reason` | `PatienceReason`. |
| `patience_rate` | float | `CPatience.LastUpdateRate` | |
| `meal_phase` | int | `CGroupMealPhase.Phase` | `MenuPhase`. |
| `table` | entity ID | `CAssignedTable.Table` | Absent before seating and after completion. |
| `size` | int | `CGroupMember` buffer length | |
| `orders` | array | `CWaitingForItem` buffer | See below. |

The Python layer derives:

```text
patience_frac = patience_left / patience_total
```

with a denominator fallback of `1.0`.

### `orders[]` — `CWaitingForItem`

| Field | Type | Notes |
|---|---|---|
| `iid` | int | Requested item. |
| `member` | int | Person within the group. |
| `satisfied` | bool | Whether this item has been delivered. |
| `is_side` | bool | Course classification. |
| `reward` | int | Payment for this item. |
| `dirt` | int | Item produced after eating; omitted when zero. |
| `extra` | int | Condiment request; only when `ExtraRequested`. |
| `extra_done` | bool | Whether the extra has been satisfied. |
| `by_sharer` | true | Present when satisfied by a shared dish. |

Orders appear late. The buffer populates at `WaitForFood`, after `Service`
completes—not at seating. A planner cannot know a specific group's order in
advance. It may prepare generic inventory, but it must not behave as if a hidden
order is known.

Partial delivery buys time. The first delivery moves the group from
`WaitForFood` to `GetFoodDelivered` and resets patience to 100%.

---

## `customers[]`

| Field | Type | Source | Notes |
|---|---|---|---|
| `e` | entity ID | | |
| `x`, `z` | float | `CPosition` | |
| `state` | int | `CCustomerState.CurrentState` | |
| `group` | entity ID | `CBelongsToGroup.Group` | |
| `idx` | int | `CBelongsToGroup.IndexInGroup` | |

---

## Collection ordering

`players`, `appliances`, `loose_items`, `groups`, and `customers` are sorted by
ECS entity index before serialization. This prevents list positions from
shuffling between frames. Nested buffers preserve their game-provided order.

---

## Enum mappings

Declaration order is from the pinned build. Numeric values for
`PatienceReason` and `MenuPhase` have been confirmed by observation; the other
mappings are declaration order and should be spot-checked before being relied
upon.

### `PatienceReason` — confirmed

| Value | Name | Observed as |
|---:|---|---|
| `0` | `Thinking` | Between courses and after seating. |
| `1` | `Eating` | After all orders are satisfied. |
| `2` | `Seating` | On arrival, before a table. |
| `3` | `Service` | Waiting to order. |
| `4` | `WaitForFood` | Orders visible, nothing delivered. |
| `5` | `GetFoodDelivered` | After the first delivery. |
| `6` | `Queue` | Queue; weather-independent variant. |
| `7` | `QueueInDarkness` | Queue under darkness. |
| `8` | `QueueInRain` | Queue in rain. |
| `9` | `QueueInSnow` | Queue in snow. |

Queue variants encode weather in the same field.

### `MenuPhase` — confirmed

| Value | Name |
|---:|---|
| `0` | `Starter` |
| `1` | `Main` |
| `2` | `Dessert` |
| `3` | `Side` |
| `4` | `Complete` |

`Complete` is a real terminal state. A group may pass through
`Dessert/Thinking` and decline to order.

### `CCustomerState.State`

| Value | Name |
|---:|---|
| `0` | `Normal` |
| `1` | `Queue` |
| `2` | `AtTable` |

`Normal` appears to cover both walking in and leaving; that interpretation is
not yet verified.

### `OccupancyLayer`

| Value | Name |
|---:|---|
| `0` | `Default` |
| `1` | `Wall` |
| `2` | `Floor` |
| `3` | `Ceiling` |

### `ItemCategory` — bit field

| Value | Name |
|---:|---|
| `0` | `Generic` |
| `1` | `Crates` |
| `2` | `Documents` |
| `4` | `MenuChoice` |
| `8` | `LayoutChoice` |
| `16` | `ProviderOnly` |
| `32` | `Plant` |
| `64` | `Contract` |
| `128` | `NonLoadoutCrate` |

Multiple non-zero flags may be combined.

### `InteractionType`

| Value | Name |
|---:|---|
| `0` | `Look` |
| `1` | `Grab` |
| `2` | `Act` |
| `3` | `Notify` |

### Process IDs

`ProcessType` is not an enum. `CItemUndergoingProcess.Process` is an integer key
into the `Process` ScriptableObject registry, resolved through
`dict.processes`—17 entries on the pinned build. Do not hardcode process IDs.

---

## Python-resolved fields

`ObservationClient` preserves the original frame in `World.raw` and adds:

| Object | Derived field | Source |
|---|---|---|
| appliance | `name` | `aid` through `dict.appliances`. |
| appliance | `layer_name` | `layer` through `OCCUPANCY_LAYER`. |
| appliance | `provides_name` | `provides` through `dict.items`. |
| appliance | `accepts_only_name` | `accepts_only` through `dict.items`. |
| item | `name` | `iid` through `dict.items`. |
| item | `component_names` | `items` through `dict.items`. |
| item | `process_name` | `process` through `dict.processes`. |
| group | `patience_frac` | `patience_left / patience_total`. |
| group | `patience_reason_name` | `PatienceReason` mapping. |
| group | `meal_phase_name` | `MenuPhase` mapping. |
| order | `name` | `iid` through `dict.items`. |
| order | `dirt_name` | `dirt` through `dict.items`. |
| order | `extra_name` | `extra` through `dict.items`. |
| customer | `state_name` | `CCustomerState.State` mapping. |

Convenience helpers include `me`, `tables`, `seconds_remaining`,
`accepting_customers`, `by_name`, `nearest`, `outstanding_orders`, `cooking`,
and `at_risk`.

---

## Fairness

Deliberately excluded:

- `CScheduledCustomer`: future arrival times and group sizes.
- Future blueprints, cards, and random outcomes.
- Computed gameplay legality or action masks.

Everything published is visible on screen or derivable from visible state.

---

## Known gaps

| Gap | Status |
|---|---|
| **Fire** | `on_fire` has never been observed. Burned food alone does not ignite; fire requires suitable equipment or misuse. |
| **Mess** | Floor dirt is not in the schema. The component still needs to be identified through `SpawnTableDirt` / `CreateNewMesses`. |
| **Failure** | `game_over` and `loss_reason` are implemented but have not yet been observed in a failed run. |
| **Rotation zero** | The world direction represented by `rot = 0` is unverified. |
| **Provider infinity** | The `available` convention for infinite providers is assumed, not confirmed. |
| **Appliance count** | It fluctuates during service; chair spawning is the current hypothesis, not a confirmed explanation. |
| **Layout tiles** | `CLayoutRoomTile` / `CLayoutInfo` are not emitted. They are needed for the grid encoder and layout validator. |
| **Blueprints** | Not emitted. |
| **`broken` / `inactive`** | Emitted but never observed. |

---

## Verification status

Verified across two hand-played days and one focused order session:

- Name dictionary resolution: 403 appliances, 420 items, 17 processes.
- Held-item tracking through pickup, plating, and dirty return.
- Cooking progress, stage transitions, and `is_bad`.
- Washing, including interrupted and resumed progress.
- Two and three concurrent groups without identity confusion.
- Full lifecycle: seating → thinking → service → wait-for-food →
  get-food-delivered → eating → complete → table released.
- Per-member order satisfaction.
- Patience reset on phase change.
- Table assignment and release.
- Money, day rollover, and real-time fields.

Everything listed under Known gaps remains unverified.

---

## Golden trace

The canonical target is:

```text
runs/golden/obs_0.1_day1.jsonl
```

It contains a hand-played day with `manifest` and `hello` records at the top.
The recording stops at `seconds_elapsed = 94.555` of a 100-second day, so it
covers the full customer lifecycle but not the final seconds of the day; see
`verified-successes.md` section 2.6. That is sufficient for schema regression
and insufficient for a recipe benchmark session. The canonical trace was
recorded with bridge `0.2.4`, session
`cf908a54f962475f8188e9ddd5b3f4b7`, and trace SHA-256
`5CB703978261E4178A0BA3FAE4E4D2C881819DA6AA30857E49D89424FCA74539`.
The prior bridge `0.2.0` trace is retained under
`runs/golden/archive/obs_0.1_day1_bridge020_20260728.jsonl`.

Replay the canonical trace through:

```powershell
python python\record.py --verify runs\golden\obs_0.1_day1.jsonl
```

The replay asserts that the confirmed lifecycle still parses and occurs in the
expected order.
