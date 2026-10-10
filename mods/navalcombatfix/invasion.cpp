// navalcombatfix, naval invasion: taking a neutral harbour where an enemy leaves no room for a colony (CONCEPT.md
// "Naval invasion"; docs/navy-and-military.md §7).
//
//   1. Scouting. An expedition that arrives at a free harbour without room for its colony building (landing.cpp, the
//      game's own placement test) reveals the area as usual, says "No Valid Position for Building found!" and turns
//      back, instead of waiting for orders that cannot succeed (the game's Expedition::Update S 005b8ac0 state 4).
//   2. "Prepare naval invasion", a 4th button on the ship-route buoy (the game uses slots 1-3 for its expedition
//      buttons, MenuSelection::SetSelectionKind S 00616f40 kind 0). Enabled when the route leads from an own harbour
//      to a neutral one the player has explored and that has no room for a colony. It sends the mod's own lockstep
//      command (kPrepareInvasionCommand), which every peer runs (nGame::System::HandleGameCommand S 007845a0 ignores
//      unknown ids, so the hook handles it): an idle ship is assigned to the route, the way the game starts an
//      expedition, and the expedition is put into the invasion states below.
//   3. The invasion is an expedition in states 100+. The state is the expedition's own saved int (Expedition::Store
//      S 005b7d30), so an invasion survives save and load. Loading reuses the game's steps (home harbour, unload,
//      GatherCargo: one soldier and the building's goods), then the ship waits at home.
//   4. An attack on the target's landmass uses the waiting ship (combat.cpp route_ship): the attackers board, it sails,
//      and only they land (NavyLink_UnlinkCargoSettler + SettlerMovement::DisembarkAt, as the game's state 6 does for
//      one soldier); the expedition soldier and the goods stay aboard.
//   5. Won (the fight's target is the player's): the survivors board again and the game's state 6 founds the colony;
//      the ship's military mission then takes them home. No room after all: the game's own failure path (message,
//      return, unload). Lost: ShipLostOnDefeat sinks the ship (Ship::ScheduleSinkingNoDelay S 005bb250, as the game's Lua
//      does), else the game's return (state 7) unloads the expedition at home.
// The button reuses the attack button's icon; its texts are plain English [TODO: own icon and translated texts].
#include "navy.hpp"

#include <sadkmod/game/sadk_noav/fn/NComm.hpp>
#include <sadkmod/game/sadk_noav/fn/NComm_Manager.hpp>
#include <sadkmod/game/sadk_noav/fn/NMap.hpp>
#include <sadkmod/game/sadk_noav/fn/nGame.hpp>
#include <sadkmod/game/sadk_noav/fn/nMenu.hpp>
#include <sadkmod/game/sadk_noav/fn/nUi.hpp>
#include <sadkmod/game/sadk_noav/fn/std_.hpp>

#include <cstring>

namespace navalcombatfix {
namespace {

using game::NNavy::Expedition;
using game::NSettlers::Settler;
using game::ai::player::Player;
using game::nMenu::ActionButton;

constexpr std::uint32_t kPrepareInvasionCommand = 0x20040;   // the game's commands are 0x20002..0x2002B
constexpr std::int32_t kInvasionAction = 31;                 // the game's button actions are 0..30
constexpr std::int32_t kAttackAction = 11;                   // Action_Attack_Begin: the icon the button borrows
constexpr std::int32_t kShipRouteMenu = 0;                   // MenuSelection kind of a selected ship route
constexpr std::int32_t kScoutRadius = 3;                     // explored cells around the harbour
constexpr std::int32_t kExpeditionReveal = 10;               // radius the game's expedition reveals on arrival
constexpr std::int32_t kMessageNavy = 6;                     // PlayerMessages type the expedition uses

// The game's expedition states (Expedition::Update) and the invasion's own (saved like them).
enum ExpeditionState : std::int32_t {
    kArrive = 4,
    kWaitForOrders = 5,
    kFoundColony = 6,
    kReturn = 7,
    kUnloadHome = 8,
    kInvSailHome = 100,   // to the route's own end
    kInvUnload,           // unload whatever is aboard
    kInvLoad,             // GatherCargo: the soldier and the building's goods
    kInvReady,            // loaded, waiting at home for an attack
    kInvBoard,            // an attack chose this ship: its attackers board
    kInvLand,             // sailing; on arrival the attackers land
    kInvBattle,           // waiting for the fight to end
    kInvReboard,          // won: the survivors board again, then kFoundColony
};
constexpr std::int32_t kShipMilitaryMission = 5;   // NNavy::Ship state
constexpr std::int32_t kMissionSailHome = 6;       // NNavy::Military state: sail to the other end, then unload

// ---- The route and its availability ------------------------------------------------------------------------------

// A route from one of `player`'s harbours (`home`) to a neutral one (`landing`).
bool invasion_ends(NavyShipRoute *route, std::int32_t player, Harbor **home, Harbor **landing)
{
    Harbor *a = fn::NLogic::ReferenceHarbor::Resolve(&route->harborA);
    Harbor *b = fn::NLogic::ReferenceHarbor::Resolve(&route->harborB);
    if (!a || !b) return false;
    if (a->playerIdx == player && b->playerIdx == -1) return *home = a, *landing = b, true;
    if (b->playerIdx == player && a->playerIdx == -1) return *home = b, *landing = a, true;
    return false;
}

bool scouted(Harbor *harbor, std::int32_t player)
{
    return !fn::NMap::Exploration::HasUnexploredInRadius(logic()->map->exploration, &harbor->posX, player,
                                                         kScoutRadius);
}

game::ai::navy::NavyShipRouteBackRef *back_ref(NavyShipRoute *route)
{
    return reinterpret_cast<game::ai::navy::NavyShipRouteBackRef *>(&route->selfLink);   // route+0x98, as the game
}

enum Reason : std::uint32_t { kReady, kNoNeutralHarbour, kNotScouted, kColonyFits, kNoShip, kReasonCount };
const char *const kReasonTexts[kReasonCount] = {
    "Prepare naval invasion",
    "Naval invasion: only from one of your harbours to a free one",
    "Naval invasion: send an expedition there first",
    "Naval invasion: there is room for a colony, found one with an expedition",
    "Naval invasion: no idle ship for this route, or one already on it",
};

Reason invasion_reason(NavyShipRoute *route, std::int32_t player)
{
    Harbor *home, *landing;
    if (!route || !invasion_ends(route, player, &home, &landing)) return kNoNeutralHarbour;
    if (!scouted(landing, player)) return kNotScouted;
    if (colony_fits(landing, player)) return kColonyFits;
    if (!fn::ai::navy::NavyShipRouteBackRef::CanAssignShip(back_ref(route), player)) return kNoShip;
    return kReady;
}

// ---- The button ----------------------------------------------------------------------------------------------------

using SetSelectionKind = sadk::Hook<fn::nMenu::MenuSelection::SetSelectionKind>;
using SetAction = sadk::Hook<fn::nMenu::ActionButton::SetAction>;
using SetAvailability = sadk::Hook<fn::nMenu::ActionButton::SetAvailability>;
using RefreshAvailability = sadk::Hook<fn::nMenu::ActionButton::RefreshAvailability>;
using ExecuteAction = sadk::Hook<fn::nMenu::ActionButton::ExecuteAction>;

std::int32_t local_player()
{
    auto *screen = static_cast<game::nMenu::Game *>(fn::nMenuSystem_GetActiveScreen_off3c());
    return screen->localPlayerEntry->index;
}

NavyShipRoute *selected_route()
{
    return fn::NLogic::ReferenceShipRoute::Resolve(&logic()->selection->shipRoute);
}

void set_tip(ActionButton *button, const char *text)
{
    sadk::msvc::string s = sadk::msvc::string::borrow(text);
    fn::nUi::Tip::SetDescription(&button->tip, &s, true);
}

// A selected ship route gets the button in its free 4th slot.
void SADK_THISCALL set_selection_kind(game::nMenu::MenuSelection *selection, std::int32_t *kind, char refresh)
{
    SetSelectionKind::original(selection, kind, refresh);
    if (*kind != kShipRouteMenu) return;
    game::nMenu::ActionButtonPanel &panel = selection->parentPanel->actionButtonPanel;
    std::int32_t action = kInvasionAction;
    fn::nMenu::ActionButton::SetAction(&panel.actionButtons[3], &action, true);
    fn::nMenu::ActionButtonPanel::LayoutVisibleButtons(&panel);
}

// The game's per-action tables (icon, name, failure texts) end at 30: the button is set up as the attack button
// and then gets its own action and texts.
void SADK_THISCALL set_action(ActionButton *button, std::int32_t *action, bool refresh)
{
    if (*action != kInvasionAction) return SetAction::original(button, action, refresh);
    std::int32_t borrowed = kAttackAction;
    SetAction::original(button, &borrowed, false);
    button->action = kInvasionAction;
    button->actionHigh = 0;
    set_tip(button, kReasonTexts[kReady]);
    if (refresh) fn::nMenu::ActionButton::RefreshAvailability(button);
}

void SADK_THISCALL set_availability(ActionButton *button, bool enabled, std::uint32_t reason)
{
    if (button->action != kInvasionAction) return SetAvailability::original(button, enabled, reason);
    button->action = kAttackAction;   // the look of an enabled / disabled button; the texts are ours
    SetAvailability::original(button, enabled, 0);
    button->action = kInvasionAction;
    set_tip(button, kReasonTexts[enabled || reason >= kReasonCount ? kReady : reason]);
}

void SADK_THISCALL refresh_availability(ActionButton *button)
{
    if (button->action != kInvasionAction) return RefreshAvailability::original(button);
    Reason reason = invasion_reason(selected_route(), local_player());
    fn::nMenu::ActionButton::SetAvailability(button, reason == kReady, reason);
}

// The press: the mod's command for the selected route, sent like the game's own ship-route commands
// (nGame::System::SendCommand_2001A S 00782d80).
void SADK_CDECL execute_action(std::int32_t *action)
{
    if (*action != kInvasionAction) return ExecuteAction::original(action);
    game::ai::game::Selection *selection = logic()->selection;
    game::NLogic::Unique &route = selection->shipRoute.unique;
    if (selection->kind != game::ai::game::ESelectionKind::ShipRoute || route.idHi < 0) return;
    game::NComm_Manager *manager = fn::NComm_GetManager();
    std::int32_t slot = fn::NComm_Manager_FindLocalPlayerSlot(manager);
    std::int32_t net = fn::NComm_Manager_NetworkVcall_30(manager);
    game::NComm::EventInt64_1Integer command;
    fn::NComm::EventInt64_1Integer::ctor(&command, kPrepareInvasionCommand, net, slot, route.idLo,
                                         static_cast<std::uint32_t>(route.idHi), local_player());
    fn::NComm_Manager::QueueGameCommand(manager, reinterpret_cast<game::NComm_Event *>(&command), false);
}

// ---- The command, on every peer ------------------------------------------------------------------------------------

using HandleGameCommand = sadk::Hook<fn::nGame::System::HandleGameCommand>;

void prepare_invasion(game::NComm::EventInt64_1Integer *command)
{
    game::NLogic::Unique id{};
    id.idLo = static_cast<std::uint32_t>(command->value64);
    id.idHi = static_cast<std::int32_t>(command->value64 >> 32);
    std::int32_t player = command->i0;
    NavyShipRoute *route = fn::ai::navy::ShipRouteList::FindByUnique(&logic()->navy->shipRoutes, &id);
    if (invasion_reason(route, player) != kReady) return;
    if (!fn::ai::navy::NavyShipRouteBackRef::AssignNearestIdleShip(back_ref(route), player)) return;
    // Assigning starts the ship's expedition (state 0, NavyLink 0053c010); it becomes an invasion.
    Ship *ship = fn::ai::navy::NavyShipRoute::GetPlayerEntryOrFirst(route, player);
    ship->expedition->state = kInvSailHome;
    sadk::log("player %d prepares a naval invasion with ship %d", player, ship->shipNumber);
}

void SADK_THISCALL handle_game_command(game::NComm::IEventHandler *handler, std::int32_t *event)
{
    auto *command = reinterpret_cast<game::NComm::EventInt64_1Integer *>(event);
    if (static_cast<std::uint32_t>(command->typeId) != kPrepareInvasionCommand)
        return HandleGameCommand::original(handler, event);
    prepare_invasion(command);
}

// ---- The ship ------------------------------------------------------------------------------------------------------

using ExpeditionUpdate = sadk::Hook<fn::NNavy::Expedition::Update>;

Ship *ship_of(Expedition *e) { return static_cast<Ship *>(e->ship); }

bool moving(game::NNavy::Movement *mv)
{
    return mv->base.interpolator.progress > 0.0f || (mv->state != 0 && mv->state != 4);
}

}  // namespace

// The game shows a message's text through Localization::GetText (nMenu::Messages::SetupSlot S 005f75a0, with the
// subject as " (subject)"); a key it does not know shows as "(MBT)<key>" once and as the key after. The mod's own
// keys are therefore entered into the table (Localization::translations, the std::map GetTextCStr S 004961f0 reads)
// before their first message. English only for now (README.md, to do).
void post(std::int32_t type, std::int32_t player, const char *key, const char *text, sadk::msvc::string *subject,
          std::int32_t *cell)
{
    if (text) {
        sadk::msvc::string k = sadk::msvc::string::borrow(key);   // copied into the map when it is new
        sadk::msvc::string *value =
            fn::ai::stl::MsvcTree::MapStrStr_Subscript(&fn::Localization_GetInstance()->translations, &k);
        fn::std_::string::assign(value, const_cast<char *>(text), static_cast<std::uint32_t>(std::strlen(text)));
    }
    sadk::msvc::string message = sadk::msvc::string::borrow(key);
    fn::PlayerMessages_SendToPlayer(type, player, &message, subject, cell);
}

void tell(Ship *ship, const char *key, const char *text)
{
    sadk::msvc::owned_string subject;
    fn::NNavy::Ship::GetNameKey(ship, &subject);
    post(kMessageNavy, ship->player->index, key, text, &subject, &ship->movement->base.currentCellX);
}

namespace {

// Pickup-style timers for the waits (not saved: after loading a game they start again).
struct Wait {
    Expedition *expedition;
    std::int32_t since;
};
Wait g_waits[32];
int g_waitCount;

bool waited_too_long(Expedition *e)
{
    std::int32_t now = logic()->tickCounter;
    for (int i = 0; i < g_waitCount; ++i)
        if (g_waits[i].expedition == e) return now - g_waits[i].since >= g_settings.pickupTimeout;
    if (g_waitCount < 32) g_waits[g_waitCount++] = {e, now};
    return false;
}

void stop_waiting(Expedition *e)
{
    for (int i = 0; i < g_waitCount; ++i)
        if (g_waits[i].expedition == e) g_waits[i] = g_waits[--g_waitCount];
}

// The mission's soldiers still aboard get off at the landing; the expedition's own soldier stays.
void land_attackers(Ship *ship)
{
    game::NLogic::ReferencesSettler &soldiers = ship->military->soldiers;
    for (void **it = soldiers.refs_first; it != soldiers.refs_last; ++it) {
        Settler *soldier = fn::ReferenceSettler_Resolve(*it);
        if (!soldier || !fn::Settler_IsAboardShip(soldier->movement)) continue;
        fn::NavyLink_UnlinkCargoSettler(ship, soldier);
        fn::ai::settlers::SettlerMovement::DisembarkAt(soldier->movement, ship);
    }
}

// A lost or cancelled invasion: the mission ends; the ship sinks (lost, ShipLostOnDefeat, at a harbour that is not
// its player's) or sails home and unloads the expedition's cargo.
void lose(Expedition *e, bool cancelled)
{
    Ship *ship = ship_of(e);
    stop_waiting(e);
    bool sinks = !cancelled && g_settings.shipLostOnDefeat && !at_own_harbor(ship);
    if (!sinks) fn::NNavy::Military::Finish(ship->military);   // a sinking ship keeps its mission until it is
                                                               // deleted (combat.cpp, sink_after_defeat)
    if (cancelled) {
        e->state = kReturn;   // the game's return: release, sail home, unload
        sadk::log("naval invasion called off: ship %d returns", ship->shipNumber);
        tell(ship, "!navalcombatfix_invasion_cancelled", "Naval invasion called off: the ship returns home");
    } else if (sinks) {
        fn::NNavy::Expedition::ReleaseAndDeactivate(e);
        fn::NNavy::Ship::ScheduleSinkingNoDelay(ship);
        sadk::log("naval invasion lost: ship %d sinks", ship->shipNumber);
        tell(ship, "!navalcombatfix_invasion_lost_sunk", "Naval invasion lost: the ship sank");
    } else {
        e->state = kReturn;   // the game's return: release, sail home, unload
        sadk::log("naval invasion lost: ship %d returns", ship->shipNumber);
        tell(ship, "!navalcombatfix_invasion_lost", "Naval invasion lost: the ship returns home");
    }
}

bool invasion_update(Expedition *e)
{
    Ship *ship = ship_of(e);
    game::NNavy::Movement *mv = ship->movement;
    NavyMission *m = ship->military;
    switch (e->state) {
    case kInvSailHome:
        fn::NNavy::Movement::MoveToHarbor(mv, fn::NNavy::Expedition::ChooseStartHarbor(e));
        e->state = kInvUnload;
        break;
    case kInvUnload:
        if (!fn::NavyCargo_UnloadStep(ship->cargo)) e->state = kInvLoad;
        break;
    case kInvLoad:
        if (fn::NNavy::Expedition::GatherCargo(e)) {
            e->state = kInvReady;
            tell(ship, "!navalcombatfix_invasion_ready", "Naval invasion ready: the ship waits for an attack");
        }
        break;
    case kInvReady:
        if (m->bActive && carries_fight(m)) e->state = kInvBoard;   // combat.cpp linked an attack
        break;
    case kInvBoard:
        if (fn::NNavy::Military::BoardSettlersAtHarbor(m, false) || waited_too_long(e)) {
            stop_waiting(e);
            if (m->soldiers.refs_first == m->soldiers.refs_last) {   // nobody came: wait for the next attack
                fn::NNavy::Military::Finish(m);
                e->state = kInvReady;
                break;
            }
            fn::NNavy::Movement::SailToOppositeRouteEnd(mv);
            e->state = kInvLand;
        }
        break;
    case kInvLand:
        land_attackers(ship);
        e->state = kInvBattle;
        break;
    case kInvBattle:
        if (!battle_over(m)) break;
        if (Outcome outcome = battle_outcome(m); outcome != Outcome::won) {   // a target that is gone counts as taken
            lose(e, outcome == Outcome::cancelled);
            break;
        }
        e->state = kInvReboard;
        break;
    case kInvReboard:
        if (fn::NNavy::Military::BoardSettlersAtHarbor(m, true) || waited_too_long(e)) {
            stop_waiting(e);
            e->state = kFoundColony;   // the game founds the colony on the next update
        }
        break;
    default:
        break;
    }
    return false;
}

// The game's arrival (state 4): at a free harbour without room for a colony, report and turn back. At an enemy
// harbour without a garrison (takeover.cpp), wait for orders as at a free harbour, where the game would say "Harbor
// is already captured!".
bool scout(Expedition *e)
{
    Ship *ship = ship_of(e);
    Harbor *landing = fn::NLogic::ReferenceHarbor::Resolve(&ship->movement->targetHarbor);
    std::int32_t player = ship->player->index;
    if (harbor_open_to(landing, player)) {
        fn::ai::map::MapModifier::ExploreArea(logic()->map->modifier, &landing->posX, kExpeditionReveal,
                                              &ship->player->index);
        tell(ship, "!Ship waiting for Orders");
        e->state = kWaitForOrders;
        return false;
    }
    if (!landing || landing->playerIdx != -1 || colony_fits(landing, player)) return ExpeditionUpdate::original(e);
    fn::ai::map::MapModifier::ExploreArea(logic()->map->modifier, &landing->posX, kExpeditionReveal,
                                          &ship->player->index);
    tell(ship, "!No Valid Position for Building found!");
    e->state = kReturn;
    return false;
}

bool found_colony_game(Expedition *e) { return ExpeditionUpdate::original(e); }

// State 6, the game's founding with the harbour takeover (takeover.cpp). No room even with the takeover: the game's
// own failure (message, return).
bool found(Expedition *e, bool invasion)
{
    TakeoverResult result = found_colony(e, invasion, found_colony_game);
    if (result != TakeoverResult::no_room) return result == TakeoverResult::founded;
    tell(ship_of(e), "!No Valid Position for Building found!");
    e->state = kReturn;
    return false;
}

bool SADK_THISCALL expedition_update(Expedition *e)
{
    if (!e->bActive || moving(ship_of(e)->movement)) return ExpeditionUpdate::original(e);
    NavyMission *m = ship_of(e)->military;
    switch (e->state) {
    case kArrive:
        return scout(e);
    case kWaitForOrders:
        // The game turns back from an owned harbour ("captured"); an enemy's without a garrison stays open.
        if (harbor_open_to(fn::NLogic::ReferenceHarbor::Resolve(&ship_of(e)->movement->targetHarbor),
                           ship_of(e)->player->index))
            return false;
        return ExpeditionUpdate::original(e);
    case kFoundColony:
    case kUnloadHome:
        if (m->bActive) {
            // An invasion ending in the game's states: after the colony, the mission takes the attackers home;
            // after a return, they were unloaded with everything else.
            std::int32_t state = e->state;
            if (!(state == kFoundColony ? found(e, true) : ExpeditionUpdate::original(e))) return false;
            e->bActive = 0;   // the invasion is over (Expedition::Finish leaves the flag set)
            if (state == kFoundColony) {
                tell(ship_of(e), "!navalcombatfix_invasion_won", "Naval invasion won: colony founded");
                ship_of(e)->state = kShipMilitaryMission;
                m->state = kMissionSailHome;
                return false;   // the ship stays in its military state
            }
            fn::NNavy::Military::Finish(m);
            return true;
        }
        return e->state == kFoundColony ? found(e, false) : ExpeditionUpdate::original(e);
    default:
        return e->state >= kInvSailHome ? invasion_update(e) : ExpeditionUpdate::original(e);
    }
}

}  // namespace

bool invasion_ready(Ship *ship)
{
    return ship->expedition->bActive && ship->expedition->state == kInvReady;
}

void invasion_forget_ship(Ship *ship) { stop_waiting(ship->expedition); }

}  // namespace navalcombatfix

bool invasion_start()
{
    using namespace navalcombatfix;
    bool ok = SetSelectionKind::install(set_selection_kind) && SetAction::install(set_action) &&
              SetAvailability::install(set_availability) && RefreshAvailability::install(refresh_availability) &&
              ExecuteAction::install(execute_action) && HandleGameCommand::install(handle_game_command) &&
              ExpeditionUpdate::install(expedition_update);
    sadk::log("%s", ok ? "naval invasion: scouting, \"Prepare naval invasion\", invasion ships" : "naval invasion NOT active");
    return ok;
}
