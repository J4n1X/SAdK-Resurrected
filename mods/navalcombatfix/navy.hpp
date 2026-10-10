// navalcombatfix: small helpers over the game's navy and map shared by combat.cpp and retreat.cpp. All game access goes
// through the generated declarations (sourcemap); docs/navy-and-military.md describes the objects.
#pragma once
#include <sadkmod/game/sadk_noav/fn/NLogic.hpp>
#include <sadkmod/game/sadk_noav/fn/NMilitary.hpp>
#include <sadkmod/game/sadk_noav/fn/NNavy.hpp>
#include <sadkmod/game/sadk_noav/fn/NProperties.hpp>
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

// An entry of the game's player table (PlayerTable_GetEntry S 005bdd50).
inline game::ai::player::Player *player_entry(std::int32_t index)
{
    return fn::PlayerTable_GetEntry(logic()->playerTable, &index);
}

// The first player FindBuildingPosition S 005b7e50 passes to the placement test: entry 8 of the player table
// (playerTable + 0x780 in the game; its role [TODO]). The colonist goes in as the alternative player.
inline std::uint32_t *expedition_placement_player()
{
    return reinterpret_cast<std::uint32_t *>(&player_entry(8)->index);
}

// A mission carries a fight while its fight reference holds a valid id (NLogic::Unique: hi in 0..0x7fffffff).
inline bool carries_fight(NavyMission *m) { return m->fight.unique.idHi >= 0; }
inline bool carries(NavyMission *m, Fight *fight)
{
    game::NLogic::Unique &id = m->fight.unique;
    return id.idLo == fight->uniqueIdLo && static_cast<std::uint32_t>(id.idHi) == fight->uniqueIdHi;
}

// The fight is over for the mission once every one of its soldiers has left it (or none is left).
inline bool battle_over(NavyMission *m)
{
    return fn::NavyMilitary_AllSoldiersLeftFight(reinterpret_cast<game::ai::stl::MsvcVector *>(&m->soldiers.refs_proxy));
}

// How the mission's fight ended, in the game's terms (NMilitary::Fight::GetPhase S 005708a0). Read unresolved, as the
// game does: ships keep their fight alive (Fight +0xbc).
//   - Lost: phase Fighting, the target still stands and is not the attacker's;
//   - Won: TargetCaptured, or a target that is gone (NoTarget), or Ending with the target the attacker's;
//   - Cancelled: Ending with the target not the attacker's. Calling an attack off (lockstep 0x2000E,
//     nGame::System::HandleCancelAttack S 00782bf0 -> Military_RequestCancel S 00570900) sets the fight's ending flag
//     (Fight::bEnding), as holding the target does.
enum class Outcome { won, lost, cancelled };
inline Outcome battle_outcome(NavyMission *m)
{
    Fight *fight = m->fight.cachedFight;
    if (!fight) return Outcome::won;
    using Phase = game::ai::military::EFightPhase;
    Phase phase = fn::NMilitary::Fight::GetPhase(fight);
    if (phase == Phase::Fighting) return Outcome::lost;
    if (phase != Phase::Ending || fight->target.unique.idHi < 0 || !fight->target.cachedBuilding) return Outcome::won;
    return owner(fight->target.cachedBuilding) == fight->attackerPlayer ? Outcome::won : Outcome::cancelled;
}

// The harbour the ship lies at (or sails to) is its player's: a lost attack from there is a coastal attack, the ship
// is safe (maintainer's rule).
inline bool at_own_harbor(Ship *ship)
{
    Harbor *h = fn::NLogic::ReferenceHarbor::Resolve(&ship->movement->targetHarbor);
    return h && h->playerIdx == ship->player->index;
}

// For a pickup mission (no fight; retreat.cpp): the game's Update cannot run it in every state.
bool retreat_update(NavyMission *m);

// ValidRetreatHarbors: the harbours a ship may pick stranded soldiers up from (retreat.cpp). Each level includes
// the ones before it; `own` leaves the soldiers to the game (only its own sea streets bring them home).
enum class RetreatHarbors { own, neutral, friendly, all };

// navalcombatfix.ini, [NavalCombatFix]. Read once at start-up; the defaults are the rules as decided. Every player
// of a match runs the host's copy of the mod, ini included (assetshare compares the whole folder), so the match
// stays in lockstep.
struct Settings {
    bool attackersBySea = true;           // AttackersBySea: attackers gather through their own harbours
    bool defendersBySea = true;           // DefendersBySea: defenders cross the water through their own harbours
    bool attackFromOwnLanding = true;     // AttackFromOwnLanding: an own harbour in the target's range counts
    RetreatHarbors retreatHarbors = RetreatHarbors::neutral;   // ValidRetreatHarbors: where ships pick up stranded soldiers
    bool proximityOverOwnRoutes = true;   // ProximityOverOwnRoutes: own routes count for the distance to the enemy
    bool neutralLandings = true;          // NeutralLandings: neutral harbours without room for a colony are landings
    std::int32_t crossingDistance = 0;    // CrossingDistance: cells a sea crossing counts as (gathering, proximity)
    std::int32_t pickupTimeout = 1200;    // PickupTimeout: ticks a pickup ship waits for its soldiers
    bool shipLostOnDefeat = false;        // ShipLostOnDefeat: a lost attack by sea sinks the attacker's ship
    std::int32_t landingReach = 9;        // LandingReach: cells a landing harbour may lie beyond a target's range + 1
    bool harborMustHaveGarrison = true;   // HarborMustHaveGarrison: expeditions may take ungarrisoned enemy harbours
};
extern Settings g_settings;

// A harbour `player`'s soldiers may land at: one of the player's own, or a neutral one where the player could not
// found a colony (landing.cpp).
bool is_landing(Harbor *harbor, std::int32_t player);
// Room for `player`'s colony building at `harbor` (the game's colony placement test; landing.cpp).
bool colony_fits(Harbor *harbor, std::int32_t player);

// A message about `ship` in its player's event log, with the ship's name as its subject (invasion.cpp). `key` is a
// localisation key; with `text`, the mod's own key and its English text, entered into the game's table first.
void tell(Ship *ship, const char *key, const char *text = nullptr);
// A message of PlayerMessages type `type` in `player`'s event log at `cell` ({x, y}), with `subject` shown as
// " (subject)" (invasion.cpp). `key` and `text` as for tell.
void post(std::int32_t type, std::int32_t player, const char *key, const char *text, sadk::msvc::string *subject,
          std::int32_t *cell);

// A naval invasion ship loaded and waiting at home for an attack (invasion.cpp).
bool invasion_ready(Ship *ship);

// HarborMustHaveGarrison (takeover.cpp): `h` is an enemy's harbour without a land street to one of its owner's
// finished military buildings, so `player`'s expedition may take it.
bool harbor_open_to(Harbor *h, std::int32_t player);
// The game's founding (Expedition::Update state 6, `original`), with the harbour takeover where it applies: at a
// harbour open to the player, and for a naval invasion (`invasion`) also at a free harbour whose land is contested.
// no_room: an enemy's harbour where not even the takeover finds room; the caller sends the expedition home.
enum class TakeoverResult { founded, game, no_room };
TakeoverResult found_colony(game::NNavy::Expedition *e, bool invasion, bool (*original)(game::NNavy::Expedition *));

// A ship is being deleted (combat.cpp's hook on its destructor): the files drop what they keep about it.
void retreat_forget_ship(Ship *ship);
void invasion_forget_ship(Ship *ship);

// The game still has this route / harbour (a pointer the mod kept may outlive it: a harbour's destruction deletes
// its routes). Compares pointers only, nothing is read through them.
inline bool route_alive(NavyShipRoute *route)
{
    game::ai::navy::ShipRouteList &list = logic()->navy->shipRoutes;
    for (auto **r = static_cast<NavyShipRoute **>(list.routesFirst); r != static_cast<NavyShipRoute **>(list.routesLast); ++r)
        if (*r == route) return true;
    return false;
}
inline bool harbor_alive(Harbor *harbor)
{
    for (Harbor *h : harbors())
        if (h == harbor) return true;
    return false;
}

}  // namespace navalcombatfix
