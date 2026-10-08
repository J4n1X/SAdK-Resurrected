# Naval combat fix

Fixes for how soldiers cross the water in fights (`combat.cpp`) and on retreat (`retreat.cpp`).

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
  attackable when that flag lies within the building's territory range + 1 (the game's own test for enemy harbours).
  Soldiers are gathered by the rule above.
- Soldier counts are the game's own ground-attack counts.
- **Retreat.** If you destroy your military building and in the process lose your harbour, which becomes neutral
  territory, and the soldiers have nowhere to go (the game would let them die), a ship of yours that is ready for the
  route from that harbour to one of yours picks them up. If the harbour's flag becomes enemy territory, the soldiers
  are not allowed to use it to return.
