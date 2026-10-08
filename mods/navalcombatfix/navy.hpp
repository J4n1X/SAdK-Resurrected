// navalcombatfix: small helpers over the game's navy and map shared by combat.cpp and retreat.cpp. All game access goes
// through the generated declarations (sourcemap); docs/navy-and-military.md describes the objects.
#pragma once
#include <sadkmod/game/sadk_noav/fn/NLogic.hpp>
#include <sadkmod/game/sadk_noav/fn/NMilitary.hpp>
#include <sadkmod/game/sadk_noav/fn/NNavy.hpp>
#include <sadkmod/game/sadk_noav/fn/NSettlers.hpp>
#include <sadkmod/game/sadk_noav/fn/NVillage.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/game/sadk_noav/fn/ai.hpp>
#include <sadkmod/game/sadk_noav/vars.hpp>
#include <sadkmod/sadkmod.hpp>

#include <algorithm>
#include <cstdint>
#include <span>

namespace navalcombatfix {

namespace game = sadk::game;
namespace fn = sadk::game::fn;
namespace var = sadk::game::var;
using game::NMilitary::Fight;
using game::NNavy::Ship;
using game::NVillage::Building;
using game::ai::navy::Harbor;
using game::ai::navy::HarborExit;
using game::ai::navy::NavyShipRoute;
using NavyMission = game::NNavy::Military;   // a ship's sea transport for a fight (or, from retreat.cpp, a pickup)

// One hook on NNavy::Military::Update S 005ba250 serves both files (combat.cpp installs it); `original` is shared.
using NavyMilitaryUpdate = sadk::Hook<fn::NNavy::Military::Update>;

inline game::NLogic::System *logic() { return *var::g_pGameSystem; }

// The game's own lists as ranges, so a loop reads `for (Harbor *h : harbors())`.
inline std::span<Harbor *> harbors()
{
    game::ai::navy::HarborList &list = logic()->navy->harbors;
    return {list.harborsFirst, list.harborsLast};
}
inline std::span<Ship *> ships()
{
    game::NNavy::System *navy = logic()->navy;
    return {reinterpret_cast<Ship **>(navy->shipsFirst), reinterpret_cast<Ship **>(navy->shipsLast)};
}
// NVillage::System+0x3c: the territory buildings (property byte +0xf5), the list the game's dispatchers walk.
inline std::span<Building *> territory_buildings()
{
    game::NVillage::System *village = logic()->village;
    return {static_cast<Building **>(village->listDefF5Begin), static_cast<Building **>(village->listDefF5End)};
}

inline std::int32_t owner(Building *b) { return b->ownerPlayer->index; }

// Landmass (or water body) id of a cell: NMap::Continents, one int per cell, index y * width + x.
inline std::int32_t region(std::int32_t x, std::int32_t y)
{
    return logic()->map->pContinents->cellContinentFirst[y * *var::g_MapWidth + x];
}
inline std::int32_t region(const std::int32_t *cell) { return region(cell[0], cell[1]); }
inline std::int32_t region(Building *b) { return region(b->posX, b->posY); }
inline std::int32_t region(Harbor *h) { return region(h->posX, h->posY); }

// Hex distance in cells between two cells, each an {x, y} pair (ai::map::MapPos::HexDistance S 00675040).
inline std::int32_t distance(std::int32_t *a, std::int32_t *b)
{
    return static_cast<std::int32_t>(fn::ai::map::MapPos::HexDistance(reinterpret_cast<game::ai::map::MapPos *>(a),
                                                                       reinterpret_cast<game::ai::map::MapPos *>(b)));
}
inline std::int32_t distance(Harbor *h, Building *b) { return distance(&h->posX, &b->posX); }
inline std::int32_t distance(Harbor *h, std::int32_t *cell) { return distance(&h->posX, cell); }

// The ground-attack range: Military_DistanceFalloff S 00574fe0 gives 1 up to 12 cells, then falls linearly to 0 at 24.
constexpr std::int32_t kAttackRange = 24;

inline float falloff(std::int32_t d)
{
    float f = static_cast<float>(kAttackRange - d);
    if (!(f > 0.0f)) return 0.0f;
    f += 12.0f;                              // the game's constants: full strength up to d = 12
    if (!(f < 24.0f)) f = 24.0f;
    return f / 24.0f;
}

// A mission carries a fight while its fight reference holds a valid id (NLogic::Unique: hi in 0..0x7fffffff).
inline bool carries_fight(NavyMission *m) { return m->fight.unique.idHi >= 0; }
inline bool carries(NavyMission *m, Fight *fight)
{
    game::NLogic::Unique &id = m->fight.unique;
    return id.idLo == fight->uniqueIdLo && static_cast<std::uint32_t>(id.idHi) == fight->uniqueIdHi;
}

// For a pickup mission (no fight; retreat.cpp): the game's Update cannot run it in every state.
bool retreat_update(NavyMission *m);

// navalcombatfix.ini, [NavalCombatFix]. Read once at start-up; the defaults are the rules as decided. Every player
// of a match runs the host's copy of the mod, ini included (assetshare compares the whole folder), so the match
// stays in lockstep.
struct Settings {
    bool attackersBySea = true;           // AttackersBySea: attackers gather through their own harbours
    bool defendersBySea = true;           // DefendersBySea: defenders cross the water through their own harbours
    bool attackFromOwnLanding = true;     // AttackFromOwnLanding: an own harbour in the target's range counts
    bool retreatPickup = true;            // RetreatPickup: ships pick up soldiers left with nowhere to go
    bool proximityOverOwnRoutes = true;   // ProximityOverOwnRoutes: own routes count for the distance to the enemy
    std::int32_t crossingDistance = 0;    // CrossingDistance: cells a sea crossing counts as (gathering, proximity)
    std::int32_t pickupTimeout = 1200;    // PickupTimeout: ticks a pickup ship waits for its soldiers
};
extern Settings g_settings;

}  // namespace navalcombatfix
