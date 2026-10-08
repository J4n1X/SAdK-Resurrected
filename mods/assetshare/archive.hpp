// The files assetshare transfers (docs/s2tftp.md): one archive per transfer, a map file or a whole mod folder.
//
//   header   "SADKAS1\0", u32 method (0 stored, 1 LZMS), u32 entry count, u64 raw size, u64 packed size
//   packed   the raw stream, as stored or compressed with LZMS (Windows Compression API, cabinet.dll, Windows 8+)
//   padding  0 or 1 byte, so the file size is never a multiple of 512: S2TFTP's receiver only finishes on a block
//            shorter than the block size (512 to 4096 bytes), so such a file would never complete
//   raw stream, per entry: u16 path length, path (relative, '\'), u64 size, the bytes
// All numbers little-endian.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace assetshare::archive {

enum Method : std::uint32_t { stored = 0, lzms = 1 };

// The Windows Compression API is there (Windows 8 and later): this side can compress and decompress LZMS.
bool can_compress();

struct Entry {
    std::string path;   // relative, '\' separated
    std::vector<std::uint8_t> data;
};

// Writes `file`. LZMS falls back to stored when this side cannot compress; `used` says which it was.
bool write(const std::string &file, const std::vector<Entry> &entries, Method method, Method *used, std::string *error);
bool read(const std::string &file, std::vector<Entry> &out, std::string *error);

// Every file below `dir` (relative paths, sorted), and the reverse: an entry with an absolute path, a drive, "..",
// or anything that would leave `dir` is refused.
bool read_folder(const std::string &dir, std::vector<Entry> &out);
bool write_folder(const std::string &dir, const std::vector<Entry> &entries, std::string *error);

bool read_file(const std::string &path, std::vector<std::uint8_t> &out);
bool write_file(const std::string &path, const void *data, std::size_t size);

}  // namespace assetshare::archive
