# PlateUp Bridge — Phase C

Programmatic control of a PlateUp chef from Python. Movement, interaction, and game-state requests, over a named pipe.

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
| Arrows | Move |
| F10 | Grab (hold) |
| F11 | Interact (hold) |

## Observation verification

Leave the bridge override off, play a day by hand, and run:

```powershell
python python/observe.py
```

Compare the summary with the game:

- The held item should change when you pick up or drop something.
- Cooking and chopping progress should increase.
- Burned food should show `!BAD`.
- Patience should fall while customers wait.
- Group and customer counts should match what is visible.

Use `python python/observe.py dump` to print one full observation.

The observer deliberately does not publish `CScheduledCustomer`. Its future
arrival times and group sizes are hidden information under the experiment
contract. State is emitted as flat entity lists; spatial encodings belong in
Python so they can change without rebuilding the mod.

## Protocol

Observation, ~12 Hz:

```json
{"kind":"obs","protocol":1,"tick":8412,"act_tick":8407,
 "input_queue_depth":1,"dropped_frames":0,
 "in_restaurant":true,"paused":false,"override":true,
 "players":[{"id":1,"x":1.1,"z":-1.5,"rot":90.0,"held":null,"captured":false}],
 "appliances":[{"e":4294967438,"aid":123,"layer":0,"x":2.0,"z":-1.0,"rot":0.0}],
 "loose_items":[],"groups":[],"customers":[]}
```

The first message on each connection is a `kind: "dict"` frame containing
appliance, item, and process name maps plus the projected camera basis.
Entity field `e` is `(Version << 32) | Index`, so identities remain unique when
Unity recycles entity indices.

Action, any rate:

```json
{"Tick":8407,"MoveX":1.0,"MoveY":0.0,"Grab":false,
 "Interact":false,"StopMoving":false,"Request":"None"}
```

`act_tick` identifies the action frame enqueued for that simulation step.
While override is active, `input_queue_depth` should remain at `1`.

## How input actually reaches the chef

Worth keeping, because it is not obvious and cost a lot of decompiling.

```text
device / bridge
   -> Player.ReportNewInput(InputState)      // also resets the liveness timer
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
bridge as the only authoritative producer. Buttons still travel through
`Player.ReportNewInput`.

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

`QuitSection`, `QuitToLobby`, `Disconnect`, and unknown values are converted to
`None`; an agent cannot trigger saving or drop the player through this channel.

**Menus read the same component.** `GenericPopupView`, `EndOfDayPopupView`, `UnlockSelectPopupView`, and `StartDayWarningView` all consume `CInputData`. Card selection, blueprint purchase, and day start are drivable through the `Menu*` buttons already in `InputState`.

**Focus matters.** `InputSource.Update` zeroes input when `Platform.Current.GameHasFocus` is false. The Harmony patch bypasses this for the injected path, but verify before planning unattended overnight training.

`CCaptureInput` / `CCapturePassthrough` mark input as owned by a menu; `AttemptInteraction` early-returns and sets `IsCaptured`. Free phase detection — query it rather than inferring from screen state.

**Demonstration recording, built in.** `IInputConsumer` + `LocalInputSourceConsumers.Consumers` is a registerable interception chain whose `TakeInput(player_id, state)` sees every input before the game does. Use that for the demo recorder rather than writing one.

## Next

- Confirm the walk-to-target demo and record it — first programmatic movement is worth having on tape.
- Widen `BridgeStateSystem` with orders, tables, money, layout, and day outcome.
- Reject stale actions in Python using the `act_tick` acknowledgement.
- Add episode reset via `Request` + practice mode.
- Add a Gymnasium wrapper.
