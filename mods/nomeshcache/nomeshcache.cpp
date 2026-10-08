// nomeshcache: the game never uses its converted-mesh cache (%LOCALAPPDATA%\SAdK\*.mshraw); every model is read from
// its .KEX file. Useful while making models: a changed .KEX shows up without deleting cache files.
//
// S2CE::CMesh::Load S 0076e0d0 (19 callers, every mesh) takes a `noCache` flag: unless it is set, the loader reads
// the .mshraw when IsPackedCacheUpToDate S 0076cbe0 says it is newer than the .KEX, and writes a fresh one after
// converting (SavePackedBinary S 0076bdc0). This mod passes noCache = true on every call. Loading takes longer, as
// every mesh is converted each time; existing cache files are left alone. Known side effect: the lobby town flickers
// while the mod is on (maintainer's test, 2026-10-08; cause not investigated). Meant for model makers, not for play.
#include <sadkmod/game/sadk_noav/fn/S2CE.hpp>
#include <sadkmod/sadkmod.hpp>

namespace game = sadk::game;
using MeshLoad = sadk::Hook<game::fn::S2CE::CMesh::Load>;

static bool SADK_THISCALL load_without_cache(game::S2CE::CMesh *mesh, sadk::msvc::string *path, std::int32_t *decl,
                                             float param30, bool merge, bool rebase, char *mesh_name, bool /*noCache*/)
{
    return MeshLoad::original(mesh, path, decl, param30, merge, rebase, mesh_name, true);
}

bool nomeshcache_start()
{
    return MeshLoad::install(load_without_cache, "CMesh::Load without the .mshraw cache");
}

SADKMOD_MAIN(nomeshcache_start, 1, SADKMOD_CLIENT)
