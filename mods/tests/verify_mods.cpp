// Checks every patch of the repo's mods against a copy of the DRM-free SADK.exe, without running the game:
// verify_mods.exe <SADK.exe>. The mods' start functions run unchanged in sadkmod's verify mode.
#include <sadkmod/game/sadk_noav/module.hpp>
#include <sadkmod/sadkmod.hpp>

#include <windows.h>

#include <cstdio>
#include <cstring>

bool billboards_start();
bool borderless_start();
bool npcmodels_start();
bool nomeshcache_start();

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
    billboards_start();
    borderless_start();
    npcmodels_start();
    nomeshcache_start();
    sadk::verify_with(sadk::Module::sadk, nullptr);
    auto n = sadk::verify_counts();
    const int expected = 4 + 6 + 1 + 1;   // billboards 4, borderless 6 hooks, npcmodels 1, nomeshcache 1 hook
    std::printf("%d patches match, %d do not (%d expected to match; log: %s)\n", n.matched, n.mismatched, expected, log);
    if (FILE *f = std::fopen(log, "r")) {
        char line[512];
        while (std::fgets(line, sizeof line, f)) std::fputs(line, stdout);
        std::fclose(f);
    }
    return n.matched == expected && n.mismatched == 0 ? 0 : 1;
}
