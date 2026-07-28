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
    /// Publishes observable game state to Python. Schema obs_0.1.
    ///
    /// Two message kinds:
    ///   {"kind":"dict",...}  sent once per connection. Maps appliance/item/process
    ///                        IDs to names so per-tick frames can stay compact.
    ///   {"kind":"obs",...}   sent at PublishEvery ticks.
    ///
    /// FAIRNESS: only fields a human can see are emitted. Notably CScheduledCustomer
    /// (future arrival times and group sizes) is deliberately NOT published -- that is
    /// hidden information under the experiment contract.
    ///
    /// Entities are sorted by index before serialisation. ToEntityArray does not
    /// guarantee stable ordering across frames, and an encoder that reads by list
    /// position would otherwise see its inputs shuffle.
    /// </summary>
    [UpdateInGroup(typeof(SimulationSystemGroup), OrderLast = true)]
    public class BridgeStateSystem : GenericSystemBase, IModSystem
    {
        EntityQuery PlayerQ, ApplianceQ, LooseItemQ, GroupQ, CustomerQ, CaptureQ;

        const int PublishEvery = 6;   // sim ~60Hz -> ~10Hz, matching motor_decision_hz
        int _frame;
        bool _dictSent;
        readonly StringBuilder _observation = new StringBuilder(4096);
        readonly List<Entity> _sorted = new List<Entity>(256);

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
            CaptureQ = GetEntityQuery(new QueryHelper()
                .All(ComponentType.ReadOnly<CCaptureInput>())
                .None(ComponentType.ReadOnly<CCapturePassthrough>()));
        }

        protected override void OnUpdate()
        {
            if (!Bridge.Connected) { _dictSent = false; return; }
            if (Bridge.ResetCommandReceipts) return;
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
            AppendGroups(sb);
            AppendCustomers(sb);

            sb.Append('}');
            Bridge.Send(sb.ToString());
        }

        // ---------- globals ----------

        void AppendGlobals(StringBuilder sb)
        {
            sb.Append(",\"in_restaurant\":").Append(B(HasSingleton<SLayout>()));
            sb.Append(",\"practice_mode\":").Append(B(HasSingleton<SPracticeMode>()));
            sb.Append(",\"paused\":").Append(B(base.Time.IsPaused));
            sb.Append(",\"override\":").Append(B(Bridge.Override));
            sb.Append(",\"input_captured\":").Append(B(!CaptureQ.IsEmpty));
            sb.Append(",\"ack_command\":").Append(Bridge.LastCommandId);
            sb.Append(",\"cmds_applied\":").Append(Bridge.CommandsApplied);
            sb.Append(",\"cmds_dropped\":").Append(Bridge.CommandsDropped);
            sb.Append(",\"outbound_frames_dropped\":")
                .Append(Bridge.DroppedOutboundFrames);

            SGameTime gameTime;
            if (TryGetSingleton(out gameTime))
            {
                sb.Append(",\"game_speed\":").Append(F(gameTime.GameSpeed));
                sb.Append(",\"game_total_time\":").Append(F(gameTime.TotalTime));
                sb.Append(",\"real_total_time\":").Append(F(gameTime.RealTotalTime));
            }

            SDay day;
            if (TryGetSingleton(out day)) sb.Append(",\"day\":").Append(day.Day);

            STime time;
            if (TryGetSingleton(out time))
            {
                sb.Append(",\"time_of_day\":").Append(F(time.TimeOfDay));
                sb.Append(",\"time_unbounded\":").Append(F(time.TimeOfDayUnbounded));
                sb.Append(",\"seconds_elapsed\":").Append(F(time.SecondsSinceDayBegan));
                sb.Append(",\"day_length\":").Append(F(time.DayLength));
            }

            SMoney money;
            if (TryGetSingleton(out money)) sb.Append(",\"money\":").Append(money.Amount);

            SKitchenStatus status;
            if (TryGetSingleton(out status))
                sb.Append(",\"lives\":").Append(status.RemainingLives);

            SGameOver over;
            if (TryGetSingleton(out over))
            {
                sb.Append(",\"game_over\":true");
                sb.Append(",\"loss_reason\":").Append((int)over.Reason);
            }
            else sb.Append(",\"game_over\":false");

            SStartDayWarnings warnings;
            if (TryGetSingleton(out warnings))
            {
                sb.Append(",\"start_day_warnings\":{");
                CPlayersReadyToStart ready;
                if (TryGetSingleton(out ready))
                    sb.Append("\"players_ready\":").Append(B(ready.Ready)).Append(',');
                sb.Append("\"popups_open\":").Append((int)warnings.PopupsOpen);
                sb.Append(",\"selling_required_appliance\":")
                    .Append((int)warnings.SellingRequiredAppliance);
                sb.Append(",\"table_size\":").Append((int)warnings.TableSize);
                sb.Append(",\"players_not_ready\":")
                    .Append((int)warnings.PlayersNotReady);
                sb.Append(",\"post_unopened\":").Append((int)warnings.PostUnopened);
                sb.Append(",\"more_than_one_table\":")
                    .Append((int)warnings.MoreThanOneTable);
                sb.Append(",\"players_in_crane_mode\":")
                    .Append((int)warnings.PlayersInCraneMode);
                sb.Append('}');
            }
        }

        // ---------- players ----------

        void AppendPlayers(StringBuilder sb)
        {
            sb.Append(",\"players\":[");
            bool first = true;
            foreach (var e in Sorted(PlayerQ))
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

                CPlayerDirtyShoes shoes;
                if (Require(e, out shoes) && shoes.TimeUntil > 0f)
                    sb.Append(",\"dirty_shoes\":").Append(F(shoes.TimeUntil));

                sb.Append('}');
            }
            sb.Append(']');
        }

        // ---------- appliances ----------

        void AppendAppliances(StringBuilder sb)
        {
            sb.Append(",\"appliances\":[");
            bool first = true;
            foreach (var e in Sorted(ApplianceQ))
            {
                CAppliance app; CPosition pos;
                if (!Require(e, out app) || !Require(e, out pos)) continue;

                Sep(sb, ref first);
                sb.Append("{\"e\":\"").Append(EId(e)).Append('"');
                sb.Append(",\"aid\":").Append(app.ID);
                sb.Append(",\"layer\":").Append((int)app.Layer);
                AppendPose(sb, pos);

                CItemHolder holder;
                if (Require(e, out holder) && holder.HeldItem != default(Entity))
                {
                    sb.Append(",\"held\":");
                    AppendItem(sb, holder.HeldItem);
                }

                CItemProvider prov;
                if (Require(e, out prov))
                {
                    sb.Append(",\"provides\":").Append(prov.ProvidedItem);
                    sb.Append(",\"available\":").Append(prov.Available);
                    sb.Append(",\"maximum\":").Append(prov.Maximum);
                }

                CTableSet table;
                if (Require(e, out table))
                {
                    sb.Append(",\"is_table\":true");
                    sb.Append(",\"chairs\":").Append(table.ChairCount);
                    sb.Append(",\"waiting_table\":").Append(B(table.IsWaitingTable));
                }

                CItemHolderFilter filter;
                if (Require(e, out filter))
                {
                    sb.Append(",\"accepts_any\":").Append(B(filter.AllowAny));
                    sb.Append(",\"accepts_cat\":").Append((int)filter.Category);
                }

                CItemHolderOnlySpecificItem only;
                if (Require(e, out only))
                    sb.Append(",\"accepts_only\":").Append(only.ItemID);

                // Storage contents (cupboards, dish racks).
                DynamicBuffer<CItemStored> stored;
                if (RequireBuffer(e, out stored) && stored.Length > 0)
                {
                    sb.Append(",\"stored\":[");
                    for (int i = 0; i < stored.Length; i++)
                    {
                        if (i > 0) sb.Append(',');
                        sb.Append('"').Append(EId(stored[i].StoredItem)).Append('"');
                    }
                    sb.Append(']');
                }

                if (Has<CIsOnFire>(e)) sb.Append(",\"on_fire\":true");
                if (Has<CIsBroken>(e)) sb.Append(",\"broken\":true");
                if (Has<CIsInactive>(e)) sb.Append(",\"inactive\":true");

                sb.Append('}');
            }
            sb.Append(']');
        }

        // ---------- items ----------

        void AppendLooseItems(StringBuilder sb)
        {
            sb.Append(",\"loose_items\":[");
            bool first = true;
            foreach (var e in Sorted(LooseItemQ))
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
            sb.Append("\"e\":\"").Append(EId(e)).Append('"');

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

            // IsBad means the current process leads to a worse state; it does not
            // necessarily mean the current item is already ruined.
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

        void AppendGroups(StringBuilder sb)
        {
            sb.Append(",\"groups\":[");
            bool first = true;
            foreach (var e in Sorted(GroupQ))
            {
                CPosition pos;
                if (!Require(e, out pos)) continue;

                Sep(sb, ref first);
                sb.Append("{\"e\":\"").Append(EId(e)).Append('"');
                sb.Append(",\"x\":").Append(F(pos.Position.x));
                sb.Append(",\"z\":").Append(F(pos.Position.z));

                CPatience pat;
                if (Require(e, out pat))
                {
                    sb.Append(",\"patience_active\":").Append(B(pat.Active));
                    sb.Append(",\"patience_left\":").Append(F(pat.RemainingTime));
                    sb.Append(",\"patience_total\":").Append(F(pat.StartTime));
                    sb.Append(",\"patience_reason\":").Append((int)pat.Reason);
                    sb.Append(",\"patience_rate\":").Append(F(pat.LastUpdateRate));
                }

                CGroupMealPhase phase;
                if (Require(e, out phase))
                    sb.Append(",\"meal_phase\":").Append((int)phase.Phase);

                CAssignedTable assigned;
                if (Require(e, out assigned) && assigned.Table != default(Entity))
                    sb.Append(",\"table\":\"").Append(EId(assigned.Table)).Append('"');

                DynamicBuffer<CGroupMember> members;
                if (RequireBuffer(e, out members))
                    sb.Append(",\"size\":").Append(members.Length);

                DynamicBuffer<CWaitingForItem> orders;
                if (RequireBuffer(e, out orders) && orders.Length > 0)
                {
                    sb.Append(",\"orders\":[");
                    for (int i = 0; i < orders.Length; i++)
                    {
                        if (i > 0) sb.Append(',');
                        var o = orders[i];
                        sb.Append("{\"iid\":").Append(o.ItemID);
                        sb.Append(",\"member\":").Append(o.MemberIndex);
                        sb.Append(",\"satisfied\":").Append(B(o.Satisfied));
                        sb.Append(",\"is_side\":").Append(B(o.IsSide));
                        sb.Append(",\"reward\":").Append(o.Reward);
                        if (o.DirtItem != 0) sb.Append(",\"dirt\":").Append(o.DirtItem);
                        if (o.ExtraRequested)
                        {
                            sb.Append(",\"extra\":").Append(o.Extra);
                            sb.Append(",\"extra_done\":").Append(B(o.ExtraSatisfied));
                        }
                        if (o.SatisfiedBySharer) sb.Append(",\"by_sharer\":true");
                        sb.Append('}');
                    }
                    sb.Append(']');
                }

                sb.Append('}');
            }
            sb.Append(']');
        }

        void AppendCustomers(StringBuilder sb)
        {
            sb.Append(",\"customers\":[");
            bool first = true;
            foreach (var e in Sorted(CustomerQ))
            {
                CPosition pos;
                if (!Require(e, out pos)) continue;

                Sep(sb, ref first);
                sb.Append("{\"e\":\"").Append(EId(e)).Append('"');
                sb.Append(",\"x\":").Append(F(pos.Position.x));
                sb.Append(",\"z\":").Append(F(pos.Position.z));

                CCustomerState st;
                if (Require(e, out st))
                    sb.Append(",\"state\":").Append((int)st.CurrentState);

                CBelongsToGroup grp;
                if (Require(e, out grp))
                {
                    sb.Append(",\"group\":\"").Append(EId(grp.Group)).Append('"');
                    sb.Append(",\"idx\":").Append(grp.IndexInGroup);
                }

                sb.Append('}');
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

            sb.Append('}');
            Bridge.Send(sb.ToString());
            Debug.Log("[BRIDGE] sent name dictionary");
            return true;
        }

        // ---------- helpers ----------

        List<Entity> Sorted(EntityQuery query)
        {
            _sorted.Clear();
            using (var entities = query.ToEntityArray(Allocator.Temp))
                foreach (var e in entities) _sorted.Add(e);
            _sorted.Sort((a, b) => a.Index.CompareTo(b.Index));
            return _sorted;
        }

        void AppendPose(StringBuilder sb, CPosition pos)
        {
            sb.Append(",\"x\":").Append(F(pos.Position.x));
            sb.Append(",\"z\":").Append(F(pos.Position.z));
            sb.Append(",\"rot\":").Append(F(((Quaternion)pos.Rotation).eulerAngles.y));
        }

        static string EId(Entity e)
        {
            return e.Index + ":" + e.Version;
        }

        static void Sep(StringBuilder sb, ref bool first)
        {
            if (!first) sb.Append(',');
            first = false;
        }

        static string B(bool b) { return b ? "true" : "false"; }

        static string F(float v)
        {
            if (float.IsNaN(v) || float.IsInfinity(v)) return "0";
            return v.ToString("0.###", CultureInfo.InvariantCulture);
        }

        static string Esc(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            var escaped = new StringBuilder(s.Length + 8);
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': escaped.Append("\\\""); break;
                    case '\\': escaped.Append("\\\\"); break;
                    case '\b': escaped.Append("\\b"); break;
                    case '\f': escaped.Append("\\f"); break;
                    case '\n': escaped.Append("\\n"); break;
                    case '\r': escaped.Append("\\r"); break;
                    case '\t': escaped.Append("\\t"); break;
                    default:
                        if (c < 0x20)
                            escaped.Append("\\u").Append(
                                ((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            escaped.Append(c);
                        break;
                }
            }
            return escaped.ToString();
        }
    }
}
