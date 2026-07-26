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

## Protocol

Observation, ~12 Hz:

```json
{"protocol":1,"tick":8412,"in_restaurant":true,"paused":false,"override":true,
 "players":[{"id":1,"x":1.1,"z":-1.5,"rot_y":90.0,"holding":false,"captured":false}],
 "interactives":[{"e":142,"x":2.0,"z":-1.0}]}
```

Action, any rate:

```json
{"MoveX":1.0,"MoveY":0.0,"Grab":false,"Interact":false,"StopMoving":false,"Request":"None"}
```

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

The fix is the Harmony postfix on `BaseInputSource.GetCurrentInputData`, which makes both branches return the same injected state. Buttons still go through the sanctioned queue path so the authoritative side stays consistent.

## Findings that constrain the design

**15-second liveness timer.** `Player.DeactivationProgress` increases every frame and is only reset by `ReportNewInput()`. Past 15 seconds, `PlayerManager` disconnects the player. The bridge therefore enqueues every tick even when idle — the heartbeat is structural, not optional. An idle or wedged policy would otherwise drop the chef mid-service and look like a bridge crash.

**Movement is also the aim vector.** `AttemptInteraction` projects the interaction point from the player along `Movement` (falling back to facing rotation when neutral), then picks the nearest interactive within `InteractionRadius`. Move and interact are not independent action channels. Reach constants, from `Player.CompleteJoining`: `InteractionOffset = 0.7`, `InteractionRadius = 0.7`.

**Button state machine**, reproduced in `BridgeInputSystem.Advance`, mirrors `InputSource.GetButtonState`:

```text
Up -> Pressed -> Held -> ... -> Released -> Up
Consumed -> Consumed (while down) -> Up
```

Grab fires on `Pressed` only. Interact acts on `Pressed` or `Held`, with `IsHeld` distinguishing them — hold across ticks for chopping and washing.

**Turn latency is real.** `PlayerWalkingComponent` rotates toward the movement vector and only applies force once the facing is within `MaximumFacingSpread`, with a `MovementDeadzone` below which nothing happens. Direction changes cost time. Any surrogate simulator has to model this or it will overestimate throughput.

**Determinism is not available.** Position is computed view-side at render rate and written back to `CPosition` through `ResponseData`. Frame-rate dependent. Drop deterministic replay from the plan; evaluate statistically instead. This also means `timeScale` needs testing for movement fidelity specifically, not just for timer correctness.

**Episode control is an input action.** `PlayerManager.HandleRequest` responds to `InputState.Request`:

| Request | Effect |
| --- | --- |
| `StartPractice` | Sets `CRequestPracticeMode` |
| `QuitSection` | Abandon-restaurant popup |
| `QuitToLobby` | Saves, then quit popup |
| `InLocalMenu` | Adds `CGamePauseRequest` |
| `InstantJoin` | Completes joining |
| `Disconnect` | Drops the player |

Reset does not need menu driving — it goes through the same channel as movement.

**Menus read the same component.** `GenericPopupView`, `EndOfDayPopupView`, `UnlockSelectPopupView`, and `StartDayWarningView` all consume `CInputData`. Card selection, blueprint purchase, and day start are drivable through the `Menu*` buttons already in `InputState`.

**Focus matters.** `InputSource.Update` zeroes input when `Platform.Current.GameHasFocus` is false. The Harmony patch bypasses this for the injected path, but verify before planning unattended overnight training.

`CCaptureInput` / `CCapturePassthrough` mark input as owned by a menu; `AttemptInteraction` early-returns and sets `IsCaptured`. Free phase detection — query it rather than inferring from screen state.

**Demonstration recording, built in.** `IInputConsumer` + `LocalInputSourceConsumers.Consumers` is a registerable interception chain whose `TakeInput(player_id, state)` sees every input before the game does. Use that for the demo recorder rather than writing one.

## Next

- Confirm the walk-to-target demo and record it — first programmatic movement is worth having on tape.
- Widen `BridgeStateSystem`: appliance types, held-item identity, `SDay`, customers, orders. Verify each component name in ILSpy before adding it.
- Add tick acknowledgement and stale-action rejection to the protocol.
- Add episode reset via `Request` + practice mode.
- Add a Gymnasium wrapper.
