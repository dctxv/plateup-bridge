using System;
using System.Collections.Generic;
using Controllers;
using HarmonyLib;
using Kitchen;
using UnityEngine;

namespace PlateUpBridge
{
    /// <summary>
    /// PlayerWalkingComponent.UpdateMovement bypasses ECS for the local player:
    ///
    ///     if (is_my_player &amp;&amp; DefaultInputSource.GetCurrentInputData(player_id, out var s) &amp;&amp; !inputs.IsCaptured)
    ///         MovementVector = ... s.Movement ...        // live device
    ///     else
    ///         MovementVector = ... inputs.State.Movement ...   // replicated CInputData
    ///
    /// Injecting CInputData therefore drives interaction (authoritative ECS) but not
    /// locomotion (client-side prediction). This postfix overrides the device read so
    /// both branches converge on the same injected InputState.
    /// </summary>
    [HarmonyPatch(typeof(BaseInputSource), nameof(BaseInputSource.GetCurrentInputData))]
    public static class GetCurrentInputDataPatch
    {
        // 'out' parameters are declared as 'ref' in Harmony patch signatures.
        static void Postfix(int player_id, ref InputState input_state, ref bool __result)
        {
            if (!Bridge.Override) return;
            input_state = Bridge.Injected;
            __result = true;
        }
    }

    /// <summary>
    /// While bridge control is active, suppress the game's device producer so the
    /// authoritative input queue receives exactly one frame from BridgeInputSystem.
    /// F9 remains available because it is polled through UnityEngine.Input.
    /// </summary>
    [HarmonyPatch(
        typeof(InputSource),
        "SetInputUpdate",
        new Type[] { typeof(int), typeof(bool), typeof(InputState) })]
    public static class SetInputUpdatePatch
    {
        static bool Prefix()
        {
            return !Bridge.Override;
        }
    }

    /// <summary>
    /// Records queue depth immediately before its one-per-tick drain. With bridge
    /// override active this should remain at one.
    /// </summary>
    [HarmonyPatch(typeof(InputQueue), nameof(InputQueue.ApplyUpdates))]
    public static class InputQueueDepthPatch
    {
        static void Prefix(Queue<InputState> ___Queue)
        {
            Bridge.InputQueueDepth = ___Queue.Count;
        }
    }

    public static class BridgePatcher
    {
        const string HarmonyId = "com.clay.plateupbridge";
        static bool _applied;

        public static void ApplyOnce()
        {
            if (_applied) return;
            _applied = true;
            try
            {
                new Harmony(HarmonyId).PatchAll(typeof(BridgePatcher).Assembly);
                Debug.Log("[BRIDGE] harmony patches applied");
            }
            catch (Exception ex)
            {
                Debug.LogError("[BRIDGE] harmony patch failed: " + ex);
            }
        }
    }
}
