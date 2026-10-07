#!/usr/bin/env bash
# Assembles release/ for a GitHub release (zip its contents):
#   release/SAdK-ServerConfig.exe   the players' setup tool (embeds the bridge shim)
#   release/LICENSE
#   release/server/                 the Python server, WITHOUT the game's msgdefs.ini, + a quick guide
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO/release"

make -C "$REPO/bridge/wsock32_shim" -B
make -C "$REPO/bridge/serverconfig" -B

rm -rf "$OUT"
mkdir -p "$OUT/server"
cp "$REPO/bridge/serverconfig/SAdK-ServerConfig.exe" "$OUT/"
cp "$REPO/LICENSE" "$OUT/"

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
