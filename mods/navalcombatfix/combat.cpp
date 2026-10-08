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
//     H1 on the target's landmass and H2 on the building's, joined by a route with a ship of P for it. Each building
//     picks its own best pair, so buildings near different home harbours reach the same H1 over different routes,
//     each with its own ship. The crossing counts as zero length: the game's own distance falloff
//     (Military_DistanceFalloff S 00574fe0) applies to d(target, H1) + d(H2, building). That holds for attackers and
//     defenders alike.
//   - Attacking: a target is attackable when such an H1 lies within the target's territory range + 1, the same test
//     the game uses for an enemy-owned landing harbour (Military_IsHarborWithinBuildingRange S 00574f70).
//   - The ship's mission (NNavy::Military::Update S 005ba250) picks its route ends by owner; when both ends belong
//     to the ship's player it lands at the end on the target's landmass and loads at the other one.
// Everything else, including every case the game already handles, runs the game's own code unchanged. The retreat
// rule (soldiers left with nowhere to go) is in retreat.cpp.
#include "navy.hpp"

namespace navalcombatfix {

Settings g_settings;

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
    bool invasion = false;          // a naval invasion ship waiting at home (invasion.cpp), still to be linked
    bool routeIdle = false;         // the route's own ship, idle on it (its sea street), still to be linked
    std::int32_t distance = 0;      // d(target, H1) + d(H2, building)
};

// The ship of `player` that can carry soldiers of `fight` over the route from `home` to `landing`: the checks of
// AttackConnector::SendSoldiersBySea S 00575510, made for this one route. A route takes one ship per player
// (NavyShipRoute::CanPlayerAssignShip S 005b6d30):
//   - the player already has a ship on it: usable while its mission is active and carries this fight, or while it
//     lies idle on the route (ship state idle or waiting, no mission): the ship of a sea street between two of the
//     player's harbours, which FindNearestIdleShipAtHarborExit skips because it serves the route already [live
//     2026-10-08: such a ship, state 1, made every attack over its route count only the target's landmass];
//   - else the nearest idle ship of the player at H2's exit (NNavy::System::FindNearestIdleShipAtHarborExit
//     S 005b3450), linked to the route only when the soldiers are actually sent.
constexpr std::int32_t kShipIdle = 0;      // NNavy::Ship states (docs/navy-and-military.md §5.3); 0 also picks up a
constexpr std::int32_t kShipWaiting = 1;   // mission (Ship::Update S 005bb500: an active mission -> 5)

constexpr std::int32_t kShipSinking = 6;   // 6 sinking, 7 sunk, 8 doomed

bool idle_on_route(Ship *ship)
{
    return (ship->state == kShipIdle || ship->state == kShipWaiting) && !ship->military->bActive;
}

// Route ships lent to a fight. A route ship cycles through Ship::Update's states 1-3 (wait, load, unload) and only
// state 0 starts a mission, so the lent ship is set to 0 [live 2026-10-08: left in 1, its mission never ran and the
// ship stayed stuck]. When the mission ends, Ship::Update sets 0 and sends the ship to its own harbour, and
// NNavy::Military::Finish S 005ba190 has taken it off its route (NavyLink_UnlinkMilitaryRoute), which would end the
// route's sea street. So the mod's Ship::Update hook puts it back on its route in state 1, as Expedition::Finish and
// Ship::Update's state 4 do for an expedition's ship (NavyLink_LinkMovementRoute S 0053c3d0). Kept by the mod, not
// saved with the game; every peer runs the same updates, so it stays in lockstep.
struct LentShip {
    Ship *ship;
    NavyShipRoute *route;
};
LentShip g_lent[64];
int g_lentCount;

void lend(Ship *ship, NavyShipRoute *route)
{
    for (int i = 0; i < g_lentCount; ++i)
        if (g_lent[i].ship == ship) return;
    if (g_lentCount < 64) g_lent[g_lentCount++] = {ship, route};
}

void forget_lent(Ship *ship)
{
    for (int i = 0; i < g_lentCount; ++i)
        if (g_lent[i].ship == ship) g_lent[i] = g_lent[--g_lentCount];
}

// After a ship update: a lent ship whose mission has ended (back in state 0) returns to its route, unless it sank.
void return_lent(Ship *ship)
{
    if (ship->military->bActive || ship->state != kShipIdle) return;
    for (int i = 0; i < g_lentCount; ++i) {
        if (g_lent[i].ship != ship) continue;
        fn::NavyLink_LinkMovementRoute(ship, g_lent[i].route);
        ship->state = kShipWaiting;
        g_lent[i] = g_lent[--g_lentCount];
        return;
    }
}

bool route_ship(Harbor *home, Harbor *landing, std::int32_t player, Fight *fight, bool attacking, SeaLink *link)
{
    HarborExit *exit = fn::ai::navy::Harbor::FindExitConnectedTo(home, landing);
    if (!exit) return false;
    NavyShipRoute *route = fn::NLogic::ReferenceShipRoute::Resolve(&exit->route);
    if (!route) return false;
    Ship *ship;
    bool onRoute = fn::ai::navy::NavyShipRoute::HasPlayerEntry(route, player);
    if (onRoute) {
        ship = fn::ai::navy::NavyShipRoute::GetPlayerEntryOrFirst(route, player);
        bool waitingInvasion = attacking && invasion_ready(ship) && !ship->military->bActive;
        if (waitingInvasion) {
            link->invasion = true;
        } else if (idle_on_route(ship)) {
            link->routeIdle = true;
        } else {
            if (!fight) return false;   // outside a dispatch a busy ship never counts
            if (!ship->military->bActive || !carries(ship->military, fight)) return false;
        }
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
    bool defending = player == owner(target);
    if (defending ? !g_settings.defendersBySea : !g_settings.attackersBySea) return false;
    bool found = false;
    for (Harbor *landing : harbors()) {
        if (region(landing) != targetRegion || !is_landing(landing, player)) continue;
        for (Harbor *home : harbors()) {
            if (home->playerIdx != player || region(home) != buildingRegion) continue;
            std::int32_t d = distance(landing, target) + g_settings.crossingDistance + distance(home, building);
            if (d >= kAttackRange || (found && d >= best->distance)) continue;
            SeaLink link;
            if (!route_ship(home, landing, player, fight, !defending, &link)) continue;
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
        if (region(landing) != targetRegion || distance(landing, target) >= range + 1 || !is_landing(landing, player))
            continue;
        for (Harbor *home : harbors()) {
            SeaLink link;
            if (home->playerIdx == player && region(home) != targetRegion &&
                route_ship(home, landing, player, g_dispatchFight, true, &link))
                return true;
        }
    }
    return false;
}

// Military_IsEnemyTerritoryInRange S 00575850 (the attack button): also true for an own landing harbour in range.
bool SADK_CDECL territory_in_range(Building *target, std::int32_t *attacker)
{
    return TerritoryInRange::original(target, attacker) ||
           (g_settings.attackFromOwnLanding && own_landing_in_range(target, *attacker));
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
    if (!g_settings.defendersBySea) return DispatchDefenders::original(attack, connector, soldierFraction);
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
    } else if (link.invasion) {   // the invasion ship is on its route already; the fight starts its boarding
        fn::NavyLink_LinkMilitaryFight(connector->fight, link.ship);
    } else if (link.routeIdle) {   // the route's own ship: linked to the route already, so only its mission starts
        fn::NNavy::Military::Activate(link.ship->military);   // what NavyLink_LinkMilitaryRoute does last
        fn::NavyLink_LinkMilitaryFight(connector->fight, link.ship);
        link.ship->state = kShipIdle;   // state 0 picks the mission up at the next stop
        lend(link.ship, link.route);
    }
    // __thiscall on the connector: binds each soldier to connector->fight and to the ship.
    fn::NMilitary::AttackConnector::SendSoldiersFromBuilding(connector, building, count, link.ship);
}

// ---- Hook: the ship's mission ------------------------------------------------------------------------------------

constexpr std::int32_t kSailToLoading = 0;   // NNavy::Military states (docs/navy-and-military.md §5.3)
constexpr std::int32_t kWaitForCargo = 1;
constexpr std::int32_t kSailToLanding = 3;
constexpr std::int32_t kDisembark = 4;
constexpr std::int32_t kBoardReturning = 5;

// The ends of a route the game's own end-picking cannot handle: the end on the target's landmass belongs to `player`
// or to nobody (an own or a neutral landing), the other end is the player's. False otherwise (the game's own case,
// a landing owned by the defender), or when the target's landmass is not exactly one of the ends.
bool own_route_ends(NavyShipRoute *route, std::int32_t player, std::int32_t targetRegion, Harbor **home,
                    Harbor **landing)
{
    Harbor *a = fn::NLogic::ReferenceHarbor::Resolve(&route->harborA);
    Harbor *b = fn::NLogic::ReferenceHarbor::Resolve(&route->harborB);
    if (!a || !b) return false;
    bool aLands = region(a) == targetRegion, bLands = region(b) == targetRegion;
    if (aLands == bLands) return false;
    *landing = aLands ? a : b;
    *home = aLands ? b : a;
    return (*home)->playerIdx == player && ((*landing)->playerIdx == player || (*landing)->playerIdx == -1);
}

// ShipLostOnDefeat: an attacker's ship at the landing (state 5, boarding the soldiers coming back) sinks once the
// attack is lost, with whoever is aboard; soldiers still ashore are left to the game (or a retreat pickup). This
// holds for every attack by sea, the game's own included; ships carrying defenders are not affected, nor is a ship
// whose landing harbour is still its player's (an attack on a coastal position), nor a cancelled attack.
bool sink_after_defeat(NavyMission *m, Ship *ship)
{
    if (!g_settings.shipLostOnDefeat || m->state != kBoardReturning) return false;
    Fight *fight = m->fight.cachedFight;
    if (!fight || fight->attackerPlayer != ship->player->index || !battle_over(m)) return false;
    if (battle_outcome(m) != Outcome::lost || at_own_harbor(ship)) return false;
    fn::NNavy::Military::Finish(m);
    forget_lent(ship);   // it sinks at its next stop: not back on its route
    fn::NNavy::Ship::SinkImmediately(ship);
    sadk::log("attack by sea lost: ship %d sinks", ship->shipNumber);
    tell(ship, "!navalcombatfix_attack_lost_sunk", "Attack by sea lost: the ship sank");
    return true;
}

// NNavy::Military::Update S 005ba250. Its states 0 (sail to the loading end) and 3 (sail to the landing end) pick
// the end owned by the ship's player and by the fight's defender; for an own or a neutral landing (own_route_ends),
// the landing end is the one on the target's landmass. A mission without a fight is a pickup (retreat.cpp). The guard is
// the game's: the mission is active and the ship stands still (its step interpolator not running, movement state 0
// or 4).
bool update_mission(NavyMission *m)
{
    auto *ship = static_cast<Ship *>(m->ship);
    game::NNavy::Movement *mv = ship->movement;
    if (!m->bActive || (mv->state != 0 && mv->state != 4) || mv->base.interpolator.progress > 0.0f)
        return NavyMilitaryUpdate::original(m);
    if (!carries_fight(m)) return retreat_update(m);
    if (sink_after_defeat(m, ship)) return true;   // finished, as the game's state 7 returns
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

bool SADK_THISCALL navy_military_update(NavyMission *m) { return update_mission(m); }

// NNavy::Ship::Update S 005bb500: lent route ships go back on their route once their mission is over.
using ShipUpdate = sadk::Hook<fn::NNavy::Ship::Update>;
void SADK_FASTCALL ship_update(Ship *ship)
{
    ShipUpdate::original(ship);
    if (g_lentCount) return_lent(ship);
}

}  // namespace
}  // namespace navalcombatfix

bool combat_start()
{
    using namespace navalcombatfix;
    bool ok = ReachFactor::install(reach_factor) && TargetReachable::install(target_reachable) &&
              TerritoryInRange::install(territory_in_range) && DispatchAttackers::install(dispatch_attackers) &&
              DispatchDefenders::install(dispatch_defenders) && SendBySea::install(send_by_sea) &&
              NavyMilitaryUpdate::install(navy_military_update) && ShipUpdate::install(ship_update);
    sadk::log("%s", ok ? "combat by sea: soldiers cross through their own harbours" : "combat by sea NOT active");
    return ok;
}
