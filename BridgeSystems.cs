using System.Text;
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
    /// This system ALWAYS enqueues, even when idle. Player.DeactivationProgress climbs
    /// every frame and is only reset by ReportNewInput(); above 15s the player is
    /// disconnected by PlayerManager. The enqueue is the heartbeat.
    /// </summary>
    [UpdateInGroup(typeof(SimulationSystemGroup), OrderFirst = true)]
    [UpdateBefore(typeof(PlayerManager))]
    public class BridgeInputSystem : GenericSystemBase, IModSystem
    {
        EntityQuery Players;
        PlayerManager Manager;

        // Latest action from Python, held until superseded.
        static BridgeAction _action = new BridgeAction();

        // Our own previous button states, so we can reproduce the game's
        // Up -> Pressed -> Held -> Released -> Up machine (see InputSource.GetButtonState).
        static InputState _previous = InputState.Neutral;

        // Manual test keys, useful before the Python side exists.
        static Vector2 _manualMove = Vector2.zero;
        static bool _manualGrab;
        static bool _manualInteract;

        protected override void Initialise()
        {
            base.Initialise();
            Players = GetEntityQuery(typeof(CPlayer), typeof(CInputData));
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
                _action = new BridgeAction();

            var next = BuildState();
            _previous = next;
            Bridge.Injected = next;

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

        static void HandleDebugKeys()
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

    /// <summary>
    /// Publishes observable state to Python. Runs late so it reports post-simulation values.
    /// Only components confirmed present are read here; widen once the schema is verified.
    /// </summary>
    [UpdateInGroup(typeof(SimulationSystemGroup), OrderLast = true)]
    public class BridgeStateSystem : GenericSystemBase, IModSystem
    {
        EntityQuery Players;
        EntityQuery Interactives;

        // Publish rate. Sim runs ~60Hz; every 5th tick gives ~12Hz, matching the
        // motor_decision_hz target in the spec.
        const int PublishEvery = 5;
        int _frame;

        protected override void Initialise()
        {
            base.Initialise();
            Players = GetEntityQuery(typeof(CPlayer), typeof(CPosition), typeof(CInputData));
            Interactives = GetEntityQuery(typeof(CIsInteractive), typeof(CPosition));
        }

        protected override void OnUpdate()
        {
            if (!Bridge.Connected) return;
            if (++_frame % PublishEvery != 0) return;

            var sb = new StringBuilder(512);
            sb.Append("{\"protocol\":").Append(Bridge.ProtocolVersion);
            sb.Append(",\"tick\":").Append(Bridge.Tick);
            sb.Append(",\"in_restaurant\":").Append(HasSingleton<SLayout>() ? "true" : "false");
            sb.Append(",\"paused\":").Append(base.Time.IsPaused ? "true" : "false");
            sb.Append(",\"override\":").Append(Bridge.Override ? "true" : "false");

            sb.Append(",\"players\":[");
            bool first = true;
            using (var entities = Players.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in entities)
                {
                    CPlayer p; CPosition pos; CInputData input;
                    if (!Require(e, out p)) continue;
                    if (!Require(e, out pos)) continue;
                    Require(e, out input);

                    CItemHolder holder;
                    bool holding = Require(e, out holder) && holder.HeldItem != default(Entity);
                    var rotation = pos.Rotation.value;
                    float rotationY = new Quaternion(
                        rotation.x, rotation.y, rotation.z, rotation.w).eulerAngles.y;

                    if (!first) sb.Append(',');
                    first = false;

                    sb.Append("{\"id\":").Append(p.ID);
                    sb.Append(",\"x\":").Append(F(pos.Position.x));
                    sb.Append(",\"z\":").Append(F(pos.Position.z));
                    sb.Append(",\"rot_y\":").Append(F(rotationY));
                    sb.Append(",\"holding\":").Append(holding ? "true" : "false");
                    sb.Append(",\"captured\":").Append(input.IsCaptured ? "true" : "false");
                    sb.Append('}');
                }
            }
            sb.Append(']');

            sb.Append(",\"interactives\":[");
            first = true;
            using (var entities = Interactives.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in entities)
                {
                    CPosition pos;
                    if (!Require(e, out pos)) continue;

                    if (!first) sb.Append(',');
                    first = false;

                    sb.Append("{\"e\":").Append(e.Index);
                    sb.Append(",\"x\":").Append(F(pos.Position.x));
                    sb.Append(",\"z\":").Append(F(pos.Position.z));
                    sb.Append('}');
                }
            }
            sb.Append(']');

            sb.Append('}');
            Bridge.Send(sb.ToString());
        }

        static string F(float v)
        {
            return v.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);
        }
    }
}
