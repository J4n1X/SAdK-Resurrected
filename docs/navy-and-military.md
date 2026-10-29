# Navy and military: the rules of attacks, defence and sea transport

How a match decides which buildings can be attacked, how many soldiers go, which way they travel (on foot or by
ship), how a fight runs and ends, and how expeditions found colonies. §7 describes what the `navalcombatfix` mod changes.

- Binary: the DRM-free `SADK.exe` (Ghidra `/sadk_noav.exe`). Addresses are static (base `0x400000`).
- Tags: **[known]** = read in the binary at the given address; **[inferred]** = follows from what was read, not
  observed; **[live]** = seen in the running game; **[TODO]** = open. Nothing in this document is [live] yet.
- All of this is simulation code. It runs in the lockstep game on every peer at the same tick
  (`docs/subsystems.md` §2.7), so a change to it must be made identically on every player's machine (a server mod).

## 1. Objects

| Object | Where | What matters here |
|---|---|---|
| Game system | `g_pGameSystem` `0088996c` (`NLogic::System`) | `+0x8` village, `+0x30` map, `+0x40` military, `+0x48` navy |
| Military building | `NVillage::Building` | `+0x8` owner player (first dword = index), `+0xc` `BuildingProperty`, `+0x20/+0x24` cell, `+0xa0` entrance flag ref (cell at flag `+0x28`), `+0xe0` `NVillage::Military` (garrison at `+8`, soldier kind `+0x68`) [known] |
| Territory buildings | `NVillage::System+0x3c` vector (first `+0x40`, last `+0x44`) | Every building whose property byte `+0xf5` is set. All attack and defence dispatch loops walk this list [known] |
| Landmass / water body | `map+0x2c` `NMap::Continents`, per-cell `int` at `+0x1c`, index `y*g_MapWidth+x` | One id per land region and per water body. "Same landmass" below means the same id [known] |
| Harbour | `ai::navy::Harbor` in `NNavy::System+0x44` (`HarborList`, vector `+0x10..+0x14`) | `+0x8` owner (-1 none), `+0x18/+0x1c` unique id, `+0x20/+0x24` cell (the harbour flag), `+0x2c..+0x30` exits [known] |
| Harbour exit | `ai::navy::HarborExit` (0x40) | `+0x18` ref to the ship route through it (valid when `+0x2c` is in `0..0x7fffffff`), `+0x38/+0x3c` water cell [known] |
| Ship route | `ai::navy::NavyShipRoute` (0xa0) | Two end harbours (refs `+0x18`, `+0x38`), ships assigned to it (`+0x5c..+0x60`) [known] |
| Ship | `NNavy::Ship` (0x50) | `+0x8` owner, `+0x24` `NNavy::Movement` (route ref `+0x80`, target harbour ref `+0x60`, state `+0xa4`), `+0x30` expedition, `+0x38` cargo, `+0x40` military mission [known] |
| Fight | `NMilitary::Fight` (0xd0) | `+0x18` attacker, `+0x1c` defender, `+0x24` start countdown, `+0x28` target building ref, `+0x78/+0x7c` attacker/defender soldier lists, `+0xb4` end countdown, `+0xb8` ending, `+0xbc` ships carrying its soldiers [inferred] |

A **ship route** joins two harbours across one water body. Each harbour exit carries at most one route. Ships are
assigned to a route per player [known: `NavyShipRoute::HasPlayerEntry` `005b6bb0`, `CanPlayerAssignShip`
`005b6d30`].

## 2. The attack button

`NMilitary::Attack::GetAttackAvailability(target, attacker, cache)` `005759f0` (`__thiscall`) returns the code shown on the attack button
(`nMenu::ActionButton::RefreshAvailability` `00623da0`) [known]:

| Code | Cause |
|---|---|
| 7 | The attacker's peace-time sacrifice runs: `ai::logic::SacrificeModifierQuery::IsPeaceTimeActive` `00661c30` (`NSacrifice::System+0xc`) tests the player's sacrifice modifier flag 10 (`+0x28`) `> 0` [known]; flag 10 is the int flag of effect index 10, `Effect_PeaceTime` (`docs/sim/military.md` §3.5, §3.9) [known] |
| 5, 1, 6, 3, 7 | From the target's own state, `NVillage::Military::GetAttackTargetState` `0055fd90`: still under construction → 5; not in proximity zone 2 → 1; an unoccupied military building → 6; already under attack (a fight is bound) → 3; the owner's peace time → 7 [known]. The proximity zone is the target's zone B (`docs/sim/military.md` §3.1) |
| 0 / 8 | `Military_IsEnemyTerritoryInRange` (below) is true: 0 if `Military_CountAttackersByKind` finds any soldier, else 8 ("no soldiers") [known] |
| 2, 4, 1 | Otherwise the sea reason from `Military_IsHarborWithinBuildingRange` `00574f70`: route but no ship → 2; ship busy → 4; no route, or no harbour in range → 1 [known] |

**Proximity zones and the flag stripes.** Every military building caches two distances to the enemy, refreshed
every 11 military ticks by `NMilitary::Distances::UpdateBuildingEnemyDistances` `00574e40` [known]:
`GameQueryHelper::MinDistanceToEnemyMilitaryBuilding` `005337e0`, with the diplomacy filter (`Military+0x5c`) and
without it (`+0x58`). Each is the smaller of:
- the distance to the nearest **enemy military building** (cap 1000), in a straight line, **across water too**
  [live 2026-10-08: buildings on the home island had cached distances equal to the straight hex distance to the
  enemy's buildings on another island, 19 and 20 cells, so stripes show across the sea without any route];
- the distance to the nearest **own harbour** on the building's landmass that has a route to an **enemy-owned**
  harbour (`HarborList::FindNearestWithEnemyRoute` `005b5e00` → `Harbor::HasRouteToEnemyHarbor` `005b47d0`).

`ClassifyIndex_0_1_2` `00553f20` turns a distance into a zone: **2 below 19 cells, 1 from 19 to 24, 0 beyond**
[known: thresholds `0x13`/`0x18`; `docs/sim/military.md` §3.1].
- **Zone A** (`+0x5c`, `GetProximityZoneA` `0055fbb0`) draws the stripes on the building's flag (`DrawFlags`
  `006d2820`): two stripes = zone 2, one = zone 1, none = zone 0 [known]. It also enables soldier upgrades in
  `NVillage::Military::Update` `005609b0`.
- **Zone B** (`+0x58`, `GetProximityZoneB` `0055fbe0`) gates attacks on the building: a target outside zone 2 cannot
  be attacked (`GetAttackTargetState` 2 → button code 1) [known].

The stripes are a separate measure from the soldier-count falloff of §3.2, which is full only up to 12 cells. A
building with two stripes (enemy within 18 cells) can still send fewer than all of its soldiers [inferred]. And since
the stripes ignore water while the soldier count does not, a building with stripes across the sea sends nobody
without a sea link (§5).

**Reach test** `Military_IsEnemyTerritoryInRange(target, attacker)` `00575850` [known]:
1. The attacker owns a cell on the hex ring at distance `R + 1` around the target, where `R` is the target's
   territory range: `NVillage::Military::GetTerritoryRange` `0055fca0`, i.e. `bp_setTerritoryRange`
   (`BuildingProperty+0x94`) summed over the owner's slot table. Put plainly: the attacker's land touches the edge of
   the target's land. Only that ring is walked; cells inside it are not tested [known].
2. Or a landing harbour is in range: `HarborList::FindNearestWithPlayerShipRoute(target cell, attacker, owner of the target)`
   finds a harbour **owned by the target's owner** on the target's landmass with a ready route to the attacker
   (§5.1), and it lies closer than `R + 1` to the target.

## 3. How many soldiers a building sends

### 3.1 Per building

`NMilitary::Attack::GetAvailableAttackers(target, building, cache)` `00575dc0` (`__thiscall`, `this` unused, returns
`int`) [known]:
1. `NVillage::Military::CanProvideAttackers` `0055fc60`: not a depot-type building (property byte `+0x54`),
   construction finished, every stationed soldier of the building's soldier kind. Else 0.
2. A building bound to another fight (`Military+0x80/+0x84` valid) gives 0 unless it is the target itself.
3. `reach = Military_GetAttackReachFactor(building, target)` (§3.2). 0 → 0 soldiers.
4. `n` = soldiers present in the building (state `0xc` and inside, `00659370`). Result `(int)(n * reach)`,
   truncated.
5. Unless the building is the target, `Military_IsTargetReachable(target, building, cache, allowSea = true)` must
   hold (§3.3), else 0.

### 3.2 The reach factor

`Military_GetAttackReachFactor(building, target)` `00575320` returns a float in 0..1 [known]:
- **Same landmass:** `Military_DistanceFalloff(building cell, target cell)`. If that is 0, it tries the sea branch.
- **Other landmass (or overland 0):** only if the target's owner is an enemy (`ai::player::Player::IsEnemyOf` `005be280`: different
  ids and different or no team), a landing harbour is in range (`Military_IsHarborWithinBuildingRange`), and
  `HarborList::FindOwnHarborConnectedToTargetHarbor` `005b65d0` finds the building owner's harbour **H2** within 25
  cells of the building with a route to that landing harbour **H1**: then `Military_DistanceFalloff(building, H2)`.
  The distance from H1 to the target is not counted.

**The falloff** `Military_DistanceFalloff(a, b)` `00574fe0`, `d` = hex distance in cells [known: constants
`007e9af8` = 24.0, `007e2a58` = 12.0]:

```
falloff(d) = d >= 24 ? 0 : min(36 - d, 24) / 24     // 1.0 up to d = 12, then down by 1/24 per cell, 0 from d = 24
```

### 3.3 Reachability

`Military_IsTargetReachable(target, building, cache, allowSea)` `00575cb0` [known]:
- On foot: `MilitaryAttack_GetCachedPathLength` `00575b70` between the two entrance cells (one step in direction 1
  from each building cell) is shorter than twice the hex distance. Path lengths are A* results cached in two maps,
  flushed after 111 ticks; the persistent one is saved with the game.
- By sea (`allowSea`): enemy, landing harbour in range, own harbour H2 connected to it, and H2 closer than 24 cells to
  the building.

### 3.4 Dispatch

The attack slider sends a fraction `f`. Per building the count is **`(int)(GetAvailableAttackers * f + 0.5)`**,
evaluated in single precision: `Military_CountAttackersByKind` (at `00576060`), `DispatchAttackers` (`005763a2`) and
`DispatchDefenders` (`005764b1`) all run `FILD available; FMUL float f; FADD double [007d4a90] = 0.5; CALL
__ftol2_sse 006f2af0` (truncation) with the FPU at 24-bit precision, so the result is
`(int)(float)((float)(n·f) + 0.5f)` [known]. Computing in double gives other counts at some fractions: n = 6,
f = 0x3f6aaaaa gives a product 5.49999976 that rounds to 5.5, so the game sends 6 (double: 5); n = 1,
f = 0x3effffff gives a sum that rounds to 1.0, so the game sends 1 (double: 0). This is simulation state.
`Military_GetMinAttackerFraction` `00575f00` gives the slider step: `1 / (2 * the largest single-building count)`.

`Military_CountAttackersByKind(target, attacker, scale, checkAvailability, outCounts, …)` `00575fd0` gives the
slider's labels: over the attacker's territory-building list it adds `ftol(available · scale + 0.5)` (as above)
to `outCounts[building.military.soldierKind]` (`military+0x68`), unchecked and without clearing the counts first
(its callers clear them); with `checkAvailability` set nothing is counted unless `GetAttackAvailability` is 0
[known]. It forwards its `persistentCache` argument to `GetAvailableAttackers`; the menu passes 0 to it, to
`GetAttackAvailability` and to `GetMinAttackerFraction` (S 00623f37, S 00623f50, S 0062473f) [known]. Small wrappers: `Military_IsAttackAvailable` `00575b50` = `GetAttackAvailability == 0`;
`Military_IsField8A0Zero` `00570d10` = fight phase == 0; `Military_IsField24Zero` `00570700` = `startCountdown == 0`
[known].

`ISoldierConnector` (`ISoldierConnector_vftable`) is the interface the dispatchers hand soldiers to [known: vtable
`007e9b04` for `NMilitary::AttackConnector`; `NAI::StrengthCounter` implements it to count soldiers for the AI]:

| Slot | AttackConnector |
|---|---|
| 0 | `AttackConnector::SendSoldiersOverland` `00575660` |
| 1 | `AttackConnector::SendSoldiersBySea` `00575510` (§5.2) |
| 2 | the fight's attacker (`fight+0x18`) |
| 3 | the fight's target building |

- **Attackers:** `NMilitary::Attack::DispatchAttackers` `00576320` walks the attacker's territory buildings and
  sends each one's count through slot 1 if `Military_ShouldAttackBySea` `00576250`, else slot 0.
  `ShouldAttackBySea`: by sea if the walking path is at least twice the hex distance, or if the reach factor beats
  the overland falloff [known].
- **Defenders:** `NMilitary::Attack::DispatchDefenders` `00576400`. The target's own garrison goes completely (slot 0,
  `0x7fffffff`). Every other territory building of the defender sends its count with the fraction stored in the
  target (`target military+0x64`, copied from the defender player's `+0x4c->+0x1c` when the attack starts).
  **Always slot 0, overland** [known]. Since the reach factor's sea branch requires an enemy (§3.2), a defending
  building on another landmass contributes 0 anyway.

Soldier choice: `AttackConnector::SendSoldiersFromBuilding(building, count, ship)` `00575490`. A storage building
releases its whole stock of both kinds; otherwise `AttackConnector::AssignBestSoldiers` `005751e0` takes, level by
level, the soldier with the highest `+0x1ec` (health) and binds it to the fight. Both are `__thiscall` on the
connector and take the fight from it (`connector+4`) [known: disasm `005751f6`, `005752bd`]: a caller must pass the
connector. With a ship it also links the
soldier to that ship's mission (soldier `+0xf8` ↔ mission settler list) [known].

## 4. The fight

**Start.** `NMilitary::Attack::StartAttack(attacker, target, fraction)` `00576500` (lockstep command `0x2000D`,
`HandleStartAttack` `00782cb0`; also the AI's `AttackExecution::Update` `005a0dd0`) [known]:
1. `FightList::CreateFight`, bound to the target.
2. The defender's fraction is copied into the target (above). It is the defending player's own setting, a slider in
   the game [live 2026-10-08: at 50% every helping building sent (int)(available × 0.5 + 0.5), e.g. 1 of 2, 2 of 4,
   3 of 6, by land and by sea alike; at 100% all available soldiers].
3. `g_bSeaAttackDispatch` `0088a4cc` is set to 1, the attackers are dispatched, then it is set back to 0. While it is
   1, a ship of the route that is already on a military mission counts as ready (§5.1).
4. The message `!You are under attack!` goes to the defender.

**Tick.** `NMilitary::Fight::Update` `005715a0` [known; full rules in `docs/sim/military.md` §3.6.1]:
- When the start countdown (`+0x24`) reaches 0: defenders are dispatched (with `g_bSeaAttackDispatch` = 0), the
  fight is recorded in the AI's history, gathering positions are computed, and when either side has no sword
  soldier both contact flags (`+0xcc/+0xcd`) are set, so the archers may shoot at once.
- If the attacker's or the defender's peace-time flag (`+0x28`, effect 10) is set while the fight is in phase
  Fighting (gathering over, target valid and **not** owned by the attacker), the fight starts ending with an end
  countdown of 0.
- While ending (`+0xb8`), at end countdown 0 `ReleaseAttackers` `005714a0` flags every attacker to leave
  (`SoldierFightState+0xa0`).

**Gathering positions.** `MilitaryGatheringPositions_Compute` `00576fb0` [known; exact rules in
`docs/sim/military.md` §3.6.1]: the attackers' origin `Military_GetAttackOriginCell` `00576d00` is the nearest home
building of an attacker on the target's landmass. Failing that, it is the nearest completed territory building of the
first attacker's owner. A landing harbour of the target's owner with a route to the attackers is used instead when it
is closer, or when the building is on another landmass. An A* path from the target's entrance flag to the origin fixes
three cells: centre at half the distance, near/far at ± half the smallest bow range of the fight's bow soldiers
(`+0xa0`). If no path exists, the path goes to the harbour nearest to the target in its water body
(`HarborList::FindNearestInWaterBody`).

**Soldier states** (`NSettlers::Soldier::Update` `006594a0`, state `+0x54`) for the sea [inferred]:

| State | Meaning |
|---|---|
| `0x28` | Entering the fight; with a ship link, walk to the ship's target harbour (ship movement `+0x60`) → `0x34` |
| `0x34` | Walking to the harbour; aboard → `0x37` / `0x33` |
| `0x33` | Aboard; unloaded → `0x29` (pick a target cell, fight) |
| `0x2d` → `0x21` | Leaving the fight. With a ship link: walk to the ship's target harbour (`0x31`), board (`0x32`), unlink when unloaded; then home (`0xe`), or stop when the soldier has no home |

So soldiers always walk to **whichever harbour the ship is heading for**. The ship decides the sides (§5.3).

**Soldiers without a home** [inferred]:
- When its building is gone, `Soldier::OnUnlinkedFromHome` `00659140` clears the soldier's home (`+0x1c0`). The
  soldier leaves the building and reaches state `0x21` without a ship and without a home, then
  `Settler::StopAndSetState3` `00656740`: state 3 with the `MoveToHome` movie (`NMovie::MoveToHome::Start` `007776f0`).
- `MoveToHome` looks for the nearest building of the player that can take the settler
  (`BuildingList_FindNearestReachable` `00557fe0`: same landmass, or a landmass joined by
  `Navy_AreContinentsConnectedForPlayer` `0052eba0`) and walks there over the street network.
- State 3 runs the `LeaveMap` movie (`NMovie::LeaveMap::Update` `00776bd0`) [known]:
  1. It starts `MoveToHome`.
  2. When `MoveToHome::Start` finds no home it can reach, the movie starts **Stray** (aimless wandering) instead.
  3. After each stray walk a soldier loses 1 health (`NSettlers::Livepoints::Damage` `0065dc20`) and `MoveToHome` is tried again.
     Other settlers retry up to 26 times.
  4. The movie ends when the soldier's health reaches 0.
- When the movie ends, `NSettlers::Settler::Update` `00656ec0` puts a settler within 2 cells of a home building into
  it (state 2). Otherwise it calls `StartDying` [known].
- So a soldier with nowhere to go **wanders and slowly loses health until it dies** [live, 2026-10-08: two stranded
  soldiers in state 3 lost 1 health per stray walk; `StartDying` was not called while they had health left].

**Crossing water on foot: sea streets** [known]. A ship route is also a street (type 3) of the street network, built
and removed by `NavyShipRoute::UpdateSeaStreet` `005b71d0`. It exists only while `IsStreetValidForPlayer` `005b6d80`
holds: **both end harbours belong to the player and the player has a ship on the route**. Settlers, soldiers going home
included, walk over it and wait at the harbour flag for a ship (`ai::navy::NavyCargo::AssignWaitingSettlers` `005bd270`).

**Harbour ownership** [known]: a harbour belongs to whoever owns its flag. `Harbor::AttachFlag` `005b49f0` copies the
flag's owner and refreshes the sea streets of its routes. When the flag goes, `005b5370` (via
`NavyLink_UnlinkHarborBuilding` `0053c1f0`) sets the harbour to -1 and unlinks the ships from its exits. So when a
player loses the territory around a harbour, the harbour turns neutral (-1) and every sea street through it disappears.
That holds whether the ground became nobody's or an enemy's. The territory map (`NMap::Territory+0x14`, one int per
cell, -1 = nobody) tells the two apart.

Together: destroying one's last military building on the far side takes the harbour's flag with the territory. The
sea street home disappears, and its soldiers wander until they die [live].

## 5. Sea transport for fights

### 5.1 Finding harbours

- `HarborList::FindNearestWithPlayerShipRoute(pos, shipPlayer, harbourOwner, militaryActive, *status)` `005b6090`:
  among the harbours **owned by `harbourOwner`** on `pos`'s landmass, the nearest one that is ready for
  `shipPlayer` [known]. Every sea check of §2–§4 uses it with `harbourOwner` = the target's owner. `*status` is
  the readiness of the **last** harbour evaluated, not of the one returned [known].
- Readiness: `Harbor::EvaluateRouteToPlayer(h, player, player, militaryActive)` `005b48c0` looks at each exit route
  of `h` whose far end belongs to `player`. It returns 0 (ready) if the player has no ship on that route but an idle
  ship of the player can be found for its exit (`NNavy::System::FindNearestIdleShipAtHarborExit` `005b3450`: same
  water body, not moving, no route, movement state 0/4, `CanPlayerAssignShip`). With `militaryActive`, it also
  returns 0 if the player's ship on the route has an active mission. Otherwise it returns 1 (route, no ship), 3 (the
  player's ship is busy) or 2 (no route to the player) [known].
- `HarborList::FindNearestConnectedTo(pos, player, other, maxDist)` `005b5f50`: the player's harbour on `pos`'s
  landmass with an exit route to `other`, nearest to `pos` and closer than `maxDist` [known].
- `FindOwnHarborConnectedToTargetHarbor(from, targetPos, player, targetOwner, militaryActive)` `005b65d0`:
  H1 = `FindNearestWithPlayerShipRoute(targetPos, player, targetOwner)`, then H2 =
  `FindNearestConnectedTo(from, player, H1, 25)` [known].

### 5.2 Sending soldiers by sea

`AttackConnector::SendSoldiersBySea(building, count)` `00575510` [known]:
1. H2 via `FindOwnHarborConnectedToTargetHarbor(building, target, building owner, target owner, 1)` and
   H1 via `FindNearestWithPlayerShipRoute`. H1 must be closer than the target's range + 1.
2. The route = the route of H2's exit towards H1.
3. If the **connector's player** (the attacker) already has a ship on the route, that ship is used only if its mission
   is active and carries this fight. Otherwise the nearest idle ship of that player at H2's exit is linked to the route
   (`NavyLink_LinkMilitaryRoute` `0053c0d0`) and to the fight (`NavyLink_LinkMilitaryFight` `0053c130`). This
   activates the ship's mission.
4. `AttackConnector::SendSoldiersFromBuilding(building, count, ship)` with the connector as `this`.

Any failure returns silently: the soldiers just stay home.

**One ship per player per route** [known]: `NavyShipRoute::CanPlayerAssignShip` `005b6d30` refuses a player who
already has a ship on the route, or who owns neither end. `FindNearestIdleShipAtHarborExit` returns nothing for such
a route. The consequences [inferred]:
- Two ships of the attacker never serve the same route. Every building whose H2 is the same harbour loads onto the
  one ship of that route. A second idle ship is not used.
- If the player's ship on the route is busy with another fight, `SendSoldiersBySea` returns without sending. The
  attack button still says "ready" when it is pressed, because `g_bSeaAttackDispatch` makes a ship with an active
  mission count as ready. So the soldiers from that route stay home.
- Two routes to the same H1 (two own harbours, or two exits) carry two ships: each building takes the route of its
  own nearest H2 (`FindNearestConnectedTo`), so the buildings split between the ships by distance.
- Manual route assignment (`GetAssignShipBlockReason` `005ba970`, lockstep `0x2001A`) refuses a route whose two ends
  both belong to the player (reason 2). Military dispatch does not go through that check, so such a route still
  takes a military ship.
- [TODO] Whether the ship's size (`sh_setSize`, `ShipConfig+0x10`) limits the soldiers a mission boards:
  `BoardSettlersAtHarbor` `005b9f30` boards every mission soldier and checks no limit.

### 5.3 The ship's mission

`NNavy::Military::Update` `005ba250` (ship `+0x40`, state `+0x40`). It runs only while the mission is active and
the ship is not moving (movement float `+0x20` ≤ 0, movement state 0 or 4) [known]:

| State | Action |
|---|---|
| 0 | Sail to the route end **owned by the ship's player** (`NavyShipRoute::GetEndHarborOwnedBy` `005b6970`, end A checked first) → 1 |
| 1 | Unload any cargo; when idle → 2 |
| 2 | If all mission soldiers have left their fight → 7; else board those that have not (standing on the harbour, idle) → 3 when all are aboard |
| 3 | Sail to the route end **owned by the fight's defender** (`fight+0x1c`) → 4; no such end → 7 |
| 4 | Disembark one soldier per tick; when empty, or when all have left the fight → 5 |
| 5 | Board the soldiers that left the fight → 6 when all are aboard. "All" are the soldiers still in the mission's list: the dead leave it through their release (`Soldier::ReleaseLinks` → `NavyLink_UnlinkMilitarySoldier`), the capturers when they join the captured building (`Military_TryAssignSoldierToBuilding` S 00574c50), so after a capture only the soldiers walking back to the landing harbour (soldier states 0x21 → 0x31) are waited for [known] |
| 6 | Sail to the opposite end of the route → 7 |
| 7 | Disembark one per tick, unlinking mission soldiers; when empty `NNavy::Military::Finish` `005ba190` |

Ship states (`Ship+0x28`) [inferred]: 0 idle, 1 waiting, 2 loading, 3 unloading/sailing, 4 expedition, 5 military,
6 sinking, 7 sunk, 8 doomed.

**Where ships are deleted** [known: callers of `NNavy::Ship::dtor` `005baf20`]: `NNavy::System::Update` `005b39d0`
deletes a ship as soon as it reaches state 7 (sunk). `NNavy::System::EraseShipByUnique` `005b3890` deletes one at
once, without sinking and without a last `Ship::Update`; it is called by the scripts' `na_destroyShip`
(`GameScript_Lua_na_destroyShip` `005af2a0`), `TransferShipsOfPlayer` `005b44e0`, the editor tool
(`HandleToolClick` `00604dd0`) and the destructor at `0055e8c0`. `NNavy::System::DeleteAllShips` `005b3c40` deletes
them all when the logic is reset between matches (`NLogic::System::Reset` `00526f80`, after the selection is reset).

**A deleted ship stays selected** [known; live 2026-10-09]: the game deselects removed buildings
(`Selection::ClearIfBuildingSelected` `00535220`), but has no such step for ships. The selection's ship reference
(`Selection::ship`, `+0x88`) keeps its cached pointer (`ReferenceShip::Resolve` `0053a450`), and
`nMenu::InfoBoxShip::Update` `0063c100` uses it without a check: a ship deleted while selected crashes the game on
the next frame. The `navalcombatfix` mod deselects it in its hook on `NNavy::Ship::dtor`, which every deletion path
passes.

## 6. Expeditions

`NNavy::Expedition::Update` `005b8ac0` (ship `+0x30`, state `+0x4c`) [inferred]:

| State | Action |
|---|---|
| any but 7/8 | If both ends of the ship's route already belong to the player → 7 |
| 0 | Sail to the start harbour (`ChooseStartHarbor` `005b7b80`) → 2 |
| 2 | Unload; idle → 3 |
| 3 | Gather the cargo (soldiers, building goods); ready → sail to the other end → 4 |
| 4 | Reveal radius 10 around the target harbour. Unowned → `!Ship waiting for Orders` → 5; owned → `!Harbor is already captured!` → 7 |
| 5 | Wait for the player's order (lockstep `0x2001C` → `OrderPlayerExpeditionFoundColony` `005ba8f0` → 6). Captured meanwhile → 7 |
| 6 | Found the colony (below); no building position → `!No Valid Position for Building found!` → 7 |
| 7 | Release units and orders, sail back → 8 |
| 8 | Unload; idle → finished |

**Founding a colony** (state 6) [known]: `NVillage::System::PlaceExpeditionBuilding` `0055a820` adds a territory
source of radius 4 for the player. It places the tribe's expedition building (`sh_setExpeditionBuilding`, `ShipConfig+0x24`)
completed at once. `Harbor::PlaceFlagAndRevealExitsForCellOwner` gives the **landing harbour to the colonist**. A
street joins the harbour flag to the building, the expedition's soldiers become its garrison, and the building's cost
is taken from the cargo.

From then on the colonist owns both ends of that route. In the game's rules (§2, §3) the colony is reached by sea
only through harbours owned by the **target's** owner, so the colonist cannot attack by sea from it. The only attacks
possible are on foot from the expedition building's garrison, against targets whose land its small territory touches
[inferred].

**What founding needs from the land** [known]:
- The building position: `FindBuildingPosition` `005b7e50` walks hex rings 1 .. `territoryRange` − 1 around the
  harbour (`MapRingIterator_Next` `00600e90`: each ring starts in direction 4, then steps through directions 0..5).
  It takes the first cell on the harbour's landmass whose entrance (one step in direction 1) is more than one cell
  from the harbour and that passes `GameQuery::CanPlaceBuildingAt` `0052fbe0`. That test reads the owner of the
  centre, of the footprint (`ai::village::FootprintIter::Init`/`Next` `0055abf0`/`0055ac80`: one cell, or four for
  a shape with none of the size bits `0x1b`) and of the entrance flag cell, all with borders allowed. It refuses any
  territory building within 4 cells (`HasNoTerritoryBuildingWithinRadius4`).
- An unowned harbour: state 6 goes back to state 5 while the harbour has an owner.
- The street: `PlaceFlagAndRevealExitsForCellOwner` `005b5670` places a flag for whoever owns the harbour cell.
  `StreetPlanner::BuildStreet` `006636e0` starts only on the colonist's own flag there. `ExtendTo` `00663bf0` runs
  `NMap::AStar::FindPath` with `NLogic::AStarStreet`, whose cells must be the colonist's and not border cells
  (`GameQuery::CanStreetPassCell` `0052fb10`, `AStarStreet::GetStepCost` `00776500`). A border cell is an owned cell
  with a neighbour of another owner (`MapCellUpdater::IsTerritoryBorderCell` `0067b5a0`).

**Territory** [known]: each cell's owner is computed from the territory sources (`Territory_ComputeCellOwner`
`00679510`): a source within 2 cells takes the cell outright; otherwise each source weighs radius / distance² (radius
doubled within 5 cells, nothing beyond it) and the strongest player gets it. `PlaceExpeditionBuilding` adds a source
of radius 4, and the building's own territory follows, so the land around a new colony is contested by its
neighbours' sources. After a change, `MapModifier::OnTerritoryChangedAt` `00673a50` refreshes the border bits and the
construction map, removes streets on land no longer their owner's (`RemoveForeignStreetsInRadius` `00665930`) and
marks buildings outside their land. Every tick, `NNet::System::Update` `00665ef0` removes each flag that no longer
stands on its owner's land (`00669e30`). A harbour loses its owner when its flag goes (`005b5370`; the flag is
`ai::navy::Harbor::flagRef`, +0x38).

**Street networks** [known]: every flag keeps a network id per kind (`NLogic_UniqueArray40_IsEqualAt` `00663d90`,
flood fill `NNet_CollectConnectedFlags` `00666250` over `Flag::linksFirst`, one `FlagLink` per street: other flag at
+0x8, street at +0x28). Kind 1 counts every street, kind 0 only streets with a carrier. Sea streets (type 3, built by
`NavyShipRoute::UpdateSeaStreet` `005b71d0` between two harbours of one player) count for both
(`NNet::Street::ctor` `00669cd0`).

### 6.1 The buoy's buttons and the ship-route commands

A selected ship route (its buoy) shows the in-game action panel: 4 button slots
(`nMenu::ActionButtonPanel.actionButtons`, at `nMenu::Game+0x8000`).
- `MenuSelection::SetSelectionKind` `00616f40` fills them per selection kind. A ship route (menu kind 0) gets actions 1
  start expedition, 2 stop, 3 found colony; **slot 4 stays empty** [known].
- An action is a number 0..30 (`ActionButton.action`). `ActionButton::RefreshAvailability` `00623da0` decides, per
  action, whether it is possible and why not. `ActionButton::ExecuteAction` `00623730` turns it into a lockstep game
  command for the selection [known].
- Static tables indexed by the action give its name (`g_ActionNames`, used by the layout XML
  `game\ui\layout\menuingame.xml`), icon (`g_ActionIconRects`), tooltip (`g_IngameCommandNames`, e.g.
  `!START EXPEDITION`) and failure texts (`Action_<name>_<code>` tags in the XML) [known].

Ship-route commands (`EventInt64_1Integer`: the route's id and the player) [inferred]:

| Id | Sent by | Run by |
|---|---|---|
| `0x2001A` | `SendCommand_2001A` `00782d80` | `HandleAssignShipToRoute` `00781ad0`: if `NavyShipRouteBackRef::CanAssignShip`, `AssignNearestIdleShip`. Assigning (`0053c010`) also switches the ship's expedition on (state 0) |
| `0x2001B` | `SendCommand_2001B` | `HandleAbortShipRouteJob` `00781b70`: `AbortPlayerExpedition` (state 7) |
| `0x2001C` | `SendCommand_2001C` | `OrderPlayerExpeditionFoundColony` `005ba8f0`: state 5 → 6 |

**Assigning a ship to a route is starting an expedition.** Manual assignment is refused for a route whose ends both
belong to the player (`GetAssignShipBlockReason` reason 2), so it only exists for routes toward someone else's or a
free harbour [inferred]. Every command passes `nGame::System::HandleGameCommand` `007845a0`, which handles ids
`0x20002`..`0x2002B` and **ignores any other** [known].

The expedition (`NNavy::Expedition`, `Ship+0x30`):
- `+0xc` its soldier orders, `+0x20` its requests for the building's goods, `+0x38` its soldiers, `+0x4c` its state.
- All of it is saved (`Expedition::Store` `005b7d30`) [known].
- A ship runs either its expedition (ship state 4) or its military mission (state 5), never both (`Ship::Update`
  `005bb500`) [known].
- `Ship::ScheduleSinkingNoDelay` `005bb250` (used by the Lua `na_sinkShipOnRoute`; formerly named `SinkImmediately`) sets
  ship state 8 (sink scheduled). A moving ship is flagged to stop but **finishes its current step to the next grid
  cell** [known; maintainer, live]. Once it lies still, `Ship::Update` calls `Ship::BeginSinking` `005bb010`
  (condition −100, state 6 for `ShipConfig::sinkingTime`); then state 7, and `NNavy::System::Update` deletes it.
  `Ship::ScheduleSinking` `005bb210` is the same with a 30-tick countdown; its caller is the sacrifice that sinks
  ships (`ApplySinkTargetShips`).

## 7. The `navalcombatfix` mod: soldiers cross through their own harbours

`mods/navalcombatfix/` (`combat.cpp`, `retreat.cpp`; a server mod: every player of a match needs it). These are rules the maintainer
decided, not a restoration of lost behaviour. Every case the game already handles runs the game's code unchanged.

**Across the water.** The mod's test is the game's own foot test, not the landmass: a building is across the water
from a target when `Military_IsTargetReachable`'s first half fails (§3.3: the walk between the two entrance cells,
`MilitaryAttack_GetCachedPathLength` `00575b70`, is not shorter than twice the hex distance; 0x7fffffff without a
path). Two landmasses always fail it, so the A* runs only within one. A harbour is on a building's side of the water
when the same test holds for the walk from the building's entrance to the harbour cell (the harbour's flag stands
there; `NMap::AStar`'s precondition slot `0041eca0` takes any two cells), with the walk allowed at least 12 steps next
to the building, which twice a small hex distance does not leave for a way round the building [inferred: the bound is
the mod's]. The harbour walks use the volatile cache, as the attack menu does. A map whose parts are joined only far
away needs this: Gold Henge is four quadrants around a cross of channels, joined by a land bridge in the middle, one
landmass [save of 2026-10-29: all 16 harbours and 275 territory buildings on continent 1]. A defender across a strait
there failed the game's test (whose sea branch needs an enemy, §3.3) and sent nobody, and a test by landmass never
applied.

**Own sea link.** For a building of player P across the water from the target, the mod considers every pair of P's
own harbours: H1 on the target's side, H2 on the building's side, and the route from H2's exit to H1. The hex sum
below is checked before the two harbour walks.
A pair counts only if **its own route has a ship for these soldiers**, by the checks `SendSoldiersBySea` makes
(§5.2). The ship is one of these:
- P's ship already on that route, carrying the fight being dispatched;
- P's ship serving that route (ship states 0-3: idle, waiting, loading, carrying; no mission, no expedition): the
  ship of the route's sea street. The game's idle-ship search skips it, because a route takes one ship per player
  [live 2026-10-08: such a ship made every attack over its route count only the target's landmass]. It is taken
  **whatever it is doing**, so a fight never depends on when the ship is free (maintainer's rule):
  - passengers assigned to board it are released (`ai::navy::NavyCargo::UnassignPendingSettlers` `005bd3b0`);
  - its mission starts (`NNavy::Military::Activate` `005b9cd0`; it stays linked to its route) and the fight is linked;
  - ship state 0: `Ship::Update` `005bb500` starts a mission only from 0 (→ 5), and a route ship cycles through 1-3
    [live 2026-10-08: left in 1, the mission never ran and the ship stayed stuck];
  - it is sent at once to the harbour on the soldiers' side (`Movement::MoveToHarbor`; re-planning from the current
    cell is what `NMovement::Base::StartMoveTo` `00772b00` does), since soldiers walk to the ship's target harbour as
    soon as they leave their buildings. The mission's first step unloads the cargo there; the economy asks for those
    goods again.
  When the mission ends, `Ship::Update` calls `Ship::ReturnToOwnHarbor` `005bab60`, which puts the ship on a route of
  its nearest home harbour, not necessarily the one it served. While that route is still a sea street, the mod puts
  the ship back on it the same way (`NavyLink_LinkMovementRoute` `0053c3d0` + `MoveToHarbor` to its nearer end +
  state 3, unload then wait): its service resumes. This bookkeeping is not saved with the game. A ship sunk after a
  defeat is not put back.
  When a harbour changes hands, `Ship::Update` ends the missions of the ships on its routes and sets state 0 without
  sending them anywhere; a ship under way stays where it stopped (still reading movement state 4, AtHarbor), out of
  every idle-ship search [live 2026-10-08: a defending ship stopped at sea after its harbour fell]. The mod sends such
  a stranded ship (state 0, no route, stopped mid-voyage) home with `Ship::ReturnToOwnHarbor`;
- an idle ship found at H2's exit, when P has no ship on the route;
- failing that, P's nearest ship serving **another** sea street (same water body as H2's exit, hex distance). Idle
  ships have no route, and every idle ship puts itself on a sea street that has none (`sim/navy.md` §3.8,
  `FindOwnRouteForShip` takes the first such exit in order), so a player with no more ships than sea streets has no
  idle ship: of a harbour with two routes and one ship, only the route the ship went to could carry a fight. The
  ship is taken as above, except that it leaves its street (`NavyLink_UnlinkMovementRoute` `0053c3f0`; the street
  goes while it has no ship) and is linked to the route like an idle ship (`NavyLink_LinkMilitaryRoute`). After the
  mission it goes back to the street it served, unless the player has another ship there by then
  [TODO, live: not tested in the game].

Of the usable pairs the one with the smallest **d(target, H1) + d(H2, building)** below
24 wins. Counting and sending use the same search, so a building is counted only with soldiers its ship can actually
take. A blocked route falls back to the next-best pair and its ship.

The fight being dispatched is recorded while `Attack::DispatchAttackers` or `DispatchDefenders` runs with a real
`AttackConnector`. Outside a dispatch (the attack button, the AI's `StrengthCounter`) there is no fight, so only routes
with an idle ship count. This replaces the game's looser test (`EvaluateRouteToPlayer`: any route at H1 with a ready
ship), and `g_bSeaAttackDispatch`, for the mod's own cases.

| Hooked | Change |
|---|---|
| `Military_GetAttackReachFactor` | When the game returns 0: `falloff(d(target, H1) + d(H2, building))` of the own sea link. The crossing counts as zero length, and the ground rule of §3.2 applies to the remaining walk. For attackers and defenders alike. On the target's landmass the game's own value (the falloff of the straight distance, which the game's own sea attacks there use too) stays |
| `Military_IsTargetReachable` | Also true (with `allowSea`) when an own sea link exists |
| `Military_IsEnemyTerritoryInRange` | Also true when a harbour of the attacker lies on the target's side of the water closer than the target's range + 1 + `LandingReach`, with a route to an attacker's harbour across the water and a ship for it: the game's harbour test of §2 without its owner condition. This makes targets around a colony's (or a neutral landing's) harbour attackable |
| `Military_IsHarborWithinBuildingRange` | The game's landing test for an enemy-owned harbour (§2): `LandingReach` cells beyond the target's range + 1. The attack button, the reach factor and the reachability test all use it |
| `NMilitary::Attack::DispatchAttackers` | Unchanged; only records the fight being dispatched |
| `NMilitary::Attack::DispatchDefenders` | Reimplemented with the game's counts (and records the fight). A building across the water from the target sends through slot 1 (by sea) instead of slot 0; its foot test reads the persistent cache, where `GetAvailableAttackers` has just put the same walk |
| `NMilitary::AttackConnector::SendSoldiersBySea` | The game's code where the game's own sea rule counted the building: through the reach factor's sea branch (another landmass, or no overland falloff), or, on the target's landmass, for an attacker the game's reachability test passes (an enemy landing harbour, §3.3). Otherwise the own sea link it was counted with, using the ships of the **building's owner** (the game would use the attacker's, which is wrong for defenders) |
| `NNavy::Military::Update` | States 0 and 3, when both route ends belong to the ship's player: load at the end on the building side and land at the end on the target's side of the water. State 5 (`ShipLostOnDefeat`): see below |

**Retreat pickup.** `NMovie::MoveToHome::Start` is hooked. Where it finds no home for a healthy soldier in state 3
(the moment the game would let it stray, see §4), a ship picks the soldier up instead, when there is:
- a harbour on its landmass that `ValidRetreatHarbors` allows. The harbour counts as the land owner's at its flag
  cell (its own owner when that cell is nobody's). `neutral` (the default): nobody's. `friendly`: also a team mate's
  (`ai::player::Player::IsEnemyOf` `005be280`: a different index and a different team, or team -1, is an enemy).
  `all`: also an enemy's. The player's own harbours are never used: their sea streets are the game's way home.
  `own` turns the pickup off;
- with a route to a harbour of the soldier's player;
- and either one of the player's ships already waiting there, or an idle one for that route.

The ship gets a transport mission without a fight (`NavyLink_LinkMilitaryRoute`), sails to that harbour and
waits in state 2, where the game boards the soldiers standing on it. The soldier is linked to the ship (`NavyLink_LinkMilitarySoldier` `0053c070`) and
set to state `0x21`, so it walks to the ship's harbour like a soldier coming back from a fight. When all are aboard,
or after a timeout (1200 ticks, [TODO] tune), state 3 sails to the other end of the route, and the game's state 7
unloads. The soldiers, with a reachable home again, walk into a building. A mission without a fight is only ever a
pickup. The game would read a null fight in its state 3, so the mod handles every mission without a fight in state 3.

| Hooked | Change |
|---|---|
| `NMovie::MoveToHome::Start` | The retreat pickup above, where the game finds no home |
| `NNavy::Military::Update` | Also: missions without a fight (pickups) wait in state 2 with a timeout, and sail to the other route end in state 3 |

**Landing harbours** (`landing.cpp`). Wherever the rules above say "H1 of the player", a **neutral** harbour also
counts as H1 when the player could not found a colony there (`NeutralLandings`). The test is the game's own colony
placement, `NNavy::Expedition::FindBuildingPosition` `005b7e50`, without the expedition:
- the tribe's expedition building;
- the cells within its `territoryRange - 1` of the harbour, on its landmass, whose entrance is more than 1 cell from
  it;
- `GameQuery::CanPlaceBuildingTypeAt` `005301c0`, with the expedition's arguments. One of them is player entry 8 of
  the player table, whose role is [TODO].

With room for the colony, the harbour is not a landing: found the colony instead. The ship's mission sails to an own
or a neutral landing end (`own_route_ends`). The distance to the enemy uses the same landings in both directions.

**Proximity zones** (§2; `proximity.cpp`). `GameQueryHelper::MinDistanceToEnemyMilitaryBuilding` is hooked. With
`includeHarbors`, the distance to the enemy is also measured over routes whose ends belong to the same player, with
the sum the soldier count uses. Like the game, there's no ship requirement: the route only has to exist.
- **Own route:** an own harbour H2 on this landmass, a route to an own harbour H1 elsewhere:
  d(here, H2) + d(H1, nearest enemy military building on H1's landmass). Buildings whose soldiers cross through their
  owner's harbours get the stripes for it.
- **The enemy's own route:** an enemy's harbour H1 on this landmass, a route to that enemy's harbour H2 elsewhere:
  d(here, H1) + d(H2, nearest military building of that enemy on H2's landmass). A target near a colony's harbour
  reaches zone 2 through the colonist's route home, so the zone-B gate no longer blocks the new attacks.

The game's own distance stays when it is smaller. The enemy filters are the game's (`Player::IsEnemyOf`, the
diplomacy flags, an active territory). Because the zones also enable soldier upgrades (zone A), this changes play,
not just the display.

| Hooked | Change |
|---|---|
| `GameQueryHelper::MinDistanceToEnemyMilitaryBuilding` | Also over routes between two harbours of the same player (both directions above) |

**Naval invasion** (`invasion.cpp`; rules in `mods/navalcombatfix/CONCEPT.md`):
- **Scouting:** in the expedition's arrival (state 4), a free harbour without room for a colony is revealed. The
  ship then sends the game's "No Valid Position for Building found!" and returns (state 7), instead of waiting for
  orders.
- **The button:** "Prepare naval invasion" goes in the ship-route panel's free slot 4 as action 31.
  - Enabled for a route from an own harbour to a neutral one that the player has explored (radius 3), where no colony
    fits, with an idle ship for the route.
  - The game's tables stop at action 30, so the button takes the attack button's icon and look (action 11) and gets
    its own texts.
- **The command:** pressing it sends command `0x20040` (`EventInt64_1Integer`, built like `SendCommand_2001A`). Each
  peer's hook on `HandleGameCommand` assigns a ship as `0x2001A` does, which starts its expedition, and puts the
  expedition into state 100.
- **The invasion's states** are expedition states, so they are saved:

| State | Action |
|---|---|
| 100 | sail to the route's own end (`ChooseStartHarbor`) |
| 101 | unload |
| 102 | `GatherCargo`: the soldier and the building's goods |
| 103 | ready, waiting at home. An attack whose sea link uses this route links its fight to the ship (`combat.cpp`; only for attackers) |
| 104 | the attackers board (`BoardSettlersAtHarbor`, up to `PickupTimeout`); nobody came → back to 103 |
| 105 | sail; on arrival only the mission's soldiers land (`NavyLink_UnlinkCargoSettler` + `DisembarkAt`) |
| 106 | until all have left the fight. Won (see below) → 107. Cancelled → state 7 (home, unload). Lost → `ShipLostOnDefeat` and the landing not the player's: `ScheduleSinkingNoDelay`, else state 7 |
| 107 | the survivors board again, then the game's state 6 founds the colony |

- **After the colony:** the ship switches to its military mission, state 6, which takes the attackers home and
  unloads them. If there is still no room, the game's own failure path (message, return, unload) applies.

Tested in the game 2026-10-08 (maintainer): naval invasions work.

Messages in the player's event log (navy type, the ship's name as the subject): invasion ready, won (colony founded),
lost (ship sank / returns), called off; attack by sea lost (ship sank). The game shows a message's text through
`Localization::GetText` (`nMenu::Messages::SetupSlot` `005f75a0`), so the mod enters its own keys
(`!navalcombatfix_*`) with English texts into the localisation table (`Localization::translations`) first. Still to check in detail:
- the scouting message;
- the button's states;
- loading and waiting;
- boarding and landing (only the attackers land);
- the colony after a win, and the attackers' trip home;
- sinking and the cancelled return after a defeat;
- saving and loading while an invasion waits.

**Lost attacks by sea** (`ShipLostOnDefeat`, `combat.cpp`). A mission of the fight's attacker (`Fight::attackerPlayer`)
in state 5, at the landing, once all its soldiers have left the fight: if the fight is lost **and the landing harbour
is not the attacker's** (an attack from an own harbour is a coastal attack), `NNavy::Military::Finish` and
`Ship::ScheduleSinkingNoDelay`. The outcome uses the game's phase, `NMilitary::Fight::GetPhase` `005708a0` [known]:
- Fighting (0): the target still stands and its owner is not the attacker: **lost**;
- TargetCaptured (3), NoTarget (4, the target is gone), or Ending (2) with the target the attacker's: **won**;
- Ending with the target not the attacker's: **cancelled**. Calling an attack off (lockstep `0x2000E`,
  `nGame::System::HandleCancelAttack` `00782bf0` → `Military_RequestCancel` `00570900`) sets the fight's ending flag
  (`Fight::bEnding`) as holding the target does [known]. A cancelled attack never sinks a ship; a cancelled invasion
  sails home and unloads.

Every attack by sea is covered, the game's own (landing at the defender's harbour) as well as the mod's, and the
invasion (state 106).

**Ending a mission pulls its soldiers out of the fight** [known; live 2026-10-09]: `NNavy::Military::Finish`
`005ba190` → `NavyLink_UnlinkMilitaryFight` `0053c160` → `NMilitary::Fight::RemoveShip` `00571500` takes every soldier
of the mission still in that fight out of it (`0053cfe0`), ashore or aboard. The game ends a mission normally only
after its soldiers have left the fight, but `Ship::Update` also ends it when the ship's route is cut (a harbour of it
changes hands). Soldiers still fighting ashore are then pulled out mid-strike; the fight can lose its last members and
be deleted, and a soldier finishing its strike reads a null fight (`NMovie::Fight::TryApplyStrike` →
`Fight::ComputeSoldierStrikeValue`, crash at `005721b1`; or `Fight::OpposingSideHasEngageableSoldierFor`, crash at `005711cb`). The
unmodded game has the same path (an attacker's home harbour taken mid-attack). The mod hooks `Military::Finish`: the
mission's soldiers ashore and still in its fight are unlinked from the ship first (`NavyLink_UnlinkMilitarySoldier`),
so they fight on without a ship.

**Soldiers aboard keep their in-fight mark** [known (static); live 2026-10-10]: a soldier sent to a fight by sea is in
the fight before it boards (`Soldier::Update` `006594a0` state 7 calls `SoldierFightState::EnterFight` `0065b840`,
`inFight = 1`; the sea states `0x34`/`0x37`/`0x33` follow). `RemoveShip` takes it out of the fight through `0053cfe0`
(`Fight::RemoveSoldier`, then the soldier's `fightState.fightRef` is cleared) and leaves `inFight` set. When such a
soldier is deleted, `SoldierFightState::Destruct` `0065c080` sees `inFight` and calls `ReleaseAll` `0065bfe0`, which
passes the null result of `ReferenceFight::Get` to `Fight::RemoveSoldier` (crash at `005719e3`). A ship deleted with
an active mission does exactly this: `Ship::dtor` ends the mission, then `ai::navy::NavyCargo::dtor` `005bd7f0` deletes the
settlers aboard. The crash dump has this stack; that the soldier was on its way to the fight is `[inferred]`. The
unmodded game has the same path; ShipLostOnDefeat makes it common, but it occurs without it too [live 2026-10-17: the
same crash and stack, `NLogic::System::Update` → `NNavy::System::Update` → `Ship::dtor` → `NavyCargo::dtor` →
`ReleaseAll` → `RemoveSoldier(null)`, in an hour-long match whose host ran a mod build from before the fix below,
ShipLostOnDefeat off]. In its `Military::Finish` hook the mod lets the mission's soldiers who are aboard and marked
leave the fight after the game's `Finish`, as the game's state `0x2d` does (`SoldierFightState::LeaveFight`
`0065be90`). `ReleaseAll` hands `ReferenceFight::Get` to `MilitaryLink_UnlinkSoldierFromFight` `0053cfe0` without a
test, and only `ReleaseAll` can pass a null fight there (its other callers, `Fight::RemoveShip` and
`MilitaryFightSoldierList_dtor` `00576a20`, pass the fight the soldier is listed in) `[known]`; the mod's hook on
`0053cfe0` therefore takes a null fight as "nothing to leave" and only clears the soldier's fight reference, as the
function does after `RemoveSoldier`, which covers any other way to the same state. Both in the game `[TODO]`.

A sinking ship keeps its mission: the game deletes a sunk ship at state 7, and `NNavy::Ship::dtor` `005baf20` ends an
active mission then. Ending it at once (`Military::Finish`) would release the fight while its last soldiers were only
just leaving it: `MilitaryFightList_Update` deletes an inactive fight the same tick, and a garrison soldier still in
state `0xF` then reads it (`Fight::OpposingSideHasEngageableSoldierFor` on a null fight) [live 2026-10-09: crash at `005711cb`].

What the mod keeps about ships (lent route ships with their route, defence holds with their landing, pickup and
invasion timers) is dropped in its hook on `NNavy::Ship::dtor`, so a ship deleted on any path (§5) leaves nothing
behind. A route or harbour the mod remembered is looked up in the game's lists (`NNavy::System::shipRoutes`,
`harbors`) before it is used: destroying a harbour deletes its routes.

**Lost defences by sea** (`ShipLostOnDefeat`, `combat.cpp`, maintainer's rule): a ship carrying defenders (its
player is the fight's `defenderPlayer`) sinks when the harbour it lies at or sails to is no longer its player's and
the attacked building is not the defender's any more (taken or gone).

The game's mission leaves the landing as soon as its own soldiers are out of the fight (state 5 boards whoever comes
back, then sails home) [live 2026-10-09: the defenders died, the ship sailed home, and only then was the building
taken and the harbour lost]. So a defenders' ship waits at the landing in state 5:
- while the attacked building is still its player's and the attacker side still has soldiers in the fight
  (`Fight::pSideList0`; a fight stays active while a side list or its ship list is non-empty, `Fight::IsActive`
  `00571090`);
- after the building is taken, until the harbour changes hands (then it sinks), at most 300 ticks: another building
  of the player may still hold the harbour's territory.
A target that is gone, or the attackers gone, ends the wait; the game's state 5 then boards the survivors.
The wait remembers its landing harbour: losing the harbour clears the ship's own target harbour (`005b5370` →
`Movement::ClearRoute`) before the next ship update, so the sinking check falls back to the remembered landing
[live 2026-10-09: without it the check found no harbour, and the game ended the mission for want of a route]. A ship at a harbour that is still its
player's is safe. Checked in the `Ship::Update` hook before the game's update: when a harbour's territory changes
hands, `005b5370` unlinks the ships from its routes, and `Ship::Update` would then end the mission for want of a
route. Soldiers aboard sink with the ship; any still ashore are left to the game (§4) or a retreat
pickup.

**Harbour garrison** (`takeover.cpp`, `HarborMustHaveGarrison`). An enemy harbour (owner an enemy by
`Player::IsEnemyOf`) is guarded when a walk over its flag's links, skipping sea streets, reaches the entrance flag of
a finished territory building of its owner (both `NVillage::Construction` remainders at 0) whose territory range
reaches the harbour flag: hex distance ≤ `NVillage::Military::GetTerritoryRange` `0055fca0`, the radius
`TerritoryUpdater::Activate` `00565350` gives its territory source. The expedition hook
(`invasion.cpp`) changes three states for an unguarded enemy harbour:
- state 4 says "Ship waiting for Orders" and goes to 5;
- state 5 keeps waiting;
- state 6 runs the takeover before the game's founding.

The takeover looks for a position in `FindBuildingPosition`'s order. The test runs while the colonist holds every cell
within `territoryRange` + 1 of the harbour: the territory grid is written, `RefreshTerritoryBorderBits` `0067b910`
and `MapModifier::RecomputeConstructionMapRadius` `00672da0` run, the placement test and the street search run, and
everything is restored. For each position found, the land the founding needs is tested once more, alone:
- the footprint;
- the street path, ends included, with the 6 neighbours of each of its cells.

The street search is the game's: the navy's `StreetPlanner` search object, set up as `NLogic::AStarStreet::SetSearchParams` `00776160`
would (player, type 0, the path so far, no street to cross). Its fields are restored afterwards. The claim writes
those cells and runs `OnTerritoryChangedAt`. It removes the enemy's harbour flag at once with
`NNet::System::RemoveFlag` `00665c10`, as the next tick would. Then it runs the game's state 6, with
`FindBuildingPosition` answering the chosen position. After `PlaceExpeditionBuilding` (whose sources recompute the
land around it) the claimed cells are written again, so the harbour flag and the street can follow.

If no position works, a second search also accepts a position that the placement test refuses only because of the
4-cell rule, when every territory building within 4 cells is an enemy's. "Only because of" means the same test
passes with size bit 0x40 cleared; that bit alone brings in `HasNoTerritoryBuildingWithinRadius4` `0052dc30`. The
search skips this when the cleared size would be 8 or 0x10, which the test compares for equality. The construction
map's own use of the 4-cell test is a separate per-player flag. The buildings (found as the game does:
`FindBuildingAtOrNearest` `00558890` radius 0 on each cell, type with `territoryRange` > 0, sites included) are
removed before the claim with `NVillage::System::RemoveBuilding` `00559db0` (spill on). Every way the game destroys a
building ends there: hitpoints at 0 (`Hitpoints::OnChanged` `0055b8b0`), land lost (`Building+0x138`, removed by
`NVillage::System::Update` `0055a640`), demolition, `vi_destroyBuilding`. The headquarters (the only type that is
both a depot and gives territory: `castle`, `BuildingProperty::depot` +0x54 and `territoryRange` 9) can be among
them only on a map with a harbour within 4 cells of it; its owner then gets a message blaming the map maker. No
position: "No Valid Position", state 7. A naval invasion's founding does the same at a harbour held by a third player without
a garrison. At a free harbour, it only falls back to the game's own founding when no position is found. Every player who
loses cells to a claim gets the game's "!Lost Territory." (message type 1, unless one is already at the harbour, as
`TerritoryLostFlags::NotifyLostTerritory` `006797f0` does).

**Settings** (`navalcombatfix.ini`, `[NavalCombatFix]`; defaults are the rules above): `AttackersBySea`,
`DefendersBySea`, `AttackFromOwnLanding`, `ProximityOverOwnRoutes` and `NeutralLandings` switch each rule; `ValidRetreatHarbors` (`own`, `neutral`, `friendly`, `all`) chooses the retreat pickup's harbours; `ShipLostOnDefeat` sinks the ship of a lost attack by sea; `HarborMustHaveGarrison` the harbour garrison rule; with one
off, that case runs the game's own code. `CrossingDistance` (cells, default 0) is added for a sea crossing to the
soldier-count sum and to the distance to the enemy. `PickupTimeout` (ticks, default 1200) is how long a pickup ship
waits. `LandingReach` (cells, default 9: as if a guard house stood at the landing) widens the landing test for
every landing, enemy, own and neutral: the harbour may lie up to that many cells beyond the target's territory
range + 1 (10 to 12 cells: `bp_setTerritoryRange` 9 for the guard house and castle, 10 tower, 11 fortress). Every player of a match runs the host's copy of the mod, this file included: `assetshare` compares the whole
folder and downloads the host's copy when anything differs.

Several ships: a route still takes one ship per player, but buildings whose best usable pairs differ use different
routes, and so different ships. When the nearest route's ship is busy with another fight, a building falls back to
another route with a free ship.

Soldier counts stay the game's: `(int)(n * reach)` per building and `(int)(that * fraction + 0.5)` per dispatch.

[TODO, live] All of it needs a match test: an attack across the water from a colony, reinforcements from home while
both harbours are owned, a defence across the water, and the return trip of the soldiers.

## 8. Open points

- [TODO] Who assigns ships to a route whose two ends both belong to the player (manual assignment refuses it with
  reason 2), i.e. how such a sea street gets its ship in the first place.
- [TODO] The AI's own sea-attack planning (`NAI::*`, `ai::navy::*`) beyond its use of the dispatchers.
