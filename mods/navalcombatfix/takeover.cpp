// navalcombatfix, HarborMustHaveGarrison: an expedition may take an enemy harbour that no military building guards
// (CONCEPT.md "Harbour garrison"; docs/navy-and-military.md §7).
//
// Garrison. A harbour is garrisoned when a street path on land joins its flag to the entrance flag of a finished
// military building of its owner whose territory range reaches the harbour flag. The game keeps a network id per flag (NLogic_UniqueArray40_IsEqualAt S 00663d90),
// but both of its kinds count sea streets (NNet::Street::ctor S 00669cd0 marks type 3 usable for both), so the
// test walks the flag links itself, the way NNet_CollectConnectedFlags S 00666250 does, and skips sea streets.
// "Military building": the territory buildings (NVillage::System+0x3c), the list the game's flag stripes and attacks
// use; "finished": both construction remainders at 0, the game's supply search's test (BuildingList_FindNearestConnected
// S 00557ef0). The garrison may be empty (maintainer).
//
// Arrival. Where the game says "Harbor is already captured!" (Expedition::Update S 005b8ac0 states 4 and 5), an
// ungarrisoned enemy harbour gets "Ship waiting for Orders" and the expedition waits for the Found colony order, as
// at a free harbour (the order only needs state 5: NavyShipRouteBackRef::CanFoundColony S 005baab0). Garrisoned
// meanwhile: the game's "captured" path.
//
// Takeover. Founding (state 6) needs, in this order: a building position (FindBuildingPosition S 005b7e50, the
// placement test GameQuery::CanPlaceBuildingAt S 0052fbe0), an unowned harbour, then the colonist's flag on the
// harbour cell (Harbor::PlaceFlagAndRevealExitsForCellOwner S 005b5670) and a street from it to the guard post's
// flag (StreetPlanner::BuildStreet S 006636e0 / ExtendTo S 00663bf0: owned cells that are not border cells,
// GameQuery::CanStreetPassCell S 0052fb10, AStarStreet::GetStepCost S 00776500; a border cell has a neighbour of
// another owner, MapCellUpdater::IsTerritoryBorderCell S 0067b5a0). The takeover gives the colonist exactly that land
// (maintainer): the guard post's footprint (FootprintIter S 0055abf0 / 0055ac80) and entrance flag, and the street
// path with every neighbour of its cells, harbour flag included. The path is the game's own street search, run while
// the colonist holds the whole search area for a moment; the land claim is then checked once more with exactly the
// claimed cells. These tests write the territory grid and refresh the border bits and the construction map, then
// restore all of it.
// The real claim writes the same grid cells and runs the game's territory-change update (MapModifier::
// OnTerritoryChangedAt S 00673a50: border bits, construction map, foreign streets removed, buildings outside their
// land marked). The enemy's harbour flag no longer stands on its owner's land, which the game punishes every tick
// (NNet::System::Update S 00665ef0 -> RemoveFlag S 00665c10); the takeover removes it at once, so the harbour is
// free (playerIdx -1, S 005b5370) when the game's state 6 runs. While state 6 runs, the guard post goes where the
// takeover found room, and after the game places it (PlaceExpeditionBuilding S 0055a820, whose new territory source
// recomputes the land around it) the claimed cells are given back to the colonist, so the harbour and the street can
// follow. From then on the game's territory rules decide.
//
// A naval invasion's founding (invasion.cpp, a harbour that was free when the invasion was prepared) takes the same
// way when a third player holds the harbour without a garrison, or contests the land around it (maintainer).
#include "navy.hpp"

#include <sadkmod/game/sadk_noav/fn/NMap.hpp>
#include <sadkmod/game/sadk_noav/fn/NNet.hpp>

#include <algorithm>
#include <unordered_set>
#include <vector>

namespace navalcombatfix {
namespace {

using game::NNavy::Expedition;
using game::NNet::Flag;
using game::NNet::FlagLink;
using game::ai::map::MapPos;

constexpr std::int32_t kSeaStreet = 3;   // NNet::Street::streetType of a sea street (NavyShipRoute::UpdateSeaStreet S 005b71d0)
constexpr std::int32_t kNobody = -1;

Ship *ship_of(Expedition *e) { return static_cast<Ship *>(e->ship); }
Harbor *target_harbor(Expedition *e) { return fn::NLogic::ReferenceHarbor::Resolve(&ship_of(e)->movement->targetHarbor); }

// ---- Garrison ------------------------------------------------------------------------------------------------------

bool finished(Building *b)
{
    return b->construction->remainingA <= 0.0f && b->construction->remainingB <= 0.0f;
}

// The harbour flag lies within the building's territory range: NVillage::Military::GetTerritoryRange S 0055fca0, the
// radius TerritoryUpdater::Activate S 00565350 gives the building's territory source (the type's range plus the
// owner's bonuses). A building far away does not guard the harbour, however long its street (maintainer).
bool within_range(Building *b, Harbor *h)
{
    return distance(h, b) <= fn::NVillage::Military::GetTerritoryRange(b->military);
}

Flag *harbor_flag(Harbor *h)
{
    return static_cast<Flag *>(fn::NNet::System::FindFlagAt(logic()->net, static_cast<std::uint32_t>(h->playerIdx),
                                                            &h->posX, 0, 0));
}

bool garrisoned(Harbor *h)
{
    Flag *start = h->playerIdx == kNobody ? nullptr : harbor_flag(h);
    if (!start) return false;
    std::unordered_set<Flag *> guards;
    for (Building *b : territory_buildings())
        if (owner(b) == h->playerIdx && finished(b) && within_range(b, h))
            if (Flag *f = fn::NLogic::ReferenceFlag::Resolve(&b->entranceFlagRef)) guards.insert(f);
    std::unordered_set<Flag *> seen{start};
    std::vector<Flag *> todo{start};
    while (!todo.empty()) {
        Flag *flag = todo.back();
        todo.pop_back();
        if (guards.count(flag)) return true;
        for (FlagLink *link = flag->linksFirst; link != flag->linksLast; ++link) {
            game::NNet::Street *street = link->street.cachedStreet;
            if (!street || street->streetType == kSeaStreet) continue;
            Flag *next = fn::NLogic::ReferenceFlag::Resolve(&link->otherFlag);
            if (next && seen.insert(next).second) todo.push_back(next);
        }
    }
    return false;
}

bool enemies(std::int32_t a, std::int32_t b)
{
    return fn::ai::player::Player::IsEnemyOf(player_entry(a), player_entry(b));
}

// ---- The territory grid --------------------------------------------------------------------------------------------

game::ai::map::MapModifier *modifier() { return logic()->map->modifier; }
std::int32_t *territory_cells() { return static_cast<game::NMap::Territory *>(logic()->map->pTerritory)->cellsFirst; }
std::int32_t cell_index(const MapPos &c) { return c.y * *var::g_MapWidth + c.x; }
bool on_map(const MapPos &c) { return c.x >= 0 && c.y >= 0 && c.x < *var::g_MapWidth && c.y < *var::g_MapHeight; }
std::int32_t hex_distance(MapPos a, MapPos b) { return distance(&a.x, &b.x); }

MapPos step(MapPos c, std::int32_t dir)
{
    fn::ai::map::MapPos::StepDirection(&c, dir, 1);
    return c;
}

// A set of cells given to one player, and what they held before.
struct Claim {
    std::vector<MapPos> cells;
    std::vector<std::int32_t> before;
    MapPos centre;
    std::int32_t radius = 0;   // every cell lies within this distance of centre
};

void add(Claim &claim, MapPos c)
{
    if (!on_map(c)) return;
    for (const MapPos &o : claim.cells)
        if (o.x == c.x && o.y == c.y) return;
    claim.cells.push_back(c);
    claim.radius = std::max(claim.radius, hex_distance(claim.centre, c));
}

// The cell and its 6 neighbours: a street cell that is not a border cell.
void add_with_ring(Claim &claim, MapPos c)
{
    add(claim, c);
    for (std::int32_t dir = 0; dir < 6; ++dir) add(claim, step(c, dir));
}

// Border bits and construction map around the claim, recomputed at once (the game's MapUpdateBatch may defer the
// construction map while a batch is open: InvalidateConstructionRadius S 005322b0).
void refresh(const Claim &claim)
{
    std::int32_t r = claim.radius + 2;   // upper bounds exclusive (S 0067b910 loops x < x1)
    fn::ai::map::MapCellUpdater::RefreshTerritoryBorderBits(&modifier()->cellUpdater, claim.centre.x - r,
                                                           claim.centre.y - r, claim.centre.x + r + 1,
                                                           claim.centre.y + r + 1);
    fn::ai::map::MapModifier::RecomputeConstructionMapRadius(modifier(), claim.radius + 4, 0, 6, 0, claim.centre.x,
                                                             claim.centre.y);
}

void write(Claim &claim, std::int32_t player)
{
    std::int32_t *cells = territory_cells();
    claim.before.clear();
    for (const MapPos &c : claim.cells) {
        claim.before.push_back(cells[cell_index(c)]);
        cells[cell_index(c)] = player;
    }
}

void restore(Claim &claim)
{
    std::int32_t *cells = territory_cells();
    for (std::size_t i = 0; i < claim.cells.size(); ++i) cells[cell_index(claim.cells[i])] = claim.before[i];
    refresh(claim);
}

// ---- The founding's tests, as the game runs them -------------------------------------------------------------------

struct Colony {
    Expedition *expedition;
    Harbor *harbor;
    std::int32_t player;
    std::int32_t type;            // the expedition building (ShipConfig::GetExpeditionBuilding)
    std::int32_t sizeFlags;       // its BuildingProperty::size (footprint shape)
    std::int32_t searchRadius;    // territoryRange - 1, FindBuildingPosition's rings
    std::int32_t landmass;
};

MapPos harbor_cell(const Colony &c) { return {c.harbor->posX, c.harbor->posY}; }

constexpr std::int32_t kKeepClearOfTerritory = 0x40;   // size bit: no territory building within 4 cells
constexpr std::int32_t kKeepClearRadius = 4;

// The territory buildings HasNoTerritoryBuildingWithinRadius4 S 0052dc30 finds around `pos`: the building on each
// cell within 4 cells (FindBuildingAtOrNearest radius 0) whose type gives territory, construction sites included.
std::vector<Building *> territory_buildings_near(MapPos pos)
{
    std::vector<Building *> found;
    for (std::int32_t y = pos.y - kKeepClearRadius - 1; y <= pos.y + kKeepClearRadius + 1; ++y)
        for (std::int32_t x = pos.x - kKeepClearRadius - 1; x <= pos.x + kKeepClearRadius + 1; ++x) {
            MapPos cell{x, y};
            if (!on_map(cell) || hex_distance(pos, cell) > kKeepClearRadius) continue;
            Building *b = fn::NVillage::System::FindBuildingAtOrNearest(logic()->village, &cell.x, 0);
            if (b && b->property->territoryRange > 0 && std::find(found.begin(), found.end(), b) == found.end())
                found.push_back(b);
        }
    return found;
}

// The game's placement test for the guard post at `pos` (FindBuildingPosition's arguments). With `blockers`, a
// position the test refuses only because of territory buildings within 4 cells also passes when every one of them
// is an enemy's; they are returned for destruction (maintainer). "Only because of": the same test with the size bit
// 0x40 cleared, the only thing that brings in the 4-cell rule (CanPlaceBuildingAt S 0052fbe0), unless clearing it
// leaves 8 or 0x10, sizes the test compares for equality.
bool placement_ok(const Colony &c, MapPos pos, std::vector<Building *> *blockers = nullptr)
{
    auto *colonist = reinterpret_cast<std::uint32_t *>(&player_entry(c.player)->index);
    game::ai::game::GameQuery *query = logic()->gameQuery;
    if (fn::ai::game::GameQuery::CanPlaceBuildingTypeAt(query, c.type, &pos.x, expedition_placement_player(), 0,
                                                        colonist, 1))
        return true;
    std::uint32_t size = static_cast<std::uint32_t>(c.sizeFlags) & ~static_cast<std::uint32_t>(kKeepClearOfTerritory);
    if (!blockers || !(c.sizeFlags & kKeepClearOfTerritory) || size == 8 || size == 0x10) return false;
    if (!fn::ai::game::GameQuery::CanPlaceBuildingAt(query, &size, &pos.x, expedition_placement_player(), 0, colonist,
                                                     1))
        return false;
    std::vector<Building *> nearby = territory_buildings_near(pos);
    for (Building *b : nearby)
        if (!enemies(owner(b), c.player)) return false;
    *blockers = std::move(nearby);
    return !blockers->empty();
}

// The game's street search from the harbour flag to the guard post's flag (StreetPlanner::ExtendTo S 00663bf0 runs
// NMap::AStar::FindPath and BuildPath on the navy's planner's AStarStreet the same way; Generic_SetLink4C S 00776160
// sets the player, the street type and the path so far). The search object is the navy's own, as state 6 uses it
// right after; its fields are restored. `path` gets the cells, both ends included.
bool street_path(const Colony &c, MapPos to, std::vector<MapPos> &path)
{
    game::NLogic::AStarStreet *search = logic()->navy->pStreetPlanner->search;
    if (!search) return false;
    // AStarStreet starts with its NMap::AStar base (+0, 0x48 bytes; the sourcemap keeps it as raw bytes because two
    // types are named AStar).
    auto *astar = reinterpret_cast<game::NMap::AStar *>(search);
    game::NLogic::AStarStreet saved = *search;
    MapPos from = harbor_cell(c);
    sadk::msvc::vector<MapPos> soFar{0, &from, &from + 1, &from + 1};   // the planner's path so far: the start
    search->playerIdx = c.player;
    search->mode = 0;
    search->pathSoFar = reinterpret_cast<game::ai::stl::MsvcVector *>(&soFar);
    search->allowedStreet.idLo = 0xffffffff;   // no street may be crossed
    search->allowedStreet.idHi = -1;
    fn::NMap::AStar::FindPath(astar, &from.x, &to.x, 0);
    bool found = astar->state == 2;
    if (found) {
        sadk::msvc::vector<MapPos> cells{};
        fn::NMap::AStar::BuildPath(astar, &cells, 0);
        path.assign(cells.begin(), cells.end());
        if (cells.first) sadk::game_free(cells.first);
        path.push_back(from);
        path.push_back(to);
    }
    search->playerIdx = saved.playerIdx;
    search->mode = saved.mode;
    search->pathSoFar = saved.pathSoFar;
    search->allowedStreet = saved.allowedStreet;
    return found;
}

// The cells founding at `pos` needs (see the top).
Claim needed_land(const Colony &c, MapPos pos, const std::vector<MapPos> &path)
{
    Claim claim;
    claim.centre = harbor_cell(c);
    game::ai::village::FootprintIter it{};
    fn::ai::village::FootprintIter::Init(&it, &pos.x, c.sizeFlags);
    do add(claim, {it.posX, it.posY});
    while (fn::ai::village::FootprintIter::Next(&it));
    for (const MapPos &cell : path) add_with_ring(claim, cell);
    return claim;
}

// FindBuildingPosition's candidates, in its order: its first MapRingIterator_Next skips the harbour cell; each ring r
// (1 .. territoryRange - 1) starts r steps in direction 4 from the harbour and is walked step-then-test, r steps per
// direction 0..5, so it ends on its start cell. A candidate is on the harbour's landmass, with its entrance (one step
// in direction 1) more than one cell from the harbour.
template <class F>
bool for_each_candidate(const Colony &c, F &&f)
{
    MapPos h = harbor_cell(c), start = h;
    for (std::int32_t ring = 1; ring <= c.searchRadius; ++ring) {
        start = step(start, 4);
        MapPos pos = start;
        for (std::int32_t dir = 0; dir < 6; ++dir) {
            for (std::int32_t s = 0; s < ring; ++s) {
                pos = step(pos, dir);
                if (on_map(pos) && region(pos.x, pos.y) == c.landmass && hex_distance(step(pos, 1), h) > 1 && f(pos))
                    return true;
            }
        }
    }
    return false;
}

// ---- The plan and its hooks ----------------------------------------------------------------------------------------

struct Plan {
    Expedition *expedition = nullptr;
    MapPos position{};
    Claim land;
    std::vector<Building *> blockers;   // enemy territory buildings within 4 cells of the position, to destroy
};
Plan g_plan;   // set only while the game's state 6 runs for a takeover

// A position for the colony and the land it needs. With `destroy`, a position blocked only by enemy territory
// buildings within 4 cells counts too (found_colony tries without first).
bool plan(const Colony &c, Plan &out, bool destroy)
{
    // The search area: FindBuildingPosition's rings and two more, so a path may go round the guard post.
    Claim area;
    area.centre = harbor_cell(c);
    for (std::int32_t y = area.centre.y - c.searchRadius - 3; y <= area.centre.y + c.searchRadius + 3; ++y)
        for (std::int32_t x = area.centre.x - c.searchRadius - 3; x <= area.centre.x + c.searchRadius + 3; ++x)
            if (MapPos p{x, y}; on_map(p) && hex_distance(area.centre, p) <= c.searchRadius + 2) add(area, p);
    std::vector<std::pair<MapPos, std::vector<MapPos>>> found;
    std::vector<Building *> blockers;
    write(area, c.player);
    refresh(area);
    for_each_candidate(c, [&](MapPos pos) {
        std::vector<MapPos> path;
        if (placement_ok(c, pos, destroy ? &blockers : nullptr) && street_path(c, step(pos, 1), path))
            found.push_back({pos, path});
        return false;
    });
    restore(area);
    // The first candidate that also works with exactly its own land, as the game would take it.
    for (auto &[pos, path] : found) {
        Claim land = needed_land(c, pos, path);
        write(land, c.player);
        refresh(land);
        std::vector<MapPos> check;
        blockers.clear();
        bool ok = placement_ok(c, pos, destroy ? &blockers : nullptr) && street_path(c, step(pos, 1), check);
        restore(land);
        if (ok) {
            out.expedition = c.expedition;
            out.position = pos;
            out.land = std::move(land);
            out.blockers = std::move(blockers);
            return true;
        }
    }
    return false;
}

// PlayerMessages type of the game's territory and military feedback ("!Lost Territory.",
// TerritoryLostFlags::NotifyLostTerritory S 006797f0).
constexpr std::int32_t kMessageTerritory = 1;

// The claim, for real: the cells become the colonist's and the game's territory-change update runs. Every player who
// lost cells gets the game's "!Lost Territory." at the harbour, unless one is already there, as
// NotifyLostTerritory does (PlayerMessages_FindNearForPlayer S 005c01b0, distance 1).
void claim(Claim &land, std::int32_t player)
{
    write(land, player);
    fn::ai::map::MapModifier::OnTerritoryChangedAt(modifier(), &land.centre, land.radius);
    refresh(land);
    bool lost[8] = {};
    for (std::int32_t before : land.before)
        if (before >= 0 && before < 8 && before != player) lost[before] = true;
    for (std::int32_t p = 0; p < 8; ++p) {
        sadk::msvc::string key = sadk::msvc::string::borrow("!Lost Territory.");
        if (!lost[p] || fn::PlayerMessages_FindNearForPlayer(kMessageTerritory, p, &key, &land.centre.x, 1)) continue;
        sadk::msvc::string none = sadk::msvc::string::borrow("");
        post(kMessageTerritory, p, "!Lost Territory.", nullptr, &none, &land.centre.x);
    }
}

// An enemy territory building in the guard post's way, removed the way the game removes a building that lost its
// hitpoints or its land (NVillage::System::RemoveBuilding S 00559db0 with spill, as Hitpoints::OnChanged S 0055b8b0
// and NVillage::System::Update S 0055a640 call it): its soldiers and goods come out, its territory goes.
// The headquarters is the one building type that is both a depot and gives territory (castle in the game's
// buildings.lua: bp_setDepot and bp_setTerritoryRange 9). Losing it this way gets its owner a word of explanation
// (maintainer's wording; it should never happen on a sane map: the headquarters' own land keeps colonies away).
bool headquarters(Building *b) { return b->property->depot && b->property->territoryRange > 0; }

void destroy(Building *b)
{
    sadk::log("harbour takeover: destroying player %d's building at (%d,%d) in the guard post's way", owner(b),
              b->posX, b->posY);
    if (headquarters(b)) {
        std::int32_t cell[2] = {b->posX, b->posY};
        sadk::msvc::string none = sadk::msvc::string::borrow("");
        post(kMessageTerritory, owner(b), "!navalcombatfix_hq_lost",
             "Your headquarters was razed to make room for an enemy colony at your unguarded harbour. Blame the map "
             "maker for putting a harbour right next to it.",
             &none, cell);
    }
    std::int32_t next[2];
    fn::NVillage::System::RemoveBuilding(logic()->village, next, &b->unique, true);
}

// The flag of the enemy on the harbour cell, which no longer stands on its owner's land: removed as
// NNet::System::Update S 00665ef0 would on its next tick, and with it the harbour's owner.
void free_harbor(Harbor *h)
{
    if (Flag *flag = harbor_flag(h)) {
        void *next[2];
        fn::NNet::System::RemoveFlag(logic()->net, next, &flag->unique, 0);
    }
}

using FindBuildingPosition = sadk::Hook<fn::NNavy::Expedition::FindBuildingPosition>;
using PlaceExpeditionBuilding = sadk::Hook<fn::NVillage::System::PlaceExpeditionBuilding>;

std::int32_t *SADK_THISCALL find_building_position(Expedition *e, std::int32_t *out)
{
    if (e != g_plan.expedition) return FindBuildingPosition::original(e, out);
    out[0] = g_plan.position.x;
    out[1] = g_plan.position.y;
    return out;
}

Building *SADK_THISCALL place_expedition_building(game::NVillage::System *village, void *player, std::int32_t *pos)
{
    Building *b = PlaceExpeditionBuilding::original(village, player, pos);
    if (g_plan.expedition) claim(g_plan.land, *static_cast<std::int32_t *>(player));   // the new source recomputed it
    return b;
}

Colony colony_of(Expedition *e)
{
    Colony c{};
    c.expedition = e;
    c.harbor = target_harbor(e);
    c.player = ship_of(e)->player->index;
    game::ai::properties::PropertiesDb *db = fn::NProperties::StaticAccess::EnsureInstance();
    c.type = fn::ai::properties::ShipConfig::GetExpeditionBuilding(db->shipConfig, ship_of(e)->player->tribeId);
    game::ai::properties::BuildingProperty *building = fn::ai::properties::PropertiesDb::GetBuildingProperty(db, &c.type);
    c.sizeFlags = building->size;
    c.searchRadius = building->territoryRange - 1;
    c.landmass = c.harbor ? region(c.harbor) : kNobody;
    return c;
}

}  // namespace

bool harbor_open_to(Harbor *h, std::int32_t player)
{
    return g_settings.harborMustHaveGarrison && h && h->playerIdx != kNobody && h->playerIdx != player &&
           enemies(h->playerIdx, player) && !garrisoned(h);
}

TakeoverResult found_colony(Expedition *e, bool invasion, bool (*original)(Expedition *))
{
    Harbor *h = target_harbor(e);
    std::int32_t player = ship_of(e)->player->index;
    bool held = h && h->playerIdx != kNobody && h->playerIdx != player;
    bool takeover = harbor_open_to(h, player) || (invasion && g_settings.harborMustHaveGarrison && h && !held);
    if (!takeover) return original(e) ? TakeoverResult::founded : TakeoverResult::game;
    Colony c = colony_of(e);
    Plan p;
    if (!plan(c, p, false) && !plan(c, p, true)) {
        if (!held) return original(e) ? TakeoverResult::founded : TakeoverResult::game;   // the game decides
        sadk::log("harbour takeover: no room for the colony of player %d at harbour (%d,%d)", player, h->posX, h->posY);
        return TakeoverResult::no_room;
    }
    sadk::log("harbour takeover: player %d founds at (%d,%d), %d cells claimed", player, p.position.x, p.position.y,
              static_cast<int>(p.land.cells.size()));
    for (Building *b : p.blockers) destroy(b);
    claim(p.land, player);
    if (held) {
        free_harbor(h);
        if (h->playerIdx != kNobody)
            sadk::log("harbour takeover: harbour (%d,%d) still owned by %d", h->posX, h->posY, h->playerIdx);
    }
    g_plan = std::move(p);
    bool founded = original(e);
    g_plan = Plan{};
    return founded ? TakeoverResult::founded : TakeoverResult::game;
}

}  // namespace navalcombatfix

bool takeover_start()
{
    using namespace navalcombatfix;
    bool ok = FindBuildingPosition::install(find_building_position) &&
              PlaceExpeditionBuilding::install(place_expedition_building);
    sadk::log("%s", ok ? "harbour garrison: ungarrisoned enemy harbours can be taken by expeditions"
                       : "harbour garrison NOT active");
    return ok;
}
