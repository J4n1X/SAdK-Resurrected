# Live-session queue entries examined statically (2026-10-12)

Source of the entries: `docs/live-session-queue.md`, section `## From the specifications (docs/sim)`.
All addresses are static addresses in `sadk_noav.exe` (`S xxxxxxxx`). Read through `mapctl fn`, the decompile
cache and read-only Ghidra MCP calls (xrefs, memory). Nothing was observed in a running game, so no statement
below is `[PROVEN]` in the sense of HARNESS §4; "SETTLED" means the code path decides it without a virtual call
or a data value in the way.

14 entries examined: 9 SETTLED, 5 STILL NEEDS LIVE, 0 CONTRADICTS SPEC. Two of the settled ones add something
the specification does not say (closed row; products per cell above amount 8).

---

### Products per resource cell
Status: SETTLED
Answer: A mine gets `n − 1` products out of a cell with amount `n` for `1 <= n <= 8`, and 7 products for any
other amount that is not 1000 (a first use sets the amount to `min(7, n − 1)`). The cycle that takes the last
unit delivers nothing and drops the link. Amount 1000 is never reduced and every cycle delivers. A mine is the
only building that loses a product this way: the fisher's use of the same call ignores the result.
Evidence:
- S 00674650 `ConsumeResourceAtCell`: only if the cell's type equals the asked type and amount != 1000; a
  positive amount becomes `min(7, amount − 1)`; at 0 the type is set to −1.
- S 00674e70 `ConsumeAnyResourceAtCell`: calls the above with the cell's own type, then returns true only if
  the amount is 1000 or not 0. So the call that brings the amount to 0 returns false.
- S 0055c860 `FieldConnection::ConsumeFieldResource`: on false sets the link to (−1, −1) and returns false.
- S 00565f80 `Production::OnProductionFinished`: for property `+0x3c == 8` and `+0x80 == 6` it calls
  `ConsumeFieldResource` and on false jumps past `DeliverProducts` (S 00565990). No other test in between.
- S 0077ebf0 `NMovie::Working::Update` switches on property `+0x80` with cases 0..3 only; a mine (6) takes
  the default, so there is no second consumption per cycle. Case 3 (fisher) calls `ConsumeFieldResource` and
  returns true whatever it answered.
- S 006745e0 `AddResourceAtCell` caps a cell at 7, so an amount above 8 can only come from a map file.
Spec text to change: `docs/sim/village-buildings.md` §3.8, replace "a cell with amount `n` gives `n − 1`
products to the mine linked to it [inferred from the two bodies]" by "a cell with amount `n` gives
`min(n, 8) − 1` products to the mine linked to it (1000 = unlimited) [known] S 00674650, S 00674e70,
S 0055c860, S 00565f80"; §10 Q10 can be closed. `docs/sim/map-resources.md` §3 (line "the cycle that takes the
last unit of a cell delivers nothing [inferred from S 00674e70]"): tag becomes [known].

### Ware delivered during an upgrade
Status: SETTLED
Answer: Yes, the double credit is real in the stocks. While the upgrade's construction still has work, one
delivered ware adds one unit to the upgrade site's stock and one unit to the building's own stock (input
stock, or output stock for a depot; the building's own construction site only if that still has work). Both
adds are unconditional. What the stock display shows was not read.
Evidence:
- S 0055aca0 `Depot::CollectGoods`: first `if (upgrade->bActive && (upgConstruction+0x70 > 0 ||
  upgConstruction+0x74 > 0)) Stock::AddOne(upgConstruction+0x10, good)`; execution then continues, picks the
  building's construction stock / `stockB` (depot) / `stockA` and calls `Stock::AddOne` again; then
  `NeedGoods::CancelRequest` once.
- S 00539de0 `Stock::AddOne`: `map[good] += 1; totalUnits += 1; changeStamp += 1; return true`, no condition.
- S 005671a0 `Upgrade::Start`: `operator_new(0x80)` + `Construction::ctor` into `upgrade->construction`, so
  the upgrade site is a different object from `building->construction`; the two adds go to two stocks.
- S 00651bc0 `NeedSystem::DeliverPackage` is the only caller and calls `CollectGoods` once per package.
Spec text to change: none in §3.19 (it already reads this way); `docs/sim/village-buildings.md` §10 Q8 can
be reduced to "what the stock display shows".

### `-nolobby` and the lobby button
Status: SETTLED
Answer: The click sets the request byte `nMenu::System +0xb4` to 1 and calls `PlayMusic(0)`; nothing else
happens. The byte is never consumed, because its only reader runs under `if (g_App.lobby != NULL)` and with
`-nolobby` the lobby pointer stays NULL for the whole run. `PlayMusic(0)` does nothing when track 0 is already
current (it restarts the menu track only if another one, for example the credits track 4, was playing). The
main menu has no `-nolobby` test: the button is neither hidden nor disabled.
Evidence:
- S 00403ac0 `ParseCommandLine`: `-nolobby` → `this->noLobby = true` (`+0xaa`).
- S 004075d0 `Initialize`: `LobbyManager_CreateInstance`, `LobbyAction::CreateInstance`, `Lobby_CreateInstance`
  and `this->lobby = …` are all inside `if (this->noLobby == false)`. Typed writers of `->lobby` in the whole
  decompile: ctor S 004039e0, `Initialize`, `Shutdown` S 00401cb0.
- S 005e27c0 `Main::HandleButtonClicks`, button key 1 (`BtLobby`): `System::RequestEnterLobby` S 005d98d0
  (`flagB4 = 1`), `PlayMusic(0)`, return.
- S 005d98e0 `ConsumeEnterLobbyRequest` has one caller, S 004018e0 `FrameTick_InGame`, inside
  `if (this->lobby != NULL)`. The field has three users in all (ctor S 005db1e0, setter, consumer).
- S 005d9f60 `PlayMusic`: `if (currentMusicIndex != idx) …`.
- S 005df8b0 `Main::SwitchPanel` tests `Lobby_GetInstance() == NULL` before using the lobby; S 005e0bb0
  registers `BtLobby` without any condition.
Spec text to change: `docs/sim/app-shell.md` §10 Q9: "settled statically: the click sets `System +0xb4` and
calls `PlayMusic(0)`; the flag's only reader is behind `lobby != NULL` (S 004018e0), so nothing follows".

### Closed row on a taken start position
Status: SETTLED
Answer: The later row's write wins, as the specification says, but the consequence is more specific than "one
is missing". A closed row always carries its own row index as start position (S 005e8410 sets it for every
row, S 005e8200 resets it on every type change, and the start button of a closed row is hidden). The world
then creates one player per `MapInfo` slot with kind != 0, at start position = slot index. For an active row
`a` that chose the position `c` of a closed row `c`:
- `a < c` (always the case for the human, row 0): slot `c` first gets row `a`'s data and is then overwritten
  by the closed row. Slot `a` is written only if another row chose position `a`; otherwise it keeps row `a`'s
  data. Result: nobody is missing, the player starts at position `a`, **the choice of the closed row's
  position has no effect**. If another active row chose position `a`, that row lands on `a` and player `a`
  is the one missing.
- `a > c`: slot `c` is closed first and then gets row `a`'s data, so the player starts at `c`. Slot `a` keeps
  row `a`'s data unless another row chose `a`: the same player (same name, colour, team, tribe, level) then
  exists twice, at positions `c` and `a`. The duplicate-colour test of the start button does not see this.
Choosing the position of another *active* row (a swap) works, because then every slot is written by exactly
one row. The session slot (`SetSlotSetup(i, …, p)`) still records the chosen position `p`, but player creation
does not read it.
Evidence:
- S 005e7350 `StartFreeGame`: first loop copies kind/tribe/colour/team/level/name of slots 0..5 into locals;
  second loop, for row i = 0..5 in order, reads `startPos = *(rowHqButton + 0x28)` and writes all six values
  into slot `startPos` of `this->setupDesc`, with no test of the row's kind.
- S 005e6e30 ctor: `setupDesc = loadDescriptor + 0x2c`.
- S 005e8200 `OnComboSelectionChanged`: on a `PlayerType` change of row > 0, `hqButton+0x28 = row`.
- S 005e6a70 `HasDuplicateStartPosition`: both loops skip slots with kind 0, so the start button stays
  enabled.
- S 005abb60 `Game_CreatePlayersFromDescriptor`: for map type 0 it reads kind, team, tribe, colour and name
  of slot `i` from `desc + 0x2c` for `i` = 0 .. start positions − 1 and calls `PlayerTable::CreatePlayer(i, …)`
  when kind != 0; the start building is placed at start position `i`.
- `PlayerTable_FindLocalPlayer` S 005bdda0 (spec, [known]): the local player is the first active slot of
  kind 2, i.e. slot 0 in the `a < c` case.
Spec text to change: `docs/sim/frontend-screens.md` §3.4, last paragraph of "Start": replace the [inferred]
sentence and the [TODO] by: "A closed row always has its own index as start position (S 005e8410,
S 005e8200), and the copy loop does not skip it [known] S 005e7350. So choosing the position of a closed row
never moves a lower row there (the closed row's write comes later; the player stays on the position of its
own row index if no other row chose that), and for a higher row it copies the player there while the slot of
its own row index keeps the same player (a duplicate) unless another row chose it. Only a swap with another
active row is carried out as shown. A reimplementation should write only rows with kind != 0 and clear the
slots no active row names." §10 Q1 can be closed as far as the outcome goes; what the duplicate looks like in
play is an observation, not an open rule.

### Info pages
Status: SETTLED
Answer: The info-page scripts (`scripts\info\i_*.lua`, `b_*.lua`) are never run. `nMenu::Info::Open` is not a
virtual function and has exactly one reference in the image, a direct call that passes mode 0; modes 1 and 2
(the only ones that build the two paths and call `GameScript_RunFile`) cannot be reached.
Evidence:
- Ghidra xrefs to S 005f6310: one, `UNCONDITIONAL_CALL` from S 005d9776; no data reference (no vftable or
  function-pointer slot holds the address).
- S 005d96e0 `System::ToggleDialogInfo`: `Info::Open(this->info, this->game, 0, slotIdx, infoId)`, the mode
  argument is the literal 0. Its only reference is the call at S 005d9797 (`ToggleDialogInfoDefault`), whose
  only reference is the call at S 0062e260 in `nMenu::Overlapped::Update`.
- S 005f6310: `if (mode == 0) …` shows the text key; the two `GameScript_RunFile` calls sit in the
  `mode == 1` and `mode == 2` branches only.
Spec text to change: `docs/sim/lua-runtime.md` §6.1 row "Info pages": replace the [TODO] by "modes 1 and 2
are unreachable [known: S 005f6310 has one code reference and no data reference]"; §10 Q4 can be closed.

### Time of day
Status: SETTLED
Answer: The hour does not run. `CEnviromentMgr +0xfc` (hour, float) has three writers: the constructor
(= `localtime` of the environment XML, default 10), `Update`, which pins it to that same value every frame
while the scene is not "animated" and does not touch it otherwise, and the setter in vftable slot 8, which
has no direct caller and no caller through a typed virtual call. Nothing adds to the hour and nothing reads
the time scale `+0xf8`. This agrees with the live result of today (no `GetDaytime` call in 2,843 frames; the
maintainer sees no change). The heading of every day-time key equals its elevation when the keys come from
`daytimes.xml`: the loader asks for the attribute `lighteeading` with the same output variable it has just
filled from `lightelevation`.
Evidence:
- S 00683d50 `CEnviromentMgr::Update`: `if (!animated) timeOfDayHours = (float)g_Env_LocalTime;` and no other
  write of the field.
- S 00685070 ctor: `timeOfDayHours = (float)g_Env_LocalTime`. S 00684be0 `Env_ParseEnvironmentXml`:
  `GetAttrInt("localtime", &g_Env_LocalTime)`, else 10.
- S 00683fd0 `SetTimeOfDay(hour, timeScale)`: `timeOfDayHours = hour % 24`; vftable S 007f9358 slot 8;
  0 callers. `timeScale` is written by the ctor and this setter and read nowhere.
- S 00684130 `LoadDaytimes`: `GetAttrInt(node, "lightelevation", &tmpInt); key[6] = tmpInt;
  GetAttrInt(node, "lighteeading", &tmpInt); key[7] = tmpInt;` and S 006e7b20 `GetAttrInt` leaves `*out`
  untouched when the attribute is absent. `daytimes.xml` spells the attribute `lightheading`.
- Limit: a call of slot 8 through an untyped pointer would not show in the decompile; none was found.
Spec text to change: `docs/sim/rendering.md` §10 Q11: "the hour does not run: no code adds to
`CEnviromentMgr +0xfc` (writers S 00685070, S 00683d50, S 00683fd0)"; §10 Q17 and the tag in §6.6
("inferred for the consequence") become [known] for the XML path.

### Chest claim result
Status: SETTLED
Answer: A `ClaimChestResult` (0xDAE) has no effect in the client beyond the log line. The two observer lists
it notifies, `RefereeServerConnection +0x38` (claim ok) and `+0x44` (claim failed), never get a subscriber, so
there is no HUD message and no sound from the result.
Evidence:
- S 0047a160 `ClaimChestResultReceived`: logs, then `ObserverList_NotifyAll3` on `+0x38` or `+0x44`; no
  other state change.
- `ObserverList::Subscribe` S 00458860 is the only subscribe function of the image. The list argument of every
  call was enumerated in the decompile: the referee connection gets subscribers on `+0x04`, `+0x10`, `+0x50`,
  `+0x5c`, `+0x80`, `+0x8c` (S 004351a0 `WorldScreen::Activate`) and on the two give-up lists (S 00600760),
  nothing else.
- The referee connection is embedded at `LobbyManager +0x490` (S 004624f0); the 12 callers of that accessor
  and the `LobbyManager` methods that use the member do not touch `+0x38` / `+0x44`, and no function uses
  the absolute offsets `LM +0x4c8` / `+0x4d4` on the manager.
- The typed fields `claimChestOkObservers` / `claimChestFailedObservers` are used by ctor S 004792a0, dtor
  S 00479230 and the handler only.
Spec text to change: `docs/sim/quests-sacrifices-stats.md` §10 Q3: "settled: the lists `+0x38` / `+0x44` have
no subscriber (every `ObserverList::Subscribe` S 00458860 call enumerated); the result only writes the log
line".

### Shop result and inventory lists
Status: SETTLED
Answer: The subscriber count of `VSC +0xd4`, `+0x134` and `+0x140` is 0 at all times: the client reacts to
none of the three notifications. (How the shop and the inventory are refreshed then, i.e. which code polls
the avatar proxy, was not read.)
Evidence:
- Every call of `ObserverList::Subscribe` S 00458860 was enumerated with its list argument. The village
  connection gets subscribers in S 00503d00 `CLobbyClient::SubscribeVillageConnection` (`+0x10`, `+0x1c`,
  `+0x28`, `+0x38`, `+0x44`, `+0x50`, `+0x5c`, `+0x68`, `+0x74`, `+0x80`, `+0xa4`, `+0xb0`, `+0xbc`, `+0xc8`,
  `+0xe0`, `+0x104`, `+0x110`, `+0x11c`) and in S 004351a0 `WorldScreen::Activate` (`+0x1c`, `+0x28`, `+0x8c`,
  `+0x98`). No call names `+0xd4`, `+0x134` or `+0x140`; the shop dialog (S 0045d180) and the selection-info
  dialog (S 0044ebe0, S 0044ed80) subscribe to their own slot widgets only.
- S 00470990 `HandleShopBuyResult` and S 00470a10 `HandleShopSellResult` notify `this+0x134` / `this+0x140`.
- Limit: a list filled by code other than `Subscribe` would not be seen; the image has no second subscribe
  function.
Spec text to change: `docs/sim/lobby-client-state.md` §10 Q3 and `docs/sim/lobby-screens.md` §10 Q4: "settled:
no `Subscribe` call for these lists exists (all calls of S 00458860 enumerated)".

### Garrison slider during an attack order
Status: SETTLED (for the question "terminates or goes on"; how to reach index −1 in play was not re-read)
Answer: The process terminates. `Soldiers::GetSoldierObject` with index −1 always fails its bounds check
(unsigned compare), which calls the CRT invalid-parameter routine; the image never installs a handler, so the
routine goes to `__invoke_watson`, which ends in `TerminateProcess(current, 0xC000000D)`. The read of the
entry before the vector is never executed.
Evidence:
- S 00566140: `if (begin == NULL || (uint)(end − begin >> 2) <= index) _invalid_parameter_noinfo();`.
- S 006f2702 → S 006f26de `_invalid_parameter`: `h = _decode_pointer(DAT_0088f5c0); if (h) jump h;
  else __invoke_watson(…)` (does not return).
- Ghidra xrefs to S 0088f5c0: one read (S 006f26e1) and one write, S 006f25dc, the CRT initialiser called
  from `__init_pointers` S 006f9cbd with `__encoded_null()`. The image has no `_set_invalid_parameter_handler`.
- S 006f25e2 `__invoke_watson`: `SetUnhandledExceptionFilter(NULL); UnhandledExceptionFilter(…);
  TerminateProcess(GetCurrentProcess(), 0xc000000d)`. Because the filter is reset first, the game's own crash
  handler is not the one that runs.
- S 00574a00 `Allocation::Update` passes the result of `FindWeakestSoldier(true)` S 00566220 (−1 when no
  soldier qualifies) straight into `GetSoldierObject`.
- The same holds for all 2,521 call sites of `_invalid_parameter_noinfo` (every checked vector and string
  access of the game): a failed check ends the process, it never "returns and reads on".
Spec text to change: `docs/sim/military.md` §3.2: replace "calls the CRT invalid-parameter handler and, if
that returns, reads the entry before the vector" by "calls the CRT invalid-parameter routine, which ends the
process with exit code 0xC000000D (no handler is installed: S 0088f5c0 is written only by the CRT start-up)";
§10 Q4 keeps only "can the state be reached from the garrison slider".

---

### Debug icons
Status: STILL NEEDS LIVE
Answer: Half settled. Slot 10 of the `nUi::Icon` vftable is the class's own `Hide` (S 004cf210), which clears
the tooltip and then calls `nUi::Object::Hide` (S 004a1130, `visible = false`): the five icons are hidden
right after their creation. Not settled: whether anything shows them again.
Evidence: vftable at S 007e26ec (slot 0 = scalar deleting destructor S 004cec70); S 007e2714 = slot 10 holds
S 004cf210 (its only reference).
Blocked by: the visible byte is also written by the show paths that walk a widget tree through virtual calls
(`SetVisible` S 004a1090 notifies children through vtbl+0x70, fades, a parent shown again after a cinematic);
which of them reach children of the HUD root cannot be listed from the decompile.
Spec text to change: `docs/sim/camera-input-cutscenes.md` §3.13: "[inferred that `nUi::Icon` keeps that slot]"
becomes "[known: slot 10 of the `nUi::Icon` vftable S 007e26ec is `Icon::Hide` S 004cf210, which ends in
`Object::Hide`]".

### Extra mouse button as forward key
Status: STILL NEEDS LIVE
Answer: Not decided. `IsMoveForwardDown` S 004295c0 asks the lobby action for key 5 with source 2
(`pressedThisFrame[5]`, S 00490ff0), outside the text-focus guard. That array is written only by the
action's `OnKeyEvent` (S 00490f50 through S 00429430). The window handler S 00401f30 turns `WM_XBUTTONDOWN`
with button 1 into `OnKeyEvent(5, 1)` on `g_pGameAction` (S 00885a00), which is a different object from the
lobby action (`g_pLobbyAction` S 008857b8), and into root event (0, 3, 0).
Blocked by: the lobby action receives mouse buttons through `CLobby::OnMouseButtonDown` S 004f4fd0 (slot 20
of vftable S 007e599c, no direct caller). Who calls that slot and with which button code (3 or 5) for the
first extra button was not resolved.
Spec text to change: none.

### Second own ship to an occupied exit
Status: STILL NEEDS LIVE
Answer: The null write itself is certain: `NavyLink_LinkMovementDocking` S 0053c2d0 passes
`FindDockingPositionForShip(...) + 8` to `Reference_SetTarget` S 0053a540 without a test, and S 005bc060
returns NULL as soon as one occupied dock of the exit belongs to the same player. Not decided: whether play
can produce the situation. `NNavy::Military::Update` S 005ba250 sends the ship along its **own** route
(`movement->route`), and the specification says a player can have one ship per route (block code 4), so the
set-up named in the queue (ferry docked, sea attack through the same harbour) may involve one ship only.
Blocked by: the preconditions of the five callers of `Movement::MoveToHarbor` S 005b97f0 (S 005b8ac0,
S 005b9990, S 005ba250, S 005bab60, S 005bb500) and the rule that picks the ship of a sea attack were not
read to the end; a ship without a route (S 005bab60 `ReturnToOwnHarbor`) is the most likely way in.
Spec text to change: none.

### Game server connection
Status: STILL NEEDS LIVE
Answer: Unchanged. `GameServerConnection::Initialize` S 0048eda0 and `OnLoggedIn` S 0048edf0 have one
reference each, both data references from the vftable (S 007deaf4, S 007deb04); no direct call exists.
Blocked by: a call through the vftable slot cannot be excluded statically.
Spec text to change: none.

### What starts observing
Status: STILL NEEDS LIVE
Answer: Unchanged. `SetObserving` S 005238e0 has four references, all data references from vftables
(S 007e71b4, S 007e7200, S 007e7240, S 007e777c); no direct call exists.
Blocked by: the caller is a virtual call through slot 4 of the table client; finding it means resolving every
`call [reg+0x10]` on a table-client pointer.
Spec text to change: none.

---

# Second pass (2026-10-12): reachability questions and three more entries

Spec corrections of both passes are applied in `docs/sim/` (list at the end).
Second pass: 6 entries examined, of them 2 re-examined from the first pass. SETTLED 3 (one of them the
re-examined garrison entry), STILL NEEDS LIVE 3.

### Garrison slider during an attack order (reachability)
Status: SETTLED
Answer: Play can reach index −1, and the process then ends (first pass). The state is: every soldier still in
the building is bound to a fight, the building wants fewer soldiers than it has, `cooldownTicks == 0`, and an
allocation pass runs. Soldiers picked for an attack are bound at once and stay inside in state 0xc while the
fight's start countdown runs (10 ticks, `mi_setWaitForTacticTime(10)`); a building in full reach sends all its
available soldiers at fraction 1.0. The allocation pass runs every 21 ticks, so with the slider lowered
(surplus not yet dismissed, one soldier per pass) and a full-strength attack ordered from that building, a
pass falls into the 10-tick window in roughly one of two attempts. After the countdown the window is closed
in practice: waiting soldiers (state 0xf) take the cooldown slot in the settler update, which runs before the
military update of the same tick.
Evidence:
- S 00574a00 `Allocation::Update`: building eligible when not a depot, finished, and not itself the target
  of a fight; `deficit = wanted − garrison − pending`; for `deficit < 0` the loop keeps every soldier for
  which `IsPresentInBuilding(s, ignoreFight = true)` holds, then, if `deficit < 0 && cooldownTicks == 0`,
  calls `FindWeakestSoldier(true)` and passes the result to `GetSoldierObject` unchecked.
- S 00566220 `FindWeakestSoldier(presentOnly)`: uses `IsPresentInBuilding(s, false)`; returns −1 when no
  soldier passes. S 00658f90: with `ignoreFight == false` a soldier whose `SoldierFightState::IsInFight`
  S 005660e0 is true (valid fight reference) does not pass.
- S 005751e0 `AssignBestSoldiers`: `LinkToFight` on each chosen soldier while he is in the building.
  S 00575dc0 `GetAvailableAttackers` counts every soldier that is `IsAvailableInBuilding` (state 0xc, present,
  not in a fight); `StartAttack` S 00576500 sends `trunc(n * fraction + 0.5)`.
- S 006594a0 `Soldier::Update`, state 0xc: a bound soldier goes to 0xf only when the fight's `+0x24`
  (`startCountdown`) is 0; state 0xf: leaves when the home's `cooldownTicks == 0` and sets it to 10.
- `military.lua`: `mi_setWaitForTacticTime(10)`. `Allocation::Update` re-arms `updateCountdown = 0x14`.
- Limit: the coincidence (pass inside the window) is timing; it was not observed.
Spec text changed: `docs/sim/military.md` §3.2 (reachability sentence added), §10 Q4.

### Second own ship to an occupied exit (the five callers)
Status: STILL NEEDS LIVE (the queue's own set-up is settled: it cannot produce the crash)
Answer: "Ferry docked, then a sea attack through the same harbour" does not send a second ship. When the
attacker already has a ship on the attack route, `SendSoldiersBySea` returns without sending anything unless
that ship's military mission is this very fight; only when the route has no ship of his does it link an idle
ship. So there is neither a crash nor a waiting ship: the building's soldiers are simply not sent by sea.
All five callers of `MoveToHarbor` send a ship to an end of its own route, and a route takes one ship per
player, so the null write needs an own ship that is docked at an exit without being on that exit's route.
Evidence:
- S 00575510 `SendSoldiersBySea`: `if (route->HasPlayerEntry(attacker)) { ship = entry; if
  (!ship->military->bActive) return; if (ship->military->fight != this->fight) return; } else { ship =
  FindNearestIdleShipAtHarborExit(...); if (!ship) return; link route and fight }`.
- S 005ba250 `Military::Update` states 0 and 3, S 005b9990 `SailToOppositeRouteEnd`, S 005b8ac0
  `Expedition::Update` states 0, 3, 7, S 005bb500 `Ship::Update` state 1: target = an end harbour of
  `movement->route`.
- S 005bab60 `ReturnToOwnHarbor`: harbour from `FindNearestHomeHarborForShip` S 005b6370, route from
  `FindOwnRouteForShip` S 005b4c50, which requires `CanPlayerAssignShip` S 005b6d30 (no ship of the player
  on the route yet).
- S 005b97f0 `MoveToHarbor` unlinks the ship's old docking position before it asks for a new one, so a ship
  never blocks itself.
Blocked by: whether a ship keeps its docking reference when it is taken off a route by the loss of the
harbour at the other end (`NavyLink_UnlinkMovementRoute`, S 005b5370) was not read; if it does, a second
own ship that joins the route later and sails to that exit hits the null write.
Spec text changed: `docs/sim/navy.md` §10 Q3 (narrowed).

### Defence fraction of an attacked computer player
Status: SETTLED
Answer: `DispatchDefenders` always gets the player setting (`NPlayer::Military +0x1c`), never the value the
AI computes. The AI's value is written while `StartAttack` links the new fight to its target, and the very
next statement of `StartAttack` overwrites the field. Every fight is created in `StartAttack`, the field has
no third writer, and it is read once, when the start countdown reaches 0.
Evidence:
- S 00576500 `StartAttack`: `CreateFight`; `MilitaryLink_LinkFightToTargetBuilding(target, fight)`;
  `target->military[+0x64] = target->owner[+0x4c][+0x1c]`; then the attackers are dispatched.
- S 0053cf50 → S 00570760 `Fight::SetTargetBuilding` (adds the watch only while `defenderPlayer == −1`) →
  S 0053be90 → S 00585cd0 `AddAttackWatch` → S 0059b3f0, which writes `target->military[+0x64]`; S 0059b3f0
  has this one caller.
- S 00573c30 `FightList::CreateFight`: one caller, S 00576500. The second caller of the link, S 0055a210
  `TransferBuildingOwnership`, re-links an existing fight.
- S 005715a0 `Fight::Update`: reads `+0x64` when `startCountdown` reaches 0 and passes it to
  `DispatchDefenders`. No other function of the decompile touches the field.
Spec text changed: `docs/sim/ai-player.md` §3.13 (tag and chain), §10 Q2.

### Mines without food
Status: SETTLED
Answer: As expected. With start resources "high" (`Player.state == 0`) the mines of a human player need no
food, request none and run as long as a resource cell is linked; a computer player's mines need food at
"high", "medium" and "low" and would run without only at level 3. With "medium" a human's mines need food.
The sacrifice flag `MinerNeedNoFood` switches the need off for its owner whatever the level.
Evidence:
- S 005be330 `Player_IsStateNotDefault`: kind (+8) 1 → `state(+0xec) != 3`, else `state != 0`.
- S 00565bd0 `CanStartProduction`, mine branch: returns false only if the input stock is below the first
  recipe amount **and** `MinersNeedFood` **and** `Player_IsStateNotDefault(owner)`; otherwise
  `fieldConnection != −1`.
- S 005657c0 `StartProductionCycle`: a mine removes its inputs only under the same two conditions.
  S 00565a70 `RequestAllInputs`: a mine files requests only when `Player_IsStateNotDefault(owner)`.
- S 005bea90 `Player::Init`: `this->state = state`; S 005abb60 passes the descriptor's `+0x20`
  (start resources, 0 high / 1 medium / 2 low: `frontend-screens.md` §3.4) to `CreatePlayer` for every slot.
  Typed writers of `+0xec` besides `Init`: the constructor.
Spec text changed: `docs/sim/village-buildings.md` §3.8 (tag), §10 Q1; `docs/sim/players-victory.md` §10 Q4.

### Door direction and levelling
Status: STILL NEEDS LIVE
Answer: Only the `cfg_setBulldozeTime` part was examined. `GameConfig +0x14` is written by the Lua setter
S 0054c470 (through S 005554b0); of the 67 decompiled functions that touch `PropertiesDb.gameConfig`, the
`cfg_set*` setters (and the database constructor, destructor and clear) are the only ones that keep the pointer, and every other use reads a fixed offset
(0, 4, 8, 0xc, 0x10, 0x18 .. 0x5c), none of them +0x14.
Blocked by: a reader that gets the block through an untyped helper would not show in this search; the door
direction and the builder's phases are a matter of the screen.
Spec text to change: none.

### Top-up maximum
Status: STILL NEEDS LIVE
Answer: The formula is as the specification has it (S 00461470: `available = avatar money (+0xd0, or +0xd4
for play money) − seat accnt`, default stake `min(10 × minimum, available)`).
Blocked by: the outcome depends on the `accnt` the server sends and on what the dialog does with a maximum
of 0, which was not read.
Spec text to change: none.

---

## Spec files and sections changed (both passes)

- `village-buildings.md`: §3.8 (products per cell; tag of the food rule), §10 Q1, Q8, Q10.
- `map-resources.md`: mines paragraph ("the cycle that takes the last unit").
- `military.md`: §3.2 (invalid-parameter outcome; reachability of index −1), §10 Q4.
- `lan-and-transport.md`: `GetUserPing` paragraph (the failed check ends the process).
- `tribes-content.md`: lookup of an id without a record (ends the program, [known]).
- `app-shell.md`: §10 Q9.
- `frontend-screens.md`: §3.4 "Start" (closed rows), §10 Q1.
- `lua-runtime.md`: §6.1 row "Info pages", §10 Q4.
- `rendering.md`: §6.6 (tag), §10 Q11, Q17.
- `quests-sacrifices-stats.md`: §3.4 (chest result lists), §10 Q3.
- `lobby-client-state.md`: §10 Q3.
- `lobby-screens.md`: open point 4 "Shop results".
- `ai-player.md`: §3.13 (defence fraction), §10 Q2.
- `navy.md`: §10 Q3.
- `players-victory.md`: §10 Q4.

---

# Third pass, batch 1 (2026-10-12)

14 entries: 12 SETTLED (two of them re-examined: second own ship, debug icons), 1 unchanged (already settled in
the document it belongs to), 1 STILL NEEDS LIVE. Entries of the hand-written sections point at documents
outside `docs/sim/`; for those the wording is given under "Spec text to change" and nothing was edited.

Note on method: the field searches of the first two passes were repeated with a corrected filter (the first
version dropped indented code lines from the listing, not from the match); every conclusion held.

### Second own ship to an occupied exit (final)
Status: SETTLED
Answer: The null write is not reachable through the game's own rules, so there is no in-game recipe. A ship
does not keep its docking reference when it leaves a route: `Movement::ClearRoute` releases the docking
position whenever a target harbour is referenced, and every way off a route goes through it. A route takes
one ship per player on every path that adds one. Every `MoveToHarbor` goes to an end of the ship's own route.
So an exit can hold a docking reference of an own ship only when that ship is the mover itself, which has
released it before it asks again. With two docking positions per exit (all shipped data) and at most the two
end owners on a route, "both docks taken by others" does not arise either.
Evidence:
- S 0053c3f0 `NavyLink_UnlinkMovementRoute`, S 0053c040 `NavyLink_UnlinkExpeditionRoute`, S 0053c100
  `NavyLink_UnlinkMilitaryRoute`: each calls `Movement::ClearRoute` S 005b9340, which clears the route
  reference and, if `targetHarbor` is valid, calls `NavyLink_UnlinkMovementDocking` S 0053c300.
- Harbour loss: S 005b5370 `Harbor::DetachFlag` → S 005bc1c0 undocks the owner's ships at this harbour and
  calls `NavyShipRoute::UnlinkMovementsOfPlayer` S 005b7050, which takes every ship of that player off the
  route (and so releases a dock held at the other end).
- Adding a ship to a route: S 005bab60 (`FindOwnRouteForShip` S 005b4c50 → `CanPlayerAssignShip` S 005b6d30),
  S 005ba720 and S 00575510 (`FindNearestIdleShipAtHarborExit` S 005b3450, which starts with
  `CanPlayerAssignShip`; S 00575510 also tests `HasPlayerEntry` S 005b6bb0), S 005b7c30 `Expedition::Finish`
  (re-adds the same ship it has just removed). All entries live in one vector (`AddMovementRef` S 005b73a0).
- `TransferShipsOfPlayer` S 005b44e0 creates new ships (`CreateShip` S 005b42f0), without route or dock.
- Limits: a save edited by hand; data with fewer than two docking positions per exit.
Spec text changed: `docs/sim/navy.md` §3.1 rule 3, §10 Q3.

### Debug icons (final)
Status: SETTLED
Answer: Hidden for the whole match. Slot 10 of the `nUi::Icon` vftable is `Icon::Hide`, and nothing can show
the icons again: a widget's visible byte has four writers (constructor and attach set it, `SetVisible` sets
it for the widget it is called on, `Hide` clears it); showing a parent does not write a child's byte; no loop
over a widget's children calls `SetVisible` or a fade-in; the five icon members are used by the screen's
constructor, destructor, `SetupHud` and `DestroyHudWidgets` only.
Evidence: vftable S 007e26ec slot 10 = S 004cf210 → S 004a1130; writers of `+0x14d`: S 004a3cc0, S 004a56d0,
S 004a1090, S 004a1130 (typed and raw search of the decompile); S 004a1230 `OnParentShown` only sets
`layoutDirty` and recurses; S 004c3d50 `nUi_FadeInObject` calls `SetVisible(1)` on its own argument only.
Limit: a call through a pointer the decompile does not type.
Spec text changed: `docs/sim/camera-input-cutscenes.md` §3.13, §10 Q1.

### E-mail change (88)
Status: SETTLED
Answer: The client sends ChangeUser with `property_mask` 8, `active` 1, `banned` 0, no name, no password
(no `cipher` field) and no data blocks; the mail string is the only content. There is one call site.
Evidence:
- S 00476390 `CharacterManager::ProcessActions`, case `UpdateEMail`: `pUserComm->vtbl[+0x20](userId, 0, 0,
  email, 0, 1, 0, 0, 8)`. It is the only use of slot `+0x20` of the user interface in the client (all uses of
  `pUserComm`: S 00472b30, S 00472f00, S 00473460, S 00476390).
- tincat3 vftable T 1005152c slot 8 = T 1002ed80 `UserManager::ChangeUser(userId, name, password, mail,
  banned, active, dataParts, dataSizes, propertyMask)`: writes `user_id`, name, mail, `cipher` only when a
  password is given, `banned`, `active`, `data` (0x18 zero bytes when no blocks), `property_mask`,
  `ticket_id`.
- Not read: how the string writer encodes the NULL name (empty or absent).
Spec text to change: `docs/message-catalog.md` 0x058 and T43: "[inferred]" → "[known] S 00476390: the one
call passes mask 8, active 1, banned 0, name and password NULL, no data".

### ChangeCharacter (90) is unused
Status: SETTLED
Answer: The client never sends 90. The tincat3 sender is slot 7 (`+0x1c`) of the character interface; the
client holds that interface in one place and calls slots `+0x04`, `+0x08`, `+0x0c`, `+0x10`, `+0x14` and
`+0x20` only. Inside tincat3 the sender has no caller.
Evidence:
- T 10016550: one reference, the vftable entry T 1004e94c = T 1004e930 + 0x1c.
- The client gets the interface once (`CommLayer` slot `+0x0c` in `LobbyManager::StatePump_Tick` S 00464ee0)
  and stores it in `CharacterManager.pCharacterComm`; all uses of that field: S 00473460 (`+0x04`),
  S 00472b30 (`+0x08`), S 00476390 (`+0x0c`, `+0x10`, `+0x14`, `+0x20`), S 00472f00 and the constructor
  (null tests).
Spec text to change: `docs/message-catalog.md` 0x05A and T49: "no SADK caller found ... [inferred]" →
"[known]: slot `+0x1c` of the character interface is not called by the client (uses of
`CharacterManager.pCharacterComm`: S 00473460, S 00472b30, S 00476390)".

### Mail `creation_time`
Status: SETTLED
Answer: The field is unused. `Mail +0x2c` is written by the constructors, the assignment and the update from a
record, and read only to copy it into another `Mail`. No function of the mail and post-office classes (61
functions) reads offset `+0x2c` of a mail in any other way; nothing displays or compares it.
Evidence: users of `creationTime`: S 0048ca80, S 0048cb70, S 0048cc60, S 0048ced0, S 0048cce0. The two raw
`+0x2c` hits in those classes are a vftable slot of the mail dialog (S 004509d0) and a list of the post office
(S 0047e590).
Spec text to change: `docs/message-catalog.md` T15: "no reader found [inferred]" → "[known]"; the unit stays
unknowable from the client.

### Own whisper echo
Status: SETTLED
Answer: The own line does not appear when the target's name is not in the name cache. The whisper itself is
sent (the name is resolved to an id by `LookUpID` first), but neither the lookup nor the send puts the name
into the id → name cache; only avatar data, a public chat line and an incoming whisper from that player do.
The send path prints nothing locally. A buddy who is not in the same zone and has not written anything counts
as "not cached" too.
Evidence:
- S 004810a0 `PrivateChatReceived`: for `from_id == local perm id` it calls `TryGetCachedName(to_id)`
  S 00472cf0 and notifies the list `+0x54` only when that returns true.
- Callers of `CacheUserName` S 004780c0: S 0046e1d0 `HandleAvatarData`, S 00480e30 `ChatReceived`, S 004810a0
  (the other branch). The name cache `+0x1a0` has no other writer.
- S 004808a0 `QueuePrivateMessage` / S 00480630 `Process` / S 00480340 (lookup callback): store the id and
  send 30; S 00473590 `CharacterDataReceived` passes the result to the callback without caching.
- S 00436860 `SendChatInput`, whisper case: only `QueuePrivateMessage`.
Spec text to change: `docs/types.md` §1.5 `+0x54`: already [known]; add "the lookup that precedes the send
does not fill the cache (S 00473590, S 00480340)".

### ItemsClient.txt tokens 3 and 4
Status: unchanged (already settled statically in `docs/village-and-character-protocol.md` §4.3)
Answer: Token 3 (`ItemInfo +0x3c`) is stored and copied and has no reader; token 4 (`+0x44`) is read in one
place, `ItemInfo::IsValid` S 0048b100. A read watch can only confirm this.
Evidence: users of the two fields: S 0048b120, S 0048b200, S 0048b2e0, S 0048bfd0 (loader), S 0048b100.

### Unknown item id (part b: hover with a shop open)
Status: SETTLED
Answer: It ends the process. For an id that is neither in the open shop's stock nor a valid item of
`ItemsClient.txt`, `GetShopSellPriceByItemId` falls through to the stock-entry read with the iterator at the
end, the bounds check fails and the invalid-parameter routine terminates the process (exit code 0xC000000D;
no handler is installed, see "Garrison slider"). The trigger is hovering such a slot while a shop is open
(`SelectionInfoDialog::OnHoverSlot` S 0044d550 is the only caller). Part (a), how the id renders on an avatar,
was not read.
Evidence: S 0046d6d0: `if (entry == end) { info = GetItemInfo(id); if (IsValid(info)) return base * SellMod; }
... if (end <= entry) _invalid_parameter_noinfo(); return entry[2];`. The sibling S 0046d800 (sell, drop on
the shop) returns the base-value price without the validity test and cannot fail this way.
Spec text to change: `docs/message-catalog.md` V23: "whether that ends the process is [TODO]" → "it ends the
process (exit code 0xC000000D) [known]".

### Timer precision after a long uptime
Status: SETTLED (the precision; what the readers look like is an observation)
Answer: The value steps by `2^(floor(log2 seconds) − 23)` seconds of counter time: 2 ms after 4.6 h, 7.8 ms
after 18 h, 15.6 ms after 36 h, 31 ms after 3 days, 62 ms after 6 days. From about 3 days on, consecutive 60 Hz
frames can return the same value.
Evidence: S 0057b8a0: `(float)(u32 ms) / 1000.0`; S 0057b790 / `Timer_QpcMilliseconds`: the source is
`QueryPerformanceCounter / (frequency / 1000)`, low 32 bits, nothing subtracted; S 0057b9b0 sets 24-bit
precision control, so the quotient is single precision. Frame deltas (S 0057b850) are integer milliseconds and
not affected.
Spec text changed: `docs/sim/app-shell.md` §3.4, §10 Q10.

### File name with an upper-case umlaut
Status: SETTLED (the locale question of `engine-core.md` Q3)
Answer: No locale object leaves a non-"C" locale active. `std::_Locinfo` saves the locale name in its
constructor and sets it again in its destructor, and it lives only inside a facet constructor. Besides it,
`nUi::Text::SetText` is the only caller of `setlocale` and restores the locale as well. So the file index and
the name keys are lower-cased under "C" on both sides of a lookup: a map `MÄP` keeps its `Ä` in the key and
in the looked-up name alike. Whether the list shows and loads it was not followed further.
Evidence: callers of `_setlocale` S 006f9161: S 004b3fe0, S 006f1938 (`_Locinfo_ctor`), S 006f17d9
(`_Locinfo_dtor`); S 00403fe0 has five callers, all facet constructors.
Spec text changed: `docs/sim/engine-core.md` §3.6, §10 Q3.

### Map with a script
Status: SETTLED (that the script runs; its effect on a match is live)
Answer: The script runs in a network session, on every peer that has `<map>.lua` next to its copy of the map.
The loader has no session test and the map-script thread is created in every session; only the registration
of the `logic` and `gfx` tables is limited to offline sessions, so in a network session those tables are
missing or left over from an earlier offline world of the same process.
Evidence: S 005aa7b0 `GameFile_LoadMap` builds the path (extension → `.lua`) and calls S 005b1fe0
`GameScript_LoadMapScript`, which runs the file when it exists; S 00784d40 `BuildWorld`:
`GameScript_InitMapScript()` unconditionally, `GameScript_RegisterLuaLibraries()` only when
`NComm_Manager_IsRole0`.
Spec text changed: `docs/sim/lua-runtime.md` §10 Q6.

### Speed button
Status: SETTLED
Answer: The button is there and works in a network match. It is `btSpeed` (hotkey `v`) of `menuingame.xml`,
the only layout of the game screen; no code hides it, and the click test that sends `0x20023` has no net-mode
condition. Every peer then stores the new speed (first pass of the specification, `game-commands.md`).
Evidence: `nMenu::Game +0x4a80`: S 005ee5d0 (constructor), S 005ed700 (create), S 005ea650 (destroy),
S 005efea0 (shows `x2` / `x3`, reads the click, calls S 00782950).
Spec text changed: `docs/sim/game-commands.md` §3.4 (`0x20023`), §10 row.

### What a desync does
Status: SETTLED
Answer: A notice, a log line and an optional dump; nothing else. The match is not aborted and nothing is sent
to the peers or to the server. In a match the notice is a letter to the local player (the game screen's
message sink turns all three sink slots into a letter).
Evidence: S 00411990 `AdvanceNetTick`: `bInSync = VerifyLatest(...)`; on true → false: `NotifyObservers_Slot1`
S 0040e3a0 (sink `+0x3c4` slot 1, list `+0x3e0`), `Logger::LogMessage`, `NComm_WriteDesyncDump` S 0041f5e0
(writes `Desync.s2dump.txt` only when the log level global is above 1). `bInSync` is read only there (the
other three users write false: S 004093a0, S 0040b270, S 0040b700). The list `+0x3e0` is used by the
destructor and the notifier only. Sink in a match: `nMenu::Game +0x1c4`, vftable S 007eec00, all slots
S 005eb120 → `PlayerMessages_SendLetterToPlayer`.
Spec text changed: `docs/sim/logic-core.md` §10 Q3.

### Ini files behind a byte order mark
Status: STILL NEEDS LIVE
Blocked by: the outcome is decided by `GetPrivateProfileIntA` of the operating system, not by client code.
(`CLAUDE.md` lists 5479 as a hosting client's game port, which is the fallback value.)

---

# Third pass, interlude (2026-10-12): corrections from the unattended live run and one new question

Applied to the specifications after reading the cited code (live numbers: `docs/live-checks/2026-10-12_unattended-run.md`).

- **Animal idle time** (`map-resources.md` §3.10 state 2, property row `+0x4c`, §10 Q3). Verified in the bytes
  of S 0054231f..0054235e: `fild tick; fld 10.0; fdiv st1,st0; fld timeStamp; fsubp st2; fxch; fstp/fld
  float32; fmul [property+0x4c]; fmulp (by the 10.0); ftol; mov [animal+0x8c]`. The decompile shows only the
  subtraction.
- **Ferry hold and wait** (`navy.md` §3.7 timing note, §3.9, §10 Q9, Q12). Phase test verified in S 005bd4e0
  (`(tick + ship id) % 3 != 0` → return true); `ship.lua` sets `sh_setWaitTime(15)`, `sh_setStockLimit(12)`.
- **Listener** (`audio.md` §3.2, §10 Q2). Verified: vftable S 00835294 slots 2 / 3 = S 00784f70 / S 00784f90
  (`eye`, `eye + lookDir`).
- **Camera** (`camera-input-cutscenes.md` §2.1 `zoomMax`, §3.1, §3.2, §10 Q2). `zoomMax` has two users in
  the game, the constructor (S 007876e0, `fld [S 007d6980]` = 4.0) and the read in `OnWheelDown` S 00786a10;
  no ini key, Lua binding or XML attribute writes it. Read-only reads of the running process (same session,
  nothing called or written): the constructor bytes and the constant are unchanged (4.0), and the loaded
  modules outside the Windows folder are the game's own, this project's mods, the PhysX and RivaTuner
  libraries and a `d3d9.dll` of 94 KB in the game's `bin` folder. So the 6.0 is written at run time by a
  module that is not the game's; the `d3d9.dll` proxy (the widescreen fix) is the candidate `[inferred]`. A
  write watch on `Camera +0x1c` during a world build would name the writer.
- **Movement and blocked flag** (`settlers-jobs.md` movie timer, §3.8.1, §3.6.2, §10 Q2, Q5). Why a carrier
  in state 1 has no 360 limit: `IsFlagFullWaitExceeded` S 0077a0c0 has one caller, the street loop
  `Carrier::UpdateStreetTransport` S 0065b200; a carrier that is not yet on a street runs
  `UpdateDropOffAfterSpawn` S 0065ad70, whose state 1 calls the flag test on every tick with no test of the
  counter. Which step produces a street carrier's initial run of per-tick attempts was not found (`[TODO]` in
  the spec).
- **Double credit** (`village-buildings.md` §3.19, §10 Q8): live sentence added.

### Victory state in a save (new question)
Status: SETTLED
Answer: None of `state[8]`, `won[8]`, `stateTime[8]` (nor the eight per-player quest records) is stored or
restored. `VictoryConditions` has no store or load function, and `NLogic::System::Save` does not touch it.
The object is initialised (all zero) when the system is set up for the world entry, before the file is read.
In the first tick after the load `VictoryCond_Update` therefore finds every state 0: it runs
`CheckPlayerEliminated` for every slot (a player without a castle gets state 1 again, with the current tick
as `stateTime`), and then declares the first slot with state 0 and `won == 0` for which `IsVictoryReached`
holds: the same winner again, with the dialog.
Evidence: S 005275c0 `System::Save` (MapInfo, logic id, running flag, three floats, tick counter); S 005357c0
`Init`; S 00535840 `Reset`; S 00535d70 `Update`; the functions of the class and of the system member `+0xf0`
enumerated in the decompile (no store, no load); save order of `GameFile_SaveLogic` S 005a9ec0 as listed in
the specification.
Spec text changed: `docs/sim/players-victory.md` §7, §10 Q8.

Other documents changed in this interlude: `docs/message-catalog.md` (0x058 / T43, 0x05A / T49, T15, V23) and
`docs/types.md` §1.5 `+0x54`, with the wordings of batch 1.

---

# Third pass, batch 2 (2026-10-12)

12 entries: 9 SETTLED, 3 STILL NEEDS LIVE (two of them narrowed).

### Autosave during a pause
Status: SETTLED
Answer: The autosave fires while the game is paused and never during a cinematic. Its timer compares wall-clock
seconds and has no pause test, and the game system's per-frame update calls it on every frame of a running
game screen, paused or not, unless the UI is suppressed or the cinematic byte is set. The interval keeps
running during a cinematic, so an overdue autosave fires in the first frame after it.
Evidence: S 0078b040 `Autosave::Update` (interval from the profile, offline only, `now − last > interval`
with `Timer_GetTotalSeconds`); S 00780d20 `nGame::System::Update`: `if (!uiSuppressed && !this[+0x635])
autosave.Update()`; the byte is `bInCinematic`, set by `BeginCinematic` S 00782b60 (called from
`nMenu::Cinematic::OnShow` S 005fbd30), cleared by `EndCinematic` S 00782bb0; S 004018e0 calls the game
system's update without a pause test (live today: once per frame).
Spec text changed: `docs/sim/save-format.md` (autosave rows and the paragraph below them), §10 Q4.

### Book reopened in quest view
Status: SETTLED
Answer: Neither the page widgets nor the quest widgets. Closing the book deletes every script-made widget of
the dialog (the quest list among them) but does not undo the quest view: the page text, the page counter and
the two page buttons stay hidden, the toggle keeps its caption `!STORY`, and the script's `questDialogOpen`
stays true because `destroyQuestUi` is not called. Opening it again resets the page count and stores the
first page's text in the hidden text block. So the book shows its frame and picture only. One click on the
toggle takes the "leave the quest list" branch (it tests whether the page text is visible), calls
`destroyQuestUi` and shows the pages.
Evidence: S 0062e0a0 `Overlapped::OnHide`: `UiWidgetList::DeleteAllAndClearFlag(face + 0xbc8)` = object
`+0xbe8`, the list `ShowQuestView` S 005fc900 and the toggle branch of `Book::Update` S 005fcbc0 use;
S 005fc160 `Book::OnHide` (stop music, base `OnHide`); S 005fc310 `Book::OnShow` (page count and current page
to 0, base show, title, position, hides two base widgets); S 005fcd50 `AddPage` (sets the text, enables
"next"); the four hides in S 005fc900 are undone only in S 005fcbc0. `quests.lua`: `destroyQuestUi` only
clears `questDialogOpen`.
Spec text changed: `docs/sim/lua-runtime.md` §10 Q7; `docs/sim/frontend-screens.md` (`Book` paragraph).

### Heal with soldiers in a barracks
Status: SETTLED
Answer: Effect 1003 sets every soldier settler of the owner to full life points and empties the remembered
life points of every occupied building of the owner in the casern list. A stocked soldier is a unit of its
good; its wound exists only as an entry of that memory. With the memory empty, a soldier leaving afterwards
keeps the value it is created with, the maximum.
Evidence: S 00660270 (two loops; `Stl_Tree_Clear_Head14(building->settlerSpawn)`); S 00564c40
`RememberSettlerValue` (push the value when it is below the maximum); S 00564d90
`SpawnSettlerRestoringValue`: `Damage(max − TakeSettlerValue)`; S 00564c90 `TakeSettlerValue` returns the
soldier's own value when the memory holds no more entries than the stock holds units.
Spec text changed: `docs/sim/quests-sacrifices-stats.md` §10 Q7; `docs/sim/village-buildings.md` §3.11.

### Joiner with less gold than the wager
Status: SETTLED
Answer: The join succeeds (the browser tests the wager of the listed entry) and the client shows no message.
The Ready button is disabled on every frame because `gold >= wager` is a term of its enable rule, so that
player cannot become ready and the match cannot start. `PlayerReady(0)` is sent, every frame, only while the
own slot is ready, i.e. only when the wager was raised after the player had become ready.
Evidence: S 00454cf0 `UpdatePlayerRow`: `readyButton->SetEnabled(unique indices && wager <= gold && humans > 1
&& parties > 1 && gameId != 0)`; S 00457a00 `Update`: `if (IsLocalPlayerReady && avatar && avatar->gold <
GetWager) SendPlayerReadyEvent(false)`.
Spec text changed: `docs/sim/match-setup-room.md` §10 item 5.

### AI seat beyond the map's positions
Status: SETTLED
Answer: The seat does not exist in the match: no player, no castle, no computer player. The room leaves the
seat's start position unchanged, `SetupSession` writes the seat into the setup slot of that index, and the
world creates and activates players only for the indices below the map's number of start positions.
Evidence: S 004562d0 `SetupSession`: `MapInfo::SetPlayerKind / Colour / Tribe / Team / AiLevel / Name` with
the key `PlayerInfo::GetPlayerIndex(slot)`; S 005abb60: both loops (create, activate and place the start
building) run over the start position list.
Spec text changed: `docs/sim/match-setup-room.md` §10 item 3.

### Left-game notice
Status: SETTLED (the value of `+0x4b` on a non-host; "exactly once" depends on the message sequence)
Answer: On a non-host the byte is 0 for every slot after each applied game information, AI and closed slots
included (on the host those are 1). The byte is not serialised; a received event's slots carry the
constructor's 0 and `AssignGameData` copies the byte with the rest of the slot. The notice sets it to 1, and
the next game information the client applies (0x30003, 0x30005, 0x30012) clears it again, so a second leave
event for the same slot after such a message shows the notice again.
Evidence: S 00415230 ctor (`+0x4b = 0`); S 00415130 `Deserialize` (does not read `+0x4b`); S 00415460
`CopyFrom` (copies it); S 00414290 `AssignGameData` (six `CopyFrom`); S 00410720 `HandlePlayerLeft`
(`if (!slot[+0x4b]) { notice; SetLeftNoticeShown(1) }`).
Spec text to change: `docs/NCOMM_GAME_PROTOCOL.md` slot table `+0x4b`: "Its value on a non-host after a
GameInformation broadcast is applied: `[TODO]`" → "On a non-host it is 0 for all six slots after every applied
game information (`Deserialize` S 00415130 leaves the constructor's 0, `AssignGameData` S 00414290 copies it)
[known]".

### Random teams
Status: SETTLED
Answer: The host's own session receives the same random values as the joiners. `BroadcastStartLoading`
builds the event from a copy of the session, fills every missing start index and team in that copy, and
`BroadcastEvent` sends it and then applies it locally through the same handler the joiners use, which
overwrites the session with the event. The values come from the C runtime's `rand()` seeded with
`time()` on the host, not from the simulation's generator.
Evidence: S 0040fe50 (`AssignGameData(ev, session)`, `AssignRandomPlayerIndicesAndTeams(ev)`,
`UpdateSettingsCrc(ev)`, `BroadcastEvent(ev)`); S 00413930 (`srand(time(0))`, `rand() % maxPlayers`);
S 0040fd80 (`pSendToAll`, then `HandleEvent(ev)`); S 0040e560 case 0x30012 (`AssignGameData(session, ev)`,
`cStartLoading = 1`).
Spec text to change: `docs/NCOMM_GAME_PROTOCOL.md` team note: "whether the host's session receives the random
values is `[TODO]`" → "the host applies its own 0x30012 (`BroadcastEvent` S 0040fd80 → `HandleEvent` case
0x30012), so its session holds the same values [known]".

### Unit of the ping samples
Status: SETTLED (the unit; the other parts of `logic-core.md` Q2 are untouched)
Answer: Milliseconds of a full round trip, with the resolution of `GetTickCount`. The request carries the
sender's `GetTickCount()`, the peer echoes it, and the reply handler reports `GetTickCount() − echoed value`.
Evidence: T 1000a2a0 `Send_Ping` (payload: magic 0x5a89, phase 0, peer id, `GetTickCount()`); T 10009070
`Received_Ping` (phase 0: echo as phase 1; phase 1: callback slot `+0x3c` with `(peer id, now − tick)`);
S 0041d910 → S 0041d610 stores the value unchanged.
Spec text changed: `docs/sim/logic-core.md` §10 Q2.

### Client chat routing
Status: SETTLED
Answer: Through the host. A client's kernel sends every message over its single connection to the host; the
host relays a message addressed to all users to every logged-on user except the sender and also delivers it
to itself. The sender shows its own line because `BroadcastEvent` applies the event locally.
Evidence: T 10003cc0 `KRNL_SendMessage` (client mode: the connection found by the own id, whatever the
destination); T 10005140 `KRNL_RouteCustomData`; T 10003bc0 `KRNL_SendToAllUsers` (skips `srcId`);
S 00410410, S 0040fd80.
Limit: that the game's send (TinCat API slots `+0x98` / `+0x9c`) ends in `KRNL_SendMessage` with kernel type 2
was not read; the kernel has no other path out of a client.
Spec text changed: `docs/sim/network-session.md` §10 item 1.

### Which seed a client uses
Status: STILL NEEDS LIVE
Answer: Narrowed, not decided. A client stores the seed of its own `RegisterGameResult` only while the
manager state is 2 (S 004082e0), then fills the descriptor and asks for the game (S 00431800); every game
information from the host (0x30003, 0x30005, 0x30012) overwrites the session seed with the host's
(`AssignGameData` S 00414290).
Blocked by: whether such a message lands between the client's own result and its chest pass is a matter of
message timing.

### Name outside Windows-1252
Status: STILL NEEDS LIVE (narrowed to the operating system)
Answer: `Str_Utf8ToAnsi` S 00487620 calls `WideCharToMultiByte(CP_ACP, 0, …, NULL, NULL)`: no
`WC_NO_BEST_FIT_CHARS`, no own default character. With these arguments the API uses the code page's best-fit
mapping where it has one and the system default character (`?`) otherwise; which letters have a best fit is a
property of the system's code page tables.

### Failed "enter village"
Status: STILL NEEDS LIVE
Answer: Nothing to add to `lobby-screens.md` §10 item 1: the writers of the enable byte are enumerated there
and the decompile shows the same set (`DisableButtons` callers S 0043a630, S 0043bc40, S 0043bd50,
S 0043b4d0).

---

# Third pass, batch 3 (2026-10-12): network match, pre-game room, village

10 entries: 4 SETTLED (one of them covers two queue entries), 6 unchanged or STILL NEEDS LIVE. Corrections to
`docs/NCOMM_GAME_PROTOCOL.md` (slot `+0x4b`, team note) from batch 2 are applied.

### A player leaves through the menu / Clean leave among three (the count of 0x2002B)
Status: SETTLED (the count on the host when a non-host leaves; the host's own leave and the visible checksum
notice stay live)
Answer: Two. A non-host's clean leave makes the host queue command 0x2002B twice: once when the lockstep
0x3000b made from its 0x3000a is executed, and once when its connection goes, because the disconnect path
finds the slot (the lockstep event does not touch the slot on the host), broadcasts 0x3000b again and the
host's own handling of that broadcast queues the command again. The order of the two does not matter. The
second command finds no castle and does nothing (first results list of today: `HandleCommand_2002B` removes
the castle).
Evidence:
- S 0040e560 `HandleEvent`, case 0x3000b: non-host → `HandlePlayerLeft`; own GUID and leave requested → leave
  completed; host in roles 1..4 → `Event1Integer` 0x2002B with the event's player index into the outgoing
  package, with no test of the slot.
- S 00410720 `HandlePlayerLeft` on a host: if `FindSlotByGuid` still finds the slot → `BroadcastEvent`
  (0x3000b; S 0040fd80 applies it locally) and `RemovePlayerById`.
- S 0041bcc0 / S 0041b990 / S 0041bb20: the connection event reaches `UIS_Remove` → `HandlePlayerLeft` unless
  the reconnector reported 1 and the reconnect state is non-zero. The object tested is the client's
  `NComm::TinCatReconnector` (`+0x0c` state: 1 after `cb_BecameServer`, 2 after `cb_ReconnectTo`); on a host
  `Reconnector::HandleRemovedConnection` T 10010b80 returns 1 with the state 0, so the removal runs.
Spec text changed: `docs/sim/network-session.md` §3.10 (the meaning of the tested field; the second command
`[known]`), §10 item 7.

### Host loss
Status: SETTLED (when the reconnect fires, who becomes host, the lobby server's part); that a migration works
across real networks stays live
Answer: The reconnect fires on a client as soon as its transport reports the connection to the host removed
(a client has no other connection). The successor is the first entry of the peer list the host last sent:
the host keeps one entry per connected client in connection order and resends the whole list after every
change. A "preferred successor" mark exists in the library but the game never sets it. The elected client is
told to become the host (reconnect address −1, which is the "all −1" of the queue entry); every other client
is told to reconnect to that entry's address (as the old host saw it) and announced port. With two players the
surviving client is the only entry and becomes the host. The lobby server takes no part: the election is peer
to peer and the restart as host only restarts the transport and re-arms the session; no game server is
registered. So the server log shows only the old host's connections going away.
Evidence: T 10010ae0 `HandleAddedConnection` (host: add peer, broadcast list; client: remember own id,
announce local port); T 10010890 `BroadcastPeerList` (module 0x61, message 0x5e7b, subtypes 1 / 2 / 3);
T 10010a30 `HandleReceivedData`; T 10010b80 `HandleRemovedConnection`; T 10010930 `ElectNewHost` (first entry
with state 2, else the first entry; own id → callback slot `+4`, else slot `+8` with address and port);
T 10010be0 `SetPreferredNextServer` (no caller in the client: no reference to it in the decompile);
S 004259b0, S 00425aa0; S 00419e10 `Process` → S 00408f60 `BeginReconnect` (needs manager state 3 or 4) or
S 0040a110; S 0040b700 (callees: session and transport only).
Spec text changed: `docs/sim/network-session.md` §3.9, §10 item 2.

### Host leaves; a kick (the host's exit)
Status: SETTLED (the host's exit from the room; the kick was already `[known]`)
Answer: The client shows no text at all; the room dialog just closes. The host's `Shutdown` only stops its
transport. On the client the connection event goes to the reconnector first; it elects a successor (the list
always holds this client), so the reconnect state becomes non-zero and the "player left" removal with its
notice is skipped. One frame later the transport's `Process` fails, because a reconnect needs a loading or
running match, and the manager shuts the transport down and sets its state to 0 with a log line only. The
world screen shows the setup dialog only while the manager state is 2, so it hides it and disables the
settlers chat tab.
Evidence: S 0040b410 `Shutdown`; S 0041bcc0 (and the two sibling callbacks); S 00419e10; S 00408f60;
S 00410f70 (`Process` false → `pShutDown`, state None, `cShutdownFlag = 1`, log "GetNetworkHandler()->Process
failed!"); S 00435980 `WorldScreen::Update` (`if (state == 2) setupGameDialog->SetVisible(...) else hide`).
Spec text changed: `docs/sim/match-setup-room.md` §10 item 1; `docs/sim/network-session.md` §3.9.

### Shop action in slot 0 plus a second action
Status: SETTLED
Answer: No 0x2E10 arrives. The automatic dispatch on selection needs slots 1 and 2 to be empty, and for a
selected NPC the three action buttons are hidden, so nothing can be clicked either: an NPC with two or three
actions cannot run any of them. (Live today: a two-action NPC did nothing.)
Evidence: S 00437760 `HandleButtonClicks`: `if (latch && codes[1] == 0 && codes[2] == 0 && codes[0] != 0)
DispatchSlotAction(0)`; the NPC branch of `RefreshActionSlots` S 00433f60 calls button slot `+0x24` with 0;
that slot of the button vftable (S 007dff14, entry S 007dff38) is `nUi::Object::SetVisible` S 004a1090, which
calls `Hide`; `Object::OnMouseButton0Up` S 0049ff60 sets the click latch only when the widget's visible test
holds.
Spec text changed: `docs/village-and-character-protocol.md` §5.2 (two paragraphs).

### Re-sent 1004
Status: STILL NEEDS LIVE (narrowed)
Answer: Unchanged from the document: the proxy is re-read in place and `OnNPCAdded` S 005031a0 does nothing
when the proxy already has an object. `CreateNpcObj` S 004f6ea0 passes the proxy and its position and rotation
to `CreateObj` once.
Blocked by: whether a component of the `settler` / `letterbox` object reads the proxy again per frame (the
object keeps the proxy pointer) was not read.

### Re-entry after a match
Status: STILL NEEDS LIVE
Blocked by: the order of the server's character list and the client's mode transition is message timing.

### Net tick length and input delay
Status: STILL NEEDS LIVE
Blocked by: real time. The constants are in the specification (length 4, package of net tick − 2 executed).

### Cannot-sell box
Status: unchanged (already `[known]` in `docs/message-catalog.md`: price 0 → `!LOBBY_TRADER_NOT_WANTS_ITEM`
for a valid item, `!LOBBY_CANT_SELL_ITEM` for an invalid one, S 0045c560)

### Unused transport timeouts
Status: unchanged (the specification's "no reader found in the library" is a static statement already; a
read watch is the only further test)

### Poker: "back in" during the own turn / Pawn Chess
Status: unchanged (both rest on a completed static reading of client and server; they need two players at a
table to be seen)

---

# Fourth pass (2026-10-12)

Entries the earlier passes did not examine. Method as before: decompile through `mapctl.py fn`, disassembly and
vftables through the Ghidra MCP where a number or a virtual call decides.

### Enclosed planter
Status: SETTLED
Answer: He never plants, when "enclosed" means: the flood fill from the building anchor through walkable cells
explored by the owner runs empty before it has collected 11 candidate cells and before it has visited a cell
farther than working radius + 4 from the anchor. The search then returns false, no random number is drawn and
`GoAfforest::Start` returns false without creating a deposit. A planter in a small reachable area that still
holds 11 or more plantable cells within the working radius plants normally (the 11th candidate stops the fill).
Unexplored ground encloses in the same way as water or buildings: the fill does not enter a cell the owner has
not explored.
Evidence:
- S 00778f30 `FloodFillSearch::Run_EmptyPlace`: returns true only from a `Visit` that returned true; false when
  the queue is empty.
- S 0077e660 visit rule: candidate if `HexDistance <= radius` and `CanPlaceDepositWithClearance`; returns true
  when the candidate vector holds `>= 0xb` entries or the cell is farther than `radius + 4`.
- S 0077e5c0 expand rule: start cell, or `Map_IsCellWalkable && Exploration::IsExplored(cell, player)`.
- S 00779330 `LookForEmptyPlace::Start`: `LogicRandom_Next` and the result cell only inside `if (Run(...))`;
  the else branch frees the candidates and returns false.
- S 0077bcb0 `GoAfforest::Start`: the call is slot `+0xc` of the member's vftable S 0083457c (one constructor,
  S 007787d0; slot `+0xc` = S 00779330); on false the function returns false, nothing else runs.
Spec text changed: `docs/sim/map-resources.md` §10 Q1 (the §3.9 text already says this).

### Animal idle time and unexplored targets (hunter half)
Status: SETTLED
Answer: Yes. The hunter's search tests exploration on the cell at `Animal +0x38`, which is `targetCell` of the
animal's embedded movement (`Animal +0x2c` + `NMovement::Base +0x0c`), not on the cell the flood fill visits.
An animal walking on explored ground towards an unexplored destination is not a target; an animal walking
through unexplored ground towards an explored destination would be one, but the flood fill itself only needs
walkable cells, so it can be reached. While the animal is at rest the target cell is the cell of its last
arrival (the spawn cell before the first walk), so the test is then the usual one. The roam search does not
look at exploration, so destinations on unexplored ground occur.
Evidence: S 00542c40 `HuntableAnimalSearch::IsTarget`: `FindHuntableAnimalAt(pos)`, stack goods `!= 0`,
`IsExplored(&animal->field_0x38, filter.player)`; S 005418e0 builds the movement at `+0x2c`; S 00772b00
`StartMoveTo` writes `targetCellX/Y` (`+0x0c/+0x10`) only when a path was found; S 005439b0 / S 00543900 (roam
rules, no exploration test, as documented).
Spec text changed: `docs/sim/map-resources.md` §10 Q4.

### Carrier sent home while his street exists
Status: SETTLED (slot and upgraded street); NARROWED (how often)
Answer:
1. The street keeps the carrier in its slot until the carrier object is destroyed. `StopAndSetState3` calls
   settler vftable slot `+0x38`, which for a carrier is the empty stub, sets state 3 and starts `LeaveMap`,
   whose `Start` only discards a held package and cancels the route. The two unlink functions of the carrier
   slots have four callers in total: the carrier destructor, the street destructor, the street split in
   `PlaceFlag` and the street swap in `GoToPackageTarget::Update`. None lies on the way home. `Street::Update`
   orders a carrier only while the slot's reference is invalid, so no order is created before the carrier has
   been booked into a building (or has died) and deleted. During that time the street keeps `usable[0]` and,
   because the carrier holds no package, the path search charges its plain length (no ×3).
2. A type-1 street that lost its first carrier goes on with the second alone: unlinking slot 1 sets
   `usable[0]` to "slot 2 valid" (stays 1), the type-1 branch of `Street::Update` looks at slot 2 only, and
   `UpdateStreetTransport` of the second carrier reads nothing of slot 1.
3. How often: `WaitForPackage::Update` ends without a package only when the carrier is not on the `mid` cell of
   his street and found no package (or stands off his street's path) and either his fine position is not the
   centre of his cell (`SettlerMovement_StopAndIsCellCentered`) or `StartStreetMoveTo(mid)` returns false (the
   start of `MoveToWorkingPlace` forwards its result). Both tests are per tick, every tick while displaced.
   Which game situations leave a carrier in state 0x16 off-centre, or with a street route that cannot start,
   was not derived.
Evidence:
- S 0065b710 `Carrier::Update`; S 00656740 `StopAndSetState3`; Carrier vftable S 007f847c slot `+0x38` =
  S 005657b0 (body `ret`); S 00776d00 `LeaveMap::Start`.
- Callers of S 0053ca80 / S 0053cb40: S 0065afb0, S 00669210, S 00666900, S 0077a2f0.
- S 00668e10 `Street::Update` (types 0/2: `carrierIdHi` invalid and no order; type 1: `secondCarrierIdHi`
  invalid and no order); S 00668ce0 `ClearFirstCarrier` (`usable[0]` = second slot valid); S 0066b9e0
  `GetLinkCost` (×3 only when no valid carrier of the street is without a package).
- S 0077ac50 `WaitForPackage::Update`; S 00657ea0 (centre test: fine position `+0x11c/+0x120` against
  `cellX*4 (+2 on odd rows)`, `cellY*4`); MoveToWorkingPlace vftable S 0083469c slot `+0xc` = S 007775a0 →
  MoveToStreetPosition slot `+0x14` = S 007780e0 → S 00657f50 `StartStreetMoveTo`.
- S 0065b200 state 0x16: movie done and no claimed package → `StopAndSetState3`.
Recipe for 3 (if wanted): hook S 00656740 with the caller address and log settler state, cell and fine position;
a developed save run for some thousand ticks tells whether the branch of S 0065b200 state 0x16 fires at all.
Spec text changed: `docs/sim/streets-transport.md` §3.7 (consequences), §3.8 "Losing the job", §10 Q1, Q2.

### One ship-building visit
Status: SETTLED
Answer: The hammering of one visit is 31 calls of `ShipConstruct::Update`, one per logic tick: `strokes =
(int)ShipConfig.constructTime` = 30 with `sh_setConstructTime(30)` (the queue entry's "50" is not the shipped
value), 30 calls that return false and one that returns true, each adding `workPerStroke`. The time between two
fetches of a good is longer: walk from the entrance flag cell to `buildCell`, the drop (two timers of 3.3
ticks), the 31 ticks, the walk back.
Evidence: S 0077fa30 (disassembly: `FLD [shipConfig+0x14]; CALL __ftol2_sse; MOV [this+8],EAX`; phase test
`1.0 - construction[+0x4c] < 1.0` → frame list `+0x58`, else `+0x68`); S 0077f9c0; S 0077d6c0 step 10 calls the
member's `Update` once per call; S 0065e770 calls the movie once per `Constructor::Update`; one settler update
per logic tick is measured (`settlers-jobs.md` §3.9); `ship.lua` line 8.
Spec text changed: `docs/sim/navy.md` §10 Q11.

### Ship on another sea adopts a route
Status: SETTLED
Answer: Both happen, by the code. An anchored idle ship takes any own-to-own route of its player, whatever the
water body: the continent test in `FindOwnRouteForShip` compares the ship's cell with itself. Sequence:
1. `ReturnToOwnHarbor`: route linked, `MoveToHarbor(nearest own harbour H1)` → movement state 4, a dock is
   reserved, `StartMoveTo(dock)` finds no path (A* precondition: same continent id) and stops. The ship lies
   still with movement state 4, ship state 3.
2. Ship states 3 → 1 → 2 run on still ticks and use `targetHarbor` only: the ship unloads to and loads from
   H1's flag while it lies on the other sea. This is the one stay with cargo exchange from a distance.
3. Leaving for H2: `MoveToHarbor(H2)` → movement state 1 → `AdvanceRouteLeg`: state 2, A* to `path[1]` or
   `path[n-2]` fails, the ship stops in movement state 2. Next tick `Movement::Update` (not under way, route
   valid, state != 4) → `AdvanceRouteLeg`: state 3, `MoveToWaypoint(path[1])`; the path source is now the
   stored route; the ship's cell is not on it, so the extracted segment is `path[1..n-1]`; the path index
   starts at the last entry and the first pop yields `path[n-2]`; `BeginStep` takes it as one step of
   `d = HexDistance(path[n-2], ship cell)` with `stepRate = speed / d`. The ship crosses whatever lies between
   in a straight line, then follows the route to `path[1]` and sails by A* to its dock at H2. From then on it
   is on the route's sea and behaves normally.
The player command and the computer player cannot produce this: `FindNearestIdleShipAtHarborExit` tests the
water body.
Evidence: S 005b4c50 (disassembly: both indices are built from `[ship+0x24]+4/+8`, compared at S 005b4d49);
S 005bab60; S 005b97f0; S 005bbbe0 (A* precondition); S 00772b00 (no path → slot `+0x10` stop, false);
S 005bb500 (still test: progress not > 0 and movement state 0 or 4; states 1 to 3); S 005b99d0; S 005b92a0;
S 005bdb30 (state 3 → `ExtractSegment`, always true); S 005bd900 (target found first → forward copy to the
end when `from` is absent); S 00772c50 (`index = count - 1`); S 005436d0 (decrement, then read); S 007728d0
(`stepRate = 1 / (dist / speed)`); S 005b3450 (water body test of the command path).
Needed in the game to see it: a finished ship with an anchorage on a sea that has none of the player's
own-to-own routes, and such a route on another sea; the ship takes it on its 102nd still tick.
Spec text changed: `docs/sim/navy.md` §3.4 ("When no path is found"), §3.8, §10 Q4, Q5.

### Founding and a lost expedition target
Status: SETTLED
Answer:
1. Founding tick: state 6 calls `PlaceExpeditionBuilding` and then, unconditionally,
   `Harbor::PlaceFlagAndRevealExitsForCellOwner` on the target harbour, before the street is built. The flag
   is placed in that call when the harbour cell has an owner and is not a border cell. The building position
   is searched in rings 0..`territoryRange - 1` around the harbour cell (9 − 1 = 8 for the three expedition
   buildings), so the harbour cell is at most 8 and each of its neighbours at most 9 = `territoryRange` cells
   from the building: all seven are inside the new source. The flag is therefore placed in the founding tick
   unless a neighbour of the harbour cell is outside the map or another player's source wins the harbour cell
   or one of its neighbours.
2. Lost target in state 7 or 8: nothing happens to the returning ship. Losing a harbour takes only the ships
   **of that harbour's owner** off the routes through it. A target that belonged to another player and is
   lost again does not touch the expedition ship: states 7 and 8 skip the "both ends mine" test and read the
   target no more; the ship unloads at its start harbour and finishes. If the lost harbour is one of the
   ship owner's own (the start harbour, or a target he owned), the ship is unlinked through
   `NavyLink_UnlinkExpeditionRoute` in the same call: route cleared (`bInterrupted` when under way, so it
   stops at the next cell), expedition deactivated, ship state 0, then the idle rules (anchorage search,
   settlers disembark one by one, `ReturnToOwnHarbor` after 101 still ticks).
Evidence: S 005b8ac0 (case 6: owner test of the target, `FindBuildingPosition`, `PlaceExpeditionBuilding`,
`PlaceFlagAndRevealExitsForCellOwner`, `BuildStreet`; the pre-switch test excludes states 7 and 8; case 7
`ChooseStartHarbor`, case 8 `UnloadStep` → `Finish`); S 005b7e50 (`maxRing = territoryRange - 1`); S 005b5670;
S 0067b5a0; S 00538cd0; `ship.lua` (`sh_setExpeditionBuilding`: the three guard houses), `buildings.lua`
(`bp_setTerritoryRange` 9); S 005b5370 → S 005bc1c0 → S 005b7050 (`*(ship+8)->index == player` only); S 0053c040.
Spec text changed: `docs/sim/navy.md` §10 Q7, Q10.

### Two players' ships at one exit
Status: SETTLED
Answer: No. Two players' ships never both wait in ship state 1 on one route, and an exit never runs out of
docks. State 1 is entered from state 3 or from a finished expedition whose route is still linked, and a ship
keeps a route only while its player owns both ends (a lost harbour unlinks the owner's ships in the same
call). A second player cannot have a ship on such a route: `CanPlayerAssignShip` refuses a player who owns
neither end, and every path that puts a ship on a route passes it (or `HasPlayerEntry` for the sea attack,
whose route runs between a harbour of the attacker and one of the target's owner). On a route with two
owners at most two ships exist, one per owner (an expedition or a sea-attack ship each); each takes its own
docking position, because the dock search only refuses an exit where a ship of the **same** player is docked
and otherwise returns the nearest free position. Ships do not block cells either: free water is water without
the logic-object bit 0x400, which ships do not set.
Evidence: S 005b6d30; S 005ba970; S 005b3450; S 005a02c0 (the computer player assigns through
`CanAssignShip`); S 005bc060; S 0052e360; S 005bba90; S 005bb500 (writers of state 1).
Spec text changed: `docs/sim/navy.md` §10 Q8.

### Good exchange output
Status: SETTLED
Answer: The goods leave through the sacrifice building's own worker, one unit per walk to the building's flag,
and state 0 ends on the first building update at which the output stock holds nothing (total unit count 0),
which is the tick after the worker has taken the last unit. The rule is the same for every building of
working mode 9 (the three temples and the Olympic flame all have a worker and no `depot` flag, so the
transport system never dispatches from them).
- `Worker::ChooseNextWork` first calls `TryStartBringGoodOut`: if the output stock holds a plain ware (good
  type 0) the worker starts `BringGoodOut` (state 0x35) or, from the idle position, `ReturnFromIdle` (0x13).
- `BringGoodOut`: pick up one ware (`Depot::TakeOneWare`, lowest good id first), wait for a free flag, leave,
  put it down, enter; if the stock still holds a ware the movie restarts itself, else it ends.
- For modes 8 and 9 the end of `BringGoodOut` leads to `ChooseNextWork` again, and mode 9 has no work of its
  own (the switch has no case 9), so the worker's state does not change and the test runs again on every
  tick: a ware that appears later is carried out at once.
- On the flag the package has no target: it is a free package and goes to the nearest storehouse or to a need
  (`streets-transport.md` §3.11, §3.12).
- `VillageSacrifice_Update`: `state == 0` and `depot.stockB.totalUnits == 0` → `state = 2`,
  `sacrificeDefId = -1`.
Limit: the stock total counts every good, `HasAnyWare` only plain wares; a settler good in the output stock of
a sacrifice building would keep state 0 for ever. The shipped exchanges reward wares only.
Evidence: S 0065d660; S 0065cc40; S 0077c510; S 0055b120 / S 0055b1b0; S 0065d7f0 (case 0x35: modes 8 and 9 →
`ChooseNextWork`; case 4: `HasArrivedAtWorkplace` → `ChooseNextWork`); S 00561940; `buildings.lua` lines
320..375 (`bp_setWorker`, `bp_setWorkingMode(…, BuildingWorkingMode_Sacrifice)`, no `bp_setDepot`);
S 00557da0 walks the `depot` list only (`streets-transport.md` §3.11).
Not read: what `EnterBuilding::Update` S 00778c20 does when it is called again after it has finished (it
returns true; it also calls the owner's enter slot on a building next to the settler's cell each time).
Spec text changed: `docs/sim/quests-sacrifices-stats.md` §3.2 effect 1001, §10 Q4.

### Script-moved NPC
Status: SETTLED (the entry's expectation is wrong; not observable with the shipped data)
Answer: An NPC that is off-centre when `se_moveNPCTo` sets its cell target re-centres and stays; it does not
walk to the target. Case 0x2f falls through into case 0x12; both movies' `Update` is the same function
("movement not busy"), so in the tick the re-centring ends the 0x12 rule clears the cell target. The entry
expects "0x29 with a walk to the target"; the code gives 0x29 without a target. No shipped script reaches it:
the only calls of `se_moveNPCTo` and `se_moveNPCToFine` (C05.lua lines 182, 184; C06.lua line 100) are
commented out.
Evidence: S 0065ddf0 (switch: case 0x2f sets 0x29 and continues into case 0x12); NPC constructor S 0065e010
(members `ReturnToLogicGrid`, `MoveToPosition`); vftable slots `+0x18` at S 008345d4 and S 00834534 both hold
S 00777c50; `grep moveNPCTo` over the decrypted data.
Spec text changed: `docs/sim/settlers-jobs.md` §10 Q3.

### Saves in special states
Status: NARROWED
Answer:
- Pause: nothing of the pause is in a save (pause is game speed 0 in the user profile); the save panel is
  reachable and the save is an ordinary one. Already measured: a load does not restore the speed.
- Sacrifice: running sacrifices are stored with their start ticks (`NSacrifice::System::Store` writes the
  per-player table); only the cinematic pause of the sacrifice system (`bPaused`, `pauseStartTick`) is not.
- Cinematic: three ways to write a save exist besides the autosave (which is gated by `+0x635`):
  1. the save panel, created only by the HUD's menu combo (`nMenu::Game::OnMenuComboSelected`) as a child of
     the HUD container `Game +0x968`. `Cinematic::OnShow` fades that container out over 1.0 s (hides it at
     once when the simulation clock is below 2.0), and every key is swallowed by the cinematic screen, so the
     panel cannot be opened by key. Open: whether a mouse click reaches the menu combo or an already open
     save panel during the 1.0 s fade (the fade keeps the target visible until it ends);
  2. `nMenu::System::EmergencySave` (window message `WM_POWERBROADCAST` with battery low): writes
     `_EmergencySave_` whenever the game screen is attached, with no test of the cinematic flag;
  3. the Debug dialog (`nMenu::Debug::Update`), not reachable in the shipped game.
  A save written through 1 or 2 during a cinematic loads with the computer players and the chests switched
  off (documented in `camera-input-cutscenes.md` §7).
Evidence: callers of `GameFile_Save` S 005aa260: S 005da7d0, S 00609130, S 0060d000, S 0060d5b0, S 0078af30;
callers of `LoadSavePanel::ctor` S 0060ce40: S 005e27c0 (main menu), S 005eb310; S 005fbd30 (`FadeOut` /
slot `+0x28` on `Game +0x968`); S 005d9650 (`CloseAllDialogs` covers the nine system dialogs, not the HUD
panels); S 005da7d0; S 00401f30.
Recipe for the open point: start a campaign mission whose briefing begins after tick 20 (clock ≥ 2.0), keep
the HUD's save panel open with a name typed, and click its confirm button in the first second of the
cinematic; a new file in the save folder = reachable.
Spec text changed: `docs/sim/camera-input-cutscenes.md` §7, §10 Q5; `docs/sim/save-format.md` §10 Q3.

### Property values after a reload
Status: NARROWED
Answer: The unmodified game never reloads: the property database is filled once in
`CApplicationEx::Initialize` and emptied only in `Shutdown`, and no script outside `scripts/properties/` calls
a `properties.*` binding, so two free games in one run read the same records. The question only exists for
the reload a mod performs (`ClearAll`, `RegisterLuaLibrary`, `data.lua`). For that reload the values come out
the same as far as the code read decides: `ClearAll` empties all thirteen record tables and the sign table;
the three config blocks (`GameConfig`, `MilitaryConfig`, `ShipConfig`) are not reset, but every binding on
them is an assignment (20 `cfg_set*`, 7 `sh_set*`, 5 `mi_set*`; the per-tribe ones are map subscripts), and
`RegisterLuaLibrary` writes only the four flags that `ClearAll` cleared. The per-tribe soldier good lists of
`GetSoldierGoodList` are static, built at the first query and not rebuilt, so they keep the values of the first
load (equal when the data is unchanged). Record addresses change; the values do not.
Not excluded by reading: a writer of a record field outside the 243 bindings (not enumerated), and code that
keeps a record pointer across matches.
Evidence: S 005494a0; S 00550e40 (flags, then the registration table); S 0054cb60, S 0054caa0, S 0054ca30 and
the names of the `cfg_` / `sh_` / `mi_` bindings; `grep 'properties\.'` over the decrypted data outside
`scripts/properties` (no hit); `docs/data-loading.md` §1.
Recipe (only with the test mod `propreload`): dump one building, one good and the three config blocks before
and after the reload and compare bytes.
Spec text changed: `docs/sim/properties-data.md` §10 Q5.

### Save and load are checksum-neutral
Status: STILL NEEDS LIVE (one candidate removed)
Answer: The one difference the specification names, the stock's change stamp that `Stock::Load` advances once
per unit, is not visible to the checksum: the stamp is written neither by `Stock::Store` nor by
`Stock::StoreContents`, the writer the depot's untagged (checksum) store uses. The other post-load steps
(callbacks re-raised by `PostLoad`, `NNet::System::PostLoad`, `MapModifier_InitAfterMapLoad`) were not compared
with the checksum writers; that is one comparison per subsystem and was not done.
Evidence: S 00539910 (count, then good id and count per entry), S 00539850, S 0055ae70 (caller).
Blocked by: the audit of every `PostLoad` against the untagged store of its subsystem; the live test (save at
tick N, compare `ComputeChecksum` S 00784080 over the next 50 ticks in both runs) answers it in one session.
Spec text changed: `docs/sim/save-format.md` §8.

### Emitter channel after scrolling away
Status: SETTLED (with a consequence that should be heard once)
Answer: On a processor with SSE2 the channel of an unclaimed emitter sound is never freed by the fade-out; it
is freed only when the emitter that owns it is removed. Step by step for the far position
(−FLT_MAX three times, S 007e51c0 = `ff7fffff`):
- the three differences are stored as float32 (−FLT_MAX each); `dx² + dz²` is formed in the x87 register and
  overflows to +inf when it is stored as float32 before `_CIsqrt`; `(2r − inf) / r` = −inf; the minimum with 1
  keeps −inf;
- height: `1 − FLT_MAX / 80` is negative, the maximum with 0 gives 0;
- `−inf × 0` = NaN (exceptions are masked by `Fpu_SetDefaultControlWord`); `NaN × volume` = NaN;
- `__ftol2_sse` S 006f2af0: with the SSE2 flag `[00898044]` set it is `CVTTSD2SI`, which returns `0x80000000`
  for a NaN; `targetVolume = −2147483648.0`;
- the stop test needs `trunc(currentVolume) == 0` and `trunc(targetVolume) == 0`; the second never holds, so
  `StopChannel` is not called and the record is kept; `currentVolume` falls by 255 per second without a bound.
Without SSE2 (flag clear) the same conversion runs `FISTP qword`, whose low dword for a NaN is 0, so
`targetVolume` = 0 and the channel is freed once the volume has ramped to 0: the behaviour the code was
written for.
When the fade-out runs at all: the nearest list has no distance limit, so a sound keeps its channel as long as
it is among the four nearest distinct sound ids of all emitters on the map. A channel is unclaimed only when
more than four distinct ids exist and its id drops out of the nearest four. From then on it holds one of the
four channels: with four records `free = 4 − 4 = 0`, so a sound that has no channel yet cannot start, and a
sound that is claimed again has to ramp up from `−255 × seconds away` (silent for about as long as it was
away). `RemoveEmitter` of the owning emitter stops and frees the channel.
Evidence: S 0056bab0 (disassembly, whole function); S 0056d2e0 at S 0056d5f4..0056d64f (far position, the two
conversions of `record +0x10` and `+0x0c`, `JNZ` past the call of S 0056d180); S 006f2af0 and its fallback at
S 006f2b26; S 0057b9b0 (`_controlfp(0x9001f, 0xffff)`: all exceptions masked; 24-bit precision); S 0056fda0
(no distance test); S 0056d180 (callers: `RemoveEmitter` S 0056d270 and the update).
`[00898044]` is the runtime's SSE2 flag, checked at its writer: S 007110d8 stores the result of S 00711078
(CPUID leaf 1, EDX bit 26, and the system test S 00711028). Not read: what FMOD does with a negative volume.
In the game: on a map with more than four ambient sounds, scroll from one group of sounding buildings to
another and back after a minute: the first group stays silent for about a minute, and the fifth sound never
starts. The size of the channel map (`SoundEmitterManager +0x10`) stays at its maximum.
Spec text changed: `docs/sim/audio.md` §3.4, §10 Q1.

### Cell demolish trigger
Status: SETTLED
Answer: The trigger is never armed. No code arms it, and no file the game can load carries AI cells: the
shipped data holds 33 `.s2m` maps, no `.a2m` and no `.aav`, and a `.s2m` is the map part alone (the AI system
is stored in the logic part). "Load each campaign save" has nothing to load: the campaign is 11 maps plus
scripts. A player's own save can hold an armed trigger only if the run that wrote it had armed it, which no
code does.
Evidence: `NAI::Trigger::Start` S 005a7960 has four callers and each passes another trigger: S 005949e0 and
S 00594a70 (`Cell +0xbc`), S 00594b20 (`+0xac`), S 005a6fe0 (the `CellFull` element); the constructor S 005a7940
clears the byte; `Load` S 005a78e0 is the only other writer; S 00594780 disarms `+0xe4`; an instruction search
for a store of 1 into `[reg + 0xe8]` finds no function of the AI. `GameFile_SaveMap` S 005a9fa0 (game system,
map, resources, doodads, ambients, navy, spawn system) against `GameFile_SaveLogic` S 005a9ec0 (… `ai` …);
file list of the decrypted data tree; `docs/sim/save-format.md` §2.6 (the one `.sav` in the install cannot be
opened).
Limit: a store through a register (`mov byte [reg+0xe8], al`) in a function the search did not attribute to
the AI.
Spec text changed: `docs/sim/ai-player.md` §2.3 (trigger row), §10 Q3.

### Floating-point control word in the scripts
Status: NARROWED
Answer: Inside `SADK.exe` nothing but `Fpu_SetDefaultControlWord` sets the precision or the exception masks:
`__controlfp` has that one caller, `__control87` is called only by `__controlfp_s` (no caller of its own in
the game code), there is no `FNINIT`, and the 205 `FLDCW` instructions are (a) the two runtime functions,
(b) inline float-to-integer conversions that load a word derived from the current one and restore it, and
(c) the runtime's transcendental functions, which load a fixed word and restore the saved one on exit. For
the property scripts the call sits in the same function: `Initialize` calls `Fpu_SetDefaultControlWord`, then
the file scan, `GetWindowRect`, `Timer_Init`, the script host and `RunPropertyScript("data")`, with no
graphics or sound call in between. So the property scripts run at 24-bit precision as far as the game's own
code goes; the same holds for `onStarted` / `onLoaded` unless a library called between the last
`Fpu_SetDefaultControlWord` and the script changes the word (Direct3D 9 sets 24-bit precision itself when the
device is created without the preserve flag, which is the same value).
Evidence: callers of S 006fa4ab and S 006fa1a8; instruction searches for `FLDCW` and `FNINIT`; S 004075d0
(order of calls); S 0057b9b0.
Blocked by: code outside the executable (Direct3D, FMOD, tincat3, codecs). The read of `_controlfp(0, 0)` in
hooks of S 0054f8d0 and S 005b2220 stays the test (needs permission).
Spec text changed: `docs/sim/lua-runtime.md` §8, §10 Q1.

### Waiting attackers without an enemy
Status: SETTLED
Answer: Yes, they give up, and an attacker that is already outside captures the building. A soldier in state
0xf whose home building's leave cool-down is still running tests every tick: if he or any attacker has
`leftFight`, or if the opposing side list holds no soldier with `leftFight == 0` while the defender list has
had a member at some time (`everAddedByKind` not both 0), he releases his fight state and returns to state
0xc. So in the tick after the last defender is removed from the defender list every waiting attacker unbinds.
The building is taken by an attacker in the fight: state 0x29 rule 2 sends an attacker-side soldier that is
linked to the target and may enter it to the target's flag (0xd), where he captures. An attack on a building
that never had a defender in the list is different: the test fails on `everAdded`, the waiting soldiers keep
leaving one per cool-down, and each then takes rule 2.
[inferred] If no attacker is outside when the last defender dies, nobody captures: the waiting soldiers unbind,
the attacker list runs empty and the attack ends with `!attack failed`.
Evidence: S 006594a0 case 0xf (`HasLinkedBuilding`; `military +0x60 == 0` → cool-down and leave; else
`AnyMemberLeftFight(fight +0x78)`, `OpposingSideHasEngageableSoldierFor`, `Military_IsSubObjEmpty` →
`ReleaseFightStateIfEngaged`, state 0xc); S 005711c0 → S 00571140 (scan of the other side's list for
`soldier +0x2d0 == 0`); S 00570980 (`(fight +0x7c) +0x24` and `+0x28` both 0); `military.md` §3.6.2 rule 2,
§3.8.
Spec text changed: `docs/sim/military.md` §10 Q8.

### Demolish countdown
Status: SETTLED
Answer:
- Length: `destroyCountdown = MilitaryConfig.actionsInFightDelayTime` = 300 (`military.lua` line 9), set only
  when the building is the target of a fight; otherwise the command removes the building at once.
- Per building update `Military::Update` decrements the value while it is above 0 (not while the cinematic
  flag `GameSystem +0xec` is set); `NVillage::System::Update` tests `destroyCountdown == 0` in the same loop
  iteration, right after `Building::Update`. The decrement from 1 to 0 and the removal therefore happen in the
  same tick, the 300th building update after the command.
- The two messages are never posted after such a countdown: `NotifyDestruction` has one caller, the branch
  `destroyCountdown == 0` at the entry of `Military::Update`, and a building whose countdown reached 0 does
  not live to its next update. The branch is reached only when the countdown is started with 0, that is with
  `mi_setActionsInFightDelayTime(0)`; then the messages and the removal fall in the same tick.
- A headquarters-type building skips the whole block, so a countdown started on one by a raw command would
  never run down and would block every later demolish command (the UI does not offer it).
- A paused construction site never disappears by itself. The paused flag (`Construction +0x78`) is used by the
  constructor, `Store`, `Load`, `Update` (no builder request), `Resume`, `AbortAndReturnGoods`,
  `Upgrade::Cancel`, the builder movie (it ends) and the building overlay; none removes the site. It goes only
  through the general removal paths (demolish, lost territory, flag removal, hit points).
Evidence: S 0055a7a0; S 0055fc10 (two callers: S 0055a7a0, S 0059b2f0); S 005609b0 (`if (c < 1) { if (c == 0)
NotifyDestruction } else if (!flagEc) c -= 1`, inside the block that headquarters types skip); S 0055a640 (loop:
`Building::Update` unless marked, then the test and `RemoveBuilding(…, true)`); S 00560890 (one caller);
users of `flag78`: S 0055e460, S 0055e720, S 0055e7a0, S 0055ea90, S 0055eeb0, S 0055ed30, S 00567320,
S 0077daf0, S 006403c0, and the raw read in S 0077d6c0.
Spec text changed: `docs/sim/village-buildings.md` §3.4 (pause), §3.5 (countdown), §10 Q7;
`docs/sim/game-commands.md` §10 (removal tick).

### Stale click latch
Status: SETTLED
Answer: Visible in play. `Button::OnMouseRelease` calls the base release handler, which sets the latch only
while the button is hovered and never clears it, and then runs `OnClicked` whenever the latch is set. A
mouse-up is delivered to every object that saw the matching mouse-down, wherever the cursor is. Only the
owner's poll clears the latch, so on a button whose owner does not poll, the first click leaves the latch set
and every later press that is released outside the button still runs `OnClicked`. Such buttons exist in the
shipped game: the poll has 54 callers (the lobby dialogs and some menu screens), while other panels act in
their click handler and never poll. Example: `nMenu::LoadSavePanel` handles its confirm button (`Confirm`) and
its delete button (`!Remove this file?`) in `OnButtonClick`, and its `Update` does not poll.
Evidence: S 004aecf0; S 0049ff60 (`if (hovered) latch = 1`; no clear); S 0049ff40 (`buttonPressed[button]`
gates the delivery); S 004a07a0 (children are offered the event back to front, no hit test); S 0049fdb0 and
its caller list; S 0060d430; callees of S 0060dd30.
In the game: open the save panel, press Delete and answer No; press Delete again, move off the button and
release: the prompt opens again. The same on the confirm button saves or loads.
Spec text changed: `docs/sim/ui-toolkit.md` §10 Q1.

### Activate-main latch and Info gate
Status: STILL NEEDS LIVE (narrowed)
Answer: Added to the byte search of the specification: no `LEA` instruction forms the address of either byte
inside a function of its class. The 30 `LEA` hits with displacement 0x228 belong to other classes (lobby
manager, widgets' `LoadFromXml` / `CopyPropertiesFrom`, an AI class at S 00592xxx, stack frames); the hits with
displacement 0xbfc are lobby dialogs, `Cinematic::OnShow` and the `Overlapped` constructor's store of 0
(S 0062e5ee).
Blocked by: a store through a register that was computed in another function (a member pointer handed out, a
block copy over the object). The write watch stays the test.
Spec text changed: `docs/sim/frontend-screens.md` §10 Q4.

### `settlers-jobs.md` §3.6.2: the run of consecutive attempts (extra question)
Status: SETTLED
Answer: The run is the walking step of `GoToPackageTarget`. In step 0x16, on every tick of the walk on which
the carrier's cell is on his street and a flag of his player stands on the final cell of the walk
(`movement +0x38`), `Update` calls `Transport_CarrierTryPlacePackageOnFlag` unless `ShouldKeepWalkingToFlag`
is true; each failure at a full flag increments the package's attempt counter. The first failure sets stop
distance 1, the walk continues to the cell before the flag, and when the walk sub-movie ends with the stop
distance set the movie goes to step 0x14, where the test runs only when `(tick + idLo) % 10 == 0`. The length
of the run is the number of walking ticks during which the flag was full: at most the whole walk to the cell
before the flag (17 or 18 ticks per flat cell), fewer when the flag filled up while he was under way. 13 to 42
ticks are walks of up to about two and a half cells.
Evidence: S 0077a2f0 (branch `currentStep == 0x16`: `FindFlagAt(owner, movement +0x38)`,
`ShouldKeepWalkingToFlag`, `Transport_CarrierTryPlacePackageOnFlag`, `SetStopDistance(1)`; on the end of the
sub-movie `HasStopDistance` → `ClearStopDistance`, step 0x14; branch `currentStep == 0x14`: the `% 10` and
`% 200` tests); S 0077a260 (`Start` sets step 0x16); `streets-transport.md` §3.8 states the per-tick growth.
Spec text changed: `docs/sim/settlers-jobs.md` §3.6.2.

---

## Fourth pass, second half (village, hand-written sections, tools)

### Extra mouse button as forward key
Status: SETTLED (with a condition the entry does not name)
Answer: Yes, and the chat box's focus does not matter; what matters is where the cursor is. The caller chain of
`CLobby::OnMouseButtonDown` (slot 20, `+0x50`, of the CLobby vftable S 007e599c):
1. `HandleWindowMessage`, `WM_XBUTTONDOWN` with button 1: cursor position, then UI event (type 0, button 3)
   through `nUi::Root`, then the in-game action map gets key 5 (a different object from the lobby's).
2. The event reaches `LobbyDesktop::OnMouseButtonDown(button 3)`. It notifies its mouse-down observers only
   when the desktop itself is the target: enabled and hovered, or holding the input capture. It then latches
   `pressed[3]`.
3. The observer `WorldScreen::OnMouseButtonDown` maps the button through the table S 00879fd4 = {1, 2, 4, 5, 6}
   to key 5 and calls lobby slot `+0x50`. It takes the input capture only for buttons 1 and 2.
4. `CLobby::OnMouseButtonDown(5)` (modes 2 and 3 only) → `LobbyAction::OnKeyEvent(5, 1)` → base `OnKeyEvent`
   sets `pressedThisFrame[5] = -1`.
5. `LobbyAction::IsMoveForwardDown`: W and Up are tested only without text focus; key 5 is tested outside that
   guard with `IsKeyDown(5, source 2)` = `pressedThisFrame[5] != 0`.
Release: `WM_XBUTTONUP` → event (2, 3) → `LobbyDesktop::OnMouseButtonUp` notifies only when the desktop is the
target again and `pressed[3]` is set → table S 00879fec (same values) → slot `+0x54` → `OnKeyEvent(5, 2)`
clears the entry.
Consequences: the button works only while the cursor is over the 3D world (not over a widget). Because no
capture is taken for button 3, a press over the world followed by a release over a widget never delivers the
key-up: `pressedThisFrame[5]` stays set and the avatar keeps walking forward until the button is pressed and
released over the world again (or the action's keys are reset).
Evidence: S 00401f30 (case 0x20b / 0x20c); S 0042e990; S 0042eab0; S 00431d60; S 00431db0; S 004f4fd0;
S 004f5010; vftable S 007e599c slots 16..24 (read: `OnKeyDown`, `OnKeyUp`, `OnMouseMove`, `OnMouseWheel`,
`OnMouseButtonDown`, `OnMouseButtonUp`, three times S 004f5050); S 00429430; S 00490f50; LobbyAction vftable
S 007d6824 slot `+0x28` = S 00490ff0; S 004295c0.
Spec text changed: `docs/sim/lobby-world-client.md` §10 Q6.

### Controller hit report
Status: STILL NEEDS LIVE (blocked on a file outside the Ghidra project)
Answer: Unchanged on the client side: the global report object S 0087cebc has the vftable S 007e763c whose two
callbacks are `__purecall`; its only writer is the static initialiser and its only user the controller
description. Whether `NxCharacter.dll` calls it cannot be read here: the library is not in the Ghidra project.
The file exists at `~/sadk_game/bin/NxCharacter.dll`; importing it would change the project, so it was not
done. [inferred] from play so far: the avatar's capsule touches the terrain on every step (constant 0.5
downward displacement per step) and the village has run for whole sessions, so the library does not call
the report for the ground contact of an ordinary step; walls and fences are not covered by that argument.
Evidence: xrefs of S 0087cebc (S 005235a7, S 007ce930) and of S 007e763c (S 005232a8, S 007ce930).
Blocked by: `NxCharacter.dll` (calls through the report pointer of the controller object). Needs the
maintainer's import of the library, or the live breakpoint on S 006f371b.
Spec text changed: none

### Limits of the walkable area
Status: NARROWED (data analysed; the library's slope rule still decides)
Answer: The `collision` mesh of `Terrain.KEX` does not fence the avatar with faces steeper than 60°. Method:
every triangle steeper than a limit and at least 1.0 high (the step offset) was projected on the ground
plane on a 0.5-unit grid, and the free cells were flood-filled from the origin (four-connected).
- limit 45° or 48°: the origin is enclosed; the free region is about 9,500 square units, x −56..61.5,
  y −74..92.5 (file axes, z up);
- limit 50° to 60°: the fill reaches the mesh border. With the 60° limit one way out runs from the origin to
  about (18, 10) and then straight in +y to the border at (18, 124); widening every blocking cell by 1.0 (the
  capsule radius twice) does not close it.
So the ring that surrounds the village consists partly of slopes between about 48° and 50°..60°, not of walls.
If slopes up to 60° are walkable as the client's value reads, the avatar can leave the fenced part and reach
the border at ±125, where nothing stops the constant sinking. If the avatar is confined in play, the library
stops it on slopes flatter than 60°, and the slope question (§10 #10) is answered by the same walk.
Evidence: `~/sadk_game_decrypted/kex/lobby/heightmap/Terrain.KEX/mesh1.*` (3,035 vertices, 5,433 triangles;
1,285 triangles steeper than 60°, 1,256 of them at least 1.0 high); slope histogram per 10°: 797, 772, 718,
635, 657, 565, 415, 258, 270, 342.
Limits: a two-dimensional projection (overhangs and stacked faces count as blocking), grid 0.5; the world
axes of the file axes were not mapped.
In the game: from the spawn area walk in the direction that is +y of the file at x ≈ 18; the slope around
y ≈ 90 is the place where the 48° ring is open at 60°.
Spec text changed: `docs/sim/lobby-extras.md` §6.2, §10 Q5.

### 1001 for the own id
Status: SETTLED
Answer: The look changes; the avatar neither moves nor vanishes; the body stays in sync. After the data
blocks are applied to the own proxy (the Location bits are read and dropped), `CLobbyClient::UpdateAvatar`
finds the existing lobby object and asks its controller for the net-controller cast (controller slot
`+0x10`). The own avatar's controller is a `CLocalController`, whose slot `+0x10` is the stub that returns 0,
so no movement sample is pushed. Then `CGfxObjAvatar::UpdateAppearance(false)` runs, as for every avatar.
(For a `CNetController` the same slot returns the object itself; the pair of cast slots is `+0x0c` local,
`+0x10` net.)
Evidence: S 00503620; `CLobbyObj::ctor` S 00502e60 (controller class `character`: `bLocal` → S 0051a1a0, else
S 00519c10); vftable S 007e70e8 (`CLocalController`): slot 3 = S 00519aa0 (returns `this`), slot 4 =
S 0072db80 (returns 0); vftable S 007e70c0 (`CNetController`): slot 3 = S 0072db80, slot 4 = S 00519aa0.
Spec text changed: `docs/village-and-character-protocol.md` §4.1.

### Shop title
Status: SETTLED
Answer: The `ShopName` text is not shown anywhere. `ShopDialog::SetShop` copies it into the dialog
(`ShopDialog +0xb5c`) and nothing reads it: the typed field is used by the constructor, the destructor and
`SetShop` only, the instruction search for displacement 0xb5c / 0xb60 finds no reader inside the dialog's
functions (S 0045b600..0045d7ff: constructor, destructor, the `LEA` in `SetShop`), and the dialog binds four
labels only (`ItemName`, `ItemDescription`, `ItemBuyPrice`, `ItemSellPrice`). The title on screen comes from
the dialog's layout file. Encoding and a leading `!` therefore do not matter; any string is accepted.
Evidence: S 0045d580; S 0045cfe0; S 0045bd70; S 0045d180 (widget names); struct `ShopDialog`; S 004323d0 and
S 004706b0 only pass the string on.
Spec text changed: `docs/message-catalog.md` (0xE11 `ShopName` row). Not edited (outside the allowed files):
`mapping/work/protocol_gaps/stub_differences.md` item 13 can be closed with "not displayed".

### Unknown item id, part (a): on an avatar
Status: SETTLED
Answer: Nothing is attached and the client survives on this path. `SyncEquipmentSlot` gets the placeholder
record for an unknown id (`GetItemInfo` never fails); `ItemInfo::IsValid` is false for it, so an item that
the slot showed before is removed (`ClearSlot`) and `AttachItem` is not called. The slot stays empty. An id
of 0 or a count below 1 takes the same way (clear, nothing attached).
Evidence: S 00507f60 (containers 2, 3, 4, 5 → visual slots 0, 2, 1, 3; both `IsValid` tests); S 00508090 is
its only caller; S 0048b6c0, S 0048b100 as documented.
Not read here: the equipment icons of the selection dialog (documented as `InvalidIcon`).
Spec text changed: `docs/village-and-character-protocol.md` §4.3 ("Unknown id").

### Map type values
Status: SETTLED
Answer: The values are the `MapPath` types of `save-format.md` §2.6: 0 / 1 / 2 / 3 = `.s2m` in
`freeGameMaps` / `campaignMaps` / `tutorialMaps` / `<My Documents>\SAdK\maps`; 10 = `.sav`; 100..103 the same
four folders; 101 = `.a2m`; 110 = `.aav`. What a host sends in `+0x229`:
- the lobby asks `GameFile_LoadMapInfo(name, type 0, …, fallback = true)`. A map found in `freeGameMaps`
  keeps the `mapType` stored in its own `MapInfo` (written by `MapInfo::Store`, read by `Load`; 0 in every
  shipped map as documented in `map-format.md`); the function overwrites `+0x1d0` only when it had to fall
  back: 3 for a file in the Documents folder, 10 for a `.sav`;
- `StartPendingMap` passes the literal 0x6e.
The live reading of 3 and `+0x228` = 1 for two stock maps is the assetshare mod, not the game: its hook of
`NComm_Manager::SetGameSettings` replaces the two arguments by 3 and 1 for every online host
(`lobby/mods/assetshare/assetshare.cpp`, `on_game_settings`). Without the mod a stock map gives 0 and 0.
Evidence: S 005aaa30 (`if (effectiveType != mapType) info->field1d0 = effectiveType`; fallbacks 3 with
`.usermapinfo`, then 10); S 005aa030 (`MapInfo` loaded from the file or its cache); S 00454ad0 (type 0,
fallback true, passes `field1d0`); users of `field1d0`: S 00529db0, S 0052bd40, S 0052b8d0, S 00529a00.
Spec text changed: `docs/types.md` §2.2 `+0x229`.

### Map fetch branch
Status: NARROWED (no memory write needed)
Answer: The static chain is complete and documented (`docs/s2tftp.md`): reader branch in event 0x30003,
`RequestFileFromHost` twice (`.s2m`, `.bmp`), the host's answer from `<My Documents>`, the rename on
completion. The host-side flag does not have to be written into memory: `+0x228` and `+0x229` are plain
arguments of `NComm_Manager::SetGameSettings`, and the assetshare mod already passes 1 and 3 there for an
online host. `docs/BINARY_PATCHES.md` records that with both values forced a joiner received a map it did
not have and the match started (live 2026-10-07). The entry is therefore covered by that record; what is
left is only the name of `+0x228`, which stays `[inferred]` from its one reader.
Evidence: `docs/types.md` §2.2 (S 0040eeb3..0040f30d, S 0040c137); `docs/s2tftp.md`; `assetshare.cpp`
`on_game_settings`.
Spec text changed: `docs/types.md` §2.2 `+0x228`.

### Re-sent 1004
Status: SETTLED
Answer: The visible NPC does not move; its label changes. A kind-1 NPC is created with the class `Settler`
(`gfxclass = "avatar"`, `controllerclass = "character"`), so it gets a `CNetController`, built with the
interpolation mode that the proxy's vftable slot 1 returns: 2 for an `NPCProxy`. Only mode 1 interpolates
samples; in every other mode `CNetController::Update` outputs `samples[0]`, which the constructor filled once
from the creation transform. `PushActorSample`, the one function that copies a proxy position into a
controller, has one caller, `UpdateAvatar` (1001), and `OnNPCAdded` returns when the proxy already has an
object. No function of `CGfxObjAvatar` or `CGfxObjStd` reads the proxy's position or rotation. The name is
different: `CGfxObjAvatar::DrawNameTag` reads `ActorProxy::GetName` when it draws, and 1004 re-reads the
proxy in place, so a new label shows at once. A kind-2 NPC (`Letterbox`, `std` / `std`) has a
`CStaticController` with the constant creation pose and no name tag.
Evidence: S 004f6ea0; `lobbyobj.xml` lines 658 and 1030; S 00502e60 (`character`, not local → S 00519c10
with `proxy->vftable[1]()`); NPCProxy vftable S 007dc7d8 slot 1 = S 004f1ea0 (returns 2); S 00519d50
(`interpMode == 1` branch, else index 0); S 00519c10 (`samples[0]` = transform); S 00519b20 (one caller,
S 00503620); S 005031a0; S 00506860; S 005197f0.
Not read: readers of the proxy position outside the object (the selection distance and the walk-away watch
of the dialogs, the minimap): a moved proxy may move the point the client measures against, not the model.
Spec text changed: `docs/village-and-character-protocol.md` §5.1.

### Open the Debug dialog
Status: SETTLED (no way in the shipped build)
Answer: Nothing opens it. The dialog is slot 1 of the menu system's array at `+0x10`. The functions that
reach a slot by index are `ActivateScreenById`, `Game::ToggleScreen`, `IsScreenAttached` and
`DetachScreenIfAttached`; every call site passes a constant:
- `ActivateScreenById`: 4 (main menu exit, the two requester items of the HUD menu), 6 (two message boxes of
  "continue"), and the id handed through by `ToggleScreen`;
- `ToggleScreen`: 2 (`menu` book function), 7 (key `x`), 5, 0 and 3 (`Game::Update`);
- `DetachScreenIfAttached`: 5, 3, 0;
- `IsScreenAttached`: 1 is only tested (`Game::Update`, `Game::Draw`: is the Debug dialog open); the other call sites test other slots.
The typed field `System +0x14` has no reader, and the Lua libraries `menu` (28 functions) and `editor` have
no function that opens it. The dialog-open call of the queue entry stays the only way.
Evidence: S 005d97a0 (callers S 005dfef0, S 005e27c0, S 005ea960, S 005eb310); S 005ea960 (callers
S 005dd5e0, S 005eb180, S 005efea0); S 005d95f0 (S 005eae90); S 005d97e0 (S 005e3810, S 005efdd0,
S 005efea0); the constants at each call site.
Limit: a load of `[system + 0x14]` through an untyped pointer.
Spec text changed: `docs/sim/map-editor-devtools.md` §10 Q1.

### Editor at work
Status: NARROWED
Answer:
- Terrain generator: `CMapRenderer::RunTerrainGenerator` (slot 1 of vftable S 007f9504, five arguments) is
  not called. Neither it nor its sibling `RunTerrainGeneratorToBuffer` has a direct caller, no function names
  the generator besides the two and the constructor / destructor, and in the whole decompiled image a call
  through slot `+4` with five arguments occurs in four functions, none of which holds a map renderer
  (S 004a5b30, S 00523670, S 00657b80, S 00676700). So generator-dependent heights do not reach the
  simulation, with the editor or without.
- `Scene +0x710`: set to 1 by the constructor, written by `SetFlag710`, and saved, cleared and restored
  around the preview render (`RenderPreviewTexture` calls the scene's `Update` and `Render` in between). No
  reader was found through the typed field; `Scene::Update` S 006805e0 has no byte compare on it. The reader
  sits in the render path below `Render` and was not located.
- Whether the tools respond and whether the file lands in `campaignMaps` needs the open dialog (entry above).
  The target is type 1 = `[data]\maps\campaignMaps\<name>.s2m` (`save-format.md` §2.6).
- `SetBatchEditing`: already settled live (results of 2026-10-12).
Evidence: S 00688540, S 00688590, S 006b24f0 (one caller); S 006890f0; S 0067fb40, S 00680110, S 00681300.
Spec text changed: `docs/sim/engine-core.md` §10 Q5; `docs/sim/map-editor-devtools.md` §10 Q3.

### CVar server
Status: STILL NEEDS LIVE (narrowed)
Answer: Between the patched gate and a listening socket there is no further condition: the first
`RemoteCVarEntry` constructor (the CVars are static objects, so this is during start-up, before `WinMain`)
calls `CVarServer_GetHolder`, whose one-time init creates the server when the gate allows; the constructor
calls `OpenListenSocket(port)` (`WSAStartup(2)`, `socket`, `bind` 0.0.0.0, `listen(10)`) and starts the thread
only if that returned true. Every failure is printed with `wprintf` only, which a windowed process does not
show. "Connection refused" in the attempt of 2026-10-07 therefore means no listener: the patched file was not
the one running, or `bind` / `listen` failed. The lobby debug switches of the entry depend on the same
server.
Evidence: S 0067cba0, S 0067c6d0, S 0067e690, S 0067cc10.
Recipe: after starting the patched copy, `netstat -ano | findstr :1234` on the game PC tells which of the two
it is before any client is tried.
Spec text changed: `docs/sim/map-editor-devtools.md` §10 Q7.

### Dormant LAN path
Status: STILL NEEDS LIVE
Blocked by: two machines. Nothing was added by reading.
Spec text changed: none

### Flag with more than 36 goods
Status: NARROWED
Answer: With the shipped limit the case cannot arise, and when it is forced no rule decides where the good
is drawn.
- The render pile has 6 stacks of 6 slots, keyed by good; a good whose stack is full takes another free
  stack, and `AddItem` merges stacks and retries once. The logic flag has 6 stacks of `FlagPackageLimit`
  packages, one good per stack. For a limit of 6 or less the logic never holds more than the pile can place:
  the pile needs `ceil(count / 6)` stacks per good, the logic uses `ceil(count / limit)`, and the logic total
  is at most 6. So the overflow needs `cfg_setFlagPackageLimit` of 7 or more (shipped: 2, at most 12
  packages).
- When it happens: `AddItem` leaves the item in no stack and still counts it; `ApplySlotTransform` gets
  stack −1, slot −1 from `FindItem` and copies 64 bytes from `pile − 0x1b4` into the item's matrix. The pile
  is its own heap block (0x9b4 bytes, `ItemMgr::CreatePileForFlag`), so those bytes are whatever lies in
  front of the block: the item gets an arbitrary transform. A crash is possible only if that address is not
  readable.
Evidence: S 006cece0; S 006ce7a0; S 006ce970; S 006ce8d0 (one caller, S 0069c390); `streets-transport.md`
§2.4; `config.lua` line 8.
Spec text changed: `docs/sim/world-objects-rendering.md` §10 Q2.
