# Verified successes and acceptance outcomes

**Purpose:** permanent evidence ledger for PlateUp Bridge integration work.  
**Pinned game:** PlateUp `1.4.3-FF8F`  
**Unity:** `2020.3.48f1`  
**Protocol:** `1`  
**Observation schema:** `obs_0.1`  
**Action schema:** `act_0.1`

This file records features only after they have worked in the live game or
passed a saved replay/acceptance test. Failed and inconclusive gates are retained
separately so that later design decisions are not based on selective evidence.

## Recording rule

Every future verified result must include:

1. Date and local time.
2. Game, bridge, observation-schema, and action-schema versions.
3. Exact command or live procedure.
4. Numeric result and acceptance threshold where applicable.
5. A durable evidence artifact, or an explicit note that the evidence was a
   live terminal observation.
6. Any limitation that prevents the result from being a formal gate.

Do not replace a failed result with a later pass. Retain both and identify which
one is current. Do not call a quick sample a formal gate when the specified
sample count has not been reached.

---

## Current gate summary

| Area | Current result | Status |
|---|---|---|
| Mod build and deployment | Bridge `0.3.0` builds with zero warnings and the built/deployed DLL hashes match. Live load is pending restart. | PASS (build) |
| Named-pipe transport | Python connects, validates the handshake, receives the dictionary and observations, and sends acknowledged actions. | PASS |
| Observation dictionary | 403 appliances, 420 items, and 17 processes resolve successfully. | PASS |
| Canonical golden trace | Bridge `0.2.4`; 2,544 frames; full lifecycle and order transitions replay successfully. | PASS |
| Phase C control frequency | 10, 12, 15, and 20 Hz each achieved 8/8 arrivals with no overshoot. | PASS |
| Phase C command expiry | Latest run stopped with 0.00 units of post-expiry drift. | PASS |
| Phase C hard disconnect | 0.000 units of post-disconnect drift. | PASS |
| Agent-initiated day start | Ready/Interact3 started service in 2.0 seconds. | PASS |
| Start Practice | Request routing plus `MenuSelect` confirmation entered Practice. | PASS |
| Quit/termination | `QuitSection` plus confirmation produced `SGameOver`, loss reason `2`. | PASS |
| Paused observation liveness | Continuous observations while paused; `paused=True`; zero outbound drops. | PASS |
| Unfocused, unpaused operation | PlateUp continued accepting bridge control while PowerShell was the foreground window, including the 500-reset run. | PASS (functional) |
| Practice reset, quick sample | 3/3 and 20/20 successful reset cycles. | PASS (quick) |
| Practice reset, formal gate | 500/500 successful; median 3.281 s, p99 3.546 s. | PASS |
| 2x/3x motor fidelity | Arrival remained 100%, but distance/game-second differed by 28.5% and 51.4%. | FAIL |
| Minimized, unpaused operation | Observation stream and game simulation continued while PlateUp was minimized. | PASS (functional) |
| Golden trace on current bridge | Bridge `0.2.4` trace promoted to the canonical filename; prior `0.2.0` trace archived. | PASS |
| Runtime DLL provenance | Bridge `0.2.4` live handshake hash exactly matches the built/deployed DLL. | PASS |
| Native-input demonstration recorder | 9,334 native-input frames aligned with 854 observations; zero sequence gaps; active input player matched the observed player. | PASS (live smoke) |

---

## 1. Build, injection, and transport

### 1.1 Bridge `0.2.3` build and deployment

- **Date:** 2026-07-28
- **Command:** `dotnet build -c Release`
- **Result:** build succeeded with zero warnings and zero errors.
- **Built DLL SHA-256:**
  `D1E76400B332A5320466BBEBDBD697A0F04A3D3B6997A26602C3D9E06FD51734`
- **Deployment result:** the DLL under `bin/Release` and the DLL under the
  PlateUp `Mods/PlateUpBridge` directory had identical hashes.
- **Status:** PASS.

### 1.2 Mod injection and Harmony patching

- PlateUp injected `PlateUpBridge`.
- Player log reported `[BRIDGE] harmony patches applied`.
- Both bridge input and named-pipe systems started successfully.
- Manual and Python-driven movement confirmed the locomotion patch was active.
- **Status:** PASS.

### 1.3 Named-pipe connection

- Python receives `hello`, validates protocol/schema versions, then receives the
  dictionary and observation stream.
- Native Win32 pipe transport connects without the earlier
  `ERROR_PIPE_LISTENING`/Python file-layer failure.
- Command acknowledgements advance through `ack_command`.
- **Status:** PASS.

### 1.4 Name dictionary

- Appliances resolved: **403**
- Items resolved: **420**
- Processes resolved: **17**
- The dictionary parses as one newline-delimited JSON frame.
- **Evidence:** golden-trace replay output and live observer sessions.
- **Status:** PASS.

### 1.5 Bridge `0.2.4` provenance build

- **Date:** 2026-07-28
- **Command:** `dotnet build -c Release`
- **Result:** build succeeded with zero warnings and zero errors.
- **Built/deployed DLL SHA-256:**
  `A95958844EE81FD6515E7E93A3CD3FE5822A2B75D86D18192675E5ACECFEA1C4`
- Built and deployed hashes matched exactly.
- Runtime resolution now tries the loaded assembly location, assembly codebase,
  the Mods path derived from `Application.dataPath`, and the application base
  directory.
- The derived PlateUp Mods fallback existed at build verification time.
- **Status:** PASS for implementation, build, and deployment.

### 1.6 Bridge `0.2.4` live provenance

- **Date:** 2026-07-28
- **Command:** `python python\observe.py dump`
- **Session:** `cf908a54`
- **Live game:** `1.4.3-FF8F`
- **Live bridge:** `0.2.4`
- **Live `hello.mod_hash`:**
  `a95958844ee81fd6515e7e93a3cd3fe5822a2b75d86d18192675e5acecfea1c4`
- **Expected built/deployed SHA-256:**
  `a95958844ee81fd6515e7e93a3cd3fe5822a2b75d86d18192675e5acecfea1c4`
- Hashes matched exactly.
- The same connection received the complete 403-appliance, 420-item,
  17-process dictionary and parsed a valid observation.
- The observation confirmed the additive fields `practice_mode`, `game_speed`,
  `game_total_time`, `real_total_time`, and `outbound_frames_dropped`.
- Initial telemetry showed `game_speed=1`, scaled and real clocks equal at
  `0.744`, and zero outbound drops.
- **Status:** PASS. Runtime DLL provenance is closed.

### 1.7 Bridge `0.3.0` native-input recorder build

- **Date/time:** 2026-07-28 21:10 AEST
- **Game target:** PlateUp `1.4.3-FF8F`
- **Bridge:** `0.3.0`
- **Protocol / schemas:** `1` / `obs_0.1` / `act_0.1` / `demo_0.1`
- **Command:** `dotnet build -c Release`
- **Result:** build succeeded with zero warnings and zero errors.
- **Built/deployed DLL SHA-256:**
  `164A7AE4F2C796E3DB0D7D8F7622DAAE49450AD515EF0319E320F214996AF8D0`
- The DLL under `bin/Release` and the deployed DLL under
  `Mods/PlateUpBridge` had identical hashes.
- `python -m py_compile python\bridge.py python\demo_record.py` succeeded.
- The implementation registers an `IInputConsumer`, always returns
  `NotConsumed`, and carries native input and observations in the same JSONL
  recording.
- **Status:** PASS for implementation/build/deployment only.
- **Limitation:** PlateUp was still running the previous DLL. A full game
  restart and live smoke recording are required before the recorder itself can
  be marked PASS. This historical limitation was closed by section 2.4.

---

## 2. Observation and schema verification

### 2.1 Live state observation

The following were verified during hand-played sessions:

- Held item changes on pickup and legal placement/storage.
- Cooking, chopping, and washing progress updates.
- Process-stage transitions and `is_bad` state.
- Customer group and member identity remains stable within a session.
- Table assignment and release.
- Per-member outstanding orders and satisfaction.
- Patience reason and meal phase transitions.
- Money, remaining lives, terminal reason, and day state.
- Start-day warning checklist.

The detailed field contract and enum mappings remain in
[observation-schema.md](observation-schema.md).

### 2.2 Historical bridge `0.2.0` golden trace replay

- **Trace:** `runs/golden/obs_0.1_day1.jsonl`
- **Recorded bridge:** `0.2.0`
- **Verification command:**
  `python python/record.py --verify runs/golden/obs_0.1_day1.jsonl`
- **Verification date:** 2026-07-28
- **Frames parsed:** **5,454**
- **Customer groups:** **3**
- **Order entries:** **6,394**
- **Unsatisfied-to-satisfied transitions:** **5**
- **Frames with a table assignment:** **5,544**
- **Patience reasons observed:** seating, thinking, service, wait_for_food,
  get_food_delivered, eating.
- **Meal phases observed:** starter, main, complete.
- **Result:** `OK -- obs_0.1 parses and the confirmed lifecycle is intact`.
- **Status:** PASS for schema/parser regression.
- **Archive:** `runs/golden/archive/obs_0.1_day1_bridge020_20260728.jsonl`
- **Archived trace SHA-256:**
  `3F8687DE176A6803709C01C74EB56954502B617D57DBE89712C1FAAB70637CA8`
- This result remains as historical evidence and has been superseded as the
  canonical trace by section 2.3.

### 2.3 Canonical bridge `0.2.4` golden trace

- **Date:** 2026-07-28
- **Trace:** `runs/golden/obs_0.1_day1.jsonl`
- **Recording session:** `cf908a54f962475f8188e9ddd5b3f4b7`
- **Game:** PlateUp `1.4.3-FF8F`
- **Bridge:** `0.2.4`
- **Protocol / schemas:** `1` / `obs_0.1` / `act_0.1`
- **Runtime mod SHA-256:**
  `a95958844ee81fd6515e7e93a3cd3fe5822a2b75d86d18192675e5acecfea1c4`
- **Trace SHA-256:**
  `5CB703978261E4178A0BA3FAE4E4D2C881819DA6AA30857E49D89424FCA74539`
- **Verification command:**
  `python python/record.py --verify runs/golden/obs_0.1_day1.jsonl`
- **Frames parsed:** **2,544**
- **Customer groups:** **4**
- **Order entries:** **308**
- **Unsatisfied-to-satisfied transitions:** **3**
- **Frames with a table assignment:** **1,473**
- **Patience reasons observed:** seating, thinking, service, wait_for_food,
  eating.
- **Meal phases observed:** starter, main, dessert, complete.
- **Dictionary:** 403 appliances, 420 items, 17 processes.
- **Result:** `OK -- obs_0.1 parses and the confirmed lifecycle is intact`.
- **Promotion procedure:** the previous canonical trace was moved to the archive
  path above; the verified candidate was moved to the canonical filename; the
  canonical file was then verified again.
- **Status:** PASS. The bridge `0.2.4` trace is the canonical `obs_0.1`
  regression artifact.

### 2.4 Bridge `0.3.0` native-input demonstration smoke

- **Date/time:** 2026-07-28 21:32 AEST
- **Game:** PlateUp `1.4.3-FF8F`
- **Bridge:** `0.3.0`
- **Protocol / schemas:** `1` / `obs_0.1` / `act_0.1` / `demo_0.1`
- **Runtime mod SHA-256:**
  `164a7ae4f2c796e3db0d7d8f7622daae49450ad515ef0319e320f214996af8d0`
- **Artifact:** [smoke.jsonl](../runs/demos/smoke.jsonl)
- **Artifact size:** 9,006,555 bytes
- **Artifact SHA-256:**
  `23C141A83C320564BAEAD8677B9AEC6557708BB62076C78648E2381B737736E1`
- **Verification command:**
  `python python/demo_record.py verify runs/demos/smoke.jsonl`
- **Acceptance gate:** at least 30 native-input frames and two observations;
  valid schema/provenance and values; F9 override off; movement plus Pressed and
  Released edges; contiguous sequence from 1; overlapping input/observation
  ticks; every active input player present in observations.
- **Observed:** 9,334 native-input frames, 854 observations, 2,200 movement
  frames, 48 Pressed edges, 48 Released edges, and zero sequence gaps.
- **Tick ranges:** demo `6766..11432`; observations `6619..11737`.
- Two local device-source IDs emitted 4,667 frames each. Source `1457758026`
  produced all movement/button activity and was the sole player ID in
  observations. Source `-822249859` remained completely neutral.
- **Result:**
  `OK -- native input and observations are aligned and gap-free`.
- **Status:** PASS for the live smoke gate.
- **Limitation:** this proves capture, alignment, player routing, edges, and
  transport integrity. It is not yet a recipe demonstration benchmark.

---

## 3. Phase C input-channel successes

Primary historical evidence is retained in
[phase-c-results.md](phase-c-results.md).

### 3.1 Control-frequency test

| Requested rate | Arrivals | Median wall time | Median final error | Maximum overshoot |
|---:|---:|---:|---:|---:|
| 10 Hz | 8/8 | 0.46 s | 0.161 | 0.000 |
| 12 Hz | 8/8 | 0.42 s | 0.148 | 0.000 |
| 15 Hz | 8/8 | 0.45 s | 0.174 | 0.000 |
| 20 Hz | 8/8 | 0.44 s | 0.165 | 0.000 |

- Gate: at least 98% arrival and at most 2% overshoot failures.
- Lowest passing evaluated rate: **10 Hz**.
- **Status:** PASS.
- **Limitation:** proportional controller, not a learned motor policy.

### 3.2 Button edges and player routing

- Held Python booleans reproduce Pressed/Held/Released edges.
- Grab/place and hold-to-interact operate through the normal input queue.
- Requests now route through `PlayerManager.HandleNewInputData`.
- Live input no longer double-registers while override is off.
- **Status:** PASS.

### 3.3 Command expiry and disconnect

Latest safety rerun:

- Watchdog stop after last command: **0.03 s**
- Drift after expiry: **0.00 world units**
- Drift after hard client termination: **0.000 world units**
- **Status:** PASS.

An earlier expiry run stopped after 0.33 seconds but drifted 1.55 units. It was
superseded by the explicit neutralization and later zero-drift rerun; both
results remain in the historical Phase C file.

### 3.4 Short command soaks

Successful recorded runs include:

| Commands | Observations | Duration | Maximum round-trip gap | Stalls over 1 s | Errors |
|---:|---:|---:|---:|---:|---:|
| 727 | 726 | 21 s | 76 ms | 0 | 0 |
| 2,345 | 2,344 | 66 s | 59 ms | 0 | 0 |
| 392 | 391 | 11 s | 73 ms | 0 | 0 |

- **Status:** PASS for short soaks.
- **Formal long-soak status:** not passed. A later 23,786-command run recorded
  one 600-frame position freeze and therefore remains a failed result.

---

## 4. Phase D episode-control successes

Historical request results are retained in
[phase-d-results.md](phase-d-results.md). Earlier failures are not deleted.

### 4.1 Agent-initiated day start

- Ready is mapped to `SecondaryAction1` / `Controls.Interact3`.
- Successful run started the day in **2.0 seconds**.
- Earlier attempts using the wrong input field failed and remain recorded.
- **Status:** PASS.

### 4.2 Start Practice

- Game-state requests are routed through
  `PlayerManager.HandleNewInputData`.
- `StartPractice` opens its managed confirmation popup.
- `MenuSelect` confirms the popup.
- Observed transition: day `0` preparation to day `1` Practice.
- **Status:** PASS.

### 4.3 QuitSection and termination

- `QuitSection` opens the Abandon Restaurant managed popup.
- `MenuSelect` confirms the choice.
- `SGameOver` was observed immediately afterward.
- `loss_reason`: **2** (`Quitting`, as confirmed from the decompiled handler).
- **Status:** PASS.

### 4.4 Paused observation liveness

- **Date:** 2026-07-28
- **Procedure:** run `python python/observe.py rate`, pause PlateUp, and keep the
  game paused for more than 30 seconds.
- **Observed stream:** approximately **29-31 observations/second**.
- **Observed simulation rate:** approximately **180 ticks/second** while paused.
- `paused=True` remained visible.
- `outbound_frames_dropped=0` throughout.
- No stall occurred.
- **Status:** PASS for paused liveness and backpressure.
- **Important finding:** `PublishEvery = 6` does not guarantee 10 Hz in wall
  time because the simulation-group rate changes. Wall-clock rate must be
  measured rather than inferred from the tick divisor.

### 4.5 Practice reset quick run: 3 attempts

- **Date:** 2026-07-28 19:41 local
- **Bridge:** `0.2.3`
- **Artifact:** [reset-20260728-194157.json](../runs/phase_d/reset-20260728-194157.json)
- Attempts: **3**
- Successes: **3**
- Success rate: **100%**
- Median/p90/p99: **2.875 / 2.875 / 2.875 seconds**
- Estimated episodes/hour at 1x: **34.99**
- Estimated wall time for 5M steps at 1x: **142.88 hours**
- **Status:** PASS as a smoke/quick-distribution run.

### 4.6 Practice reset quick run: 20 attempts

- **Date:** 2026-07-28 19:43 local
- **Bridge:** `0.2.3`
- **Artifact:** [reset-20260728-194314.json](../runs/phase_d/reset-20260728-194314.json)
- Attempts: **20**
- Successes: **20**
- Success rate: **100%**
- Median: **2.9455 seconds**
- p90: **3.0470 seconds**
- p99: **3.1710 seconds**
- Estimated episodes/hour at 1x: **34.97**
- Estimated wall time for 5M steps at 1x: **142.98 hours**
- **Status:** PASS as a quick-distribution run.
- **Historical classification:** this remains a quick-distribution result; the
  formal gate is now independently passed in section 4.7.

### 4.7 Practice reset formal gate: 500 attempts

- **Date:** 2026-07-28 20:46 local
- **Game:** PlateUp `1.4.3-FF8F`
- **Bridge:** `0.2.4`
- **Protocol / schemas:** `1` / `obs_0.1` / `act_0.1`
- **Runtime mod SHA-256:**
  `a95958844ee81fd6515e7e93a3cd3fe5822a2b75d86d18192675e5acecfea1c4`
- **Command:** `python python\phase_d_accept.py reset 500`
- **Artifact:** [reset-20260728-204632.json](../runs/phase_d/reset-20260728-204632.json)
- Acceptance gate: at least **99%** successful resets over 500 attempts.
- Attempts: **500**
- Successes: **500**
- Failures: **0**
- Success rate: **100%**
- Median reset time: **3.281 seconds**
- p90 reset time: **3.453 seconds**
- p99 reset time: **3.546 seconds**
- Estimated episodes/hour at 1x: **34.856**
- Estimated wall time for 5M steps at 1x: **143.446 hours**
- Provisional 3x estimate: **50.853 hours**, but this estimate is **not
  approved** because the 2x/3x motor-fidelity gate failed.
- **Status:** PASS. The Practice reset mechanism and its formal reliability
  requirement are approved for the environment contract.

### 4.8 Unfocused, unpaused background operation

- **Date:** 2026-07-28
- **Procedure:** run the Phase D reset and timescale harnesses with PowerShell
  as the foreground window in front of PlateUp.
- PlateUp was therefore unfocused while remaining unpaused.
- The formal reset run completed **500/500** successful Practice cycles in this
  state.
- The timescale harness also continued receiving observations and controlling
  the player in this state.
- **Status:** PASS for functional unfocused/background operation.
- **Limitation:** the saved artifacts do not label window focus or contain a
  dedicated foreground-versus-unfocused simulation-rate comparison. This does
  not establish minimized-window behavior.

### 4.9 Minimized, unpaused background operation

- **Date:** 2026-07-28
- **Procedure:** run `python python/observe.py rate`, leave PlateUp unpaused,
  minimize the PlateUp window, and observe the bridge stream.
- The observation stream continued and the game remained operational while
  minimized.
- **Evidence:** user-confirmed live terminal test.
- **Status:** PASS for functional minimized/background operation.
- **Limitation:** no saved numeric rate transcript was supplied, so this closes
  functional liveness rather than a precise foreground/minimized throughput
  comparison.

---

## 5. Failed and inconclusive gates

These results are deliberately included because they constrain subsequent
architecture.

### 5.1 Timescale movement fidelity: FAIL

- **Date:** 2026-07-28 19:53 local
- **Bridge:** `0.2.3`
- **Artifact:** [timescale-20260728-195301.json](../runs/phase_d/timescale-20260728-195301.json)
- Course: 0.9-unit x-axis shuttle, 12 out/back laps per speed.

| Speed | Arrivals | Arrival rate | Distance/game-second | Median lap game-seconds |
|---:|---:|---:|---:|---:|
| 1x | 24/24 | 100% | 1.7682 | 0.9365 |
| 2x | 24/24 | 100% | 1.2644 | 1.8670 |
| 3x | 24/24 | 100% | 0.8591 | 2.8750 |

Compared with 1x:

- 2x arrival delta: **0.0 percentage points**
- 2x distance/game-second delta: **28.49%**
- 3x arrival delta: **0.0 percentage points**
- 3x distance/game-second delta: **51.42%**
- Gate: at most 2 percentage points arrival delta and at most 2% distance
  delta.
- **Verdict:** FAIL.

The chef can still reach every target at 2x and 3x, but locomotion does not
remain faithful per scaled game-second. Motor-policy training against the real
game is therefore approved only at **1x** unless a later experiment establishes
a different acceleration mechanism. The provisional 3x estimate of 50 hours
for 5M steps is not approved.

### 5.2 Phase-transition capture test: INCONCLUSIVE

- Earlier Phase C runs observed no captured-input frames during the selected
  transition.
- Motion while captured was zero, but the required condition was never
  exercised.
- Pause is now independently verified using `paused=True`; generic popup capture
  still needs its own formal transition soak.

### 5.3 Long command soak: FAIL/PENDING RERUN

- Commands and observations: 23,786 each.
- Duration: 667 seconds.
- Maximum round-trip gap: 191 ms.
- Stalls over one second: zero.
- Error: one 600-frame frozen-position event.
- A clean 100,000-command formal soak remains pending.

### 5.4 Runtime mod hash: RESOLVED

- The bridge `0.2.3` reset and timescale artifacts both report
  `mod_hash: "unknown"`.
- The locally built and deployed DLLs had matching SHA-256 hashes, but that fact
  is not embedded in the run manifests.
- Bridge `0.2.4` now contains robust path fallbacks and emits the full SHA-256.
- Quick `0.2.3` measurements remain useful, but formal acceptance evidence must
  include a runtime-resolved mod hash so a result can be tied to the exact DLL.
- The live `0.2.4` handshake reported
  `a95958844ee81fd6515e7e93a3cd3fe5822a2b75d86d18192675e5acecfea1c4`,
  exactly matching the built/deployed DLL.
- **Status:** RESOLVED on 2026-07-28. Earlier `0.2.3` artifacts continue to
  retain `unknown` as accurate historical provenance.

---

## 6. Remaining measurement gates before Phase E

1. Retain the 1x-only motor-fidelity decision unless new evidence supersedes the
   failed 2x/3x gate.
2. Record matched burger and steak demonstrations, then make the initial recipe
   decision from measured complexity and service throughput.

The Phase D measurements, canonical trace, and native-input recorder smoke gate
are complete. No Gym/environment design should be treated as stable until the
remaining recipe gate is closed.

---

## Future entry template

```markdown
### YYYY-MM-DD HH:MM — Short result name

- **Game:** PlateUp 1.4.3-FF8F
- **Bridge:** x.y.z
- **Protocol / schemas:** 1 / obs_0.1 / act_0.1
- **Command or procedure:** `exact command`
- **Acceptance gate:** numeric threshold
- **Observed result:** numeric result
- **Artifact:** relative path
- **Status:** PASS / FAIL / INCONCLUSIVE
- **Limitations:** anything preventing generalisation or formal closure
```
