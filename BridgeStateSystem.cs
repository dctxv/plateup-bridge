using System.Collections.Generic;
using System.Globalization;
using System.Text;
using Kitchen;
using KitchenData;
using KitchenMods;
using Unity.Collections;
using Unity.Entities;
using UnityEngine;

namespace PlateUpBridge
{
    /// <summary>
    /// Publishes observable game state to Python.
    ///
    /// Two message kinds:
    ///   {"kind":"dict",...}  sent once per connection. Maps appliance/item/process
    ///                        IDs to names so per-tick frames can stay compact.
    ///   {"kind":"obs",...}   sent at PublishEvery ticks.
    ///
    /// FAIRNESS: only fields a human can see are emitted. Notably CScheduledCustomer
    /// (future arrival times and group sizes) is deliberately NOT published -- that is
    /// hidden information under the experiment contract.
    /// </summary>
    [UpdateInGroup(typeof(SimulationSystemGroup), OrderLast = true)]
    public class BridgeStateSystem : GenericSystemBase, IModSystem
    {
        EntityQuery PlayerQ, ApplianceQ, LooseItemQ, GroupQ, CustomerQ;

        const int PublishEvery = 5;   // sim ~60Hz -> ~12Hz, matching motor_decision_hz
        int _frame;
        bool _dictSent;
        readonly StringBuilder _observation = new StringBuilder(4096);

        protected override void Initialise()
        {
            base.Initialise();

            PlayerQ = GetEntityQuery(
                ComponentType.ReadOnly<CPlayer>(),
                ComponentType.ReadOnly<CPosition>());
            ApplianceQ = GetEntityQuery(
                ComponentType.ReadOnly<CAppliance>(),
                ComponentType.ReadOnly<CPosition>());

            // Items on the floor / in transit: have CItem but are not held or stored.
            LooseItemQ = GetEntityQuery(new QueryHelper()
                .All(ComponentType.ReadOnly<CItem>(), ComponentType.ReadOnly<CPosition>())
                .None(ComponentType.ReadOnly<CHeldBy>(), ComponentType.ReadOnly<CStoredBy>()));

            GroupQ = GetEntityQuery(
                ComponentType.ReadOnly<CCustomerGroup>(),
                ComponentType.ReadOnly<CPosition>());
            CustomerQ = GetEntityQuery(
                ComponentType.ReadOnly<CCustomer>(),
                ComponentType.ReadOnly<CPosition>());
        }

        protected override void OnUpdate()
        {
            if (!Bridge.Connected) { _dictSent = false; return; }
            if (!_dictSent)
            {
                _dictSent = SendDictionary();
                if (!_dictSent) return;
            }
            if (++_frame % PublishEvery != 0) return;

            var sb = _observation;
            sb.Clear();
            sb.Append("{\"kind\":\"obs\",\"protocol\":").Append(Bridge.ProtocolVersion);
            sb.Append(",\"tick\":").Append(Bridge.Tick);

            AppendGlobals(sb);
            AppendPlayers(sb);
            AppendAppliances(sb);
            AppendLooseItems(sb);
            AppendCustomers(sb);

            sb.Append('}');
            Bridge.Send(sb.ToString());
        }

        // ---------- globals ----------

        void AppendGlobals(StringBuilder sb)
        {
            sb.Append(",\"in_restaurant\":").Append(B(HasSingleton<SLayout>()));
            sb.Append(",\"paused\":").Append(B(base.Time.IsPaused));
            sb.Append(",\"override\":").Append(B(Bridge.Override));
            sb.Append(",\"act_tick\":").Append(Bridge.AppliedActionTick);
            sb.Append(",\"input_queue_depth\":").Append(Bridge.InputQueueDepth);
            sb.Append(",\"dropped_frames\":").Append(Bridge.DroppedOutboundFrames);

            SDay day;
            if (TryGetSingleton(out day)) sb.Append(",\"day\":").Append(day.Day);

            STime time;
            if (TryGetSingleton(out time))
                sb.Append(",\"time_of_day\":").Append(F(time.TimeOfDayUnbounded));

            // Any menu/popup currently owning input.
            sb.Append(",\"input_captured\":").Append(B(AnyInputCapture()));
        }

        bool AnyInputCapture()
        {
            var q = GetEntityQuery(new QueryHelper()
                .All(ComponentType.ReadOnly<CCaptureInput>())
                .None(ComponentType.ReadOnly<CCapturePassthrough>()));
            return !q.IsEmpty;
        }

        // ---------- players ----------

        void AppendPlayers(StringBuilder sb)
        {
            sb.Append(",\"players\":[");
            bool first = true;
            using (var es = PlayerQ.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in es)
                {
                    CPlayer p; CPosition pos;
                    if (!Require(e, out p) || !Require(e, out pos)) continue;

                    Sep(sb, ref first);
                    sb.Append("{\"id\":").Append(p.ID);
                    AppendPose(sb, pos);

                    CItemHolder holder;
                    if (Require(e, out holder) && holder.HeldItem != default(Entity))
                    {
                        sb.Append(",\"held\":");
                        AppendItem(sb, holder.HeldItem);
                    }
                    else sb.Append(",\"held\":null");

                    CInputData input;
                    if (Require(e, out input))
                        sb.Append(",\"captured\":").Append(B(input.IsCaptured));

                    sb.Append('}');
                }
            }
            sb.Append(']');
        }

        // ---------- appliances ----------

        void AppendAppliances(StringBuilder sb)
        {
            sb.Append(",\"appliances\":[");
            bool first = true;
            using (var es = ApplianceQ.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in es)
                {
                    CAppliance app; CPosition pos;
                    if (!Require(e, out app) || !Require(e, out pos)) continue;

                    Sep(sb, ref first);
                    sb.Append("{\"e\":").Append(EntityId(e));
                    sb.Append(",\"aid\":").Append(app.ID);
                    sb.Append(",\"layer\":").Append((int)app.Layer);
                    AppendPose(sb, pos);

                    CItemHolder holder;
                    if (Require(e, out holder) && holder.HeldItem != default(Entity))
                    {
                        sb.Append(",\"held\":");
                        AppendItem(sb, holder.HeldItem);
                    }

                    // Ingredient source: what it dispenses and how much is left.
                    CItemProvider prov;
                    if (Require(e, out prov))
                    {
                        sb.Append(",\"provides\":").Append(prov.ProvidedItem);
                        sb.Append(",\"available\":").Append(prov.Available);
                        sb.Append(",\"maximum\":").Append(prov.Maximum);
                    }

                    // Storage contents (cupboards, dish racks).
                    DynamicBuffer<CItemStored> stored;
                    if (RequireBuffer(e, out stored) && stored.Length > 0)
                    {
                        sb.Append(",\"stored\":[");
                        for (int i = 0; i < stored.Length; i++)
                        {
                            if (i > 0) sb.Append(',');
                            AppendItem(sb, stored[i].StoredItem);
                        }
                        sb.Append(']');
                    }

                    if (Has<CIsOnFire>(e)) sb.Append(",\"on_fire\":true");
                    if (Has<CIsBroken>(e)) sb.Append(",\"broken\":true");
                    if (Has<CIsInactive>(e)) sb.Append(",\"inactive\":true");

                    sb.Append('}');
                }
            }
            sb.Append(']');
        }

        // ---------- items ----------

        void AppendLooseItems(StringBuilder sb)
        {
            sb.Append(",\"loose_items\":[");
            bool first = true;
            using (var es = LooseItemQ.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in es)
                {
                    CPosition pos;
                    if (!Require(e, out pos)) continue;

                    Sep(sb, ref first);
                    sb.Append('{');
                    AppendItemBody(sb, e);
                    sb.Append(",\"x\":").Append(F(pos.Position.x));
                    sb.Append(",\"z\":").Append(F(pos.Position.z));
                    sb.Append('}');
                }
            }
            sb.Append(']');
        }

        void AppendItem(StringBuilder sb, Entity e)
        {
            sb.Append('{');
            AppendItemBody(sb, e);
            sb.Append('}');
        }

        void AppendItemBody(StringBuilder sb, Entity e)
        {
            sb.Append("\"e\":").Append(EntityId(e));

            CItem item;
            if (Require(e, out item))
            {
                sb.Append(",\"iid\":").Append(item.ID);
                sb.Append(",\"cat\":").Append((int)item.Category);
                if (item.IsPartial) sb.Append(",\"partial\":true");

                // Composite contents: a plated burger is a plate holding component IDs.
                if (item.Items.Count > 0)
                {
                    sb.Append(",\"items\":[");
                    for (int i = 0; i < item.Items.Count; i++)
                    {
                        if (i > 0) sb.Append(',');
                        sb.Append(item.Items[i]);
                    }
                    sb.Append(']');
                }
            }

            // Cooking / chopping in progress. IsBad is the burn flag.
            CItemUndergoingProcess proc;
            if (Require(e, out proc))
            {
                sb.Append(",\"process\":").Append(proc.Process);
                sb.Append(",\"progress\":").Append(F(proc.Progress));
                sb.Append(",\"is_bad\":").Append(B(proc.IsBad));
                sb.Append(",\"rate\":").Append(F(proc.CurrentChange));
            }
        }

        // ---------- customers ----------

        void AppendCustomers(StringBuilder sb)
        {
            sb.Append(",\"groups\":[");
            bool first = true;
            using (var es = GroupQ.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in es)
                {
                    CPosition pos;
                    if (!Require(e, out pos)) continue;

                    Sep(sb, ref first);
                    sb.Append("{\"e\":").Append(EntityId(e));
                    sb.Append(",\"x\":").Append(F(pos.Position.x));
                    sb.Append(",\"z\":").Append(F(pos.Position.z));

                    CPatience pat;
                    if (Require(e, out pat))
                    {
                        sb.Append(",\"patience_active\":").Append(B(pat.Active));
                        sb.Append(",\"patience_left\":").Append(F(pat.RemainingTime));
                        sb.Append(",\"patience_total\":").Append(F(pat.StartTime));
                        sb.Append(",\"patience_reason\":").Append((int)pat.Reason);
                    }

                    CGroupMealPhase phase;
                    if (Require(e, out phase))
                        sb.Append(",\"meal_phase\":").Append((int)phase.Phase);

                    DynamicBuffer<CGroupMember> members;
                    if (RequireBuffer(e, out members))
                        sb.Append(",\"size\":").Append(members.Length);

                    sb.Append('}');
                }
            }
            sb.Append(']');

            sb.Append(",\"customers\":[");
            first = true;
            using (var es = CustomerQ.ToEntityArray(Allocator.Temp))
            {
                foreach (var e in es)
                {
                    CPosition pos;
                    if (!Require(e, out pos)) continue;

                    Sep(sb, ref first);
                    sb.Append("{\"e\":").Append(EntityId(e));
                    sb.Append(",\"x\":").Append(F(pos.Position.x));
                    sb.Append(",\"z\":").Append(F(pos.Position.z));

                    CCustomerState st;
                    if (Require(e, out st))
                        sb.Append(",\"state\":").Append((int)st.CurrentState);

                    CBelongsToGroup grp;
                    if (Require(e, out grp))
                    {
                        sb.Append(",\"group\":").Append(EntityId(grp.Group));
                        sb.Append(",\"idx\":").Append(grp.IndexInGroup);
                    }

                    sb.Append('}');
                }
            }
            sb.Append(']');
        }

        // ---------- name dictionary ----------

        bool SendDictionary()
        {
            if (Data == null) return false;

            var sb = new StringBuilder(8192);
            sb.Append("{\"kind\":\"dict\",\"protocol\":").Append(Bridge.ProtocolVersion);

            sb.Append(",\"appliances\":{");
            bool first = true;
            foreach (var a in Data.Get<Appliance>())
            {
                Sep(sb, ref first);
                sb.Append('"').Append(a.ID).Append("\":\"").Append(Esc(a.name)).Append('"');
            }
            sb.Append('}');

            sb.Append(",\"items\":{");
            first = true;
            foreach (var i in Data.Get<Item>())
            {
                Sep(sb, ref first);
                sb.Append('"').Append(i.ID).Append("\":\"").Append(Esc(i.name)).Append('"');
            }
            sb.Append('}');

            sb.Append(",\"processes\":{");
            first = true;
            foreach (var p in Data.Get<Process>())
            {
                Sep(sb, ref first);
                sb.Append('"').Append(p.ID).Append("\":\"").Append(Esc(p.name)).Append('"');
            }
            sb.Append('}');

            AppendCameraBasis(sb);

            sb.Append('}');
            Bridge.Send(sb.ToString());
            Debug.Log("[BRIDGE] sent name dictionary");
            return true;
        }

        // ---------- helpers ----------

        void AppendPose(StringBuilder sb, CPosition pos)
        {
            sb.Append(",\"x\":").Append(F(pos.Position.x));
            sb.Append(",\"z\":").Append(F(pos.Position.z));
            sb.Append(",\"rot\":").Append(F(((Quaternion)pos.Rotation).eulerAngles.y));
        }

        void AppendCameraBasis(StringBuilder sb)
        {
            var camera = Camera.main;
            if (camera == null) return;

            var forward = camera.transform.forward;
            var right = camera.transform.right;
            forward.y = 0f;
            right.y = 0f;
            forward.Normalize();
            right.Normalize();

            sb.Append(",\"camera_forward\":[")
                .Append(F(forward.x)).Append(',').Append(F(forward.z)).Append(']');
            sb.Append(",\"camera_right\":[")
                .Append(F(right.x)).Append(',').Append(F(right.z)).Append(']');

            if (Mathf.Abs(forward.x) > 0.01f ||
                Mathf.Abs(forward.z - 1f) > 0.01f ||
                Mathf.Abs(right.x - 1f) > 0.01f ||
                Mathf.Abs(right.z) > 0.01f)
            {
                Debug.LogWarning(
                    "[BRIDGE] non-identity camera basis forward=" + forward +
                    " right=" + right);
            }
        }

        static long EntityId(Entity e)
        {
            return ((long)e.Version << 32) | (uint)e.Index;
        }

        static void Sep(StringBuilder sb, ref bool first)
        {
            if (!first) sb.Append(',');
            first = false;
        }

        static string B(bool b) { return b ? "true" : "false"; }

        static string F(float v)
        {
            return v.ToString("0.###", CultureInfo.InvariantCulture);
        }

        static string Esc(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }
}
