
## Phase D -- agent-initiated day start -- 2026-07-28 15:50

- day before: **0**, seconds before: **0.0**
- day started: **NO**
- verdict: FAIL -- Ready did not start service

## Phase D -- agent-initiated day start -- 2026-07-28 16:13

- day before: **0**, seconds before: **0.0**
- day started: **NO**
- verdict: FAIL -- Ready did not start service

## Phase D -- agent-initiated day start -- 2026-07-28 16:14

- day before: **0**, seconds before: **0.0**
- day started: **NO**
- verdict: FAIL -- Ready did not start service

## Phase D -- agent-initiated day start -- 2026-07-28 16:36

- day before: **0**, seconds before: **0.0**
- day started: **yes in 2.0s**
- verdict: PASS

## Phase D -- request probe: StartPractice -- 2026-07-28 16:37

### `StartPractice`
- frames after pulse: **253**
- state changes: **0**
- tuple is `(in_restaurant, day, paused, input_captured)`
- destructive requests may be converted to `None` by the mod's request safety whitelist

## Phase D -- request probe: StartPractice -- 2026-07-28 16:38

### `StartPractice`
- frames after pulse: **300**
- state changes: **0**
- tuple is `(in_restaurant, day, paused, input_captured)`
- destructive requests may be converted to `None` by the mod's request safety whitelist

## Phase D -- request probe: StartPractice -- 2026-07-28 17:08

### `StartPractice`
- frames after pulse: **300**
- state changes: **0**
- tuple is `(in_restaurant, day, paused, input_captured)`
- destructive requests may be converted to `None` by the mod's request safety whitelist

## Phase D -- request probe: StartPractice -- 2026-07-28 17:08

### `StartPractice`
- frames after pulse: **300**
- state changes: **0**
- tuple is `(in_restaurant, day, paused, input_captured)`
- destructive requests may be converted to `None` by the mod's request safety whitelist

## Phase D -- request probe: StartPractice -- 2026-07-28 17:09

### `StartPractice`
- frames after pulse: **154**
- state changes: **0**
- tuple is `(in_restaurant, day, paused, input_captured)`
- destructive requests may be converted to `None` by the mod's request safety whitelist

## Phase D -- termination -- 2026-07-28 17:11

- frames observed: **3719**
- lives sequence: **[1]**
- SGameOver observed: **False**
- loss_reason: **None**
- verdict: NOT OBSERVED

`CheckGameOverFromLife` uses `LossReason.Patience` when lives reach zero unless practice/rescue rules suppress the normal failure path.

## Phase D -- request probe: StartPractice -- 2026-07-28 17:20

### `StartPractice`
- frames after pulse: **300**
- state changes: **1**
  confirmed: (True, 0, False, False) -> (True, 1, False, False)
- tuple is `(in_restaurant, day, paused, input_captured)`
- StartPractice and QuitSection include their required MenuSelect confirmation

## Phase D -- termination -- 2026-07-28 17:20

- before: `day=1 t=0/100 $=0 lives=1 over=False groups=1`
- frames observed: **1**
- SGameOver observed: **True**
- restaurant section closed: **False**
- loss_reason: **2**
- verdict: PASS

## Phase D -- reset throughput -- 2026-07-28 17:27

- **all resets failed** — StartPractice semantics did not match the assumed reset path
