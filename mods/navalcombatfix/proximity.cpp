// navalcombatfix, proximity: routes between two harbours of the same player count for the distance to the enemy
// (docs/navy-and-military.md §2 "Proximity zones", §7).
//
// Every military building caches its distance to the nearest enemy (NMilitary::Distances::UpdateBuildingEnemyDistances
// S 00574e40, every 11 military ticks), from GameQueryHelper::MinDistanceToEnemyMilitaryBuilding S 005337e0: the
// nearest enemy military building, or (includeHarbors) the nearest own harbour on the building's landmass with a route
// to an *enemy* harbour. Below 19 cells is zone 2, up to 24 zone 1. The zone draws the stripes on the building's flag
// (zone A) and gates attacks on it (zone B: a target outside zone 2 cannot be attacked), before any of combat.cpp's
// rules. A route whose two ends belong to the same player never counts, so
//   - a building whose soldiers now cross through its owner's harbours shows no stripes for it, and
//   - a target near a colony's harbour, but 19 or more cells from the colonist's military buildings, cannot be attacked.
// Added here, with the same sum the soldier count uses (combat.cpp), and like the game without asking for a ship:
//   - own route: an own harbour H2 on this landmass, its route to another own harbour H1:
//     d(here, H2) + d(H1, the nearest enemy military building on H1's landmass);
//   - the enemy's own route: an enemy harbour H1 on this landmass, its route to another harbour H2 of that enemy:
//     d(here, H1) + d(H2, the nearest military building of that enemy on H2's landmass).
// The game's own distance stays when it is smaller.
#include "navy.hpp"

namespace navalcombatfix {
namespace {

using game::ai::player::Player;
using MinEnemyDistance = sadk::Hook<fn::ai::game::GameQueryHelper::MinDistanceToEnemyMilitaryBuilding>;

constexpr std::int32_t kFar = 1000;   // the game's "no enemy" distance

Player *player_entry(std::int32_t index) { return fn::PlayerTable_GetEntry(logic()->playerTable, &index); }

// The game's filters for an enemy (MinDistanceToEnemyMilitaryBuilding S 005337e0): an enemy of `player`
// (Player::IsEnemyOf S 005be280), with filterDiplomacy not marked in `player`'s per-player flags.
bool enemy_of(Player *other, Player *player, bool filterDiplomacy)
{
    return fn::ai::player::Player::IsEnemyOf(other, player) &&
           (!filterDiplomacy || player->pMilitary->flags[other->index] == 0);
}

// A military building that counts as an enemy's: territory active (the game's test, TerritoryUpdater+8).
bool counts(Building *b) { return b->territoryUpdater->bActive; }

// The nearest building of `isWanted` on the landmass of `harbor`, from `harbor`; kFar if none.
template <class Wanted>
std::int32_t nearest_building(Harbor *harbor, Wanted isWanted)
{
    std::int32_t best = kFar, landmass = region(harbor);
    for (Building *b : territory_buildings())
        if (counts(b) && region(b) == landmass && isWanted(b)) best = std::min(best, distance(harbor, b));
    return best;
}

bool route_between(Harbor *a, Harbor *b) { return a != b && fn::ai::navy::Harbor::FindExitConnectedTo(a, b); }

// Own route: our harbour H2 here, a route to our harbour H1 elsewhere, an enemy military building near H1.
std::int32_t over_own_route(std::int32_t *pos, Player *player, bool filterDiplomacy)
{
    std::int32_t best = kFar, here = region(pos);
    for (Harbor *home : harbors()) {
        if (home->playerIdx != player->index || region(home) != here) continue;
        for (Harbor *landing : harbors()) {
            if (landing->playerIdx != player->index || region(landing) == here || !route_between(home, landing))
                continue;
            std::int32_t toEnemy = nearest_building(
                landing, [&](Building *b) { return enemy_of(b->ownerPlayer, player, filterDiplomacy); });
            best = std::min(best, distance(home, pos) + g_settings.crossingDistance + toEnemy);
        }
    }
    return best;
}

// The enemy's own route: an enemy's harbour H1 here, a route to that enemy's harbour H2 elsewhere, a military
// building of that enemy near H2.
std::int32_t over_enemy_route(std::int32_t *pos, Player *player, bool filterDiplomacy)
{
    std::int32_t best = kFar, here = region(pos);
    for (Harbor *landing : harbors()) {
        if (landing->playerIdx < 0 || landing->playerIdx == player->index || region(landing) != here) continue;
        Player *enemy = player_entry(landing->playerIdx);
        if (!enemy || !enemy_of(enemy, player, filterDiplomacy)) continue;
        for (Harbor *home : harbors()) {
            if (home->playerIdx != landing->playerIdx || region(home) == here || !route_between(landing, home))
                continue;
            std::int32_t toEnemy = nearest_building(home, [&](Building *b) { return owner(b) == enemy->index; });
            best = std::min(best, distance(landing, pos) + g_settings.crossingDistance + toEnemy);
        }
    }
    return best;
}

std::int32_t SADK_THISCALL min_enemy_distance(game::ai::game::GameQueryHelper *helper, std::int32_t *pos,
                                              Player *player, bool filterDiplomacy, bool includeHarbors)
{
    std::int32_t d = MinEnemyDistance::original(helper, pos, player, filterDiplomacy, includeHarbors);
    if (!includeHarbors || !g_settings.proximityOverOwnRoutes) return d;
    d = std::min(d, over_own_route(pos, player, filterDiplomacy));
    return std::min(d, over_enemy_route(pos, player, filterDiplomacy));
}

}  // namespace
}  // namespace navalcombatfix

bool proximity_start()
{
    bool ok = navalcombatfix::MinEnemyDistance::install(navalcombatfix::min_enemy_distance);
    sadk::log("%s", ok ? "proximity: own routes count for the distance to the enemy" : "proximity NOT active");
    return ok;
}
