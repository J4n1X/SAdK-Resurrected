#!/usr/bin/env bash
# Assembles release/ for a GitHub release (zip its contents): the lobby repository's release (lobby/release, built by
# lobby/packaging/make_release.sh: SAdK-ServerConfig.exe, the mods gamebridge / assetshare / billboards, the server)
# plus this repository's mods of EXTRA_MODS below.
#   release/SAdK-ServerConfig.exe   the players' setup tool (embeds the shim and the lobby's three mods)
#   release/mods/<name>/            the mods, to copy into <game>\mods
#   release/LICENSE
#   release/server/                 the Python server, WITHOUT the game's msgdefs.ini, + a quick guide
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO/release"
export SADKMOD="$REPO/sadkmod"
# This repository's mods a release ships. Test mods (cheatstart, propreload), nomeshcache (for model makers) and
# npcmodels stay out.
EXTRA_MODS="borderless oscursor nopreview foresterfix navalcombatfix"

# Plain make: the Makefiles track their dependencies. (make -B rebuilds sadkmod's precompiled header from several
# sub-makes at once, which corrupts it.)
"$REPO/lobby/packaging/make_release.sh" > /dev/null
make -C "$REPO/mods"

rm -rf "$OUT"
cp -r "$REPO/lobby/release" "$OUT"
for m in $EXTRA_MODS; do cp -r "$REPO/mods/build/$m" "$OUT/mods/"; done
cp "$REPO/mods/navalcombatfix/README.md" "$OUT/mods/navalcombatfix-README.md"
cp "$REPO/sadkmod/docs/writing-mods.md" "$OUT/mods/README.md"
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
README.md describes how mods work and how to write one (https://github.com/S2-modders/sadkmod).
TXT

if find "$OUT" -iname 'msgdefs.ini' | grep -q .; then
    echo "msgdefs.ini ended up in the release — aborting" >&2
    exit 1
fi
echo "release/ assembled:"
(cd "$OUT" && find . -type f | sort | sed 's/^/  /')
