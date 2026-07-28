using System.Globalization;
using System.Text;
using Controllers;
using UnityEngine;

namespace PlateUpBridge
{
    /// <summary>
    /// Observes the local device InputState before InputSource sends it to the
    /// game. It never consumes or mutates input. Recording is enabled only by a
    /// connected demo_control client, and every frame carries both a bridge tick
    /// and Unity render-frame identity for later observation alignment.
    /// </summary>
    public sealed class BridgeDemoRecorder : IInputConsumer
    {
        static readonly BridgeDemoRecorder Instance = new BridgeDemoRecorder();
        static bool _registered;

        public static void Register()
        {
            if (_registered) return;
            LocalInputSourceConsumers.Register(Instance);
            _registered = true;
            Debug.Log("[BRIDGE] native input demo recorder registered");
        }

        public InputConsumerState TakeInput(int player_id, InputState state)
        {
            if (!Bridge.Connected || !Bridge.DemoRecording)
                return InputConsumerState.NotConsumed;

            long sequence = ++Bridge.DemoSequence;
            var sb = new StringBuilder(384);
            sb.Append("{\"kind\":\"demo_input\"");
            sb.Append(",\"demo_schema\":\"").Append(Bridge.DemoSchema).Append('"');
            sb.Append(",\"seq\":").Append(sequence);
            sb.Append(",\"tick\":").Append(Bridge.Tick);
            sb.Append(",\"unity_frame\":").Append(Time.frameCount);
            sb.Append(",\"real_time\":").Append(F(Time.realtimeSinceStartup));
            sb.Append(",\"player\":").Append(player_id);
            sb.Append(",\"move_x\":").Append(F(state.Movement.x));
            sb.Append(",\"move_y\":").Append(F(state.Movement.y));
            sb.Append(",\"interact\":").Append((int)state.InteractAction);
            sb.Append(",\"grab\":").Append((int)state.GrabAction);
            sb.Append(",\"secondary1\":").Append((int)state.SecondaryAction1);
            sb.Append(",\"secondary2\":").Append((int)state.SecondaryAction2);
            sb.Append(",\"stop\":").Append((int)state.StopMoving);
            sb.Append(",\"menu_trigger\":").Append((int)state.MenuTrigger);
            sb.Append(",\"menu_up\":").Append((int)state.MenuUp);
            sb.Append(",\"menu_down\":").Append((int)state.MenuDown);
            sb.Append(",\"menu_left\":").Append((int)state.MenuLeft);
            sb.Append(",\"menu_right\":").Append((int)state.MenuRight);
            sb.Append(",\"menu_select\":").Append((int)state.MenuSelect);
            sb.Append(",\"menu_cancel\":").Append((int)state.MenuCancel);
            sb.Append(",\"request\":").Append((int)state.Request);
            sb.Append('}');
            Bridge.Send(sb.ToString());
            return InputConsumerState.NotConsumed;
        }

        static string F(float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value)) return "0";
            return value.ToString("0.######", CultureInfo.InvariantCulture);
        }
    }
}
