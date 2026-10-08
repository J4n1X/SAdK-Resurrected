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
| 7 | The attacker's slot-table flag `+0x28` is set (`SlotTable_IsField28Positive`, `NSacrifice::System+0xc`) [known]; meaning [TODO: likely a sacrifice/peace lock] |
| 5, 1, 6, 3, 7 | From the target's own state, `NVillage::Military::GetAttackTargetState` `0055fd90`: still under construction → 5; not in proximity zone 2 → 1; an unoccupied military building → 6; already under attack (a fight is bound) → 3; the owner's slot flag → 7 [known]. "Proximity zone" is [TODO] |
| 0 / 8 | `Military_IsEnemyTerritoryInRange` (below) is true: 0 if `Military_CountAttackersByKind` finds any soldier, else 8 ("no soldiers") [known] |
| 2, 4, 1 | Otherwise the sea reason from `Military_IsHarborWithinBuildingRange` `00574f70`: route but no ship → 2; ship busy → 4; no route, or no harbour in range → 1 [known] |

**Reach test** `Military_IsEnemyTerritoryInRange(target, attacker)` `00575850` [known]:
1. The attacker owns a cell on the hex ring at distance `R + 1` around the target, where `R` is the target's
   territory range: `NVillage::Military::GetTerritoryRange` `0055fca0`, i.e. `bp_setTerritoryRange`
   (`BuildingProperty+0x94`) summed over the owner's slot table. Put plainly: the attacker's land touches the edge of
   the target's land.
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
- **Other landmass (or overland 0):** only if the target's owner is an enemy (`Player_IsEnemyOf` `005be280`: different
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

The attack slider sends a fraction `f`. Per building the count is **`(int)(GetAvailableAttackers * f + 0.5)`**
[known: constant `007d4a90` = 0.5]. `Military_GetMinAttackerFraction` `00575f00` gives the slider step:
`1 / (2 * the largest single-building count)`.

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
2. The defender's fraction is copied into the target (above).
3. `g_bSeaAttackDispatch` `0088a4cc` is set to 1, the attackers are dispatched, then it is set back to 0. While it is
   1, a ship of the route that is already on a military mission counts as ready (§5.1).
4. The message `!You are under attack!` goes to the defender.

**Tick.** `NMilitary::Fight::Update` `005715a0` [inferred]:
- When the start countdown (`+0x24`) reaches 0: defenders are dispatched (with `g_bSeaAttackDispatch` = 0), the
  fight is recorded in the AI's history, gathering positions are computed, and a side with no soldiers marks the fight
  as empty (`+0xcc/+0xcd`).
- If either player's slot flag `+0x28` is set while the target is held by the attacker, the fight ends at once.
- While ending (`+0xb8`), at end countdown 0 `ReleaseAttackers` `005714a0` flags every attacker to leave
  (`SoldierFightState+0xa0`).

**Gathering positions.** `MilitaryGatheringPositions_Compute` `00576fb0` [inferred]: the attackers' origin
`Military_GetAttackOriginCell` `00576d00` is the nearest home building of an attacker on the target's landmass. Failing
that, it is the owner's nearest completed building. A landing harbour of the target's owner with a route to the
attackers is used instead when it is closer, or when the building is on another landmass. An A* path from the target's
entrance to the origin fixes three cells: centre at half the distance, near/far at ± half the soldiers' minimum kind-1
property `+0xa0`. If no path exists, the path goes to the harbour nearest to the target in its water body
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
- When the movie ends, `NSettlers::Settler::Update` `00656ec0` puts a settler within 2 cells of such a building into it
  (state 2). **Otherwise it calls `StartDying`** [known]. A soldier with nowhere to go dies.

**Crossing water on foot: sea streets** [known]. A ship route is also a street (type 3) of the street network, built
and removed by `NavyShipRoute::UpdateSeaStreet` `005b71d0`. It exists only while `IsStreetValidForPlayer` `005b6d80`
holds: **both end harbours belong to the player and the player has a ship on the route**. Settlers, soldiers going home
included, walk over it and wait at the harbour flag for a ship (`NavyCargo_AssignWaitingSettlers` `005bd270`).

**Harbour ownership** [known]: a harbour belongs to whoever owns its flag. `Harbor::AttachFlag` `005b49f0` copies the
flag's owner and refreshes the sea streets of its routes. When the flag goes, `005b5370` (via
`NavyLink_UnlinkHarborBuilding` `0053c1f0`) sets the harbour to -1 and unlinks the ships from its exits. So when a
player loses the territory around a harbour, the harbour turns neutral (-1) and every sea street through it disappears.
That holds whether the ground became nobody's or an enemy's. The territory map (`NMap::Territory+0x14`, one int per
cell, -1 = nobody) tells the two apart.

Together: destroying one's last military building on the far side takes the harbour's flag with the territory. The
sea street home disappears, and its soldiers die with nowhere to go [inferred].

## 5. Sea transport for fights

### 5.1 Finding harbours

- `HarborList::FindNearestWithPlayerShipRoute(pos, shipPlayer, harbourOwner, militaryActive, *status)` `005b6090`:
  among the harbours **owned by `harbourOwner`** on `pos`'s landmass, the nearest one that is ready for
  `shipPlayer` [known]. Every sea check of §2–§4 uses it with `harbourOwner` = the target's owner.
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
| 5 | Board the soldiers that left the fight → 6 when all are aboard |
| 6 | Sail to the opposite end of the route → 7 |
| 7 | Disembark one per tick, unlinking mission soldiers; when empty `NNavy::Military::Finish` `005ba190` |

Ship states (`Ship+0x28`) [inferred]: 0 idle, 1 waiting, 2 loading, 3 unloading/sailing, 4 expedition, 5 military,
6 sinking, 7 sunk, 8 doomed.

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

## 7. The `navalcombatfix` mod: soldiers cross through their own harbours

`mods/navalcombatfix/` (`combat.cpp`, `retreat.cpp`; a server mod: every player of a match needs it). These are rules the maintainer
decided, not a restoration of lost behaviour. Every case the game already handles runs the game's code unchanged.

**Own sea link.** For a building of player P on another landmass than the target, the mod considers every pair of
P's own harbours: H1 on the target's landmass, H2 on the building's landmass, and the route from H2's exit to H1.
A pair counts only if **its own route has a ship for these soldiers**, by the checks `SendSoldiersBySea` makes
(§5.2). Either P's ship already on that route carries the fight being dispatched, or P has no ship there and an idle
one is found at H2's exit. Of the usable pairs the one with the smallest **d(target, H1) + d(H2, building)** below
24 wins. Counting and sending use the same search, so a building is counted only with soldiers its ship can actually
take. A blocked route falls back to the next-best pair and its ship.

The fight being dispatched is recorded while `Attack::DispatchAttackers` or `DispatchDefenders` runs with a real
`AttackConnector`. Outside a dispatch (the attack button, the AI's `StrengthCounter`) there is no fight, so only routes
with an idle ship count. This replaces the game's looser test (`EvaluateRouteToPlayer`: any route at H1 with a ready
ship), and `g_bSeaAttackDispatch`, for the mod's own cases.

| Hooked | Change |
|---|---|
| `Military_GetAttackReachFactor` | When the game returns 0: `falloff(d(target, H1) + d(H2, building))` of the own sea link. The crossing counts as zero length, and the ground rule of §3.2 applies to the remaining walk. For attackers and defenders alike |
| `Military_IsTargetReachable` | Also true (with `allowSea`) when an own sea link exists |
| `Military_IsEnemyTerritoryInRange` | Also true when a harbour of the attacker lies on the target's landmass closer than the target's range + 1, with a route to an attacker's harbour across the water and a ship for it: the game's harbour test of §2 without its owner condition. This makes targets around a colony's harbour attackable |
| `NMilitary::Attack::DispatchAttackers` | Unchanged; only records the fight being dispatched |
| `NMilitary::Attack::DispatchDefenders` | Reimplemented with the game's counts (and records the fight). A building on another landmass than the target sends through slot 1 (by sea) instead of slot 0 |
| `NMilitary::AttackConnector::SendSoldiersBySea` | The game's code when the game's own reach factor counted the building. Otherwise the own sea link it was counted with, using the ships of the **building's owner** (the game would use the attacker's, which is wrong for defenders) |
| `NNavy::Military::Update` | States 0 and 3, when both route ends belong to the ship's player: load at the end on the building side and land at the end on the target's landmass |

**Retreat pickup.** `NSettlers::Settler::StartDying` is hooked. A healthy soldier in state 3 (dying only for having
nowhere to go, see §4) is picked up by a ship instead, when there is:
- a harbour on its landmass that is **neutral**: no owner, and nobody's territory at its cell. A harbour whose cell
  belongs to an enemy is not used;
- with a route to a harbour of the soldier's player;
- and either one of the player's ships already waiting there, or an idle one for that route.

The ship gets a transport mission without a fight (`NavyLink_LinkMilitaryRoute`), sails to the neutral harbour and
waits in state 2, where the game boards the soldiers standing on it. The soldier is linked to the ship (`NavyLink_LinkMilitarySoldier` `0053c070`) and
set to state `0x21`, so it walks to the ship's harbour like a soldier coming back from a fight. When all are aboard,
or after a timeout (1200 ticks, [TODO] tune), state 3 sails to the other end of the route, and the game's state 7
unloads. The soldiers, with a reachable home again, walk into a building. A mission without a fight is only ever a
pickup. The game would read a null fight in its state 3, so the mod handles every mission without a fight in state 3.

| Hooked | Change |
|---|---|
| `NSettlers::Settler::StartDying` | The retreat pickup above |
| `NNavy::Military::Update` | Also: missions without a fight (pickups) wait in state 2 with a timeout, and sail to the other route end in state 3 |

Several ships: a route still takes one ship per player, but buildings whose best usable pairs differ use different
routes, and so different ships. When the nearest route's ship is busy with another fight, a building falls back to
another route with a free ship.

Soldier counts stay the game's: `(int)(n * reach)` per building and `(int)(that * fraction + 0.5)` per dispatch.

[TODO, live] All of it needs a match test: an attack across the water from a colony, reinforcements from home while
both harbours are owned, a defence across the water, and the return trip of the soldiers.

## 8. Open points

- [TODO] The proximity zone of `GetAttackTargetState` (code 1 on the button) and the slot-table flag `+0x28` (code 7).
- [TODO] Who assigns ships to a route whose two ends both belong to the player (manual assignment refuses it with
  reason 2), i.e. how such a sea street gets its ship in the first place.
- [TODO] `SoldierFightState+0x40`, set together with the leave flag by `0065b7c0`.
- [TODO] The AI's own sea-attack planning (`NAI::*`, `ai::navy::*`) beyond its use of the dispatchers.
