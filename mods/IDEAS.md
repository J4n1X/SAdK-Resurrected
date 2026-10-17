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

## assetshare: warn when the host's server mod is older than yours

A server mod runs in the host's copy for every player, and the mod version is never bumped, so a host with an old
build replaces everyone's newer one without a word. 2026-10-17: an hour-long match crashed at 005719e3 because the
host ran navalcombatfix `08551286…` (built 2026-10-09, before the null-fight fix) while the joiner had the fixed
build (`docs/navy-and-military.md` §7). To do:
- **Build time in the manifest.** Every mod.dll carries its link time in the PE header (`IMAGE_FILE_HEADER.TimeDateStamp`,
  PE header + 8; MinGW's ld writes it on every build, so the builds already handed out have it too). The host's
  manifest line (`mod\tname\tversion\thash\tflags`, `assetshare.cpp`) gets it as a fifth field; older joiners ignore
  it (`sscanf ... >= 3`).
- **Joiner warns.** Same name and version, other hash, own build newer than the host's: a room line such as "Your
  navalcombatfix (built 2026-10-12) is newer than the host's (built 2026-10-09); the host's copy runs for this game.
  Ask the host to update." A host manifest without the field: "the host's assetshare is older; its mods probably
  are too". The joiner can also read the stamp of the downloaded copy itself.
- **The host should hear it too** [decision open]: the joiner's warning only reaches the joiner. Telling the host
  needs a message back (the room chat is the obvious way, but it changes what the room shows).
- **Real versions without bumping.** `sadkmod/mods.mk` writes each mod's last commit time
  (`git log -1 --format=%ct -- <mod>`) into the DLL as its build version; the PE stamp stays the fallback for builds
  without it. A rebuild of old source then no longer looks newer.

## Build checksum: name the differing file

A joiner whose installation differs is kicked with `!CHECKSUM MISMATCH` and no hint which file is at fault. The build
checksum (`GameData_ComputeBuildChecksum` S 005ab800, `docs/data-loading.md` §3) covers 171 files (`scripts\**\*.lua`,
`settings\**\*.xml`, mod replacements included). A mod could hash each of these files as the checksum reads them
(hooks on `File::Open` S 006e6a30 and `File::Read` S 006e6530) and send the list to the server, which then names the
file to both players. 2026-10-14: a third-party fog mod had edited `settings\daytimes.xml` in place; uninstalling it
on one PC restored the original and broke every join (maintainer).
