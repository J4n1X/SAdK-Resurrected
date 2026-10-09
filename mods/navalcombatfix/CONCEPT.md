# Naval combat fix

Fixes for how soldiers cross the water in fights (`combat.cpp`), on retreat (`retreat.cpp`), and for the distance to
the enemy behind the flag stripes and the attack gate (`proximity.cpp`).

## Reported bugs

Defenders and additional attackers can be send by ship if a player already owns both sides (the most important)

Soldiers stuck on the other side due to a destroyed military military buildings can be transported regardless of the harbour flag owner

Any military buildings can be attacked regardless of the harbour flag owner

### Decided rules (implemented in `combat.cpp`, not tested in the game yet)

The game's rules are in `docs/navy-and-military.md`; the change is §7 there.

- **Both sides owned (attackers and defenders).** If a harbour flag of the player lies in the gathering radius of the
  attacked building, soldiers gather from the other harbour flag of the route, with a total radius of attack radius
  minus the distance from the attacked building to the harbour flag: the game's ground falloff (full to 12 cells,
  nothing from 24) on d(target, harbour flag) + d(other harbour flag, building).
- **Invasion.** The destination harbour flag of an expedition counts like the attacker's land: a building is
  attackable when that flag lies within the building's territory range + 1 (the game's own test for enemy harbours),
  plus `LandingReach` cells (default 9) for every kind of landing.
  Soldiers are gathered by the rule above.
- Soldier counts are the game's own ground-attack counts.
- **Retreat.** If you destroy your military building and in the process lose your harbour, which becomes neutral
  territory, and the soldiers have nowhere to go (the game would let them die), a ship of yours that is ready for the
  route from that harbour to one of yours picks them up. If the harbour's flag becomes enemy territory, the soldiers
  are not allowed to use it to return.
- **Neutral landings.** An attack is also possible when an enemy is close to a neutral harbour where there is not
  enough room to found a colony; the distance to the enemy (flag stripes, attackability) is then also measured from
  that neutral harbour, when one of the player's harbours has a route to it. With room for a colony, the colony is
  the way in.

## Naval invasion (implemented in `invasion.cpp`; works in the game, maintainer's test 2026-10-08)

For a neutral harbour where a colony cannot be founded (an enemy is in the way), as decided by the maintainer:

1. **Scouting.** An expedition that arrives at a harbour without room for its colony building (the game's own test,
   `NNavy::Expedition::FindBuildingPosition`) says so at once ("not enough space") and ends: it sails home and unloads,
   instead of waiting for orders that cannot succeed. The player now knows that harbour needs an invasion.
2. **"Prepare naval invasion".** A new action button at the home buoy of that route, active once the harbour was
   scouted that way. It starts a new ship mission: the ship loads like an expedition (one soldier and the colony
   building's goods) and then **waits at home**.
3. **Attack.** When the player starts an attack on the target's landmass, the waiting invasion ship is the transport:
   the attackers board with the cargo, it sails, and only the attackers land. The expedition soldier and the goods
   stay aboard.
4. **Won:** the colony is founded at once (guard post, the expedition soldier as its garrison); the ship takes the
   surviving attackers home and unloads them. The guard post's garrison is the game's business: with no enemy near,
   the game keeps no soldier there and the soldier walks home by himself (with both route ends the player's, the
   game puts the ship back on the route, so the sea street exists). If there is still no room for the colony (very
   rare), the captured building keeps its garrison and the rest sail home with the "not enough space" message: invade
   again.
5. **Lost:** with `ShipLostOnDefeat` (new setting, harsh: on by default) the ship is destroyed with everything aboard;
   with it off, the invasion is cancelled and the ship sails home and unloads the expedition cargo. The setting holds
   for **every** lost attack by sea, not only invasions: the attacker's ship sinks at the landing.

"Scouted" means: the player has explored the harbour (an expedition reveals it on arrival), it is neutral, and no
colony fits. The button borrows the attack icon and shows plain English texts for now (`README.md`, to do).
