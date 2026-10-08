# Forester fix

When a forester tries to plant a tree on a volcanic texture, the game crashes. The fix is a corrected
`data\game\scripts\properties\patterns.lua` by PiotrWieczorek:
https://www.moddb.com/games/the-settlers-rise-of-cultures/downloads/forester-crash-fix

The file is game data and is not in this repository. Put the fixed `patterns.lua` at
`mods/foresterfix/data/game/scripts/properties/patterns.lua` before `make`; the build copies it to
`build/foresterfix/`.

A plain data mod (no code). It changes a property script, which is part of the match checksum, so every player of a
match needs it (`.server`).
