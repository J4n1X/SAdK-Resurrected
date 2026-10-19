# Military: soldiers, buildings, attacks and fights

Specification of the military simulation of *Die Siedler: Aufbruch der Kulturen* for a reimplementation.

- Binary: `sadk_noav.exe` (base `0x400000`). `S 00xxxxxx` is a static address and only evidence.
- Tags: **[known]** = read directly in the code or the data (address or file and key given); **[inferred]** =
  one step of reasoning from what is visible; **[TODO]** = open. Nothing here was observed in the running game.
- Related documents, not repeated here:
  [../navy-and-military.md](../navy-and-military.md) (the attack button states, the reach factor, sea transport
  of soldiers, ship missions, stranded soldiers), [village-buildings.md](village-buildings.md) (building
  objects, settler orders and their suppliers, hit points, ownership change, territory sources),
  [game-commands.md](game-commands.md) (the lockstep commands), [players-victory.md](players-victory.md)
  (player settings, statistics, strength), [logic-core.md](logic-core.md) (tick, random generator, save stream),
  [../lua-surface.md](../lua-surface.md), [../data-loading.md](../data-loading.md), [../types.md](../types.md).
- Time unit: the **logic tick**, 10 per second at game speed 1 (`logic-core.md`).
- Distances are **hex distances in cells** (`ai::map::MapPos::HexDistance`) unless stated otherwise. The
  **fine grid** has 4 fine cells per cell: fine x = `4 * x` (+2 on odd rows), fine y = `4 * y` [known]
  S 00578400, S 00572fa0.

## 1. Purpose and scope

The subsystem is responsible for:

- the soldier **types** (two kinds, sword and bow, up to five levels each per tribe in the code; `military.lua`
  defines at most three, levels 0..2) and their combat values;
- **producing** soldiers in barracks and **promoting** them with coins;
- the **garrison** of military buildings: how many soldiers a building wants, ordering, dismissing, swapping the
  kind, replacing wounded soldiers and promoting the weakest one;
- the **cached enemy distance** of each military building (the "front line" zones);
- **attacks**: who may attack what, how many soldiers each building sends, defence and reinforcements;
- the **fight**: gathering, grouping soldiers against opponents, standing positions, strike timing, hit rolls,
  damage, death, leaving;
- **capturing** a building or destroying a castle, and the delayed demolition of a building under attack;
- **projectiles** (arrows, bolts, sling stones, catapult stones) and the **catapult**;
- saving and loading all of the above.

It is not responsible for: the territory grid and borders (map), the building life cycle and settler order
matching (`village-buildings.md`), ships and harbours (`../navy-and-military.md` §5), walking and path finding
(settlers, map), the computer player's planning (`NAI::*`, `ai::ai_military::*`, and
`ai::military::MilitaryBuildingRanking` S 005a8310, which only ranks building sites for the computer player),
the sacrifice system (it supplies modifiers, §3.9), rendering and menus.

## 2. Data model

### 2.1 Soldier type (`GoodProperty`, one per soldier good)

A soldier is a settler good of settler type 3 (`gp_setSettlerType(…, settlerType_Soldier)`, `GoodProperty+0x7c`
[known] S 0054e4b0, `Jobs.lua`). Fields set by `Jobs.lua` [known: binders
S 0054e460, S 0054ec00, S 0054e410, S 0054e370, S 0054e3c0, S 0054e320, S 0054e2d0, S 0054e280, S 0054eba0,
S 0054eb50, S 0054e9b0; defaults from the constructor S 00554da0]:

| Offset | Lua key | Type | Meaning |
|---|---|---|---|
| +0x80 | `gp_setSoldierType` | int | kind: 0 = sword (melee, default), 1 = bow (ranged) |
| +0x84 | `gp_setHitDamage` | int | base damage per strike; default 0 |
| +0x88 | `gp_setHealth` | int | maximum life points; default 0 |
| +0x90 | `gp_setArmor` | int | subtracted from every hit taken; default 0 |
| +0x94 | `gp_setAttackWaitTime` | int | ticks of pause after a strike (plus 0..9 random, S 006594a0); default 0 |
| +0x98 | `gp_setBlockingChance` | int | percent; used as the striker's **own miss threshold** (§3.7); default 0 |
| +0x9c | `gp_setAttackTime` | int | length of the strike in ticks; default 17 |
| +0xa0 | `gp_setBowRange` | int | maximum shooting distance in cells, inclusive (bow only); default 6 |
| +0xa8 | `gp_addHitTime` | vector&lt;int&gt; | ticks within the strike at which the hit is applied; several allowed |
| +0xb8 | `gp_setProjectileType` | int | 0 arrow, 2 bolt, 3 sling stone (1 = catapult stone, set in code S 005678b0); default -1 |
| +0x04 | `gp_addCost` | list | cost goods: level 0 = weapon + drink (+ clothing; the sling soldier takes 3 stones as its weapon); level n = level n-1 soldier + 1 coin |

### 2.2 Military configuration (`ai::properties::MilitaryConfig`, 0x120, `PropertiesDb+0x5c`)

[known] ctor S 00554380, setters S 00554290, S 0054cbc0..S 0054cc50.

| Offset | Content | Default in code | In the data |
|---|---|---|---|
| +0x00 | `soldierId[kind 0..1][level 0..4]`: map tribe → soldier good id | empty | `mi_setSoldierId` |
| +0x78 | `health[kind][level]`: map tribe → `gp_setHealth` of that good (cached when the id is set) | empty | derived |
| +0xf0 | `maxLevel[kind]`: map tribe → highest level defined | empty | derived |
| +0x108 | int | 20 | never read, no setter: only the ctor writes it [known] (§10 Q3) |
| +0x10c | byte | 0 | never read: set to 1 at the start of `Properties_RegisterLuaLibrary` S 00550e40 (S 00553f00), to 0 by `Properties_Db_ClearAll` (S 00553f10) [known] (§10 Q3) |
| +0x110 | `regenerationRate` | not set by the ctor [known] | `mi_setRegenerationRate(100)` |
| +0x114 | `waitForTacticTime` | 100 | `mi_setWaitForTacticTime(10)` |
| +0x118 | `actionsInFightDelayTime` | 300 | `mi_setActionsInFightDelayTime(300)` |
| +0x11c | `healthExchangeDistance` | 200 | `mi_setHealthExchangeDistance(200)` |

Level lookups: `GetSoldierId(tribe, kind, level)` S 00554090; `FindSoldierLevel(tribe, goodId)` S 00553fb0
searches levels 0..4 and both kinds, returns -1 if not a soldier of that tribe; `GetMaxSoldierLevel(tribe, kind)`
S 005540e0. `SoldierLevelRange(tribe, kind, ascending)` S 005703d0 iterates `0..max` or `max..0` [known].

The `health` cache is filled by `mi_setSoldierId` itself (S 00554290) from the good's `gp_setHealth` at that
moment: `Jobs.lua` must be loaded before `military.lua` (`data.lua` loads "jobs" before "military"), and a
later `gp_setHealth` does not update the cache [known; `properties-data.md`]. `maxLevel` is raised only when
the level set is higher than the stored one, so it is the highest level index set, whatever the order [known].

### 2.3 Player settings (`NPlayer::Military`, 0x20, `Player+0x4c`)

[known] S 005c0930 (defaults; the three fractions come from the constants in S 00553f40), S 005337e0; commands
in `game-commands.md`.

| Offset | Type | Meaning | Default |
|---|---|---|---|
| +0x08 | f32[3] | garrison fraction per zone: [0] far, [1] medium, [2] near (§3.2) | 0.1, 0.3, 1.0 |
| +0x14 | u8[8] | per other player: ignore that player's buildings when measuring the enemy distance A (§3.1) | 0 |
| +0x1c | f32 | defence fraction: share of each helping building's soldiers sent to defend | 0.5 |

### 2.4 Military building component (`NVillage::Military`, 0x98, `Building+0xe0`)

The component object is allocated for **every** building, whatever its type (`Building::ctor_Place` S 0055d980
creates it unconditionally; the catapult target filter reads it on catapult buildings) [known]. Its rules only
act on types with `bp_setTerritoryBuilding` (`BuildingProperty+0xf5`): only those are in the territory-building
list that the distance, allocation and dispatch passes walk [known] ctor S 0055fef0, S 00574a00.

| Offset | Name | Type | Meaning |
|---|---|---|---|
| +0x04 | building | ptr | owner building |
| +0x08 | soldiers | `NVillage::Soldiers` | garrison list: references to soldier settlers, vector at +0x10/+0x14 |
| +0x24 | slotUpgrade | `MilitaryOrderSlot*` | order slot 0: promotion exchange |
| +0x28 | slotKindExchange | `MilitaryOrderSlot*` | order slot 1: kind exchange |
| +0x2c | slotReplace | `MilitaryOrderSlot*` | order slot 2: replacement of a wounded soldier |
| +0x30 | attackers | references | soldiers attacking this building ("list 30") |
| +0x44 | defenders | references | soldiers defending this building ("list 44") |
| +0x58 | enemyDistanceB | int | distance to the nearest enemy, no ignore flags; -1 = not computed |
| +0x5c | enemyDistanceA | int | same with the player's ignore flags; -1 = not computed |
| +0x60 | cooldownTicks | int | counts down 1 per tick; set to 10 when a soldier is released (§3.2, §3.5) |
| +0x64 | defenceFraction | f32 | copy of the owner's defence fraction, taken when an attack on this building starts (S 00576500); 0.5 |
| +0x68 | soldierKind | int | wanted kind, 0 sword / 1 bow; 0 |
| +0x70 | fight | `ReferenceFight` | the fight this building is the target of; id high word at +0x84, valid = under attack |
| +0x90 | destroyCountdown | int | -1 idle; > 0 counting; 0 = demolish now (§3.8) |
| +0x94 | unconnectedTicks | int | counter for the "not connected" message; 500 |

`MilitaryOrderSlot` (0x34) [known] S 00568800: +0 building, +4 references to the soldiers waiting to be exchanged,
+0x18 `OrderContainer`, +0x2c f32 load weight, +0x30 slot index.

Building type predicates used throughout [known]:
- **headquarters type** = `depot && casern && territoryBuilding` (`+0x54`, `+0xf1`, `+0xf5`); in the data only the
  castle.
- **occupied** = `Building+0xc4` territory updater byte `+8` set (the first soldier has arrived,
  `village-buildings.md` §3.14).
- **garrison capacity** = `max(1, trunc(hitpoints / maxHitpoints * bp_setSoldierLimit))` S 0055c1a0.

### 2.5 Barracks components (`ai::village::SoldierTraining`, 0x6c, `Building+0x124`)

Allocated for every building (`Building::ctor_Place` S 0055d980, unconditional) [known]; used only by
`bp_setCasern` types, whose production cycle calls into it [known] S 00566740, S 005668e0 (the `casern` test
is in the production functions, §3.4).

| Offset | Content |
|---|---|
| +0x00 | building |
| +0x04, +0x08 | two `SoldierTrainingSlot*` (0x10 each): +4 `enabled` (bool), +8 `goodId` = level-0 soldier of kind 0 / 1 of the owner's tribe, fixed by the constructor (S 00566740) and saved (§7), +0xc `running` |
| +0x0c | `currentSlotIndex`, initial 1 |
| +0x10 | `SoldierUpgrade` (embedded): +4 `enabled` (1), +8 round-robin `soldierType` (1), +0xc `active`, +0x10 cost list = { tribe's `tp_setSoldierUpgradeGoodId`, 1 } |
| +0x30, +0x4c | two stocks used as good lists, rebuilt by S 00566840: cost goods of the enabled slots and of the enabled upgrade / cost goods of the disabled ones |
| +0x68 | `running` |

### 2.6 Soldier (`NSettlers::Soldier`, extends `Settler`)

[known] ctor S 00658420, field use in S 006594a0.

| Offset | Content |
|---|---|
| +0x54 | state (§3.5) |
| +0x58 | `GoodProperty*` of the soldier good |
| +0xf8 | ship reference (military transport) |
| +0x11c, +0x144, +0x164, +0x180, +0x188, +0x1a8, +0x1b0, +0x1b8 | movies: GoToWorkingPlace, LeaveBuilding, MoveToAttackBuilding, Fight, ReturnToMilitaryBuilding, MoveToPosition (cell), MoveToFinePosition, ReturnToLogicGrid |
| +0x1c0 | home building reference (id high word +0x1d4) |
| +0x1e0 | `Livepoints`: +0xc current life points (= `Soldier+0x1ec`), +0x10 regeneration tick counter |
| +0x1f4 | references to projectiles flying at this soldier |
| +0x208 | `ai::settlers::Bow`: reference to the last projectile shot |
| +0x230 | `SoldierFightState` (below) |
| +0x338 | paired soldier (the one this soldier replaces, or its replacement) |
| +0x358 | order building (the building whose exchange slot this soldier serves) |
| +0x378 | village order reference |

Soldier vtable S 007f842c, the slots this document uses [known]: +0x20 `OnEnterBuilding` S 00659300 (§3.3);
+0x28 (slot 10) `IsInWorkCycle` S 00658860, true in states 7, 0xd, 0xe, 0xf, 0x21 and 0x28..0x34; +0x2c
(slot 11) `GetWorkBuildingFlagPos` S 00658e50, the entrance flag cell of the home building or, without a home,
of the order building (that reference is not tested for validity), the "working place" a non-worker settler is
walked to (`NMovie::MoveOnMapToWorkingPlace::Start` S 00780090); +0x30 / +0x34 the stretched hit times (§3.7).

The two walking movies of the fight [known]: `MoveToAttackBuilding` (vtable S 008347f4, `Start` S 00779d10,
`Update` S 00779cb0) walks to the entrance flag cell of the attacked building (`SoldierFightState+0x68`),
first back onto the cell grid (`ReturnToLogicGrid`, step 0xe) when the soldier is off-centre, then
`MoveToPosition` (step 0x16); without a valid target it does not start. `ReturnToMilitaryBuilding` (vtable
S 00834794, `Start` S 00779820, `Update` S 007797c0) walks with `MoveToPosition` to the entrance flag cell of
the home building and then plays `EnterBuilding` (step 0xc); it does not start without a home, and ends without
entering when the home link is gone at arrival.

`ai::military::SoldierFightState` (0x104) [known] layout from the type database, use in S 006594a0:

| Offset | Name | Meaning |
|---|---|---|
| +0x00 | owner | the soldier |
| +0x04 | int | -1 in the constructor (S 0065bbc0); written only by `Load` S 0065bcc0, read only by `Store` / `StoreUntagged` S 0065b8b0 / S 0065ba40: always -1, no effect but its bytes in the save and checksum streams [known] (§10 Q3) |
| +0x08 | attackers | references to the soldiers whose opponent is this soldier |
| +0x20 | defendedBuilding | set while linked as defender of the target ("list 44") |
| +0x40 | retarget | bool: drop the current opponent at the next decision |
| +0x48 | opponent | the enemy soldier this one fights |
| +0x68 | attackedBuilding | set while linked as attacker of the target ("list 30") |
| +0x88 | cellA | gathering cell of the soldier's side |
| +0x90 | cellB | the cell the soldier stands on (or walks to) in the fight; -1 = none |
| +0x98 | cellC | fine-grid position next to the opponent |
| +0xa0 | leftFight | bool: leaving / has left |
| +0xa8 | fight | `ReferenceFight` |
| +0xc8 | targetedBy | references to the enemy fight groups targeting this soldier |
| +0xe0 | group | the fight group the soldier is a member of |
| +0x100 | strikeHits | bool: the running strike will hit (§3.7) |
| +0x101 | inFight | bool |

### 2.7 Military system (`NMilitary::System`, 0x20, `GameSystem+0x40`)

[known] S 00570260, S 0056ffb0: +4 bool, set by `Init` S 0056ff50 (game start) and cleared by `Reset`
S 0056ff80, saved, read by no rule ("initialised" [inferred]), +8 `Distances*` (countdown, initial 10), +0xc
`Allocation*` (countdown, initial 20), +0x10 `Attack*`, +0x14 `ProjectileList*`, +0x18 `FightList*`, +0x1c
`FightGroupList*`. All three lists are vectors of owned pointers in creation order.

**Fight** (`NMilitary::Fight`, 0xd0) [known] S 00570ae0, S 00570d20:

| Offset | Name | Meaning |
|---|---|---|
| +0x08 | unique | logic id |
| +0x18 | attackerPlayer | player index |
| +0x1c | defenderPlayer | player index, -1 until the target is bound |
| +0x20 | assignDirty | bool: run the assignment pass (§3.6) at the next update |
| +0x24 | startCountdown | ticks until the fight starts; initial `waitForTacticTime` |
| +0x28 | target | `ReferenceBuilding` (id high word +0x3c) |
| +0x48 | targetCell | cell of the target when it was bound |
| +0x50, +0x64 | groups[side] | references to the fight groups of side 0 / 1 |
| +0x78, +0x7c | sideList[side] | `FightSoldierList*`: side 0 = attackers, side 1 = defenders |
| +0x80 | assigner | `FightAssigner`: +8/+0xc `targetKind[side]` |
| +0x90 | gathering mode holder | +4 `mode` (0..3, §3.6) |
| +0x98 | gathering positions | three cells: +4 centre, +0xc far, +0x14 near |
| +0xb4 | endCountdown | -1 idle |
| +0xb8 | ending | bool |
| +0xbc | ships | references to the ships carrying its soldiers |
| +0xcc, +0xcd | contact[2] | two bools, always set together: "the archers may shoot" (§3.7) |

Side of a soldier: 0 if its owner is `attackerPlayer`, else 1 [known] S 00571110. So a third player's soldier
would count as a defender; no path that adds one was found [inferred].

`FightSoldierList` (0x2c) [known] S 00576710: +4 soldier references (vector +0xc/+0x10), +0x18 `gatheringSlot`
(0 centre, 1 far, 2 near, -1), +0x1c `countByKind[2]` (current), +0x24 `everAddedByKind[2]` (never decremented).

**Fight group** (`ai::military::FightGroup`, 0x78) [known] S 00573420: +0 unique id, +0x10 fight reference,
+0x30 cell (x, y; -1 = none), +0x38 **target** (one enemy soldier), +0x58 **members** (soldier references, vector
+0x60/+0x64), +0x6c side, +0x70 kind (the kind of its members). A group is "several soldiers of one side and one
kind who fight the same enemy soldier".

**Projectile** (`ai::military::MilitaryProjectile`, 0xd8) [known] S 00572b80, S 00572fa0: +0 unique id, +0x10
type, +0x14 `flightTicks`, +0x18 `elapsedTicks`, +0x20 target, +0x78 source, +0xd0 damage. Target and source are
`ProjectileOwner` (0x54): +0 kind (0 soldier, 1 building, else a position), +0x08 building reference, +0x28 settler
reference, +0x48/+0x4c cell, +0x50 int (the shooter's player index, used for the kill credit) [known for the
offsets; the meaning of +0x50 is inferred from the uses in S 00572fa0 and S 0055e080]. The source's cell is
therefore projectile +0xc0/+0xc4; for a catapult shot it is the catapult building's anchor.

**Catapult** (`NVillage::Catapult`, `Building+0xf4`) [known] S 00567640: +8 target cell, +0x10 aim cell (-1 =
none), +0x18 f32 last fire stamp (copy of the f32 at `GameSystem+0x78` when fired, S 005678b0), +0x1c f32
rotation start stamp (0 in the constructor; copy of the same f32 whenever a rotation starts and the pending
direction is set, S 00567750; read only by `Serialize` S 00567770, so it has no effect on play [known]
(§10 Q3)), +0x20 current direction 0..5 (initial 1), +0x24 pending direction (initial 8), +0x28 projectile
reference, +0x48 `targetSeed` (counts attacks, initial 0).

**Path-length cache** of `NMilitary::Attack` [known] S 00575b70: two static maps `key → path length` with a
time stamp each; one is saved (§7). Key = `(fromIndex - 1) * 0x10000 + (toIndex - 1)`, cell index =
`y * mapWidth + x`. On maps with more than 65536 cells two pairs can share a key [inferred].

## 3. Rules and algorithms

### 3.1 Enemy distance and zones

Every 11th tick (countdown reset to 10), for every territory building that is not `depot` type [known]
S 00574e40:

```
enemyDistanceA = MinDistanceToEnemyMilitaryBuilding(cell, owner, useIgnoreFlags = true,  harbours = true)
enemyDistanceB = MinDistanceToEnemyMilitaryBuilding(cell, owner, useIgnoreFlags = false, harbours = true)
```

`MinDistanceToEnemyMilitaryBuilding` S 005337e0 [known]: start at 1000; for every territory building whose
owner `IsEnemyOf` the player and that is **occupied** (and, with flags, whose owner is not ignored): take the
smaller hex distance. Then the nearest own harbour **on the same landmass as the cell** (same id in the
per-cell landmass table, `../navy-and-military.md`) with a route to an enemy harbour
(`HarborList::FindNearestWithEnemyRoute` S 005b5e00) replaces the result if it is strictly nearer.
Details and the live
observation that water is ignored: `../navy-and-military.md` §2.

Zone of a distance `d` (`ClassifyIndex_0_1_2` S 00553f20) [known]: `d < 19` → 2 (near), `19 <= d <= 24` → 1
(medium), `d > 24` → 0 (far). `GetProximityZoneA/B` return -1 for a building that is not occupied.

A building placed by an expedition gets its distances at once (`Distances::UpdateBuilding` S 00574d60) [known].

### 3.2 Garrison size and allocation

**Wanted size** (`Military_GetDesiredGarrisonSize` S 00574980) [known, from the disassembly]:

```
zone    = Classify(enemyDistanceA)                 // an uncomputed -1 classifies as 2
wanted  = trunc(capacity * owner.garrisonFraction[zone] + 0.5)
minimum = occupied ? 0 : 1
size    = max(minimum, wanted)
```

`capacity` is the hit-point-scaled garrison capacity of §2.4 (S 0055c1a0); the added 0.5 is the double at
S 007d4a90 [known]. `bp_setSoldierLimit` in `buildings.lua` is 2, 3, 4, 6, 8, 9 or 12. With the defaults a far
building of capacity 2..4 wants 0 soldiers once it is occupied, capacity 6..12 wants 1
[inferred from the formula]. The allocation pass below then dismisses its soldiers one per pass until none is
left. "Occupied" here is the territory updater's `bActive` byte, which is set once by `Activate` and never
cleared: `NVillage::TerritoryUpdater` has no deactivation, its territory source is removed only by its
destructor (S 00565270), so the emptied building keeps its territory, keeps wanting 0, and can be attacked
(target state 3 does not apply) [inferred from the functions of that class: ctor, dtor, `Refresh`, `Activate`,
`ActivateIfOccupied`, `Store`, `Load`].
Observed [live, 2026-10-12, developed save]: with the default fractions written into the local player's
`NPlayer::Military` (0.1 / 0.3 / 1.0, defence 0.5), seven occupied buildings kept returning wanted size 0 over
127 allocation passes and kept an empty garrison vector (`Military +0x10` = `+0x14`); the buildings go on
existing. On screen (maintainer) with those defaults: no soldier stays in the guard hut, one stays in the guard
tower and one in the fortress. Their capacities were not read, so which capacity limit separates 0 from 1 is not
measured, and the border of an emptied building was not watched. The computer players' fractions in that save
were the constructor defaults for three of them and 0.1 / 1.0 / 1.0 and 0.1 / 0.24 / 0.8 for the other two.

**Allocation pass** (`NMilitary::Allocation::Update` S 00574a00), every 21st tick (countdown 20), over the
territory buildings in list order. A building takes part when it is not `depot` type, finished (the two floats
`Construction+0x70` and `+0x74` are both `<= 0`), and **not under attack** [known]:

```
pending = number of open orders of the building (Building+0xd4 vector)
present = number of garrison entries (soldiers on the way count)
deficit = size - present - pending
```

- `deficit > 0`: create **one** soldier order for `GetSoldierId(tribe, soldierKind, level 0)` (S 0055c170).
  One order per building per pass [known].
- `deficit < 0`: cancel open orders, oldest first (always the first element of the order vector), one per
  missing unit of deficit. Then, only if the garrison list is not empty, walk it with an index `i = 0`:

  ```
  while count != 0:
      if deficit >= 0 or i >= count:
          if deficit < 0 and cooldownTicks == 0: dismiss the weakest present soldier; cooldownTicks = 10
          break
      s = garrison[i]
      if s is present in the building (fight ignored): i += 1
      else: unlink s from the building; deficit += 1; count -= 1      // no cooldown is set
  ```

  The dismissed soldier is the **lowest level** among the soldiers that are present **and in no fight** (first
  of that level in list order, `Soldiers::FindWeakestSoldier(presentOnly)` S 00566220, released by S 0055fc40).
  So at most one present soldier leaves per pass, and none when no garrison entry is left after the releases
  [known, decompiled C of S 00574a00]. "Present" = has a home, not moving, on the home's door cell
  (`IsPresentInBuilding` S 00658f90). When every present soldier is bound to a fight, `FindWeakestSoldier`
  returns -1. That state exists in play: soldiers picked for an attack are bound to the fight at once
  (`AssignBestSoldiers` S 005751e0) and stay in the building in state 0xc for the `startCountdown`
  (`mi_setWaitForTacticTime`, 10 ticks); a building in full reach with fraction 1.0 gives all its available
  soldiers (`GetAvailableAttackers` S 00575dc0). If an allocation pass (every 21 ticks) falls into those ticks
  while the building's wanted size is below its garrison (slider lowered, surplus not yet dismissed) and
  `cooldownTicks == 0`, the index is -1 [known for each step; the coincidence itself is not observed].
  The code then passes that index on unchecked; `Soldiers::GetSoldierObject` S 00566140 fails its
  bounds check on it and calls the CRT invalid-parameter routine S 006f2702, which ends the process with exit
  code 0xC000000D: no handler is installed (the handler slot S 0088f5c0 is written only by the CRT start-up,
  with an encoded null), so `_invalid_parameter` S 006f26de goes to `__invoke_watson` S 006f25e2, which resets
  the unhandled-exception filter and calls `TerminateProcess` [known]. The entry before the vector is never
  read. Guard it (§10 #4).

A released soldier has no home and walks to a storehouse (`../navy-and-military.md` §4, "Soldiers without a
home"). Which barracks or castle supplies an order and in which order orders are served:
`village-buildings.md` §3.12. Orders of the plain garrison are category 0; orders of the three exchange slots
are categories 1/2 (slot 0), 4 (slot 1) and 5 (slot 2) [known, `village-buildings.md` §2.6]. Whatever level an
order names, the supplier hands out the **highest** level of the kind it holds
(`SettlerSpawn::SpawnSoldierForOrder` S 00565020, `village-buildings.md` §3.11), so a level-0 garrison order
of this pass can receive a level-2 soldier [known].

**Load weight** of an exchange slot (`VillageMilitaryOrderSlot_AccumulateLoad` S 00568910) [known]: when
`enemyDistanceA != -1`, `weight += (1 / enemyDistanceA²) / openOrdersOfSlot` (f32; the square is an integer
product; a distance of 0 or a slot without open orders is not guarded and gives an infinite weight).
It is used only for slot 0
(promotion orders): each time the order matching looks for a promotion order to serve at a flag, every
candidate order's building of the wanted zone (zone 2 for category 1, zone 1 for category 2) first accumulates
its slot-0 weight, then the order with the **highest** weight wins (a later one only when strictly greater) and
the winner's weight is reset to 0 (`VillageOrderBucket_SelectLeastLoadedSoldierOrder` S 00569290 → S 00560690,
S 005606a0) [known]. Buildings near the enemy gain weight faster and are promoted more often. The matching
itself: `village-buildings.md` §3.12.

**New building.** `Soldiers::SpawnSoldier(level)` S 00566440 creates a soldier of **kind 0 (sword)** of the given
level at the building's door cell and links it as garrison member [known]. Two callers [known]:

- `Building::ctor_Place` S 0055d980, only when the game places buildings **finished**: the query is
  `NLogic::Edit::GetBatchEditing()` (`GameSystem+0x38`, vtable S 007e7c28 slot 1 = the byte `Edit+4`, set by
  slot 0 `SetBatchEditing` S 00538a60) [known]. Batch editing is the mode in which the logic tick is skipped
  (`logic-core.md`); who switches it on (map set-up, editor, script placement) is in `village-buildings.md`
  §3.2. Then a type with `bp_setWorkerLimit` (`BuildingProperty+0x7c`) `< 1`, `territoryBuilding` and not
  `depot` gets exactly **one** level-0 sword soldier; a `depot` territory type (castle) gets its initial stock
  instead.
- `NVillage::System::ConquerBuilding` S 0055a890 (script `vi_changePlayerOfBuilding`, transfer of all buildings
  of a player): before the transfer it counts, for each level `max..0` of the **old** owner's tribe and the
  building's `soldierKind`, the garrison soldiers of that level that are present and in no fight (either kind,
  S 005662d0). After the transfer it walks the levels `max..0` of the **new** owner's tribe and the same
  `soldierKind` and spawns the counted number per level on the new building, all as kind 0 of the new owner's
  tribe [known]. So soldiers of a level above the new tribe's maximum for that kind are not replaced, and when
  `soldierKind` is 1 and the new tribe has more bow levels than sword levels (egyptians: sword 0, bow 0..2) a
  sword good of an undefined level is looked up unchecked [inferred: guard it].

A spawned soldier starts in state 12 (S 00658770) [known].

### 3.3 Per-building upkeep (`NVillage::Military::Update` S 005609b0)

Runs every tick with the building. `cooldownTicks` is decremented if non-zero. Headquarters types do nothing
else. Otherwise [known]:

1. Demolition countdown (§3.8), for every building type.
2. Only when **not under attack** and the type is `territoryBuilding`:
   1. If not all garrison soldiers are of `soldierKind`: `ExchangeWrongKindSoldiers` and stop.
   2. If `(tick + building unique id) mod 20 == 0` and zone A is not 0 (zones 1, 2 and the unoccupied -1
      pass): `UpgradeLowestSoldier`, then `ReplaceSoldiers`. The sum is 64-bit (the id's high word with the
      carry) and the remainder the signed 64-bit `__allrem` [known: S 005609b0].
   3. If the garrison list is empty and the building has open orders (the vector at `Building+0xd0` of the
      order container `Building+0xcc`, the orders §3.2 counts as `pending`): `unconnectedTicks += 1`; whenever the
      counter is a multiple of 600 (it starts at 500 and is never reset, so first after 100 such ticks, then
      every 600), if `OrderSystem::GetSupplyStatus` for the first open order says 1 ("nothing reachable",
      S 00562820, `village-buildings.md` §3.12 [known]; asked for the order's good, order +0x48, at the cell one
      step in direction 1 from the building's cell, `MapPos_StepDir1` S 0052d8e0 at 00560b51, i.e. the
      entrance flag cell [known]), post or refresh the message `!Building is not connected` to the owner.

A soldier is **idle in the building** (`IsIdleInBuilding` S 00659060) when it has a home, is not moving, stands
on the home's door cell (`Building+0xf8`), is in no fight, and has no order building, no paired soldier and no
order [known].

**Kind exchange** (S 00560190) [known]: for each garrison soldier of the wrong kind, in list order:
not present in the building (fight ignored) → unlinked from the building at once, without cooldown (the index
still advances, so the entry that moves into its place is skipped in this tick); idle → order a **level-0**
soldier of the wanted kind through slot 1,
paired with this soldier; otherwise, if `Soldier::IsPairedSettlerTypeEqualSoldierType` S 00658df0 holds, its order
and pairing are dissolved. That test is true when the soldier has a paired soldier, no order building, and the paired soldier's
`GoodProperty+0x7c` equals this soldier's `soldierType` (+0x80) [known]. `+0x7c` is the **settler type** (3 for
every soldier good), `soldierType` is 0 or 1, so with the shipped data the test is never true and this branch
never runs. The code settles this without a run: the paired object is always an `NSettlers::Soldier` (the member
is an `NLogic::ReferenceSoldier`, written only by `LinkPairedSoldier` S 006587e0 and by `Load`), a `Soldier`
exists only for a good whose settler type is 3 (`NSettlers::System::CreateSettler` S 00656500; `Jobs.lua` gives
all 16 soldier goods `settlerType_Soldier`), and 3 never equals 0 or 1 [inferred; the comparison of two
different fields looks like a slip in the original code]. Data that sets a `soldierType` of 3 would make the
test true. In play S 00658df0 returned 0 on all 31,676 calls between ticks 53,306 and 124,149 of a developed
save [live, 2026-10-12].
When the order matching finds **no supplier** for a kind-exchange order (category 4), it releases the waiting
wrong-kind soldier of the selected order from the building if `cooldownTicks == 0`, and sets
`cooldownTicks = 10` (`OrderSystem::Update` S 005626c0 → `Military::ReleaseSoldier` S 0055fc40) [known]. So
without a stocked soldier of the wanted kind the old soldiers still leave, at most one per 10 ticks per
building, and the allocation pass (§3.2) then orders level-0 soldiers of the new kind [inferred].

**Promotion by exchange** (S 00560250) [known]: `minLevel` = lowest level among the idle soldiers. If
`minLevel < GetMaxSoldierLevel(tribe, soldierKind)`: for the **first** idle soldier of that level, order a
soldier of `level + 1` of the soldier's own kind through slot 0. Nothing new is trained by this: the order is
served only from soldiers of that level or higher already stocked in a barracks or castle
(`village-buildings.md` §3.12: categories 1/2, "same kind from the requested level upwards") [inferred], and the
soldier sent is the highest level of the kind that supplier holds (S 00565020, §3.2) [known].

**Replacement of the wounded** (S 00560110) [known]: for each garrison soldier, in list order, whose life points
are `<= maxHealth / 2` (integer division, S 0065da50) and for which `IsPairedSettlerTypeEqualSoldierType`
(above; never true with the shipped data) is false:

1. if the soldier has no paired soldier and no order building but holds an order whose reference at `Order+0xb4`
   is valid (`HasUnpairedUpgradeOrder` S 00659390: `Order+0xb4` is the id high word of the building reference
   of soldier slot 0, `Order+0xa0`, so this is a pending promotion order [known]), that order
   and pairing are dissolved first: replacing a wounded soldier takes precedence over promoting it;
2. if the soldier is then idle in the building, order a soldier of the **same good** through slot 2. The
   supplier must hold that exact good, but it sends the highest level of the kind it holds (S 00565020, §3.2),
   so the replacement can be of a higher level than the wounded soldier [known]. The supplier's
   `HasHealthySettler` test is made for the ordered good only, so a higher-level replacement can leave with a
   remembered wounded value of its own good (`village-buildings.md` §3.11) [inferred from S 00558330 and
   S 00565020].

The supplier's flag path cost must be **below** `healthExchangeDistance` (200) (`OrderSystem_FindSupplierBuilding`
S 00562280, order category 5 only; `village-buildings.md` §3.12) [known].

**Exchange hand-over**, the same for the three slots [known unless tagged]:

1. *Order* (`MilitaryOrderSlot::CreateSoldierOrder(oldSoldier, goodId)` S 00568970 →
   `OrderLink_LinkMilitarySlotSoldier` S 0053d2f0): a village order for `goodId` is created; its slot record
   `s` (the slot index) stores the building (`Order+0xa0 + s*0x40`) and the old soldier
   (`Order+0xc0 + s*0x40`); the order enters the slot's `OrderContainer` and the order index; the old soldier's
   order reference (`+0x378`) points to it. The old soldier stays a garrison member.
2. *Match* (`OrderSystem::AssignOrderToSettler` S 00562580 → `VillageOrder_LinkSettlerToDestination`
   S 00561e20, when a barracks or castle supplies a soldier, `village-buildings.md` §3.12): by order category
   4 → slot 1, 1 → slot 0, 5 → slot 2 (S 00561dd0): the new soldier and the old one are **paired** both ways
   (`+0x338`, S 0053d270); the new soldier is added to the slot's waiting list (`MilitaryOrderSlot+4`) and gets
   the building as its **order building** (`+0x358`, S 0053d3d0). It is not a garrison member yet. Then the
   order is removed.
3. *Arrival* (`Soldier::OnEnterBuilding` S 00659300, the soldier's virtual slot +0x20 in the vtable
   S 007f842c; called by `NMovie::EnterBuilding::Update` S 00778c20 when the settler has stepped in: with the
   building at the settler's cell, or, for a type with an entrance direction, after the one-cell door step with
   the building one cell in direction 1 of the settler's cell [known]): a fight state still held is released; if the soldier has an order building,
   first the **paired old soldier is unlinked** from the entered building's garrison, then the new soldier is
   **linked** as garrison member (S 0053c4f0, S 0053c4c0).
4. *Old soldier* (`Soldier::OnUnlinkedFromHome` S 00659140, inside the unlink of step 3): if it has a home, is
   not moving, stands on the home's door cell and is in no fight: a headquarters-type home turns it into a
   stocked good again (state 2), any other home starts LeaveBuilding (state 7). In every case its own open
   order is removed, the pairing is dissolved both ways and its home reference is cleared. Dissolving the
   pairing (`UnlinkPairedSoldier` S 006587f0 on both soldiers) also takes the **new** soldier out of the
   slot's waiting list and clears its order building, so when step 3 links it as garrison member (home
   reference `+0x1c0`, S 00658740) the exchange has left no trace. After state 7 the old soldier has neither
   home nor fight and walks to a storehouse as a homeless settler (§3.5.1).

Dissolving an exchange early (`Soldier::UnlinkOrderAndPairing` S 006588d0) removes the soldier from the slot's
waiting list, clears its order building, dissolves the pairing and removes its open order. Clearing a slot
(`VillageMilitaryOrderSlot_Clear` S 005689f0: slots 0 and 2 on a kind toggle, all three when a fight is
attached to the building S 005606b0, and on destruction)
cancels the slot's open orders and takes every waiting soldier out of the list through S 0053d400, which
clears its order building and dissolves its pairing [known].

**Toggle of the kind** (command 0x20012, `ToggleSoldierKind` S 005600d0) [known]: allowed
(`CanToggleSoldierKind` S 00560390, asked by the callers, not by the toggle itself) when not under
attack, all garrison soldiers are of the current kind and none is in a fight; flips `soldierKind`, cancels the
building's open orders and clears slots 0 and 2.

**Healing** [known]: a soldier that is present in its building and in no fight gains 1 life point each time
its counter exceeds
`regenerationRate`, i.e. every 102nd tick (the counter runs 0..101), up to `gp_setHealth`; outside the building
the counter is reset every tick (`Livepoints::UpdateRegeneration` S 0065dbc0). Soldiers stored as goods in a
barracks heal by the rule of `village-buildings.md` §3.11. The game-wide flag `GameSystem+0xec` stops healing.

### 3.4 Training and promotion in the barracks

A `casern` building runs the production cycle of `village-buildings.md` (`bp_setProductionTime(…, 333)`,
`bp_setRestTime(…, 55)`); the cycle calls into `SoldierTraining` [known] S 005668e0, S 00566920, S 00566990:

- **Can start**: a training slot is ready, or the upgrade is ready.
  - Slot ready (S 00569cb0): slot enabled, the input stock holds the whole `gp_addCost` list of the slot's
    soldier good, and the good is not locked for the player (lock kind 3).
  - Upgrade ready (S 00569b60): upgrade enabled, the input stock holds 1 coin, and for kind 0 or 1 some level
    `0 .. max - 1` has a soldier in the **output** stock whose good is not locked (lock kind 3; S 00569940,
    S 005698a0). `FindUpgradableSoldier` S 005698a0 returns −1 at once for a kind whose maximum level is 0, so
    a kind with a single level never makes the upgrade ready [known].
- **Start** (S 00566920): advance `currentSlotIndex` (0 ↔ 1) up to two times until a ready slot is found; that
  slot removes its cost from the input stock, re-requests the same goods and is `running` (S 00569d50).
  Independently, if the upgrade is ready it becomes `active`. Then `running = true`. So one cycle can train one
  soldier **and** promote one.
- **Finish** (S 00566990): each running slot adds one soldier good to the output stock, +1 to the player's
  statistics, and stops `running` (S 00569d10).
  The upgrade (S 00569970) [known]: move the upgrade's cost list (1 coin) from the input stock to the output
  stock; then up to two tries, each of which first flips the round-robin kind: for levels `0 .. max` of that
  kind in the current owner's tribe (looked up at this call, unlike the training slots of §2.5), the first
  level whose soldier good the output stock can pay for (`SettlerSpawn::CanAffordGoodCost`, then
  `ExchangeCostForGood`: remove the whole cost, i.e. the lower soldier and a coin, add one soldier) is made;
  re-request the coin, +1 statistics, done. If both tries fail and the upgrade is still enabled, the coin goes
  back to the input stock; with the upgrade switched off it stays in the output stock. The loop starts at
  level 0, whose cost is weapon and drink: with those goods in the **output** stock a level-0 soldier is made
  here and the coin stays in the output stock. Normally weapon and drink are in the input stock.
- Input requests are re-synchronised by `VillageSoldierTraining_UpdateInputRequests` S 00566ba0, which runs
  only when a slot or the upgrade is switched (`SetSlotEnabled` S 00566db0, `SetUpgradeEnabled` S 00566dd0:
  commands 0x20018 / 0x20019, the computer player, and `Building::ctor_Place`) [known]. It rebuilds the two
  good lists (§2.5); for each required good, in ascending good id, it first moves every unit of that good lying
  in the **output** stock to the input stock, then requests it up to `stockLimit(HP-scaled) * amount in the
  list`; then, for each good that is only in the list of the disabled parts, it cancels **every** request for
  it, served and unserved, in vector order (`NeedGoods::CancelAllRequestsOfGood` S 0064e6d0), and moves its
  units from the input to the output stock [known].
- The executors of 0x20018 and 0x20019 (S 007823f0, S 00782480) test neither the building type nor the
  sender, and every building has the training component (§2.5), so the commands also act on a building that is
  not a barracks: they switch its training parts and file requests for the soldier inputs into it [known].
- Production on/off (0x2000A) does not pause a barracks whose training is switched on: for a `casern` type
  `Production::IsEnabled` S 00565580 is `SoldierTraining::IsAnyEnabled` S 005668b0 (a training slot or the
  upgrade on), so the toggle always calls `SetEnabled(false)`, which clears the requests and moves the input
  stock to the output stock, and never turns anything back on (`village-buildings.md` §3.7) [known].
- A cost check with an empty cost list passes (`Stock::CanAffordGoodCost` S 00539b90), so in the upgrade loop a
  soldier good without `gp_addCost` would be created for the coin alone [inferred].

The castle is `casern`, `depot` and `territoryBuilding` in `buildings.lua` [known]. `Building::ctor_Place`
S 0055d980 switches **both training slots and the upgrade off** for every type that is `territoryBuilding` and
`depot` [known]. The castle also has `bp_setWorkerLimit(castle, 0)` and no `bp_setProductionTime`, and the
training calls above are reached only from the production cycle that a worker's production movie starts
(`Production::CanStartProduction` S 00565bd0, `StartProductionCycle` S 005657c0, `OnProductionFinished`
S 00565f80, each behind the `casern` test) [known]. A building can supply a soldier order only when its
output stock holds a soldier good of the tribe and the wanted kind (`SettlerSpawn::CanSupplyGood` S 005643c0:
no cost exchange for soldier goods) [known]. So a castle stores soldiers and hands them out as a depot but does
not train or promote by this cycle [inferred]. Nothing else starts the cycle [known]: `StartProductionCycle`
S 005657c0 has exactly two callers, `NMovie::ProduceGood::Start` S 00777460 and `NMovie::GoAfforest::Start`
S 0077bcb0, both steps of a worker's movie that take the building from the worker's workplace reference
(settler +0x120); `VillageSoldierTraining_StartNext` S 00566920 is called only from S 005657c0, and
`VillageSoldierTraining_Finish` S 00566990 only from `OnProductionFinished` S 00565f80, whose only caller is
`NMovie::ProduceGood::Update` S 00777430. A building without a worker therefore never trains or promotes.

### 3.5 Attack: start, dispatch, defence

Who may be attacked and with how many soldiers is specified in `../navy-and-military.md` §2 and §3 and was
re-read for this document; the statements there hold. Additions and corrections:

- Button code 7 and target state 5 are the **peace time** sacrifice (`Effect_PeaceTime`, §3.9): no attack by
  or on a player while it runs [known: `SacrificeModifierQuery::IsPeaceTimeActive` S 00661c30 tests the
  player's modifier flag at `+0x28` > 0 (S 00663440), the int flag of effect index 10; callers S 0055fdc1,
  S 005716a4, S 005716bd, S 00575a09].
- "Proximity zone" there is §3.1 here. A target must be in zone 2 by its **own** `enemyDistanceB`, measured to
  any enemy, not to the attacker in particular [known] S 0055fd90.
- An **unoccupied** non-headquarters building with `bp_setSoldierLimit != 0` cannot be attacked (target state 3)
  [known].
- `GetAttackTargetState` S 0055fd90 tests in this order and returns the first hit [known]: 1 under construction;
  5 owner in peace time; 4 already the target of a fight; 3 unoccupied (as above); 2 zone B is not 2; else 0.
- A building available as attacker source: not `depot` type, finished, all garrison soldiers of the building's
  `soldierKind`, and not the target of another fight. Counted soldiers: state 0xc and present in the building.
- The command handler does not check that the target belongs to an enemy (`game-commands.md`) [known]. It
  starts the attack when the target building exists and has no valid fight reference, with the fraction taken
  as raw f32 from the command (`HandleStartAttack` S 00782cb0) [known].
- The fraction the menu sends is at least `1 / (2 * n)`, `n` = the largest number of available attackers of
  any single own building (`Military_GetMinAttackerFraction` S 00575f00: minimum of `1 / (2 * n)` over the
  attacker's territory buildings with `n > 0`, start value 1.0) [known], so that the building with the most
  soldiers sends at least one. The computer player computes its own fraction (`ai-player.md`).

**Start** (`NMilitary::Attack::StartAttack(attacker, target, fraction)` S 00576500) [known]:

1. Create the fight (`startCountdown = waitForTacticTime`), bind it to the target: the target's three exchange
   slots are cleared, `defenderPlayer` is set, the computer players are told.
2. `target.defenceFraction = owner.defenceFraction`. A defending computer player's attack watch writes its
   own value into the same field (`AttackWatch` S 0059b3f0, `ai-player.md`), but the watch is created inside
   step 1 (`Fight::SetTargetBuilding` S 00570760 → S 0053be90 → S 00585cd0), so this assignment replaces it:
   the player setting is what counts [known from the call order in S 00576500].
3. Dispatch attackers: for every territory building of the attacker in list order,
   `n = trunc(GetAvailableAttackers * fraction + 0.5)` in single precision (`(int)(float)((float)(n·f) + 0.5f)`,
   S 005763a2; `../navy-and-military.md` §3.4) [known]; if `n > 0` send by sea or overland
   (`Military_ShouldAttackBySea`).
4. Message `!You are under attack!` to the defender, at the target.

`g_bSeaAttackDispatch` S 0088a4cc is 1 only around the attacker dispatch of step 3 (its only writes are in
S 00576500); it is passed to every harbour lookup below and lets a ship with an active mission count as ready
(`../navy-and-military.md` §5.1) [known].

**Attack availability** (`Attack::GetAttackAvailability(target, player, persistentCache)` S 005759f0) [known]:
7 while the player is in peace time; else by the target state (`GetAttackTargetState` S 0055fd90) 1 → 5, 2 → 1,
3 → 6, 4 → 3, 5 → 7; else, with enemy territory in range (`Military_IsEnemyTerritoryInRange`), 0 when
`Military_CountAttackersByKind` at scale 1.0 without the availability test counts any soldier, else 8; otherwise
the harbour test (`Military_IsHarborWithinBuildingRange` S 00574f70, reason preset 4): in range → 1, else reason
1 → 2, 3 → 4, 2 and 4 → 1, any other → 0. `Military_IsAttackAvailable` S 00575b50 is this value = 0.

**Attackers per soldier kind** (`Military_CountAttackersByKind(target, player, persistentCache, scale, out,
checkAvailability)` S 00575fd0) [known]: with `checkAvailability`, a non-zero availability returns at once and
leaves `out` untouched (the callers zero it). Otherwise, for every territory building of the village in list order
whose owner is the player, `trunc(GetAvailableAttackers(target, building, persistentCache) × scale + 0.5)`
(S 00576060, the same single-precision sequence as the dispatch of step 3, so the attack slider shows what an
attack sends) is added to `out[kind]`, the kind being the building's military component `+0x68`; the index is not
checked (S 0057607c). Callers: `GetAttackAvailability` (at S 00575b06, scale 1.0, no availability test, its own
`persistentCache`), the attack slider's `UpdateLabels` S 006247a0 (twice, `persistentCache = 0`, with the test; the
menu's other military queries pass 0 as well, S 00623f37, S 00623f50, S 0062473f) and the computer player's
`AiAttack_ScoreAttackersVsFightHistory` S 0059e930 (at S 0059e99d: `persistentCache = 1`, scale 1.0, with the test;
[ai-player.md](ai-player.md)), so the computer player's counts go through the persistent path cache.

**Soldiers one building can send** (`GetAvailableAttackers(target, building, persistentCache)` S 00575dc0)
[known]:

1. 0 unless `CanProvideAttackers` S 0055fc60; 0 if the building is bound to a fight (`Military` fight
   reference valid) and is not the target itself.
2. `reach = Military_GetAttackReachFactor(building, target)` S 00575320; `reach <= 0` gives 0.
3. `n` = number of soldiers with `IsAvailableInBuilding`, counted as a float; result `trunc(n * reach)`.
4. A result above 0 is returned only if the building is the target or
   `Military_IsTargetReachable(target, building, persistentCache, allowSea = 1)`; else 0.

`falloff(a, b)` S 00574fe0 with `d = hexDistance(a, b)`: `d >= 24` gives 0, else `min(36 - d, 24) / 24` (1.0
up to 12 cells) [known]. "Landmass" below is the continent id of the cell (`NMap::Continents`).

`reach(building, target)` S 00575320 [known]:
- same landmass: `f = falloff(building, target)`; if `f == 0` the sea branch is tried, else `f` is the result;
- other landmass, or `f == 0`: the sea branch gives `falloff(building, H2)` when the target's owner is an enemy
  of the building's owner (`Player::IsEnemyOf` S 005be280), `Military_IsHarborWithinBuildingRange` S 00574f70
  holds (a harbour **H1** of the target's owner on the target's landmass, ready for the attacker, closer than
  `territoryRange(target) + 1` to the target) and `FindOwnHarborConnectedToTargetHarbor` S 005b65d0 finds the
  attacker's harbour **H2** on the building's landmass with an exit route to H1, nearest to the building and
  closer than 25 cells; otherwise 0. The distance from H1 to the target does not count.

`IsTargetReachable(target, building, persistentCache, allowSea)` S 00575cb0 [known]: `D` = hex distance of the
two buildings; `E(x)` = the neighbour of building cell `x` in direction 1. True if
`cachedPathLength(E(target), E(building)) < 2 * D`; else, with `allowSea`, true when the enemy test, the H1
test and the H2 lookup above succeed and H2 is closer than **24** cells to the building; else false.
`cachedPathLength(from, to, persistent)` S 00575b70 [known]: one of two static maps (`persistent` selects the
saved one) keyed `(index(from) - 1) * 0x10000 + (index(to) - 1)`, `index = y * mapWidth + x`; a map is emptied
when `tick > stamp + 111` and the stamp set to the tick; a miss runs the map A* (`NMap::AStar::FindPath`, mode
0) and stores its step count, or 0x7fffffff when it finds no path. The step count (`AStar::GetPathStepCount`
S 00676a90) is 1 when the two cells are neighbours; otherwise it walks from the start cell, at each cell taking
the lowest-numbered descent direction of the search result (the previous direction where none descends), and
counts the steps to the goal; it draws no random number [known].

`ShouldAttackBySea(building, target)` S 00576250 [known]: with `D` as above, false (overland) when
`cachedPathLength(E(target), E(building), persistent) < 2 * D` and `reach(building, target) <=
falloff(building, target)`; true otherwise. On one landmass with `d < 24` the two values are equal, so a
building with a short enough walk goes on foot; by sea when the walk is too long, or when `d >= 24` and the
sea branch gives a factor above 0 [inferred from the two formulas].

**Choosing the soldiers of one building** (`AttackConnector::AssignBestSoldiers` S 005751e0) [known]: iterate
the levels of the building's kind from the **highest down**; at each level repeatedly take the available soldier
with the **most life points** (strictly greater wins, so the first in list order on a tie; a soldier with 0
life points is never taken) until none of that level is left or `n` are assigned. Each chosen soldier is bound to
the fight (added to its side list, `leftFight = false`, `assignDirty = true`). A `depot` type building (castle)
first turns **all** stocked soldiers of both kinds into settlers (S 005750e0: each kind from its highest level
down; per round up to **two** of kind 0, then **one** of kind 1, until both kinds are exhausted; each becomes a
garrison member in state 0xc, spawned by `SettlerSpawn::SpawnSettlerRestoringValue`), then sends all of them
regardless of `n`: it
sets the building's `soldierKind` to 0 and assigns every available sword soldier, then sets it to 1 and
assigns every available bow soldier, so the castle's `soldierKind` is left at 1 (S 00575490) [known]. A `depot`
type is never an attacker or helper source (`CanProvideAttackers` S 0055fc60 is false for it, so its available
count is 0), so this branch runs only for a castle that is itself the target, in the defence dispatch below
[inferred from the callers].

**Leaving the building** (soldier states, §3.5.1): a bound soldier waits in the building until
`startCountdown == 0`. Then soldiers leave **one per building every 10 ticks** (`cooldownTicks`).

**Defence** (when `startCountdown` reaches 0, `DispatchDefenders` S 00576400) [known]:

- the target's own garrison: all available soldiers (`n = 0x7fffffff`, without the source test or the reach
  factor), by the same selection;
- every other territory building of the defender: `trunc(GetAvailableAttackers(target, building) *
  target.defenceFraction + 0.5)` in single precision (S 005764b1), always overland. `GetAvailableAttackers` applies the same distance falloff as
  for attackers (full up to 12 cells, 0 from 24).

In addition a soldier idling in a building that is under attack joins on its own once the fight has started and
the enemy side has an engageable soldier (state 0xc, below) [known].

There are **no later reinforcements**: nothing dispatches again after these two moments [known: the
callers of `DispatchAttackers` S 00576320 are `StartAttack` S 00576500 and the computer player's strength
estimate `AiAttack_EstimateStrengthRatio` S 0059f290; those of `DispatchDefenders` S 00576400 are
`Fight::Update` S 005715a0 at countdown 0 and the same estimate, which counts through its own
`ISoldierConnector` instead of sending]. The attacker can only start a new attack after this fight has ended.

**Retreat** (command 0x2000E) and the computer player's attack watch call `Military_RequestCancel` S 00570900:
`ending = true`, `endCountdown = actionsInFightDelayTime` (300) [known]. The command is honoured only when the
target building has a valid fight, the sender is that fight's `attackerPlayer` and the phase is Fighting
(`HandleCancelAttack` S 00782bf0) [known]. The attack watch (`AiAttackWatch_Evaluate` S 0059b2f0) acts once
per fight, only after the fight has started (`startCountdown == 0`), while the target is valid and still owned
by `defenderPlayer`, and only when the computer player's strength ratio in the fight is below 0.5: as
attacker in phase
Fighting it retreats with a profile chance; as defender of a non-headquarters building whose
`destroyCountdown` is idle it starts the demolition countdown (§3.8) with another profile chance. Each of the
two decisions draws one logic random number (`% 100`) [known; chances and ratio: `ai-player.md`].

#### 3.5.1 Soldier states

`NSettlers::Soldier::Update` S 006594a0 [known unless tagged]. Before the state switch, every tick: base
settler update; exploring radius 2 around the cell the soldier just left when it changed cell while moving;
**death** when life points < 1
(release home and projectiles, start dying); healing (§3.3); and a soldier that has no ship, no home, no order
building and no fight (outside states 1, 7, 0x11) becomes a homeless settler (state 3).

| State | Meaning | Transitions |
|---|---|---|
| 1 | created | home is headquarters type → 0xc; else LeaveBuilding movie → 0x11 |
| 0x11 | leaving the supplier | done → GoToWorkingPlace (4), or by ship (0x26 / 0x36); none → homeless |
| 4 | walking to the home building | arrived on the home cell → 0xc; else homeless |
| 0xc | in the building | bound to a fight whose countdown is 0 → 0xf. Not bound, home is headquarters type → 2 (becomes a stocked good again). Not bound, home under attack, fight started, enemy side engageable → bind to that fight |
| 0xf | waiting to leave | no home, or home `cooldownTicks == 0` (then set it to 10) → LeaveBuilding → 7. While waiting: if this soldier or any attacker has `leftFight`, or the enemy side has no engageable soldier while the defender list ever had members → unbind, back to 0xc |
| 7 | leaving the building | done: fight and target valid → enter fight (link as attacker or defender of the target, `inFight = true`) → 0x28; else → 0x21 |
| 0x28 | entered | no fight → 0x2d. `cellA` = own side's gathering cell. No ship link → 0x29; ship link with a target harbour → walk there (0x34); ship link without one → stays in 0x28 |
| 0x29 | decide | §3.6.2 |
| 0x2a | walking to `cellB` | §3.6.2 |
| 0x2b | at `cellB` | §3.6.2 |
| 0x2c | stepping to the fine slot | arrived → request reassignment → 0x2e |
| 0x2e | fighting | §3.7 |
| 0x30 | striking | strike movie done → 0x2e and pause `attackWaitTime + random(0..9)` ticks |
| 0x2f | returning to the cell grid | done: should leave → 0x2d; else walk to `cellB` (0x2a); cannot → 0x2d |
| 0xd | walking to the target's flag (`MoveToAttackBuilding`, §2.6) | arrived on the flag cell and allowed to enter → **capture** (§3.8); in every case → 0x2d |
| 0x2d | leaving the fight | stop the walk with `holdStep` (finish the current step) and wait until not moving; `LeaveFight`; back on the grid (0x2f) → 0x21 |
| 0x21 | going home | ship link → walk to the ship's target harbour (0x31); home → ReturnToMilitaryBuilding (0xe); neither → homeless |
| 0xe | walking home (`ReturnToMilitaryBuilding`, §2.6) | arrived and present in the building → 0xc; else unbind → homeless |
| 0x31..0x37, 0x26 | sea transport | `../navy-and-military.md` §4 |

**Orders taken on the way home** (`Soldier::TryCompleteOrderAtCurrentPos` S 0065a340) [known]: when a soldier
without a home starts its walk home (`NMovie::MoveToHome::Start` S 007776f0, the only caller), it first looks
for a building of its own player on its cell (`FindBuildingAtOrNearest`, radius 0) or, failing that, one cell
in direction 1 when that building's type has an entrance direction, and takes that building's entrance flag;
otherwise an own flag on its cell. At that flag `OrderSystem::FindOrderForSoldier` S 00561cb0 picks an open
order (§10 #9) and `AssignOrderToSettler` S 00562580 links the soldier to it as if a supplier had sent it; the
walk home is then not started. A soldier that afterwards still has no home, no order building and no ship
stops (state 3); one that stood at a building leaves it (LeaveBuilding, 0x11); otherwise it starts towards its
working place (slot 11 of §2.6).

`LeaveFight` (S 0065be90) [known]: unlink from the target's attacker / defender list, from the opponent and the
group, delete every group that targets this soldier, reset the three cells to -1, `leftFight = true`,
`inFight = false`. `ReleaseAll` (S 0065bfe0, on death and on unbinding) also clears the opponent link of every
soldier attacking this one, removes the soldier from the fight's side list and from its ship.

Removing the **last attacker** from the side list while the target is still valid and not owned by the attacker
posts `!attack failed` to the attacker and `!attack averted` to the target's owner (S 005719b0) [known].

### 3.6 The fight object

#### 3.6.1 Fight update (`NMilitary::Fight::Update` S 005715a0), every tick

[known]

1. If not **active**, return. Active = (not: countdown running and target reference invalid) and (a side list
   is non-empty or a ship is linked) (S 00571090). An inactive fight is deleted by the list right after its
   update (§4).
2. `startCountdown`: if not 0, decrement; when it reaches 0: dispatch defenders with the target's
   `defenceFraction` (`Military+0x64`), record the fight for the computer players, compute the gathering
   positions, set the gathering mode and slots, and if **either side has no sword soldier** (`countByKind[0]`
   of side 0, then side 1) set both `contact` flags.
3. If not `ending`: if the attacker or the defender is in **peace time** and the phase is Fighting:
   `ending = true`, `endCountdown = 0`.
4. Otherwise (`ending` was already set when the tick began): when `endCountdown == 0`, flag every attacker
   (`leftFight = true`, `retarget = true`, S 005714a0); then, if `endCountdown > -1` and the game-wide flag
   `GameSystem+0xec` is clear, decrement it. Steps 3 and 4 are the two branches of one test on `ending`, so a
   fight that starts ending in step 3 releases its attackers in the next tick, not in this one.
5. If `startCountdown == 0` and `assignDirty`: run the assignment pass, clear `assignDirty`.

**Phase** (`GetPhase` S 005708a0) [known]: 1 Gathering (`startCountdown != 0`); 2 Ending; 4 NoTarget (target
reference invalid); 3 TargetCaptured (target owned by the attacker); 0 Fighting.

**Target lost** (`ReleaseTargetBuilding` S 00571720, when the target building object is unlinked) [known]: if
the phase is Fighting and the defenders still have an engageable soldier: `ending = true`,
`endCountdown = actionsInFightDelayTime / 10` (30). The target reference is cleared. When the target is destroyed,
this runs from the military component's destructor inside `Building::dtor` S 0055ce70 (`Military::dtor`
S 005606f0, after the territory updater's), while the building object still exists, so the phase is still
Fighting [known]. The component destructors that run between the AI notification and the military one (depot,
construction, workers, production, settler spawn, territory updater, bulldozing) read no military, fight or
garrison state [known] S 0055af70, S 0055e8c0, S 0055b620, S 00565270; the AI's `OnBuildingRemoved` S 005836d0
reads no projectile state, and the military destructor reads none of their state either: it unlinks the fight
(S 0053cf80), the attackers and defenders (S 0053d1e0 / S 0053d180, references only), clears the order slots
(S 005689f0) and releases the garrison (`Soldiers::dtor` S 005666c0 → `ReleaseAll` S 005665f0), so the order of
these destructors is not observable [known]. Under batch editing `ReleaseAll` removes the garrison soldiers
(`NSettlers::System::RemoveSettler`) instead of unlinking them (`map-editor-devtools.md`) [known] S 005665f0.

**Gathering positions** (S 00576fb0, S 00576d00) [known; summary in `../navy-and-military.md` §4]: `r` =
smallest `bowRange` among the bow soldiers of both sides (0x7fffffff if none). Every distance below is measured
to the **target's entrance flag cell** `F` (the flag referenced at `Building+0xa0`, its cell at flag `+0x28`),
not to the building's anchor. `origin` = the attackers' origin cell (below); path from `F` to the origin; `d` =
hex distance origin–`F`. On that path: centre = the cell at distance `d / 2` from `F`, far = at
`min(d / 2 + r / 2, d)`, near = at `max(d / 2 - r / 2, 0)` (integer divisions; with no bow soldier, far = `d`
and near = 0; every path cell is tested in path order and a later match overwrites an earlier one; a slot for
which no path cell matches keeps its previous value).

**Origin cell** (`Military_GetAttackOriginCell(attacker side list, F, target owner)` S 00576d00) [known]:

1. Among the attacker side list's soldiers, in list order, that have a home: the home whose anchor lies on the
   same continent as `F` (per-cell continent id, `NMap::Continents`) with the smallest hex distance from its
   anchor to `F` (strict `<`, first wins a tie).
2. If there is none: the nearest finished building of the **first** listed soldier's owner in the village's
   territory-building list (`FindNearestCompletedInList3C` S 005578f0: smallest hex distance from the anchor to
   that soldier's cell, strict `<`; may be none).
3. `H` = `HarborList::FindNearestWithPlayerShipRoute(F, first soldier's owner, target owner, 1, null)`. If `H`
   exists: when the building of steps 1–2 (its entrance flag cell; without a building the first soldier's
   cell) is not farther from `F` than `H` **and** that building's anchor lies on `F`'s continent, go on to
   step 4; otherwise the origin is `H`'s cell.
4. The origin is the building's entrance flag cell; without a building, the first soldier's cell.

Step 3 reads the building's anchor without a null test, so "no building, a harbour, and the first soldier at
least as close as the harbour" dereferences a null building; step 2 reads the first soldier without testing
that the list is non-empty (§9). The path is searched from the target's entrance flag cell
to the origin (`AStar::FindPath`); if none is found, the origin is replaced by the nearest harbour in the
target's water body (`HarborList::FindNearestInWaterBody`) and the search repeated, and `d` is then measured to
that harbour; the harbour is used without a null test, so no path and no harbour dereferences a null pointer
[known, S 00576fb0]. The path is built with `AStar::BuildPath(…, randomize = false)`, which draws no random number
(the randomizing variant of that function does) [known] S 00576fb0, S 00676d10. When origin and entrance cell
are equal the path is that single cell.

**Gathering mode** (S 00577210) = (attackers have no sword soldier ? 1 : 0) + (defenders have none ? 2 : 0), and
the slot of each side (`GetSlotForSide` S 00576b10) [known]:

| Mode | Attackers | Defenders |
|---|---|---|
| 0 | centre | centre |
| 1 | centre | far |
| 2 | near | centre |
| 3 | its current slot when both sides' slots are valid and differ; else mode 2's: near | the same test; else mode 2's: centre |

Any other mode gives −1 (S 00576b10). Recomputed whenever a soldier is removed from the fight. A soldier or new group looks for a free cell around
`slot'`, where (`MilitaryFight_PickGatheringSide` S 00576b80) [known]: sword → the side's slot; bow, attacker
side → slot 1 if the side's slot is 0, else slot 0; bow, defender side → slot 2 if the side's slot is 0, else
slot 0.

**The three cell searches** share one breadth-first flood fill (`ai::map::FloodFillSearch::Run_*` S 00572210,
S 00572610, S 00572410; the visited grid is the map's, `NMap::System+0x40`) [known]:

```
if not canExpand(start, start): fail
if accept(start): done
queue = [start]; mark start
while queue not empty:
    cur = pop front
    for n in neighbours of cur in the order SE, E, NE, NW, W, SW:     // directions 5, 0, 1, 2, 3, 4
        if n is on the map and not marked and canExpand(cur, n):
            if accept(n): done
            push n at the back; mark n
fail
```

The neighbour order comes from walking the ring: one step in direction 4 from `cur`, then one step each in
directions 0..5 (`MapPos::StepDirection`, direction table in `map-resources.md` §3.1). The first accepted cell
in this order wins; there is no other tie-break.

- **Soldier cell** (`Fight::FindFreeGatheringCell` S 00572810, a soldier without a group) and **group cell**
  (`FindFreeGatheringCellForGroup` S 00572ab0, a new group), start = the gathering cell of `slot'`:
  - `canExpand(from, n)`: `n == from`, or `n` is walkable (`Map_IsCellWalkable`, `map-resources.md` §3.2)
    (S 005787a0). Since the test is made with `from` = the cell being expanded, the start cell is entered even
    when it is not walkable.
  - `accept(n)` (S 00578550, S 005787f0): grid-state bit 0x2 of `n` is clear, object layer 0 holds no object on
    `n`, and `n` is the search's **exempt cell** or is free. The exempt cell is passed by the caller: none
    (-1, -1) for a soldier (S 006594a0) and for a new group on a gathering cell, the enemy group's cell for a
    counter-attack group (§3.6.2 step 4.1; S 00577ec0). Free for a soldier (`Fight::IsCellFree`
    S 005711e0): no soldier of either side list has `cellB == n` and no **sword** group of either side has its
    cell on `n`. Free for a group (`IsCellFreeForGroup` S 00571300): no group of either side has its cell on
    `n` and no member of a **bow** group has `cellB == n`.
  - The result is the last cell tested: when the fill runs dry without an accepted cell, that is the last
    cell that was examined, not "none" [known: the predicate stores every tested cell as result].
- **Archer's ring** (`Fight::ComputeSoldierFightCell` S 005728e0, bow soldier with a group), start = the own
  group's cell; `anchor` and `range` as in §3.6.2; `own` = the soldier's current cell;
  `near = hexDistance(own, anchor) < range` (`FightRingSearch` ctor S 00578650):
  - `canExpand(from, n)` (S 00578600): `n == from`, or `n` walkable and `hexDistance(n, anchor) <= 2 * range`.
  - `accept(n)` (S 005786a0): the first cell ever tested becomes the provisional result. A cell is scored only
    if grid-state bit 0x2 is clear, object layer 0 is empty and (`n == own` or `IsCellFree(n)`):

    ```
    score = abs(hexDistance(n, anchor) - range / 2) + (near ? hexDistance(own, n) : 0)     // integer division
    ```

    A strictly lower score replaces the result; score 0 ends the search. Otherwise the whole reachable
    area within `2 * range` of the anchor is scanned and the first cell with the lowest score wins.
  So an archer stands about half its range from its target, and one that is already within range prefers a
  cell close to where it is.

#### 3.6.2 Pairing: the assignment pass (`FightAssigner::Update` S 00577ec0)

Runs when `assignDirty` (a soldier was added or removed, or a soldier reached its opponent). An **engageable**
soldier is one with `leftFight == false`. [known]

1. `targetKind[side] = (the enemy side has no sword soldier) ? bow : sword`. A side fights the enemy's sword
   soldiers first and its bow soldiers only when no sword soldier is left.
2. **Trim** (S 00577c90, S 005777b0): for kind 0, 1 and side 0, 1 with own soldiers of that kind and an enemy
   count above 0: `ratio = own count of kind / enemy count of targetKind[side]` (f32). Build the size plan
   (below) and take the side's groups of that kind in list order. Drop the groups that **conform**
   (S 00578900: size == ceil while `ceilSeen < ceilGroups`, counting `ceilSeen`; else size == floor while
   `floorSeen < floorGroups`, counting `floorSeen`) and the groups below the floor size (S 005789e0). For each
   remaining group with size >= ceil: if `ceilSeen < ceilGroups`, count it and shrink it to the ceil size,
   else count `floorSeen` and shrink it to the floor size. Shrinking (S 00577670) walks the member list in
   order and removes a member only when it is engageable and no enemy group of kind `targetKind[side]` targets
   it (`IsTargetAvailable` S 005772a0), until enough are removed or the list ends; a removed member that has an
   opponent gets `retarget = true`.
3. **Retarget to attackers** (S 00577a10): for each valid group with more than one member whose kind is what
   the other side targets: let `T` be the group's target. If `T` is in the fight, has a group and an opponent,
   is outside a building, not moving, has a `cellB` and no `retarget` flag: pick the group member with the best
   **score** (below) measured from `T.cellB`. If it is not `T`'s current opponent: `T.retarget = true`, and if
   `T`'s own group targets that old opponent, the group's target becomes the picked member. So a soldier attacked
   by several turns to the nearest, weakest of them.
4. **Assign** for kind 0 then 1, side 0 then 1, when the side has soldiers of that kind and the enemy has
   soldiers of `targetKind[side]`, `ratio` as in step 2. Collect the unassigned soldiers of that side and kind
   (engageable, no group) in side-list order.
   1. **Counter-attack**: for each such soldier `S` that an enemy group of kind `targetKind[side]` targets:
      pick the best-scoring available member of that enemy group (measured from `S`'s cell); if one exists,
      create a new group (side, kind) with `S` as member and that enemy as target. Its cell is searched like
      any group cell, from the side's gathering cell (§3.6.1), with the enemy group's cell exempt from the
      occupancy test. `S` leaves the unassigned list either way.
   2. For each remaining soldier: **join** the nearest own group of the same kind that is below its planned
      size (`FindJoinableGroup` S 005774d0: groups that do not conform to the plan, with size below the ceil
      size while ceil groups are left, or below the floor size while floor groups are left; smallest hex
      distance from the group's cell to the soldier, first found on a tie). When a sword group thereby reaches
      exactly 2 members and its target is a sword soldier: the target and the group's **first** member get
      `retarget = true` if they have an opponent.
   3. If no group can be joined: collect the available enemy targets (kind `targetKind[side]`, engageable, not
      already targeted by a group of this kind, and either in no group or on a side that does not target this
      kind); if any, create a new group on a free gathering cell and target the best-scoring one measured from
      that cell.

**Score** of a candidate `c` seen from position `p` (lower is better, first found wins a tie; S 00577340,
S 00577420) [known]:

```
score = c.lifePoints * 100 / c.maxHealth  +  50 * (hexDistance(c.cell, p) + (c is present in a building ? 100 : 0))
```

**Size plan** (`FightGroupSizePlan::Init` S 00578aa0) for `own` soldiers against `enemy` targets [known]:

```
floor = floor(ratio); ceil = ceil(ratio); if ratio < 1: floor = ceil = 1
if kind == sword and floor >= 6:  floor = ceil = 6; ceilGroups = enemy; floorGroups = 0
else: ceilGroups  = own > floor * enemy ? own - floor * enemy : 0
      floorGroups = (own - ceilGroups * ceil) / floor            // unsigned integer division
```

So soldiers are spread evenly: every enemy gets `floor` opponents and the surplus goes one each to `ceilGroups`
enemies; at most 6 sword soldiers surround one enemy (the six neighbours).

Groups whose target reference is invalid or whose member list is empty are deleted at the start of every tick
(§4) [known] S 005744c0.

**Soldier decisions.** State 0x29 [known]:

1. No fight, or `ShouldLeaveFight` → 0x2d. `ShouldLeaveFight` (S 0065b780): `leftFight`, or the fight has no
   target any more and the soldier is on the attacker side.
2. The enemy side has **no engageable soldier**: an attacker-side soldier linked to the target that may enter it
   (§3.8) starts walking to the target's flag (0xd); everyone else → 0x2d.
3. Else `T` = target of the soldier's group.
   - No group: `cellB` = free cell near the side's gathering cell (see above).
   - Group: `T` becomes the opponent. `cellB` (`ComputeSoldierFightCell` S 005728e0):
     - sword: `T.cellB` if `T` has one and `T.retarget` is clear; otherwise the cell of `G` (below) if there
       is one, else the own group's cell;
     - bow: the ring search of §3.6.1 with `range = bowRange`, started from the own group's cell;
       `anchor = T.cellB` if `T` has one and there is no `G`, else the gathering cell of the own side's slot
       (`Fight+0x9c + slot * 8`, the side's slot itself, not `slot'`).

     `G` = `FindGroupByMemberAndAnchor(other side, T, soldier)` S 00571d60: the first group in the other
     side's group list that has `T` as a member **and** whose target is this soldier, i.e. the group with
     which the opponent fights back at exactly this soldier [known]. The own group is
     `FindGroupOfSoldier(own side, soldier)` S 00571c60: the first group of the side's list that has the
     soldier as a member or as its target [known].
     If the soldier's sword group is **not outnumbered** (below), its walk stops one step short of the target
     cell (`ai::settlers::SettlerMovement::SetStopDistance(movement, 1)`; a stop distance `n` ends the walk `n`
     cells short, `settlers-jobs.md` §3.8 [known]).
4. `cellB` unchanged → 0x2b (or first back to the grid, 0x2f, when outnumbered and off-centre). Changed → walk
   there (0x2a), via 0x2f when off-centre; walk impossible → 0x2d.

State 0x2a: arrived → if the walk was a stop-short walk → 0x2b, else request reassignment → 0x2e. While
walking: if the enemy side has no engageable soldier, or the soldier has no opponent but its group has a target,
the walk is aborted by setting `holdStep` (the current step is finished, then the soldier stops;
`settlers-jobs.md` §3.8.2) and the decision repeats [known].

State 0x2b: no opponent → 0x29. Sword group not outnumbered → pick the **fine slot** (`PickSoldierFightSlot`
S 00572130, S 00578400) [known]: take the soldier's own `cellB` (for a sword soldier normally the opponent's
cell, see above) as a fine position (`4 * x` (+2 on odd rows), `4 * y`); try its six fine-grid neighbours in
direction order 0..5; skip
a neighbour that is the `cellC` of a member of the soldier's group, unless it equals the soldier's own current
`cellC`; of the rest take the one with the smallest hex distance to the soldier's fine position (the first on
a tie). Store it in `cellC`, step there (0x2c). Otherwise walk to `cellB` (0x2a), first back to the grid
(0x2f) when off-centre; when the walk cannot start, it is started once more with `astarMode = 1` (movement
`+0x70`, the free path's byte: the A* step cost ignores blocking, `settlers-jobs.md` §3.8.3) [known].

**Not outnumbered** (`IsMeleeGroupNotOutnumbered` S 00572060) [known]: false for a bow soldier or a soldier
without a group. Let `own` = number of members of the soldier's group, `T` = that group's target and `G` as
defined above (the enemy group that contains `T` and targets this soldier). True if no such `G` exists; true if
`G` is a bow group; false if `own < |G|`; true if `own > |G|`; on equal sizes true for the attacker side and
false for the defender side. `G` only exists for the one soldier the opponent has turned on, so every other
member of a group counts as not outnumbered [inferred].

`RequestReassignForSoldier` (S 00570c90) [known]: sets `assignDirty`; when a sword soldier's opponent is not
moving, also sets both `contact` flags: the first melee contact opens fire for all archers of the fight.

### 3.7 Striking

State 0x2e, every tick [known] S 006594a0:

1. No fight → 0x2d. If `retarget`: drop the opponent, clear the flag. No opponent → 0x29.
2. Only when the pause timer has run out:
   - **Sword**: if the opponent is not moving and the hex distance of the two **fine** positions is < 2 →
     strike. Otherwise drop the opponent if (the opponent has a `cellB` different from the soldier's) or the
     opponent has `leftFight`, or (the soldier's group is outnumbered and the soldier is off-centre).
   - **Bow**: if the opponent has not left and the `contact` flags are not both set → wait. Else if the hex
     distance of the two cells is `<= bowRange`, the opponent is not aboard a ship and not present in a building
     → strike. Otherwise drop the opponent if it has `leftFight` or is not moving.

**Strike start** (`NMovie::Fight::Start` S 007798d0) [known]:

```
duration  = sword ? attackTime : trunc(attackTime * archerAttackSpeedFactor)        // §3.9
threshold = striker.blockingChance + (opponent is moving ? 50 : 0)
if bow: threshold = threshold - trunc(archerHitChanceFactor * 100.0) + 100
roll      = LogicRandom_Next() % 100
strikeHits = threshold < roll
start animation kind 4 for `duration` ticks
```

Note that the threshold is the **striker's own** `blockingChance`: a level-0 halberdier (2) hits with
probability 97/100 against a standing opponent and 47/100 against a moving one; a bow soldier (0) 99/100 and
49/100 [inferred from the formula]. `roll` is never negative: the generator returns a value in
1..0x7fffffff [known] S 006ec350.

**Hit moment** (`NMovie::Fight::Update` S 00779a70, `TryApplyStrike` S 00779980) [known]: each tick, with
`t = duration - remaining`, a hit time `h` of the soldier good fires when `t - 1 < h <= t`. When the running
strike is shorter than the good's `attackTime` (`duration < attackTime`; soldier vtable S 007f842c slot +0x30 =
S 00658ea0), the times are stretched by `k = attackTime / duration` (slot +0x34 = S 00658ed0, f32): the test
is `t * k - k < h <= t * k`. Only a bow soldier under `Effect_ArcherAttackSpeed` below 1 has a shorter strike
(§3.9), so its hit times, given on the `attackTime` scale, still fire [known]. Every listed hit time fires
once, so a good with two `gp_addHitTime` entries (the Egyptian sword soldier: 4 and 15) hits twice per strike
with one roll.

- **Sword**, if `strikeHits` and the opponent is still set: `opponent.TakeDamage(striker's player,
  StrikeValue(striker))`.
- **Bow**, if the opponent is still set: shoot a projectile (`ai::settlers::Bow::Shoot` S 0065f270): `flightTicks =
  trunc(hexDistance(target cell, shooter cell) * cfg_setBowFlightTimeFactor)` (2 per cell; the conversion
  sets the FPU to truncation, read in the disassembly), type from the good,
  `damage = StrikeValue(shooter)` taken **when shot**. If `strikeHits` is false the projectile is unlinked from
  the target at once: it flies and does nothing.

When the animation ends `strikeHits` is cleared and the soldier pauses (state 0x30 → 0x2e).

**Strike value** (`ComputeSoldierStrikeValue` S 005721a0, S 00658f20, S 005735b0, S 0052de30, S 00553f70,
factor addresses read in the disassembly) [known]:

```
base = trunc(hitDamage * soldierDamageFactor + 0.5)                // own player's sacrifice bonus, §3.9
m    = 1                                                           // bow soldier, or soldier without group
sword soldier in a group:
    n = number of group members that are not moving                // float count
    r = max(n, 1)
    f = (max((r - 1) * 0.2, 0) + 1) / r      // 0.2 = the double at S 007e6d70, an f32 0.2 widened
    m = f                            // group's target reference invalid
    m = (A + (D - A) * f) / D        // target valid; D = striker's raw hitDamage, A = target's raw armor
value = trunc(float(base * m) + 0.99)                              // product stored as f32, then + 0.99
```

"In a group" = the first group of the soldier's own side that has it as a **member**
(`FindGroupContainingSoldier_B` S 00571f20) [known].

The rounding constant is the double at S 007dee80 = 0.99 (the f32 0.99 widened, 0.9900000095…), added in
S 005721a0 before the truncation: the product is rounded **up** unless its fraction is below about 0.01, and a
whole product is unchanged (so a bow soldier's value is `base`) [known].

With all factors 1 the net damage of a group of `r` standing soldiers per round is about `(1 + 0.2 * (r - 1)) *
(D - A)`, each soldier's share rounded up as above and at least 1: each additional soldier adds 20 %, not 100 %
[inferred from the formula].

**Damage** (`Soldier::TakeDamage` S 00659260) [known]:

```
armor = trunc(victim.armor * victimPlayer.soldierArmorFactor + 0.5)
net   = max(1, value - armor)
lifePoints -= net              // skipped while GameSystem+0xec is set
if lifePoints < 1: attacker player's kill counter += 1
                   if the soldier's fight reference is valid or inFight: release the fight state (ReleaseAll)
```

The soldier object dies in its next update (§3.5.1). A projectile hit calls the same function with the stored
damage and the shooter's player (`ProjectileOwner+0x50` of the source, S 00572fa0).
The kill test reads only the life points after the hit, not before it: every hit that leaves them below 1
counts, so a hit on a soldier that is already below 1 but has not had its next update yet (a second projectile
landing in the same military step, §4) credits a second kill [known for the test; the coincidence in play is
inferred]. The kill credit goes to the player passed in, without a test that it is an enemy.

**Projectiles** (`ai::military::MilitaryProjectile::Update` S 00572fa0) [known]: `elapsedTicks += 1` each tick; when
`elapsedTicks >= flightTicks`: target kind 0 (soldier) → `TakeDamage` and a strike notification at the **source**
cell (fine grid); kind 1 (building) → `Building::OnCatapultHit`; otherwise nothing. The projectile is then
deleted. Kind 0 calls `TakeDamage` without testing the settler reference, which is safe because unlinking a
projectile from its target soldier (a missed shot in `Bow::Shoot` S 0065f270, the soldier's death or removal
through `ReleaseHomeAndProjectiles` S 00659400 → S 0053cee0) runs `ProjectileOwner::ClearSettler` S 00570530:
the settler reference is cleared, the soldier's current cell is kept as the target cell and the kind becomes 2
(position). Such a projectile flies on and lands without effect [known].

### 3.8 Capture, castle destruction, demolition

**May enter the target** (`CanSoldierEnterTargetBuilding` S 00571440, `CanSoldierOccupyTarget` S 005707d0,
`HasFreeSlotForSoldier` S 00576900) [known]: the target already belongs to the attacker, or the enemy side has
no engageable soldier; and

```
requiredKind = target owned by attacker ? target.soldierKind
                                        : (attackers: max(0, sword count) < bow count ? bow : sword)
soldier.kind == requiredKind
better = attackers of the same kind, not homed at the target, with more life points than this soldier
better < capacity(target) - (soldiers of the soldier's player already in the target's garrison)
```

So the kind in the majority among the surviving attackers (sword on a tie) takes the building, and the
healthiest soldiers go in, up to the HP-scaled capacity.

**Capture** (`Military_SoldierCaptureTargetBuilding` S 00571af0), when such a soldier reaches the target's flag
[known]:

- Target owner is an enemy of the soldier's owner:
  - **headquarters type** (castle): message `!Castle was destroyed!` (type 1) to all players except the owner,
    with the owner's name (`Player+0x18`, `players-victory.md` §2.2) as its argument and the castle's cell as
    its position, and the building is removed (`NVillage::System::RemoveBuilding(…, spill = true)`). The loss of the last castle defeats the player
    (`players-victory.md`).
  - otherwise `TransferBuildingOwnership(target, soldier's player, withMessages)`
    (`village-buildings.md` §3.16), and the new building's `soldierKind` = the capturing soldier's kind.
- Then, if the (new) building belongs to the soldier's player: `Military_TryAssignSoldierToBuilding`
  S 00574c50: while `wantedSize - garrison - openOrders - 1 < 0`, cancel one open order; if there are none left
  and the value is still negative, the soldier is **not** taken; otherwise the soldier is unlinked from its old
  home and its ship and becomes a garrison member.

The following soldiers find the target owned by the attacker and enter by the same test.

**Re-binding on transfer** (`NVillage::System::TransferBuildingOwnership` S 0055a210; the village side is
`village-buildings.md` §3.16) [known]. The transfer replaces the building object, so the military links are
carried over by hand, in this order:

1. Remembered from the old building: the fight (if its fight reference is valid), the ids of its **attacker
   list** ("list 30"), and the hit points.
2. The old building is removed. Its `Military` destructor unlinks the fight
   (`Fight::ReleaseTargetBuilding`, "target lost" in §3.6.1: with an engageable defender left in phase Fighting
   the fight starts ending with the 30-tick delay; in a capture there is none) and the fight's target
   reference is cleared.
3. The new building is created for the new owner, finished and indexed; its `Military` part starts from the
   constructor defaults (§2.4).
4. Every remembered attacker is linked to the new building's attacker list. The **defender list** ("list 44")
   is not carried over: the defenders' `defendedBuilding` links end with the old building.
5. Hit points are restored.
6. If a fight was remembered: `MilitaryLink_LinkFightToTargetBuilding` S 0053cf50, the same call as at the
   start of an attack: the new building's three exchange slots are cleared and its fight reference is set
   (`Military::AttachFight` S 005606b0); the fight's target reference and `targetCell` are set
   (`Fight::SetTargetBuilding` S 00570760). `defenderPlayer` is written only while it is -1, so it keeps the
   **old owner**, and no new attack watch is created.

The captured building therefore stays "under attack" until the fight object is deleted: no allocation pass,
no upkeep exchanges, no kind toggle, and it cannot be attacked by a third player (target state 4) during
that time [inferred from the tests on the fight reference in §3.2, §3.3, §3.5].

**End of a fight** [known]: there is no explicit result. Soldiers leave one by one (state 0x2d) when their side
has nothing left to do; the fight object is deleted when both side lists are empty and no ship is linked. Its
destructor notifies "fight removed", removes the computer players' attack watch, unlinks the target (the
building is attackable again), deletes its groups and unlinks its ships (S 00571790).

**Demolition under attack** [known]: the destroy command (0x20003, `HandleDestroyBuilding` S 00781150) acts
only while `destroyCountdown < 0`, so a running countdown is not restarted; it checks neither the sender nor
the building type. The menu's own test (`Building::GetDestroyBlockReason` S 0055cd40: 1 headquarters type,
3 type with `constructionTime < 1`, 2 under attack with the countdown already running) is not repeated by the
executor (`game-commands.md`). On a building that is the target of a fight the command only sets
`destroyCountdown = actionsInFightDelayTime` (300) (S 0055fc10). `Military::Update` decrements it each tick
(not while `GameSystem+0xec`); at 0 it posts `!Military Building Destruction executed` to the owner and
`!Attack Target has been destructed` to the attacker (S 00560890), and the village removes the building in the
same tick (`village-buildings.md` §3.6).

### 3.9 Sacrifice modifiers

Per player the sacrifice system keeps, for each effect index, a flag/int, an own bonus and an **effective
factor** = own bonus / hostile divisor, all 1.0 (flags 0) by default [known] S 006634f0, S 006630b0. The
military reads [known, disassembly S 00663610, S 00663370, S 006633b0, S 006633d0, S 006633f0, S 006634d0,
S 00663440, S 00663310]:

| Effect (index) | Used as | Formula | Data example |
|---|---|---|---|
| `Effect_SoldierDamage` (3) | `soldierDamageFactor` = **own bonus** (not the effective factor) | `trunc(hitDamage * f + 0.5)` | 120, 140 → 1.2, 1.4 |
| `Effect_SoldierArmor` (2) | `soldierArmorFactor` | `trunc(armor * f + 0.5)` | 120 → 1.2 |
| `Effect_ArcherAttackSpeed` (5) | `archerAttackSpeedFactor` | `trunc(attackTime * f)`, bow only | 80 → 0.8 (minimum of bonuses) |
| `Effect_ArcherHitChance` (6) | `archerHitChanceFactor` | threshold `- trunc(f * 100) + 100`, bow only | 2 → 2.0 (value not divided by 100) |
| `Effect_SoldierSpeed` (8) | walking speed of soldiers | `cfg_setSettlerSpeed * f` | 300 → 3.0 |
| `Effect_PeaceTime` (10) | flag > 0: no attacks, running fights end | | |
| `Effect_BuildingArmor` (11) | catapult damage | `trunc(damage / f)` | 400 → 4.0 |
| `Effect_ExpandTerritory` (14) | territory range | `bp_setTerritoryRange + value` | 5 |
| `Effect_FunctionSoldierHeal` (1003) | every soldier settler of the owner gets full life points; the remembered life points of the soldiers stocked in the owner's occupied `casern` buildings are cleared (the map at `SettlerSpawn+0x10`; its meaning [inferred], `village-buildings.md` §3.11) | S 00660270, S 0065da20 | |
| `Effect_FunctionSpawnSoldier` (1000) | nothing: the effect dispatcher `Sacrifice::ApplyEffect` S 00660500 has no case for it, and no shipped sacrifice uses it (`properties-data.md`) | | |

With `Effect_ArcherHitChance` 2 the bow threshold becomes `blockingChance - 100` (+50 against a moving
target): every shot hits [inferred].

### 3.10 Catapult

The `Catapult` component object is allocated for every building (`Building::ctor_Place` S 0055d980) [known];
it is driven only by the worker of a building type with `bp_setCatapult` and working mode 5
(`BuildingWorkingMode_Catapult`).

1. **Trigger** (`Worker::TryStartCatapultAttack` S 0065d410) [known]: select a target; if the input stock holds the
   ammunition good and a target was found, start the attack movie. The ammunition is the **first cost** of the
   type's `bp_setGoods` good, not that good itself: `Catapult::HasAmmo` S 00567a30 reads `costs[0]`
   (`GoodProperty+0x04`) of the product slot's good, so the Scots catapult's `catapultStoneScots`, which costs
   `stoneScots`, makes the stock hold stone; the slot good is never created (`tribes-content.md`). Then the movie
   starts (state 0x1d; first `ReturnFromIdle`, state 0x13, when the worker stands at the idle position). How often
   the worker tries [known]: the only caller is the worker's `ChooseNextWork` S 0065d660, working mode 5
   (`settlers-jobs.md` §3.5.3), so a try follows the worker's arrival, every finished attack and every rest. After
   an attack the worker stamps its work tick and rests `trunc(bp_setRestTime * effective[13])` ticks (55 for the
   catapult types; state 0x1e, then `ChooseNextWork` again); a try without a target or without ammunition fails into
   `RestOrIdleOutside` (`Rest`, or `IdleOutside` after 600 ticks without work). With production switched off
   (command 0x2000A) the worker never tries (`ChooseNextWork` step 2). `bp_setProductionTime` (25) is the length of
   the shot, step 3.
2. **Target selection** (`Catapult::SelectTarget` S 00567d20, `CatapultTargetSearch` S 00567c60 / S 00567be0 /
   S 00567ac0) [known]. A building is a valid target (`Military::IsValidCatapultTarget` S 0055fff0) when its cell is
   **explored** by the catapult's owner, its owner is an enemy, it is finished, any fight on it is led by an enemy
   of the catapult's owner (so not by the owner or an ally), and it is an **active military installation**
   (`Military::IsActiveMilitaryBuilding` S 0055fea0): headquarters type, a catapult, or an occupied building with a
   soldier limit. Candidates are appended in this order: the village's catapult list, the territory-building list,
   the catapult list **again**, each filtered to non-headquarters types, then the territory-building list filtered
   to headquarters types; each must be within `bp_setWorkingRadius` (12) cells (`<=`). The landmass filter is off
   for the catapult. Enemy catapults thus appear twice in the candidate list. The choice is
   `candidates[targetSeed mod count]`; `targetSeed` grows by 1 per attack, so a catapult cycles through its targets
   deterministically, with no random number.
3. **Attack movie** (`NMovie::CatapultAttack` S 0077b940, S 0077b880) [known]: `targetSeed += 1`, aim = target.
   Rotate: `turns` = shortest way round the 6 directions from the current direction to the direction of the aim
   cell; animation for `(turns + 1) * cfg_setCatapultRotationTimeFactor` (5) ticks; then the direction is committed.
   If the ammunition is still there: shoot (animation kind 5 for `BuildingProperty+0xd8` ticks, f32 =
   `bp_setProductionTime`, 25 for the catapult types; `properties-data.md`); `Fire` runs when the shoot animation
   **starts** (`NMovie::ShootCatapult::Start` S 0077eb30), so the projectile is in the air during the animation.
   Then the aim is cleared and the catapult rotates back with the same rule; with no valid aim cell the rotation
   target is direction 1 (`NMovie::RotateCatapult::Start` S 0077e980, `Update` S 0077e950). Without ammunition after
   the first rotation the same `CatapultAttack::Update` starts the rotation back (step 0x1e) and returns false, so
   the movie does not end in that tick; this branch does not clear the aim, so the rotation back turns toward the
   same aim cell: 0 turns, `(0 + 1) × 5` = 5 ticks [known] S 0077b880, S 0077e980. The shoot step is
   `NMovie::ShootCatapult` S 0077eb30 / S 0077eb00 (`Start` / `Update`).
4. **Fire** (`Catapult::Fire` S 005678b0) [known]: unless `GameSystem+0xec` is set, remove one ammunition good
   from the input stock and request a new one. Create a projectile of type 1 with `flightTicks =
   trunc(hexDistance(building anchor, aim) * cfg_setCatapultFlightTimeFactor)` (5 per cell; the int distance is
   loaded with `FILD`, multiplied by the f32 factor and stored with the control word's rounding bits forced to
   truncation, `OR 0xc00` at S 005679b5, the same conversion as in `ai::settlers::Bow::Shoot` S 0065f2cd
   [known]). The f32 at `GameSystem+0x78` (`nextTickTime`) is copied into the last fire stamp before the
   projectile is created, also while `GameSystem+0xec` is set. If aim equals target and a building is found at
   or nearest to the target cell (`FindBuildingAtOrNearest`), the projectile targets that building, else the
   position. Projectile damage = `bp_setCatapultDamage` of the catapult's type (10).
5. **Impact** (`Building::OnCatapultHit` S 0055e080) [known]: `damage' = trunc(damage / buildingArmorFactor)`
   of the **hit building's owner**; messages as in `village-buildings.md` §3.15 (`!Building hit by Catapult`,
   refreshed with distance 1, and `!Building destroyed by Catapult` at the projectile's source cell;
   `!Enemy Building destroyed by Catapult` at the hit building's anchor; `quests-sacrifices-stats.md` §3.6.2); `Hitpoints::ApplyDamage`. A
   building at 0 hit points is removed; a damaged military building has a smaller capacity (§2.4), and the
   allocation then releases surplus soldiers (§3.2). The catapult never hits soldiers [inferred: no settler
   target is ever set for type 1].
6. **A building removed while projectiles fly** [known]: the projectiles flying at it
   (`Building::dtor` S 0055ce70 → `MilitaryLink_UnlinkProjectileFromTargetBuilding` S 0053ce30) and the catapult's
   own projectile, whose source it is (`Catapult::dtor` S 005676d0 → `MilitaryLink_UnlinkProjectileFromCatapult`
   S 0053cdd0), become position projectiles at the building's anchor: `ProjectileOwner::ClearBuilding` S 005704c0
   clears the building reference, stores the anchor cell and sets the kind to 2 (position); the player index
   (+0x50) stays.

The attack movie saves only its step: `CatapultAttack::Store` S 0077b7e0 calls the `Store` of `RotateCatapult`
and `ShootCatapult`, which is the empty function S 0064b9c0, then `Package::Store` (`settlers-jobs.md` §7)
[known].

There are no other special units: the projectile types are arrow, catapult stone, bolt and sling stone, and the
only soldier kinds are sword and bow [known: `Jobs.lua`, S 0065f270, S 005678b0].

### 3.11 Territory effect

A military building contributes territory only through the village and map subsystems
(`village-buildings.md` §3.14): when the first soldier arrives the territory updater activates with radius
`bp_setTerritoryRange + Effect_ExpandTerritory` [known] S 0055fca0, S 006634d0. The military subsystem reads
territory in two places: the attack reach test (the attacker owns a cell on the ring at `range + 1` around the
target, `../navy-and-military.md` §2) and `SizeMilitary` placement (size bit 64: no territory building within
4 rings of the site, `village-buildings.md`). An emptied building keeps its source (§3.2). Losing a building
through capture or destruction removes its source; buildings left outside any territory are removed by the
village.

## 4. Update order

Per logic tick, inside `NLogic::System::Update` (`logic-core.md`: village, road net, settlers, …, military,
navy). `NMilitary::System::Update` S 0056ffb0 [known], in this order:

1. `Distances::UpdateBuildingEnemyDistances` — every 11th tick (§3.1).
2. `Allocation::Update` — every 21st tick (§3.2).
3. Projectiles — every tick, list order; finished ones are deleted (§3.7).
4. Fight groups — every tick: invalid or empty groups are deleted.
5. Fights — every tick, creation order: `Fight::Update`, then deletion if inactive.

Elsewhere in the same tick [known]:

- `NVillage::Military::Update` with its building (village update, building list order): cooldown, demolition
  countdown, every 20 ticks per building (phase `(tick + id) mod 20`) promotion and replacement (§3.3). It is
  called from `Building::Update` S 0055e2f0 only once construction is finished, and `NVillage::System::Update`
  S 0055a640 skips a building marked as outside its territory; right after each building's update the same
  loop removes it when its `destroyCountdown` is 0 or it is so marked.
- Order matching (`OrderSystem` update) after all buildings, at the end of the village update S 0055a640.
- Barracks production cycle in the settler update, not the village update: it is driven by the barracks
  worker (`Worker::TryStartProduction` S 0065d480 → `Production::CanStartProduction`; the production movie
  `NMovie::ProduceGood` S 00777460 / S 00777430 → start and finish of the cycle, §3.4).
- `NSettlers::Soldier::Update` in the settler update: state machine, strikes, random numbers (§3.5.1, §3.7).
- The worker of a catapult in the settler update (§3.10).

The whole tick, and with it everything above, is skipped while batch editing is on (`logic-core.md`).
The game-wide flag `GameSystem+0xec` is the **cinematic** flag: set when a cinematic is shown (S 00782b60),
cleared when it ends (S 00782bb0) [known]. While it is set no damage is dealt, nothing heals, the end and
demolition countdowns stand still and the catapult uses no ammunition (§3.3, §3.6.1, §3.7, §3.8, §3.10).

Since the village and the settlers run before the military system, a soldier's request for reassignment made in
tick `n` is processed by the fight in tick `n`, and the soldiers see the new groups in tick `n + 1` [inferred
from the order in `logic-core.md`].

Per frame only: flags, stripes, soldier figures, projectile arcs and catapult arm (`S2CG::*`), info boxes
(`nMenu::*`). They read the state above and write none of it [inferred from the namespaces].

## 5. Inputs and outputs

**Commands** (`game-commands.md`): 0x2000D attack (target id, fraction), 0x2000E retreat, 0x20011 defence
fraction, 0x20013..15 garrison fractions near / medium / far, 0x20016 reset, 0x20017 toggle an ignore flag,
0x20012 toggle soldier kind, 0x20003 destroy (delayed under attack), 0x2000A production on/off (pauses a
catapult; a barracks with a training part on is not paused, only emptied of requests and inputs, §3.4),
0x20018 / 0x20019 toggle a training slot / the promotion (on any building, §3.4) [known].

**Script functions** (`../lua-surface.md`): `logic.pl_isUnderAttack`, `pl_getPositionUnderAttack`,
`pl_isAttacking` (backed by `FightList::IsPlayerUnderAttack` S 00573930, `GetPositionUnderAttack` S 005739a0,
`IsPlayerAttackingPlayer` S 005738c0), `pl_getMilitaryStrength`, `vi_countMilitaryBuildings`,
`vi_isMilitaryBuildingAtContinent`, and the computer-player switches `ai_allowAttack`, `ai_setAttackEnable`,
`ai_forbidAttackingPlayer`, … [known names; bodies not read here].

**Callbacks raised** (`NLogic::CallbackManager`, `logic-core.md`) [known]: fight added / removed (slots
+0x34 / +0x38, S 00531ea0, S 00531f20; "added" from the fight constructor and again in the post-load pass);
soldier entered / left a fight (slots +0x28 / +0x2c, S 005308a0, S 00530920); strike or projectile hit on a
settler with a position (slot +0x30, S 00531e20: for a melee strike the striker's figure position, for a
projectile the fine-grid cell of its source); projectile source set (slot +0x98, S 00531420: when the
shooting soldier or the catapult is bound, and again in the post-load pass, each only if `flightTicks != 0`);
projectile destroyed (slot +0x9c, S 005314a0).

**Player messages** (type 1, with building name and position) [known]: `!You are under attack!`,
`!attack failed`, `!attack averted`, `!Castle was destroyed!`, `!Military Building Destruction executed`,
`!Attack Target has been destructed`, `!Building is not connected`, the catapult messages
(`!Building hit by Catapult`, `!Building destroyed by Catapult`, `!Enemy Building destroyed by Catapult`), and
from the ownership transfer `!Lost Military Building to enemy.` / `!Military Building conquered.` (both with
the leading `!` and the full stop). The castle message is the exception to "building name": it goes to all
players except the owner and carries the owner's name (`Player+0x18`, the `std::string` name of
`players-victory.md` §2.2) in place of the building name (S 00571af0) [known].

**Asks of other subsystems**: map (hex distance, landmass ids, territory owner grid, exploration grid, A* path
and path length, flood fill), village (territory-building and catapult lists, orders, stocks, hit points,
remove / transfer building), settlers (create soldier, movement, movies), navy (harbour and route queries,
linking soldiers and fights to ships), players (`IsEnemyOf`, tribe, locks, settings, statistics, messages),
sacrifices (§3.9), computer players (attack watch, fight history).

**Offers**: attack availability and attacker counts (`Attack::GetAttackAvailability` S 005759f0,
`Military_CountAttackersByKind` S 00575fd0, `Military_CountDefendersByKind` S 005760a0,
`Military_GetMinAttackerFraction` S 00575f00) to the menu and the computer player; zones and flag soldier count
(present soldiers, or stocked soldiers for a headquarters, capped at 10, S 0055fd40) to the renderer; the
`ISoldierConnector` interface so that the computer player can count instead of send
(`../navy-and-military.md` §3.4).

**Rules about soldiers and military buildings owned by other specifications** (pointers only):

- `players-victory.md`: the kill counter raised in `TakeDamage`, the coin counter raised per produced coin, and
  the military strength value (weight per soldier by level).
- `village-buildings.md`: `mi_setRegenerationRate` is also the hit-point regeneration period of buildings;
  which building takes a returning soldier (`SettlerSpawn::CanAcceptSettler`) and how it becomes a stocked
  good again with its life points remembered (`OnSettlerEntered`); hit points and catapult damage messages.
- `settlers-jobs.md`: walking speed (`cfg_setSettlerSpeed` times the soldier-speed factor of §3.9), movies,
  the homeless settler.
- `navy.md`: boarding of mission soldiers at a harbour (all eligible soldiers in one tick, no capacity limit);
  a coast counts as a player's only with one of its military buildings on that continent.
- `ai-player.md`: the attack fraction, target choice, attack budget and the attack watch of a computer player.
- `properties-data.md`: the start building of every player is the first type that is `depot`, `casern` and
  `territoryBuilding` (the castle).

## 6. Data-driven parameters

All in `data/game/scripts/properties/` (encrypted; `../data-loading.md`).

**`military.lua`** [known]: `mi_setRegenerationRate(100)`, `mi_setWaitForTacticTime(10)`,
`mi_setActionsInFightDelayTime(300)`, `mi_setHealthExchangeDistance(200)`, and `mi_setSoldierId(tribe, kind,
level, good)`: Bavarians sword 0..2 and bow 0..2, Egyptians sword 0 only and bow 0..2, Scots sword 0..2 and bow
0..1. The file also defines `tactic_aggressive/normal/defensive` = 0/1/2, used by no `mi_` call in it.

**`Jobs.lua`** [known], soldier goods. Examples (hitDamage / health / armor / attackWaitTime / blockingChance /
attackTime / hitTimes / bowRange):

| Good | Values |
|---|---|
| Bavarian halberd 0 | 10 / 100 / 5 / 19 / 2 / 11 / {4} / – |
| Bavarian halberd 2 | 21 / 250 / 6 / 17 / 5 / 11 / {4} / – |
| Scottish claymore 2 | 24 / 300 / 8 / 15 / 6 / 11 / {5} / – |
| Egyptian sword 0 | 9 / 50 / 4 / 12 / 1 / 18 / {4, 15} / – |
| Bavarian crossbow 0 | 10 / 50 / 0 / 3 / 0 / 27 / {6} / 6 |
| Egyptian bow 2 | 26 / 250 / 2 / 6 / 0 / 22 / {7} / 7 |
| Scottish sling 0 | 10 / 50 / 0 / 12 / 0 / 18 / {12} / 5 |

Costs: level 0 e.g. `halberd + weissbeer`, `claymore + kilt + whisky`, `stoneScots × 3 + kilt + whisky`; level
n = the level n-1 soldier + 1 coin (`coinBav`, `coinScots`, `coin`). `gp_setProjectileType`: bolt 2, arrow 0,
sling stone 3.

**`buildings.lua`** [known]: `bp_setTerritoryBuilding`, `bp_setTerritoryRange` (guard house 9, tower 10,
fortress 11, castle 9), `bp_setSoldierLimit` (guard house / tower / fortress: Scots 2 / 4 / 6, Bavarians
3 / 6 / 9, Egyptians 4 / 8 / 12; none for the castle), `bp_setHealth` (Scots and Bavarians 60 / 80 / 100,
Egyptians 80 / 100 / 120, castle 200, catapult 40), `bp_setUpgrade` (guard house → tower → fortress),
`bp_setSize(… + SizeMilitary)` (`SizeMilitary = 64`, defined in `config.lua`), `bp_setCasern` (the castle and
the three barracks; only the barracks have `bp_setProductionTime` 333 and `bp_setRestTime` 55),
`bp_setCatapult`, `bp_setCatapultDamage(10)`, `bp_setWorkingRadius(12)`, `bp_setProductionTime(catapult, 25)`,
`bp_setGoods(catapult, catapultStone…, 1)`, `bp_setAiThreat`.

**`config.lua`** [known]: `cfg_setBowFlightTimeFactor(2)` (GameConfig+0x38), `cfg_setCatapultFlightTimeFactor(5)`
(+0x28), `cfg_setCatapultRotationTimeFactor(5)` (+0x24), `cfg_setSettlerSpeed(0.058)`,
`cfg_setSettlerDyingTime(28)`. Defaults in code when a key is missing (`GameConfig` ctor S 00555780): bow
flight factor 1.0, both catapult factors 10.0, settler speed 0.1, dying time 50.0 [known].

**`tribes.lua`** [known]: `tp_setSoldierUpgradeGoodId(tribe, coin)`, `tp_addJob` (which soldier goods a tribe
has), start and bonus soldiers (`tp_addStartResources(bavarians, good_soldierHalberd0, 5)`).

**`sacrifices.lua`** [known]: the effects of §3.9 with value, duration (`sf_setDuration`, e.g. 6000) and
regeneration delay.

**Constants in code** [known]: zone limits 19 and 24; distance pass every 11 ticks, allocation every 21,
building upkeep every 20, "not connected" every 600 counts; soldier release cooldown 10; reach falloff 12 / 24
cells; path cache lifetime 111 ticks; superiority 0.2 per extra soldier; strike value rounding 0.99; group cap
6; moving-target penalty 50;
score weights 100 / 50 / 100; wounded limit half health; random pause 0..9; target-lost end delay
`actionsInFightDelayTime / 10`; default garrison fractions 0.1 / 0.3 / 1.0, defence 0.5; flag soldier cap 10.

## 7. Save and load

Stream primitives and section tags: `logic-core.md`. Every `Store` starts with a section tag carrying a
version; versions are checked on load as noted. The version written is the one given to the section's
log-category object in its static initialiser (e.g. `Village Military` 9 S 007c1870, `Settlers Fight` 3
S 007c9300) [known]; the full list is `save-format.md` Appendix A. For the sections below: `MilitarySystem` 0,
`Military Distances` 0, `Military Allocation` 0, `Military Attack` 1, `Military Projectiles` 0,
`Military Projectile` 1, `Military Fights` 0, `Military Fight` 8, `Military FightSoldierList` 2,
`Military FightGroups` 0, `Military FightGroup` 1, `Village Military` 9, `VillageCasern` 1,
`Village Catapult` 1, `SettlersSoldier` 1, `Settlers Fight` 3, `Player Military` 2 [known, each read in its
initialiser S 007c1870..S 007c2e90, S 007c6fb0, S 007c91c0, S 007c9300]. Nested tags of this subsystem, all
version 0: `Military Projectile Target`, `Military Projectile Owner`, `Military GatheringPositionState`,
`Military GatheringPositions`, `Soldier Exchange` (one order slot), `VillageSoldiers`, `Soldiers Container`
[known].

**`NMilitary::System`** (section `MilitarySystem`) [known] S 0056ffe0, S 00570050. Load first clears the
projectile, group and fight lists.

1. bool `+4` (the "initialised" byte of §2.7)
2. `Distances`: int countdown
3. `Allocation`: int countdown
4. `Attack` (`NMilitary::Attack::Store` S 00575740, `Load` S 00576600; version ≥ 1, else the cache is cleared
   and stamped with the current tick): uint stamp of the persistent path cache (global S 0088a4d0); uint entry
   count (map object at S 0088a4dc: head S 0088a4e0, size S 0088a4e4); per entry in ascending key order: uint
   key, int path length. Load empties the map before reading. The second cache is not saved; the post-load
   pass `NMilitary::Attack::PostLoad` S 00575800 (vtable slot 3, no direct caller) empties it (map head
   S 0088a4ec, size S 0088a4f0) and stamps it (S 0088a4d4) with the tick counter at load time, i.e. the saved
   tick, not 0 [known].
5. Projectile list: bool, uint count, then each projectile: unique id, int type, uint flightTicks, uint
   elapsedTicks, target owner, source owner, int damage. An owner (tag `Military Projectile Owner`; the
   target one preceded by the tag `Military Projectile Target`): int kind, building reference, settler
   reference, cell, int.
6. Fight list: bool, uint count, each fight (below).
7. Fight group list: bool, uint count, each group: unique id, fight reference, cell, target soldier reference,
   member references, int side, int kind.

**Fight** (section `Military Fight`, version ≥ 8 for the full layout) [known] S 00570d20, S 00570e30: unique id;
int attackerPlayer; bool assignDirty; uint startCountdown; target reference; targetCell (v ≥ 8); for side 0, 1:
{ group references (v ≥ 2), soldier list, bool contact[side] (v ≥ 7) }; gathering mode (int) and the three
gathering cells (v ≥ 3); int endCountdown and bool ending (v ≥ 4); int defenderPlayer (v ≥ 5, else taken from
the target's owner when the target reference is valid); ship references (v ≥ 6). A version 1 fight has one
group reference list before the two sides, read into side 0. Soldier list (section `Military
FightSoldierList`, S 005767d0, S 00576810): soldier references, (v < 2 only: one int, read and discarded,)
int gatheringSlot, `everAddedByKind[2]` (v ≥ 1). `countByKind` is **not** stored; it is recounted
from the resolved soldier list in the post-load pass (`MilitaryFightSoldierList_RecountByKind` S 00576aa0, only
caller `Fight::ResolveReferences` S 00570920) [known].

**`NVillage::Military`** (section `Village Military`, current layout needs version ≥ 9) [known] S 005603f0,
S 005604d0: garrison references; attacker references; int enemyDistanceA; int cooldownTicks; defender
references; int soldierKind; fight reference; int destroyCountdown; int enemyDistanceB (v ≥ 4); f32
defenceFraction (v ≥ 5); uint 3 and the three order slots (v ≥ 7), each: soldier references, order container,
f32 load weight; int unconnectedTicks (v ≥ 9). Older layouts in Load: v < 8 has one more int before
soldierKind (read and discarded); v < 6 has, after destroyCountdown, the soldier references and the order
container of slot 0 and one more value; v = 6 has no count and exactly one slot (slot 0) at the end [known].

**Barracks** (section `VillageCasern`) [known] S 00566a90: two training slots (bool enabled, int goodId, bool
running), the upgrade (bool enabled, int soldierType, bool active), the two stocks, bool running, int
currentSlotIndex (v ≥ 1).

**Catapult** (section `Village Catapult`) [known] S 00567770: target cell, aim cell, f32 `+0x1c`, f32 last fire
stamp, int direction, int pending direction, projectile reference, int targetSeed (v ≥ 1).

**Soldier** (section `SettlersSoldier`; `Soldier::Store` S 00658960 writes in this member order) [known]: movies GoToWorkingPlace, home reference,
LeaveBuilding, MoveToAttackBuilding, Fight, ReturnToMilitaryBuilding, MoveToPosition; life points; bow;
projectile references; fight state; order building, paired soldier, order reference (v ≥ 1); then the base
settler. Fight state (section `Settlers Fight`) [known] S 0065b8b0: fight reference, and **only if it is valid**:
int `+4`, attacker references, defended building, bool retarget, opponent, attacked building, cellA, cellB,
cellC, bool leftFight (v ≥ 3; older versions stored an int: v < 2 true when it is 4, v = 2 true when it is
not 0), targetedBy references, group reference, bool strikeHits, bool inFight (v ≥ 1; in version 0 it is
derived: true if the attacked building, the defended building, the group or the opponent reference is valid
or `targetedBy` is not empty) [known] S 0065bcc0.

**Player settings** (section `Player Military`): `players-victory.md` §7.

All references are stored as logic ids and resolved in the post-load pass (`ResolveReferences` S 005700e0,
`Military::PostLoad` S 00560630, `Soldier::PostLoad` S 00658ba0); a soldier with `inFight` re-raises "entered
fight", a fight re-raises "fight added" and a projectile with `flightTicks != 0` re-raises its slot +0x98
callback [known]. The checksum variant (`StoreUntagged`) writes the fields without tags, with these
differences [known]: in place of the own unique id of a fight, a projectile and a fight group it writes the
global next-unique-id counter (`LogicId_StoreGlobal` S 00538760; S 00570fb0, S 00572f40, S 00573320); a fight
omits the two `contact` bytes; a side's soldier list writes only the references and gatheringSlot, not
`everAddedByKind` (S 00576870); the soldier fight state writes int `+4` first, before the fight reference and
whatever its validity, and `leftFight` as an int (S 0065ba40). It is what the lockstep checksum hashes of the
military system (`NMilitary::System::StoreUntagged` S 00570120; `save-format.md` §3.9); the player settings
of §2.3 are hashed with the player (`players-victory.md`).

## 8. Determinism notes

- **Random numbers**: only `LogicRandom_Next` (`logic-core.md`), exactly two draws per strike: one at strike
  start (hit roll, `% 100`) and one when the strike ends (pause, `% 10`). Target choice, grouping, the catapult
  and soldier selection use none [known]. The computer player draws from the same generator around fights
  (attack watch §3.5, attack planning; `ai-player.md`). The generator is Park-Miller (16807, 2^31 - 1) and
  returns 1..2^31 - 1
  (S 006ec350). **Walking draws too**: every off-road path of a settler (`NMovement::FreePath::FindPath`
  S 00775170) is built with the random variant (`AStar::BuildPathReversed(…, 1)` → `BuildPath` S 00676d10: no
  draw when start and goal are neighbours; else one draw `% 6` for the start direction, then at each step
  where the current direction is not a descent direction one draw `% count of descent directions`) [known];
  soldiers walking to a fight, to a cell or home off-road take such paths, so their walks sit between the
  strike draws in the generator's sequence [inferred; `settlers-jobs.md`]. The gathering path uses the non-random variant of `AStar::BuildPath` (S 00576fb0), and
  `AStar::FindPath` S 00676900 and `GetPathStepCount` S 00676a90 (path-length cache) do not call the generator
  themselves [known]. Neither does `AStar::Step` S 00676700 (pop the best node, relax the six neighbours in
  direction order 0..5 with the virtual step cost) nor the base step cost `AStar::GetStepCost` S 00676840
  [known]; both military uses search with the map's own instance `NMap::System.pAStar`, which is of the base
  class: `NMap::System::ctor` S 00672180 builds it with `NMap::AStar::ctor` S 00676cd0 (vtable S 007f89c8,
  slot +4 = `GetStepCost` S 00676840) [known].
- **Iteration order** decides ties everywhere: the territory-building list (dispatch, allocation, distances),
  the garrison list (soldier selection, weakest soldier, exchanges), the fight side lists (assignment), group
  member lists, the fight and projectile lists (all vectors in insertion order, erased with order kept). All
  "best" searches use strict comparisons, so the first candidate wins a tie [known].
- **The path-length cache** changes results only through timing: it is flushed when older than 111 ticks, and
  the persistent one is saved, so a loaded game continues with the same cached lengths. A reimplementation that
  recomputes paths every time is equivalent only if the path length between two cells cannot change within 111
  ticks; it can (roads, buildings, terrain), so the cache and its flush tick must be reproduced for lockstep
  compatibility [inferred].
- **Floating point**: all conversions truncate (`ftol`), several add 0.5 first, the strike value adds 0.99.
  Single precision: garrison
  size, send counts (`avail * fraction + 0.5` = `(int)(float)((float)(n·f) + 0.5f)` at S 00576060, S 005763a2,
  S 005764b1: an implementation in double sends one soldier more or less at some fractions [known]), strike multiplier, sacrifice factors, falloff. Fractions arrive
  as raw f32 bits in commands. The two flight-tick conversions truncate as well: they force the rounding bits
  of the x87 control word to truncation around a `FISTP` (S 0065f2ba..0065f2da, S 005679a8..005679c2) [known].
- **Integer division** in the score (`lifePoints * 100 / maxHealth`), the gathering distances and the wounded
  limit [known].
- The fight keeps `countByKind` incrementally while it is not stored; after a load it is recounted
  (S 00570920 → S 00576aa0) [known]. The recount first resolves every reference of the side list from its
  saved id (the reference container's post-load call, vtable S 007e7db0 slot +0xc = S 0059fe70) and then counts
  every entry; nothing is purged, so both counts agree as long as adds and removes were balanced [inferred].
- The game-wide flag `GameSystem+0xec` changes combat (no damage, no healing, free catapult ammunition, frozen
  countdowns); it must be identical on all machines [inferred]. It is the cinematic flag (§4), set from the
  menu side and neither saved nor hashed (`logic-core.md`).

## 9. Notes for a reimplementation

- The split into `Fight`, `FightSoldierList`, `FightGroup` and `SoldierFightState` with two-way references can
  be replaced by plain ownership, as long as the **orders** of §8 and the rules of §3.6.2 are kept.
- Must be exact for lockstep with original clients or for loading original saves: every formula with
  truncation, the tick phases (11 / 21 / 20 with their countdown or id phase), the one-soldier-per-10-ticks
  release, the two random draws per strike and their order relative to other users of the generator, the
  list orders, the path cache, and the save layouts of §7.
- For a stand-alone remake these can be simplified without changing what the player sees much: the path cache,
  the fine-grid standing slots (any free neighbour of the opponent), the gathering-cell flood fills.
- Worth keeping because they define the feel: sword soldiers are fought before bow soldiers; archers hold fire
  until the first melee contact (or when a side has no sword soldier); numbers give only +20 % per extra
  soldier; a strike misses half of the time against a moving opponent; the healthiest, highest soldiers are sent
  first; the majority kind captures; a castle is destroyed, not captured; no reinforcements after the start.
- Quirks to decide on deliberately: the strike value is rounded up (`+ 0.99`), so group fighters never lose the
  fraction of their share; `blockingChance` works as the striker's miss chance; an occupied building
  far from the enemy can want 0 soldiers; the catapult lists enemy catapults twice; the Egyptian sword soldier
  hits twice per strike; the castle sends every stocked soldier whatever the slider says; the defence fraction
  is frozen in the target when the attack starts.
- More quirks from the code: an emptied far building keeps its territory and is attackable (§3.2); a kind
  switch with no stocked soldier of the new kind still sends the old soldiers away (§3.3); a captured building
  gets no garrison orders and no exchanges until the fight object is gone (§3.8); the defence fraction a
  computer player computes for its attacked building is overwritten at once (§3.5); a cell search that finds
  nothing returns the last cell it tested (§3.6.1).
- Simulation-state quirks of the barracks side: a supplier always sends the highest level of the kind it
  holds, whatever level the order names (§3.2, §3.3); production off (0x2000A) never pauses a barracks whose
  training is on, it only empties its requests and inputs (§3.4); a promotion can turn weapon and drink lying
  in the output stock into a level-0 soldier and leave the coin there (§3.4); the training toggles work on any
  building (§3.4). A compatible remake reproduces all four.
- The paired-soldier test of §3.3 (`IsPairedSettlerTypeEqualSoldierType`) is always false with the shipped data.
  It decides simulation state (which wounded soldiers are replaced, which exchange orders are dissolved): a
  remake that must stay in step with original clients keeps the comparison as it is, settler type against
  soldier kind; comparing soldier kind with soldier kind changes the outcome.
- The command `0x20017` (toggle an ignore-distance flag, §5) has no sender in the original client
  (`game-commands.md` §3.4); it changes simulation state only when a peer's command stream contains it.
- `Military_GetAttackOriginCell` dereferences the first attacker without a check, and with no building found
  but a harbour found whose distance to the target is not smaller than the first soldier's, it reads the cell
  of a null building [known, decompiled C of S 00576d00]: guard both. The same holds for the water-body
  harbour of `MilitaryGatheringPositions_Compute` S 00576fb0 when no path to the origin exists (§3.6.1).

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered for the garrison (§3.2): an occupied building whose wanted size is 0 is emptied and goes on existing; with the default sliders the guard hut keeps no soldier, the guard tower and the fortress one [live, 2026-10-12]. Open: whether the emptied building's border stays, and the capacities that separate 0 from 1 | observation in the game: a far guard house (capacity 2..4) with default sliders; watch the border; read the capacities |
| 2 | Answered (§3.3): `Soldier::IsPairedSettlerTypeEqualSoldierType` (settler type compared with soldier kind) is always false with the shipped data, so `ReplaceSoldiers` S 00560110 never skips a wounded soldier because of it and `ExchangeWrongKindSoldiers` S 00560190 never reaches its unlink call [inferred]; 31,676 calls in play all returned 0 [live, 2026-10-12] | static: S 00658df0, S 006587e0, S 00656500; `Jobs.lua` |
| 3 | Answered (§2.2, §2.6, §2.7): none of the four is read by the simulation. `MilitaryConfig+0x108` is written only by the ctor (20); `+0x10c` only by S 00553f00 (1, from `Properties_RegisterLuaLibrary`) and S 00553f10 (0, from `Properties_Db_ClearAll`); a whole-binary scan of `[reg+0x108/+0x10c]` after a load of `PropertiesDb+0x5c` finds no access, while it finds every known reader of +0x110..+0x11c. `SoldierFightState+4` is -1 from the ctor, written by `Load`, read only by `Store` / `StoreUntagged` (no access through `Soldier+0x234` or `Soldier+0x230`). `Catapult+0x1c` is read only by `Serialize` S 00567770 (all `NVillage::Catapult` and movie methods scanned, plus every `[reg+0x1c]` after a load of `Building+0xf4`) [known] | — |
| 4 | Answered (§3.2): index -1 in `Soldiers::GetSoldierObject` ends the process (exit code 0xC000000D), and play can reach it: all present soldiers bound to an attack during its 10-tick start countdown, wanted size below the garrison, an allocation pass in that window. Not observed in the running game | static: S 00574a00, S 00566220, S 00658f90, S 005751e0, S 006594a0 (state 0xc), S 006f26de; observation: lower the garrison slider, then at once attack with all soldiers of that building |
| 5 | Answered (§3.8, §5): `Player+0x18` is the owner's name, passed as the argument of `!Castle was destroyed!` with the castle's cell as position (S 00571af0) [known] | — |
| 6 | Answered (§3.5, after Start): `GetAvailableAttackers` S 00575dc0, the reach factor S 00575320, the falloff S 00574fe0, `Military_IsTargetReachable` S 00575cb0, the path cache S 00575b70, `Military_ShouldAttackBySea` S 00576250 and the harbour lookups S 00574f70 / S 005b65d0 / S 005b5f50 re-read; they agree with `../navy-and-military.md` §3, with two precisions: the H2 limit is 25 cells in the reach factor and 24 in the reachability test, and a cache is emptied when the tick exceeds its stamp + 111 | — |
| 7 | Answered: specified in `ai-player.md` (`MilitaryBuildingRanking` §3.8 step 5, the fight history in the attack fraction §3.12, attack watches §3.13). The military side only creates and deletes the watch: `Fight::SetTargetBuilding` S 00570760 is the only caller of the add S 0053be90, `Fight::dtor` S 00571790 the only caller of the remove S 0053bed0, and the watch's defence fraction is overwritten by `StartAttack` (§3.5 step 2) [known] | — |
| 8 | Answered (§3.5.1 state 0xf, §3.6.2 rule 2): yes. A waiting soldier unbinds in the first tick in which the opposing list has no soldier with `leftFight == 0` and the defender list has had a member; the building is captured by an attacker already in the fight (0x29 → 0xd). With no attacker outside nobody captures [inferred]. In play the attack dialog does not let the player send more soldiers than can fight at once, so the case does not arise from the dialog [live, maintainer, 2026-10-12] | static: S 006594a0 case 0xf, S 005711c0, S 00571140, S 00570980 |
| 9 | Open: how `OrderSystem::FindOrderForSoldier` S 00561cb0 chooses the order a homeless soldier takes at a flag on its way home (§3.5.1): which categories, which order of iteration, and whether the soldier's good or level must match. Known so far: it runs the order iterator from `NextPlayer` (clearing the served bytes) and ends with `Reset` (`village-buildings.md` §8) [TODO] | static: S 00561cb0 and the iterator functions S 00569170..S 00569840 |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 0056ffb0 | `NMilitary::System::Update` | per-tick order of the subsystem |
| S 00574e40 | `NMilitary::Distances::UpdateBuildingEnemyDistances` | enemy distances every 11 ticks |
| S 005337e0 | `GameQueryHelper::MinDistanceToEnemyMilitaryBuilding` | the distance measure |
| S 00553f20 | `ClassifyIndex_0_1_2` | distance → zone |
| S 00574980 | `Military_GetDesiredGarrisonSize` | wanted garrison |
| S 00574a00 | `NMilitary::Allocation::Update` | ordering and dismissing soldiers |
| S 00566220 / 0055fc40 | `Soldiers::FindWeakestSoldier` / `Military::ReleaseSoldier` | who is dismissed |
| S 00569290 / 00568910 | `VillageOrderBucket_SelectLeastLoadedSoldierOrder` / `MilitaryOrderSlot` load | promotion order choice |
| S 0055c1a0 | `NVillage::Building::GetHpScaledSoldierCapacity` | capacity |
| S 005609b0 | `NVillage::Military::Update` | per-building upkeep |
| S 00560190 / 00560250 / 00560110 | `ExchangeWrongKindSoldiers` / `UpgradeLowestSoldier` / `ReplaceSoldiers` | the three exchanges |
| S 005600d0 / 00560390 | `ToggleSoldierKind` / `CanToggleSoldierKind` | kind switch |
| S 00568970 / 0053d2f0 | `MilitaryOrderSlot::CreateSoldierOrder` / `OrderLink_LinkMilitarySlotSoldier` | exchange order |
| S 00561e20 / 00561dd0 | `VillageOrder_LinkSettlerToDestination` / `VillageOrder_LinkSoldierToMilitarySlot` | exchange match |
| S 00659300 / 00659140 / 006588d0 | `Soldier::OnEnterBuilding` / `OnUnlinkedFromHome` / `UnlinkOrderAndPairing` | exchange hand-over |
| S 0055fd90 | `NVillage::Military::GetAttackTargetState` | why a building cannot be attacked |
| S 005668e0 / 00566920 / 00566990 | `VillageSoldierTraining_CanStart` / `StartNext` / `Finish` | barracks cycle |
| S 00569cb0 / 00569d50 / 00569d10 | `VillageSoldierTrainingSlot_CanStart` / `Start` / `Finish` | one training slot |
| S 00569b60 / 00569940 / 005698a0 | `VillageSoldierUpgrade_CanStart` / `HasUpgradableSoldier` / `FindUpgradableSoldier` | promotion readiness |
| S 00569970 | `VillageSoldierUpgrade_Finish` | promotion with a coin |
| S 005759f0 | `NMilitary::Attack::GetAttackAvailability` | attack button code |
| S 00575dc0 | `NMilitary::Attack::GetAvailableAttackers` | soldiers one building can send |
| S 00576500 | `NMilitary::Attack::StartAttack` | start of an attack |
| S 00782cb0 / 00782bf0 / 00781150 | `HandleStartAttack` / `HandleCancelAttack` / `HandleDestroyBuilding` | command executors |
| S 00575f00 | `Military_GetMinAttackerFraction` | lowest attack fraction |
| S 00576320 / 00576400 | `DispatchAttackers` / `DispatchDefenders` | who is sent |
| S 005751e0 | `AttackConnector::AssignBestSoldiers` | which soldiers of a building |
| S 005715a0 | `NMilitary::Fight::Update` | fight tick |
| S 005708a0 / 00571090 | `Fight::GetPhase` / `IsActive` | phase, life time |
| S 00576fb0 / 00576d00 | `MilitaryGatheringPositions_Compute` / `Military_GetAttackOriginCell` | gathering cells |
| S 00577ec0 | `ai::military::FightAssigner::Update` | pairing |
| S 00578aa0 | `FightGroupSizePlan::Init` | group sizes |
| S 00577c90 / 005777b0 / 00577670 | `TrimAllGroups` / `TrimOversizedGroups` / `RemoveExcessMembers` | trim pass |
| S 00578900 / 005789e0 / 005772a0 | plan: remove conforming / undersized groups; `IsTargetAvailable` | trim pass |
| S 00577a10 / 005774d0 | `RetargetToAttackers` / `FightAssigner::FindJoinableGroup` | retarget, join |
| S 00571c60 / 00571d60 / 00571e50 / 00571f20 | `Fight::FindGroupOfSoldier` / `FindGroupByMemberAndAnchor` / `FindGroupContainingSoldier` / `_B` | group lookups |
| S 00572210 / 00572610 / 00572410 | `FloodFillSearch::Run_MilitaryFightCell` / `GroupCell` / `Ring` | cell searches |
| S 00572810 / 00572ab0 | `Fight::FindFreeGatheringCell` / `FindFreeGatheringCellForGroup` | cell searches |
| S 005787a0 / 00578550 / 005787f0 | `FightCellSearch` expand / `IsFreeCell` / `IsFreeCellForGroup` | cell predicates |
| S 00578650 / 00578600 / 005786a0 | `FightRingSearch` ctor / `CanExpand` / `Evaluate` | archer's ring |
| S 005711e0 / 00571300 | `Fight::IsCellFree` / `IsCellFreeForGroup` | occupancy |
| S 00578400 | `FightSlotSearch::PickNearestFreeNeighbour` | fine slot |
| S 00577340 / 00577420 | `MilitaryFightAssign_PickBestTargetInGroup` / `PickBestTarget` | target score |
| S 006594a0 | `NSettlers::Soldier::Update` | soldier state machine |
| S 005728e0 / 00572130 | `Fight::ComputeSoldierFightCell` / `PickSoldierFightSlot` | where a soldier stands |
| S 00572060 | `Fight::IsMeleeGroupNotOutnumbered` | who closes in |
| S 007798d0 / 00779a70 / 00779980 | `NMovie::Fight::Start` / `Update` / `TryApplyStrike` | hit roll, timing, hit |
| S 00658ea0 / 00658ed0 | soldier vtable slots +0x30 / +0x34 | stretched hit times |
| S 005721a0 / 005735b0 | `Fight::ComputeSoldierStrikeValue` / `FightGroup::GetStrikeMultiplier` | damage |
| S 00659260 | `NSettlers::Soldier::TakeDamage` | armor, death, kill credit |
| S 0065f270 | `ai::settlers::Bow::Shoot` | arrow launch |
| S 00572fa0 | `ai::military::MilitaryProjectile::Update` | flight and impact |
| S 00571440 / 005707d0 / 00576900 | `CanSoldierEnterTargetBuilding` / `CanSoldierOccupyTarget` / `HasFreeSlotForSoldier` | who captures |
| S 00571af0 | `Military_SoldierCaptureTargetBuilding` | capture or castle destruction |
| S 00574c50 | `Military_TryAssignSoldierToBuilding` | capturer becomes garrison |
| S 0055a210 / 0053cf50 / 005606b0 / 00570760 | `TransferBuildingOwnership` / link fight to building / `Military::AttachFight` / `Fight::SetTargetBuilding` | re-binding on capture |
| S 0065be90 / 0065bfe0 | `SoldierFightState::LeaveFight` / `ReleaseAll` | leaving, dying |
| S 005719b0 | `Fight::RemoveSoldier` | "attack failed" |
| S 00570900 / 00571720 | `Military_RequestCancel` / `Fight::ReleaseTargetBuilding` | retreat, target lost |
| S 0065d410 / 00567d20 / 005678b0 | `Worker::TryStartCatapultAttack` / `Catapult::SelectTarget` / `Catapult::Fire` | catapult |
| S 00567c60 / 00567be0 / 00567ac0 | `CatapultTargetSearch` steps | candidate lists and the choice |
| S 0055fff0 / 0055fea0 / 00567a30 | `Military::IsValidCatapultTarget` / `IsActiveMilitaryBuilding` / `Catapult::HasAmmo` | target filter, ammunition = `costs[0]` of the slot good |
| S 0077b940 / 0077b880 / 0077b7e0 | `NMovie::CatapultAttack::Start` / `Update` / `Store` | attack movie; the store writes only the step |
| S 0077e980 / 0077e950 | `NMovie::RotateCatapult::Start` / `Update` | rotation, `(turns + 1) × 5` ticks |
| S 0077eb30 / 0077eb00 | `NMovie::ShootCatapult::Start` / `Update` | shot; `Fire` at the start |
| S 005676d0 / 0053ce30 / 0053cdd0 / 005704c0 | `Catapult::dtor` / `MilitaryLink_UnlinkProjectileFromTargetBuilding` / `MilitaryLink_UnlinkProjectileFromCatapult` / `ProjectileOwner::ClearBuilding` | projectiles of a removed building become position projectiles |
| S 0055e080 | `NVillage::Building::OnCatapultHit` | catapult damage |
| S 00660500 / 00660270 | `Sacrifice::ApplyEffect` / `ApplyHealOwnUnits` | function effects |
| S 00782b60 / 00782bb0 | cinematic start / `nGame::System::EndCinematic` | flag `GameSystem+0xec` |
| S 00676700 / 00676840 | `NMap::AStar::Step` / `GetStepCost` | path search, no random draw |
| S 006630b0, S 006633f0..00663610 | `SacrificeModifiers::ApplyOwnEffect`, slot readers | sacrifice factors |
| S 00575740 / 00576600 / 00575800 | `NMilitary::Attack::Store` / `Load` / `PostLoad` | path-length cache in the save; `PostLoad` empties the transient cache and stamps it with the load tick |
| S 00570120 / 00570fb0 / 0065ba40 | `StoreUntagged` of system, fight, fight state | checksum variant |
| S 00775170 / 00676d10 | `NMovement::FreePath::FindPath` / `NMap::AStar::BuildPath` | random draws of off-road walks |
| S 0056ffe0 / 00570d20 / 005603f0 / 00658960 / 0065b8b0 | `Store` of system, fight, building part, soldier, fight state | save format |
| S 00565020 / 00564c90 | `SettlerSpawn::SpawnSoldierForOrder` / `TakeSettlerValue` | the supplier sends its highest stocked level of the kind |
| S 00565580 / 005668b0 | `Production::IsEnabled` / `SoldierTraining::IsAnyEnabled` | a barracks counts as enabled while a training part is on |
| S 00566740 | `ai::village::SoldierTraining::ctor` | training slot goods fixed from the owner's tribe |
| S 00566ba0 / 0064e6d0 | `VillageSoldierTraining_UpdateInputRequests` / `NeedGoods::CancelAllRequestsOfGood` | barracks input requests |
| S 007823f0 / 00782480 | executors of 0x20018 / 0x20019 | training toggles, any building |
| S 00676a90 | `NMap::AStar::GetPathStepCount` | path length stored in the path cache |
| S 00576b10 | `GatheringPositions::GetSlotForSide` | gathering slot per side and mode |
| S 00658860 / 00658e50 | `Soldier::IsInWorkCycle` / `GetWorkBuildingFlagPos` | soldier vtable S 007f842c slots 10 / 11 |
| S 00779d10 / 00779cb0 | `NMovie::MoveToAttackBuilding::Start` / `Update` (vtable S 008347f4) | walk to the target's flag |
| S 00779820 / 007797c0 | `NMovie::ReturnToMilitaryBuilding::Start` / `Update` (vtable S 00834794) | walk home and enter |
| S 0065a340 / 007776f0 / 00561cb0 | `Soldier::TryCompleteOrderAtCurrentPos` / `NMovie::MoveToHome::Start` / `OrderSystem::FindOrderForSoldier` | order taken on the way home |
