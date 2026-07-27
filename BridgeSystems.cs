using Controllers;
using Kitchen;
using KitchenMods;
using Newtonsoft.Json;
using Unity.Collections;
using Unity.Entities;
using UnityEngine;

namespace PlateUpBridge
{
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

        protected override void Initialise()
        {
            base.Initialise();
            Players = GetEntityQuery(
                ComponentType.ReadOnly<CPlayer>(),
                ComponentType.ReadOnly<CInputData>());
            Bridge.AppliedActionTick = -1;
            Bridge.InputQueueDepth = 0;
            BridgePatcher.ApplyOnce();
            Bridge.Start();
            Debug.Log("[BRIDGE] input system online. F9 = toggle override, F10 = grab, F11 = interact, arrows = move");
        }

        protected override void OnUpdate()
        {
            Bridge.Tick++;
            HandleDebugKeys();

            // Pull the newest action; discard any backlog so we never lag behind.
            string line;
            while (Bridge.Inbound.TryDequeue(out line))
            {
                try
                {
                    var a = JsonConvert.DeserializeObject<BridgeAction>(line);
                    if (a != null) { _action = a; Bridge.LastActionTick = Bridge.Tick; }
                }
                catch { /* malformed frame, ignore */ }
            }

            // Watchdog: if the client goes quiet, stop moving but keep the heartbeat alive.
            if (Bridge.Connected && Bridge.Tick - Bridge.LastActionTick > 120)
                _action = NeutralAction;

            var next = BuildState();
            _previous = next;
            Bridge.Injected = next;
            Bridge.AppliedActionTick = -1;

            if (!Bridge.Override) return;

            if (Manager == null) Manager = World.GetExistingSystem<PlayerManager>();
            if (Manager == null) return;

            using (var entities = Players.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in entities)
                {
                    CPlayer p;
                    if (!Require(e, out p)) continue;

                    Player player;
                    if (!Manager.GetPlayer(p.ID, out player, false)) continue;

                    player.ReportNewInput(next);
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
            bool sec1 = driving && Bridge.Connected && _action.Secondary1;
            bool sec2 = driving && Bridge.Connected && _action.Secondary2;
            bool stop = driving && Bridge.Connected && _action.StopMoving;

            var s = InputState.Neutral;
            s.Movement = move;
            s.GrabAction = Advance(_previous.GrabAction, grab);
            s.InteractAction = Advance(_previous.InteractAction, interact);
            s.SecondaryAction1 = Advance(_previous.SecondaryAction1, sec1);
            s.SecondaryAction2 = Advance(_previous.SecondaryAction2, sec2);
            s.StopMoving = Advance(_previous.StopMoving, stop);
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

            float x = 0f, y = 0f;
            if (Input.GetKey(KeyCode.RightArrow)) x += 1f;
            if (Input.GetKey(KeyCode.LeftArrow)) x -= 1f;
            if (Input.GetKey(KeyCode.UpArrow)) y += 1f;
            if (Input.GetKey(KeyCode.DownArrow)) y -= 1f;
            _manualMove = new Vector2(x, y);
        }
    }

}
