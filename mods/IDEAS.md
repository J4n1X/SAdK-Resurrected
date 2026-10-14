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

# Mods planned

## mapedit: the developers' map editor, usable

The shipped game still holds the developers' in-game map editor. Concept, with what was tried in the running game
on 2026-10-12 and what the mod has to do: `docs/mod-concepts/mapedit.md`.

## assetshare: map scripts, plain or encrypted

A map's script (`<map>.lua` next to the `.s2m`) is not transferred today: only the `.s2m` and the `.bmp` reach a
joiner, so a scripted map runs its script only on the peers that happen to have the file (`docs/sim/lua-runtime.md`
§10 Q6). assetshare should carry the script with the map and the game should load it whether it is in the game's
encrypted container or a plain text file (maintainer, 2026-10-12), so that map makers can write scripts without an
encryption step. Belongs with the two other things scripted online maps need: the `logic` table registered in
network sessions and script timing tied to the tick counter.

## Build checksum: name the differing file

A joiner whose installation differs is kicked with `!CHECKSUM MISMATCH` and no hint which file is at fault. The build
checksum (`GameData_ComputeBuildChecksum` S 005ab800, `docs/data-loading.md` §3) covers 171 files (`scripts\**\*.lua`,
`settings\**\*.xml`, mod replacements included). A mod could hash each of these files as the checksum reads them
(hooks on `File::Open` S 006e6a30 and `File::Read` S 006e6530) and send the list to the server, which then names the
file to both players. 2026-10-14: a third-party fog mod had edited `settings\daytimes.xml` in place; uninstalling it
on one PC restored the original and broke every join (maintainer).
