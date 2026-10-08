# Forester fix

When a forester tries to plant a tree on a volcanic texture, the game crashes. The fix is a corrected
`data\game\scripts\properties\patterns.lua` by PiotrWieczorek, included here with his consent; the original
download: https://www.moddb.com/games/the-settlers-rise-of-cultures/downloads/forester-crash-fix

A plain data mod (no code). It changes a property script, which is part of the match checksum, so every player of a
match needs it (`.server`).
