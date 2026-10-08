// cheatstart: a TEST mod (not for play). Every player starts with plenty of every good of their tribe and of every
// soldier type and level, to try out military and naval rules quickly in a multiplayer match.
//
// Where the starting goods come from: NVillage::Depot::AddInitialStock S 0055b020 fills the headquarters' stock
// (Depot::stockB) with the map's starting goods for the owner's tribe (NLogic::MapInfo::GetInitialGoods S 005296e0;
// maps of save format 14 and later carry their own list, MapInfo::Load S 0052c000, so tribes.lua's
// tp_addStartResources only reaches older maps) and, for a player in the default state, the tribe's bonus goods. It
// runs for buildings placed finished: the headquarters at the start of a match (Game_CreatePlayersFromDescriptor
// S 005ac212) and finished buildings a map places (Building::ctor_Place S 0055de24), not for depots built during
// play. This mod adds its amounts after the game's, so it covers every map. Changes the match: every player needs it
// (SERVER).
//
// What it adds, per depot:
//   - Goods (cheatstart.ini) units of every good the tribe has (TribeProperty::goods, tp_addGood);
//   - Soldiers units of every soldier type (0 melee, 1 ranged) and level the tribe has, the way Player_Update
//     S 005bf8a0 counts them: ai::military::SoldierLevelRange over MilitaryConfig::GetSoldierId.
#include <sadkmod/game/sadk_noav/fn/NLogic.hpp>
#include <sadkmod/game/sadk_noav/fn/NProperties.hpp>
#include <sadkmod/game/sadk_noav/fn/NVillage.hpp>
#include <sadkmod/game/sadk_noav/fn/ai.hpp>
#include <sadkmod/sadkmod.hpp>

#include <cstdint>

namespace game = sadk::game;
namespace fn = sadk::game::fn;

namespace {

using AddInitialStock = sadk::Hook<fn::NVillage::Depot::AddInitialStock>;

constexpr std::int32_t kSoldierKinds = 2;   // MilitaryConfig: 0 melee, 1 ranged (Player_Update's loop)

std::int32_t g_goods = 1000;
std::int32_t g_soldiers = 99;

void add(game::NLogic::Stock *stock, std::int32_t good, std::int32_t count)
{
    if (good < 0 || count <= 0) return;
    std::int32_t entry[2] = {good, count};   // the GoodAmount pair Stock::AddEntry reads
    fn::NLogic::Stock::AddEntry(stock, entry);
}

void SADK_THISCALL add_initial_stock(game::NVillage::Depot *depot)
{
    AddInitialStock::original(depot);
    game::ai::player::Player *player = depot->building->ownerPlayer;
    game::ai::properties::TribeProperty *tribe = player->pTribeProperty;
    auto *goods = static_cast<std::int32_t *>(tribe->goods.first);
    auto *goodsEnd = static_cast<std::int32_t *>(tribe->goods.last);
    for (std::int32_t *g = goods; g && g != goodsEnd; ++g) add(&depot->stockB, *g, g_goods);

    game::ai::properties::MilitaryConfig *military = fn::NProperties::StaticAccess::EnsureInstance()->militaryConfig;
    for (std::int32_t kind = 0; kind < kSoldierKinds; ++kind) {
        game::ai::military::SoldierLevelRange levels;
        fn::ai::military::SoldierLevelRange::ctor(&levels, player->tribeId, kind, 0);
        for (std::int32_t level = levels.first; level != levels.end; level += levels.step)
            add(&depot->stockB, *fn::ai::properties::MilitaryConfig::GetSoldierId(military, player->tribeId, kind, level),
                g_soldiers);
    }
    sadk::log("player %d: start depot filled (%d of each good, %d of each soldier)", player->index, g_goods, g_soldiers);
}

}  // namespace

bool cheatstart_start()
{
    sadk::Ini ini = sadk::mod_settings();
    g_goods = ini.get_int("CheatStart", "Goods", g_goods);
    g_soldiers = ini.get_int("CheatStart", "Soldiers", g_soldiers);
    bool ok = AddInitialStock::install(add_initial_stock);
    sadk::log(ok ? "TEST MOD: every player starts with %d of each good and %d of each soldier"
                 : "cheatstart NOT active (%d goods, %d soldiers)", g_goods, g_soldiers);
    return ok;
}

SADKMOD_MAIN(cheatstart_start, 1, SADKMOD_SERVER)
