// propreload: a TEST mod (not for play). It answers one question for server mods (docs/data-loading.md §1): can the
// property database be filled again between matches, so that a mod that changes scripts\properties\*.lua takes
// effect without restarting the game?
//
// The game fills the database once, in CApplicationEx::Initialize S 004075d0: Properties_RegisterLuaLibrary
// S 00550e40 (defaults + the Lua library "properties"), then Properties_RunPropertyScript("data") S 0054f8d0. Its
// bindings append, so the database is emptied first with the game's own Properties_Db_ClearAll S 005494a0 (otherwise
// only called at shutdown). This mod runs those three steps every time a match is entered: in Scene_CreateGlobal
// S 0067e800, which nMenu::Game::OnEnter S 005eed00 calls once per match (offline and online), before the world is
// built. If something kept pointers into the old records (menus, sound, music), it now reads freed memory: a crash,
// or wrong names / values in the menus, is the answer "not safe". The log shows the record counts before and after.
#include <sadkmod/game/sadk_noav/fn/NProperties.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/sadkmod.hpp>

namespace game = sadk::game;
namespace fn = sadk::game::fn;
using SceneCreate = sadk::Hook<fn::Scene_CreateGlobal>;

namespace {

int reloads;

void log_counts(const char *when, game::ai::properties::PropertiesDb *db)
{
    sadk::log("%s: %u buildings, %u goods, %u tribes, %u animals, %u AI, %u sacrifices", when, db->buildingMapSize,
              db->goodMapSize, db->tribeMapSize, db->animalMapSize, db->aiMapSize, db->sacrificeMapSize);
}

// Initialize calls it with the database in ECX and the name on the stack, and does not clean up the stack after
// the call (S 00407792..0040779e); the body ignores ECX. Called the same way here.
using run_script_fn = void(SADK_THISCALL *)(void *db, sadk::msvc::string *name);

void SADK_CDECL scene_create()
{
    auto *db = fn::NProperties::StaticAccess::EnsureInstance();
    reloads++;
    sadk::log("match %d: reloading the property database", reloads);
    log_counts("before", db);
    fn::Properties_Db_ClearAll(db);
    log_counts("cleared", db);
    fn::Properties_RegisterLuaLibrary(db);
    sadk::msvc::string name = sadk::msvc::string::small("data");
    reinterpret_cast<run_script_fn>(reinterpret_cast<void *>(fn::Properties_RunPropertyScript.get()))(db, &name);
    log_counts("after", db);
    SceneCreate::original();
}

}  // namespace

bool propreload_start()
{
    sadk::log("TEST MOD: the property database is reloaded every time a match is entered");
    return SceneCreate::install(scene_create, "Scene_CreateGlobal: reload the properties first");
}

SADKMOD_MAIN(propreload_start, 1, SADKMOD_SERVER)
