# PlateUp AI Knowledge Base

**Stable baseline:** PlateUp public PC branch, version 1.4.3 mechanics, researched 27 July 2026.

**Purpose:** A Claude-ready reference and telemetry contract for an autonomous PlateUp agent. It extends the hierarchical setup/preparation/service architecture described in the referenced conversation.

**Deliverables:** This Markdown manual, an editable DOCX rendering, and the companion plateup-telemetry.schema.json JSON Schema.

**Provenance limitation:** The previously linked /mnt/data/PLATEUP_AI_FULL_CREATION_SPEC.md was not present in the accessible workspace. The architectural context was reconstructed from the quoted conversation. No claim in this manual depends on the missing file.

**Release boundary:** The official 1.4.3 patch is the stable authority for this document. The 1.4.4 Heat/Chill/Greenhouse work was still described by official announcements as a Taste-Test branch in the material checked for this build, so it is isolated as beta-only and must not enter stable training data unless the session reports branch: taste_test. [S02][S03]

## Contents

1. Scope, version baseline, and evidence rules

2. Claude operating contract

3. PlateUp ontology and run lifecycle

4. Player controls, carried items, tools, and simultaneous actions

5. Surfaces, storage, capacities, and placement rules

6. Customers, groups, patience, urgency, and expected demand

7. Dirt, cleaning, wet floors, buff floors, and fire

8. Recipes and process-state modelling

9. Appliances, equipment, upgrades, and automation

10. Blueprints, research, cards, themes, and decorations

11. Headquarters, setup, restaurant settings, and franchise lifecycle

12. Edge cases, contradictions, and version-sensitive behavior

13. PowerShell/C# telemetry bridge contract

14. Verification harness and acceptance tests

15. Source register

16. Appendices: full recipe process reference, card registry, and appliance index

## 1. Scope, version baseline, and evidence rules

### 1.1 What this knowledge base covers

This manual models:

- Headquarters setup, profile-dependent unlocks, recipes, floorplans, settings, franchises, garage items, and loading bay choices.

- The Preparation, Practice, Customer Service, card-selection, decoration, franchise, and post-run phases.

- Every normal appliance/equipment family listed by the current wiki, plus event-limited enchanted items in a separate registry.

- Food recipes as state transitions, including portions, leftovers, burn states, equipment, extra-item requests, and piecemeal ordering.

- Customer pathing, group-size rules, all patience phases, demand scaling, table capacity, orders, extra requests, and failure.

- Messes, cleaning, water, buff floors, fire, tools, footwear, and actions that remain possible while carrying an item.

- Blueprints, pools, rerolls, cabinets, research/copy/discount, upgrades, cards, themes, decorations, and automation.

- A versioned telemetry schema that exposes live action affordances instead of making Claude guess whether a move is legal.

This is not a promise that prose alone can describe every internal Unity component. When a behavior can vary by build, mod, object state, or recipe, the bridge must expose the live component-derived value.

### 1.2 Evidence labels

| **Label** | **Meaning** | **Agent behavior** |
| --- | --- | --- |
| **A - Official stable** | Official game/patch source for the stable branch. | Treat as baseline unless live build differs. |
| **B - Current** **mechanics** **reference** | Current PlateUp community wiki page, usually with per-page edit history. | Use for mechanics, but allow official patch or live component to override. |
| **C - Derived** **engineering** **rule** | Inference needed to turn mechanics into an AI-safe representation. | Keep provenance and verify through integration tests. |
| **D - Live** **observation** **required** | Conflicting, missing, modded, beta-only, or internal value. | Do not hardcode; read from game or run a probe. |

### 1.3 Source precedence

Use this order when sources disagree:

1. Exact live game component/event data for the recorded Steam build.

2. Official patch notes for that branch and version.

3. Current per-mechanic wiki page.

4. Older wiki pages, old modding docs, videos, guides, and remembered behavior.

5. Inference.

Example: some provider/automation text still refers to a Combiner adding water. The official 1.4.3 patch says sinks, milk dispensers, and ice dispensers no longer auto-fill via that older route and that Portioners are used for automation. This manual therefore records Portioner behavior as stable and marks old Combiner wording stale. [S02]

### 1.4 Version keys that must accompany every run

- Game semantic version and Steam build ID.

- Branch (public_stable, taste_test, or unknown).

- Platform.

- Bridge version and Git commit.

- KitchenLib and dependency versions, if used.

- Mod manifest/hash.

- Observation schema version/hash.

- Recipe/card/appliance semantic registry version.

- Seed and whether the seed affects layout only or everything.

Without these keys, a saved trajectory is not reproducible training data.

## 2. Claude operating contract

### 2.1 Non-negotiable reasoning rules

1. **Live affordances beat static knowledge.** If telemetry says place is unavailable, do not place even if a table in this manual normally accepts portable items.

2. **Do not infer an object from its display name alone.** Use semantic_id, live gdo_id, traits, slots, process states, and source-mod ID.

3. **Separate facts from plans.** A claim such as "the sink can accept this pot" requires a current affordance or a verified mechanic. A plan such as "move to the sink" is not evidence.

4. **Respect phase boundaries.** Appliance movement, purchase, reroll, layout editing, and Ready occur in preparation. Service actions occur during the day. Card/theme/franchise choices are separate phases.

5. **Do not use hidden future data in scored runs.** Future orders, future shop rolls, hidden randomness, and unseen customer outcomes must not be exposed.

6. **Treat partial orders explicitly.** Sandwiches, Sundaes, Tacos, Buffets, sides, multi-course meals, condiments, and extra-item requests can be satisfied incrementally.

7. **Do not compress patience to one number.** Track phase, current/max value, decay, modifiers, visibility, and estimated seconds to failure.

8. **Never silently resolve a source conflict.** Attach a warning, the two sources/builds, and the chosen runtime authority.

9. **Avoid absolute optimization claims.** Optimize the current policy, recipe set, seed distribution, and branch. "Best known under these conditions" is defensible; "perfect PlateUp strategy" is not.

10. **Log every strategic choice and primitive action.** A final result without traceable decisions is not useful for debugging, evaluation, or the video.

### 2.2 Recommended Claude ingestion prompt

```text
You are assisting development of an autonomous PlateUp agent.
Use the live telemetry snapshot as the authoritative state.
Use this knowledge base only to interpret fields, propose tests, and
reason about
mechanics not directly encoded in the current snapshot.
Before recommending or issuing an action:
1. Confirm the current phase.
2. Locate an affordance with available=true for the actor, verb, target,
and item.
3. Check blockers, held-item/tool state, capacity, path reachability,
process state,
customer urgency, and expected consequences.
4. If no live affordance exists, mark the action as an assumption and
request a
bridge probe; do not present it as verified.
When sources conflict, prefer:
live component > official patch > current wiki > older references >
inference.
Preserve game version, Steam build ID, branch, schema version, and
provenance.
```

### 2.3 Static fact record

Every fact imported into a retrieval store should use this shape:

```json
{
"claim_id": "plates.standard.capacity",
"subject": "appliance.plates",
"predicate": "stores_clean_plate_count",
"object": 8,
"unit": "plates",
"evidence_tier": "B",
"version_scope": {
"branch": "public_stable",
"verified_through": "1.4.3"
},
"source_url": "https://wiki.plateupgame.co.uk/appliances/Plates",
"last_observed_build_id": null ,
"conflicts": [],
"notes": "Live provider count still wins."
}
```

## 3. PlateUp ontology and run lifecycle

### 3.1 Core entity types

- **Run:** seed, setting, floorplan, player count, base recipe, franchise state, active cards, coins, day, overtime, and branch.

- **Phase:** Headquarters setup, preparation, practice, service, card/theme/franchise selection, rewards, post-run.

- **Player:** position, facing, velocity, normal carried item(s), equipped hand tool, worn footwear, current interaction, and input ownership.

- **Appliance:** movable restaurant object with live components, processes, upgrade links, effect range, storage slots, orientation, and collision.

- **Equipment/provider:** plate stacks, pots, woks, trays, boards, ingredient sources, tools, and recipe-specific containers.

- **Item:** portable stateful object. It can have a recipe state, portions, cleanliness, burn progress, plating/equipment composition, or leftover state.

- **Surface/slot:** a location that may accept an item. Capacity and accepted traits are live properties, not universal assumptions.

- **Recipe process:** a transition from one or more input states to an output state through Chop, Knead, Cook, Portion, Combine, Add Water, Clean, or another action.

- **Customer group:** shared phase and patience plus members, table/queue target, path, orders, and delivered items.

- **Order:** course and one or more requirements; each requirement lists accepted item states/traits and quantity.

- **Blueprint:** purchasable definition plus cost, copied/upgradable/discountable flags, cabinet location, and pool provenance.

- **Card/theme/setting/franchise modifier:** persistent rule that changes demand, patience, recipes, shop, groups, processes, or setup.

- **Floor tile:** room, edges/walls/doors/hatches, traversal, mess/wet/buffed/fire state, and occupying entities.

### 3.2 Full lifecycle

```text
Headquarters
-> choose fresh run or franchise
-> choose setting
-> choose recipe(s)
-> choose random floorplan, daily/weekly seed, or entered seed
-> choose zero to two garage items
-> start run
Restaurant day
-> Preparation
inspect expected groups and group-size range
open/buy/store/reroll blueprints
rearrange appliances, tables, chairs, automation, and research
optionally enter Practice
intentionally Ready
-> Customer Service
customers spawn, path, queue, sit, order, receive, eat, request
extras, leave
cooking, cleaning, research, booking, automation, and emergencies
occur
-> end-of-day transition
earnings and shop update
every third completed day: card choice
Day 6 and every fifth day thereafter: decoration day
first decoration day: theme choice
Day 15 completion
-> franchise-card choice for future franchise
-> continue into overtime
-> on later failure/end: create franchise or scrap cards
```

The official press material frames a normal success target as surviving 15 days, and the daily operations reference documents the two main in-restaurant phases and post-Day-15 franchise flow. [S01][S09]

### 3.3 Day timing

- Service time-bar length starts at roughly 100 seconds and grows by 25 seconds after every three completed days according to the current Daily Operations reference.

- The day does not end merely because the time bar is full; it ends after all scheduled customers are cleared.

- Night applies late in the day and remains relevant while uncleared customers remain.

- Booking Desk interaction advances time toward the next scheduled group and awards money according to its current rule.

- Rush and closing-time cards can alter arrival distribution or create arrivals not represented by the simple base schedule.

Telemetry must emit scheduled/remaining groups when available, not reconstruct them solely from the bar.

## 4. Player controls, carried items, tools, and simultaneous actions

### 4.1 Primitive controls

The current controls reference defines five named controls beyond movement: **Grab**, **Interact/Act**, **Ready**, **Ping**, and **Stand Still**. [S06]

- **Grab in preparation:** pick up/place/swap appliances; reassign a chair when adjacent to multiple tables.

- **Interact in preparation:** rotate directional appliances, toggle chairs, buy, reroll, enter Practice, and perform other contextual actions.

- **Ready:** starts the day only after all active players are ready; it has no service function.

- **Ping:** highlights/reveals information and enters/exits advanced build mode when held.

- **Stand Still:** anchors position while allowing facing changes.

- **Grab in service:** take, place, or combine portable items.

- **Interact in service:** clean, chop, knead, portion, wash, add water, open/close, equip, wear, research, copy, discount, extinguish, and other context actions.

**No free drop or toss action:** a carried item cannot be released onto an
arbitrary floor tile. Grab releases it only through a legal contextual outcome:
place or combine it on an accepting appliance/holder, store it in an accepting
container, or dispose of it through a valid trash interaction. Pressing Grab
toward empty floor does not create a freely dropped item. Consequently,
`loose_items` must not be interpreted as evidence that the player has a general
drop action.

### 4.2 The user's observed case: cleaning dirt while carrying a plate

**Verified rule:** Floor mess is cleaned by **Interact** without placing the
carried item. A player can normally continue to hold one ordinary item and
Interact with a floor mess. This is why a player holding a plate or food can
clean dirt. [S06][S07]

The bridge must model this as two different channels:

```text
normal carried-item state: held_items[]
equipped/worn state: equipped_tools[] and footwear
contextual interaction: affordance verb + target
```

Do not encode hands_occupied => cannot_interact. That rule is false. Instead, expose the exact blocker returned by the target/action rule.

### 4.3 Important empty-hand and tool exceptions

Examples:

- Emptying a normal bin produces a garbage bag and is blocked when the player already carries an item/tool that uses the carry channel.

- Mops, Floor Buffer, and Fire Extinguisher are themselves carried tools and generally prevent carrying an ordinary item.

- Scrubbing Brush, Sharp Knife, Rolling Pin, and Clipboard act as equipped hand tools and can coexist with a normal carried item.

- Tray is special: it replaces ordinary carrying with two tray slots, and its Grab priority differs from normal Grab.

- Footwear is worn independently and does not occupy the item or hand-tool slot.

| **Tool/** **equipme** **nt** | **State** **chann** **el** | **Can carry** **norm** **al** **item?** | **Can still** **Intera** **ct?** | **Critical behavior** |
| --- | --- | --- | --- | --- |
| Scrubbing Brush | Equipped tool slot | Yes | Yes | 3x dish-clean speed; 2x floor-mess clean speed. |
| Sharp Knife | Equipped tool slot | Yes | Yes | Speeds chopping; live bridge should expose applicable process multiplier. |
| Rolling Pin | Equipped tool slot | Yes | Yes | Speeds kneading. |
| Clipboard | Equipped tool slot | Yes | Yes | Speeds research/copy/discount and Booking Desk interaction. |
| Mop / Fast Mop / Lasting Mop | Carried tool | No ordinary carried item | Yes | Instantly cleans mess under travel path and creates wet floor. |
| Floor Buffer | Carried tool | No ordinary carried item | Yes | Creates buff floor; does not clean existing mess. |
| Fire Extinguisher | Carried tool | No ordinary carried item | Yes | Extinguishes much faster; can still interact with floor mess or process items. |
| Tray | Special carried tool | Carriestwo items | Yes | Grab behavior is tray-specific; items on tray do not combine. |
| Footwear | Worn slot | Yes | Yes | Separate from hands and tool slot; may change speed, collision, and mess spreading. |

### 4.4 Action telemetry requirement

For the current player and faced/nearby targets, emit at least:

```json
{
"actor_id": "player.1",
"verb": "clean_floor",
"target_id": "tile.7.3",
"item_id": "item.clean_plate.42",
"available": true ,
"blockers": [],
"hold_seconds": 1.0,
"source": "game_rule_check",
"confidence": 1.0
}
```

This makes contextual combinations explicit and prevents Claude from assuming that all tools or held items behave alike.

## 5. Surfaces, storage, capacities, and placement rules

### 5.1 General rule

Portable items cannot normally be placed directly on an empty floor tile. They require a surface, container, provider return, table, automation appliance, or compatible holder. Most appliances expose at least one item position, but that does **not** mean every appliance accepts every item or that placement has no side effect. [S07]

The safest bridge representation is:

```text
entity
slots[]
capacity
count
accepted_semantic_ids[]
accepted_traits[]
homogeneous_only
contents[]
processes[]
affordances[]
```

### 5.2 Plate and rack answer

- **Starter Plates:** four clean plates.

- **Purchased Plates:** eight clean plates.

- **Dish Rack:** up to four dirty plates only; a plate with Picky Eaters leftovers is not accepted until leftovers are discarded.

- **Wash Basin/Dish Washer:** up to four plates in a homogeneous clean or dirty batch.

- **Auto Plater:** the current wiki reports two provided plates and storage up to three, an unusual distinction that should be read from live components before training.

- The 1.4.3 game prevents starting a day without enough plates for the largest group, and starter stacks can be added by the game when needed. [S02]

- Players can buy another Plates blueprint when it appears; Plates is a conditional staple only while no active purchased Plates appliance exists. Once one is present, further copies are possible through the normal pool/reroll mechanics rather than the staple guarantee.

- Plates can sit on generic surfaces including Counter, Workstation, table, Hob-family surface, compatible automation, and compatible sinks. A plate stack/rack itself is a provider, not a universal placement surface.

- Plated food generally stops further cooking/burning, which is strategically important for hobs and automation.

### 5.3 Capacity and acceptance table

| **Appliance** | **Capacity** | **Accepted contents** | **Notes** |
| --- | --- | --- | --- |
| Starter Plates | 4 clean plates | Clean plates only | Free starter; extra stacks may be granted when required group size exceeds available plates. |
| Plates | 8 clean plates | Clean plates only | Purchasable conditional staple; upgrades to Auto Plater. |
| Auto Plater | Wiki reports 2 provided and storage up to 3 | Clean plates; automatically plates valid adjacent food | Capacity wording is internally awkward; bridge must read live provider/storage components. |
| Dish Rack | 4 | Dirty plates only; not leftovers | A dirty plate carrying leftover food is rejected. |
| Wash Basin | 4 | All clean or all dirty plates | One manual 5-second wash cleans the batch; cannot supply recipe water. |
| Dish Washer | 4 | All clean or all dirty plates | Closed 10-second cycle; locks contents until finished; no recipe water. |
| Starter Sink | 1 surface slot | Portable item; manual plate/wok cleaning | Provides water; 2.66s plate and 6.66s wok at base. |
| Sink | 1 surface slot | Portable item; manual plate/wok cleaning | Provides water; 2s plate and 5swok. |
| Power Sink | 1 surface slot | Portable item; manual plate/wok cleaning | No recipe water; 1s plate and 2.5s wok. |
| Soaking Sink | 1 surface slot | Portable item; automatically cleans dirty plate/wok | No manual cleaning and no recipe water; about 6.67s plate, 16.75s wok. |
| Prep Station | 4 | Four identical eligible food items | No plates, pots, boards, or woks; not whole portionable batches. |

| **Appliance** | **Capacity** | **Accepted contents** | **Notes** |
| --- | --- | --- | --- |
| Frozen Prep Station | 4 | Same rules as Prep Station | Contents persist overnight. |
| Freezer | 1 | Any portable item | Persists overnight except tools; does not inherit Counter processing. |
| Counter / Workstation | 1 | Any portable item | Generic surface; Workstation processes chop/knead faster. |
| Hob family | 1 | Any portable item | Generic surface plus automatic cook when the item has a valid cook process. |
| Conveyor / Grabber / Mixer / Combiner / Portioner / Teleporter | 1 active item | Any portable item, subject to appliance process | Automation can be blocked by target occupancy or active processes. |
| Tray | 2 | Any portable items | Items do not combine while onthe tray. |
| Pot Stack | 3 empty pots | Empty pots only | Provider tile is not a generic surface. |
| Woks | 4 | Woks only | Provider tile is not a generic surface; dirty burned woks need a compatible sink. |
| Taco Trays | 4 trays | Tray provider; tortillas combine with trays | Provider tile is not a generic surface. |
| Serving Boards | Provider stack | Serving boards only | Exact live count should be read from the provider component. |
| Blueprint Cabinet | 1 original plus at most 1 copy | Blueprints only | Stores across days; copy cannot itself be copied. |
| Bin | 5 items | Discardable items | Emptying requires taking a garbage bag; blocked when hands are occupied. |
| Starter Bin | 2 items | Discardable items | Free starter. |
| Compactor Bin | 1 item | Discardable items | Automatically clears after its cycle. |
| Expanded Bin | 10 items | Discardable items | Manual emptying. |

### 5.4 Placement and interaction matrix

Yes below means normally placeable, not necessarily strategically safe. Live affordance telemetry remains authoritative.

| **Item class** | **Counter/work + dining table** | **Hob + sink + prep station** | **Important constraints** |
| --- | --- | --- | --- |
| Unmodified ingredient | Counter/work: Yes; Dining table: Usually yes | Hob: Yes, may cook; Sink: Yes; Prep station: Usually yes | Provider normally accepts onlyits matching unmodified ingredient back. |
| Modified ingredient / unplated food | Counter/work: Yes; Dining table: Yes | Hob: Yes, if cookable; Sink: Yes; Prep station: Eligible only if the station accepts that food state | Combines or processes when a valid transition exists. |
| Plated dish | Counter/work: Yes; Dining table: Yes; may satisfy orders | Hob: Can be placed; plated food does not continue cooking/burning; Sink: Yes; Prep station: No | A plate changes burn/process behavior and later becomes dirty. |
| Clean plate | Counter/work: Yes; Dining table: Yes | Hob: Yes; Sink: Yes; Prep station: No | Stacks only in plate providers/batch sinks that accept clean plates. |
| Dirty plate | Counter/work: Yes; Dining table: Blocks seating until cleared | Hob: Can be placed, but no useful cook action; Sink: Yes; cleaning depends on sink type; Prep station: No | Dish Rack and cleaning appliances are preferred. |
| Dirty plate with leftovers | Counter/work: Yes; Dining table: Blocks seating | Hob: Technically portable; Sink: Cleaning normally blocked until leftovers discarded; Prep station: No | Dish Rack explicitly rejects leftovers; Picky Eaters requires disposal. |
| Pot / wok / tray / serving board | Counter/work: Yes; Dining table: Yes | Hob: Yes where meaningful; Sink: Portable, but cleaner compatibility varies; Prep station: No | These are equipment items, not generic ingredient states. |
| Tool | Counter/work: Usually yes if tool supports set-down; Dining table: Possible but blocks seating | Hob: Do not assume; Sink: Donot assume; Prep station: No | Some tools only return to theirown stand; use live affordances. |
| Blueprint | Counter/work: Preparation only; Dining table: Preparation only but unsafe | Hob: No service use; Sink: No; Prep station: No | Store in Blueprint Cabinet; loose blueprints disappear whenthe day starts. |
| Garbage bag | Counter/work: Yes; Dining table: Yes but blocks seating | Hob: No useful process; Sink: No; Prep station: No | Must be taken to outside Trash Can; cannot be put in another bin. |

### 5.5 Table-specific placement consequences

- Any ordinary item on a dining table normally makes it unavailable for new seating until cleared.

- Charming level 3 allows customers to sit before tables are cleared, changing this rule.

- After a group has committed to pathing toward a table, replacing an item may not stop them from taking the seats.

- Valid food placed on the active head table can satisfy an order. Condiments and table consumables have their own rules.

- Conveyors, Grabbers, and Teleporters adjacent to tables can expose food or requested extras directly to customers.

- The Buffet introduces separate customer pathing: customers leave their table to collect an acceptable full or partial order from the Buffet.

- A table set's last-placed table is the head table and determines the dirty-item return point.

### 5.6 Why a universal hard-coded placement table is unsafe

Acceptance can depend on:

- Exact item state, not merely ingredient name.

- Whether an item is plated or contained in a pot/wok/tray/board.

- Current appliance door/cycle/process state.

- Clean versus dirty versus leftovers.

- Provider return rules.

- Capacity and homogeneous stacking.

- Phase.

- Cards, setting, mods, and branch.

Therefore, static knowledge should generate candidate actions; the bridge's affordances must decide legality.

## 6. Customers, groups, patience, urgency, and expected demand

### 6.1 Group size is not a recipe property

Steak, burgers, or another base recipe can modify **Expected Groups**, but they do not establish a fixed maximum group size. Group size comes from the run's active cards/setting/franchise state. The default range is 1-2. [S08]

| **Card/state** | **Resulting normal group-** **size range** | **Notes** |
| --- | --- | --- |
| Default | 1-2 | At least one dining table must seat the maximum. |
| Individual Dining | 1-1 | Blocked by Medium Groups. |
| Medium Groups | 2-4 | Base for larger/flexible chains. |
| Medium + Large Groups | 4-6 | Both minimum and maximum increase. |
| Medium + Flexible Dining | 1-5 | Wider spread. |
| Medium + Large + | 3-7 | Normal combined result. |

| **Card/state** | **Resulting normal group-** **size range** | **Notes** |
| --- | --- | --- |
| Flexible |  |  |
| Expansion franchise card | Adds group size | Franchise stacking can raise the range further. |
| Autumn Community setting card | Grows over time | Group size increases during the run; no single recipe-level maximum. |

**Conclusion:** There is no safe global MAX_CUSTOMERS_PER_GROUP constant. Emit minimum_group_size and maximum_group_size from the live run. Expected total customers/concurrency is also run-dependent.

### 6.2 Seating and pathing

- Active green chairs count toward table capacity.

- Inactive chairs do not.

- Active-but-unreachable chairs must not be counted as usable until customer pathing is clear.

- Tables of the same combinable type can join; Bar Table and Simple Cloth Table are important exceptions.

- Each active chair needs a customer-valid path from the entrance. Customers cannot exploit narrow half-tile gaps available to players.

- Customer destination priority is broadly: clear suitable dining table, Hosting Stand, Coffee Table, then outside queue.

- Smaller groups may skip a larger group when a newly free table fits only the smaller group.

### 6.3 Patience state machine

#### Phase What ends it Solo base 2 players 3 players 4 players

120s day / Suitable inside destination Queuing 60s 90 / 45 82 / 41 78 / 39 becomes available night

Waiting for Suitable dining table 200s 150s 136s 130s Table

Thinking Timer 2.5s 2.5s 2.5s 2.5s

Service Order taken 200s 150s 136s 130s

Waiting for First required delivery 120s 90s 82s 78s Food

20s Delivery Remaining group requirements (+2.7/de 15s (+2) 13.6s (+1.8) 13s (+1.7) livery)

| **Phase** | **What ends it** | **Solo base** | **2 players** | **3 players** | **4 players** |
| --- | --- | --- | --- | --- | --- |
| Eating | Timer/extra request | 3s base | 3s | 3s | 3s |

Thinking and Eating use food/card-specific duration modifiers but are not ordinary failure bars. Multi-course restaurants repeat dining phases for each course.

### 6.4 Queue formula

The current customer reference models shared queue patience as:

```text
decay_per_second =
time_of_day_factor
* weather_factor
* player_count_factor
* 1.1^(groups_in_queue), capped at factor 5
* exclusive_level_1_factor
```

Relevant factors include night 2x, rain 1.5x, snow 2x, solo 0.75x, two players 1x, three 1.1x, four 1.15x, and Exclusive level 1 factor 0.75. When a group enters, shared queue patience gains roughly ten seconds at the current decay rate; emptying the queue resets it.

### 6.5 Urgency

The visual "urgent" threshold is not reliably documented as a stable numeric percentage in the sources used. Do not invent one.

Telemetry should provide:

- current, maximum, and normalized.

- decay_per_second.

- seconds_to_failure_estimate.

- is_urgent read from a game component/event where possible.

- urgency_threshold_source.

- visible_to_player, because Empathy/Photographic Memory can hide information.

For scheduling, use time-to-failure and travel/action duration, not only a red-flash boolean.

### 6.6 Expected groups

- Expected groups passively grow with day length and modifiers.

- Solo normally receives 80% of the two-player baseline, three players 125%, and four players 150%.

- Base recipe and most food cards alter expected groups.

- Rush cards add waves; Closing Time can add customers outside the simple display.

- Adding courses reduces expected groups further.

The live top-right count is a better observation than reimplementing the whole calculation. Retain the formula only for validation and simulation.

### 6.7 Extra requests and piecemeal orders

- Hot Dogs, Stir Fry, Dumplings, and Coffee variants can produce extra-item/condiment requests during Eating.

- An individual customer requests at most one extra, but multiple members of a group can request sequentially.

- Satisfying an extra restarts Eating duration.

- Sandwiches and Sundaes use piecemeal delivery; Tacos and portionable containers can also be partially satisfied.

- Orders therefore require a list of requirements and quantities, not a single requested_item string.

## 7. Dirt, cleaning, wet floors, buff floors, and fire

### 7.1 Mess generation

Messes arise from customers while eating and from cooking appliances. The current restaurant reference gives the customer chance per second as approximately:

group_members * 0.4 * mess_factor percent Mess placement is normally within a 3x3 area around the source, widened by Splash Zone. Existing mess can grow from small to medium to large. Customer mess location is tied to the sitting chair, so chair/table layout affects floor risk. [S07]

| **Mess size** | **Movement reduction** | **Customer-mess clean time** | **Hob-mess clean time** |
| --- | --- | --- | --- |
| Small | 50% | 1s | 1s |
| Medium | 60% | 2s | 4s |
| Large | 85% | 3s | 8s |

### 7.2 Manual and tool cleaning

- Bare-handed floor cleaning: Interact with the mess; works while carrying a normal item.

- Scrubbing Brush: speeds dish cleaning 3x and floor mess cleaning 2x; can coexist with a carried item.

- Mop/Fast Mop/Lasting Mop: carried tools that instantly clean floor mess as the player traverses it and leave wet floor.

- Robot Mop: autonomous, seeks mess within its room, cleans, and leaves wet floor.

- Enchanted Broom: event-limited autonomous cleaner that does not leave wet floor.

- Sink family: cleans dishes/woks as supported and may clear nearby small/medium mess while producing wet floor.

- Floor Buffer/Robot Buffer: create buff floor but do not clean existing mess.

- Kitchen Floor Protector/rugs/appliance footprints can prevent a floor state from forming on occupied tiles.

### 7.3 Wet floor and buff floor

- Wet floor typically lasts 10 seconds; Lasting Mop wet floor lasts 30 seconds.

- Wet floor increases base movement by about 21% but interacts badly with Trainers.

- Buff floor lasts about 60 seconds, increases movement by about 56.25%, and prevents new mess/wet state on that tile.

- A tile cannot simultaneously be normal mess, wet, and buffed. Emit one current floor state plus expiry/progress.

### 7.4 Dish and wok cleaning

| **Cleaner** | **Plate behavior** | **Wok behavior** | **Water for recipes?** |
| --- | --- | --- | --- |
| Starter Sink | Manual, ~2.66s | Manual, ~6.66s | Yes |
| Sink | Manual, 2s | Manual, 5s | Yes |
| Power Sink | Manual, 1s | Manual, 2.5s | No |
| Soaking Sink | Automatic, ~6.67s | Automatic, ~16.75s | No |
| Wash Basin | Manual batch up to 4, 5s | No | No |
| Dish Washer | Closed 10s batch up to 4 | No | No |

### 7.5 Fire

- Normal sources include a Danger Hob burning an item and misuse of a Microwave.

- Fire spreads to adjacent items/mess but not across room boundaries.

- Bare-handed extinguishing takes about 3 seconds; Fire Extinguisher about 0.6 seconds.

- A burning object generally blocks manual/other-appliance interaction, but automatic Grabber/Teleporter behavior can continue.

- Players can still grab/place into fire in some cases.

- Fire on a table/customer causes near-immediate patience collapse.

- Fire spread speed scales with player count.

The bridge must treat fire as an emergency state and expose both extinguish and any legal rescue-Grab affordance.

## 8. Recipes and process-state modelling

### 8.1 Base recipe catalog

| **Base** **recip** **e** | **Course** | **Unlock shown** **by current** **catalog** | **Expected-** **group** **s** **modi** **fier** | **Base** **value** | **Base eating time** |
| --- | --- | --- | --- | --- | --- |
| Steak | Main | 1 | 0% | 5 | 3s |
| Salad | Main | 2 | +15% | 4 | 3s |
| Pizza | Main | 3 | 0% | 5 | 3s |
| Dumplings | Main | 4 | -30% | 8 | 3s (some tables show historical inconsistency) |
| Black Coffee | Dessert base | 4 | +30% | 1 | 12s |
| Burgers | Main | 5 | +30% | 3 | 2.25s |
| Sandwiches | Main | Catalogs conflict on unlock | -15% or page-specific | 3+ | 3s |
| Turkey | Main | 6 | -15% | 5 | 4.5s |
| Pies | Main | 7 | -15% | 8 | 3s |
| Cakes | Dessert base | 7 | page/card tables conflict | 3+ | varies by cake and patched eating-time rules |
| Spaghetti | Main | 8 | -15% | 5 | 3s |
| Sundaes | Current catalogs conflict on course/unlock | Catalogs conflict | -15% or variant-specific | 3 | 3s base |
| Fish | Main | 9 | -15% | 5 | varies by fish |
| Tacos | Main | 10 | +15% | per taco | 2.25s |

| **Base** **recip** **e** | **Course** | **Unlock shown** **by current** **catalog** | **Expected-** **group** **s** **modi** **fier** | **Base** **value** | **Base eating time** |
| --- | --- | --- | --- | --- | --- |
| Hot Dogs | Main | 11 | +15% | 5 | 2.25s |
| Breakfast | Main | 13 | 0% | 5 | 3s |
| Stir Fry | Main | 15 | -15% | 10 | 3s |

**Version warning:** Sandwiches, Sundaes, and some Cakes/Dumplings rows differ between the live recipe index, individual pages, and the Cards table after the Buffet/1.4 updates. Use the player's unlocked HQ state and the live card GDO as authority rather than hardcoding these unlock/course rows.

### 8.2 Required recipe graph

Each recipe must be stored as a graph, not a prose sequence:

```json
{
"recipe_id": "recipe.pizza.plain",
"course": "main",
"order_acceptance": ["item.plated_pizza_slice"],
"states": ["flour", "dough", "pizza_base", "tomato_sauce",
"chopped_cheese",
"raw_pizza", "cooked_pizza", "pizza_slice",
"plated_pizza_slice"],
"transitions": [
{
"action": "knead",
"inputs": ["item.flour"],
"required_surface_traits": ["supports_knead"],
"duration_seconds_at_1x": 1.0,
"outputs": ["item.dough"]
},
{
"action": "cook",
"inputs": ["item.raw_pizza"],
"duration_seconds_at_1x": 8.0,
"burn_after_additional_seconds": 8.0,
"outputs": ["item.cooked_pizza"]
},
{
"action": "portion",
"inputs": ["item.cooked_pizza", "item.clean_plate"],
"duration_seconds_at_1x": 1.0,
"portions": 4,
"outputs": ["item.plated_pizza_slice"]
}
]
}
```

### 8.3 High-level process summaries

- **Steak:** raw cut -> sequential Rare -> Medium -> Well-done -> Burnt; plating freezes doneness. Cuts have different stage/burn timing. Sauces use reusable pots/broth; toppings add to plated steak.

- **Salad:** chop lettuce and optional/topping ingredients -> combine on plate. Apple and potato salads add mayonnaise and/or cooked pot components.

- **Pizza:** flour -> dough -> oil base; tomato -> sauce; cheese chopped; combine raw pizza -> cook -> portion four onto plates.

- **Dumplings:** dough + chopped meat + chopped carrot -> unwrapped -> knead -> raw dumplings -> cook -> plate; optional seaweed and soy request.

- **Coffee:** cup -> machine-filled coffee; variants combine ice, steam milk, tea pot/cups, ice cream, or later table extras.

- **Burgers:** patty -> cook -> combine bun -> optional toppings -> plate; Fresh Patties replaces provider with meat+egg production.

- **Sandwiches:** piecemeal individual ingredients bracketed by bread/toast; toppings/fillings are delivered separately, and giant/club variants expand requirements.

- **Turkey:** whole bird -> cook -> portion four -> bones; optional sauce, gravy from bones, stuffing, and nut-roast alternative.

- **Pies:** flour -> dough -> pie crust -> filling -> cook -> plate; pre-cooking crust is legal but changes total timing.

- **Cakes:** mixing bowl batter plus flavor/tray paths -> bake/rise/fry -> portion; order acceptance is by flavor, not one exact cake shape.

- **Spaghetti:** pot + water + pasta -> cook -> discard/drain water -> portions; tomato/bolognese/white-sauce paths; Lasagne layers two cycles of sauces and sheets.

- **Sundaes:** scooped or homemade source -> glass -> piecemeal scoops/toppings/syrups; homemade path freezes and mixes a batch.

- **Fish:** daily provider contents vary among unlocked fish recipes; each fish has its own process and eating time.

- **Tacos:** mince -> cook; tortilla + tray + mince + toppings -> portion four or offer splittable tray.

- **Hot Dogs:** sausage -> cook -> bun -> plate; ketchup/mustard can be requested during eating.

- **Breakfast:** dough -> loaf -> ten slices -> toast -> plate; beans/eggs/mushroom/tomato additions.

- **Stir Fry:** wok + rice cook, then each selected prepared ingredient is added and cooked sequentially; burned wok becomes dirty.

### 8.4 Shared starters, sides, and desserts

- Soups use broth: pot + water + onion -> initial 15s broth; later refill cycle about 3s; ingredient-specific cook; usually three portions and a drained-broth remainder.

- Bread starter: dough -> long cook -> loaf -> portions combined with Serving Board; board returns.

- Mandarin: portion 2-4 slices into a bowl.

- Pumpkin seed: extract seeds, cook, serve; hollow pumpkin can feed other recipes.

- Sides include bamboo, broccoli, chips, corn, mashed potato, onion rings, and roast potato.

- Desserts include fruit pies, cheese board, and ice cream.

- Starters/sides/desserts use order-chance rules rather than universal per-customer guarantees.

### 8.5 Telemetry fields for food

For every item:

- Semantic ID and live GDO ID.

- Ingredient/food/equipment traits.

- Current recipe/process state.

- Valid next process IDs.

- Process progress and speed.

- Burn progress and time-to-burn.

- Portions remaining and depleted remainder.

- Plated/container/equipment composition.

- Clean/dirty/leftover state.

- Order compatibility IDs for current visible orders.

- Whether a customer or automation can take it now.

## 9. Appliances, equipment, upgrades, and automation

### 9.1 Exhaustive normal catalog by family

#### Cooking

[Starter Hob,](https://wiki.plateupgame.co.uk/appliances/StarterHob) [Hob,](https://wiki.plateupgame.co.uk/appliances/Hob) [Safety Hob,](https://wiki.plateupgame.co.uk/appliances/SafetyHob) [Danger Hob,](https://wiki.plateupgame.co.uk/appliances/DangerHob) [Oven,](https://wiki.plateupgame.co.uk/appliances/Oven) [Microwave,](https://wiki.plateupgame.co.uk/appliances/Microwave) [Gas Limiter,](https://wiki.plateupgame.co.uk/appliances/GasLimiter) [Gas Override.](https://wiki.plateupgame.co.uk/appliances/GasOverride)

#### Kitchen and storage

[Starter](https://wiki.plateupgame.co.uk/appliances/PrepStation) [Bin, Bin, Compactor](https://wiki.plateupgame.co.uk/appliances/FrozenPrepStation) [Bin, Composter Bin,](https://wiki.plateupgame.co.uk/appliances/KitchenFloorProtector) [Expanded Bin,](https://wiki.plateupgame.co.uk/appliances/RollingPin) [Counter, Freezer,](https://wiki.plateupgame.co.uk/appliances/SharpKnife) [Workstation,](https://wiki.plateupgame.co.uk/appliances/Workstation) [Prep](https://wiki.plateupgame.co.uk/appliances/PrepStation) [Station,](https://wiki.plateupgame.co.uk/appliances/PrepStation) [Frozen Prep Station,](https://wiki.plateupgame.co.uk/appliances/FrozenPrepStation) [Kitchen Floor Protector,](https://wiki.plateupgame.co.uk/appliances/KitchenFloorProtector) [Rolling Pin,](https://wiki.plateupgame.co.uk/appliances/RollingPin) [Sharp Knife.](https://wiki.plateupgame.co.uk/appliances/SharpKnife)

#### Dining room

[Dining](https://wiki.plateupgame.co.uk/appliances/Napkins) [Table, Bar Table,](https://wiki.plateupgame.co.uk/appliances/SharpCutlery) [Metal Table,](https://wiki.plateupgame.co.uk/appliances/SpecialsMenu) [Table - Simple](https://wiki.plateupgame.co.uk/appliances/LeftoverBags) [Cloth,](https://wiki.plateupgame.co.uk/appliances/Supplies) [Table - Fancy](https://wiki.plateupgame.co.uk/appliances/TrayStand) [Cloth,](https://wiki.plateupgame.co.uk/appliances/CoffeeTable) [Breadsticks, Candle Box,](https://wiki.plateupgame.co.uk/appliances/HostingStand) [Napkins, Sharp Cutlery,](https://wiki.plateupgame.co.uk/appliances/FlowerPot) [Specials Menu,](https://wiki.plateupgame.co.uk/appliances/SpecialsMenu) [Leftover Bags,](https://wiki.plateupgame.co.uk/appliances/LeftoverBags) [Supplies,](https://wiki.plateupgame.co.uk/appliances/Supplies) [Tray Stand,](https://wiki.plateupgame.co.uk/appliances/TrayStand) [Coffee Table,](https://wiki.plateupgame.co.uk/appliances/CoffeeTable) [Hosting Stand,](https://wiki.plateupgame.co.uk/appliances/HostingStand) [Buffet,](https://wiki.plateupgame.co.uk/appliances/Buffet) [Flower Pot.](https://wiki.plateupgame.co.uk/appliances/FlowerPot)

#### Cleaning

[Starter Sink,](https://wiki.plateupgame.co.uk/appliances/RobotMop) [Sink,](https://wiki.plateupgame.co.uk/appliances/FloorBuffer) [Soaking Sink, Power](https://wiki.plateupgame.co.uk/appliances/RobotBuffer) [Sink, Wash](https://wiki.plateupgame.co.uk/appliances/DishRack) [Basin, Dish Washer,](https://wiki.plateupgame.co.uk/appliances/ScrubbingBrush) [Mop,](https://wiki.plateupgame.co.uk/appliances/Mop) [Lasting Mop,](https://wiki.plateupgame.co.uk/appliances/LastingMop) [Fast Mop,](https://wiki.plateupgame.co.uk/appliances/FastMop) [Robot Mop,](https://wiki.plateupgame.co.uk/appliances/RobotMop) [Floor Buffer,](https://wiki.plateupgame.co.uk/appliances/FloorBuffer) [Robot Buffer,](https://wiki.plateupgame.co.uk/appliances/RobotBuffer) [Dish Rack,](https://wiki.plateupgame.co.uk/appliances/DishRack) [Scrubbing Brush.](https://wiki.plateupgame.co.uk/appliances/ScrubbingBrush)

#### Automation

[Conveyor,](https://wiki.plateupgame.co.uk/appliances/HeatedMixer) [Grabber, Smart Grabber,](https://wiki.plateupgame.co.uk/appliances/RapidMixer) [Grabber - Rotating,](https://wiki.plateupgame.co.uk/appliances/GrabberRotating) [Combiner,](https://wiki.plateupgame.co.uk/appliances/Combiner) [Portioner,](https://wiki.plateupgame.co.uk/appliances/Portioner) [Mixer,](https://wiki.plateupgame.co.uk/appliances/Mixer) [Conveyor Mixer,](https://wiki.plateupgame.co.uk/appliances/ConveyorMixer) [Heated Mixer,](https://wiki.plateupgame.co.uk/appliances/HeatedMixer) [Rapid Mixer.](https://wiki.plateupgame.co.uk/appliances/RapidMixer)

#### Research

[Blueprint Cabinet,](https://wiki.plateupgame.co.uk/appliances/BlueprintCabinet) [Research Desk,](https://wiki.plateupgame.co.uk/appliances/ResearchDesk) [Blueprint Desk,](https://wiki.plateupgame.co.uk/appliances/BlueprintDesk) [Copying Desk,](https://wiki.plateupgame.co.uk/appliances/CopyingDesk) [Discount Desk,](https://wiki.plateupgame.co.uk/appliances/DiscountDesk) [Clipboard Stand.](https://wiki.plateupgame.co.uk/appliances/ClipboardStand)

#### Footwear

[Trainers,](https://wiki.plateupgame.co.uk/appliances/Trainers) [Wellies,](https://wiki.plateupgame.co.uk/appliances/Wellies) [Work Boots.](https://wiki.plateupgame.co.uk/appliances/WorkBoots)

#### Miscellaneous

[Booking](https://wiki.plateupgame.co.uk/appliances/SpecialsTerminal) [Desk,](https://wiki.plateupgame.co.uk/appliances/Extralife) [Display Stand, Dumbwaiter,](https://wiki.plateupgame.co.uk/appliances/Upgradekit) [Teleporter,](https://wiki.plateupgame.co.uk/appliances/Teleporter) [Fire Extinguisher,](https://wiki.plateupgame.co.uk/appliances/FireExtinguisher) [Ordering Terminal,](https://wiki.plateupgame.co.uk/appliances/OrderingTerminal) [Specials](https://wiki.plateupgame.co.uk/appliances/SpecialsTerminal) [Terminal,](https://wiki.plateupgame.co.uk/appliances/SpecialsTerminal) [Extra Life,](https://wiki.plateupgame.co.uk/appliances/Extralife) [Upgrade Kit.](https://wiki.plateupgame.co.uk/appliances/Upgradekit)

#### General equipment

[Starter Plates,](https://wiki.plateupgame.co.uk/appliances/StarterPlates) [Plates,](https://wiki.plateupgame.co.uk/appliances/Plates) [Auto Plater,](https://wiki.plateupgame.co.uk/appliances/AutoPlater) [Pot Stack,](https://wiki.plateupgame.co.uk/appliances/PotStack) [Serving Boards.](https://wiki.plateupgame.co.uk/appliances/ServingBoards)

#### Recipe-specific equipment

[Coffee](https://wiki.plateupgame.co.uk/appliances/BrownieTray) [Machine, Ice](https://wiki.plateupgame.co.uk/appliances/CookieTray) [Dispenser, Milk](https://wiki.plateupgame.co.uk/appliances/CupcakeTray) [Steamer, Woks,](https://wiki.plateupgame.co.uk/appliances/DoughnutTray) [Lasagne Tray, Taco Trays,](https://wiki.plateupgame.co.uk/appliances/Sundae-Glasses) [Mixing Bowls,](https://wiki.plateupgame.co.uk/appliances/Mixing-Bowls) [Cake Tin,](https://wiki.plateupgame.co.uk/appliances/CakeTin) [Brownie Tray,](https://wiki.plateupgame.co.uk/appliances/BrownieTray) [Cookie Tray,](https://wiki.plateupgame.co.uk/appliances/CookieTray) [Cupcake Tray,](https://wiki.plateupgame.co.uk/appliances/CupcakeTray) [Doughnut Tray,](https://wiki.plateupgame.co.uk/appliances/DoughnutTray) [Sundae Glasses.](https://wiki.plateupgame.co.uk/appliances/Sundae-Glasses)

#### Event/setting-limited enchanted catalog

[Enchanting Desk,](https://wiki.plateupgame.co.uk/appliances/MagicSpring) [Ghost Scrubber,](https://wiki.plateupgame.co.uk/appliances/MagicAppleTree) [Ghostly Knife,](https://wiki.plateupgame.co.uk/appliances/MagicMirror) [Ghostly Rolling](https://wiki.plateupgame.co.uk/appliances/Cauldron) [Pin, Ghostly](https://wiki.plateupgame.co.uk/appliances/VanishingCircle) [Clipboard, Enchanted](https://wiki.plateupgame.co.uk/appliances/TableSharingCauldron) [Plates,](https://wiki.plateupgame.co.uk/appliances/TableSharingCauldron) [Magic Spring,](https://wiki.plateupgame.co.uk/appliances/StoneTable) [Magic Apple](https://wiki.plateupgame.co.uk/appliances/IllusionWall) [Tree, Magic Mirror,](https://wiki.plateupgame.co.uk/appliances/LevitationStation) [Cauldron,](https://wiki.plateupgame.co.uk/appliances/InstantWand) [Vanishing Circle, Table](https://wiki.plateupgame.co.uk/appliances/LevitationLine) [- Sharing](https://wiki.plateupgame.co.uk/appliances/PreservingStation) [Cauldron,](https://wiki.plateupgame.co.uk/appliances/TableSharingCauldron) [Table - Stone,](https://wiki.plateupgame.co.uk/appliances/StoneTable) [Illusion Wall,](https://wiki.plateupgame.co.uk/appliances/IllusionWall) [Levitation Station,](https://wiki.plateupgame.co.uk/appliances/LevitationStation) [Instant Wand,](https://wiki.plateupgame.co.uk/appliances/InstantWand) [Levitation Line,](https://wiki.plateupgame.co.uk/appliances/LevitationLine) [Preserving](https://wiki.plateupgame.co.uk/appliances/PreservingStation)

[Station,](https://wiki.plateupgame.co.uk/appliances/PreservingStation) Pouch of Holding, [Enchanted Broom.](https://wiki.plateupgame.co.uk/appliances/EnchantedBroom) These are not part of the normal stable baseline and must be enabled only when the active setting/cards expose them.

### 9.2 Upgrade graph

The current upgrade tree says only **blueprints in cabinets** are upgraded; already purchased appliances are not. Research must occur during Customer Service. First upgrade selection can be random where several branches exist; later upgrades follow the documented cycles. [S11][S12]

| **Base** | **Upgrade path** | **Type** |
| --- | --- | --- |
| Plates | Auto Plater | Linear |
| Oven | Microwave | Linear |
| Prep Station | Frozen Prep Station | Linear |
| Dumbwaiter | Teleporter | Linear |
| Ordering Terminal | Specials Terminal | Linear |
| Research Desk | Blueprint Desk -> Discount Desk -> Copying Desk -> Blueprint Desk | Cyclic among upgraded desks |
| Counter | Freezer <-> Workstation | Cyclic after first upgrade |
| Hob | Safety Hob <-> Danger Hob | Cyclic after first upgrade |
| Dining Table | Fancy Cloth -> Bar Table -> Simple Cloth -> Metal Table -> Fancy Cloth | Cyclic |
| Bin | Compactor -> Composter -> Expanded -> Compactor | Cyclic |
| Sink | Power Sink -> Wash Basin -> Dish Washer -> Soaking Sink -> Power Sink | Cyclic |
| Conveyor | Grabber -> Smart Grabber -> Rotating Grabber -> Smart Grabber | Cyclic |
| Mixer | Rapid Mixer -> Heated Mixer -> Conveyor Mixer -> Rapid Mixer | Cyclic |
| Mop | Branches to Fast Mop, Lasting Mop, Robot Mop, Robot Buffer, or Floor Buffer depending path | Branched/cyclic; query live upgrade list |
| Portioner | Combiner <-> Portioner | Cyclic |

### 9.3 Core appliance semantics

#### Cooking

- Hobs are one-slot generic surfaces with automatic Cook when valid. Starter Hob is slow, Safety Hob is slower but safe/no-burn, and Danger Hob is fast but creates major burn/fire risk.

- Oven is an enclosed cooking surface requiring open/close state.

- Microwave is an active enclosed fast cooker with invalid-use/fire edge cases.

- Gas Limiter and Gas Override modify nearby cooking/burn rates and can change a safe timing policy into an unsafe one.

#### Storage and work

- Counter is a generic one-item surface and supports manual Chop/Knead.

- Workstation is a faster Counter upgrade.

- Freezer stores one portable item across days but does not retain Counter processing.

- Prep Stations stack four identical eligible food states; whole portionable batches and equipment are excluded.

- Bins are terminal storage with different capacities/cycles; garbage bags must be removed to the exterior trash unless self-clearing.

#### Dining

- Dining tables create chairs, combine with compatible tables, define seating, receive food, return dirty equipment, and interact with patience/mess/decorations.

- Bar Table seats one and removes Thinking but cannot use table consumables.

- Simple Cloth seats two opposite customers who share one meal.

- Metal Table modifies patience and can alter side requirements.

- Fancy Cloth increases payment.

- Coffee Table buffers groups but cannot serve meals.

- Hosting Stand creates a different waiting location/patience behavior.

- Buffet creates a self-service customer path and can satisfy full or partial requirements.

#### Research

- Blueprint Cabinet stores one original and at most one copied blueprint.

- Research Desk upgrades eligible blueprints in adjacent cabinets.

- Discount Desk halves cost, rounded up, to a minimum of 1; repeatable across days.

- Copying Desk creates one copy per cabinet under normal rules; copies cannot be copied again.

- Blueprint Desk cycles candidate next-day blueprints and locks a selection.

### 9.4 Automation primitives

| **Primitive** | **Behavior** | **Critical edge cases** |
| --- | --- | --- |
| Conveyor | Pushes one item in arrow direction, about 1sper push | Destination occupancy causes back-pressure. |
| Grabber | Pulls then pushes; about 2s end-to-end | Waits for most active processes to finish; burning is a notable exception. |

| **Primitive** | **Behavior** | **Critical edge cases** |
| --- | --- | --- |
| Smart Grabber | Pulls only trained item state | Training can occur from first pulled/placed item; practice setting persists. |
| Rotating Grabber | Input orientation in prep; output can rotate during service/practice | Practice orientation persists into the real day. |
| Mixer | Automatic Chop/Knead | Does not provide manual process; 0.5x base. |
| Rapid Mixer | Faster automatic Chop/Knead | Still no manual processing. |
| Heated Mixer | Chop/Knead then safe Cook | Priorities matter; not counted by game as a qualifying cooking appliance for all setup validation. |
| Conveyor Mixer | Processes then pushes | Also pushes items that have no valid mix process. |
| Combiner | Combines held item onto target in facing direction | Stable 1.4.3 no longer uses it for sink/milk/ice auto-fill. |
| Portioner | Pulls portions toward itself and may combine | Stable route for sink/milk/ice fill; remainder/by-product handling matters. |
| Auto Plater | Adds plate to valid adjacent food | Needs plate inventory and correct facing. |
| Dumbwaiter | Shared manual slot; only one endpoint open | Not fully automatic and door state blocks access. |
| Teleporter | Paired by purchase order; teleports when paired destination is available | Requires at least two; expensive; one item per endpoint. |
| Buffet | Customer takes compatible item/portion | Requires customer path and can move mess generation away from tables. |

### 9.5 Stable 1.4.3 automation override

The official 1.4.3 patch controls this rule:

- Sinks, Milk Dispensers/Steamers, and Ice Dispensers do not automatically fill arbitrary items merely because they are placed there.

- Portioners are the intended automation helper.

- Smart Grabber priority over other grabbers was fixed.

- Combiner duplication and piecemeal reward bugs were also addressed.

Any old demonstration or wiki sentence that shows Combiner-based water filling must be tagged stale_before_1.4.3. [S02]

### 9.6 Automation telemetry

Emit:

- Input/output direction and pull source.

- Trained Smart Grabber item ID/traits.

- Current item, process lock, pull/push progress, destination availability.

- Pair ID for teleporters/dumbwaiters.

- Portion source, remainder, by-product destination, and portion count.

- Expected next transition and whether a process is blocked.

- Customer-accessible adjacency for conveyors/grabbers/teleporters/buffets.

## 10. Blueprints, research, cards, themes, and decorations

### 10.1 Blueprint shop and rerolls

- Normal preparation begins with blueprint envelopes; loose blueprints are lost when the day starts.

- Typical shops produce about five blueprints, with a mix of Staple and Seed pools.

- Day 1 and decoration days use different rules.

- Reroll initially costs 10 coins and increases by 10 each use for the rest of the run.

- Reroll includes loose/cabinet-removed blueprints and excludes stored ones; it draws from the Seed pool rather than Staple pool.

- Upgraded blueprint chance grows later in a run and can be changed by cards.

- Conditional Staples move between Staple and Seed pools according to whether the appliance already exists.

### 10.2 Research/copy/discount

1. Put a blueprint in a Blueprint Cabinet during preparation.

2. Place cabinet within one of the eight adjacent spaces of a compatible desk, in the same room.

3. During service, hold Interact at the desk.

4. Retrieve/buy/retain the result next preparation.

One desk can influence several adjacent cabinets under normal rules, but each effect applies once per cabinet per day. Simplicity changes desk limits. An original and its copy can be upgraded/discounted in the same day; the copy cannot be copied again.

### 10.3 Customer cards

| **Card** | **Prerequisite/block** | **Mechanical effect** |
| --- | --- | --- |
| Individual Dining | Blocks Medium Groups | Maximum group size -1; normal result is 1-1. Total customers are redistributed into more, smaller groups. |
| Medium Groups | Blocks Individual Dining | Minimum group size +1 and maximum +2; normal result is 2-4. |
| Large Groups | Requires Medium Groups | Minimum and maximum group size +2; normally 4-6. |
| Flexible Dining | Requires Medium Groups | Minimum -1 and maximum +1; normally 1-5, or 3-7 with Large Groups. |
| Morning Rush | Blocked by Turbo | Adds a morning wave and approximately +15% expected groups. |
| Lunch Rush | Blocked by Turbo | Adds a midday wave and approximately +15% expected groups. |
| Dinner Rush | Blocked by Turbo | Adds an evening wave and approximately +15% expected groups. |
| Herd Mentality | - | Moves arrivals into morning, lunch, and dinner waves without itself adding customers. |
| Advertising | May recur | Adds 25% customers. |
| All You Can Eat | - | After a course, a group has a chance to repeat that course once; expected groups -30%. |
| Double Helpings | Requires All You Can Eat | Raises repeat-course and starter/side/dessert order chances; expected groups -15%; adds dish revenue. |
| Blindfolded Chefs | - | Hides food-process progress bars; desk progress remains separate. |
| Closing Time? | - | Can spawn customers after the time bar closes if service remains uncleared after a grace period. |
| Discounts | - | Revenue -25%. |
| Empathy | - | Hides in-restaurant patience gauges, although low patience still flashes; queue bar remains visible. |
| Health and Safety | - | Customers are slowed by mess. |
| High Expectations | - | Most patience -20%; Hosting Stand waiting is an exception. |
| High Quality | - | Most food processes are 20% slower; desk work and some actions are exceptions. |
| High Standards | Blocked by Salad | Burn rate doubled for burnable food. |
| Instant Service | Blocked by Coffee Shop setting | Removes the Service/order-taking phase. |
| Leisurely Eating | - | Eating duration +300%, with correspondingly more time to create mess; expected groups -15%. |
| Personalised Waiting | - | A group can change its order once per course before any part is delivered; change resets patience. |

| **Card** | **Prerequisite/block** | **Mechanical effect** |
| --- | --- | --- |
| Picky Eaters | - | May leave food on dirty plates; leftovers require disposal before washing and arenot fully automatable. |
| Photographic Memory | - | Orders are hidden unless a player is near the table. |
| Relaxed Atmosphere | - | Customers generate more mess. |
| Sedate Atmosphere | - | Players move 50% slower near customers in the same room. |
| Simplicity | - | Each research/copy/discount desk can affect only one cabinet per day. |
| Splash Zone | - | Customer/appliance messes and sink wet spots use a wider area. |
| Tipping Culture | - | Payment depends on remaining Waiting for Food patience. |
| Victorian Standards | - | Relevant table patience drains faster while customers can see a nearby player in the same room. |

### 10.4 Themes

The first theme choice normally appears for Day 6, with thresholds at 3, 6, and 9 points. Decoration days replace the normal shop with theme/miscellaneous decoration choices plus free wallpaper/flooring options. [S14]

#### Theme Thresholds Progressive effects

Faster Thinking and Eating; 50% consumable reuse chance; Waiting for Food shortened Affordable 3 / 6 / 9 and Delivery merged.

More Service patience; slower table-patience loss near players; customers may sit Charming 3 / 6 / 9 before a table is cleared.

More queue patience; +1 coin per delivered item; active queue prevents table-patience Exclusive 3 / 6 / 9 decay.

Less customer mess; much larger delivery patience recovery; no customer-generated Formal 3 / 6 / 9 mess at level 3.

### 10.5 Franchise cards

#### Expected-

#### Card/family Effect groups

#### modifier

Bootstrapping Two random free starting appliances +30%

Grabber Free Grabber at run start +30%

Wash Basin Free Wash Basin at run start +30%

| **Card/family** | **Effect** | **Expected-** **groups** **modifier** |
| --- | --- | --- |
| Coffee Tables / Conveyors / Floor Protectors / Flower Pots | Named appliance becomes a frequent staple blueprint | +30% |
| Metal Table / Simple Cloth Table | Named table becomes a frequent staple blueprint | varies |
| Loyal Customer | Buying can create another blueprint | +30% |
| Second Helpings | Chance a blueprint remains purchasable again | +30% |
| Careful Accounting | Revenue +50% | +30% |
| Catalogue | One extra shop blueprint each day | +30% |
| Coupons | Blueprint prices -25% | +30% |
| Double Homework | Desk copying creates two copies | +30% |
| High Tech Suppliers | Shop and rerolls can yield upgraded blueprints more often | +30% |
| Mandatory Tips | Flat bonus per customer served | +30% |
| Preparation Time | Customers start later | +30% |
| Reincarnation | Consumed Extra Lives regenerate daily | +30% |
| Savings | Start with extra money | +30% |
| Supplier Error | Shop prices are randomized | +30% |
| Variety | Adds another selectable starting recipe to future franchise runs | special |

### 10.6 Difficulty, setting, and romantic cards

#### Class Cards Important effects

Difficult y Focus, Renown, Simplicity, Variety, Quality, Burn, customers, desks, recipes, process speed, patience, card Expectation, Discount, Expansion income, and group-size difficulty. s

Setting Community, Flower Pots, Turbo, Coffee Shop, Only offered in their settings; can carry through franchise card Banquet Dining, Enchantment, Christmas Treats even if the setting later changes. s

Romanti Queue-patience boosts and relationship-specific Couples, Double Dates, First Dates c group/behavior rules.

### 10.7 Preparation-policy compatibility rule

The preparation/strategy layer must not select a card/appliance/layout merely because it is globally strong. It must score:

```text
strategic_value
- service_policy_failure_risk
- unsupported_recipe_or_appliance_penalty
- layout/pathing_risk
- retraining_cost
```

Every candidate layout should be tested by the current service policy. Unsupported mechanics must either be blocked in the first project or trigger a clearly separated training stage before scored evaluation.

## 11. Headquarters, setup, restaurant settings, and franchise lifecycle

### 11.1 HQ state that changes available actions

- Experience level unlocks recipe slots, floorplan slots, recipes, larger layouts, settings, seeded runs, and later HQ facilities.

- Current recipe/floorplan shelves can be rerolled by entering/leaving Tutorial according to the HQ reference.

- Dish Cabinet provides access to unlocked base dishes later in progression.

- Save slots, active franchise, and garage inventory affect start options.

- A dedicated AI test profile should have a backed-up known HQ state.

### 11.2 Fresh run setup

Required decisions:

1. Fresh run versus selected franchise.

2. Restaurant setting.

3. Base recipe (and extra franchise recipes when Variety applies).

4. Floorplan or entered/daily/weekly seed.

5. Seed behavior option.

6. Zero to two garage items in the Loading Bay.

7. Start run.

For a reproducible baseline, use public stable, a fresh run, fixed recipe, fixed setting, fixed seed, empty garage, no Extra Life, and only the bridge plus dependencies.

### 11.3 Garage

- Storage room has 25 visible slots but can stack more than one item in a slot.

- Loading Bay accepts one or two items for the next run.

- Workshop combines crates; Upgrade Kit operates in HQ and cannot itself enter a restaurant.

- End-of-game reward availability depends on progression and host state.

### 11.4 Franchise

- Completing Day 15 enables a future franchise-card choice.

- When the run later ends, the player may create a franchise by selecting three eligible non-franchise cards from that run or scrap for experience.

- A franchise carries its base recipe, theme, franchise card(s), and selected cards.

- Starting a franchise consumes/removes that saved franchise from HQ; failure before re-franchising loses it.

- Tier is a count/history indicator rather than an independent hidden difficulty multiplier; carried cards create the difficulty.

### 11.5 Settings

City/Country/Alpine are normal visual/weather/layout families; special settings such as Autumn, Turbo, Coffee Shop, Banquet Hall, Witch Hut, and event variants modify rules. The baseline must fix the setting rather than let it drift.

### 11.6 Taste-Test boundary

Heat, Chill, Greenhouse plants, and their later hotfix behavior belong to official 1.4.4 Taste-Test announcements in the sources checked. They are not silently included in the stable 1.4.3 schema. If the agent runs the beta:

- Set branch: taste_test.

- Extend setting/setup schemas rather than reusing stable assumptions.

- Record the exact beta build suffix.

- Maintain separate training/evaluation results.

## 12. Edge cases, contradictions, and version-sensitive behavior

### 12.1 Known source conflicts

| **Conflict** | **Stable handling** |
| --- | --- |
| Older pot/provider pages mention Combiner-based water automation. | Official 1.4.3 patch overrides: use Portioner-driven automationand verify live. |
| Auto Plater says it provides two plates but stores up to three. | Read provider/storage counts from live components; retain both |

| **Conflict** | **Stable handling** |
| --- | --- |
|  | source statements as a warning. |
| Sandwich/Sundae unlock and course rows differ across index/cards/individual pages after 1.4. | HQ unlocked state and live Card/Recipe GDO win. |
| Some recipe eating-time tables were corrected in 1.4.2/1.4.3. | Read live item/card value; cite official eating-time fix. |
| Wiki Upgrade Tree and event enchantment pages can evolve independently. | Keep normal upgrade and enchantment graphs separate; record page/build date. |

### 12.2 Important gameplay edge cases

- A plate protects food from further burn progression.

- A table can become path-committed after being briefly cleared.

- Dirty plate with leftovers is a different state from dirty plate.

- Fish providers choose daily contents from unlocked fish recipes; menu coverage depends on provider count.

- A whole portionable batch may be accepted by Buffet/customer self-service where a normal table delivery expects a portion.

- Smart Grabber training persists from Practice into service; Rotating Grabber output orientation can also persist.

- Practice resets most transient changes but preserves specific automation configuration.

- Loose blueprints vanish during Practice but return on exit; they are truly lost when the day starts.

- An appliance placed in a doorway converts it into a serving hatch and changes traversal.

- Half-width appliance collision may allow players through gaps that customers cannot use.

- A Sink can be a generic surface while also supplying water/cleaning; upgraded sinks may remove water capability.

- Heated Mixer can cook but may not satisfy the game's setup requirement for a qualifying cooking appliance.

- Fire can disable manual interaction but automatic movement can continue.

- Early-day failure has a soft-reset option; later failure ends the run.

- Extra Life can prevent immediate loss and has early-day/regeneration edge rules.

- Closing Time can add customers after the displayed schedule.

- Multi-course orders repeat the dining state machine.

- Extras/condiments can restart Eating and create a new Delivery phase.

### 12.3 Modded-content rule

Never map a modded object to a vanilla semantic ID solely by display name. Store:

- source mod/workshop ID,

- live GDO ID,

- unique semantic ID,

- inherited traits/processes,

- explicit compatibility edges,

- schema extension version.

## 13. PowerShell/C# telemetry bridge contract

### 13.1 Companion schema

The full Draft 2020-12 schema is delivered separately as:

plateup-telemetry.schema.json

The schema covers session/build provenance, phase, run configuration, spatial tiles/rooms, players, entities/slots/processes, customer groups, orders, shop state, live affordances, and events.

### 13.2 Snapshot versus event stream

Use both:

- **Snapshot:** authoritative current state at a sequence number.

- **Events:** what changed since the previous snapshot.

Never reconstruct critical state only from events; dropped pipe messages can corrupt the world model. Never log only snapshots; they hide causality and make reward/debug analysis difficult.

### 13.3 Semantic IDs

Use stable readable IDs such as:

```text
appliance.plates
appliance.sink.standard
item.plate.clean
item.plate.dirty
item.plate.dirty_with_leftovers
recipe.steak.rare
process.clean
card.customer.medium_groups
phase.customer_service
```

Also retain live numeric/string GDO IDs. Semantic IDs are for storage/model use; GDO IDs are for exact build integration.

### 13.4 Minimum high-frequency service snapshot

At 10-20 decision ticks per in-game second, emit only decision-critical fields:

- Player pose/facing/held/tool/current action.

- Nearby/path-relevant entity slots and processes.

- Customer group phase, patience, table, orders.

- Live floor hazards and fires.

- Current task-relevant recipe states and orders.

- Legal primitive affordances.

- Events since last tick.

Full restaurant metadata, descriptions, source notes, and static recipe graphs can be sent at reset or on change.

### 13.5 Example snapshot

```json
{
"schema_version": "1.0.0",
"sequence": 4812,
"captured_at_utc": "2026-07-27T05:14:03Z",
"monotonic_time_ms": 133704,
"session": {
"session_id": "run-burger-seed-abc",
"game_version": "1.4.3",
"steam_build_id": "RECORD_AT_RUNTIME",
"branch": "public_stable",
"platform": "steam_windows",
"bridge_version": "0.1.0",
"kitchenlib_version": "RECORD_AT_RUNTIME",
"mod_manifest_hash": "sha256:...",
"observation_schema_hash": "sha256:..."
},
"phase": {
"location": "restaurant",
"subphase": "customer_service",
"day": 3,
"overtime_day": null ,
"day_progress_0_1": 0.61,
"is_night": false ,
"weather": "clear",
"time_scale": 1.0,
"can_ready": false ,
"all_players_ready": null
},
"run": {
"run_id": "run-burger-seed-abc",
"seed": "ABC123",
"seed_affects": "everything",
"setting": {"semantic_id": "setting.city", "display_name": "City",
"gdo_id": 1, "source_mod_id": null },
"base_recipe": {"semantic_id": "recipe.burgers", "display_name":
"Burgers", "gdo_id": 2, "source_mod_id": null },
"floorplan": {"semantic_id": "floorplan.abc123", "display_name":
"ABC123", "gdo_id": null , "source_mod_id": null },
"is_franchise": false ,
"franchise_tier": null ,
"player_count": 1,
"expected_groups": 4,
"additional_rush_groups": 0,
"minimum_group_size": 1,
"maximum_group_size": 2,
"coins": 31,
"active_cards": [],
"theme": null ,
"theme_points": null
},
"world": {"rooms": [], "tiles": []},
"players": [{
"player_id": "player.1",
"position": {"x": 7.2, "y": 3.0},
"grid": {"x": 7, "y": 3},
"room_id": "room.kitchen",
"facing": "south",
"velocity": {"x": 0, "y": 0},
"held_items": [{"semantic_id": "item.plate.clean", "display_name":
"Plate", "gdo_id": 123, "source_mod_id": null }],
"carry_capacity": 1,
"equipped_tools": [],
"footwear": null ,
"current_action": null ,
"action_progress_0_1": null ,
"movement_speed_multiplier": 1.0
}],
"entities": [],
"customer_groups": [{
"group_id": "group.7",
"size": 2,
"phase": "waiting_for_food",
"member_ids": ["customer.10", "customer.11"],
"table_entity_id": "table.2",
"target_entity_id": "table.2",
"patience": {
"current": 26.1,
"maximum": 120.0,
"normalized": 0.2175,
"decay_per_second": 1.0,
"seconds_to_failure_estimate": 26.1,
"is_urgent": true ,
"urgency_threshold_source": "game_component",
"visible_to_player": true
},
"orders": ["order.7.1", "order.7.2"],
"path_reachable": true
}],
"orders": [],
"shop": {},
"affordances": [{
"affordance_id": "aff.4812.clean",
"actor_id": "player.1",
"verb": "clean_floor",
"target_id": "tile.7.2",
"item_id": null ,
"available": true ,
"blockers": [],
"hold_seconds": 1.0,
"expected_effect": "Remove small customer mess while retaining
carried plate",
"confidence": 1.0,
"source": "game_rule_check"
}],
"events_since_previous": [],
"derived_metrics": {"urgent_group_count": 1},
"warnings": []
}
```

### 13.6 PowerShell transport recommendations

- C# bridge owns game access; PowerShell is an operator console/log sink, not the high-frequency control loop.

- Use a local named pipe or loopback IPC with length-prefixed UTF-8 JSON or MessagePack.

- Include sequence, monotonic timestamp, snapshot hash, and acknowledgement.

- Keep human-readable PowerShell summaries separate from canonical JSON output.

- Rotate logs by run/session and never overwrite the only trajectory.

- On desynchronization, request a full snapshot and discard derived state after the last acknowledged sequence.

### 13.7 Action command/receipt

Commands should be primitive and acknowledged:

```json
{
"command_id": "cmd.991",
"expected_snapshot_sequence": 4812,
"actor_id": "player.1",
"verb": "interact",
"target_id": "tile.7.2",
"hold_ms": 100
}
```

Receipt:

```json
{
"command_id": "cmd.991",
"accepted": true ,
"applied_at_sequence": 4813,
"result_event_ids": ["event.mess_removed.72"],
"rejection_reason": null
}
```

## 14. Verification harness and acceptance tests

### 14.1 Golden rule

Do not mark a static claim verified_live until a repeatable probe passes on the recorded build.

### 14.2 Mandatory bridge tests

1. **Version test:** game version, Steam build, branch, mods, schema, and registry hashes are non-empty.

2. **State identity:** entity IDs remain stable across snapshots while live; reused IDs are generation-scoped.

3. **Action release:** movement/Interact/Grab never sticks after command completion or disconnect.

4. **Snapshot recovery:** deliberate dropped events are repaired by a full snapshot.

5. **Reset determinism:** fixed scenario returns expected recipe, layout, appliances, and seed.

6. **Phase gating:** preparation-only actions are rejected in service and vice versa.

7. **No hidden future leakage:** observation allowlist is audited.

### 14.3 Placement/capacity probe suite

For each item class and surface:

- Query affordance before action.

- Attempt if allowed.

- Record source and destination slot counts.

- Verify expected automatic process.

- Remove item and verify state restoration.

- Repeat at full capacity and wrong homogeneous type.

- Repeat across preparation/practice/service where meaningful.

Required first probes:

- Four Starter Plates, eight Plates, four Dish Rack dirty plates.

- Dish Rack rejection of clean plates and leftovers.

- Wash Basin/Dish Washer mixed clean/dirty rejection.

- Prep Station four-identical rule and rejection of plate/pot/whole portionable batch.

- Tray two-item storage and no auto-combination.

- Clean/dirty plate on Counter, table, Hob, Sink, Conveyor, and Grabber.

- Ingredient return to matching provider versus modified ingredient rejection.

### 14.4 Held-item and cleaning probes

- Hold clean plate, Interact with small mess, confirm plate retained and mess progress changes.

- Repeat with plated food, dirty plate, Scrubbing Brush equipped, Mop carried, Fire Extinguisher carried, and Tray.

- Attempt bin emptying while carrying an item and confirm blocker.

- Verify tool and footwear state channels separately.

### 14.5 Customer probes

- Default 1-2 groups and table validation.

- Individual, Medium, Large, Flexible combinations.

- Path reachability for player-only half-tile gaps.

- Head-table dirty return after table combination/reorder.

- Queue decay under day/night/rain/snow and multiple queuers.

- Empathy/Photographic Memory visibility.

- Extra-item request and Eating reset.

- Buffet partial order and customer route.

### 14.6 Recipe probes

For every extracted process:

- Validate input state IDs.

- Validate required action/surface/process.

- Measure base duration at 1x.

- Validate output, portions, by-product, and burn transition.

- Validate plate/equipment composition.

- Validate order acceptance.

- Validate automation through Combiner/Portioner/Grabber where supported.

Run recipe probes again after every game update.

### 14.7 Stable 1.4.3 regression tests

- Combiner does not perform old sink/milk/ice fill behavior.

- Portioner does perform supported fill behavior.

- Start-day is blocked when plates cannot cover maximum group.

- Smart Grabber priority works when grabbing from another grabber.

- Piecemeal deliveries award correctly.

- Cakes and fast-food eating durations match live data.

### 14.8 Promotion workflow

```text
unverified
-> sourced_static
-> probe_written
-> verified_on_build
-> regression_guarded
-> stale_after_update (automatic until re-run)
```

Any upgrade, patch, branch switch, or mod change invalidates affected verified_on_build facts until regression tests pass.

## 15. Source register

| **ID** | **Source** | **URL** | **Use** |
| --- | --- | --- | --- |
| S01 | Official PlateUp press kit | [open](https://www.plateupgame.com/presskit/) | Primary overview: 15-day run, card cadence, HQ/franchise imagery. |

| **ID** | **Source** | **URL** | **Use** |
| --- | --- | --- | --- |
| S02 | Official patch 1.4.3 | [open](https://www.plateupgame.com/updates/1-4-3/) | Primary override for sink/portioner automation, plate-start validation, eating-time fixes, and grabber priority. |
| S03 | Official Steam announcements | [open](https://steamcommunity.com/app/1599600/announcements/) | Primary release stream; distinguishes public patch from 1.4.4 Taste-Test beta. |
| S04 | PlateUp community wiki - Recipes | [open](https://wiki.plateupgame.co.uk/recipes) | Current recipe catalog and links to per-recipe process pages. |
| S05 | PlateUp community wiki - Appliances | [open](https://wiki.plateupgame.co.uk/appliances) | Current appliance/equipment catalog. |
| S06 | PlateUp community wiki - Controls | [open](https://wiki.plateupgame.co.uk/gameplay/Controls) | Grab, Interact, Ready, Ping, Stand Still, and phase-specific controls. |
| S07 | PlateUp community wiki - Restaurant | [open](https://wiki.plateupgame.co.uk/gameplay/Restaurant) | Rooms, hatches, surfaces, mess, wet/buffed floors, fire, and placement behavior. |
| S08 | PlateUp community wiki - Customers | [open](https://wiki.plateupgame.co.uk/gameplay/Customers) | Groups, pathing, patience phases, formulas, and expected-groups rules. |
| S09 | PlateUp community wiki - Daily Operations | [open](https://wiki.plateupgame.co.uk/gameplay/DailyOperations) | Preparation/customer phases, day cadence, practice, cards, themes, overtime, and franchise creation. |
| S10 | PlateUp community wiki - Blueprints | [open](https://wiki.plateupgame.co.uk/gameplay/Blueprints) | Shop pools, rerolls, Blueprint Desk, and blueprint modifiers. |
| S11 | PlateUp community wiki - Research | [open](https://wiki.plateupgame.co.uk/gameplay/Research) | Cabinet adjacency, upgrade/copy/discount rules, and per-day limits. |
| S12 | PlateUp community wiki - Upgrade Tree | [open](https://wiki.plateupgame.co.uk/appliances/UpgradeTree) | Upgrade graph; page edited 24 June 2026 in the retrieved snapshot. |
| S13 | PlateUp community wiki - Cards | [open](https://wiki.plateupgame.co.uk/Cards) | Base, food, customer, theme, franchise, setting, and romantic cards. |
| S14 | PlateUp community wiki - Decorations | [open](https://wiki.plateupgame.co.uk/Decorations) | Decoration-day offerings and theme thresholds/effects. |
| S15 | PlateUp community wiki - Headquarters | [open](https://wiki.plateupgame.co.uk/gameplay/Headquarters) | Profile progression, recipe/floorplan selection, seeded runs, garage, franchises, and loading bay. |
| S16 | PlateUp community wiki - Automation | [open](https://wiki.plateupgame.co.uk/Automation) | Automation patterns and limitations. |
| S17 | KitchenLib repository | [open](https://github.com/KitchenMods/KitchenLib) | Current Workshop-oriented modding library and |

| **ID** | **Source** | **URL** | **Use** |
| --- | --- | --- | --- |
|  |  |  | provenance guidance. |
| S18 | KitchenLib Appliance GDO reference | [open](https://github-wiki-see.page/m/KitchenMods/KitchenLib/wiki/Appliance) | Documents appliance properties such as item holders, processes, and upgrades; older reference, so confirm against current assemblies. |

### 15.1 Source notes

- The official patch/announcement sources are primary for version boundaries.

- The PlateUp wiki is a high-quality mechanics reference but is community maintained and can contain cross-page lag after patches.

- KitchenLib documentation shows useful GDO/component patterns but some wiki pages are older than the current stable game. Inspect the actual installed assemblies/components.

- Page edit dates from the retrieved wiki snapshot are preserved in work/plateup_wiki_pages.json during generation but are not a substitute for game-build verification.

## Appendix A. Full recipe preparation/process reference

The following normalized step lists are extracted from the current per-recipe pages. They are reference data, not a substitute for live GDO/process validation. Times are generally reported at the source page's stated baseline and may change with appliances, cards, gas modifiers, player count, patches, or mods.

### Black Coffee

Source: [Black Coffee recipe page.](https://wiki.plateupgame.co.uk/recipes/BlackCoffee)

#### Black Coffee

- Grab Coffee Cup from Coffee Machine and Place back into Machine

- Fill Coffee Cup 3s (automatic, does not burn)

- Grab Coffee and serve!

- (provide Extra Sugar or Extra Milk or Cake Stand if requested)

#### Iced Coffee

- Wait for Ice Dispenser to refill with Ice (automatic, one every 10 seconds)

- Combine Black Coffee with Ice (from Ice Dispenser) to make Iced Coffee

- Grab Iced Coffee and serve!

- (provide Extra Sugar or Extra Milk or Cake Stand if requested)

#### Latte

- Grab Milk and Place into Milk Steamer to refill

- Froth Black Coffee on Milk Steamer to make Latte

- Grab and serve!

- (provide Extra Sugar or Extra Milk or Cake Stand if requested)

#### Tea

- Combine Tea Pot with Water (from Sink) and Tea Bag

- Steep Tea Pot 10s

- Grab and serve! (can be shared by up to 4 customers at a table)

- Also Grab Tea Cup and serve! (one per customer)

- (provide Extra Sugar or Extra Milk or Cake Stand if requested)

#### Affogato

- Grab Coffee Cup from Coffee Machine and Place back into Machine

- Fill Coffee Cup 3s (automatic, does not burn)

- Interact with Ice Cream Freezer to select Vanilla

- Combine Coffee with 1 x Vanilla Ice Cream and serve!

### Breakfast

Source: [Breakfast recipe page.](https://wiki.plateupgame.co.uk/recipes/Breakfast)

#### Breakfast

- Knead Flour 1s or Combine with Water (from Sink) to make Dough

- Cook Dough 20s | +20s to burn to make Bread

- Portion Slice from Bread 0.5s (provides 10 portions)

- Cook Slice of Bread 3s | +3s to burn to make Toast

- Plate and serve!

#### Breakfast Beans

- Combine Pot with Beans

- Cook Beans 8s (does not burn)

- Combine with plated Toast and serve!

- (provides 4 portions, leaves empty Pot once depleted)

#### Breakfast Eggs

- Chop Egg 0.1s

- Cook Cracked Egg 3s | +10s to burn

- Combine Cooked Egg with plated Toast and serve!

#### Breakfast Extras

- Chop Tomato 0.5s and/or Mushroom 1s

- Combine Chopped Tomato and/or Chopped Mushroom with plated Toast and serve!

### Burgers

Source: [Burgers recipe page.](https://wiki.plateupgame.co.uk/recipes/Burgers)

#### Burgers

- Cook Raw Patty 2s | +2s to burn

- Combine Cooked Patty with Burger Bun

- (add requested toppings from Burger Toppings and/or Cheeseburgers)

- Plate and serve!

#### Burger Toppings

- Chop Onion 1s and/or Tomato 0.5s

- Combine Chopped Onion and/or Chopped Tomato with Burger

- (continue to make Burgers)

#### Cheeseburgers

- Chop Cheese 1s

- Combine Chopped Cheese with Burger

- (continue to make Burgers)

#### Fresh Patties

- Chop Raw Meat 2s and Egg 0.1s

- Combine Chopped Meat with Cracked Egg to make Raw Patty

- (continue to make Burgers)

### Cakes

Source: [Cakes recipe page.](https://wiki.plateupgame.co.uk/recipes/Cakes)

#### Cakes (a.k.a Cookies + Chocolate Flavour)

- No step list was extracted; use the live recipe GDO and validate manually.

#### Sponge Cakes

- Combine Cake Batter with Milk

- Combine Mixing Bowl with Cake Tin and Cook 45s | +12s to burn (optional, use microwave oven to bake at a fix time of 5s)

- Combine Cooked Sponge with flavour

- Portion 1s and serve! (provides 6 portions)

#### Cupcake

- Combine Cake Batter with Milk

- Combine Mixing Bowl with Cupcake Tray and Cook 12s | +12s to burn

- Portion 1s (provides 4 portions)

- Combine Cupcake with flavour and serve!

#### Doughnut

- Combine Cake Batter with Milk

- Combine Mixing Bowl with Doughnut Tray and leave to rise 10s

- Combine Pot with Oil

- Portion Doughnut Tray 1s and Combine with pot (provides 12 portions)

- Cook Pot with Doughnut 2s and Portion 1s (provides 1 portion)

- Combine Cooked Doughnut with flavour and serve!

#### Brownies

- Combine Cake Batter with Chcocolate flavour

- Combine Mixing Bowl with Brownie Tray and Cook 9s | +20s to burn

- Portion 1s and serve! (provides 6 portions)

#### Cake Flavor - Coffee

- Grab Coffee Cup from Coffee Machine and Place back into Machine

- Fill Coffee Cup 3s (automatic, does not burn)

- Grab Coffee and use in a cake recipe!

#### Cake Flavor - Lemon

- Chop lemon and use in a cake recipe 1s

### Dumplings

Source: [Dumplings recipe page.](https://wiki.plateupgame.co.uk/recipes/Dumplings)

#### Dumplings

- Knead Flour 1s or Combine with Water (from Sink) to make Dough

- Chop Raw Meat 2s and Carrot 1s

- Combine Chopped Meat and Chopped Carrot with Dough to make Unwrapped Dumplings

- Knead Unwrapped Dumplings 0.1s to make Raw Dumplings

- Cook Raw Dumplings 1s | +3s to burn

- Plate and serve!

#### Seaweed

- Cook Raw Seaweed 1s | +3s to burn

- Combine with plated Dumplings and serve!

### Fish

Source: [Fish recipe page.](https://wiki.plateupgame.co.uk/recipes/Fish)

#### Fish

- Cook Blue Fish 7s | +14s to burn or Pink Fish 4s | +6s to burn

- Plate and serve!

#### Crab Cake

- Chop Crab 1s and Egg 0.1s

- Combine Chopped Crab with Cracked Egg, then Flour to make Raw Crab Cake

- Cook Raw Crab Cake 5s | +6s to burn

- Plate and serve!

#### Fish Fillet

- Chop Raw Fish Fillet 2s

- Cook Chopped Fish Fillet 3s | +4s to burn

- Plate and serve!

#### Oysters

- Chop 2 or 3 Oysters 0.2s each

- Plate all Shucked Oysters together and serve!

#### Spiny Fish

- Portion Spines from Raw Spiny Fish 1s and Discard

- Cook Raw Deboned Fish 4s | +8s to burn

- Plate and serve!

### Hot Dogs

Source: [Hot Dogs recipe page.](https://wiki.plateupgame.co.uk/recipes/HotDogs)

#### Hot Dogs

- Cook Raw Hot Dog 3s | +4s to burn

- Combine Cooked Hot Dog with Hot Dog Bun

- Plate and serve!

- (Provide Ketchup or Mustard if requested)

### Pies

Source: [Pies recipe page.](https://wiki.plateupgame.co.uk/recipes/Pies)

#### Pie Crust (Base)

- Knead Flour 1s or Combine with Water (from Sink) to make Dough

- Knead Dough 2s to make Raw Pie Crust

- (optional) Cook Raw Pie Crust 5s | +20s to burn before adding filling (less time-efficient)

#### Pies

- Combine Meat with Pie Crust to make Raw Meat Pie

- Cook Raw Meat Pie 5s | +20s to burn (cooks in 3s if Pie Crust is already cooked)

- Plate and serve!

#### Mushroom Pie

- Combine Mushroom with Pie Crust to make Raw Mushroom Pie

- Cook Raw Mushroom Pie 5s | +20s to burn (cooks in 3s if Pie Crust is already cooked)

- Plate and serve!

#### Vegetable Pies

- Combine Carrot and Broccoli with Pie Crust to make Raw Vegetable Pie

- Cook Raw Vegetable Pie 5s | +20s to burn (cooks in 3s if Pie Crust is already cooked)

- Plate and serve!

### Pizza

Source: [Pizza recipe page.](https://wiki.plateupgame.co.uk/recipes/Pizza)

#### Pizza

- Knead Flour 1s or Combine with Water (from Sink) to make Dough

- Combine Dough with Oil to make Pizza Base

- Chop (x2) Tomato 0.5s + 1s to make Tomato Sauce

- Chop Cheese 1s

- Combine Pizza Base with Tomato Sauce, then Chopped Cheese to make Raw Pizza

- Cook Raw Pizza 8s | +8s to burn

- Portion 1s onto Plate and serve! (provides 4 portions)

#### Mushroom Pizza

- Chop Mushroom 1s

- Combine Chopped Mushroom with Raw Pizza

- Cook Raw Mushroom Pizza 8s | +8s to burn

- Portion 1s onto Plate and serve! (provides 4 portions)

#### Onion Pizza

- Chop Onion 1s

- Combine Chopped Onion with Raw Pizza

- Cook Raw Onion Pizza 8s | +8s to burn

- Portion 1s onto Plate and serve! (provides 4 portions)

### Salad

Source: [Salad recipe page.](https://wiki.plateupgame.co.uk/recipes/Salad)

#### Salad

- Chop Lettuce 1s and Tomato (optional) 0.5s

- Plate Chopped Lettuce and Chopped Tomato (optional) and serve!

#### Apple Salad

- Chop Egg 0.1s and Combine with Oil to make Mayonnaise

- Chop Lettuce 1s and Apple 1s

- Plate each of Mayonnaise, Chopped Lettuce, Chopped Apple, and Nuts, and serve!

#### Potato Salad

- Chop Potato 1s

- Combine Pot with Water (from Sink) and Chopped Potato

- Cook Chopped Potato in Pot 5s (does not burn) to make Cooked Potato

- Chop Onion 1s

- Chop Egg 0.1s and Combine with Oil to make Mayonnaise

- Plate each of Cooked Potato, Chopped Onion, and Mayonnaise, and serve!

#### Salad Toppings

- Chop Onion 1s

- Combine Chopped Onion and/or Olive with plated Salad and serve!

### Sandwiches

Source: [Sandwiches recipe page.](https://wiki.plateupgame.co.uk/recipes/Sandwiches)

#### Sandwiches

- Grab a flour then knead into a flat surface for 1s or combine with water in sink to create a dough ball.

- Cook the dough ball to make loaf of bread for 20s | +20s to burn

- Portion the bread for 0.5s, then serve. (optional) Serve the whole loaf of bread.

- If the customer wants chopped tomato; Grab tomato, chop the tomato for 0.5s, then serve.

- If the customer wants chopped lettuce, Grab lettuce; chop the lettuce for 1s, then serve.

- If the customer wants ham, Grab ham, then serve.

- Finish it by serving a slice of bread. (optional) Serve the whole loaf of bread.

#### Sandwich - Toppers

- If the customer wants Pickles as toppings, Grab pickles; then serve.

- If the customer wants Olives as toppings, Grab olives; then serve.

#### Sandwich - Eggs

- If the customer wants fried egg, Grab egg from the provider,

- Crack the egg for 0.1s,

- Cook the egg for 3s | +10s to burn,

- Then serve.

#### Sandwich - Toast

- Portion a piece of bread from the loaf for 0.5s,

- Cook the slice of bread for 3s | +3s to burn,

- Then serve.

#### Sandwich - Mayo

- If the customer wants mayo; Grab an egg from the provider,

- Crack the egg for 0.1s,

- Combine cracked egg with oil,

- Then serve.

#### Sandwich - Mayo

- If the customer wants cheese; Grab cheese from the provider

- Chop the cheese for 1s

- Then serve.

#### Club Sandwiches

- Grab Raw Turkey from the provider,

- Cook the turkey for 20s | +10s to burn

- If the customer wants turkey; Portion Cooked turkey for 1s, then serve. (optional) serve the whole cooked turkey)

- If the customer wants toast; Portion Bread for 0.5s, cook for 3s | +3s to burn, then serve.

- (Discard Turkey Bones)

#### Giant Sandwiches

- Portion a piece of bread for 0.5s, then serve. (or for 3s | +3s to burn, if toast is ordered) if lettuce is ordered; grab lettuce from the provider, chop for 1s, then serve. if tomato is ordered; grab tomato from the provider, chop for 0.5s, then serve. if fried egg is ordered; grab egg from the provider, crack for 0.1s, for 3s | +3s to burn, then serve. if mayo is ordered; grab egg from the provider, crack for 0.1s, combine with oil, then serve. if cheese is ordered; grab cheese from the provider, chop for 1s, then serve. if turkey is ordered; portion a piece from cooked turkey, then serve. (Optional) serve the whole turkey

- if lettuce is ordered; grab lettuce from the provider, chop for 1s, then serve.

- if tomato is ordered; grab tomato from the provider, chop for 0.5s, then serve.

- if fried egg is ordered; grab egg from the provider, crack for 0.1s, for 3s | +3s to burn, then serve.

- if mayo is ordered; grab egg from the provider, crack for 0.1s, combine with oil, then serve.

- if cheese is ordered; grab cheese from the provider, chop for 1s, then serve.

- if turkey is ordered; portion a piece from cooked turkey, then serve. (Optional) serve the whole turkey

- Once the fillings ordered were fulfilled, Portion a piece of bread for 0.5s, then serve. (or for 3s | +3s to burn, if toast is ordered)

- (only one) if olives or pickles is ordered; Grab olives or pickles from the provider, then serve.

### Spaghetti

Source: [Spaghetti recipe page.](https://wiki.plateupgame.co.uk/recipes/Spaghetti)

#### Spaghetti II: Extra Starch

- Combine Pot with Water (from Sink) and Spaghetti

- Cook Spaghetti 2s

- Dispose water into bin

- Grab Spaghetti portion with a plate (provides 2 portions)

#### Spaghetti I: Traditional Recipe

- Combine Pot with Water (from Sink) and Spaghetti

- Cook Spaghetti 2s

- Dispose water into sinks

- Grab Spaghetti portion with a plate (provides 2 portions)

#### Spaghetti

- Chop (x2) Tomato 0.5s + 1s to make Tomato Sauce

- Combine with Plain Spaghetti and serve!

#### Spaghetti Bolognese

- Cook mince 2s | 2s to burn

- Chop (x2) Tomato 0.5s + 1s to make Tomato Sauce

- Combine cooked Mince and Tomato Sauce with Pot to make Bolognese sauce

- Cook Bolognese sauce 3s (does not burn)

- Combine with Plain Spaghetti and serve!

#### Cheesy Spaghetti

- Combine Pot with Flour and Butter to make Roux

- Cook Roux 2s (does not burn)

- Combine cooked Roux with Milk

- Knead Roux 1s

- Combine mixed Roux with Milk again

- Knead Roux 1s again to make white sauce

- Chop Cheese 1s

- Combine Plain Spaghetti with White Sauce and Chopped Cheese, then serve!

#### Lasagne

- Add Bolognese Sauce, Pasta Sheet, and White Sauce to Lasagne Tray in order, twice

- Cook Lasagne 20s | 10s to burn

- Portion 1s onto Plate and serve! (provides 4 portions)

### Starters, Sides, and Desserts

Source: [Starters, Sides, and Desserts recipe page.](https://wiki.plateupgame.co.uk/recipes/StartersSidesDesserts)

#### Broth (Base)

- Combine Pot with Water (from Sink) and Onion to make Broth

- Cook Broth 15s

- (add other ingredients to make any Soup, and Portion until depleted)

- Combine Drained Broth with Water (from Sink) to refill

- Cook Refilled Broth 3s and reuse!

#### Broccoli Cheese Soup

- Combine Broccoli and Cheese with Broth (see Broth Recipe)

- Cook Broccoli Cheese Broth 6s (does not burn) to make Broccoli Cheese Soup

- Portion 1s and serve!

- (provides 3 portions, leaves Drained Broth once depleted)

#### Carrot Soup

- (optional) Chop Carrot 1s

- Combine Carrot or Chopped Carrot with Broth (see Broth Recipe)

- Cook Carrot Broth 10s (does not burn, cooks in 8s with Chopped Carrot) to make Carrot Soup

- Portion 1s and serve!

- (provides 3 portions, leaves Drained Broth once depleted)

#### Meat Soup

- (optional) Chop Raw Meat 2s

- Combine Raw Meat or Chopped Meat with Broth (see Broth Recipe)

- Cook Meat Broth 12s (does not burn, cooks in 6s with Chopped Meat) to make Meat Soup

- Portion 1s and serve!

- (provides 3 portions, leaves Drained Broth once depleted)

#### Pumpkin Soup

- Portion Seeds from Pumpkin 0.3s to make Hollow Pumpkin

- (Discard Seeds, or use in Pumpkin Seed Recipe)

- Chop Hollow Pumpkin 2s

- Combine Chopped Pumpkin with Broth (see Broth Recipe)

- Cook Pumpkin Broth 6s (does not burn) to make Pumpkin Soup

- Portion 1s and serve!

- (provides 3 portions, leaves Drained Broth once depleted)

#### Tomato Soup

- Chop (x2) Tomato 0.5s + 1s to make Tomato Sauce

- Combine Tomato Sauce with Broth (see Broth Recipe)

- (optional) Chop Tomato 0.5s

- Combine Tomato or Chopped Tomato with Broth

- Cook Tomato Broth 8s (does not burn, cooks in 4s with Chopped Tomato) to make Tomato Soup

- Portion 1s and serve!

- (provides 3 portions, leaves Drained Broth once depleted)

#### Bread

- Knead Flour 1s or Combine with Water (from Sink) to make Dough

- Cook Dough 20s | +20s to burn to make Bread

- Portion 2 x Slices from Bread 0.5s (provides 10 portions)

- Combine 2 x Slices of Bread with Serving Board

- Grab and serve!

- (Grab Serving Board from table once eaten)

#### Christmas Crackers

- Grab Christmas Cracker and serve!

#### Mandarin Starter

- Portion 2 or 4 Mandarin Slices as requested 1s each (automatically creates bowl)

- (provides 4 portions, disappears once depleted)

- Grab and serve!

#### Pumpkin Seed

- Portion Seeds from Pumpkin 0.3s

- (Discard Hollow Pumpkin, or use in Pumpkin Soup or Pumpkin Pies Recipes)

- Cook Pumpkin Seeds 4s | +6s to burn

- Grab and serve!

#### Bamboo

- Combine Pot with Water (from Sink) and Raw Bamboo

- Cook Raw Bamboo in Pot 10s (does not burn)

- Portion 1s and serve with Main!

- (provides 3 portions, leaves empty Pot once depleted)

#### Broccoli

- Combine Pot with Water (from Sink) and Broccoli

- Cook Broccoli in Pot 10s (does not burn)

- Portion 1s and serve with Main!

- (provides 5 portions, leaves empty Pot once depleted)

#### Chips

- Chop Potato 1s

- Cook Chopped Potato 2s | +4s to burn to make Chips

- Plate and serve with Main!

#### Corn on the Cob

- Portion Husk from Corn 1s

- (Discard Corn Husk)

- Cook Husked Corn 4s | +8s to burn to make Corn on the Cob

- Plate and serve with Main!

#### Mashed Potato

- Combine Pot with Water (from Sink) and Potato

- Cook Potato in Pot 20s (does not burn)

- Chop Potato in Pot 5s to make Mashed Potato

- Portion 1s and serve with Main!

- (provides 20 portions, leaves empty Pot once depleted)

#### Onion Rings

- Chop Onion 1s

- Combine Chopped Onion with Flour to make Raw Onion Rings

- Cook Raw Onion Rings 2s | +3s to burn

- Plate and serve with Main!

#### Roast Potato

- Cook Potato 5s | +10s to burn to make Roast Potato

- Plate and serve with Main!

#### Pie Crust (Base)

- Knead Flour 1s or Combine with Water (from Sink) to make Dough

- Knead Dough 2s to make Raw Pie Crust

#### Apple Pies

- Cook Raw Pie Crust 5s | +20s to burn (see Pie Crust Recipe)

- Chop Apple 1s

- Combine Chopped Apple with Cooked Pie Crust to make Raw Apple Pie

- Cook Raw Apple Pie 7s | +20s to burn

- Grab and serve!

#### Cherry Pie

- Cook Raw Pie Crust 5s | +20s to burn (see Pie Crust Recipe)

- Combine Cherries with Cooked Pie Crust to make Raw Cherry Pie

- Cook Raw Cherry Pie 3s | +5s to burn

- Grab and serve!

#### Pumpkin Pies

- (optional) Cook Raw Pie Crust 5s | +20s to burn (see Pie Crust Recipe)

- Portion Seeds from Pumpkin 0.3s to make Hollow Pumpkin

- (Discard Seeds, or use in Pumpkin Seed Recipe)

- Chop Hollow Pumpkin 2s

- Combine Chopped Pumpkin with Pie Crust to make Raw Pumpkin Pie

- Cook Raw Pumpkin Pie 5s | +5s to burn (cooks in 3s if Pie Crust is already cooked)

- Grab and serve!

#### Cheese Board

- Chop Apple 1s

- Combine Serving Board with Chopped Apple, Cheese, and Nuts to make Cheese Board

- Grab and serve! (can be shared by up to 3 customers at a table)

- (Grab Serving Board from table once eaten)

#### Ice Cream

- Interact with Ice Cream Freezer to cycle between Strawberry, Chocolate, and Vanilla

- Grab 2–3 requested flavours in any order (automatically creates bowl)

- Grab and serve!

### Steak

Source: [Steak recipe page.](https://wiki.plateupgame.co.uk/recipes/Steak)

#### Steak

- Cook Raw Meat 5s for Rare | +2s for Medium | +2s for Well-done | +10s to burn (19s total)

- Plate and serve!

#### Bone-in Steaks

- Cook Raw Bone-in Meat 5s for Rare | +3s for Medium | +3s for Well-done | +4s to burn (15s total)

- Plate and serve!

- (Portion Bone from Plate 2s and Discard once eaten)

#### Thick Cut Steaks

- Cook Raw Thick Cut Meat 10s for Rare | +8s for Medium | +8s for Well-done | +8s to burn (34s total)

- Plate and serve!

#### Thin Cut Steaks

- Cook Raw Thin Cut Meat 4s for Rare | +1s for Medium | +1s for Well-done | +1s to burn (7s total)

- Plate and serve!

#### Steak Sauce - Mushroom

- Combine Pot with Water (from Sink) and Onion to make Broth

- Cook Broth 15s initially, 3s after refill (does not burn)

- Chop Mushroom 1s and Combine with Broth to make Mushroom Sauce

- Cook Mushroom Sauce 5s (does not burn)

- Combine with any plated Steak and serve!

- (provides 10 portions, leaves empty Pot once depleted)

#### Steak Sauce - Red Wine Jus

- Combine Pot with Water (from Sink) and Onion to make Broth

- Cook Broth 15s initially, 3s after refill (does not burn)

- Combine Wine with Broth to make Red Wine Jus

- Cook Red Wine Jus 5s (does not burn)

- Combine with any plated Steak and serve!

- (provides 10 portions, leaves empty Pot once depleted)

#### Steak Topping - Mushroom

- Chop Mushroom 1s

- Combine with any plated Steak and serve!

#### Steak Topping - Tomato

- Chop Tomato 0.5s

- Combine with any plated Steak and serve!

### Stir Fry

Source: [Stir Fry recipe page.](https://wiki.plateupgame.co.uk/recipes/StirFry)

#### Stir Fry

- Combine Wok with Raw Rice and Cook 2s | +10s to burn

- Chop Carrot 1s and/or Broccoli 1s

- Combine first chopped vegetable with Wok and Cook 2s | +10s to burn

- (optional) Combine second chopped vegetable with Wok and Cook 2s | +10s to burn

- (add Bamboo and/or Chopped Mushroom and/or Chopped Meat if requested)

- Plate and serve!

#### Bamboo Stir Fry

- Combine Pot with Water (from Sink) and Raw Bamboo

- Cook Raw Bamboo in Pot 10s (does not burn)

- Portion Cooked Bamboo from Pot 1s

- (provides 3 portions, leaves empty Pot once depleted)

- Combine Cooked Bamboo with Wok and Cook 2s | +10s to burn

- (continue to make Stir Fry)

#### Mushroom Stir Fry

- Chop Mushroom 1s

- Combine Chopped Mushroom with Wok and Cook 2s | +10s to burn

- (continue to make Stir Fry)

#### Steak Stir Fry

- Chop Raw Meat 2s

- Combine Chopped Meat with Wok and Cook 2s | +10s to burn

- (continue to make Stir Fry)

### Ice Cream Sundaes

Source: [Ice Cream Sundaes recipe page.](https://wiki.plateupgame.co.uk/recipes/Sundaes)

#### Sundaes I: Scoops

- Serve a sundae glass to the customer

- Serve the requested flavours as the customer requests them (2-4 scoops)

#### Sundaes II: Homemade

- Combine sugar and milk into a mixing bowl

- Place into freezer to freeze for 5s

- Once frozen Combine in chocolate, strawberry, or nothing (makes vanilla flavor) and mix for 2s

- Portion for 1s (makes 5 portions)

- Serve a sundae glass to the customer

- Serve the requested flavours as the customer requests them (2-4 scoops)

- (optional) Serve the whole mixing bowl of ice cream

#### Sundae Syrups

- Grab the requested syrup from the provider.

- Place chocolate syrup or strawberry syrup on table to serve, if requested. (Optional) Place one chocolate or strawberry syrup bottle on a buffet.

#### Sundae Toppings

- If cranberry is requested, Grab a cranberry from the provider, then serve.

- If chopped nuts is requested, Grab a nut from the provider, Chop the nut for 2s, then serve.

#### Giant Sundaes

- Grab sundae glass from provider, then serve.

- Serve the requested flavours as the customer requests them (2-4 scoops)

- If cranberry is requested, Grab a cranberry from the provider, then serve.

- If chopped nuts is requested, Grab a nut from the provider, Chop the nut for 2s, then serve.

- If syrup is requested, Grab one the requested syrup flavor from the provider, then serve.

### Tacos

Source: [Tacos recipe page.](https://wiki.plateupgame.co.uk/recipes/Tacos)

#### Tacos

- Cook Mince 2s

- Combine Tortilla with Taco Tray

- Add the Cooked Mince to Taco Tray

- Portion 1s and serve! (provides 4 portions)

#### Tacos - Cheese

- Chop Cheese 1s

- Combine Grated Cheese with Tacos on Tray

- Portion 1s and serve! (provides 4 portions)

#### Tacos - Onion

- Chop Onion 1s

- Combine Chopped Onion with Tacos on Tray

- Portion 1s and serve! (provides 4 portions)

#### Tacos - Lettuce

- Chop Lettuce 1s

- Combine Chopped Lettuce with Tacos on Tray

- Portion 1s and serve! (provides 4 portions)

#### Tacos - Tomato

- Chop Tomato 0.5s

- Combine Chopped Tomato with Tacos on Tray

- Portion 1s and serve! (provides 4 portions)

### Turkey

Source: [Turkey recipe page.](https://wiki.plateupgame.co.uk/recipes/Turkey)

#### Turkey

- Cook Raw Turkey 20s | +10s to burn

- Portion Cooked Turkey 1s

- Plate and serve! (provides 4 portions, leaves Turkey Bones once depleted)

- (Discard Turkey Bones, or use in Turkey - Gravy Recipe)

#### Nut Roast

- Chop Onion 1s and Nuts 2s

- Combine Chopped Onion and Chopped Nuts to make Raw Nut Roast

- Cook Raw Nut Roasts 20s | +20s to burn

- Portion Cooked Nut Roast 1s

- Plate and serve! (provides 3 portions)

#### Turkey - Cranberry Sauce

- Chop Cranberry 1s

- Combine Chopped Cranberry with Sugar to make Cranberry Sauce

- Combine with plated Turkey and serve!

#### Turkey - Gravy

- Combine Pot with Water (from Sink) and Onion to make Broth

- Cook Broth 15s initially, 3s after refill (does not burn)

- Combine Broth with Turkey Bones (from depleted Turkey) to make Gravy

- Cook Gravy 6s (does not burn)

- Combine with plated Turkey and serve!

- (provides 20 portions, leaves Drained Broth once depleted)

#### Turkey - Stuffing

- Knead Flour 1s or Combine with Water (from Sink) to make Dough

- Cook Dough 20s | +20s to burn to make Bread

- Portion Slice from Bread 0.5s (provides 10 portions)

- Cook Slice of Bread 3s | +3s to burn to make Toast

- Chop Toast 1s to make Breadcrumbs

- Chop Onion 1s

- Combine Chopped Onion with Breadcrumbs to make Raw Stuffing

- Cook Raw Stuffing 3s | +6s to burn

- Combine Cooked Stuffing with plated Turkey and serve!

## Appendix B. Complete card registry

This registry records the stable categories and quantitative implications needed by the agent. Descriptive flavor text is intentionally omitted. Use live Card GDO values for the exact build.

### B1. Customer cards

| **Card** | **Prerequisite/block** | **Mechanical effect** |
| --- | --- | --- |
| Individual Dining | Blocks Medium Groups | Maximum group size -1; normal result is 1-1. Total customers are redistributed into more, smaller groups. |
| Medium Groups | Blocks Individual Dining | Minimum group size +1 and maximum +2; normal result is 2-4. |
| Large Groups | Requires Medium Groups | Minimum and maximum group size +2; normally 4-6. |
| Flexible Dining | Requires Medium Groups | Minimum -1 and maximum +1; normally 1-5, or 3-7 with Large Groups. |
| Morning Rush | Blocked by Turbo | Adds a morning wave and approximately +15% expected groups. |
| Lunch Rush | Blocked by Turbo | Adds a midday wave and approximately +15% expected groups. |
| Dinner Rush | Blocked by Turbo | Adds an evening wave and approximately +15% expected groups. |
| Herd Mentality | - | Moves arrivals into morning, lunch, and dinner waves without itself adding customers. |
| Advertising | May recur | Adds 25% customers. |
| All You Can Eat | - | After a course, a group has a chance to repeat that course once; expected groups -30%. |
| Double Helpings | Requires All You Can Eat | Raises repeat-course and starter/side/dessert order chances; expected groups -15%; adds dish revenue. |
| Blindfolded Chefs | - | Hides food-process progress bars; desk progress remains separate. |
| Closing Time? | - | Can spawn customers after the time bar closes if service remains uncleared after a grace period. |
| Discounts | - | Revenue -25%. |
| Empathy | - | Hides in-restaurant patience gauges, although low patience still flashes; queue bar remains visible. |
| Health and Safety | - | Customers are slowed by mess. |
| High Expectations | - | Most patience -20%; Hosting Stand waiting is an exception. |
| High Quality | - | Most food processes are 20% slower; desk work and some actions are exceptions. |
| High Standards | Blocked by Salad | Burn rate doubled for burnable food. |

| **Card** | **Prerequisite/block** | **Mechanical effect** |
| --- | --- | --- |
| Instant Service | Blocked by Coffee Shop setting | Removes the Service/order-taking phase. |
| Leisurely Eating | - | Eating duration +300%, with correspondingly more time to create mess; expected groups -15%. |
| Personalised Waiting | - | A group can change its order once per course before any part is delivered; change resets patience. |
| Picky Eaters | - | May leave food on dirty plates; leftovers require disposal before washing and arenot fully automatable. |
| Photographic Memory | - | Orders are hidden unless a player is near the table. |
| Relaxed Atmosphere | - | Customers generate more mess. |
| Sedate Atmosphere | - | Players move 50% slower near customers in the same room. |
| Simplicity | - | Each research/copy/discount desk can affect only one cabinet per day. |
| Splash Zone | - | Customer/appliance messes and sink wet spots use a wider area. |
| Tipping Culture | - | Payment depends on remaining Waiting for Food patience. |
| Victorian Standards | - | Relevant table patience drains faster while customers can see a nearby player in the same room. |

### B2. Theme cards

#### Theme Thresholds Effects

Faster Thinking and Eating; 50% consumable reuse chance; Waiting for Food shortened Affordable 3 / 6 / 9 and Delivery merged.

More Service patience; slower table-patience loss near players; customers may sit Charming 3 / 6 / 9 before a table is cleared.

More queue patience; +1 coin per delivered item; active queue prevents table-patience Exclusive 3 / 6 / 9 decay.

Less customer mess; much larger delivery patience recovery; no customer-generated Formal 3 / 6 / 9 mess at level 3.

### B3. Franchise cards

#### Expected-

#### Card/family Effect groups

#### modifier

Bootstrapping Two random free starting appliances +30%

Grabber Free Grabber at run start +30%

| **Card/family** | **Effect** | **Expected-** **groups** **modifier** |
| --- | --- | --- |
| Wash Basin | Free Wash Basin at run start | +30% |
| Coffee Tables / Conveyors / Floor Protectors / Flower Pots | Named appliance becomes a frequent staple blueprint | +30% |
| Metal Table / Simple Cloth Table | Named table becomes a frequent staple blueprint | varies |
| Loyal Customer | Buying can create another blueprint | +30% |
| Second Helpings | Chance a blueprint remains purchasable again | +30% |
| Careful Accounting | Revenue +50% | +30% |
| Catalogue | One extra shop blueprint each day | +30% |
| Coupons | Blueprint prices -25% | +30% |
| Double Homework | Desk copying creates two copies | +30% |
| High Tech Suppliers | Shop and rerolls can yield upgraded blueprints more often | +30% |
| Mandatory Tips | Flat bonus per customer served | +30% |
| Preparation Time | Customers start later | +30% |
| Reincarnation | Consumed Extra Lives regenerate daily | +30% |
| Savings | Start with extra money | +30% |
| Supplier Error | Shop prices are randomized | +30% |
| Variety | Adds another selectable starting recipe to future franchise runs | special |

### B4. Difficulty cards

#### Card Effect

Focus Food burns 50% faster.

Renown Customers +30%.

Simplicity Desks limited per day.

Variety Add another dish.

Quality Processes 20% slower.

Expectation Patience -20%.

Discount Money -25%.

Expansion Group size +2.

### B5. Setting and romantic cards

| **Card** | **Setting/** **prerequisite** | **Effect** |
| --- | --- | --- |
| Community | Autumn | Group size grows on a day/overtime cadence. |
| Flower Pots | Romantic | Flower Pots become frequent shop offers. |
| Turbo | Turbo | Card every day, larger shops, cheaper blueprints, more/rushed customers. |
| Coffee Shop | Coffee Shop | Less patience, instant orders, less mess. |
| Banquet Dining | Banquet Hall | Customers order immediately. |
| Enchantment | Witch Hut | Enchant appliances instead of normal upgrade flow. |
| Christmas Treats | Elf Banquet | Buffet-oriented setting rules and instant orders. |
| Couples | Romantic | Queue patience boost and couple behavior modifiers. |
| Double Dates | Requires Couples | Couples can arrive in groups of four; queue patience boost. |
| First Dates | Requires Couples | Randomized thinking/eating plus relationship modifiers and queue patience boost. |

### B6. Food-card inventory

The process steps for every item below are in Appendix A.

**Additional recipes:** Bone-in Steaks; Thick Cut Steaks; Thin Cut Steaks; Apple Salad; Potato Salad; Mushroom Pies; Vegetable Pies; Crab Cake; Fish Fillet; Oysters; Spiny Fish; Bamboo Stir Fry; Mushroom Stir Fry; Steak Stir Fry; Iced Coffee; Latte; Tea; Affogato; Sponge Cake; Cupcake; Doughnut; Brownies; Cake Flavour - Coffee; Cake Flavour - Lemon; Spaghetti I; Spaghetti II; Spaghetti Bolognese; Cheesy Spaghetti; Lasagne; Sundaes I; Sundaes II.

**Extras:** Steak sauces/toppings; Turkey cranberry/gravy/stuffing; Dumpling Soy Sauce; Seaweed; Salad Toppings; Mushroom/Onion Pizza; Burger Toppings; Cheeseburgers; Fresh Patties; Fish Selection; Hot Dog Mustard; Breakfast Beans/Eggs/Extras; Stir Fry Soy Sauce; Sandwich Toppers/Eggs/Toast/Mayo/Cheese/Club/Giant; Sundae Toppings/Syrups/Giant.

**Starters:** Broccoli Cheese Soup, Carrot Soup, Meat Soup, Pumpkin Soup, Tomato Soup, Bread, Christmas Crackers, Mandarin Starter, Pumpkin Seed.

**Sides:** Bamboo, Broccoli, Chips, Corn on the Cob, Mashed Potato, Onion Rings, Roast Potato.

**Desserts:** Apple Pie, Cherry Pie, Pumpkin Pie, Cheese Board, Ice Cream.

## Appendix C. Complete appliance/equipment source index

This is the source-linked index captured from the live wiki crawl. "Normal or recipe-dependent" does not mean the item is available in every run; recipes, cards, progression, pools, and settings still gate availability.

| **Appliance/equipment** | **Availability class** | **Source** |
| --- | --- | --- |
| Auto Plater | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/AutoPlater) |
| Bar Table | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/BarTable) |
| Bin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Bin) |
| Blueprint Cabinet | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/BlueprintCabinet) |
| Blueprint Desk | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/BlueprintDesk) |
| Booking Desk | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/BookingDesk) |
| Breadsticks | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Breadsticks) |
| Brownie Tray | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/BrownieTray) |
| Buffet | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Buffet) |
| Cake Tin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CakeTin) |
| Candle Box | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CandleBox) |
| Cauldron | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/Cauldron) |
| Christmas Crackers | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ChristmasCrackers) |
| Clipboard Stand | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ClipboardStand) |
| Coffee Machine | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CoffeeMachine) |
| Coffee Table | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CoffeeTable) |
| Combiner | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Combiner) |
| Compactor Bin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CompactorBin) |
| Composter Bin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ComposterBin) |
| Conveyor Mixer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ConveyorMixer) |
| Conveyor | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Conveyor) |
| Cookie Tray | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CookieTray) |

| **Appliance/equipment** | **Availability class** | **Source** |
| --- | --- | --- |
| Copying Desk | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CopyingDesk) |
| Counter | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Counter) |
| Cupcake Tray | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/CupcakeTray) |
| Danger Hob | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/DangerHob) |
| Dining Table | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/DiningTable) |
| Discount Desk | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/DiscountDesk) |
| Dish Rack | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/DishRack) |
| Dish Washer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/DishWasher) |
| Display Stand | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/DisplayStand) |
| Doughnut Tray | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/DoughnutTray) |
| Dumbwaiter | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Dumbwaiter) |
| Enchanted Broom | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/EnchantedBroom) |
| Enchanted Plates | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/EnchantedPlates) |
| Enchanting Desk | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/EnchantingDesk) |
| Expanded Bin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ExpandedBin) |
| Extra Life | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Extralife) |
| Fast Mop | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/FastMop) |
| Fire Extinguisher | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/FireExtinguisher) |
| Floor Buffer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/FloorBuffer) |
| Flower Pot | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/FlowerPot) |
| Freezer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Freezer) |
| Frozen Prep Station | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/FrozenPrepStation) |
| Gas Limiter | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/GasLimiter) |
| Gas Override | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/GasOverride) |
| Ghost Scrubber | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/GhostScrubber) |
| Ghostly Clipboard | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/GhostlyClipboard) |

| **Appliance/equipment** | **Availability class** | **Source** |
| --- | --- | --- |
| Ghostly Knife | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/GhostlyKnife) |
| Ghostly Rolling Pin | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/GhostlyRollingPin) |
| Grabber - Rotating | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/GrabberRotating) |
| Grabber | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Grabber) |
| Heated Mixer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/HeatedMixer) |
| Hob | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Hob) |
| Hosting Stand | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/HostingStand) |
| Ice Cream | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/IceCream) |
| Ice Dispenser | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/IceDispenser) |
| Illusion Wall | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/IllusionWall) |
| Instant Wand | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/InstantWand) |
| Kitchen Floor Protector | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/KitchenFloorProtector) |
| Lasagne Tray | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/LasagneTray) |
| Lasting Mop | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/LastingMop) |
| Leftover Bags | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/LeftoverBags) |
| Levitation Line | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/LevitationLine) |
| Levitation Station | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/LevitationStation) |
| Magic Apple Tree | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/MagicAppleTree) |
| Magic Mirror | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/MagicMirror) |
| Magic Spring | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/MagicSpring) |
| Metal Table | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/MetalTable) |
| Microwave | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Microwave) |
| Milk Steamer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/MilkSteamer) |
| Mixer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Mixer) |
| Mixing Bowls | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Mixing-Bowls) |
| Mop | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Mop) |

| **Appliance/equipment** | **Availability class** | **Source** |
| --- | --- | --- |
| Napkins | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Napkins) |
| Oil | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Oil) |
| Ordering Terminal | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/OrderingTerminal) |
| Oven | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Oven) |
| Plates | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Plates) |
| Portioner | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Portioner) |
| Pot Stack | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/PotStack) |
| Pouch Of Holding | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/PouchOfHolding) |
| Power Sink | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/PowerSink) |
| Prep Station | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/PrepStation) |
| Preserving Station | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/PreservingStation) |
| Rapid Mixer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/RapidMixer) |
| Research Desk | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ResearchDesk) |
| Robot Buffer | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/RobotBuffer) |
| Robot Mop | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/RobotMop) |
| Rolling Pin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/RollingPin) |
| Safety Hob | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SafetyHob) |
| Scrubbing Brush | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ScrubbingBrush) |
| Serving Boards | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/ServingBoards) |
| Sharp Cutlery | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SharpCutlery) |
| Sharp Knife | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SharpKnife) |
| Sink | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Sink) |
| Smart Grabber | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SmartGrabber) |
| Soaking Sink | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SoakingSink) |
| Specials Menu | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SpecialsMenu) |
| Specials Terminal | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SpecialsTerminal) |

| **Appliance/equipment** | **Availability class** | **Source** |
| --- | --- | --- |
| Starter Bin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/StarterBin) |
| Starter Hob | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/StarterHob) |
| Starter Plates | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/StarterPlates) |
| Starter Sink | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/StarterSink) |
| Sundae Glasses | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Sundae-Glasses) |
| Supplies | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Supplies) |
| Table - Fancy Cloth | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/FancyTable) |
| Table - Sharing Cauldron | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/TableSharingCauldron) |
| Table - Simple Cloth | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/SimpleTable) |
| Table - Stone | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/StoneTable) |
| Taco Trays | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/TacoTrays) |
| Teleporter | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Teleporter) |
| Trainers | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Trainers) |
| Tray Stand | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/TrayStand) |
| Upgrade Kit | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Upgradekit) |
| Vanishing Circle | Event/limited | [source](https://wiki.plateupgame.co.uk/appliances/VanishingCircle) |
| Wash Basin | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/WashBasin) |
| Wellies | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Wellies) |
| Woks | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Woks) |
| Work Boots | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/WorkBoots) |
| Workstation | Normal or recipe-dependent | [source](https://wiki.plateupgame.co.uk/appliances/Workstation) |

## Appendix D. Telemetry schema field map

The canonical machine-readable version is plateup-telemetry.schema.json.

| **Top-level field** | **Required** | **Purpose** |
| --- | --- | --- |
| schema_version | Yes | Semantic version of this payload. |
| sequence / timestamps | Yes | Ordering, dropped-message detection, and timing. |
| session | Yes | Game/build/branch/platform/bridge/mod provenance. |
| phase | Yes | Location/subphase/day/time/weather/ready gating. |
| run | Recommended | Seed, setting, recipe, franchise, players, demand, money, cards, theme. |
| world | Yes | Rooms, grid, walls/doors/hatches, traversal, floor states. |
| players | Yes | Pose, facing, held items, equipped tools, footwear, action. |
| entities | Yes | Appliances/items/slots/providers/processes/tables/blueprints. |
| customer_groups | Yes | Group phase, patience, path, table, member/order references. |
| orders | Recommended | Course and piecemeal requirements with accepted item states. |
| shop | Preparation | Reroll cost/count, loose/stored blueprints, card choices. |
| affordances | Yes | Authoritative legal/illegal actions now. |
| events_since_previous | Yes | Causal deltas for debugging and rewards. |
| derived_metrics / warnings | Recommended | Non-authoritative summaries and source conflicts. |
