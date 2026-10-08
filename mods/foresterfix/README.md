# Forester fix

When a forester tries to plant a tree on volcanic ground, the game crashes: the volcanic patterns (`pattern_l_*` in
`patterns.lua`) ask for "Lava" trees. PiotrWieczorek's fix
(https://www.moddb.com/games/the-settlers-rise-of-cultures/downloads/forester-crash-fix) changes those ten patterns to
Bavarian trees. This mod makes the same change without replacing the game's file: its own property script
`foresterfix.lua` sets the tree kind of the ten patterns (`properties.pa_setTreeType`). The mod host runs property
scripts that mods add right after the game's own (`mods/README.md`, "Data files").

A data-only mod. It changes the property database, which every player of a match must have alike (`.server`).
