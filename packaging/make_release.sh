#!/usr/bin/env bash
# Assembles release/ for a GitHub release (zip its contents):
#   release/SAdK-ServerConfig.exe   the players' setup tool (embeds the bridge shim and the billboards mod)
#   release/mods/<name>/            the mods of RELEASE_MODS below, to copy into <game>\mods
#   release/LICENSE
#   release/server/                 the Python server, WITHOUT the game's msgdefs.ini, + a quick guide
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO/release"
# The mods a release ships. Test mods (cheatstart, propreload), nomeshcache (for model makers) and npcmodels stay
# out; gamebridge, assetshare and billboards are also embedded in SAdK-ServerConfig.
RELEASE_MODS="gamebridge assetshare billboards borderless oscursor nopreview foresterfix navalcombatfix"

# Plain make: the Makefiles track their dependencies. (make -B rebuilds sadkmod's precompiled header from several
# sub-makes at once, which corrupts it.)
make -C "$REPO/bridge/wsock32_shim"
make -C "$REPO/mods"
make -C "$REPO/bridge/serverconfig"

rm -rf "$OUT"
mkdir -p "$OUT/server"
cp "$REPO/bridge/serverconfig/SAdK-ServerConfig.exe" "$OUT/"
cp "$REPO/LICENSE" "$OUT/"
mkdir -p "$OUT/mods"
for m in $RELEASE_MODS; do cp -r "$REPO/mods/build/$m" "$OUT/mods/"; done
cp "$REPO/mods/navalcombatfix/README.md" "$OUT/mods/navalcombatfix-README.md"
cp "$REPO/mods/README.md" "$OUT/mods/"
cat > "$OUT/mods/INSTALL.txt" <<'TXT'
Mods for "Die Siedler - Aufbruch der Kulturen". They need the DRM-free SADK.exe and the mod loader
(bin\wsock32.dll), which SAdK-ServerConfig installs.

1. Copy the folders in here into the game's "mods" folder, so that you get e.g.
       ...\Die Siedler - Aufbruch der Kulturen\mods\navalcombatfix\mod.dll
   Create the "mods" folder next to "bin" and "data" if it is not there.
2. Run SAdK-ServerConfig.exe, choose the game folder and the lobby server, and press Save. It installs the mod
   loader and writes your choices into the mods' settings. On any other SADK.exe than the DRM-free one it shows a
   red warning and installs neither the loader nor the mods.

  gamebridge      hosting from behind a router, through the lobby server (gamebridge.ini)
  assetshare      shares a match's map and the host's server mods with the joiners; every player needs it
  billboards      plain screens on the lobby's advertising billboards (billboards.ini)
  borderless      the game's fullscreen becomes a borderless window, stretched to the monitor;
                  borderless.ini: Monitor = primary, or the display number (1, 2, ...)
  oscursor        the game's mouse cursors as Windows cursors: the cursor stays visible at display
                  scaling above 125%
  nopreview       choosing a map without a preview picture (.bmp) no longer crashes the game
  foresterfix     server mod: the forester no longer crashes the game on volcanic ground
  navalcombatfix  server mod: soldiers cross the water through their own harbours, naval invasions;
                  settings in navalcombatfix.ini, described in navalcombatfix-README.md

gamebridge, assetshare and billboards are also inside SAdK-ServerConfig, which installs them by itself.

A server mod runs for every player of a match: the host's copy, its .ini included, is used, and joiners who do not
have it (or have another version) download it from the host when they enter the game.

To switch a mod off, remove its folder or rename it so that it starts with "_".
README.md describes how mods work and how to write one.
TXT

# The package's tracked .py files (working-tree contents), minus the game's msgdefs.ini: players
# supply their own copy.
(cd "$REPO" && git ls-files sadk_lobby | grep '\.py$') | while read -r f; do
    mkdir -p "$OUT/server/$(dirname "$f")"
    cp "$REPO/$f" "$OUT/server/$f"
done
mkdir -p "$OUT/server/sadk_lobby/data"
cat > "$OUT/server/sadk_lobby/data/PUT_MSGDEFS_INI_HERE.txt" <<'TXT'
Copy msgdefs.ini from the bin folder of your game installation into this folder.
The server reads the game's own message definitions from it and will not start without it.
TXT
cp "$REPO/requirements.txt" "$OUT/server/"
cp "$REPO/packaging/server-README.md" "$OUT/server/README.md"
cp "$REPO/LICENSE" "$OUT/server/"

if find "$OUT" -iname 'msgdefs.ini' | grep -q .; then
    echo "msgdefs.ini ended up in the release — aborting" >&2
    exit 1
fi
echo "release/ assembled:"
(cd "$OUT" && find . -type f | sort | sed 's/^/  /')
