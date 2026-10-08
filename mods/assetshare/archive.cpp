#include "archive.hpp"

#include <windows.h>

#include <algorithm>
#include <cstring>

namespace assetshare::archive {

namespace {

const char magic[8] = {'S', 'A', 'D', 'K', 'A', 'S', '1', '\0'};
constexpr std::size_t header_size = 8 + 4 + 4 + 8 + 8;

// The Windows Compression API (compressapi.h), loaded at run time: cabinet.dll has it from Windows 8 on.
constexpr DWORD COMPRESS_ALGORITHM_LZMS = 5;
constexpr DWORD COMPRESS_INFORMATION_CLASS_BLOCK_SIZE = 2;
using create_fn = BOOL(WINAPI *)(DWORD, void *, HANDLE *);
using compress_fn = BOOL(WINAPI *)(HANDLE, const void *, SIZE_T, void *, SIZE_T, SIZE_T *);
using close_fn = BOOL(WINAPI *)(HANDLE);
using set_info_fn = BOOL(WINAPI *)(HANDLE, DWORD, const void *, DWORD);

struct Api {
    create_fn create_compressor = nullptr, create_decompressor = nullptr;
    compress_fn compress = nullptr, decompress = nullptr;
    close_fn close_compressor = nullptr, close_decompressor = nullptr;
    set_info_fn set_compressor_information = nullptr;
    bool ok = false;
};

const Api &api()
{
    static Api a = [] {
        Api r;
        HMODULE dll = LoadLibraryA("cabinet.dll");
        if (!dll) return r;
        auto get = [&](const char *name) { return reinterpret_cast<void *>(GetProcAddress(dll, name)); };
        r.create_compressor = reinterpret_cast<create_fn>(get("CreateCompressor"));
        r.create_decompressor = reinterpret_cast<create_fn>(get("CreateDecompressor"));
        r.compress = reinterpret_cast<compress_fn>(get("Compress"));
        r.decompress = reinterpret_cast<compress_fn>(get("Decompress"));
        r.close_compressor = reinterpret_cast<close_fn>(get("CloseCompressor"));
        r.close_decompressor = reinterpret_cast<close_fn>(get("CloseDecompressor"));
        r.set_compressor_information = reinterpret_cast<set_info_fn>(get("SetCompressorInformation"));
        HANDLE h = nullptr;   // present is not enough: LZMS itself must be there
        r.ok = r.create_compressor && r.create_decompressor && r.compress && r.decompress && r.close_compressor &&
               r.close_decompressor && r.create_compressor(COMPRESS_ALGORITHM_LZMS, nullptr, &h);
        if (h) r.close_compressor(h);
        return r;
    }();
    return a;
}

bool lzms_compress(const std::vector<std::uint8_t> &in, std::vector<std::uint8_t> &out)
{
    const Api &a = api();
    HANDLE h = nullptr;
    if (!a.ok || !a.create_compressor(COMPRESS_ALGORITHM_LZMS, nullptr, &h)) return false;
    // One block over the whole input (at least LZMS's 1 MB minimum): matches across every file of a mod.
    DWORD block = static_cast<DWORD>(std::max<std::size_t>(in.size(), 1u << 20));
    if (a.set_compressor_information)
        a.set_compressor_information(h, COMPRESS_INFORMATION_CLASS_BLOCK_SIZE, &block, sizeof block);
    SIZE_T need = 0;
    a.compress(h, in.data(), in.size(), nullptr, 0, &need);   // asks for the size
    bool ok = need > 0;
    if (ok) {
        out.resize(need);
        SIZE_T got = 0;
        ok = a.compress(h, in.data(), in.size(), out.data(), out.size(), &got);
        out.resize(ok ? got : 0);
    }
    a.close_compressor(h);
    return ok;
}

bool lzms_decompress(const std::uint8_t *in, std::size_t n, std::vector<std::uint8_t> &out, std::uint64_t raw_size)
{
    const Api &a = api();
    HANDLE h = nullptr;
    if (!a.ok || !a.create_decompressor(COMPRESS_ALGORITHM_LZMS, nullptr, &h)) return false;
    out.resize(static_cast<std::size_t>(raw_size));
    SIZE_T got = 0;
    bool ok = a.decompress(h, in, n, out.data(), out.size(), &got) && got == raw_size;
    a.close_decompressor(h);
    return ok;
}

void put(std::vector<std::uint8_t> &v, const void *p, std::size_t n)
{
    auto *b = static_cast<const std::uint8_t *>(p);
    v.insert(v.end(), b, b + n);
}

template <class T>
void put_le(std::vector<std::uint8_t> &v, T x)
{
    for (std::size_t i = 0; i < sizeof x; i++) v.push_back(static_cast<std::uint8_t>(static_cast<std::uint64_t>(x) >> (8 * i)));
}

template <class T>
bool get_le(const std::uint8_t *&p, const std::uint8_t *end, T *x)
{
    if (static_cast<std::size_t>(end - p) < sizeof(T)) return false;
    std::uint64_t v = 0;
    for (std::size_t i = 0; i < sizeof(T); i++) v |= static_cast<std::uint64_t>(p[i]) << (8 * i);
    *x = static_cast<T>(v);
    p += sizeof(T);
    return true;
}

// A relative path that stays below its folder: no drive, no root, no "..", no empty part.
bool safe_relative(const std::string &p)
{
    if (p.empty() || p.size() > 240 || p[0] == '\\' || p[0] == '/' || p.find(':') != std::string::npos) return false;
    std::size_t start = 0;
    while (start <= p.size()) {
        std::size_t end = p.find_first_of("\\/", start);
        std::string part = p.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (part.empty() || part == "." || part == "..") return false;
        for (char c : part)
            if (static_cast<unsigned char>(c) < 0x20 || std::strchr("<>\"|?*", c)) return false;
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return true;
}

void collect(const std::string &dir, const std::string &rel, std::vector<Entry> &out, bool &ok)
{
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA((dir + (rel.empty() ? "" : "\\" + rel) + "\\*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (!std::strcmp(fd.cFileName, ".") || !std::strcmp(fd.cFileName, "..")) continue;
        std::string r = rel.empty() ? std::string(fd.cFileName) : rel + "\\" + fd.cFileName;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            collect(dir, r, out, ok);
            continue;
        }
        Entry e{r, {}};
        ok = read_file(dir + "\\" + r, e.data) && ok;
        out.push_back(std::move(e));
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}

}  // namespace

bool can_compress() { return api().ok; }

bool read_file(const std::string &path, std::vector<std::uint8_t> &out)
{
    HANDLE f = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER size;
    bool ok = GetFileSizeEx(f, &size) && size.QuadPart < (1ll << 30);
    if (ok) {
        out.resize(static_cast<std::size_t>(size.QuadPart));
        DWORD got = 0;
        ok = out.empty() || (ReadFile(f, out.data(), static_cast<DWORD>(out.size()), &got, nullptr) && got == out.size());
    }
    CloseHandle(f);
    return ok;
}

bool write_file(const std::string &path, const void *data, std::size_t size)
{
    HANDLE f = CreateFileA(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    DWORD put = 0;
    bool ok = size == 0 || (WriteFile(f, data, static_cast<DWORD>(size), &put, nullptr) && put == size);
    CloseHandle(f);
    return ok;
}

bool write(const std::string &file, const std::vector<Entry> &entries, Method method, Method *used, std::string *error)
{
    std::vector<std::uint8_t> raw;
    for (auto &e : entries) {
        put_le<std::uint16_t>(raw, static_cast<std::uint16_t>(e.path.size()));
        put(raw, e.path.data(), e.path.size());
        put_le<std::uint64_t>(raw, e.data.size());
        put(raw, e.data.data(), e.data.size());
    }
    std::vector<std::uint8_t> packed;
    Method m = stored;
    if (method == lzms && lzms_compress(raw, packed)) m = lzms;
    const std::vector<std::uint8_t> &body = m == lzms ? packed : raw;
    std::vector<std::uint8_t> out;
    put(out, magic, sizeof magic);
    put_le<std::uint32_t>(out, m);
    put_le<std::uint32_t>(out, static_cast<std::uint32_t>(entries.size()));
    put_le<std::uint64_t>(out, raw.size());
    put_le<std::uint64_t>(out, body.size());
    put(out, body.data(), body.size());
    if (out.size() % 512 == 0) out.push_back(0);
    if (used) *used = m;
    if (!write_file(file, out.data(), out.size())) {
        if (error) *error = "cannot write " + file;
        return false;
    }
    return true;
}

bool read(const std::string &file, std::vector<Entry> &out, std::string *error)
{
    auto fail = [&](const char *why) {
        if (error) *error = why;
        return false;
    };
    std::vector<std::uint8_t> data;
    if (!read_file(file, data)) return fail("cannot read the file");
    if (data.size() < header_size || std::memcmp(data.data(), magic, sizeof magic) != 0) return fail("not an archive");
    const std::uint8_t *p = data.data() + sizeof magic, *end = data.data() + data.size();
    std::uint32_t method = 0, count = 0;
    std::uint64_t raw_size = 0, packed_size = 0;
    get_le(p, end, &method);
    get_le(p, end, &count);
    get_le(p, end, &raw_size);
    get_le(p, end, &packed_size);
    if (packed_size > static_cast<std::uint64_t>(end - p) || raw_size > (1ull << 30)) return fail("truncated archive");
    std::vector<std::uint8_t> raw;
    if (method == stored) {
        if (packed_size != raw_size) return fail("damaged archive");
        raw.assign(p, p + packed_size);
    } else if (method == lzms) {
        if (!can_compress()) return fail("LZMS archive, but this Windows cannot decompress it");
        if (!lzms_decompress(p, static_cast<std::size_t>(packed_size), raw, raw_size)) return fail("damaged archive");
    } else {
        return fail("unknown compression");
    }
    out.clear();
    const std::uint8_t *q = raw.data(), *qend = raw.data() + raw.size();
    for (std::uint32_t i = 0; i < count; i++) {
        std::uint16_t len = 0;
        std::uint64_t size = 0;
        if (!get_le(q, qend, &len) || static_cast<std::size_t>(qend - q) < len) return fail("damaged archive");
        Entry e{std::string(reinterpret_cast<const char *>(q), len), {}};
        q += len;
        if (!get_le(q, qend, &size) || size > static_cast<std::uint64_t>(qend - q)) return fail("damaged archive");
        e.data.assign(q, q + size);
        q += size;
        out.push_back(std::move(e));
    }
    return q == qend ? true : fail("damaged archive");
}

bool read_folder(const std::string &dir, std::vector<Entry> &out)
{
    out.clear();
    bool ok = true;
    collect(dir, "", out, ok);
    std::sort(out.begin(), out.end(), [](const Entry &a, const Entry &b) { return a.path < b.path; });
    return ok;
}

bool write_folder(const std::string &dir, const std::vector<Entry> &entries, std::string *error)
{
    CreateDirectoryA(dir.c_str(), nullptr);
    for (auto &e : entries) {
        if (!safe_relative(e.path)) {
            if (error) *error = "refused a file outside the mod's folder: " + e.path;
            return false;
        }
        std::string path = dir + "\\" + e.path;
        for (std::size_t i = dir.size() + 1; (i = path.find('\\', i)) != std::string::npos; i++)
            CreateDirectoryA(path.substr(0, i).c_str(), nullptr);
        if (!write_file(path, e.data.data(), e.data.size())) {
            if (error) *error = "cannot write " + path;
            return false;
        }
    }
    return true;
}

}  // namespace assetshare::archive
