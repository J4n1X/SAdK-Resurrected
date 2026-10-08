// navalcombatfix, retreat: soldiers left without a home on the far side are picked up by a ship of their player
// (docs/navy-and-military.md §4 for the game's rules, §7 "Retreat pickup" for this change).
//
// A soldier without a home building goes to state 3 (Settler::StopAndSetState3 S 00656740) and runs MoveToHome
// (S 007776f0). When that ends without a building within 2 cells, NSettlers::Settler::Update S 00656ec0 kills it
// (StartDying S 00656760). Across the water a home is only reachable through a sea street, which exists only while
// both harbours of the route belong to the player (NavyShipRoute::IsStreetValidForPlayer S 005b6d80). Destroying
// one's last military building on the far side removes the harbour flag there with the territory (the harbour turns
// neutral, Harbor -1 by S 005b5370), so its soldiers die.
//
// The rule (maintainer): if a harbour on the soldier's landmass is neutral, the territory at its flag owned by nobody,
// and one of the player's ships is ready for the route from it to one of the player's harbours, that ship picks the
// soldier up instead. A harbour whose cell went to an enemy is not used.
//
// The pickup is the game's own sea transport (NNavy::Military) without a fight:
//   1. the ship is linked to the route, sails to the neutral harbour and waits there in state 2, where the game's
//      Update boards the soldiers standing on the harbour;
//   2. each soldier, linked to the ship, walks there through the states the game uses for soldiers coming back from a
//      fight (Soldier::Update S 006594a0, 0x21 -> 0x31 -> 0x32);
//   3. when all are aboard (or the wait times out), state 3 sails to the other end of the route (for a fight, state 3
//      would sail to the defender's harbour and read a fight there is none of);
//   4. the game's state 7 unloads; the soldiers, a home reachable again, walk into a building of the player.
#include "navy.hpp"

namespace navalcombatfix {
namespace {

using StartDying = sadk::Hook<fn::NSettlers::Settler::StartDying>;

constexpr std::int32_t kWaitingForSoldiers = 2;   // NNavy::Military: board the soldiers standing on the harbour
constexpr std::int32_t kSailHome = 3;             // for a fight: sail to the landing; a pickup sails home instead
constexpr std::int32_t kUnload = 7;
constexpr std::int32_t kLeavingMap = 3;           // NSettlers::Settler state: MoveToHome running (see above)
constexpr std::int32_t kWalkToShip = 0x21;        // Soldier::Update: walk to the linked ship's harbour
constexpr std::int32_t kNobody = -1;              // owner of a neutral harbour / of nobody's territory

// ---- Pickup bookkeeping ------------------------------------------------------------------------------------------
//
// Pickup missions waiting at their harbour, with the tick they started waiting. Kept by the mod, not saved with the
// game: after loading a game the wait starts again. Every peer runs the same updates, so it stays in lockstep.

struct Pickup {
    NavyMission *mission;
    std::int32_t since;
};
Pickup g_pickups[64];
int g_pickupCount;

// The entry of a waiting mission; a mission seen for the first time starts waiting now. Null when the table is full
// (that mission then waits for its soldiers without a timeout).
Pickup *pickup(NavyMission *m)
{
    for (int i = 0; i < g_pickupCount; ++i)
        if (g_pickups[i].mission == m) return &g_pickups[i];
    if (g_pickupCount == 64) return nullptr;
    g_pickups[g_pickupCount] = {m, logic()->tickCounter};
    return &g_pickups[g_pickupCount++];
}

void forget_pickup(NavyMission *m)
{
    for (int i = 0; i < g_pickupCount; ++i)
        if (g_pickups[i].mission == m) g_pickups[i] = g_pickups[--g_pickupCount];
}

// ---- Finding the ship --------------------------------------------------------------------------------------------

bool same_harbor(game::NLogic::ReferenceHarbor &ref, Harbor *h)
{
    return ref.unique.idHi >= 0 && ref.unique.idLo == static_cast<std::uint32_t>(h->uniqueIdLo) &&
           ref.unique.idHi == h->uniqueIdHi;
}

// Who owns the territory at the harbour's flag cell (NMap::Territory, one int per cell). The harbour itself is -1
// both when its ground became nobody's and when an enemy took it; only the territory tells the two apart.
std::int32_t territory_owner(Harbor *h)
{
    auto *territory = static_cast<game::NMap::Territory *>(logic()->map->pTerritory);
    return territory->cellsFirst[h->posY * *var::g_MapWidth + h->posX];
}

bool is_neutral(Harbor *h) { return h->playerIdx == kNobody && territory_owner(h) == kNobody; }

// A ship of `player` already waiting at `landing` for soldiers: how a second stranded soldier at the same harbour
// joins the ship the first one called.
Ship *waiting_ship(Harbor *landing, std::int32_t player)
{
    for (Ship *ship : ships()) {
        NavyMission *m = ship->military;
        if (ship->player->index == player && m->bActive && !carries_fight(m) && m->state == kWaitingForSoldiers &&
            same_harbor(ship->movement->targetHarbor, landing))
            return ship;
    }
    return nullptr;
}

// An idle ship of `player` for a route from one of the player's harbours to `landing`, and the exit of that route
// (to link the ship to it). One ship per player per route: FindNearestIdleShipAtHarborExit S 005b3450 finds none on
// a route the player already serves.
Ship *idle_ship_for(Harbor *landing, std::int32_t player, HarborExit **exitOut)
{
    for (Harbor *home : harbors()) {
        if (home->playerIdx != player) continue;
        HarborExit *exit = fn::ai::navy::Harbor::FindExitConnectedTo(home, landing);
        if (!exit) continue;
        if (Ship *ship = fn::NNavy::System::FindNearestIdleShipAtHarborExit(logic()->navy, player, &exit->posX)) {
            *exitOut = exit;
            return ship;
        }
    }
    return nullptr;
}

// Sends an idle ship to wait at `landing`. NavyLink_LinkMilitaryRoute S 0053c0d0 puts it on the route and activates
// its mission (state 0); it then sails to the neutral harbour and waits there in state 2.
void send_to_wait(Ship *ship, HarborExit *exit, Harbor *landing)
{
    fn::NavyLink_LinkMilitaryRoute(fn::NLogic::ReferenceShipRoute::Resolve(&exit->route), ship);
    fn::NNavy::Movement::MoveToHarbor(ship->movement, landing);
    ship->military->state = kWaitingForSoldiers;
}

// The ship to pick up a soldier of `player` standing at `cell`: at the nearest neutral harbour of the soldier's
// landmass that has one, the ship already waiting there, else an idle one sent there.
Ship *pickup_ship(std::int32_t player, std::int32_t *cell)
{
    std::int32_t soldierRegion = region(cell);
    Harbor *bestLanding = nullptr;
    HarborExit *bestExit = nullptr;   // set only when the ship still has to be sent
    Ship *bestShip = nullptr;
    std::int32_t bestDistance = 0;
    for (Harbor *landing : harbors()) {
        if (!is_neutral(landing) || region(landing) != soldierRegion) continue;
        std::int32_t d = distance(landing, cell);
        if (bestLanding && d >= bestDistance) continue;
        HarborExit *exit = nullptr;
        Ship *ship = waiting_ship(landing, player);
        if (!ship) ship = idle_ship_for(landing, player, &exit);
        if (!ship) continue;
        bestLanding = landing, bestExit = exit, bestShip = ship, bestDistance = d;
    }
    if (bestShip && bestExit) send_to_wait(bestShip, bestExit, bestLanding);
    return bestShip;
}

// ---- Hook --------------------------------------------------------------------------------------------------------

// A soldier the game is about to kill only for having nowhere to go: healthy, in state 3, on no ship.
bool stranded_soldier(game::NSettlers::Settler *settler)
{
    return settler->state == kLeavingMap &&
           settler->property->settlerType == game::ai::properties::ESettlerType::Soldier &&
           reinterpret_cast<game::NSettlers::Soldier *>(settler)->health > 0 && settler->ship.unique.idHi < 0;
}

// Settler::StartDying S 00656760: a ship picks the stranded soldier up instead, when the rule allows.
void SADK_THISCALL start_dying(game::NSettlers::Settler *settler)
{
    if (g_settings.retreatPickup && stranded_soldier(settler)) {
        std::int32_t *cell = &settler->movement->cellX;   // {cellX, cellY}
        if (Ship *ship = pickup_ship(settler->ownerPlayer->index, cell)) {
            fn::NavyLink_LinkMilitarySoldier(settler, ship);   // as AttackConnector::AssignBestSoldiers does
            settler->state = kWalkToShip;
            return;
        }
    }
    StartDying::original(settler);
}

}  // namespace

// NNavy::Military::Update for a mission without a fight, i.e. a pickup (called from combat.cpp's hook, past the
// game's guard): state 2 is the game's (board the soldiers standing on the harbour) until all are aboard or the wait
// times out; state 3 sails to the other end of the route; 7 is the game's again.
bool retreat_update(NavyMission *m)
{
    if (m->state == kWaitingForSoldiers) {
        Pickup *p = pickup(m);
        if (!p || logic()->tickCounter - p->since < g_settings.pickupTimeout) return NavyMilitaryUpdate::original(m);
        m->state = kSailHome;   // leave with whoever is aboard
    }
    forget_pickup(m);
    if (m->state != kSailHome) return NavyMilitaryUpdate::original(m);
    fn::NNavy::Movement::SailToOppositeRouteEnd(static_cast<Ship *>(m->ship)->movement);
    m->state = kUnload;
    return false;
}

}  // namespace navalcombatfix

bool retreat_start()
{
    bool ok = navalcombatfix::StartDying::install(navalcombatfix::start_dying);
    sadk::log("%s", ok ? "retreat: ships pick up soldiers left with nowhere to go" : "retreat NOT active");
    return ok;
}
