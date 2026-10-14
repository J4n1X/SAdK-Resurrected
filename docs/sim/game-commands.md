# Game system and player commands

Evidence tags: **[known]** read directly in the code (address `S 00xxxxxx` in `sadk_noav.exe`) or in the game data
(file and key); **[inferred]** one step of reasoning from what is visible; **[TODO]** open. Nothing here was
observed in the running game.

Related documents (not repeated here): `docs/NCOMM_LAYER.md` and `docs/NCOMM_GAME_PROTOCOL.md` (session, event
classes, transport), `docs/multiplayer-save.md` (tick packages and saves, desync detection),
`docs/navy-and-military.md` (attack, fight, ship routes and expeditions), `docs/subsystems.md` (overview),
`docs/types.md` (structs), `docs/lua-surface.md` (Lua API).

## 1. Purpose and scope

`nGame::System` is the client-side controller of a running match. It is responsible for:

- building and tearing down the world when a match is entered or left (`BuildWorld`, `Shutdown`);
- per-frame updates of the things that are not simulation: autosave timer, camera, music, cutscene camera
  (`Update`), and the cursor and the street-placement preview (`Render`);
- **the player command path**: turning a local input into a *command event*, and executing every command event
  that the lockstep layer delivers (`HandleGameCommand`); this is the only way a human player changes the
  simulation;
- the desync checksum of the simulation state (`ComputeChecksum`).

It is not responsible for the simulation itself (the logic root is `NLogic::System`, global `g_pGameSystem`), for
what the commands do in detail once validated (buildings, street net, military, navy, sacrifices: their own
subsystems), for transporting events between machines (NComm), or for the AI. The AI does not send command events:
it calls the same simulation functions directly from its own tick, on every machine [known for
`NVillage::Military::ToggleSoldierKind`, `NVillage::Production::SetEnabled`, `NMilitary::Attack::StartAttack`,
`Logic_PlaceFlag`: S 005600d0, S 00565ff0, S 00576500, S 00538cd0 list AI callers; inferred as the general rule].

## 2. Data model

### 2.1 `nGame::System` (size 0x648) [inferred, vftables known]

Three interface faces: primary `IRenderable` at +0 (vftable S 008350e8: slot 1 `Render` S 007835d0), `IUpdateable`
at +4 (vftable S 008350dc: slot 1 `Update` S 00780d20), `NComm::IEventHandler` at +8 (vftable S 008350c8: slot 1
`HandleGameCommand` S 007845a0, slot 2 "game running" forwarder S 00782a50, slot 3 `ComputeChecksum` S 00784080).

| Offset | Type | Meaning |
|---|---|---|
| +0x0c | bool | world built / running; set at the end of `BuildWorld`, cleared by `Shutdown` |
| +0x0d | bool | scene hook active (`Render` calls the scene when set) |
| +0x10 | `nGame::Cursor` (0x2c0) | map cursor and picking; updated by `Render` (`Cursor::Update`), its own vftable slot 1 (S 008352b8), which `Update` calls, is the shared empty function S 005657b0 [known] |
| +0x2d0 | `nGame::Camera` (0xe0) | in-game camera |
| +0x3b0 | setup descriptor copy | the match setup the world was loaded from |
| +0x5f8 | `nGame::Autosave` (0x10) | autosave timer (net mode 0 only, S 0078b040) |
| +0x60c | `nGame::Script` (vftable S 007eab20 only) | `Update` calls its slot 1 once the logic tick counter is not -1; the slot is the shared empty function S 005657b0 [known] |
| +0x610 | `nGame::Sound` | vftable and an enabled byte at +4 (set by `BuildWorld`, cleared by `Shutdown`); not touched by `Update` [known] |
| +0x61c | music state | |
| +0x630 | `CutsceneCamera*` | |
| +0x634 | bool | AI-enabled flag saved while a cinematic runs |
| +0x635 | bool | in cinematic |
| +0x638 | `std::list<StreetBuildMode*>` (head +0x63c, size +0x640) | the local player's street placement modes |

None of this is simulation state; none of it is saved or part of the checksum.

### 2.2 The command event

Every command is an `NComm` event object. Common header [known, S 00780e10 and every other sender]:

| Offset | Type | Field | Value |
|---|---|---|---|
| +0x00 | ptr | vftable | selects the event class (see below) |
| +0x04 | u32 | type id | the command id `0x20002`..`0x2002B` |
| +0x08 | u32 | sender net id | the transport's local net id; `0xEFFFFFEE` when there is no transport (S 004089a0) |
| +0x0c | i32 | sender slot | the session slot of the local player, found by its GUID (S 00408330) |
| +0x10.. | | payload | by class |

Executors translate the sender slot into a **player index** with `NComm_Event_GetSenderPlayerIndex` S 00412490
(session lookup `GetSlotPlayerIndex`; -1 without a manager) and take the player from the player table
(`PlayerTable::GetEntry`, entries of 0xf0 bytes, S 005bdd50). There is no check that the index is valid [known].

Event classes used by commands, with their wire tag (the tag table is in `docs/NCOMM_LAYER.md`):

| Class | Tag | Payload |
|---|---|---|
| `EventBase` | `0x00000101` | none |
| `Event1Integer` | `0x11111010` | +0x10 i32 |
| `Event2Integer` | `0x11110202` | +0x10 i32, +0x14 i32 |
| `Event3Integer` | `0x11113030` | +0x10, +0x14, +0x18 i32 |
| `EventInt64` | `0x22220101` | +0x10 u64 (an `NLogic::Unique` id: low dword +0x10, high dword +0x14) |
| `EventInt64_1Integer` | `0x22222020` | +0x10 u64, +0x18 i32 |
| `EventData` | `0x33331010` | +0x10 u32 link id (0), +0x14 pointer to bytes, +0x18 u32 byte count |

An integer field also carries floats as raw bits (commands `0x2000D`, `0x20011`, `0x20013`..`0x20015`, `0x2001F`).
On the wire an event is its u32 class tag followed by the class's own serialisation [known, the `Serialize` of each
class: S 004085a0 base, S 0041f780, S 0041f860, S 0041fa50, S 0041fb30, S 0041feb0; `Event1Integer::Serialize` is
slot 3 of its vftable S 007d4294 = S 004085e0, a body shared with `NetGUID::Serialize` that writes the four dwords
at +0x04..+0x10]. All fields are written as raw little-endian memory of the given width:

| Order | Field | Width |
|---|---|---|
| 1 | class tag | 4 |
| 2 | type id (+0x04) | 4 |
| 3 | sender net id (+0x08) | 4 |
| 4 | sender slot (+0x0c) | 4 |
| 5 | payload: each i32 as 4 bytes in struct order; the u64 as 8 bytes (low dword first) before any i32 | 4 / 8 |

`EventData` differs from its struct order: after the header it writes the link id (4), the byte count (4), then the
bytes themselves. The reader allocates the byte count unchecked (S 0041fd80) [known].

### 2.3 Objects named by commands

- Buildings, flags, streets and ship routes are named by their 64-bit `NLogic::Unique` id, never by pointer or
  position. Lookups: `NVillage::System::FindBuildingByUnique`, `NNet::System::FindFlagByIdAnyPlayer`,
  `NNet::System::FindStreetById`, `ai::navy::ShipRouteList::FindByUnique` [known]. An id whose high dword is
  negative is "no object"; senders test `(int)hi > -2 && hi < 0x80000000` before sending [known, S 007810a0].
- Map cells are two i32 (x, y).
- Building types, goods and sacrifices are their numeric property ids.

### 2.4 Local selection (`ai::game::Selection`, 0xe0 bytes, `g_pGameSystem->selection`) [known, Ghidra struct; `operator new(0xe0)` in `NLogic::System::ctor` S 00528360]

Not simulation state, but the source of most command targets. The six targets are embedded `NLogic::Reference*`
members of 0x20 bytes each; the 64-bit id of a reference is at +0x10 (low) and +0x14 (high) of the member
[known] S 00535630.

| Offset | Field |
|---|---|
| +0x04 | `kind`: 0 None, 1 Building, 2 Flag, 3 Settler, 4 Street, 5 Ship, 6 ShipRoute |
| +0x08 | `settler` (`ReferenceSettler`); its id at +0x18 / +0x1c |
| +0x28 | `building` (`ReferenceBuilding`); its id at +0x38 / +0x3c |
| +0x48 | `flag` (`ReferenceFlag`); its id at +0x58 / +0x5c |
| +0x68 | `street` (`ReferenceStreet`); its id at +0x78 / +0x7c |
| +0x88 | `ship` (`ReferenceShip`) |
| +0xa8 | `shipRoute` (`ReferenceShipRoute`); its id at +0xb8 / +0xbc |

### 2.5 Per-player state changed by settings commands

In the player-table entry (stride 0xf0): +0x00 player index, +0x0c `NPlayer::GoodPriorities*`, +0x10
`NPlayer::GoodArrangement*`, +0x44 tribe id [inferred: it is the tribe argument of the transport-priority lookup,
S 005c2bf0], +0x4c `NPlayer::Military*`, +0x50 active flag [known offsets].

`NPlayer::Military` (settings, not the building component) [known, S 005c0930, S 005c09d0]:

| Offset | Type | Meaning | Default |
|---|---|---|---|
| +0x08 | f32 | allocation factor, far (tier 0) | 0.1 |
| +0x0c | f32 | allocation factor, medium (tier 1) | 0.3 |
| +0x10 | f32 | allocation factor, near (tier 2) | 1.0 |
| +0x14..+0x1b | 8 × bool | "ignore distance" flags, indexed by the **other** player's index | all false |
| +0x1c | f32 | defense factor (the fraction of soldiers that defend, see `docs/navy-and-military.md` §4) | 0.5 |

The three defaults are constants in code, not data (S 00553f40) [known].

Reader of the flag bytes: `GameQueryHelper::MinDistanceToEnemyMilitaryBuilding(pos, player, filterDiplomacy,
includeHarbors)` S 005337e0. With `filterDiplomacy` set, an enemy building whose owner index `i` has
`player.Military+0x14+i` non-zero is left out of the minimum; the same filter argument is passed on to the harbour
search `HarborList::FindNearestWithEnemyRoute` S 005b5e00 [known for the building loop; the harbour search was not
read]. So a set flag makes the player's own buildings ignore the distance to that opponent. What the resulting
distance drives (proximity zones, garrison size from the three allocation factors) is in `docs/sim/military.md`
§3.1. No command of this build's UI sets a flag (§3.4 `0x20017`).

`NPlayer::GoodPriorities`: +0x08 initialized flag, +0x0c vector of 8-byte entries `{i32 goodId, i32 rank}`
[known, S 005c2700]. Default list: every good of the player's tribe good table whose property field +0x14 is not 1,
in table order, with rank = the good's transport priority for the tribe (S 005c2bf0) [known].

`NPlayer::GoodArrangement`: a vector of groups (`GoodArrangementGroup`, +0x1c good group id, entries of 0x14 bytes:
+0x04 f32 weight, +0x0c building type id). A good maps to a group by its property field +0x78 (S 005c10f0). The
default weight of an entry is the building type's property field +0xe4, never below 0.001 (S 005c0d40, S 005c2df0)
[known]. How the weights choose the receiver of a good is the transport subsystem's matter
(`docs/sim/streets-transport.md`).

All three settings objects are part of the desync checksum: `ai::player::Player::StoreChecksum` S 005be6e0 writes,
per player, index, colour, tribe id, then the `Store` of `GoodPriorities`, `GoodArrangement` and `Military`, then
the stock (active players only), team, the 8 spotted / reached byte pairs and the state field [known]. A settings
command that is applied differently on two machines is therefore detected at the next checksum.

### 2.6 The per-player street planner

`NLogic::System` holds 8 `ai::logic::StreetPlanner` objects, one per player index (`streetPlanners[8]`) [known,
S 00527070 loops 8]. A planner (0x10 bytes): +0 active, +4 `NLogic::AStarStreet*` `search`, +8 state, +0xc
`constructor`, the street constructor it drives, held through the interface `NNet::IStreetConstructorStreet` (ten
virtual slots: `Begin`, `Cancel`, `IsActive`, `AddPoints`, `IsValid`, `CanComplete`, `GetPath`, `GetOwner`,
`GetStreetType`, `IsPointsOnly`) [known] S 00663790. The interface has two implementations:
`NNet::StreetConstructorStreet` (vftable S 007f87b8) builds a real street and is the one of the eight planners
here, of the computer player and of the navy; `NNet::StreetConstructorPoints` (S 007f87e4) only records points
and is the one of the two planners of the street build mode [known]. A `StreetConstructorStreet` owns the
id of a real, unfinished street in the street net [known, S 00668830].

Planner state (+8) [known from the writers S 006636e0, S 00663a00, S 00663ba0, S 00663bf0, S 00663740]:

| Value | Meaning |
|---|---|
| 1 | last extension found no route |
| 2 | part of the path was committed (a click on a cell already on the path) |
| 3 | extended by a found route |
| 4 | path taken (handed to the street net as a finished street) |
| 5 | construction started at a flag |
| 6 | construction cancelled |

Two queries of the construction object are used by the command handlers: slot 2 "has a street under construction"
(called *active* below) and slot 5 "can be completed" (called *ready*: the street still exists, its start cell
holds a flag, its end cell holds a flag or allows one, and start and end differ, S 00668770) [known: the call
sites use slot 2 (S 00663780) and slot 5 (S 00663770), and the vftable of `NNet::StreetConstructorStreet`
S 007f87b8 holds 0 Begin S 00668830, 1 Cancel S 00668880, 2 IsActive S 00526eb0 (the street id at +0x10 / +0x14 is
a valid id), 3 AddPoints S 006688d0, 4 IsValid S 00668750, 5 CanComplete S 00668770, 6 GetPath S 00668b00,
7 GetOwner S 006687a0, 8 GetStreetType S 006687c0; slot names from the typed struct
`StreetConstructorPoints_vftable`].

## 3. Rules and algorithms

### 3.1 From input to command event

1. A UI element decides locally whether the action is offered (action buttons: `ActionButton::RefreshAvailability`
   S 00623da0 with a failure code per action, tabulated in §5.1) and, on the click, builds the event with the
   local net id and the local slot (§5.1 lists every source).
2. The event goes to `NComm_Manager::QueueGameCommand(event, force=false)` S 00408b10 [known]:
   - if `IsGameHanging()` (S 00408860) the command is **dropped** and `false` is returned. Hanging means: the
     shutdown latch is set, or a reconnect is in progress, or the session is in state 3 (waiting for the start), or
     it is in state 4 (in match) and the last logic tick ran more than 2.0 s ago (or never);
   - in net mode 0 (offline) the event is **executed at once**, inside the UI call, through
     `DispatchEventLocal` S 0040fd50 (seen for `SendCreateFlag` S 00780e10: `QueueGameCommand` →
     `DispatchEventLocal` → `HandleGameCommand` → `HandleCreateFlag`, all in the same tick and before the send
     returned [live, 2026-10-14]);
   - otherwise it is serialised and appended to the outgoing tick package of the local machine (`manager+0x54`).
   The two events the manager queues itself (`0x2002B`, and the session event `0x3000D`) are appended to the
   outgoing package directly and do not pass the hanging test [known, S 0040e560, S 00410f70, S 004109b0; the
   three places that build `0x2002B` are listed in §3.4].
3. Nothing is predicted locally. The sender's own simulation changes only when the command comes back through the
   tick stream, like everyone else's.

### 3.2 When a command is executed

Constants and counters [known unless tagged]:

- Logic tick interval: 0.1 s (`GameConfig+4`, constructor default S 00555780; the Lua setter `cfg_setGameSpeed`
  S 0054c380 is not called by the shipped property scripts).
- A **net tick** is `L = netTickLength × speedUp` logic ticks (`manager+0x34 = +0x38 × +0x3c`, S 0040e560).
  `netTickLength` starts at 1 offline and 4 in a network match (S 0040a9a0, which sets `L` to the same value
  without multiplying by `speedUp`) and is changed during the match by the host through
  `NE_InGame_ChangeNetTickLength` `0x3000D` (see below). `speedUp` is the game speed 1..3 (§3.4 `0x20023`); it is 1
  after the manager's constructor and after every session reset (S 0040a530, S 0040a810) [known].
- `subTick` (`manager+0x40`) counts logic ticks inside the net tick; `T` (`manager+0x2c`) is the net tick number;
  `startTick` (`manager+0x30`) is the net tick at which the current run of the lockstep began. All three are -1
  after a session reset (S 0040a810) [known].
- Match start [known]: the session event `NE_StartGame` `0x30005` (S 0040e560) clears the outgoing package and
  restarts it with a header for net tick 0 (`SendEventUserChecksum(0)`; a checksum event is added under the
  conditions of step 4 below), copies the game information, stores the number of connected human players in
  `manager+0x28` (the number of checksums expected per net tick, §8) and calls the sink's "game running" slot
  (S 00782a50). That slot runs `NComm_Manager::BeginGameRunning` S 0040b270, which requires session state 3 and
  no shutdown latch and then sets `T = 0`, `startTick = 0`, `subTick = 0`, the last-tick time and number
  (`manager+0x44`, `+0x48`) to 0, the in-sync flag (`manager+0x4c`) to false, the session state to 4, stores
  the number of connected human players in `manager+0x28` again, clears the checksum log, stamps the adaptation
  timer (`manager+0x24`) with the current time and calls two transport slots: +0x80 (`TinCatNetwork`: S 00419940,
  empties every user's ping sample list) and +0x90 (S 00419b50, empties the traffic statistics list). Because
  the last-tick time is 0, the session counts as hanging (§3.1) until the first logic tick has run.
- Net tick length adaptation (`NComm_Manager::Process_MainLoop` S 00410f70, per frame, host only, session state 4,
  no reconnect in progress) [known]: every `manager+0x370` seconds (measured from the adaptation timer
  `manager+0x24`) the host looks at the transport. With fewer
  than 2 entries in the transport's user list (slot +0x44; `TinCatNetwork+0x1c`, the list's size) it queues
  `0x3000D` with value 1 (every interval, unconditionally). Otherwise, with a measured
  latency `lat` (0 = no measurement, nothing happens): `f = lat × 0.5`; if the net mode is below 3 or the
  transport's quality level is below 5, `f` is multiplied by 1.7 (level 0 or 1), 1.4 (level 2) or 1.1 (level 3);
  `value = clamp(ceil(manager+0x388 × f × 0.01), 1, 10)`; when `value` differs from the current `netTickLength`,
  `0x3000D(value)` is queued. The event travels in the tick package like a command, so every machine applies
  `netTickLength = value`, `L = speedUp × value` at the same boundary (S 0040e560). `manager+0x360` is the
  network configuration block (`NComm_NetworkConfig`, defaults S 0040a390, loaded from `network.ini` by
  S 0041ede0 when the network is started): `manager+0x370` is block +0x10 = `[Ping] pingFrequencyGame` in
  seconds (code default 3.0, shipped file 2.5); `manager+0x388` is block +0x28, a float with default 1.0 that no
  ini key sets; `manager+0x384` is block +0x24, an int with default 4 that no ini key sets (the net tick length
  after a reconnect, see below) [known]. In `TinCatNetwork` (vftable S 007d58f4) `lat` is slot +0x8c
  S 00419a50, the largest value any user record reports as its maximum sample, capped at 1000, and the quality
  level is slot +0x60 S 004198e0, the smallest value of a per-user field (list node +0x3c), starting from 3:
  it is never above 3, so with this transport one of the three multipliers always applies [known]. The samples
  are milliseconds of a full round trip (`GetTickCount()` at the reply minus the value the request carried;
  `docs/sim/logic-core.md` §10 Q2) [known]. [TODO] not established: what sets the per-user level (the writers
  of the level field); the offline transport's slots were not read.

`NLogic::System::Update` S 00527070 calls `NComm_Manager::AdvanceNetTick(logicTick)` S 00411990 as the **first step
of every logic tick**, before any subsystem is updated. There:

0. Nothing at all happens unless the session is in state 4 and `CanAdvanceTick()` holds (the caller has already
   tested the latter).
1. `subTick += 1`; the logic tick number and the current time are stored (`manager+0x48`, `+0x44`; the time feeds
   the hanging test of §3.1). If `subTick < L`, nothing else happens.
2. Otherwise this logic tick is a net-tick boundary: `subTick = 0`, then, in this order:
   0. during the first net ticks (`T - startTick < 11`) the adaptation timer `manager+0x24` is set to the current
      time and a transport slot (+0x80) is called (S 00408f30); so the net tick length is not adapted during
      these net ticks as long as a net tick is shorter than `pingFrequencyGame` [inferred]. What the transport
      slot does (clearing its ping samples) is specified in `docs/sim/logic-core.md` §3.2;
   1. the package for net tick `T-2` in the received list (`manager+0xb8`), if present, is executed: every event
      in it, in stored order, through `ExecuteEventPackage` S 00410530. If the flag `manager+0x4d` is set
      afterwards, the function returns here: no exchange, `T` is not advanced. The only instructions in the
      program that store to an object's byte +0x4d inside the NComm code are the two that clear it (constructor
      S 0040a5b6, session reset S 0040a864) [known, instruction search], so the early return never happens in
      this build [inferred] and a reimplementation can leave it out;
   2. on the host: the collected package for `T-1` (`manager+0xac`), if present, is broadcast (TinCat message
      1002) and merged into the host's own received list;
   3. the local outgoing package (stamped `T`) is sent to the host (client, message 1001) or merged into the host's
      collected list for `T` (host and offline);
      steps 2 and 3 are skipped while the reconnect state (`manager+0x00`) is 1; steps 4 and 5 still run;
   4. `T += 1`; the outgoing package is cleared and restarted with a header for the new `T`, and its first event
      is the checksum event `0x30009` for this tick (S 004089c0). The event is added whenever an event sink is
      registered, a transport exists with a local net id, the session state is 2, 3 or 4 and the local player has
      a slot; the checksum value is 0 in net mode 0, otherwise `ComputeChecksum()` at this moment, i.e. after the
      commands of this boundary ran and before the subsystems of this logic tick update [known];
   5. if `T-5 > 0`, packages and checksums older than `T-5` are dropped; checksums are compared (§8).

So a command queued while the net tick number is `T` is collected at the boundary `T`, broadcast at boundary
`T+1` and **executed at boundary `T+2`**, at the very start of that logic tick, on every machine. The delay is
between `2L` and `3L` logic ticks, i.e. 0.8 to 1.2 s at the initial network setting (`L` = 4, speed 1) [inferred
from the steps above]. `L` adapts: in a two-player match over a LAN it read 1 or 2, and commands ran 240-310 ms
(3 logic ticks) after queueing at `L` = 1 and 440-540 ms (5-6 logic ticks) at `L` = 2 [live, 2026-10-14]
([logic-core.md](logic-core.md) §3.2). Offline the pipeline still runs (with
empty packages) but commands bypass it (§3.1).

The simulation may not start a logic tick unless `NComm_Manager::CanAdvanceTick` S 004088b0 allows: inside a net
tick always; at a boundary the host (net modes 0, 2, 4, and not while the reconnect state is 1) needs the collected
package for `T-1` to contain a part from each of the 6 session slots whose net id is not `0xEFFFFFEE` (only once
`T ≥ startTick + 1`), and everyone needs the received package for `T-2` to exist with at least one event block
(only once `T ≥ startTick + 2`). It is false outright unless the session state is 4 and the reconnect state is 0
or 1 [known]. A machine that cannot advance
stops simulating and after 2 s counts as hanging.

**Reconnect and the command stream.** The reconnect state is `manager+0x00` (0 = none). [known unless tagged]:

- While it is not 0, `IsGameHanging` is true: every command of the local player is dropped at the queue (§3.1).
- State 1 (restart as client armed): logic ticks may still run (`CanAdvanceTick` accepts states 0 and 1, and
  skips the host's "all slots delivered" test), but boundaries exchange no packages (steps 2 and 3 above). Every
  boundary still needs the received package for `T-2`, and none arrives, so the simulation stops after the
  packages already received are used up: at most two more boundaries [inferred].
- States 2 and above: no logic tick.
- When the transport is back, both the client that rejoins (`ReconnectAndRejoin` S 004093a0, state becomes 3) and
  the machine that takes over as host (`Reconnector_RestartAsServer_DoAction` S 0040b700, state becomes 2) do the
  same to the stream: the outgoing package is cleared and restarted for the current `T` (with a checksum event);
  **both package lists are cleared** and an empty collected package for `T-1` is created; `startTick = T`;
  `subTick = 0`; `netTickLength = manager+0x384` (4) and `L = speedUp × manager+0x384`; the last-tick time is 0;
  the in-sync flag is false; the checksum log, the ping samples and the adaptation timer are reset. The new host
  also sets the expected checksum count (`manager+0x28`) to 1.
- Consequences [inferred]: commands that were queued, collected or received but not yet executed when the lists
  are cleared are lost on every machine; no command is replayed. Since `startTick = T`, the gates of
  `CanAdvanceTick` (`T ≥ startTick + 1`, `+ 2`) open again as at a match start, so the first two boundaries after
  a reconnect run without packages.
- How the reconnect state returns to 0 and what the host does with slots that do not come back belongs to the
  session layer (`docs/NCOMM_LAYER.md`); [TODO] not established here: whether every machine clears its lists at
  the same `T` (static read of the reconnect state machine in S 00410f70).

Execution of one event (S 00410530): `NComm_Manager::HandleEvent` S 0040e560 first; it consumes the session events
(`0x30001`..`0x30012`) and returns false for everything else, which then goes to the registered sink,
`nGame::System::HandleGameCommand`. An event that cannot be deserialised ends the execution of the rest of the
package silently; an event nobody consumes while no sink is registered is logged
(`Error Executing Event - Class: … - Type: …`) and also ends the package [known].

`HandleGameCommand` S 007845a0: sets the default FPU control word (`Fpu_SetDefaultControlWord` S 0057b9b0), reads
the event's type id and dispatches by a switch. Ids `0x2000C`, `0x2001D`, `0x20001` and anything outside
`0x20002`..`0x2002B` are ignored [known].

### 3.3 Order of commands within a tick

All commands of one net tick run in the order in which they are stored in the host's package: the host's own
package for that tick is appended when the host passes the boundary, each client's when it arrives at the host.
Inside one player's package the order is the order of queueing. Every machine executes the host's merged package,
so the order is the same everywhere but is decided by arrival order at the host [inferred from S 00411990 and
the two functions below].

`TickPackageList::AddReceived(sender, len, data)` S 00412ae0 [known]: a block without the 8-byte header (u16
`0x5332`, u32 net tick, u16 `0x4b38`) is rejected and dropped silently; otherwise the package for the header's
net tick is found or created and `TickPackage::AppendEvents` S 00412e80 appends the block's bytes after the
header **at the end** of what the package already holds, counts one more event block and records the sender.
There is no sorting by slot or net id. A block whose header names another net tick than the package is refused.
A client's block is filed under the net tick in its own header, not under the host's current `T`; a block that
arrives after the host has broadcast that net tick is appended to a package that is never sent [inferred].

### 3.4 The commands

For every command: **no reply and no error**. A command whose target does not exist or whose check fails is
ignored silently [known for each executor].

"Owner check: none" below means the executor does not compare the sender with the owner of the target; the
restriction to one's own objects is made only by the sender's UI. This matters for a reimplementation that wants
to stay compatible, and for one that wants to be safe against a modified peer.

Names in the first column are the game's own event names from its debug table (S 00421bd0) [known].

#### Buildings

**`0x20002` GE_Building_Create** — `Event3Integer`: building type id, cell x, cell y. Sender `SendPlaceBuilding`
S 007818b0 (build menu `InfoBoxCreateBuilding`), unconditional. Executor `HandlePlaceBuilding` S 00781980:
player = sender; if `GameQuery::CanPlaceBuildingTypeAt(type, cell, player, ignoreCentre=false, altPlayer=none,
allowBorder=false)` S 005301c0 then `NVillage::System::PlaceBuilding(player, type, cell)` S 0055a090. The check
resolves the type's size class (building property +0x3c) and runs the full placement test of the building
subsystem. Placing creates the construction site, registers it, attaches its entrance flag and marks the footprint
on the map [known]. Not checked on execution: whether the type is unlocked for the player or belongs to its
tribe. Neither the executor, `CanPlaceBuildingTypeAt`, `CanPlaceBuildingAt` S 0052fbe0 nor `PlaceBuilding` calls
the lock test `ai::player::Player::IsLocked` S 005be970 (category 0 = building types); that test is only in
`Village_CheckBuildingPlacement` S 005576e0, whose single caller chain ends in the debug tool [known from the
callee lists]. The build menu is therefore the only place that hides locked or foreign types [inferred].

**`0x20003` GE_Building_Destroy** — `EventInt64`: building id. Sender `SendDestroyBuilding` S 007810a0 (action 4);
the UI sends it only for a building of the local player whose `GetDestroyBlockReason` S 0055cd40 is 0 (1 =
headquarters-type, i.e. property flags depot, casern and territoryBuilding all set; 3 = construction time below 1
and not headquarters-type, i.e. not player-buildable; 2 = in a fight with the destroy countdown running). Executor
`HandleDestroyBuilding` S 00781150: building found and its military component's `destroyCountdown < 0` →
`NVillage::System::DestroyBuilding` S 0055a7a0: if the building is the target of a fight (fight reference valid)
only the destroy countdown is started: military component +0x90 = the military property
`actionsInFightDelayTime` (S 0055fc10) [known]; otherwise the
building is removed at once with `RemoveBuilding(spill = true)`. Owner check: none; the headquarters and
"not buildable" rules are not re-checked [known].
The countdown runs in `NVillage::Military::Update` S 005609b0, once per logic tick [known]: a value above 0 is
decremented by 1 unless the simulation flag `GameSystem+0xec` is set (the cinematic start S 00782b60 sets it,
`nGame::System::EndCinematic` S 00782bb0 clears it); a value of exactly 0 calls
`NotifyDestruction` S 00560890 (messages `!Military Building Destruction executed` to the owner and, with a
valid fight reference, `!Attack Target has been destructed` to the attacker); -1 is idle. With the shipped value
300 the messages come on the 301st update after the command, i.e. about 30 s later at speed 1. The removal of
the building itself is not in these two functions; it is specified in `docs/sim/military.md` §3.8. The whole
block is skipped for a building whose type has the three headquarters-type flags set, so a countdown started on
such a building (possible only with a command the UI never sends) never runs [inferred]. Because the executor
requires `destroyCountdown < 0`, a second destroy command during the countdown is ignored [known].

**`0x20029` GE_Construction_Pause** — `EventInt64`: building id. Sender: action 6. Executor
`HandleAbortConstruction` S 00782fc0: takes the building's *effective construction* (the upgrade's construction
when an upgrade is active, else the building's own, S 0055bf90); if one of its float fields +0x70 or +0x74 is above 0
(the same test that makes `Upgrade::GetBlockReason` report "still under construction"; both hold **remaining**
work: `Construction::AdvanceWork` S 0055eff0 subtracts from +0x74 while it is above 0 (a negative result is set
to 0), then from +0x70, and reports the build done in the call whose subtraction makes +0x70 negative (it is
then set to 0; a result of exactly 0 is not reported, and no later call reports it) [known]; the two phases
are specified in `docs/sim/village-buildings.md`
§2.4 and §3.4) and its paused flag +0x78 is clear →
`NVillage::Construction::AbortAndReturnGoods` S 0055ed30: all open material requests are cancelled, the builder is
released, every delivered good is put out as a package at the building's flag and taken from the site stock (per
good, until the flag's stack for that good is full; the rest stays in the site stock), flag +0x78 = 1. Owner
check: none.

**`0x2002A` GE_Construction_Continue** — `EventInt64`: building id. Sender: action 7. Executor S 00782840: if the
effective construction's flag +0x78 is set: `Construction::RequestMaterials` S 0055eb50 and flag +0x78 = 0
(S 0055eeb0). Owner check: none.

**`0x2000F` GE_Military_Upgrade** — `EventInt64`: building id. Sender `SendStartUpgrade` S 00781470 (action 5).
Executor `HandleStartUpgrade` S 00781540: `NVillage::Upgrade::GetBlockReason` S 005670c0 must be 0, then
`Upgrade::Start` S 005671a0. Block reasons, tested in this order:
- 4: the building's field +0x34 differs from its owner's tribe (+0x44) [inferred meaning: a building of a foreign
  tribe cannot be upgraded];
- 3: the building is still under construction, or its construction has a valid reference at +0x44, or an upgrade
  is already active;
- 1: the type has no upgrade target (building property +0xe8 = -1; data key `bp_setUpgrade`);
- 2: the target type has another size class than the current one and `CanPlaceBuildingTypeAt(target, cell, owner,
  ignoreCentre=true)` fails.
`Start` sets the upgrade active, stores the target type, creates a construction and a bulldozing helper, swaps the
blocking footprint to the target's and raises the "upgrade started" callback. Owner check: none.

**`0x20010` GE_Military_CancelUpgrade** — `EventInt64`: building id. Sender: action 30. Executor S 007815d0: if an
upgrade is active → `Upgrade::Cancel` S 00567320: aborts the construction if not already paused, hands the
collected goods back at the building's flag, destroys the helpers, raises "upgrade cancelled". Owner check: none.

**`0x2000A` GE_Production_Enable** — `EventInt64`: building id. Sender `SendToggleProduction` S 00780eb0 (actions
24..27: production pause/resume, catapult pause/resume). Executor S 00780f80: **toggles**
`Production::SetEnabled(!IsEnabled())` S 00565ff0. Disabling cancels all input requests and moves the input stock
to the output store, and nothing else; enabling reclaims surplus inputs (`ReclaimSurplusInputs`) and requests all
inputs (`RequestAllInputs`) [known]. Because it
is a toggle, two commands issued before the first comes back cancel each other. Owner check: none.

**`0x2001E` GE_Depot_ToggleFlags_UID** — `EventInt64_1Integer`: building id, good id. Sender `SendToggleGoodFlag`
S 00781720 (depot info box; casern info box). Executor S 007817f0: toggles whether the building accepts the good:
if a flag entry for the good exists and is enabled → disable, else create the entry if needed and enable
(`Building_SetGoodFlagEnabled` S 00557630). Disabling notifies the building's ordering component so pending orders
are re-synchronised. Owner check: none.

**`0x20012` GE_Military_ToggleSoldierType** — `EventInt64`: building id. Sender: actions 13 and 14 (set to
swordsmen / bowmen). Executor S 00781690: `NVillage::Military::CanToggleSoldierKind` S 00560390 (no fight
reference, all soldiers present are of the current kind, no soldier is in a fight) → `ToggleSoldierKind` S 005600d0:
kind = (kind + 1) mod 2 (0 sword, 1 bow), all of the building's orders are cancelled and the upgrade and replace
order slots cleared. Both actions send the same toggle [known]. Owner check: none.

**`0x20018` GE_Casern_ToggleTraining** — `EventInt64_1Integer`: building id, slot index (0 sword, 1 bow; actions
15/16 and 17/18). Executor S 007823f0: toggles the enabled flag of that training slot of the building's training
component (+0x124) and re-synchronises the input requests (`VillageSoldierTraining_UpdateInputRequests`
S 00566ba0). No bounds check on the index, no check that the building has the component [known]. Owner check: none.

**`0x20019` GE_Casern_ToggleUpgrading** — `EventInt64`: building id (actions 19/20). Executor S 00782480: toggles
the component's upgrading flag (+0x14) and re-synchronises as above. Owner check: none.

#### Flags and streets

**`0x20004` GE_Flag_Create** — `Event2Integer`: cell x, y. Sender `SendCreateFlag` S 00780e10 (action 29, with the
hovered cell). Executor `HandleCreateFlag` S 00783690: `GameQuery::CanPlaceFlagAt(cell, player, allowBorder=false)`
S 0052f8a0 — the cell is free land owned by the player (`IsOwnedCellFree`), no object of object layer 0 within
hex distance 1, and no cell of the ring of six neighbours has the grid-state bit `0x2000` (harbour bit [inferred
from the plate]) — then `Logic_PlaceFlag(player, cell)` S 00538cd0
(`NNet::System::PlaceFlag`, which may split a street passing the cell; a harbour at the cell is linked to the
flag). A log line is written. Then, if the player's planner is active and ready,
`NLogic::System::BuildPlannedStreet(player)` S 005289b0 finishes the street under construction (this is how a
street is ended on a free cell: flag first, street after, in one command). Only in that case (a street was
finished), and if the sender is the local player, the street placement mode is closed [known]. On the sender's
side action 29 additionally cancels a running placement mode right after queueing (S 00623730).

**`0x20005` GE_Flag_Destroy** — `EventInt64`: flag id. Sender `SendRemoveFlag` S 00781320 (action 8, only when
the block reason is 0). Executor S 007813d0: flag found among all players' flags and
`NNet::Flag::GetRemoveBlockReason` S 00669f70 = 0 → `NNet::System::RemoveFlag` S 00665c10 (deletes every street
attached to the flag, the flag, and an attached building). Block reasons, in order: with an attached building: 3
the building is in a fight, 2 it is headquarters-type, 4 it is not player-buildable; then 1 the flag has a harbour
link and its cell lies in its owner's territory; else 0. Owner check: none.

**`0x20006` GE_Street_StartConstruction** — `Event3Integer`: cell x, y, water flag (0/1). Sender
`SendBuildStreetCommand` S 00781d40 (first click of the street placement mode; the cell is the mode's start
waypoint, the flag is "street type = 2"). Executor `HandleBuildStreet` S 00783e10, on the sender's planner:
1. if active: cancel the street under construction (it is removed from the net), state 6;
2. `StreetPlanner::BuildStreet(player, cell, kind)` S 006636e0 with kind = 2 when the flag is set, else 0: the
   player must have a flag on the cell; for kind 2 `NNet::Flag::GetWaterStreetBlockReason` S 0066a020 must be 0
   (1 = the flag already has a harbour/navy link, reference at flag +0x168; 2 = the flag's cell does not have
   grid-state bit `0x8`, the shore bit [inferred name]) [known];
   then a path-less street is created at the flag (`NNet::System::CreateStreetAtFlag(player, cell, kind)`,
   S 00668830) and, only if that returned a street, the state becomes 5; otherwise the state keeps its previous
   value (6 after step 1, or whatever an earlier command left);
3. if the state is not 5 (it failed) and the sender is the local player, the placement mode is closed.

**`0x20008` GE_Street_BuildToPosition** — `Event2Integer`: cell x, y. Sender `SendExtendStreetCommand` S 00781e80
(every accepted click of the placement mode). Executor `HandleExtendStreet` S 00783f60, on the sender's planner:
1. not active → nothing (only the local preview is refreshed);
2. already ready → `BuildPlannedStreet`;
3. else `StreetPlanner::ExtendTo(cell)` S 00663bf0:
   - the cell is already on the path → `CommitPathTo` S 00663a00: the path is cut back to that cell, the
     construction is cancelled and restarted from the path's first cell with the same owner and type, the cut path
     is added, state 2;
   - else an A* search (`NLogic::AStarStreet`) from the path's last cell to the cell: found → the route is
     appended to the street when it is not empty, state 3; not found → state 1. The route comes from
     `NMap::AStar::BuildPath(out, randomize = false)` S 00676d10, which writes the search's start cell (the
     current end of the street) first and the clicked cell last and, without `randomize`, draws no random
     number; `StreetConstructorStreet::AddPoints` S 006688d0 skips the first point and appends every further
     cell to the street, inside one map-update batch, and returns false when the street no longer exists
     [known];
4. state 1 → for the local sender the clicked waypoint is removed from the placement mode; no build;
5. otherwise, if now ready → `BuildPlannedStreet` S 005289b0: the street type is read from the street under
   construction (street +0xe4), the path is copied out of the planner, the street under construction is
   cancelled (removed from the net; `TakePath` S 00663ba0, final state 4) and the path is handed to
   `NNet::System::BuildStreet(player, path, street type)`, which creates the finished street [known];
6. in every case, for the local sender with an open placement mode that is still valid, the mode is refreshed
   (`ai::game::StreetBuildMode::OnPlannerCommand`).
The search costs and the rules of a valid street cell belong to the street net subsystem.

**`0x20007` GE_Street_CancelConstruction** — `EventBase`, no payload. Sender `SendCancelStreetCommand` S 00781df0
(placement mode cancelled by the user). Executor S 00783eb0: if the sender's planner is active, the street under
construction is cancelled (removed), state 6. For the local sender the placement mode is notified.

**Automatic cancel.** Independently of commands, every logic tick, right after `AdvanceNetTick`, each of the 8
planners is tested: active and `IsPathValid()` false → cancelled as above. `IsPathValid` S 00663900: the
construction is valid, every path cell passes `GameQuery::IsOwnedCellFree_AllowWater(cell, owner, type == 2)`, and
the owner still has a flag on the first cell [known].

**`0x20009` GE_Street_Destroy** — `EventInt64`: street id. Sender `SendRemoveStreet` S 007811e0 (action 28; while
a street is being placed the same button cancels the placement instead). Executor S 00781290: street found →
`NNet::System::RemoveStreet` S 006652d0. Owner check: none.

**`0x2000B` GE_Order_Scholar** — `EventInt64`: flag id. Sender: action 10 (`Action_Flag_SendGeologist`). Executor
S 00781010: finds the flag; the follow-up is gated by a function that always returns false and calls an empty
stub. **The command does nothing in this build** [known].

#### Military

**`0x2000D` GE_Military_Attack** — `EventInt64_1Integer`: target building id, soldier fraction (f32 bits). Sender
`SendStartAttack` S 00781a00 from `AttackSlider::ExecuteAttack` S 00624700 (action 11): fraction = max(slider
value, `Military_GetMinAttackerFraction`), where the minimum is 1 / (2 × the largest number of available attackers
against this target in any single building of the player), 1.0 if none (S 00575f00; the buildings iterated are
the village system's vector at +0x3c, in list order [known]; it holds the buildings whose type has property
byte +0xf5, the territory-building flag [inferred from the field names of the typed structs]).
Executor `HandleStartAttack` S 00782cb0: target
found and its military component has **no** fight reference → `NMilitary::Attack::StartAttack(attacker = sender,
target, fraction)` S 00576500 (`docs/navy-and-military.md` §4). Neither the executor nor `StartAttack` tests that
the target belongs to another player or to an enemy, or that the sender can reach it: `StartAttack` creates the
fight, binds it to the target, copies the target owner's defense factor (`Military+0x1c`) into the target
building's military component (+0x64), dispatches attackers scaled by the fraction and sends the owner `!You
are under attack!` unconditionally [known]. `NMilitary::Attack::DispatchAttackers` S 00576320 walks the same
village list as the minimum above (vector at village system +0x3c) in list order and, for every building of
the attacker, sends `(int)(GetAvailableAttackers(target, building) × fraction + 0.5)` soldiers (truncated; the
0.5 is the double at S 007d4a90) when that is above 0, by sea or overland (`Military_ShouldAttackBySea`)
[known]. The fraction therefore acts per source building, not on the total. How
the soldiers of one building are chosen, the exception for depot-type buildings, and what a fight with an empty
side does are in `docs/sim/military.md` §3.5 and §3.6. The computer players call the same `StartAttack` with a
fraction of their own (`docs/sim/ai-player.md`).

**`0x2000E` GE_Military_Retreat** — `EventInt64`: target building id. Sender: action 12, only when the fight's
phase is 0 ("fighting"). Executor `HandleCancelAttack` S 00782bf0: target found, has a fight reference, the fight's
attacker (+0x18) **is the sender's player index**, and the fight's phase is 0 → `Military_RequestCancel`
S 00570900: fight +0xb4 = `actionsInFightDelayTime` (300 logic ticks in the data, i.e. 30 s), fight +0xb8 = true.
`NMilitary::Fight::Update` S 005715a0 then, once per logic tick while +0xb8 ("ending") is set [known]: if +0xb4
is exactly 0 it releases the attackers (`ReleaseAttackers`); then, if +0xb4 is 0 or above and the simulation
flag `GameSystem+0xec` is clear, +0xb4 is decremented. So the attackers are released on the 301st update after
the command and the counter rests at -1. `NMilitary::Fight::GetPhase` S 005708a0 returns 1 (gathering) while
the fight's start countdown is not 0, else 2 (ending) when +0xb8 is set, so a retreat command during gathering
and a second retreat command for the same fight both fail the executor's phase test [known]. What released
attackers do is described in `docs/sim/military.md` §3.6.

**`0x20011` GE_Military_SetDefenseFactor** — `Event1Integer`: f32 bits. Executor S 00781650: if the sender's player
entry is active, `Military+0x1c = value`. No range check.

**`0x20013` / `0x20014` / `0x20015` GE_Military_Set{Near,Medium,Far}DistanceAllocationFactor** — `Event1Integer`:
f32 bits. Executors S 00782180 / S 00782260 / S 00782340: `Military+0x10` / `+0x0c` / `+0x08` = value. No range
check, no active check.

The four commands above and `0x20021` are sent together, in the order `0x20013`, `0x20014`, `0x20015`, `0x20021`,
`0x20011`, by the confirm button of the in-game settings panel (`IngameSettingsPanel::OnButtonClick` S 00620970)
with the current slider values and the edited priority list, whether or not they changed [known].

**`0x20016` GE_Military_Reset** — `EventBase`. Executor S 007823c0: `NPlayer::Military::ResetDefaults` (§2.5
defaults). No sender exists in this build [known: no caller builds the id].

**`0x20017` GE_Military_ToggleIgnoreDistance** — `Event1Integer`: flag index. Executor S 00782390: toggles the
bool at `Military+0x14+index` (`NPlayer::Military::ToggleFlag` S 005c0990). No bounds check. No sender exists in
this build: the constant `0x20017` occurs once in the whole image, at S 00422e31 in the event-name table
(`NComm_InitEventTypeNameMap` S 00421bd0), and the dispatcher reaches the case through a jump table, so no HUD
control and no other code builds the event [inferred, byte search of the image]. The index is the index of
another player: a set flag removes that player's buildings from the sender's enemy-distance measure (§2.5). The
computer player sets the same flags directly (`Military::SetFlag` S 005c09b0), not through the command. The
executor changes simulation state, so a client that stays in step with original peers must still execute the
command when a peer's command stream contains it.

#### Goods

**`0x2001F` GE_Good_SetModifier** — `Event3Integer`: good id, entry index, weight (f32 bits). Sender
`SendCommand_2001F` S 00781f60 from the six sliders of the goods distribution panel (on every slider change).
Executor S 00782000: the sender's arrangement group for the good's good group; entry `index`; weight =
max(value, 0.001). A missing group or an index beyond the entries is not handled (null use / container assert)
[known]. The panel (`GoodArrangementPanel::OnSliderValueChanged` S 006412f0) sends its selected id only after
finding a group of the local player whose group id (+0x1c) equals it, and the slider's own index (+0x28); the
executor reads the same value as a good id and maps it to a group through the good's property field +0x78
[known].

**`0x20020` GE_Good_ResetModifier** — payload +0x10: good id. Executor S 00781f20: every entry of the sender's
group for that good gets its default weight. No sender exists in this build.

**`0x20021` GE_Good_MoveTransportPriority** — `EventData`: `count × {i32 goodId, i32 rank}` (byte count =
`count × 8`). Sender `SendSetGoodPrioritiesCommand` S 00783070 (settings panel confirm; the whole edited list).
Executor `HandleSetGoodPriorities` S 007844b0: the sender's priority list is **replaced** by the payload
(`count = bytes >> 3`). No validation of ids, ranks, duplicates or length [known].

**`0x20022` GE_Good_TransportPriorityReset** — `EventBase`. Executor S 007828d0: clears the sender's list and
rebuilds the default list (§2.5). No sender exists in this build.

#### Ship routes (details in `docs/navy-and-military.md` §5)

All three: `EventInt64_1Integer`: ship route id, player index (the local player's). Sent only when the selection
is a ship route (kind 6) with a valid id (S 00782d80, S 00782e40, S 00782f00; actions 1, 2, 3).

**`0x2001A` GE_Expedition_Start** — executor S 00781ad0: route found and `CanAssignShip(player)` →
`AssignNearestIdleShip(player)`.

**`0x2001B` GE_Expedition_Stop** — executor S 00781b70: route found and `HasActivePlayerExpedition(player)` →
`AbortPlayerExpedition(player)`.

**`0x2001C` GE_Expedition_Finish** — executor S 00781c10: route found, the player has an active expedition and it
is waiting for orders (state 5) → `OrderPlayerExpeditionFoundColony(player)`.

The player index is taken from the payload, not from the sender slot [known].

#### Sacrifices (rules of the sacrifices themselves belong to the sacrifice subsystem)

All five commands require the building's type property field +0x80 = 9 (sacrifice building) and use its
sacrifice component (+0x128, `VillageSacrifice`: +0x04 state, 0 none / recharging, 1 active, 2 ready, 3 ordered
[inferred from the writers]).

**`0x20024` GE_Sacrifice_Order** — `EventInt64_1Integer`: building id, sacrifice id. Sender
`SacrificeButton::OnClicked` S 0062f390 when the order check passes. Executor S 00782510: `CheckCanOrder(id)`
S 00561240 = 0 → `VillageSacrifice::Order(id, free = false)` S 00561410 (posts the cost goods as demand, state 3).
Check codes in test order: 1 component not in state 2; 5 the player's research is running at this building; 4 the
sacrifice needs research that is not done; 7 it is regenerating; 3 a dependency is not fulfilled; 2 it targets an
enemy (`sf_setTarget` = `Target_Enemies`, property +0x7c = 1) and the player has none
(`PlayerTable::HasEnemyOf`); 6 the sacrifice is locked for the owner (`ai::player::Player::IsLocked(owner, 1, id)`
S 005be970; lock category 1 = sacrifices, set by the Lua menu lock/unlock functions) [known].

**`0x20026` GE_Sacrifice_StartOrdered** — `EventInt64_1Integer`: building id, target player index. Senders: action
22 for a sacrifice with target kind 0 (`Target_Owner` in the data; the value is the owner's own index), else the
target chooser `SacrificeTargetPanel::OnChildClicked` S 00626c20 with the chosen player. Executor S 007825b0:
`CheckCanStart` S 00560f20 = 0 → component +0x0c = target, `ai::village::VillageSacrifice::Start` S 005615e0, in this order
[known]: a village callback; for target kind 1 two messages to the target player (`!Player started a sacrifice
against you!`, `!A Sacrifice is targeted at you!`); for target kind 0 the component's target is **overwritten
with the owner's index**, whatever the payload said, and, if a test on the definition passes (S 00556540, not
read), the same two messages go to every other player; then the active sacrifice is created with (building,
ordered sacrifice id, target), the target is reset to -1, the building's input stock is emptied and the state
becomes 1.
Check codes in order: 1 nothing ordered; 2 already active; 4 state
0; 3 cost goods missing (unless a free ticket is used); 6 regenerating; 5 the player already has an active
sacrifice of this kind; 7 targets an enemy and none exists; 8 the sacrifice is locked for the owner (as code 6
of the order check). The target index itself is
not validated [known].

**`0x20025` GE_Sacrifice_AbortSacrifice** — `EventInt64`: building id. Sender: action 23. Executor S 00782660:
`CanAbortOrCancel` S 00561050 → state 1: `ai::village::VillageSacrifice::AbortActive` S 00560d70 (the active sacrifice is removed, nothing
ordered, state 2); else `ai::village::VillageSacrifice::CancelOrder` S 00560e80 (demand cleared, delivered goods moved back to the output store,
state 0). Allowed when: state 1 and the active sacrifice's definition is abortable (`sf_setAbortable`); or
something is ordered, state is not 0, and the building type is not of the "not player-buildable" class.

**`0x20027` GE_Sacrifice_StartResearch** — `EventInt64_1Integer`: building id, sacrifice id. Sender
`SacrificeButton::OnClicked` when ordering is not possible but research is. Executor S 00782700: if the owner's
research is not already running at this building → `SacrificeResearch::Start(id, building)` S 0065fae0 (records the
definition, the start tick = current logic tick, running = true, links the research to the building, raises the
research-started callback). The executor only tests "running at this building" (S 00561210 → S 0065fb80), and
`Start` has no test of its own, so a research of the same player running at *another* building is overwritten
without its cancel callback [inferred from the two bodies]. The link (S 0053be10) is written on both sides: the
building's research reference (+0x12c: id and pointer of the research) and the research's building reference
(+0x18) [known]. Only the new building is touched, so the building of an overwritten research keeps its
reference to the research object while the research now names the new building [inferred]; "running at this
building" compares the research's stored building id with the asked building (S 0065fb80), so the old building
no longer counts as researching [known]. The sacrifice
id is not validated (not that it needs research, nor that it is not yet researched) [known].

**`0x20028` GE_Sacrifice_AbortResearch** — `EventInt64`: building id. Sender: action 21. Executor S 007827a0: if
the owner's research is running → `ai::logic::SacrificeResearch::Cancel` S 0065fbd0 (raises the research-cancelled callback,
running = false, unlinks the research building). The test is "running", not "running at this building": the
command cancels the owner's research whichever sacrifice building it names [known].

Owner check for all five: none (the component's owner is used, not the sender).

#### Session

**`0x20023` GE_Logic_SpeedUp** — `Event1Integer`: speed (i32). Sender `SendCycleGameSpeedCommand` S 00782950 (the
speed button of the game screen): `new = floor(current) mod 3 + 1`, so 1 → 2 → 3 → 1. Execution, in this order:
`NComm_Manager::HandleEvent` stores `speedUp = value` and recomputes `L = netTickLength × value`; then the sink
S 00782a20 stores `(float)value` in the global speed factor (`singleton+0x24`), which multiplies the frame time
fed to the logic tick accumulator. So at speed `s` the logic runs `s` times as many ticks per second and a net
tick holds `s` times as many logic ticks: its wall-clock length stays the same [inferred]. No range check on
execution. The global speed factor is not reset by the NComm session reset (it lives in another singleton, the
user profile); it is set to 1.0 by `nMenu::Game::SetupHud` S 005ed700, unconditionally, whenever the game
screen builds its HUD [known], i.e. on entering a match or a loaded game [inferred: its caller is the screen's
`OnEnter`]. The click test in `nMenu::Game::Update` S 005efea0 has no net-mode condition at the
call site [known]. The button is the widget `btSpeed` (hotkey `v`) of `menuingame.xml`, the one layout of
the game screen (`nMenu::Game +0x4a80`); the only code that touches it creates and destroys it, reads its
click and shows its children `x2` / `x3` (S 005ed700, S 005ea650, S 005efea0), so it is shown and usable in a
network match exactly as offline [known].

Other writers of the global speed factor, none of them a command and none of them touching `speedUp` [known]:
- pause: `nMenu::System::TogglePause` S 005da400 does nothing in net modes 1..4; offline `nMenu::Game::SetPaused`
  S 005ea9b0 saves the factor and sets it to 0, and restores it on unpause, raised to 1.0 when the saved value
  is below that (`docs/sim/logic-core.md` §3.1);
- the options panel, outside net modes 1..4 and when the profile's first byte is set: its constructor
  S 005e62f0 saves the factor and sets it to 0, its destructor S 005e61b0 restores it;
- cinematics: `nMenu::Cinematic::Update` S 005fb3e0 writes the factor while a cinematic fades, `OnHide`
  S 005faee0 restores a saved value;
- a typed cheat: in net mode 0, Enter on the chat input with the text `WhatTheHell` sets the factor to 20.0
  (`nMenu::Game::OnKeyDown` S 005ec340).
A factor of 0 stops the logic tick accumulator, so offline no command is executed late: commands still run at
once in the UI call (§3.1) while the simulation stands still [inferred].

**`0x2002B` GE_PlayerLeftGame** — `Event1Integer`: player index (not the sender). Never sent by a UI; three
places in the NComm manager build it, each with the local machine's own net id and slot as sender [known,
instruction search for the id]:
- `HandleEvent` S 0040e560, on `NE_InGame_PlayerLeftGame` (`0x3000B`): only in net modes 2 and 4 (the host
  test and `NComm_Manager_IsRole1to4` must both pass), with the player index of the event; appended to the
  outgoing package. The "net mode 0: run at once" branch behind it cannot be reached;
- `Process_MainLoop` S 00410f70, reconnect state 2 (the new host waits for the clients): once every human slot
  is filled again or the wait time (`manager+0x04`) is used up, each human slot that is still not filled is
  reset and gets one command with its player index;
- `Reconnector_DropRemotePlayers` S 004109b0 (reconnect state becomes 4): one command per slot that belongs to
  another machine.
  The last two append to the outgoing package, or in net mode 0 execute at once.
Executor S 00782910: finds the first building of that player whose type is headquarters-type (depot, casern and
territoryBuilding all set, in the order of the village system's vector at +0x20, S 005579a0) and removes it with
`RemoveBuilding(spill = true)`. What follows from losing the headquarters belongs to the victory conditions
(`docs/sim/players-victory.md` §3.6.1).

**Not handled:** `0x20001` GE_Turn_Done, `0x2000C` GE_Order_Explorer, `0x2001D` GE_Properties_Settings exist as
names only [known].

## 4. Update order

Per frame (`CApplicationEx::FrameTick_InGame` S 004018e0), in this order [known]: frame timer; input enable;
when the game screen's slot 4 returns true, `nGame::System::Update` and the update of the screen's message
list; the menu system's update (UI, where commands are queued); the NComm pump `Process_MainLoop` (where
packages arrive; only when a manager exists); the Lua thread update; `Fpu_SetDefaultControlWord` and
`NLogic::System::Update(listener = null, allowScript = true)` when a game system exists; the sound system;
rendering. `nGame::System::Update` therefore runs before the UI and before the logic of the same frame.

`NLogic::System::Update` S 00527070, only in session state 4:
1. `frameDelta = frameSeconds × speedFactor(1..3) × logic speed factor`; if above 5.0 it is replaced by one tick
   interval. `accumulated += frameDelta`.
2. While `accumulated ≥ nextTickTime`: if `CanAdvanceTick()` is false, stop and pull `accumulated` back to
   `nextTickTime - interval`. Otherwise, unless the editor's batch-edit mode is on, run one logic tick:
   1. `tickCounter += 1`;
   2. `AdvanceNetTick(tickCounter)` — **commands execute here** at net-tick boundaries;
   3. the 8 street planners: cancel invalid constructions;
   4. player table, village, street net (these two inside one map-update batch), settlers, transport, resources,
      doodads, military, navy, statistics (if initialised), AI, sacrifices, spawn system, chests, victory
      conditions;
   then (also when the batch-edit mode skipped the tick) `nextTickTime += interval`, slot 6 of the scene
   (global `g_pScene` S 0088ca60, getter S 0067e860; slot 6 of the vftable S 007f8f2c is
   `S2CG::Scene::SyncLogicTick` S 00680550: it copies `nextTickTime` into the scene's game time and hands it to
   the map, character, item, animal, ship and swarm renderers; presentation only [known for the slot and the
   body; inferred that S 007f8f2c is the scene's primary vftable]), the map script's `onLogicTick` (when the
   caller allows it and batch-edit mode is off), and slot 1 of the tick listener for every tick after the first
   of this frame. The only caller, `FrameTick_InGame`, passes no listener and allows the script [known].
   The loop ends when `accumulated < nextTickTime`.

`nGame::System::Update` S 00780d20, per frame: host only, session state 3 and all slots loaded → broadcast
StartGame (every frame until the state changes); autosave timer (only while the menu system's UI-suppressed
flag is clear and not in a cinematic); slot 1 of the cursor (+0x10; empty, §2.1); camera; once the logic tick
counter is not -1: slot 1 of the script object (+0x60c; empty, §2.1), and (UI-suppressed flag clear) music and
the cutscene camera [known]. The sound object (+0x610) is not updated here.

`nGame::System::Render` S 007835d0, per frame [known]: when a street placement mode exists, its first entry has
waypoints and its byte +0x39 is clear, refreshes the placement preview at the cursor cell (+0x24); when the
scene hook byte (+0x0d) is set, calls slot 12 of the scene (S 00680a00 `RenderPostFxAndOverlay` in the vftable
S 007f8f2c); updates the cursor (`Cursor::Update`).

## 5. Inputs and outputs

### 5.1 Command sources

Action buttons (`nMenu::ActionButton::ExecuteAction` S 00623730). The action number indexes the name table
`g_ActionNames` (31 strings at S 0087fe78, filled by the initializer S 007c81c0) [known]; that the UI layout
names actions by these strings is [inferred]:

| # | Name | Result |
|---|---|---|
| 0 | Action_None | nothing |
| 1 | Action_ShipRoute_StartExpedition | `0x2001A` |
| 2 | Action_ShipRoute_StopExpedition | `0x2001B` |
| 3 | Action_ShipRoute_FinishExpedition | `0x2001C` |
| 4 | Action_Building_Destroy | `0x20003` (own building, block reason 0) |
| 5 | Action_Building_Upgrade | `0x2000F` |
| 6 | Action_Construction_Pause | `0x20029` |
| 7 | Action_Construction_Resume | `0x2002A` |
| 8 | Action_Flag_Destroy | `0x20005` (block reason 0) |
| 9 | Action_Flag_BuildStreet | no command: opens the street placement mode at the selected flag |
| 10 | Action_Flag_SendGeologist | `0x2000B` (dead) |
| 11 | Action_Attack_Begin | `0x2000D` through the attack slider |
| 12 | Action_Fight_Retreat | `0x2000E` (fight phase 0) |
| 13, 14 | Action_Military_SetToSwordsMen / SetToBowMen | `0x20012` |
| 15, 16 | Action_Casern_Enable/DisableTraining_Sword | `0x20018` index 0 |
| 17, 18 | Action_Casern_Enable/DisableTraining_Bow | `0x20018` index 1 |
| 19, 20 | Action_Casern_Enable/DisableUpgrading | `0x20019` |
| 21 | Action_Sacrifice_AbortResearch | `0x20028` |
| 22 | Action_Sacrifice_Start | `0x20026`, or the target chooser first |
| 23 | Action_Sacrifice_AbortSacrifice | `0x20025` |
| 24..27 | Action_Production_Pause/Resume, Action_Catapult_Pause/Resume | `0x2000A` |
| 28 | Action_Street_Destroy | `0x20009`, or cancels a running placement |
| 29 | Action_Flag_Create | `0x20004` at the menu selection's cell (+0x8c); then cancels a running placement |
| 30 | Action_Upgrade_Cancel | `0x20010` |

Enable/disable pairs send the same toggle command; which of the two buttons is shown is a UI decision.

Availability (`ActionButton::RefreshAvailability` S 00623da0) [known]. "Local player" is the game screen's
player; the target is the current selection (§2.4). An unavailable button shows the tooltip text indexed by the
failure code (per-action text tables, `SetAvailability` S 00623470); the codes are those of the named function.

| # | Available when | Failure code |
|---|---|---|
| 1 | route `CanAssignShip(local player)` | `GetAssignShipBlockReason(local player)` |
| 2 | the route has an active expedition of the local player | 1 when it has none |
| 3 | route `CanFoundColony(local player)` | `GetFoundColonyBlockReason(local player)` |
| 4 | `Building::GetDestroyBlockReason` = 0 | that reason (1..3, §3.4 `0x20003`) |
| 5 | `Upgrade::GetBlockReason` = 0 | that reason (1..4, §3.4 `0x2000F`) |
| 8 | `Flag::GetRemoveBlockReason` = 0 | that reason (1..4, §3.4 `0x20005`) |
| 9, 30 | always | 0 |
| 10 | never: the test is a function that returns false | 2 |
| 11 | `NMilitary::Attack::GetAttackAvailability(target, local player)` = 0 (S 005759f0, through the wrapper S 00575b50) | that value |
| 12 | the building's fight reference is valid, the fight is active and its phase is 0 | the fight's phase |
| 13, 14 | `Military::CanToggleSoldierKind` | `GetToggleSoldierKindBlockReason` |
| 21 | the owner's sacrifice research is running (S 005611b0) | 1 when it is not |
| 22 | `VillageSacrifice::CheckCanStart` = 0 | that code (1..8, §3.4 `0x20026`) |
| 23 | `VillageSacrifice::CanAbortOrCancel` | `GetAbortOrCancelBlockReason` |
| 29 | the menu selection's cell is inside the map and its construction-map flags for the local player have bit `0x20` (a flag can be placed) | 0 |
| 28 | not evaluated (the state set elsewhere stays) | |

Buttons that swap their action instead of being enabled or disabled (same function) [known]:

| Pair | Shown action |
|---|---|
| 6 / 7 | 7 (resume) when a building is selected and its construction fails "(+0x70 > 0 or +0x74 > 0) and not paused" (S 00622f10); else 6 (pause) |
| 15 / 16, 17 / 18 | per training slot (sword: component +4, bow: +8): enabled byte clear → 15 / 17 (enable), set → 16 / 18 |
| 19 / 20 | training component +0x14 clear → 19 (enable), set → 20 |
| 24 / 25, 26 / 27 | production enabled → 24 / 26 (pause), else 25 / 27 (resume) |

After the per-action test, for every action except 4, 6 and 7 (the 6 / 7 swap returns before it): when a
building is selected and the action panel holds an override for the key read through building +0x0c
(`ActionButtonPanel::HasActionOverride` S 005f07c0; the key is the first dword of the object at building
+0x0c [inferred: the building type id of its property; the scripts below pass building types]), the button is
made unavailable with the override's
code [known]. The override table (a map key → code) has one writer, `ActionButtonPanel::SetActionOverride`
S 005f0fc0, whose only caller is the Lua menu function `allowActions(key, allow, code)` S 005d9570: `allow =
true` removes the key's entry, `allow = false` stores `code` for it [known]. The shipped scripts call it in
two campaign maps only, with a building type as key (`maps/campaignMaps/C08.lua`: `menu.allowActions(woodCutter,
false, 4)`; `C09.lua`: `farm` with code 5, later `menu.allowActions(farm, true)`) [known]. `MenuSelection::SetSelectionKind`
S 00616f40 applies the same override to every button of the panel whose action is neither 0 nor 4 when the
selection changes [known]. The attack availability codes (action
11) come from `GetAttackAvailability` S 005759f0 and are specified in `docs/navy-and-military.md` §2 and
`docs/sim/military.md` §3.5. None of these tests is repeated by an executor unless §3.4 says so.

Other sources: build menu (`0x20002`), street placement mode `ai::game::StreetBuildMode::HandleClick` S 0078bed0
(`0x20006` on the first segment, `0x20008` per accepted click) and `Cancel` S 0078b1d0 (`0x20007`), depot and
casern info boxes (`0x2001E`), in-game settings panel (`0x20013`, `0x20014`, `0x20015`, `0x20021`, `0x20011`),
goods distribution panel (`0x2001F`), sacrifice buttons (`0x20024`, `0x20027`), sacrifice target panel
(`0x20026`), speed button (`0x20023`), the NComm manager itself (`0x2002B`).

### 5.2 What the subsystem asks of others

- NComm: `QueueGameCommand`, local slot and net id, sender index lookup, local player index, session state.
- Simulation: the functions named in §3.4 on `g_pGameSystem` (village, net, navy, military, sacrifice, player
  table, game query, street planners).
- UI: the selection and the hovered cell.

### 5.3 What it offers

- To NComm (registered in `BuildWorld` as `manager+0x50`): execution of game commands, the "game running"
  notification, and `ComputeChecksum`.
- To the menus: `Send*` functions, `BeginStreetBuildMode` S 00784220, `GetActiveStreetBuildMode` S 00783490,
  `EndCinematic` S 00782bb0. `EndStreetBuildMode` S 00783430 is called only by the executors of `0x20004` and
  `0x20006` and by the placement mode itself (`StreetBuildMode::Cancel`, `ai::game::StreetBuildMode::OnPlannerCommand`)
  [known from the caller lists].
- Commands raise no event of their own; effects are seen through the simulation's callbacks (e.g. upgrade
  started / cancelled, sacrifice callbacks). `0x20004` writes the log line
  `Create Flag for Player %d at position ( %d, %d ) with UID %016X` [known].

## 6. Data-driven parameters

| Key (file under `data/game/scripts/properties/`) | Read by | Example | Use here |
|---|---|---|---|
| `properties.mi_setActionsInFightDelayTime` (`military.lua`) | military config +0x118 | 300 | retreat delay (`0x2000E`), destroy countdown (`0x20003` in a fight); logic ticks |
| `properties.bp_setArrangementValue(building, w)` (`buildings.lua`) | building property +0xe4 | 0.55, 0.3, 0.5, 0.7, 0.4 | default distribution weight (`0x20020`, initial groups) |
| `properties.bp_setArrangementLocked(building, bool)` (`buildings.lua`, 4 calls) | building property +0xf2 (S 0054cdd0) | `true` for the four sacrifice buildings | entry not user-adjustable [inferred from the name] |
| `properties.gp_setArrangementGoodId` (`Goods.lua`) | good property +0x78 | | the good group a good's distribution belongs to [inferred] |
| `properties.gp_setTransportPriority(good, tribe, n)` (`Goods.lua`, 141 calls) | good property | 13, 12, 4, 0, 15, 11, 16 | default rank in the priority list (`0x20022`, initial list) |
| `properties.bp_setUpgrade(building, target)` (`buildings.lua`) | building property +0xe8 | guardHouse → tower → fortress | upgrade target (`0x2000F`) |
| `properties.sf_setTarget(sacrifice, Target_Owner…)`, `sf_setAbortable` (`sacrifices*.lua`) | sacrifice property +0x7c, +0x80 | `Target_Owner`, `true` | target chooser, abort rule |
| `properties.cfg_setGameSpeed` | game config +4 | not set in the shipped data; code default 0.1 | logic tick interval in seconds |
| `[Ping] pingFrequencyGame` (`data/game/settings/network.ini`) | network config +0x10 (`manager+0x370`) | 2.5; constructor default 3.0 (S 0040a390); the loader S 0041ede0 uses the string `2.5` when the key is missing | seconds between two net tick length adaptations (§3.2) |

Constants in code: military allocation defaults 0.1 / 0.3 / 1.0 and defense 0.5; weight floor 0.001; hang timeout
2.0 s; frame delta clamp 5.0 s; game speeds 1..3, initial `speedUp` 1; net tick length 1 offline, 4 at network
start, adapted within 1..10 (factors 0.5, 1.7 / 1.4 / 1.1, 0.01; latency scale `manager+0x388` 1.0), 4 after a
reconnect (`manager+0x384`); command delay 2 net ticks; packages kept for 5
net ticks; 6 session slots; 8 street planners.

## 7. Save and load

- `nGame::System` stores nothing. Pending commands (the outgoing package and the tick package lists) are not in a
  save [known: the save contents are listed in `docs/multiplayer-save.md`].
- Stored by their owners, and therefore restored: the player settings changed by commands — `NPlayer::Military`
  (section `PlayerMilitary`: 3 floats, 8 bytes, 1 float, S 005c09d0), `NPlayer::GoodPriorities` (initialized byte,
  count, then per entry a section `GoodPriority` with good id and rank, S 005c2700),
  `NPlayer::GoodArrangement` — and all building, street and fight state.
- `NPlayer::GoodArrangement::Store` S 005c1050 [known]: section `Good Arrangement`, initialized flag, group
  count, then every group in vector order. `GoodArrangementGroup::Store` S 005c0b80: its own section,
  initialized flag, the entry list (the `Store` of the list object at group +0x08), good group id (+0x1c).
  `Load` S 005c16a0 clears an initialized object first and reads the same; for a section version below 4 the
  loaded groups are discarded and the defaults of §2.5 are rebuilt from the tribe [inferred: the version test is
  visible, the decompiled call order around it is not clean]. The entry list is an `NPlayer::ArrangementBase`
  (constructed by S 005c37b0 inside the group constructor S 005c0c20); `ArrangementBase::Store` S 005c2fa0
  writes a section `PlayerArrangementBase`, the entry count, then slot 1 of every entry (stride 0x14), and
  `ArrangementObject::Store` S 005c2e20 writes a section `PlayerArrangementObject`, the float +0x04 (weight),
  the float +0x08 and the int +0x0c (building type id) [known for the two bodies; inferred that they are the
  slot-1 functions the group and the list call: neither has a direct caller]. [TODO] not established: the
  meaning of the entry float +0x08 (static read of `ArrangementBase::PickNext` S 005c30c0).
- The 8 street planners are not stored: `NLogic::System::Save` S 005275c0 writes the map info, the id counter,
  the running flag, three timing floats and the tick counter, and no subsystem `Store` takes a planner
  [known for S 005275c0; `docs/sim/save-format.md` lists the sections]. On load,
  `NLogic::System::PostLoad` S 005273d0 first goes through the 8 planners — one that is active is cancelled as
  in §3.4 (`0x20007`), then each is stopped — and then starts all 8 again on the loaded map [known]. A freshly
  loaded planner object is not active, so the unfinished street that a save may contain (it is an object of the
  street net) has no planner after the load and cannot be extended, completed or cancelled by a street command
  [inferred]. The planner pass runs before any subsystem's post-load; later in the same function the street
  net's `NNet::System::PostLoad` S 006654f0 calls the post-load of every flag and street and then removes
  (`RemoveStreet`) every street whose start or end flag reference (id high dword at street +0x4c / +0x6c) is
  not a valid id [known]. An unfinished street has no end flag, so it is removed there [inferred: the end
  reference of an unfinished street was not read]. In the running game the street mode survives opening the
  menu and its dialogs (nothing is placed until the street ends in a flag); after loading a save made in that
  state the street mode is gone and no street or stub exists [live, 2026-10-12].
- The game speed factor and the NComm `speedUp` are session values, not in a save. `speedUp` is 1 after every
  NComm session reset (S 0040a810); the global speed factor is set to 1.0 when the game screen builds its HUD
  (`nMenu::Game::SetupHud` S 005ed700; the write lies inside the function's `uiSuppressed == 0` block, so it
  does not happen while the menu system's UI-suppressed flag is set) [known].

## 8. Determinism notes

- Commands are the only non-deterministic input of the simulation. They must run on every machine at the same
  logic tick, before that tick's subsystem updates, in the same order (§3.2, §3.3).
- `HandleGameCommand` resets the FPU control word before each command, because the caller is not the logic loop's
  own floating-point context [inferred]. A reimplementation needs identical float behaviour only where a command's
  float feeds the simulation: the attack fraction, the allocation and defense factors, the distribution weights.
  These travel as raw 32-bit patterns and must not be converted on the way.
- Validation runs on execution, against the state of that tick, identically on every machine. A sender-side check
  is only a convenience; never skip the executor's check.
- Toggle commands (`0x2000A`, `0x2001E`, `0x20012`, `0x20018`, `0x20019`, `0x20017`) depend on the state at
  execution, not at the click.
- Lookups by `Unique` id are map lookups; `0x2002B` and the minimum attack fraction iterate vectors in insertion
  order. No command handler draws a random number itself [known for the handlers; callees such as `StartAttack`
  not audited here]. The street search of `0x20008` builds its route with `randomize = false` and draws none
  [known, S 00676d10].
- Local state changes that bypass the command path exist only outside network matches: pause, the options
  panel and the typed cheats of `nMenu::Game::OnKeyDown` S 005ec340, which are accepted in net mode 0 only
  (`WhatTheHell` speed 20; `WhatCanEyeSee` calls `MapModifier::ExploreArea` from the map centre with the map
  height as radius for the local player; `ItsLikeAJackpot` calls `Cheat_FillStoreWithGoods`; two more touch no
  simulation state: `DontWantToLose` records the map as completed in the user profile, `ThatsANiceView`
  switches the camera view mode between 0 and 2) [known for the mode test and the calls; the callees' bodies
  were not read].
- Offline, commands run inside the UI call between two logic ticks, not at a tick boundary [live, 2026-10-14:
  a flag command ran inside `SendCreateFlag`, in the tick it was issued]. This is deterministic
  for a single machine but means an offline session cannot be replayed from tick-stamped commands without
  recording the tick at which each ran.
- Checksum (`ComputeChecksum` S 00784080): an `NCore::CRCStream` over, in this order: logic random generator,
  player table, village, settlers, transport, military, navy, street net, AI, global logic id counter [known].
  Not part of it: resources, doodads, statistics, sacrifices, the spawn system, chests, victory conditions, the
  street planners and the map itself [known from the call list; a divergence there is only detected once it
  reaches a checksummed subsystem]. It is sent
  with every new outgoing package (value 0 in net mode 0, §3.2) and compared per net tick against the expected
  number of checksums `manager+0x28` (connected human players at the start; 1 on a new host after a reconnect);
  the result is the in-sync flag `manager+0x4c`, and only a change of the flag is reported (S 00411990)
  [known]: true → false raises `!DESYNC DETECTED`, logs the report and writes a dump; false → true raises
  `!RESYNC DETECTED` when `T > 4`; and when `T - startTick` is exactly 5 with the flag still false,
  `!NO SYNC START` is raised with a dump. The flag is false at match start and after a reconnect, so the first
  desync message needs a matching comparison before it. Nothing else follows from a mismatch
  (`docs/multiplayer-save.md`). The stream ignores section
  tags and hashes field values only; widths and the string rule are in `docs/sim/save-format.md` §3.9.
- What the checksum sees of each command family [known from the `StoreForChecksum` / `StoreChecksum` bodies
  named]: the settings commands (`0x20011`, `0x20013`..`0x20017`, `0x2001F`..`0x20022`) through the player table
  (§2.5); all building commands through `NVillage::Building::StoreForChecksum` S 0055c690, which writes every
  component including construction, production, military (with the destroy countdown), good flags, upgrade,
  soldier training (casern types) and, for sacrifice buildings, the sacrifice component (+0x128) and the
  research reference (+0x12c). Flags and streets (with the unfinished street of a planner) are reached through
  the street net's entry and fights through the military system's entry of the checksum list [inferred: those
  two bodies were not read here; `docs/sim/streets-transport.md` §7, `docs/sim/military.md` §7].
- Sacrifice commands are therefore covered only on the building side: the component state changed by
  `0x20024`, `0x20025`, `0x20026` and the building's research reference set by `0x20027` are hashed, but the
  sacrifice system itself (active sacrifices, the per-player research record with its start tick, the
  modifiers) is not. A machine on which `0x20026` started a sacrifice with different parameters, or on which
  `0x20028` did not stop the research, keeps a matching checksum until an effect of the sacrifice changes a
  hashed subsystem (goods, soldiers, buildings) [inferred]. The target player index of `0x20026` is such a
  value: it is used and reset by `ai::village::VillageSacrifice::Start` and never hashed. A remake that wants earlier
  detection can add the sacrifice system to its own checksum; this changes nothing in play.
- The street planners' own fields (state, search object) are not hashed [known from the call list]; their only
  simulation effect is the unfinished street.
- A command from one player can address another player's object (no owner check in most executors). The original
  relies on the UI. All machines apply it alike, so it does not desynchronise.

## 9. Notes for a reimplementation

- Keep the model: input → command record `{id, sender, payload}` → scheduled for a future tick → validated and
  applied identically everywhere. A single-player build can use the same queue with delay 0 or 1 tick; executing at
  a tick boundary instead of mid-frame is a safe simplification.
- The original command set is small enough to keep one-to-one. Ids, classes and field order only matter for
  network compatibility with the original client; saves do not contain commands.
- Worth changing: add sender-owns-target checks; replace toggles by explicit set commands; validate indices
  (`0x20018`, `0x20017`, `0x2001F`), list contents (`0x20021`) and ranges (factors, speed); drop the dead ids
  (`0x2000B`, `0x2000C`, `0x2001D`, `0x20001`); give `0x20016`, `0x20020`, `0x20022` a UI or drop them.
- Must be kept exactly for identical play: the validation order and block reasons of §3.4, the two-step street
  protocol (the unfinished street exists in the net between commands and is cancelled when its path becomes
  invalid), flag creation finishing a ready street, destroy turning into a countdown during a fight, the retreat
  delay, the minimum attack fraction, the weight floor 0.001, the default tables of §2.5.
- The settings panel sends five commands on every confirm; a remake can send only what changed.

## 10. Open questions

| Question | Settled by |
|---|---|
| Answered (§3.4, `0x20023`): the speed button is shown and usable in a network match; nothing hides `btSpeed` and the click test has no net-mode condition | static: S 005efea0, S 005ed700, `menuingame.xml` |
| What sets the per-user quality level in the net tick adaptation (§3.2). Answered: the latency samples are milliseconds of a full round trip (`logic-core.md` §10 Q2) | `TinCatNetwork::UIS_AddPingSample` S 0041d610 only stores the value its caller passes (newest first, at most 2 per user); static read of `cb_Ping_Received` S 0041d910 and of the writers of the level field |
| Do all machines clear their package lists at the same net tick in a reconnect (§3.2) | static read of the reconnect state machine in S 00410f70; or observe: issue commands just before a host loss and compare the worlds after the rejoin |
| Does a forged `0x2000D` against an own or allied target find attackers. `GetAvailableAttackers` S 00575dc0 has no owner or diplomacy test of its own [known]: it returns 0 only when the source building cannot provide attackers, is bound to another fight, has a reach factor of 0 or below, has no available soldier, or the target is not reachable | static read of `Military_GetAttackReachFactor` and `Military_IsTargetReachable`, the two callees that could still exclude such a target (`docs/sim/military.md` §3.5) |
| Meaning of the second float (+0x08) of a distribution entry (§7) | static read of `ArrangementBase::PickNext` S 005c30c0 |
| Answered (§7): an unfinished street in a save is gone after the load, with no stub at the start flag [live, 2026-10-12] | — |
| Is the old building's research reference (+0x12c) cleared when `0x20027` moves the research (§3.4) | cannot be produced with the UI of this build; static read of the readers of building +0x12c |
| Answered (`village-buildings.md` §3.5): the building is removed in the tick in which the countdown is decremented to 0, by the test that follows `Building::Update` in the same loop iteration; the two messages are not posted at all unless the countdown started at 0 | static: S 0055a640, S 005609b0 |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 007845a0 | `nGame::System::HandleGameCommand` | dispatcher of executed commands |
| 00408b10 | `NComm_Manager::QueueGameCommand` | entry of every command (drop / run now / queue) |
| 00408860 | `NComm_Manager::IsGameHanging` | input gate |
| 00411990 | `NComm_Manager::AdvanceNetTick` | net tick, package exchange, execution point |
| 004088b0 | `NComm_Manager::CanAdvanceTick` | lockstep gate |
| 00410530 | `NComm_Manager::ExecuteEventPackage` | runs the events of a package |
| 0040e560 | `NComm_Manager::HandleEvent` | session events; `0x20023` side effect; queues `0x2002B` |
| 004089c0 | `NComm_Manager::SendEventUserChecksum` | begins the next outgoing package |
| 00412490 | `NComm_Event_GetSenderPlayerIndex` | sender slot → player index |
| 00421bd0 | `NComm_InitEventTypeNameMap` | the game's names of all event ids |
| 00527070 | `NLogic::System::Update` | logic tick loop |
| 00780d20 | `nGame::System::Update` | per-frame update |
| 00784d40 | `nGame::System::BuildWorld` | world build, registers the event sink |
| 00784080 | `nGame::System::ComputeChecksum` | desync CRC |
| 00623730 | `nMenu::ActionButton::ExecuteAction` | action buttons → commands |
| 007c81c0 | initializer of `g_ActionNames` | action names |
| 00620970 | `nMenu::IngameSettingsPanel::OnButtonClick` | settings commands |
| 0078bed0 | `ai::game::StreetBuildMode::HandleClick` | street commands |
| 00781980 / 007818b0 | `HandlePlaceBuilding` / `SendPlaceBuilding` | `0x20002` |
| 00781150 / 007810a0 | `HandleDestroyBuilding` / `SendDestroyBuilding` | `0x20003` |
| 00783690 / 00780e10 | `HandleCreateFlag` / `SendCreateFlag` | `0x20004` |
| 007813d0 / 00781320 | `HandleRemoveFlag` / `SendRemoveFlag` | `0x20005` |
| 00783e10 / 00781d40 | `HandleBuildStreet` / `SendBuildStreetCommand` | `0x20006` |
| 00783eb0 / 00781df0 | `HandleCancelStreet` / `SendCancelStreetCommand` | `0x20007` |
| 00783f60 / 00781e80 | `HandleExtendStreet` / `SendExtendStreetCommand` | `0x20008` |
| 00781290 / 007811e0 | `HandleRemoveStreet` / `SendRemoveStreet` | `0x20009` |
| 00780f80 / 00780eb0 | `HandleToggleProduction` / `SendToggleProduction` | `0x2000A` |
| 00781010 | `HandleCommand_2000B` | `0x2000B` (dead) |
| 00782cb0 / 00781a00 | `HandleStartAttack` / `SendStartAttack` | `0x2000D` |
| 00782bf0 | `HandleCancelAttack` | `0x2000E` |
| 00781540 / 00781470 | `HandleStartUpgrade` / `SendStartUpgrade` | `0x2000F` |
| 007815d0 | `HandleCancelUpgrade` | `0x20010` |
| 00781650 / 007820f0 | `HandleCommand_20011` / `SendCommand_20011` | `0x20011` defense factor |
| 00781690 | `HandleToggleSoldierKind` | `0x20012` |
| 00782180, 00782260, 00782340 | `HandleSetMilitaryValue2/1/0` | `0x20013`, `0x20014`, `0x20015` |
| 00782060, 007821d0, 007822b0 | `SendSetMilitaryValue2/1/0Command` | senders of the same |
| 007823c0 | `HandleResetMilitaryDefaults` | `0x20016` |
| 00782390 | `HandleToggleMilitaryFlag` | `0x20017` |
| 007823f0, 00782480 | `HandleCommand_20018`, `HandleCommand_20019` | casern training / upgrading |
| 00781ad0, 00781b70, 00781c10 | ship route executors | `0x2001A`, `0x2001B`, `0x2001C` |
| 00782d80, 00782e40, 00782f00 | `SendCommand_2001A/B/C` | senders of the same |
| 007817f0 / 00781720 | `HandleToggleGoodFlag` / `SendToggleGoodFlag` | `0x2001E` |
| 00782000 / 00781f60 | `HandleCommand_2001F` / `SendCommand_2001F` | `0x2001F` |
| 00781f20 | `HandleCommand_20020` | `0x20020` |
| 007844b0 / 00783070 | `HandleSetGoodPriorities` / `SendSetGoodPrioritiesCommand` | `0x20021` |
| 007828d0 | `HandleResetGoodPriorities` | `0x20022` |
| 00782a20 / 00782950 | `HandleSetGameSpeed` / `SendCycleGameSpeedCommand` | `0x20023` |
| 00782510, 00782660, 007825b0, 00782700, 007827a0 | sacrifice executors | `0x20024`..`0x20028` |
| 00782fc0, 00782840 | `HandleAbortConstruction`, `HandleCommand_2002A` | `0x20029`, `0x2002A` |
| 00782910 | `HandleCommand_2002B` | `0x2002B` |
| 005301c0, 0052f8a0 | `GameQuery::CanPlaceBuildingTypeAt`, `CanPlaceFlagAt` | placement checks |
| 0055cd40, 00669f70, 005670c0 | destroy / remove-flag / upgrade block reasons | validation |
| 006636e0, 00663bf0, 00663a00, 00663900, 005289b0 | street planner | street protocol |
| 005c0930, 005c2bf0, 005c0d40 | `NPlayer::Military::ResetDefaults`, `GoodPriorities::InitFromGoodTable`, `GoodArrangementGroup::ResetToDefaults` | reset commands |
| 00410f70 | `NComm_Manager::Process_MainLoop` | net tick length adaptation (`0x3000D`) |
| 0040a530, 0040a810 | `NComm_Manager` constructor, `ResetSession` | start values of `L`, `speedUp`, `T` |
| 0040b270 | `NComm_Manager::BeginGameRunning` | match start: `T`, `startTick`, `subTick` = 0, state 4 |
| 004093a0, 0040b700 | `ReconnectAndRejoin`, `Reconnector_RestartAsServer_DoAction` | reset of the command stream in a reconnect |
| 0040a390, 0041ede0 | `NComm_NetworkConfig` defaults, `network.ini` loader | `pingFrequencyGame`, `manager+0x384`, `+0x388` |
| 00412ae0, 00412e80 | `TickPackageList::AddReceived`, `TickPackage::AppendEvents` | order of blocks in a package |
| 004085e0 | `Event1Integer::Serialize` (shared body) | wire layout |
| 00623da0, 00623470 | `ActionButton::RefreshAvailability`, `SetAvailability` | sender-side availability |
| 005609b0, 00560890, 0055fc10 | `NVillage::Military::Update`, `NotifyDestruction`, countdown start | destroy countdown |
| 005715a0, 00570900 | `NMilitary::Fight::Update`, `Military_RequestCancel` | retreat delay |
| 00576320 | `NMilitary::Attack::DispatchAttackers` | use of the attack fraction |
| 005337e0 | `GameQueryHelper::MinDistanceToEnemyMilitaryBuilding` | reader of the ignore-distance flags |
| 005be6e0, 0055c690 | `Player::StoreChecksum`, `Building::StoreForChecksum` | what the checksum sees of commands |
| 005c1050, 005c16a0, 005c0b80 | `GoodArrangement::Store` / `Load`, `GoodArrangementGroup::Store` | save of the distribution |
| 005275c0, 005273d0 | `NLogic::System::Save`, `PostLoad` | planners not saved, restarted on load |
| 006654f0 | `NNet::System::PostLoad` | removes streets without a valid start or end flag after a load |
| 005c2fa0, 005c2e20 | `ArrangementBase::Store`, `ArrangementObject::Store` | save of the distribution entries |
| 004018e0 | `CApplicationEx::FrameTick_InGame` | per-frame order |
| 0067e860, 00680550 | `g_pScene` getter, `S2CG::Scene::SyncLogicTick` | scene call after every logic tick |
| 005f07c0, 005f0fc0, 005d9570 | `ActionButtonPanel::HasActionOverride`, `SetActionOverride`, Lua `allowActions` | action button overrides |
| 005759f0, 00575b50 | `GetAttackAvailability`, its boolean wrapper | availability of action 11 |
| 006688d0, 00676d10, 007f87b8 | `StreetConstructorStreet::AddPoints`, `AStar::BuildPath`, vftable | route appended by `0x20008` |
| 0055eff0 | `NVillage::Construction::AdvanceWork` | meaning of +0x70 / +0x74 |
| 0053be10, 0065fb80, 0065fae0 | research link, `IsAtBuilding`, `SacrificeResearch::Start` | `0x20027` |
| 005ed700, 005da400, 005ea9b0, 005ec340 | `nMenu::Game::SetupHud`, `TogglePause`, `SetPaused`, `OnKeyDown` | other writers of the speed factor |
| 004085a0, 0041f780, 0041f860, 0041fa50, 0041fb30, 0041feb0 | event `Serialize` functions | wire layout of commands |
| 0052fbe0, 005be970 | `GameQuery::CanPlaceBuildingAt`, `Player::IsLocked` | placement test; lock test (not on the command path for buildings) |
| 0066a020 | `NNet::Flag::GetWaterStreetBlockReason` | start-flag test of water streets |
| 00561240, 00560f20, 00561050 | sacrifice order / start / abort checks | validation |
