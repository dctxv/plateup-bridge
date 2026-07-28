using Controllers;
using Kitchen;
using KitchenMods;
using Newtonsoft.Json;
using Unity.Collections;
using Unity.Entities;
using UnityEngine;

namespace PlateUpBridge
{
    public class BridgeControlFrame
    {
        public string Kind;
        public bool Enabled;
    }

    /// <summary>
    /// Drives the player. Runs once per sim tick, immediately before PlayerManager,
    /// which is where Player.Update() -> InputQueue.ApplyUpdates() -> UpdateToEntity()
    /// happens. One enqueue per tick, one dequeue per tick, so we stay well under
    /// InputQueue.QueueAggregationLimit (5).
    ///
    /// While override is active, this system is the only input producer and enqueues
    /// exactly once per tick. The enqueue is also the heartbeat that prevents the
    /// player's 15-second liveness timer from expiring. With override off it is passive.
    /// </summary>
    [UpdateInGroup(typeof(SimulationSystemGroup), OrderFirst = true)]
    [UpdateBefore(typeof(PlayerManager))]
    public class BridgeInputSystem : GenericSystemBase, IModSystem
    {
        EntityQuery Players;
        PlayerManager Manager;

        // Latest action from Python, held until superseded.
        static readonly BridgeAction NeutralAction = new BridgeAction();
        BridgeAction _action = NeutralAction;

        // Our own previous button states, so we can reproduce the game's
        // Up -> Pressed -> Held -> Released -> Up machine (see InputSource.GetButtonState).
        InputState _previous = InputState.Neutral;

        // Manual test keys, useful before the Python side exists.
        Vector2 _manualMove = Vector2.zero;
        bool _manualGrab;
        bool _manualInteract;
        bool _manualReady;
        GameStateRequest _previousRequest = GameStateRequest.None;

        protected override void Initialise()
        {
            base.Initialise();
            Players = GetEntityQuery(
                ComponentType.ReadOnly<CPlayer>(),
                ComponentType.ReadOnly<CInputData>());
            Bridge.AppliedActionTick = -1;
            Bridge.InputQueueDepth = 0;
            BridgePatcher.ApplyOnce();
            BridgeDemoRecorder.Register();
            Bridge.Start();
            Debug.Log("[BRIDGE] input system online. F5/F6/F7 speed 1x/2x/3x, F8 ready, F9 override, F10 grab, F11 interact, arrows move");
        }

        protected override void OnUpdate()
        {
            Bridge.Tick++;
            HandleDebugKeys();

            if (Bridge.ResetInjectedInput)
            {
                _action = NeutralAction;
                _previous = InputState.Neutral;
                _previousRequest = GameStateRequest.None;
                Bridge.Injected = InputState.Neutral;
                Bridge.ResetInjectedInput = false;
            }

            if (Bridge.ResetCommandReceipts)
            {
                _action = NeutralAction;
                _previous = InputState.Neutral;
                _previousRequest = GameStateRequest.None;
                Bridge.Injected = InputState.Neutral;
                Bridge.LastActionTick = Bridge.Tick;
                Bridge.LastCommandId = 0;
                Bridge.CommandsApplied = 0;
                Bridge.CommandsDropped = 0;
                Bridge.DemoRecording = false;
                Bridge.DemoSequence = 0;
                Bridge.ResetCommandReceipts = false;
            }

            // Pull the newest action; discard any backlog so we never lag behind.
            string line;
            bool received = false;
            while (Bridge.Inbound.TryDequeue(out line))
            {
                try
                {
                    var control = JsonConvert.DeserializeObject<BridgeControlFrame>(line);
                    if (control != null &&
                        string.Equals(
                            control.Kind, "demo_control",
                            System.StringComparison.OrdinalIgnoreCase))
                    {
                        bool enabled = control.Enabled && Bridge.Connected;
                        if (enabled && !Bridge.DemoRecording)
                            Bridge.DemoSequence = 0;
                        Bridge.DemoRecording = enabled;
                        Bridge.Send(
                            "{\"kind\":\"demo_status\",\"demo_schema\":\""
                            + Bridge.DemoSchema
                            + "\",\"enabled\":"
                            + (enabled ? "true" : "false")
                            + ",\"tick\":" + Bridge.Tick + "}");
                        Debug.Log("[BRIDGE] demo recording=" + enabled);
                        continue;
                    }

                    var a = JsonConvert.DeserializeObject<BridgeAction>(line);
                    if (a == null) continue;
                    if (received) Bridge.CommandsDropped++;
                    _action = a;
                    received = true;
                }
                catch { /* malformed frame, ignore */ }
            }
            if (received)
            {
                Bridge.LastActionTick = Bridge.Tick;
                Bridge.LastCommandId = _action.CommandId;
                Bridge.CommandsApplied++;
            }

            // Watchdog: if the client goes quiet, stop moving but keep the heartbeat alive.
            if (Bridge.Connected && Bridge.Tick - Bridge.LastActionTick > 120)
                _action = NeutralAction;

            var next = BuildState();
            _previous = next;
            Bridge.Injected = next;
            Bridge.AppliedActionTick = -1;

            if (!Bridge.Override)
            {
                _previousRequest = GameStateRequest.None;
                return;
            }

            if (Manager == null) Manager = World.GetExistingSystem<PlayerManager>();
            if (Manager == null) return;

            // GameStateRequest is not consumed from CInputData. The game's native
            // command router sends it through PlayerManager.HandleNewInputData(),
            // which calls HandleRequest() before enqueuing the same InputState.
            // Route bridge input through that public entry point too. A held request
            // is dispatched once; normal buttons and movement still enqueue each tick.
            var requested = next.Request;
            bool dispatchRequest =
                requested != GameStateRequest.None &&
                _previousRequest == GameStateRequest.None;
            _previousRequest = requested;

            bool firstPlayer = true;
            using (var entities = Players.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in entities)
                {
                    CPlayer p;
                    if (!Require(e, out p)) continue;

                    var routed = next;
                    routed.Request =
                        firstPlayer && dispatchRequest
                            ? requested
                            : GameStateRequest.None;
                    firstPlayer = false;

                    Manager.HandleNewInputData(new UserInputUpdate
                    {
                        SourceIdentifier = p.InputSource,
                        Data = new InputUpdateEvent
                        {
                            User = p.ID,
                            State = routed
                        }
                    });
                    Bridge.AppliedActionTick = Bridge.Connected ? _action.Tick : -1;
                }
            }
        }

        InputState BuildState()
        {
            bool driving = Bridge.Override;

            var move = driving
                ? (Bridge.Connected ? new Vector2(_action.MoveX, _action.MoveY) : _manualMove)
                : Vector2.zero;

            bool grab = driving && (Bridge.Connected ? _action.Grab : _manualGrab);
            bool interact = driving && (Bridge.Connected ? _action.Interact : _manualInteract);
            // StartDayWarningView consumes Controls.Interact3, represented by
            // SecondaryAction1. Ready is a semantic alias for that same button.
            bool sec1 = driving && (
                Bridge.Connected
                    ? (_action.Secondary1 || _action.Ready)
                    : _manualReady);
            bool sec2 = driving && Bridge.Connected && _action.Secondary2;
            bool stop = driving && Bridge.Connected && _action.StopMoving;
            bool menuSelect = driving && Bridge.Connected && _action.MenuSelect;
            bool menuCancel = driving && Bridge.Connected && _action.MenuCancel;
            bool menuUp = driving && Bridge.Connected && _action.MenuUp;
            bool menuDown = driving && Bridge.Connected && _action.MenuDown;
            bool menuLeft = driving && Bridge.Connected && _action.MenuLeft;
            bool menuRight = driving && Bridge.Connected && _action.MenuRight;

            var s = InputState.Neutral;
            s.Movement = move;
            s.GrabAction = Advance(_previous.GrabAction, grab);
            s.InteractAction = Advance(_previous.InteractAction, interact);
            s.SecondaryAction1 = Advance(_previous.SecondaryAction1, sec1);
            s.SecondaryAction2 = Advance(_previous.SecondaryAction2, sec2);
            s.StopMoving = Advance(_previous.StopMoving, stop);
            s.MenuSelect = Advance(_previous.MenuSelect, menuSelect);
            s.MenuCancel = Advance(_previous.MenuCancel, menuCancel);
            s.MenuUp = Advance(_previous.MenuUp, menuUp);
            s.MenuDown = Advance(_previous.MenuDown, menuDown);
            s.MenuLeft = Advance(_previous.MenuLeft, menuLeft);
            s.MenuRight = Advance(_previous.MenuRight, menuRight);
            s.Request = (driving && Bridge.Connected) ? _action.ParsedRequest() : GameStateRequest.None;
            return s;
        }

        /// <summary>Mirrors InputSource.GetButtonState exactly.</summary>
        static ButtonState Advance(ButtonState old, bool down)
        {
            if (old == ButtonState.Consumed)
                return down ? ButtonState.Consumed : ButtonState.Up;
            if (down)
                return (old == ButtonState.Held || old == ButtonState.Pressed)
                    ? ButtonState.Held : ButtonState.Pressed;
            return (old == ButtonState.Up || old == ButtonState.Released)
                ? ButtonState.Up : ButtonState.Released;
        }

        void HandleDebugKeys()
        {
            if (Input.GetKeyDown(KeyCode.F9))
            {
                Bridge.Override = !Bridge.Override;
                Debug.Log("[BRIDGE] override=" + Bridge.Override);
            }

            _manualGrab = Input.GetKey(KeyCode.F10);
            _manualInteract = Input.GetKey(KeyCode.F11);
            _manualReady = Input.GetKey(KeyCode.F8);
            if (Input.GetKeyDown(KeyCode.F5)) SetGameSpeed(1f);
            if (Input.GetKeyDown(KeyCode.F6)) SetGameSpeed(2f);
            if (Input.GetKeyDown(KeyCode.F7)) SetGameSpeed(3f);

            float x = 0f, y = 0f;
            if (Input.GetKey(KeyCode.RightArrow)) x += 1f;
            if (Input.GetKey(KeyCode.LeftArrow)) x -= 1f;
            if (Input.GetKey(KeyCode.UpArrow)) y += 1f;
            if (Input.GetKey(KeyCode.DownArrow)) y -= 1f;
            _manualMove = new Vector2(x, y);
        }

        void SetGameSpeed(float speed)
        {
            SGameTime gameTime;
            if (!TryGetSingleton(out gameTime)) return;
            gameTime.GameSpeed = speed;
            SetSingleton(gameTime);
            Debug.Log("[BRIDGE] game speed=" + speed + "x");
        }
    }

}
