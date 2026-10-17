// Checks every patch of the repo's mods against a copy of the DRM-free SADK.exe, without running the game:
// verify_mods.exe <SADK.exe>. The mods' start functions run unchanged in sadkmod's verify mode.
#include <sadkmod/game/sadk_noav/module.hpp>
#include <sadkmod/sadkmod.hpp>

#include <windows.h>

#include <cstdio>
#include <cstring>

bool borderless_start();
bool npcmodels_start();
bool nomeshcache_start();
bool propreload_start();
bool combat_start();
bool retreat_start();
bool proximity_start();
bool invasion_start();
bool takeover_start();
bool cheatstart_start();
bool oscursor_start();
bool nopreview_start();
bool mpsave_start();
bool distantlands_start();

int main(int argc, char **argv)
{
    if (argc < 2) {
        std::printf("usage: verify_mods.exe <SADK.exe>\n");
        return 2;
    }
    char log[MAX_PATH];
    GetTempPathA(MAX_PATH, log);
    std::strcat(log, "verify_mods.log");
    DeleteFileA(log);
    sadk::log_open(log);
    if (sadk::file_md5(argv[1]) != sadk::game::md5) {
        std::printf("%s is not the DRM-free build (%s)\n", argv[1], sadk::game::md5);
        return 2;
    }
    static sadk::MappedImage image;
    if (!sadk::map_image(argv[1], image)) return 2;
    sadk::verify_with(sadk::Module::sadk, &image);
    borderless_start();
    npcmodels_start();
    nomeshcache_start();
    propreload_start();
    combat_start();       // navalcombatfix
    retreat_start();
    proximity_start();
    invasion_start();
    takeover_start();
    cheatstart_start();
    oscursor_start();
    nopreview_start();
    mpsave_start();
    distantlands_start();
    sadk::verify_with(sadk::Module::sadk, nullptr);
    auto n = sadk::verify_counts();
    const int expected = 6 + 1 + 1 + 23 + 1 + 3 + 2 + 12 + 3;   // borderless 6 hooks, npcmodels 1, nomeshcache 1 hook,
                                                        // navalcombatfix 23 hooks, cheatstart 1 hook, oscursor 3
                                                        // hooks, nopreview 2 hooks, mpsave 9 hooks and 3 redirected
                                                        // calls (events are not verified), distantlands 3 hooks
    std::printf("%d patches match, %d do not (%d expected to match; log: %s)\n", n.matched, n.mismatched, expected, log);
    if (FILE *f = std::fopen(log, "r")) {
        char line[512];
        while (std::fgets(line, sizeof line, f)) std::fputs(line, stdout);
        std::fclose(f);
    }
    return n.matched == expected && n.mismatched == 0 ? 0 : 1;
}
