// navalcombatfix, combat by sea: soldiers cross the water through harbours of their own player (docs/navy-and-military.md:
// §2-§6 the game's rules, §7 this change).
//
// The game ships soldiers only towards a landing harbour that belongs to the target's owner: every sea check goes
// through HarborList::FindNearestWithPlayerShipRoute S 005b6090, which filters by that owner. So
//   - an attacker who already owns a harbour next to the target (both sides of the route) gathers no soldiers from
//     across the water, and neither does a defender whose buildings are across the water from the attacked one
//     (Attack::DispatchDefenders S 00576400 never uses the sea at all);
//   - after an expedition founds a colony (NNavy::Expedition::Update S 005b8ac0, state 6) the landing harbour
//     belongs to the colonist, so no sea attack is possible from it.
// The rules added here, decided by the maintainer:
//   - Gathering: a building of player P across the water from the target contributes through a pair of P's harbours,
//     H1 on the target's landmass and H2 on the building's, joined by a route with a ship of P for it. The crossing
//     counts as zero length: the game's own distance falloff (Military_DistanceFalloff S 00574fe0) applies to
//     d(target, H1) + d(H2, building). That holds for attackers and defenders alike.
//   - Attacking: a target is attackable when such an H1 lies within the target's territory range + 1, the same test
//     the game uses for an enemy-owned landing harbour (Military_IsHarborWithinBuildingRange S 00574f70).
//   - The ship's mission (NNavy::Military::Update S 005ba250) picks its route ends by owner; when both ends belong
//     to the ship's player it lands at the end on the target's landmass and loads at the other one.
// Everything else, including every case the game already handles, runs the game's own code unchanged. The retreat
// rule (soldiers left with nowhere to go) is in retreat.cpp.
#include "navy.hpp"

namespace navalcombatfix {
namespace {

using game::NMilitary::AttackConnector;
using game::NMilitary::ISoldierConnector;

using ReachFactor = sadk::Hook<fn::Military_GetAttackReachFactor>;
using TargetReachable = sadk::Hook<fn::Military_IsTargetReachable>;
using TerritoryInRange = sadk::Hook<fn::Military_IsEnemyTerritoryInRange>;
using DispatchAttackers = sadk::Hook<fn::NMilitary::Attack::DispatchAttackers>;
using DispatchDefenders = sadk::Hook<fn::NMilitary::Attack::DispatchDefenders>;
using SendBySea = sadk::Hook<fn::NMilitary::AttackConnector::SendSoldiersBySea>;

// ---- The fight being dispatched ----------------------------------------------------------------------------------
//
// Counting soldiers (the reach factor) runs both inside a dispatch and outside it (attack button, AI estimates); only
// inside does a ship already busy with *this* fight count as available. The dispatch hooks record the fight for their
// duration. NAI::StrengthCounter implements the same connector interface to count soldiers for the AI and has no
// fight; it is told apart from the real AttackConnector by its vtable.

Fight *g_dispatchFight;

struct DispatchScope {
    Fight *saved = g_dispatchFight;
    explicit DispatchScope(ISoldierConnector *c)
    {
        bool realAttack = c->vftable == var::NMilitary::AttackConnector::vftable.get();
        g_dispatchFight = realAttack ? reinterpret_cast<AttackConnector *>(c)->fight : nullptr;
    }
    ~DispatchScope() { g_dispatchFight = saved; }
};

// ---- Own sea links -----------------------------------------------------------------------------------------------

struct SeaLink {
    Harbor *landing = nullptr;      // H1, on the target's landmass
    Harbor *home = nullptr;         // H2, on the building's landmass
    NavyShipRoute *route = nullptr; // the route from H2's exit to H1
    Ship *ship = nullptr;           // the player's ship for this route
    bool onRoute = false;           // already on the route (carrying this fight), else idle and still to be linked
    std::int32_t distance = 0;      // d(target, H1) + d(H2, building)
};

// The ship of `player` that can carry soldiers of `fight` over the route from `home` to `landing`: the checks of
// AttackConnector::SendSoldiersBySea S 00575510, made for this one route. A route takes one ship per player
// (NavyShipRoute::CanPlayerAssignShip S 005b6d30):
//   - the player already has a ship on it: usable only while its mission is active and carries this fight;
//   - else the nearest idle ship of the player at H2's exit (NNavy::System::FindNearestIdleShipAtHarborExit
//     S 005b3450), linked to the route only when the soldiers are actually sent.
bool route_ship(Harbor *home, Harbor *landing, std::int32_t player, Fight *fight, SeaLink *link)
{
    HarborExit *exit = fn::ai::navy::Harbor::FindExitConnectedTo(home, landing);
    if (!exit) return false;
    NavyShipRoute *route = fn::NLogic::ReferenceShipRoute::Resolve(&exit->route);
    if (!route) return false;
    Ship *ship;
    bool onRoute = fn::ai::navy::NavyShipRoute::HasPlayerEntry(route, player);
    if (onRoute) {
        if (!fight) return false;   // outside a dispatch a busy ship never counts
        ship = fn::ai::navy::NavyShipRoute::GetPlayerEntryOrFirst(route, player);
        if (!ship->military->bActive || !carries(ship->military, fight)) return false;
    } else {
        ship = fn::NNavy::System::FindNearestIdleShipAtHarborExit(logic()->navy, player, &exit->posX);
        if (!ship) return false;
    }
    link->route = route;
    link->ship = ship;
    link->onRoute = onRoute;
    return true;
}

// The best usable pair of the building owner's own harbours for carrying the building's soldiers to the target:
// H1 of the player on the target's landmass, H2 of the player on the building's landmass, a ship for the route
// between them (route_ship), and the smallest d(target, H1) + d(H2, building) within the attack range. Only for a
// building on another landmass: the game's overland rules stay untouched. Counting and sending both use this, so
// the soldiers counted for a building are the ones its ship can take, and a blocked route falls back to the next pair.
bool own_sea_link(Building *building, Building *target, Fight *fight, SeaLink *best)
{
    std::int32_t player = owner(building), targetRegion = region(target), buildingRegion = region(building);
    if (buildingRegion == targetRegion) return false;
    bool found = false;
    for (Harbor *landing : harbors()) {
        if (landing->playerIdx != player || region(landing) != targetRegion) continue;
        for (Harbor *home : harbors()) {
            if (home->playerIdx != player || region(home) != buildingRegion) continue;
            std::int32_t d = distance(landing, target) + distance(home, building);
            if (d >= kAttackRange || (found && d >= best->distance)) continue;
            SeaLink link;
            if (!route_ship(home, landing, player, fight, &link)) continue;
            link.landing = landing;
            link.home = home;
            link.distance = d;
            *best = link;
            found = true;
        }
    }
    return found;
}

// ---- Hooks: counting and attackability ---------------------------------------------------------------------------

// Military_GetAttackReachFactor S 00575320: where the game finds no way (0), the own sea link's falloff.
float SADK_CDECL reach_factor(Building *building, Building *target)
{
    float f = ReachFactor::original(building, target);
    if (f != 0.0f) return f;
    SeaLink link;
    return own_sea_link(building, target, g_dispatchFight, &link) ? falloff(link.distance) : 0.0f;
}

// Military_IsTargetReachable S 00575cb0: also reachable over an own sea link.
bool SADK_CDECL target_reachable(Building *target, Building *building, bool persistentCache, bool allowSea)
{
    if (TargetReachable::original(target, building, persistentCache, allowSea)) return true;
    SeaLink link;
    return allowSea && own_sea_link(building, target, g_dispatchFight, &link);
}

// A harbour of `player` on the target's landmass within the target's territory range + 1, with a route to one of
// the player's harbours across the water and a ship for it (the game's harbour test without its owner condition).
bool own_landing_in_range(Building *target, std::int32_t player)
{
    std::int32_t range = fn::NVillage::Military::GetTerritoryRange(target->military), targetRegion = region(target);
    for (Harbor *landing : harbors()) {
        if (landing->playerIdx != player || region(landing) != targetRegion || distance(landing, target) >= range + 1)
            continue;
        for (Harbor *home : harbors()) {
            SeaLink link;
            if (home->playerIdx == player && region(home) != targetRegion &&
                route_ship(home, landing, player, g_dispatchFight, &link))
                return true;
        }
    }
    return false;
}

// Military_IsEnemyTerritoryInRange S 00575850 (the attack button): also true for an own landing harbour in range.
bool SADK_CDECL territory_in_range(Building *target, std::int32_t *attacker)
{
    return TerritoryInRange::original(target, attacker) || own_landing_in_range(target, *attacker);
}

// ---- Hooks: dispatch ---------------------------------------------------------------------------------------------

void SADK_THISCALL dispatch_attackers(game::NMilitary::Attack *attack, ISoldierConnector *connector,
                                      float soldierFraction)
{
    DispatchScope scope(connector);
    DispatchAttackers::original(attack, connector, soldierFraction);
}

// Attack::DispatchDefenders S 00576400, with one change: a building on another landmass than the target sends its
// defenders through the connector's sea slot. The counts are the game's: the target's own garrison completely, every
// other building of the defender (int)(GetAvailableAttackers * soldierFraction + 0.5).
void SADK_THISCALL dispatch_defenders(game::NMilitary::Attack *attack, ISoldierConnector *connector,
                                      float soldierFraction)
{
    DispatchScope scope(connector);
    game::NMilitary::ISoldierConnector_vftable *slots = connector->vftable;
    Building *target = slots->GetTarget(connector);
    std::int32_t defender = owner(target), targetRegion = region(target);
    for (Building *b : territory_buildings()) {
        if (b == target) {
            slots->SendOverland(connector, b, 0x7fffffff);   // the whole garrison
            continue;
        }
        if (owner(b) != defender) continue;
        std::int32_t available = fn::NMilitary::Attack::GetAvailableAttackers(attack, target, b, true);
        auto count = static_cast<std::int32_t>(static_cast<double>(available) * soldierFraction + 0.5);
        if (count <= 0) continue;
        if (region(b) != targetRegion)
            slots->SendBySea(connector, b, count);
        else
            slots->SendOverland(connector, b, count);
    }
}

// AttackConnector::SendSoldiersBySea S 00575510. The game's own code when the game's own rules counted this building
// (its reach factor is above 0: an enemy landing harbour, or the same landmass); otherwise the own sea link the
// soldiers were counted with, with the ships of the building's owner (the game would use the attacker's, which is
// wrong for defenders).
void SADK_THISCALL send_by_sea(AttackConnector *connector, Building *building, std::int32_t count)
{
    Building *target = connector->vftable->GetTarget(reinterpret_cast<ISoldierConnector *>(connector));
    if (ReachFactor::original(building, target) != 0.0f) {
        SendBySea::original(connector, building, count);
        return;
    }
    SeaLink link;
    if (!own_sea_link(building, target, connector->fight, &link)) return;
    if (!link.onRoute) {   // the first building of this fight on the route brings the ship in
        fn::NavyLink_LinkMilitaryRoute(link.route, link.ship);
        fn::NavyLink_LinkMilitaryFight(connector->fight, link.ship);
    }
    // __thiscall on the connector: binds each soldier to connector->fight and to the ship.
    fn::NMilitary::AttackConnector::SendSoldiersFromBuilding(connector, building, count, link.ship);
}

// ---- Hook: the ship's mission ------------------------------------------------------------------------------------

constexpr std::int32_t kSailToLoading = 0;   // NNavy::Military states (docs/navy-and-military.md §5.3)
constexpr std::int32_t kWaitForCargo = 1;
constexpr std::int32_t kSailToLanding = 3;
constexpr std::int32_t kDisembark = 4;

// The ends of a route that belong to `player` at both sides, split into the one on the target's landmass and the
// other one. False when the route is not wholly the player's or the target's landmass is not exactly one of its ends.
bool own_route_ends(NavyShipRoute *route, std::int32_t player, std::int32_t targetRegion, Harbor **home,
                    Harbor **landing)
{
    Harbor *a = fn::NLogic::ReferenceHarbor::Resolve(&route->harborA);
    Harbor *b = fn::NLogic::ReferenceHarbor::Resolve(&route->harborB);
    if (!a || !b || a->playerIdx != player || b->playerIdx != player) return false;
    bool aLands = region(a) == targetRegion, bLands = region(b) == targetRegion;
    if (aLands == bLands) return false;
    *landing = aLands ? a : b;
    *home = aLands ? b : a;
    return true;
}

// NNavy::Military::Update S 005ba250. Its states 0 (sail to the loading end) and 3 (sail to the landing end) pick
// the end owned by the ship's player and by the fight's defender; when both ends belong to the ship's player, the
// landing end is the one on the target's landmass. A mission without a fight is a pickup (retreat.cpp). The guard is
// the game's: the mission is active and the ship stands still (its step interpolator not running, movement state 0
// or 4).
bool SADK_THISCALL navy_military_update(NavyMission *m)
{
    auto *ship = static_cast<Ship *>(m->ship);
    game::NNavy::Movement *mv = ship->movement;
    if (!m->bActive || (mv->state != 0 && mv->state != 4) || mv->base.interpolator.progress > 0.0f)
        return NavyMilitaryUpdate::original(m);
    if (!carries_fight(m)) return retreat_update(m);
    if (m->state != kSailToLoading && m->state != kSailToLanding) return NavyMilitaryUpdate::original(m);

    NavyShipRoute *route = fn::NLogic::ReferenceShipRoute::Resolve(&mv->route);
    Fight *fight = m->fight.cachedFight;   // read unresolved, as the game does
    Building *target = fight ? fight->target.cachedBuilding : nullptr;
    Harbor *home, *landing;
    if (!route || !target || !own_route_ends(route, ship->player->index, region(target), &home, &landing))
        return NavyMilitaryUpdate::original(m);
    bool loading = m->state == kSailToLoading;
    fn::NNavy::Movement::MoveToHarbor(mv, loading ? home : landing);
    m->state = loading ? kWaitForCargo : kDisembark;
    return false;
}

}  // namespace
}  // namespace navalcombatfix

bool combat_start()
{
    using namespace navalcombatfix;
    bool ok = ReachFactor::install(reach_factor) && TargetReachable::install(target_reachable) &&
              TerritoryInRange::install(territory_in_range) && DispatchAttackers::install(dispatch_attackers) &&
              DispatchDefenders::install(dispatch_defenders) && SendBySea::install(send_by_sea) &&
              NavyMilitaryUpdate::install(navy_military_update);
    sadk::log("%s", ok ? "combat by sea: soldiers cross through their own harbours" : "combat by sea NOT active");
    return ok;
}
