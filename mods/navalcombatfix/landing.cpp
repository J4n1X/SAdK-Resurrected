// navalcombatfix, landing harbours: which harbours a player's soldiers may land at (docs/navy-and-military.md §7).
//
// A player's own harbours, and (NeutralLandings) a neutral harbour where the player could not found a colony: a
// colony is the way to take a free harbour, so a neutral harbour only serves as a landing where an expedition would
// find no room for its building. That test is the game's own, NNavy::Expedition::FindBuildingPosition S 005b7e50,
// without the expedition:
//   - the tribe's expedition building (ShipConfig::GetExpeditionBuilding, sh_setExpeditionBuilding);
//   - every cell within its territoryRange - 1 of the harbour, on the harbour's landmass, whose entrance (one step in
//     direction 1) is more than 1 cell from the harbour;
//   - GameQuery::CanPlaceBuildingTypeAt S 005301c0 with the arguments the expedition passes: player entry 8 of the
//     player table (playerTable + 0x780 in the game; its role [TODO]), no centre exception, the player, borders
//     allowed.
// The expedition takes the first fitting cell; only "is there one" matters here, so the order of the search does not.
#include "navy.hpp"

namespace navalcombatfix {
namespace {

using game::ai::player::Player;

// Room for `player`'s colony building at `harbor` (FindBuildingPosition's search, see above).
bool colony_fits_uncached(Harbor *harbor, std::int32_t player)
{
    Player *colonist = player_entry(player);
    game::ai::properties::PropertiesDb *db = fn::NProperties::StaticAccess::EnsureInstance();
    std::int32_t type = fn::ai::properties::ShipConfig::GetExpeditionBuilding(db->shipConfig, colonist->tribeId);
    game::ai::properties::BuildingProperty *building = fn::ai::properties::PropertiesDb::GetBuildingProperty(db, &type);
    std::int32_t radius = building->territoryRange - 1, landmass = region(harbor);
    std::uint32_t *placementPlayer = expedition_placement_player();
    auto *colonistIndex = reinterpret_cast<std::uint32_t *>(&colonist->index);
    for (std::int32_t y = harbor->posY - radius; y <= harbor->posY + radius; ++y) {
        for (std::int32_t x = harbor->posX - radius - 1; x <= harbor->posX + radius + 1; ++x) {
            if (x < 0 || y < 0 || x >= *var::g_MapWidth || y >= *var::g_MapHeight) continue;
            std::int32_t cell[2] = {x, y};
            if (distance(harbor, cell) > radius || region(x, y) != landmass) continue;
            game::ai::map::MapPos entrance{x, y};
            fn::ai::map::MapPos::StepDirection(&entrance, 1, 1);
            if (distance(&entrance.x, &harbor->posX) <= 1) continue;
            if (fn::ai::game::GameQuery::CanPlaceBuildingTypeAt(logic()->gameQuery, type, cell, placementPlayer, 0,
                                                                colonistIndex, 1))
                return true;
        }
    }
    return false;
}

// The test runs for many buildings and targets in a row; within one tick its answer is reused.
struct ColonyAnswer {
    Harbor *harbor;
    std::int32_t player, tick;
    bool fits;
};
ColonyAnswer g_answers[64];
int g_nextAnswer;

}  // namespace

bool colony_fits(Harbor *harbor, std::int32_t player)
{
    std::int32_t tick = logic()->tickCounter;
    for (ColonyAnswer &a : g_answers)
        if (a.harbor == harbor && a.player == player && a.tick == tick) return a.fits;
    bool fits = colony_fits_uncached(harbor, player);
    g_answers[g_nextAnswer] = {harbor, player, tick, fits};
    g_nextAnswer = (g_nextAnswer + 1) % 64;
    return fits;
}

bool is_landing(Harbor *harbor, std::int32_t player)
{
    if (harbor->playerIdx == player) return true;
    return harbor->playerIdx == -1 && g_settings.neutralLandings && !colony_fits(harbor, player);
}

}  // namespace navalcombatfix
