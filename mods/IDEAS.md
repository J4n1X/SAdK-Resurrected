# Bug fixes not done yet

Reported bugs without a mod yet.

## Campaign: Nile flood bug

In mission 7 of the game, there's a sacrifice used by or against the player (not sure). A bug in the code causes this sacrifice to be broken.

## Ship bugs: a mod of their own

The naval code has several bugs of its own, independent of `navalcombatfix`'s combat rules. They belong in one
client-side mod (working for single player and the campaign too), so that a player can take the fixes without the
combat changes. Known so far (`docs/navy-and-military.md`):
- **A ship deleted while selected crashes the game** (`nMenu::InfoBoxShip::Update`): the game never deselects a
  removed ship, whether it sank or was erased at once (`EraseShipByUnique`). Campaign sacrifices that sink ships hit
  it too. Fixed for now inside `navalcombatfix` (`deselect` in its `NNavy::Ship::dtor` hook, `combat.cpp`); to move
  here.
- **A ship stranded mid-voyage when a harbour changes hands** stays where it stopped, out of every idle-ship search.
  Fixed for now inside `navalcombatfix` (`return_stranded`); to move here, as far as it does not depend on the mod's
  own rules.
