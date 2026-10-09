# navalcombatfix

A server mod: every player of a match needs it (the host's copy, ini included, is what runs; `assetshare` takes care
of that). The rules are in `CONCEPT.md`, how the game works and what the mod changes in
`docs/navy-and-military.md` (§2-§6 the game, §7 the mod). Naval invasions work in the game (maintainer's test
2026-10-08); the rest is still being tested.

What it does:

- **Attacks across the water through your own harbours** (`combat.cpp`): soldiers from buildings across the water
  count and sail when you own both harbours of the route, from a colony, or through a neutral harbour where no colony
  fits (`landing.cpp`). The soldier count is the game's ground rule on the land distances, the crossing free.
- **Defence across the water**, the same way, with the defender's own ships.
- **Retreat** (`retreat.cpp`): soldiers left with nowhere to go (the game lets them wander until they die) are
  picked up by a ship from a neutral harbour on their landmass, as soon as the game finds no home for them. A harbour
  whose flag stands in someone's territory is not neutral.
- **Flag stripes and attackability** (`proximity.cpp`): routes between your own harbours count for the distance to
  the enemy.
- **Naval invasion** (`invasion.cpp`): an expedition to a free harbour without room for a colony says so and turns
  back. The route's buoy then offers **Prepare naval invasion** (4th button): a ship loads an expedition (soldier and
  building goods) and waits at home. Attack a building near that harbour: the ship carries the attackers, only they
  land, and when the building is taken the colony is founded. The event log says when the ship is ready and how the
  invasion ended.
- **Lost attacks by sea sink the ship** (`ShipLostOnDefeat`): when an attack by sea fails (the target still stands and
  is not taken), the attacker's ship sinks at the landing with everyone aboard. This holds for every attack by sea,
  the game's own and invasions. Not affected: ships carrying defenders, a ship whose landing harbour is still its
  player's (a coastal attack), and cancelled attacks (a cancelled invasion sails home and unloads). A ship carrying
  defenders sinks when the defence is lost together with the harbour it landed them at.

## Settings (`navalcombatfix.ini`, `[NavalCombatFix]`)

| Key | Default | |
|---|---|---|
| `AttackersBySea` | true | attackers gather through their own harbours |
| `DefendersBySea` | true | defenders cross the water |
| `AttackFromOwnLanding` | true | an own harbour within a target's range makes it attackable |
| `RetreatPickup` | true | ships pick up stranded soldiers |
| `ProximityOverOwnRoutes` | true | own routes count for the flag stripes and attackability |
| `NeutralLandings` | true | neutral harbours without room for a colony are landings |
| `CrossingDistance` | 0 | cells a sea crossing counts as |
| `PickupTimeout` | 1200 | ticks a ship waits for soldiers (pickups, invasion boarding) |
| `LandingReach` | 9 | cells a landing harbour may lie beyond a target's territory range + 1 (enemy, own and neutral landings); 0: the game's rule |
| `ShipLostOnDefeat` | true | a lost attack by sea sinks the attacker's ship, a defence lost with its harbour the defender's; false: they sail home (an invasion unloads its cargo) |

## To do

- **The invasion button's look:** it borrows the attack button's icon and shows plain English texts. It needs its
  own icon (the action icon atlas) and translated texts (the game's text database), like the game's buttons.
- **Translated messages:** the event-log messages (`!navalcombatfix_*`) are English only.
- **Ship bug fixes to move out:** deselecting a sunk ship (a crash of the unmodded game) and sending stranded ships
  home are general fixes, not combat rules; they belong in a separate ship-fixes mod (`mods/IDEAS.md`).
- Everything above still needs testing in the game; the doc's §7 lists what to check.
