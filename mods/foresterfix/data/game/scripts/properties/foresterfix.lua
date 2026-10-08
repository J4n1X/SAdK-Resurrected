-- foresterfix: a forester planting a tree on volcanic ground crashes the game, because the volcanic ("l_") patterns
-- ask for "Lava" trees. As PiotrWieczorek's fix of patterns.lua does, they plant Bavarian trees instead.
-- Run by the mod right after the game's own property scripts (data.lua); the game has one Lua state, so the globals
-- patterns.lua set (pattern ids, tree kinds) are still there.

-- A pattern's id: the global patterns.lua gave it, else its hex id the way pa_create hands it out (a signed int).
local function pattern(name, hex)
	local id = _G[name]
	if id == nil then
		id = tonumber(hex, 16)
		if id >= 2147483648 then id = id - 4294967296 end
	end
	return id
end

local bavaria = Bavaria or 5   -- the tree kind patterns.lua calls Bavaria

properties.pa_setTreeType(pattern("pattern_l_ground_00", "decade02"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_ground_02", "decade07"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_ground_03", "decade08"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_ground_04", "decade09"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_rock_00",   "decade04"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_rock_01",   "decade05"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_rock_02",   "decade06"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_rock_03",   "ca87fab0"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_sand_00",   "f1cabb70"), bavaria)
properties.pa_setTreeType(pattern("pattern_l_meadow_00", "f67adb70"), bavaria)
