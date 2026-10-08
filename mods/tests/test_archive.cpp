// assetshare's archive format (mods/assetshare/archive.hpp), run under Wine or Windows: test_archive.exe
// Round trips stored and (where this Windows has the Compression API) LZMS, the size padding S2TFTP needs, a folder
// written back, and refusals of damaged archives and of paths outside the folder.
#include "../assetshare/archive.hpp"

#include <windows.h>

#include <cstdio>
#include <string>

using namespace assetshare::archive;

static int failures, checks;
#define CHECK(cond)                                                                    \
    do {                                                                               \
        checks++;                                                                      \
        if (!(cond)) {                                                                 \
            failures++;                                                                \
            std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);                \
        }                                                                              \
    } while (0)

static std::vector<Entry> sample()
{
    std::vector<Entry> e;
    std::string text;
    for (int i = 0; i < 2000; i++) text += "repetitive text compresses well, line " + std::to_string(i % 7) + "\n";
    e.push_back({"mod.dll", std::vector<std::uint8_t>(5000, 0x90)});
    e.push_back({"data\\game\\scripts\\properties\\data.lua", std::vector<std::uint8_t>(text.begin(), text.end())});
    e.push_back({"empty.txt", {}});
    return e;
}

static long file_size(const std::string &p)
{
    WIN32_FILE_ATTRIBUTE_DATA fa{};
    return GetFileAttributesExA(p.c_str(), GetFileExInfoStandard, &fa) ? long(fa.nFileSizeLow) : -1;
}

int main()
{
    char tmp[MAX_PATH];
    GetTempPathA(MAX_PATH, tmp);
    std::string dir = std::string(tmp) + "test_archive";
    CreateDirectoryA(dir.c_str(), nullptr);
    auto in = sample();
    std::string error;

    for (Method want : {stored, lzms}) {
        std::string file = dir + (want == stored ? "\\stored.sas" : "\\lzms.sas");
        Method used;
        CHECK(write(file, in, want, &used, &error));
        CHECK(used == (want == lzms && can_compress() ? lzms : stored));
        CHECK(file_size(file) > 0 && file_size(file) % 512 != 0);
        std::vector<Entry> out;
        CHECK(read(file, out, &error));
        CHECK(out.size() == in.size());
        for (std::size_t i = 0; i < out.size() && i < in.size(); i++)
            CHECK(out[i].path == in[i].path && out[i].data == in[i].data);
        std::printf("%s: %ld bytes (%s)\n", file.c_str(), file_size(file), used == lzms ? "LZMS" : "stored");
    }

    // padding: an archive whose natural size is a multiple of 512 gets one more byte
    for (std::size_t n = 0; n < 600; n++) {
        std::vector<Entry> e{{"x", std::vector<std::uint8_t>(n, 1)}};
        std::string f = dir + "\\pad.sas";
        write(f, e, stored, nullptr, &error);
        if (file_size(f) % 512 == 0) {
            CHECK(!"a size that is a multiple of 512");
            break;
        }
        std::vector<Entry> back;
        if (!read(f, back, &error) || back.size() != 1 || back[0].data.size() != n) {
            CHECK(!"padded archive does not read back");
            break;
        }
    }

    // a folder and back
    std::string folder = dir + "\\folder";
    CHECK(write_folder(folder, in, &error));
    std::vector<Entry> again;
    CHECK(read_folder(folder, again) && again.size() == in.size());

    // refused: damage, and paths that leave the folder
    std::vector<std::uint8_t> bytes;
    read_file(dir + "\\stored.sas", bytes);
    bytes.resize(bytes.size() / 2);
    write_file(dir + "\\cut.sas", bytes.data(), bytes.size());
    std::vector<Entry> out;
    CHECK(!read(dir + "\\cut.sas", out, &error));
    for (const char *bad : {"..\\escape.txt", "C:\\abs.txt", "\\root.txt", "a\\..\\..\\b", "a\\\\b"})
        CHECK(!write_folder(folder, {{bad, {1}}}, &error));

    std::printf("%d checks, %d failed; this Windows %s LZMS\n", checks, failures, can_compress() ? "has" : "does not have");
    return failures ? 1 : 0;
}
