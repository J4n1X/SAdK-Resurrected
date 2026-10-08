#!/usr/bin/env bash
# Assembles release/ for a GitHub release (zip its contents):
#   release/SAdK-ServerConfig.exe   the players' setup tool (embeds the bridge shim and the billboards mod)
#   release/mods/<name>/            the repo's mods, to copy into <game>\mods (optional extras)
#   release/LICENSE
#   release/server/                 the Python server, WITHOUT the game's msgdefs.ini, + a quick guide
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO/release"

make -C "$REPO/bridge/wsock32_shim" -B
make -C "$REPO/mods" -B
make -C "$REPO/bridge/serverconfig" -B

rm -rf "$OUT"
mkdir -p "$OUT/server"
cp "$REPO/bridge/serverconfig/SAdK-ServerConfig.exe" "$OUT/"
cp "$REPO/LICENSE" "$OUT/"
mkdir -p "$OUT/mods"
cp -r "$REPO"/mods/build/*/ "$OUT/mods/"
cp "$REPO/mods/README.md" "$OUT/mods/"
cat > "$OUT/mods/INSTALL.txt" <<'TXT'
Optional mods for "Die Siedler - Aufbruch der Kulturen" (they need the DRM-free SADK.exe and the bridge shim,
which SAdK-ServerConfig installs).

Install: copy a mod's folder into the game's "mods" folder, e.g.
    ...\Die Siedler - Aufbruch der Kulturen\mods\borderless\
Create the "mods" folder next to "bin" and "data" if it is not there. Remove the folder (or rename it so it starts
with "_") to switch the mod off.

  billboards    plain screens on the lobby's advertising billboards (SAdK-ServerConfig installs it;
                "Disable billboards" = Enabled in billboards.ini)
  borderless    the game's fullscreen becomes a borderless window, stretched to the monitor;
                borderless.ini: Monitor = primary, or the display number (1, 2, ...)
  nomeshcache   models are always read from their .KEX files (no cache); for model makers only: loads slower,
                and the lobby town flickers while it is on
  npcmodels     lets the server show the female, MacDoyleJr and MacGabhan NPC models (chat: !npc <set> <index>)

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
