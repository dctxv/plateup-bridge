# Demonstration schema `demo_0.1`

**Status:** live smoke verified 2026-07-28
**Pinned game:** PlateUp `1.4.3-FF8F`  
**Bridge:** `0.3.0`  
**Protocol:** `1`  
**Observation schema:** `obs_0.1`  
**Action schema:** `act_0.1`

## Purpose

The recorder captures the human player's native `InputState` through
`IInputConsumer.TakeInput(int player_id, InputState state)`. It records the
state before the normal `InputSource` path sends it to the game and always
returns `InputConsumerState.NotConsumed`, so recording does not intentionally
change or block gameplay.

Demonstrations and observations share the existing newline-delimited JSON pipe
and one file. A recording contains `manifest`, `hello`, `dict`, `obs`,
`demo_status`, and `demo_input` frames.

## Recording contract

- Bridge override must remain **off**.
- PlateUp must be focused while demonstrating. The game replaces native device
  input with neutral state before invoking consumers when it is unfocused.
- One Python client may own the pipe at a time.
- The Python recorder enables capture with an internal `demo_control` message.
- A monotonically increasing `seq` detects dropped demo frames.
- `outbound_frames_dropped` supplies the transport-backpressure diagnostic.

## `hello` addition

| Field | Type | Value |
|---|---|---|
| `demo_schema` | string | `"demo_0.1"` |

## `demo_status`

Emitted when Unity processes a recorder control message.

| Field | Type | Meaning |
|---|---|---|
| `kind` | string | `"demo_status"` |
| `demo_schema` | string | `"demo_0.1"` |
| `enabled` | bool | Whether native input capture is active. |
| `tick` | int | Current bridge simulation tick. |

## `demo_input`

One frame per native local-player input update while recording is active and
PlateUp has focus.

| Field | Type | Meaning |
|---|---|---|
| `kind` | string | `"demo_input"` |
| `demo_schema` | string | `"demo_0.1"` |
| `seq` | int | Recording-local monotonic sequence. |
| `tick` | int | Most recently entered bridge simulation tick. |
| `unity_frame` | int | `UnityEngine.Time.frameCount`. |
| `real_time` | float | `Time.realtimeSinceStartup`, seconds. |
| `player` | int | Native local player ID. |
| `move_x` | float | Raw `InputState.Movement.x`. |
| `move_y` | float | Raw `InputState.Movement.y`. |
| `interact` | int | `InteractAction`. |
| `grab` | int | `GrabAction`. |
| `secondary1` | int | `SecondaryAction1`. |
| `secondary2` | int | `SecondaryAction2`. |
| `stop` | int | `StopMoving`. |
| `menu_trigger` | int | Pause/menu trigger. |
| `menu_up` | int | Menu-up state. |
| `menu_down` | int | Menu-down state. |
| `menu_left` | int | Menu-left state. |
| `menu_right` | int | Menu-right state. |
| `menu_select` | int | Menu-confirm state. |
| `menu_cancel` | int | Menu-cancel state. |
| `request` | int | Raw `GameStateRequest`. |

### Button-state mapping

| Value | `ButtonState` |
|---:|---|
| 0 | Up |
| 1 | Released |
| 2 | Held |
| 3 | Pressed |
| 4 | Consumed |

### Request mapping

| Value | `GameStateRequest` |
|---:|---|
| 0 | None |
| 1 | InLocalMenu |
| 2 | Disconnect |
| 3 | QuitSection |
| 4 | InstantJoin |
| 5 | KickUser |
| 6 | StartPractice |
| 7 | QuitToLobby |

## Alignment

`tick` aligns native inputs to the nearest observation interval. Native input is
sampled at Unity/render cadence while observations are sampled from the
simulation group, so multiple input frames may share one bridge tick and many
input frames normally fall between two observation snapshots.

`unity_frame` preserves render ordering and `real_time` supplies an unscaled
clock. Training preprocessing must not assume one input frame per observation.

Held-item, process, customer, order, and other changes come from interleaved
`obs` frames. Interaction/goal segmentation is a later derived-data step and
must preserve the raw file.

The consumer can receive frames from more than one local device source,
including a neutral device that has not joined the restaurant. A demonstration
player is considered active when it emits movement, a non-Up button, or a
non-None request. Active IDs must occur in `obs.players[].id`; neutral unmatched
sources may remain in the raw file and should be excluded during training
preprocessing.

## Commands

```powershell
python python\demo_record.py record runs\demos\smoke.jsonl --recipe smoke
python python\demo_record.py verify runs\demos\smoke.jsonl
```

The verifier requires valid provenance/schema frames, at least two
observations, at least 30 native input frames, an enabled status, no sequence
gaps, sequence numbering from 1, valid movement/button/request values, movement,
Pressed and Released edges, F9 override off throughout, and overlapping
demonstration/observation tick ranges. It also requires every active native
input player to be present in the observation stream.

## Known limitations

- Raw device input is unavailable to `IInputConsumer` while PlateUp is
  unfocused.
- The live smoke passed, but matched recipe demonstrations have not yet been
  benchmarked.
- Direct entity-interaction labels are not separate events yet. They will be
  derived by aligning input edges with observation changes and validated before
  recipe demonstrations are accepted.
- Restaurant gameplay is the initial acceptance scope; menu-consumer priority
  requires separate verification.
