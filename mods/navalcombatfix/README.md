# navalcombatfix

A server mod: every player of a match needs it (the host's copy, ini included, is what runs; `assetshare` takes care
of that). The rules are in `CONCEPT.md`, how the game works and what the mod changes in
`docs/navy-and-military.md` (§2-§6 the game, §7 the mod). Nothing of it has been tried in the game yet.

What it does:

- **Attacks across the water through your own harbours** (`combat.cpp`): soldiers from buildings across the water
  count and sail when you own both harbours of the route, from a colony, or through a neutral harbour where no colony
  fits (`landing.cpp`). The soldier count is the game's ground rule on the land distances, the crossing free.
- **Defence across the water**, the same way, with the defender's own ships.
- **Retreat** (`retreat.cpp`): soldiers the game would let die for having nowhere to go are picked up by a ship from
  a neutral harbour on their landmass.
- **Flag stripes and attackability** (`proximity.cpp`): routes between your own harbours count for the distance to
  the enemy.
- **Naval invasion** (`invasion.cpp`): an expedition to a free harbour without room for a colony says so and turns
  back. The route's buoy then offers **Prepare naval invasion** (4th button): a ship loads an expedition (soldier and
  building goods) and waits at home. Attack a building near that harbour: the ship carries the attackers, only they
  land, and when the building is taken the colony is founded.
- **Lost attacks by sea sink the ship** (`ShipLostOnDefeat`): when an attack by sea fails (the target still stands and
  is not taken), the attacker's ship sinks at the landing with everyone aboard. This holds for every attack by sea,
  the game's own and invasions; ships carrying defenders are not affected.

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
| `ShipLostOnDefeat` | true | a lost attack by sea sinks the attacker's ship; false: it sails home (an invasion unloads its cargo) |

## To do

- **The invasion button's look:** it borrows the attack button's icon and shows plain English texts. It needs its
  own icon (the action icon atlas) and translated texts (the game's text database), like the game's buttons.
- Everything above still needs testing in the game; the doc's §7 lists what to check.
