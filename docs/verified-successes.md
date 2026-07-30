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
| Recipe benchmark protocol | Matched conditions, sample size, metrics, and decision rule declared before any benchmark recording. | DECLARED |
| Demonstration analyzer | Reproduces the ledger's golden-trace counts exactly; 10/10 offline checks pass. | PASS |
| Recipe benchmark result | Not started. No benchmark session has been recorded. | PENDING |
| Project 1 recipe | Fixed to steak by project-owner scope decision, **not** by the benchmark. | DECIDED (scope) |
| Observation facts from artifacts | Rotation zero, provider infinity, floor mess, table linkage and entity recycling derived; 14/14 checks pass. | PASS (offline) |
| Steak agent offline gate | 146/146 checks across facts, geometry, recipe, options, model, service, capability, surrogate, environment, preparation, learning, reward hacking, manifests and the live verifier. | PASS (offline) |
| Steak agent in the live game | Never run. No live evidence exists for any agent layer. `python python\livecheck.py` is the read-only tool that settles the offline assumptions first. | PENDING |
| Environment API and random soak | 12/12 API checks; 20,000 random actions with a constant observation shape and stated terminal reasons, on the offline model. | PASS (offline) |
| Capability registry | Measured against the offline model only. No live rows exist. | PROVISIONAL |
| Preparation phase handling | Popup cleared with Cancel, consent given once, day started; verified against the model and the recorded day 0 checklist. | PASS (offline) |
| Behaviour-cloning pipeline | Datasets from human recordings and from the model; goal-conditioned policy trains and round-trips. | PASS (offline) |
| Learned motor policy, Phase G gate | Best observed 1 group of 4; best-validated 0, against a baseline of 4. Movement is the gap: learned buttons alone reach parity. | FAIL (gate not met, decision written) |
| Reward-hacking suite | 12 of 14 section 11.3 adversaries closed against the model; 2 are live-only and stay OPEN. | PASS (offline, partial) |
| Evidence bundle | Run manifests record code, schemas, pinned build and artifact hashes, and re-check them. | PASS (offline) |
| Live verifier | `livecheck.py` replays correctly against both recordings: 13 claims confirmed, untriggered ones left PENDING, and a recording from a different mod build rejected. | PASS (offline) |

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
- **Later finding:** section 2.5 established that this recording is a **steak**
  Day 1 played with `--recipe smoke`. That does not affect the smoke gate, which
  never claimed a recipe, and the recording is now the live proof that the
  analyzer's provenance cross-check fires.

### 2.5 Demonstration analyzer offline validation

- **Date/time:** 2026-07-28 22:49 AEST
- **Game:** PlateUp `1.4.3-FF8F`
- **Bridge:** `0.3.0` (analyzer is offline and reads recorded files only)
- **Protocol / schemas:** `1` / `obs_0.1` / `act_0.1` / `demo_0.1`
- **Command:** `python python\demo_analyze.py validate`
- **Artifact:** [analyzer-validation.txt](../runs/benchmark/analyzer-validation.txt)
- **Artifact SHA-256:**
  `B44B326233FFF00DBC2B7F54F65E77BA2102F2F58DA462CFB76C9ECECBA080F2`
- **Inputs:** `runs/golden/obs_0.1_day1.jsonl` (SHA-256 verified as
  `5cb703978261e4178a0ba3fae4e4d2c881819da6aa30857e49d89424fca74539`,
  matching section 2.3) and `runs/demos/smoke.jsonl` (section 2.4).
- **Acceptance gate:** the analyzer must independently reproduce the
  golden-trace counts already recorded in section 2.3, report interaction
  metrics as unavailable rather than zero on a demonstration-free file, and
  reject the smoke recording as a benchmark session.
- **Observed:** 10 of 10 checks passed.
  - Golden trace: **4** groups, **308** order entry frames, **3**
    satisfaction transitions. All three match section 2.3 exactly.
  - Recipe derived from ordered item IDs alone: **burger**
    (`Burger - Plated`, 308 entries).
  - Demonstration-free file: interaction metrics `unavailable`; observation
    metrics still computed (failure rate `0.000`, process seconds per meal
    `5.5`).
  - Smoke recording rejected, with both reasons reported: declared `smoke`
    versus derived `steak`, and the day stopping at 24.7% of its length.
  - Segmentation: 10 of 10 Pressed edges paired, null rate `0.600`.
- **Result:** `OK -- 10 analyzer checks passed against recorded artifacts`.
- **Status:** PASS for the analyzer against recorded artifacts.
- **Limitation:** this validates the analyzer, not the benchmark. It uses
  the only two recordings that exist, neither of which is an acceptable
  benchmark session. The decision rule in protocol section 5 was exercised
  separately against synthetic recordings covering a clear win, a
  lexicographic fall-through to metric 3, an INCONCLUSIVE tiebreak, and the
  quick-sample threshold; those recordings were fabricated and are
  deliberately **not** retained as evidence.

### 2.6 Golden trace is a partial day: correction

- **Date:** 2026-07-28
- The canonical trace was described as containing a full hand-played day. The
  analyzer measured its final Day 1 frame at `seconds_elapsed = 94.555` against
  `day_length = 100`, with `time_unbounded = 0.946` and zero groups remaining.
- The recording therefore stops approximately 5.4 seconds before the day ends.
- **Impact on section 2.3:** none. That gate is a schema and lifecycle
  regression check, and every count it records is unchanged and independently
  reproduced in section 2.5.
- **Impact elsewhere:** the trace is correctly **rejected** as a recipe
  benchmark session, because protocol section 3 requires the recording to run
  past the end of the day. The wording in `observation-schema.md` was corrected
  to match.
- **Status:** documentation correction. No result is withdrawn.

### 2.7 Observation facts derived from the recorded artifacts

- **Date:** 2026-07-29
- **Game:** PlateUp `1.4.3-FF8F`
- **Bridge:** `0.2.4` and `0.3.0` recordings; the deriver is offline and reads
  files only.
- **Protocol / schemas:** `1` / `obs_0.1` / `act_0.1` / `demo_0.1`
- **Command:** `python python\facts.py --json runs\facts\observation-facts.json`
- **Artifact:** [observation-facts.json](../runs/facts/observation-facts.json)
- **Artifact SHA-256:**
  `9685E7C7F1693CA6380BC78C3F416320F64E98519485F54F0336FA22A6435D56`
- **Inputs:** `runs/golden/obs_0.1_day1.jsonl` (section 2.3) and
  `runs/demos/smoke.jsonl` (section 2.4).
- **Acceptance gate:** each derived fact must hold on the recordings that
  produced it, and the deriver re-asserts all fourteen on every run.
- **Observed:** 14 of 14 checks passed.
  - **Rotation zero, resolved.** `rot = atan2(MoveX, MoveY)` in degrees; 0
    faces +z and 90 faces +x. 187 steady samples across all four quadrants,
    median error **0.21°**, p90 **3.29°**. Larger errors occur only while the
    commanded direction is still changing, which is turn latency.
  - **Provider infinity, resolved.** Infinite providers report `maximum` 0 and
    `available` 0, not a negative sentinel. `Plate Stack - Starting` reports
    `maximum` 4 with `available` 4 → 0. This corrects the schema's earlier
    "negative appears to mean infinite".
  - **Floor mess, resolved.** Mess is published as `Mess - *` appliances at
    `OccupancyLayer.Floor`, off the tile grid; it was never a missing field.
    Layer 2 holds exactly mess, mop water, nameplates and the practice
    trigger, and every other appliance sits at layer 0.
  - **Table linkage, negative result.** `groups[].table` resolved 0 times out
    of 1,473 in the golden trace and 0 of 731 in the smoke recording, and
    `is_table` was emitted 0 times in either. The `CTableSet` entity is not an
    appliance. The substitute is the group's own position, which sits exactly
    on a table appliance in 823 of 823 and 421 of 421 seated group frames.
  - **Entity recycling.** 17 appliance names in the golden trace span two or
    three generations of entity ID at a constant per-frame count, and 14 do in
    the smoke recording: fixed appliances are rebuilt when the day starts.
    `(aid, tile)` survives it.
  - **Reach model.** All three recorded deliveries stood inside the 1.4-unit
    reach limit, at 0.88, 0.91 and 1.02 units. Two aimed at the table and one
    at an occupied chair; all three put the plate on the table.
- **Result:** `OK -- 14 observation facts derived from recorded artifacts`.
- **Status:** PASS for the derivations against the recorded artifacts.
- **Limitations:** these are properties of two recordings on one build, not
  live probes. The rotation and provider results are strong because they span
  the full circle and both provider kinds; the table-linkage result is a
  negative one and only says the reference cannot be resolved from `obs_0.1`,
  not why. `observation-schema.md` has been updated to match, without a schema
  version bump, because no field changed.

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

## 4A. Project 1 recipe scope decision

### 4A.1 Steak selected as the Project 1 recipe

- **Date:** 2026-07-29
- **Decision:** Project 1 is fixed to the steak base recipe.
- **Basis:** project-owner scope decision. **Not** a benchmark result.
- **Record:** [steak-decision.md](steak-decision.md)
- **Status:** DECIDED (scope).
- **Explicitly not claimed:** that steak is the measured easier recipe.
  [recipe-benchmark-protocol.md](recipe-benchmark-protocol.md) has not been
  run, no benchmark session exists for either arm, and the "Recipe benchmark
  result" row above stays PENDING. The protocol, its decision rule and its
  §5.1 tiebreak are unchanged and can still be run.
- **Limitations:** the specification's §10.5 requirement to choose the recipe
  by measurement is unmet. The decision is revisable under the protocol's §7
  triggers plus the additional Phase G and Phase H triggers in
  `steak-decision.md` §5.

---

## 4B. Steak agent layers, offline only

Everything in this section was measured against `python/mockgame.py`, a
tick-level **model** of the game built from the two recordings, or against the
recordings themselves. None of it is live-game evidence, and no layer described
here has ever run against PlateUp.

### 4B.1 Offline gate for the steak agent

- **Date:** 2026-07-29
- **Game target:** PlateUp `1.4.3-FF8F` (not run; the gate is offline)
- **Bridge target:** `0.3.0`
- **Schemas:** `obs_0.1` / `act_0.1` / `encode_0.1` / `capability_0.1` /
  `env_0.1`
- **Command:** `python python\selftest.py --json runs\selftest\offline-gate.json`
- **Artifact:** [offline-gate.json](../runs/selftest/offline-gate.json)
- **Artifact SHA-256:**
  `488467A89E3819D8D98274853BA36600923CB5695942646A03775A17F93EE874`
- **Acceptance gate:** every check passes, across nine groups: facts,
  geometry, steak, options, model, service, capability, surrogate and
  environment.
- **Observed:** **146 of 146** checks passed, 0 failed.
  - Geometry: every working appliance in the recorded steak layout has a
    reachable approach pose with a positive aim clearance, and all three
    recorded human delivery stances pass the same aim model the planner uses.
  - Steak: the chain, the servable set, the measured-rate-to-timescale
    identity, and menu inference, including that the recorded burger day is
    **not** recognised as steak.
  - Options: acquire, place, watch-cook, plate and buffer complete against the
    model; invalidation, timeout, neutral release and the grab press/release
    edge are classified as specified.
  - Environment: 12 API checks plus a 12,000-step random-action soak.
  - Preparation: the day-0 checklist, a popup cleared with Cancel only,
    consent given once, and the toggle behaviour that would otherwise stall a
    live run.
  - Learning: dataset alignment from a real recording, episode-level splits,
    training, checkpoint round-trip and the metric harness.
  - Live verifier: `livecheck.py` replayed against both recordings, confirming
    it reaches the right verdicts and correctly rejects a recording made with a
    different mod build.
- **Result:** `OK -- 146 offline checks passed. This is an offline gate and not
  live-game evidence.`
- **Status:** PASS (offline).
- **Limitations:** a pass means the agent code is internally consistent and
  agrees with the two recordings. It says nothing about how the chef behaves
  on screen. The model's simplifications are listed in `mockgame.py`:
  customers do not collide with the chef, there is no mess, fire, dessert
  course or dish rack, and every group orders one main.

### 4B.2 Reference controller on the offline model

- **Date:** 2026-07-29
- **Command:**
  `python python\service.py mock --episodes 8 --capability runs\capability\mock-reference.json --json runs\benchmark\mock-episodes.json`
- **Artifacts:** [mock-episodes.json](../runs/benchmark/mock-episodes.json)
  (SHA-256 `3BD0BB9EB8E87A0D03E7BF89057C926EA44161838ED84F922E8BA5228D6B8EA5`),
  [mock-reference.json](../runs/capability/mock-reference.json)
  (SHA-256 `57B6C6DD1044284DC00563DAF723C33505944B45B3A8E6B514FE22842BF837DA`)
- **Layout:** taken verbatim from the recorded steak restaurant in
  `runs/demos/smoke.jsonl`.
- **Sweep artifact:** [mock-sweep.txt](../runs/benchmark/mock-sweep.txt)
- **Sweep SHA-256:**
  `503965BCE62C935F617A61A1562186C88E85570E63AA3BD0599B9A6FF6F6FE33`
- **Observed:** 8 of 8 modelled days served **4 of 4** groups with **0** lost
  and **0** ruined items. A ten-configuration sweep is retained in that
  artifact: every configuration up
  to and including a saturated day with a single plate lost nobody and ruined
  nothing. Working while a steak cooks served **7** on a saturated modelled
  day against **6** standing at the hob, and lifting at Well-done served
  **6** against **7** lifting at Rare. The one configuration that lost a
  group — 12 groups every 5 s with one plate, cooked to Well-done — is a
  plate-throughput limit, not a stall: a single plate serialises the kitchen.
- **Status:** PASS (offline model only).
- **Bugs this found, which are the point of having a model:** a cooked steak
  in hand with no clean plate and every counter full deadlocked the chef; a
  clean plate in hand made the planner aim repeatedly at an already-occupied
  plate stack, failing 158 times in one modelled day; and counting only
  finished dishes as work-in-progress let the counters fill with cooked steaks
  no plate would ever arrive for. All three are fixed and covered by the
  offline gate.
- **Limitations:** this is a **scripted** controller. Specification §2.3
  disallows scripted cook-plate-serve control and deterministic pathfinding
  inside a scored run, so this is a baseline and a data source, never an
  autonomy result. The throughput comparison between doneness policies is a
  property of the model's timings, three of which are knowledge-base priors
  that have never been observed on a steak.

### 4B.3 Environment API and random-action soak

- **Date:** 2026-07-29
- **Commands:** `python python\env.py check`,
  `python python\env.py soak --steps 20000 --json runs\env\random-soak.json`
- **Artifact:** [random-soak.json](../runs/env/random-soak.json)
- **Artifact SHA-256:**
  `5DF3EF87514C12325587E17D29463AF6E77FB45D3DBDE55DC5FB377C8F5AE260`
- **Observed:** 11 of 11 API checks passed. The soak ran **20,000** random
  actions producing 4 episodes, all terminating as `game_over`, with a single
  observation length of 147 throughout and a total reward of −8.375. Random
  play never completed a day; the reference controller completed every day
  through the same API with a reward of 3.95.
- **Status:** PASS (offline model only).
- **Limitations:** specification §16.3 requires the soak to run against the
  real bridge across phase transitions and resets. This soak ran against the
  model, so it exercises the environment's own contract, not the bridge's. The
  live 100,000-command soak remains FAIL/PENDING (§5.3).

### 4B.4 Semi-MDP surrogate against the model it was calibrated on

- **Date:** 2026-07-29
- **Command:**
  `python python\surrogate.py compare runs\capability\mock-reference.json --episodes 20 --json runs\benchmark\surrogate-vs-model.json`
- **Artifact:** [surrogate-vs-model.json](../runs/benchmark/surrogate-vs-model.json)
- **Artifact SHA-256:**
  `27B9FCBB86B80936291E49B1A3C45F8865100C19E5E94006A6F9E35393124365`
- **Observed:** over 20 episodes each, the surrogate and the tick-level model
  agreed exactly on the medians that matter: 4 served, 0 lost, 0 ruined, 20
  money. Calibration support was 1.0, meaning every measurable transition
  found a registry row.
- **Status:** PASS for internal consistency between the two models.
- **Limitations:** this is **not** the specification §9.4 validation. That
  requires the surrogate to predict held-out **real** service outcomes, and
  the registry it was calibrated from contains only model-derived rows. The
  agreement shown here means the option abstraction does not itself distort
  the day; it says nothing about either model matching PlateUp.


### 4B.5 Preparation phase, handled end to end

- **Date:** 2026-07-30
- **Command:** `python python\selftest.py --only preparation`
- **Grounding:** both recordings publish `start_day_warnings` only on day 0 —
  378 frames in the golden trace, 123 in the smoke recording — with
  `players_not_ready` at Error until consent and every other warning at Safe.
  `popups_open` reached Error in exactly the 94 golden-trace frames where
  `input_captured` was true.
- **Observed:** 5 of 5 checks passed. The controller clears a modal popup with
  `MenuCancel`, consents once, the day starts, and the modelled day is then
  served 4 of 4 with nothing lost.
- **Two behaviours that would each have cost a live session:** consent
  **toggles** on the `Pressed` edge, so a controller that releases and presses
  again un-readies itself and stalls the day forever; and the day will not
  start under an open popup, so consent has to wait for it to clear.
- **Status:** PASS (offline model and recorded artifacts).
- **Limitations:** the model's preparation phase is a reconstruction from the
  published checklist, not a recording of one being cleared. `MenuSelect` is
  deliberately never sent, so a popup that requires a choice will stop the run
  with a message rather than be answered.

### 4B.6 Behaviour cloning, goal conditioning, and the Phase G gate

- **Date:** 2026-07-30
- **Schemas:** `encode_0.2` / `env_0.2` / `dataset_0.1` / `policy_0.1` /
  `dagger_0.1` / `evaluate_0.1`
- **Commands:**
  `python python\dataset.py model runs\datasets\reference-goal.npz --episodes 14`,
  `python python\policy.py train runs\datasets\reference-goal.npz runs\policies\bc-goal.npz`,
  `python python\evaluate.py compare runs\policies\bc-goal.npz`
- **Acceptance gate:** specification section 12 stage G requires the option
  gates to pass across held-out starts. The operational proxy used here is
  matching the scripted baseline's 4-of-4 groups served.
- **Observed:** no variant of the learned policy comes close to the baseline.
  The best observed was a **median of 1** group of 4 with 8 of 8 modelled days
  completed; the best-validated checkpoint, trained on 60 randomised-start
  episodes with a held-out accuracy of 0.969, serves **0**. The baseline serves
  **4**.
- **Verdict:** **FAIL.** The Phase G gate is not met. The pipeline is complete
  and measured; the policy is not good enough.
- **Curriculum randomisation, a second negative result:** specification
  section 10.3 step 3 was implemented and the dataset regenerated at three
  times the size (60 episodes, 187,950 states). Held-out accuracy rose from
  0.863 to **0.969** and groups served fell from 1 to **0**. Generalisation
  improved; play did not. This is the **third** time in this work that
  supervised accuracy and play moved in opposite directions.
- **Findings that are results in their own right**, recorded in
  [learning-pipeline.md](learning-pipeline.md):
  - a state-only clone reached **97.2%** held-out per-frame accuracy and served
    **zero** groups on every seed, walking into an appliance and pushing
    against it for the rest of the day. Per-frame accuracy is not a proxy for
    playing, and this is why `evaluate.py` scores by playing;
  - cloning a hierarchical expert needs the goal: 4.5% of repeated quantised
    states carried conflicting movement labels, because the planner's choice of
    target is not in the observation;
  - inverse-frequency class balancing, correct on the movement heads, made the
    grab head fire in **36%** of frames against a true 1.9%, at **99.0%
    balanced accuracy**, putting the chef in a plate-on-plate-off loop for a
    whole modelled day. Balancing is now applied to the movement heads only and
    `policy.py report` prints the fires-versus-should ratio that balanced
    accuracy hides.
- **DAgger, a negative result:** six iterations, four rollouts each, an
  aggregate grown from 32,000 to **124,984** states. Every iteration scored a
  median of 0 groups served against the seed policy's 1, so the retained
  checkpoint is iteration 0. Aggregating more labels at the states the policy
  reaches is not what is missing. History:
  [dagger-goal-history.json](../runs/policies/dagger-goal-history.json).
- **How far off, measured:** `python python\evaluate.py assist` hands a given
  share of ticks to the scripted controller. **10%** reaches full parity
  (4 served, 0 lost); 5% already triples the score. The policy is failing on a
  small, decisive minority of frames rather than being generally lost.
  Artifact: [assist-sweep.json](../runs/policies/assist-sweep.json).
- **Which half, measured:** `python python\evaluate.py split` gives one half of
  the action to the policy and the other to the option layer. Buttons learned
  with a scripted route serves **4 of 4**, which is parity; movement learned
  with scripted buttons serves **2**. **The gap is movement, not the press.**
  This contradicted the earlier reading of the on-policy mismatch table, which
  had blamed the press head; that mismatch is measured at states the movement
  head had already drifted into. Artifact:
  [policy-split.json](../runs/benchmark/policy-split.json).
- **Evidence bundle:** [steak-agent.json](../runs/manifests/steak-agent.json)
  records the commit, every schema version, the pinned build taken from the
  recording's handshake, and a SHA-256 for each artifact above.
  `python python\manifest.py --check runs\manifests\steak-agent.json`
  re-hashes them and reports anything that has moved.
- **Status:** PASS for the pipeline, FAIL for the gate.
- **Decision:** specification section 12 requires a written method-change
  decision rather than a longer run. It is
  [phase-g-decision.md](phase-g-decision.md), kept current as items were
  measured and failed. RL fine-tuning is now first, then changing the movement
  representation to the continuous head section 7.1 already declares as the
  comparison baseline; explicitly not more DAgger, more data, more epochs, or a
  larger network, all four of which have now been tried and measured.
- **Limitations:** trained against `mockgame`, so the policy has learned the
  model. The task layer is still the scripted planner, so this is a learned
  motor controller under a scripted planner and not an autonomous agent.
  Specification section 10.3 step 6 (RL fine-tuning) is not implemented.

### 4B.7 Reward-hacking suite

- **Date:** 2026-07-30
- **Command:** `python python\antihack.py`
- **Acceptance gate:** every specification section 11.3 exploit either fails to
  pay or is reported as untestable, with no exploit passing quietly.
- **Observed:** **12 of 14** checks closed. Idling, refusing to start the day,
  holding every input, spamming interactions, camping and deliberately failing
  all earn nothing and are beaten by the baseline. An unchanged frame pays
  nothing and money going backwards pays nothing, so an order cannot be
  farmed. Ruining items is a cost.
- **Left OPEN, deliberately:** Practice-only reset state and duplicate command
  receipts. Both are properties of the live bridge, and both are reported as
  OPEN rather than counted as passing.
- **Status:** PASS (offline, partial).
- **Limitations:** measured against the model. The reward function is designed
  so most of these are structurally impossible rather than merely
  unprofitable, but that design is only as good as the model it was checked
  against.


### 4B.8 Live verifier, validated offline

- **Date:** 2026-07-30
- **Command:** `python python\selftest.py --only livecheck`
- **What it is:** `python python\livecheck.py` connects read-only with F9 off,
  sends only the neutral heartbeat, and marks 21 falsifiable claims as the
  evidence for each one arrives while a human plays. It cannot move the chef.
- **Acceptance gate:** replayed against both recordings it must reach the right
  verdicts, must leave untriggered claims PENDING rather than passing them, and
  must reject a recording produced by a different mod build.
- **Observed:** 8 of 8 checks passed. On the steak recording it confirms 13
  claims with no contradiction and leaves 8 PENDING, which are exactly the
  actions that recording never performed. On the golden trace it correctly
  **fails** the provenance check, because that trace was recorded with bridge
  `0.2.4` rather than `0.3.0`.
- **Status:** PASS for the verifier itself, offline.
- **Limitations:** this validates the tool, not the claims. The claims are still
  unverified in the live game, which is the entire point of the tool existing.
  Three of them are the ones most likely to fail: the steak cook stage
  durations (knowledge-base priors, never observed), the plating route, and
  whether `StopMoving` leaves `Movement` intact for aiming.

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

## 6. Remaining measurement gates

1. Retain the 1x-only motor-fidelity decision unless new evidence supersedes the
   failed 2x/3x gate.
2. **Run the steak agent in the live game.** Nothing in section 4B has ever
   touched PlateUp. The first live run of `python python\service.py run` inside
   Practice, with a capability registry written from real trials, is the gate
   that turns any of it into evidence.
3. Compare the live capability registry against the model's. That difference
   is the first honest measurement of how wrong `mockgame` is, and it is what
   the surrogate's §9.4 validation depends on.
4. Close the 100,000-command soak (§5.3) before any unattended run.
5. Optionally, record matched burger and steak demonstrations under
   [recipe-benchmark-protocol.md](recipe-benchmark-protocol.md) and decide the
   recipe by measurement. The recipe is currently fixed by scope decision
   (§4A.1), not by that protocol.

The Phase D measurements, canonical trace, native-input recorder smoke gate, and
demonstration analyzer are complete. The benchmark protocol and its decision rule
remain declared and unrun.

Note that the benchmark measures intrinsic production-chain cost and **not**
behaviour under service load: Day 1 saturates every demand-pressure proxy
tested (protocol section 4.1.1), so a load comparison would need a harder day
and its own protocol.

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
