// propreload: a TEST mod (not for play). It answers one question for server mods (docs/data-loading.md §1): can the
// property database be filled again between matches, so that a mod that changes scripts\properties\*.lua takes
// effect without restarting the game?
//
// The game fills the database once, in CApplicationEx::Initialize S 004075d0: Properties_RegisterLuaLibrary
// S 00550e40 (defaults + the Lua library "properties"), then PropertiesDb::RunPropertyScript("data") S 0054f8d0. Its
// bindings append, so the database is emptied first with the game's own Properties_Db_ClearAll S 005494a0 (otherwise
// only called at shutdown). This mod runs those three steps every time a match is entered: in Scene_CreateGlobal
// S 0067e7e0, which nMenu::Game::OnEnter S 005eed00 calls once per match (offline and online), before the world is
// built. If something kept pointers into the old records (menus, sound, music), it now reads freed memory: a crash,
// or wrong names / values in the menus, is the answer "not safe". The log shows the record counts before and after.
#include <sadkmod/game/sadk_noav/fn/NProperties.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/game/sadk_noav/fn/ai.hpp>
#include <sadkmod/sadkmod.hpp>

namespace game = sadk::game;
namespace fn = sadk::game::fn;

namespace {

int reloads;

void log_counts(const char *when, game::ai::properties::PropertiesDb *db)
{
    sadk::log("%s: %u buildings, %u goods, %u tribes, %u animals, %u AI, %u sacrifices", when, db->buildingMapSize,
              db->goodMapSize, db->tribeMapSize, db->animalMapSize, db->aiMapSize, db->sacrificeMapSize);
}

void match_enter(void *)
{
    auto *db = fn::NProperties::StaticAccess::EnsureInstance();
    reloads++;
    sadk::log("match %d: reloading the property database", reloads);
    log_counts("before", db);
    fn::Properties_Db_ClearAll(db);
    log_counts("cleared", db);
    fn::Properties_RegisterLuaLibrary(db);
    sadk::msvc::string name = sadk::msvc::string::small("data");
    fn::ai::properties::PropertiesDb::RunPropertyScript(db, &name);
    log_counts("after", db);
}

}  // namespace

bool propreload_start()
{
    sadk::log("TEST MOD: the property database is reloaded every time a match is entered");
    return sadk::events::on_match_enter(match_enter);   // Scene_CreateGlobal, before the world is built
}

SADKMOD_MAIN(propreload_start, 1, SADKMOD_SERVER)
