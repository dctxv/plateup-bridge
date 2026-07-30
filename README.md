# PlateUp Bridge

Programmatic control of a PlateUp chef from Python. Movement, interaction, and game-state requests, over a named pipe — plus the steak-service agent layers built on top of it.

Verified integration and acceptance results are maintained in
[`docs/verified-successes.md`](docs/verified-successes.md). Successful tests
must be added there with their evidence; failed gates are retained separately.

**Project 1 is fixed to the steak recipe** by scope decision, not by the
benchmark, which has not been run. See
[`docs/steak-decision.md`](docs/steak-decision.md). The agent layers
(`kitchen`, `steak`, `options`, `service`, `capability`, `surrogate`, `encode`,
`env`) pass a **146-check offline gate** and have **never been run in the
live game**; see [`docs/agent-architecture.md`](docs/agent-architecture.md)
and [How to test this](#how-to-test-this).

## Build

```powershell
& "$env:LOCALAPPDATA\PlateUpBridgeDotnet\dotnet.exe" build -c Release
```

If a .NET SDK is installed globally, `dotnet build -c Release` works as well.

The Deploy target copies `PlateUpBridge.dll` and `0Harmony.dll` into `PlateUp\PlateUp\Mods\PlateUpBridge\`. Edit `GameDir` in the csproj if your Steam library is elsewhere.

Quit the game before every build. Windows locks the DLL while PlateUp runs and the copy fails.

## Run

1. Launch PlateUp and enter a restaurant.
2. Check `Player.log` for `[BRIDGE] input system online` and `[BRIDGE] harmony patches applied`.
3. Press F9 to hand over control.
4. Run `python python/bridge.py`.

Log: `%USERPROFILE%\AppData\LocalLow\It's Happening\PlateUp\Player.log`

```powershell
Get-Content "$env:USERPROFILE\AppData\LocalLow\It's Happening\PlateUp\Player.log" -Wait -Tail 40
```

### Manual test keys (no Python needed)

| Key | Action |
| --- | --- |
| F9 | Toggle override — your keyboard is ignored while on |
| F5 / F6 / F7 | Measurement game speed: 1x / 2x / 3x |
| Arrows | Move |
| F10 | Grab (hold) |
| F11 | Interact (hold) |
| F8 | Ready/Start (hold) |

## Observation verification

Leave the bridge override off, play a day by hand, and run:

```powershell
python python/observe.py
```

Compare the summary with the game:

- The held item should change when you pick something up, place/store it in a
  legal holder, or dispose of it through a valid trash interaction.
- Cooking and chopping progress should increase.
- Burned food should show `!BAD`.
- Patience should fall while customers wait.
- Group and customer counts should match what is visible.

Use `python python/observe.py dump` to print one full observation.

To verify that observations continue while the game is paused:

```powershell
python python/observe.py rate
```

Pause PlateUp for 30 seconds. The expected result is a continued stream at
roughly `25-30 obs/s`, `paused=True`, and `OK`; `0 obs/s | STALL` means the
simulation group stopped. The tick divisor suggests 10 Hz but the simulation
group runs at about 180 ticks per second, so the wall-clock rate has to be
measured rather than assumed.

The observer deliberately does not publish `CScheduledCustomer`. Its future
arrival times and group sizes are hidden information under the experiment
contract. State is emitted as flat entity lists; spatial encodings belong in
Python so they can change without rebuilding the mod.

## Protocol

The first frame is a schema/provenance handshake:

```json
{"kind":"hello","protocol":1,"bridge_version":"0.3.0",
 "obs_schema":"obs_0.1","act_schema":"act_0.1","demo_schema":"demo_0.1",
 "session_id":"...","game_version":"1.4.3-FF8F",
 "mod_hash":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
 "unity":"2020.3.48f1"}
```

It is followed by one `dict` frame containing appliance, item, and process name
maps. Observations then arrive every sixth simulation tick, measured at 25-30 Hz:

```json
{"kind":"obs","protocol":1,"tick":8412,
 "in_restaurant":true,"paused":false,"override":true,
 "input_captured":false,"ack_command":417,
 "cmds_applied":412,"cmds_dropped":5,"outbound_frames_dropped":0,
 "day":1,"seconds_elapsed":42.5,
 "day_length":180.0,"money":25,"game_over":false,
 "players":[{"id":1,"x":1.1,"z":-1.5,"rot":90.0,"held":null,"captured":false}],
 "appliances":[{"e":"142:1","aid":123,"layer":0,"x":2.0,"z":-1.0,"rot":0.0}],
 "loose_items":[],"groups":[],"customers":[]}
```

Entity IDs use the string `"index:version"` so identities remain unique when
Unity recycles entity indices. Never compare them across game sessions. The
frozen field contract is documented in
[`docs/observation-schema.md`](docs/observation-schema.md).

Action, any rate:

```json
{"Tick":8407,"CommandId":418,"MoveX":1.0,"MoveY":0.0,
 "Grab":false,"Interact":false,"StopMoving":false,"Ready":false,
 "MenuSelect":false,"MenuCancel":false,
 "MenuUp":false,"MenuDown":false,"MenuLeft":false,"MenuRight":false,
 "Request":"None"}
```

The client refuses mismatched protocol, observation-schema, or action-schema
versions instead of silently mixing incompatible trajectory data.
`ack_command`, `cmds_applied`, and `cmds_dropped` expose command receipt without
a separate acknowledgement channel.

## How input actually reaches the chef

Worth keeping, because it is not obvious and cost a lot of decompiling.

```text
device / bridge
   -> PlayerManager.HandleNewInputData
        +-> HandleRequest(GameStateRequest)
        +-> Player.ReportNewInput(InputState) // also resets the liveness timer
   -> InputQueue.Enqueue
   -> InputQueue.ApplyUpdates()              // called from PlayerManager.OnUpdate
   -> Player.UpdateToEntity()                // CInputData = new { State = queue.State }
   -> CInputData on the player entity
        |
        +-> AttemptInteraction               // authoritative ECS. Grab/Interact work here.
        |
        +-> UpdatePlayerView -> PlayerView.ViewData.Inputs
             -> PlayerWalkingComponent.UpdateMovement(...)
                  if (is_my_player && DefaultInputSource.GetCurrentInputData(...))
                      use the LIVE DEVICE      <-- bypasses everything above
                  else
                      use CInputData
```

Locomotion for your own player is client-side prediction. It reads the device directly and ignores `CInputData`; the ECS value is only used for replicated remote players. That is why queue injection makes the chef grab but not walk.

The Harmony postfix on `BaseInputSource.GetCurrentInputData` makes predicted
locomotion read the same injected state. A prefix on `InputSource.SetInputUpdate`
suppresses the live-device queue producer while override is active, leaving the
bridge as the only authoritative producer. The bridge enters through
`PlayerManager.HandleNewInputData`, which handles `GameStateRequest` and then
queues movement/buttons through `Player.ReportNewInput`.

## Findings that constrain the design

**15-second liveness timer.** `Player.DeactivationProgress` increases every frame
and is only reset by `ReportNewInput()`. While override is active, the bridge
enqueues every tick even when the requested action is neutral. With override off,
the bridge is passive and the player's real device input supplies liveness.

**Movement is also the aim vector.** `AttemptInteraction` projects the interaction point from the player along `Movement` (falling back to facing rotation when neutral), then picks the nearest interactive within `InteractionRadius`. Move and interact are not independent action channels. Reach constants, from `Player.CompleteJoining`: `InteractionOffset = 0.7`, `InteractionRadius = 0.7`.

**Button state machine**, reproduced in `BridgeInputSystem.Advance`, mirrors `InputSource.GetButtonState`:

```text
Up -> Pressed -> Held -> ... -> Released -> Up
Consumed -> Consumed (while down) -> Up
```

Grab fires on `Pressed` only. Interact acts on `Pressed` or `Held`, with `IsHeld` distinguishing them — hold across ticks for chopping and washing.

**Turn latency is real.** `PlayerWalkingComponent` rotates toward the movement vector and only applies force once the facing is within `MaximumFacingSpread`, with a `MovementDeadzone` below which nothing happens. Direction changes cost time. Any surrogate simulator has to model this or it will overestimate throughput.

**Determinism is not available.** Position is computed view-side at render rate and written back to `CPosition` through `ResponseData`. Frame-rate dependent. Drop deterministic replay from the plan; evaluate statistically instead. This also means `timeScale` needs testing for movement fidelity specifically, not just for timer correctness.

**Episode control is an input action.** For save safety, the bridge accepts only:

| Request | Effect |
| --- | --- |
| `StartPractice` | Sets `CRequestPracticeMode` |
| `InLocalMenu` | Adds `CGamePauseRequest` |
| `InstantJoin` | Completes joining |
| `QuitSection` | Opens the game's Abandon Restaurant confirmation |

`StartPractice` and `QuitSection` do not act immediately: each opens a
`GenericChoiceView`, and the bridge must subsequently pulse `MenuSelect`.
`QuitToLobby`, `Disconnect`, `KickUser`, and unknown values are converted to
`None`; the bridge cannot trigger saving or silently drop a player.

**Menus read the same component.** `GenericPopupView`, `EndOfDayPopupView`,
`UnlockSelectPopupView`, and `StartDayWarningView` all consume `CInputData`.
Start-day consent specifically reads `SecondaryAction1` (`Controls.Interact3`);
the Python `ready` field is a semantic alias for that button. Other popups use
the menu navigation buttons in `InputState`.

**Focus matters.** `InputSource.Update` zeroes input when `Platform.Current.GameHasFocus` is false. The Harmony patch bypasses this for the injected path, but verify before planning unattended overnight training.

`CCaptureInput` / `CCapturePassthrough` mark input as owned by a menu; `AttemptInteraction` early-returns and sets `IsCaptured`. Free phase detection — query it rather than inferring from screen state.

**Demonstration recording.** Bridge `0.3.0` registers a non-consuming
`IInputConsumer` and streams native `InputState` frames beside observations.
The live smoke gate passed with 9,334 input frames, 854 observations, and zero
sequence gaps. With F9 off, record and verify demonstrations using:

```powershell
python python\demo_record.py record runs\demos\smoke.jsonl --recipe smoke
python python\demo_record.py verify runs\demos\smoke.jsonl
```

Move the chef and press/release Grab or Interact while recording. The contract
is documented in
[`docs/demonstration-schema.md`](docs/demonstration-schema.md).

## Recipe benchmark

`demo_record.py verify` checks transport integrity. Measuring a demonstration is
a separate offline step that needs neither PlateUp nor the bridge:

```powershell
python python\demo_analyze.py validate
python python\demo_analyze.py session runs\demos\burger\day1-01.jsonl
python python\demo_analyze.py benchmark runs\demos\burger runs\demos\steak
```

`validate` re-derives the golden trace's recorded counts and should be run after
any change to the analyzer. `session` reports the metrics for one recording and
says whether it is acceptable as a benchmark session. `benchmark` applies the
decision rule and reports the winner, the deciding metric, or INCONCLUSIVE.

The matched conditions, sample size, metrics, and decision rule are fixed in
advance by
[`docs/recipe-benchmark-protocol.md`](docs/recipe-benchmark-protocol.md). The
analyzer takes no threshold or weighting arguments, so the rule cannot be
adjusted after seeing the data.

## Phase D acceptance

Start inside active Practice with F9 enabled. Run a quick reset check before the
formal 500-cycle gate:

```powershell
python python\phase_d_accept.py reset 20
python python\phase_d_accept.py reset 500
```

For movement fidelity:

```powershell
python python\phase_d_accept.py timescale x
```

Stand beside one clear adjacent floor tile and choose its world direction:
`x` (right arrow), `-x` (left), `z` (up), or `-z` (down). The harness runs a
compact 0.9-unit out/back shuttle, prompts for F5/F6/F7 (1x/2x/3x), records raw
trajectories, and writes machine-readable results under `runs/phase_d/`.
Practice exit uses
SecondaryAction1 to reload the pre-Practice autosave; `QuitSection` cannot be
used for cycling because `StartPractice` is only valid during restaurant
preparation.

## How to test this

Three tiers, cheapest first. Tier 1 needs nothing but Python. Tier 2 needs
PlateUp but never takes control of it. Only tier 3 lets the agent drive.

### Tier 1 - offline, no game, about two minutes

```powershell
python python\selftest.py
```

146 checks over geometry, the recipe graph, option lifecycles, the model, whole
modelled days, the capability registry, the surrogate, the environment,
preparation, the learning pipeline, reward hacking, run manifests, and the live
verifier replayed against both recordings. Expect `OK -- 146 offline checks
passed`.

Then watch the scripted controller play modelled days, and push it until it
breaks:

```powershell
python python\service.py mock --episodes 4
```

```powershell
python python\service.py mock --episodes 3 --groups 10 --interval 9 --plates 1
```

Expect 4 of 4 groups served on a normal day and no losses under pressure. The
pressure knobs are `--plates`, `--groups`, `--interval`, `--day-length`,
`--min-stage` (1 Rare, 2 Medium, 3 Well-done), `--watch-hob`, `--preparation`
and `--popup-seconds`. Three planner deadlocks were found this way.

To see the learned policy and the diagnostics behind
[`docs/phase-g-decision.md`](docs/phase-g-decision.md):

```powershell
python python\evaluate.py compare runs\policies\bc-goal.npz --episodes 8
```

```powershell
python python\evaluate.py split runs\policies\bc-goal.npz --episodes 4
```

None of this is evidence about PlateUp. `mockgame` is a model built from the two
recordings, and every command says so in its own output.

### Tier 2 - live, read-only, five minutes of hand-play

This is the tier that matters, because it is the one that can prove the offline
work wrong. **Leave F9 OFF.** The tool sends only the neutral heartbeat the pipe
already requires; it cannot move the chef or fail a restaurant.

1. Back up your PlateUp save (specification section 1.1).
2. Launch PlateUp and enter a **steak** restaurant. Check `Player.log` for
   `[BRIDGE] input system online`.
3. Run, then play normally:

```powershell
python python\livecheck.py --json runs\live\check.json
```

A live checklist refreshes every three seconds. Twenty-one falsifiable claims,
each marked the moment its evidence arrives. To settle all of them: walk
around, put a raw steak on a hob, let one reach Well-done, plate one, serve a
customer, let them eat, wash the plate, and start a day while it runs.

**PENDING is not a pass.** A check whose trigger never happened says so.

The one to watch is `cook_timings`. The four steak stage durations are the only
numbers in the project taken from the knowledge base and never observed, and
this prints the measured rate against the prior. If it fails, the fix is
`docs/steak-recipe.md` section 3 and `steak.CUTS`; nothing else depends on
them, because the live controller reads `rate` directly.

While you are there, record the day - it costs nothing extra and gives the
project its first real steak demonstration:

```powershell
python python\demo_record.py record runs\demos\steak\day1-01.jsonl --recipe steak --scenario day1
```

```powershell
python python\demo_record.py verify runs\demos\steak\day1-01.jsonl
```

```powershell
python python\dataset.py demo runs\datasets\human.npz runs\demos\steak\day1-01.jsonl
```

### Tier 3 - live, the agent drives

Only after tier 2 is clean. Start in **Practice** so a failure costs nothing.

1. Enter Practice, press **F9**.
2. Run for a few minutes with a hard time limit:

```powershell
python python\service.py run --minutes 3 --capability runs\capability\live.json
```

It refuses a kitchen that is not serving steak, waits for F9 rather than
sending commands nobody is listening to, prints a status line, and releases
every control on any exit. Ctrl+C is safe, and the mod's own watchdog zeroes
input after 120 quiet ticks regardless.

Watch for: does it walk to the meat source, cook, plate, deliver, and wash? The
two most likely first failures are the aiming mode (`StopMoving` may not leave
`Movement` intact - the controller flips it after three failed presses on its
own) and route choices around chairs.

When it ends it prints a capability table. Compare it with the model's:

```powershell
python python\manifest.py runs\manifests\live.json --artifact runs\capability\live.json --note "first live run"
```

That difference is the first honest measurement of how wrong `mockgame` is, and
it is what the surrogate's section 9.4 validation needs. Log the result in
[`docs/verified-successes.md`](docs/verified-successes.md) either way - the
working agreement in `AGENTS.md` requires failures to be retained too.

## Steak agent

The layers between the bridge and a policy. All of them resolve item,
appliance and process identities by name through the connection's `dict`
frame, never by hardcoded ID.

| Module | What it is |
| --- | --- |
| `python/steak.py` | The steak chain, doneness policy, and checked name resolution |
| `python/kitchen.py` | Reach, aim, occupancy, routes, and appliance roles |
| `python/options.py` | Options: navigate, acquire, place, operate, serve, watch-cook, bin, start-day |
| `python/service.py` | Reference planner and the loop that runs it, live or offline |
| `python/capability.py` | Measured option durations and failure rates |
| `python/surrogate.py` | Semi-MDP over options, calibrated from the registry |
| `python/encode.py` | Fixed-size observation vector |
| `python/env.py` | Gymnasium-compatible environment; gymnasium itself is optional |
| `python/mockgame.py` | Tick-level **model** of the game, for running offline |
| `python/facts.py` | Re-derives observation facts from the recorded artifacts |
| `python/livecheck.py` | Read-only live verification of every offline assumption |
| `python/manifest.py` | Run manifests: code, schemas, build and artifact hashes |
| `python/dataset.py` | Behaviour-cloning datasets, from demonstrations or the model |
| `python/policy.py` | A goal-conditioned cloned policy; NumPy, no framework |
| `python/dagger.py` | Labels the states the policy actually visits |
| `python/evaluate.py` | The specification's metric set, with confidence intervals |
| `python/antihack.py` | The specification's reward-hacking adversaries |
| `python/manifest.py` | Run manifests: code, schemas, build and artifact hashes |
| `python/selftest.py` | The offline gate over all of the above |

`service.py` and the motor control in `options.py` are a **scripted baseline**,
not the agent. Specification §2.3 disallows scripted cook-plate-serve control
and deterministic pathfinding inside a scored run. They exist to build training
data, to measure the capability registry, and to be the baseline a learned
policy is compared against.

A learned motor policy runs under that planner and is measured against it. It
completes the modelled day but serves fewer groups than the baseline, so the
Phase G gate is **not** met. The measured progression and the eight findings
that produced it are in
[`docs/learning-pipeline.md`](docs/learning-pipeline.md), and the method-change
decision the specification requires instead of a longer run is in
[`docs/phase-g-decision.md`](docs/phase-g-decision.md).

The split diagnostic is the load-bearing measurement: give the policy the
buttons and a scripted route and it reaches parity; give it movement and
scripted buttons and it does not. The gap is movement.

The interaction model is worth stating once, because it drives everything:
`AttemptInteraction` projects a point 0.7 units ahead along the **movement**
vector and takes the nearest interactive within 0.7 of it, so aiming and
walking are the same channel and a stance is only useful if the intended
target is also the nearest thing to that point.

### Offline, no game required

```powershell
python python\selftest.py
```

```powershell
python python\facts.py
```

```powershell
python python\service.py mock --episodes 8
```

The mock accepts pressure knobs, which is how three planner deadlocks were
found without a game running: `--plates`, `--groups`, `--interval`,
`--day-length`, `--min-stage` (1 Rare, 2 Medium, 3 Well-done) and
`--watch-hob` (stand at the hob for the whole cook instead of working through
it).

```powershell
python python\env.py check
```

```powershell
python python\env.py soak --steps 20000
```

```powershell
python python\surrogate.py compare runs\capability\mock-reference.json
```

```powershell
python python\antihack.py
```

Train and score a policy, all offline:

```powershell
python python\dataset.py model runs\datasets\reference-goal.npz --episodes 14
```

```powershell
python python\policy.py train runs\datasets\reference-goal.npz runs\policies\bc-goal.npz
```

```powershell
python python\evaluate.py compare runs\policies\bc-goal.npz --episodes 20
```

`mockgame` is a model built from the two recordings, not the game. A pass means
the code is coherent and agrees with those recordings; it is not evidence about
PlateUp, and every command above says so in its output.

### Live

```powershell
python python\service.py run --capability runs\capability\live.json
```

Requires PlateUp in a restaurant with the mod loaded and F9 override on.

## Next

1. **Run the agent live.** Nothing in the steak stack has touched PlateUp. The
   first live `service.py run` inside Practice, writing a capability registry
   from real trials, is what turns any of it into evidence.
2. Compare the live registry against `runs/capability/mock-reference.json`.
   That difference is the first honest measurement of how wrong the offline
   model is, and the surrogate's §9.4 validation depends on it.
3. Close the Phase G motor gate. The learned policy completes the modelled day
   but serves one group where the baseline serves four; the next steps in
   priority order are in [`docs/learning-pipeline.md`](docs/learning-pipeline.md)
   §7. Real-game motor training remains restricted to 1x.
4. Train the task planner in the surrogate (§10.4), which is what removes the
   remaining scripted half.
5. Optionally run the recipe benchmark and replace the scope decision with a
   measurement.

Still open: the 100,000-command formal soak remains FAIL/PENDING after one
600-frame position freeze, and must close before any unattended training run.
The popup-capture transition soak is inconclusive.
