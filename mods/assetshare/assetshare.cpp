// assetshare: shares what a match needs between its players, over the game's own file transfer (S2TFTP,
// docs/s2tftp.md): the map, and the host's server mods (mods/README.md). Both sides need it: a host kicks a joiner
// that does not ask for its list of server mods.
//
// Maps (docs/BINARY_PATCHES.md, "Map sharing"). The client already transfers a missing map from the host, but only
// for maps the host advertises with type 3 (Documents\SAdK\maps) AND "download allowed" (+0x228), which
// OnMapSelected always sends as 0.
//   1. NComm_Manager::SetGameSettings S 0040bfd0 (hook), while hosting a network game: every map goes out as
//      type 3 with downloads allowed (OnMapSelected S 00454ad0 passes the map's own type and 0).
//   2. SelectMapDialog::RefreshMapList S 0045a300: also list Documents\SAdK\maps (location 3).
//   3. S2Tftp_Session_ReadNextBlock S 00426ac0 (host serving a file): only maps and assetshare's own files;
//      a map that is not in Documents\SAdK\maps is served from the game's own map folder.
//   4. S2TftpSession::CloseFile S 00427990 (joiner finishing a download): the host-chosen file name may only land in
//      Documents\SAdK\maps as .s2m/.bmp, or in assetshare's download folder.
// Starting a match while the joiner still lacks the map crashes the client, so "ready" is refused until the map is
// present and nothing is downloading. Messages go to the pre-game room through the game's own
// NComm_SendUINotification S 0040e3d0 (the "Player joined game" channel). When the last download completes the
// joiner sends PlayerReady(0) once: the host answers every ready change by re-broadcasting the game information,
// and the joiner then finds the map and refreshes the room.
//
// A joiner (when the host's GameInformation 0x30003 arrives, NComm_Manager::HandleEvent S 0040e560) first fetches
// the host's manifest: its active server mods (name, version, content hash). Then it switches off its own server
// mods that the host does not run, uses its own copy of a host's mod where name, version and hash agree, and
// downloads the others into <game>\mods\.temp_<name>, activating each after its download. Map requests
// (NComm_Manager::RequestFileFromHost S 004084d0) are answered in the same archive form. When the network session
// ends (NComm_Manager::Shutdown S 0040b410) everything is put back: downloaded mods off and deleted, own mods on.
//
// Every transfer is an archive (archive.hpp): LZMS-compressed when both sides can (Windows 8+), stored otherwise,
// and sent in 4 KB blocks whatever the host's connection type (S2TftpSession::BeginSend S 00426a30). The build
// checksum, which the game sends before any transfer, leaves out server mods' files on both sides
// (GameData_ComputeBuildChecksum S 005ab800): server mods are matched here instead.
//
// Settings: assetshare.ini [AssetShare] AcceptServerMaps, AcceptServerMods (false: refuse those downloads).
#include <windows.h>

#include <sadkmod/sadkmod.hpp>
#include <sadkmod/game/sadk_noav/fn/LobbyMenu.hpp>
#include <sadkmod/game/sadk_noav/fn/NComm.hpp>
#include <sadkmod/game/sadk_noav/fn/NComm_Manager.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/game/sadk_noav/fn/ai.hpp>

#include <shlobj.h>

#include <cstdio>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#include "archive.hpp"

using sadk::log;

namespace assetshare {

namespace fn = sadk::game::fn;
namespace game = sadk::game;
using GameFILE = game::mbstring_h::FILE;   // the game's C runtime FILE, not ours
using Manager = game::NComm_Manager;

constexpr int MAP_LOCATION_USER = 3;
constexpr std::uint32_t EV_USER_INFORMATION = 0x30001, EV_GAME_INFORMATION = 0x30003;
constexpr std::uint32_t HOST_NET_ID = 0xEFFFFFCC;   // the host's id in the match network
constexpr DWORD MANIFEST_TIMEOUT_MS = 15000;   // joiner: no manifest by then -> the host has no assetshare
constexpr DWORD KICK_AFTER_MS = 20000;         // host: a joiner that has not asked for the manifest by then
const char kick_reason[] = "This game needs the assetshare mod: install it with SAdK-ServerConfig.";

bool accept_maps = true, accept_mods = true;   // assetshare.ini
std::string docs;                              // <My Documents>\ (with the backslash)
std::string maps_dir;                          // <My Documents>\SAdK\maps\ ...
std::string share_dir;                         // <My Documents>\SAdK\assetshare\  host: archives it serves
std::string in_dir;                            // <My Documents>\SAdK\assetshare\in\  joiner: downloads land here
const char share_rel[] = "SAdK\\assetshare\\";  // the same, relative to My Documents (what a joiner asks for)

const sadkmod_api &host() { return *sadk::host_api(); }
Manager *manager() { return static_cast<Manager *>(fn::NComm_GetManager()); }
bool is_joiner(Manager *m) { return m && (m->nMode == 1 || m->nMode == 3); }
bool is_host_online(Manager *m) { return m && (m->nMode == 2 || m->nMode == 4); }
const char *capability() { return archive::can_compress() ? "lzms" : "stored"; }

bool starts_with_icase(const std::string &s, const std::string &prefix)
{
    return s.size() >= prefix.size() && _strnicmp(s.c_str(), prefix.c_str(), prefix.size()) == 0;
}

// ── Messages in the pre-game room ───────────────────────────────────────────────────────────────────────────────
// NComm_SendUINotification takes a std::string* (the game passes the result of a string builder; Ghidra still
// types the argument as int). The observers only read or copy it; the text must outlive the call.
void room_message(const std::string &text)
{
    static char held[256];
    std::snprintf(held, sizeof held, "%s", text.c_str());
    sadk::msvc::string str = sadk::msvc::string::borrow(held, std::strlen(held));
    if (void *mgr = fn::NComm_GetManager())
        fn::NComm_SendUINotification(mgr, static_cast<std::int32_t>(reinterpret_cast<std::uintptr_t>(&str)));
    log("room: %s", held);
}

// Several short messages for a long list (one chat line each).
void room_list(const std::string &head, const std::vector<std::string> &items)
{
    std::string line = head;
    for (std::size_t i = 0; i < items.size(); i++) {
        std::string add = (i ? ", " : " ") + items[i];
        if (line.size() + add.size() > 200) {
            room_message(line + ",");
            line = "  " + items[i];
        } else {
            line += add;
        }
    }
    room_message(line + ".");
}

// ── Our downloads ────────────────────────────────────────────────────────────────────────────────────────────────
// The game runs one transfer with the host at a time and queues the rest in request order (S2TftpManager::RequestFile
// S 00427140), so ours finish in the order they were asked for: the head of `pending` is the one running.
enum class Kind { manifest, mod, map, raw_map };
struct Download {
    Kind kind;
    std::string local;   // where the game writes it (in_dir\... or, for a raw map, its final path)
    std::string label{};        // for the room: "the server mod rules (version 3)"
    std::string name{};         // mod name, or the map's file name
    std::string final_path{};   // map: where the unpacked file goes
    std::uint32_t version = 0;  // mod
    std::string hash{};         // mod
};
std::deque<Download> pending;

bool request(Manager *m, const std::string &remote, const Download &d);

// ── Joiner state ─────────────────────────────────────────────────────────────────────────────────────────────────
enum class State { idle, waiting_manifest, syncing, ready, legacy, failed };
State state = State::idle;
DWORD manifest_asked_at;
bool host_shares;                       // the manifest came: maps go as archives too
std::vector<std::string> switched_off;  // our server mods off for this game (folder names): on again afterwards
std::vector<std::string> switched_on;   // our inactive mods activated for this game: off again afterwards
std::vector<std::string> downloaded;    // .temp_ folders activated for this game
std::vector<std::string> summary;       // "rules 3 (downloaded)" ...
std::vector<std::string> missing;       // mods this game needs that we will not download
std::vector<std::pair<std::string, std::string>> deferred_maps;   // (remote, local) asked before the manifest came
std::vector<std::string> leftovers;     // .temp_ folders that could not be removed yet

struct HostMod {
    std::string name, hash;
    std::uint32_t version = 0, flags = 0;
};

// ── Download progress (all transfers) ───────────────────────────────────────────────────────────────────────────
volatile LONG downloads_active;
unsigned long download_bytes, download_reported;
DWORD download_last_activity;

bool download_running()
{
    if (downloads_active > 0 && GetTickCount() - download_last_activity > 60000) {
        log("download stalled for 60 s - no longer blocking ready");
        InterlockedExchange(&downloads_active, 0);
    }
    return downloads_active > 0;
}

void download_finished()
{
    if (InterlockedDecrement(&downloads_active) <= 0) {
        InterlockedExchange(&downloads_active, 0);
        if (Manager *m = manager())   // host re-broadcasts -> room refreshes
            fn::NComm_Manager::SendPlayerReadyEvent(m, false);
    }
}

std::string current_label() { return pending.empty() ? std::string("a map file") : pending.front().label; }

bool session_map_present(Manager *mgr)
{
    // NetGUID (vtable + 4 dwords, 0x14 bytes) and NCore::UUID (constructed, GUID at +8..+0x17; the map search
    // compares it there): both get room to spare. The name comes back as a std::string the game may allocate.
    alignas(4) unsigned char guid[32] = {}, uuid[64] = {};
    sadk::msvc::string name = sadk::msvc::string::small("");
    std::int32_t type = 0;
    auto *info = &mgr->gameInformation;
    auto *g = static_cast<game::NComm::NetGUID *>(fn::NComm::EventGameInformation::GetMapGuid(info, guid));
    fn::NComm::NetGUID::ToUUID(g, uuid);
    bool found = fn::GameFile_FindMapByGuidAnyType(uuid, &name, &type);
    if (!name.is_inline()) sadk::game_free(name.heap_text);
    return found;
}

// ── Mods: what the host has, what we have ───────────────────────────────────────────────────────────────────────
struct LocalMod {
    std::string folder, name;
    std::uint32_t version = 0, flags = 0;
    bool active = false, pending_free = false;
};

std::vector<LocalMod> local_mods()
{
    std::vector<LocalMod> out;
    host().list_mods(
        [](const sadkmod_modinfo *i, void *ctx) {
            static_cast<std::vector<LocalMod> *>(ctx)->push_back(
                LocalMod{i->folder, i->name, i->version, i->flags, i->active, i->pending_free});
        },
        &out);
    return out;
}

std::string mod_hash(const std::string &folder)
{
    char h[33] = {};
    return host().mod_hash(folder.c_str(), h) ? std::string(h) : std::string();
}

std::string mod_dir(const std::string &folder) { return sadk::game_path("mods\\") + folder; }

bool remove_tree(const std::string &dir)
{
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA((dir + "\\*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!std::strcmp(fd.cFileName, ".") || !std::strcmp(fd.cFileName, "..")) continue;
            std::string p = dir + "\\" + fd.cFileName;
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
                remove_tree(p);
            else
                DeleteFileA(p.c_str());
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    return RemoveDirectoryA(dir.c_str()) || GetFileAttributesA(dir.c_str()) == INVALID_FILE_ATTRIBUTES;
}

// A downloaded mod's folder: off, out of the list, deleted. Retried later (leftovers) if its mod.dll is still mapped.
void discard_temp(const std::string &folder)
{
    host().deactivate_mod(folder.c_str());
    host().free_pending();
    host().forget_mod(folder.c_str());   // false if it was never listed or is still waiting to be freed
    if (remove_tree(mod_dir(folder))) return;
    log("%s could not be removed yet (its mod.dll is still in use) - later", folder.c_str());
    leftovers.push_back(folder);
}

void retry_leftovers()
{
    host().free_pending();
    std::vector<std::string> still;
    for (auto &f : leftovers)
        if (!host().forget_mod(f.c_str()) && GetFileAttributesA(mod_dir(f).c_str()) != INVALID_FILE_ATTRIBUTES &&
            !remove_tree(mod_dir(f)))
            still.push_back(f);
        else
            remove_tree(mod_dir(f));
    leftovers = still;
}

// ── Host: serving ────────────────────────────────────────────────────────────────────────────────────────────────
// What a joiner asks for, relative to My Documents:
//   SAdK\assetshare\manifest.<cap>      the server mods this host runs
//   SAdK\assetshare\mod.<name>.<cap>    one of them, the whole folder
//   SAdK\assetshare\map.<file>.<cap>    a map file (.s2m / .bmp)
// <cap> is what the joiner can unpack: "lzms" or "stored". The archive goes to share_dir\out\ and is served from there.
std::string manifest_text()
{
    std::string t = "assetshare 1\n";
    for (auto &m : local_mods())
        if (m.active && (m.flags & SADKMOD_SERVER) && !starts_with_icase(m.folder, ".temp_")) {
            char line[512];
            std::snprintf(line, sizeof line, "mod\t%s\t%u\t%s\t%u\n", m.name.c_str(), m.version,
                          mod_hash(m.folder).c_str(), m.flags);
            t += line;
        }
    return t;
}

// The file part of `path` if it is <maps_dir><plain name>.s2m|.bmp, else nullptr.
const char *map_file_name(const char *path)
{
    if (maps_dir.empty() || !starts_with_icase(path, maps_dir)) return nullptr;
    const char *name = path + maps_dir.size();
    std::size_t len = std::strlen(name);
    if (len < 5 || len > 120 || std::strstr(name, "..")) return nullptr;
    for (const char *c = name; *c; c++)
        if (*c == '\\' || *c == '/' || *c == ':' || static_cast<unsigned char>(*c) < 0x20) return nullptr;
    if (_stricmp(name + len - 4, ".s2m") != 0 && _stricmp(name + len - 4, ".bmp") != 0) return nullptr;
    return name;
}

// A plain name: no path, no "..".
bool plain_name(const std::string &n)
{
    if (n.empty() || n.size() > 120 || n.find("..") != std::string::npos) return false;
    for (char c : n)
        if (c == '\\' || c == '/' || c == ':' || static_cast<unsigned char>(c) < 0x20) return false;
    return true;
}

// Builds the archive for a request below share_dir; returns its path, or "" (logged) if there is nothing to send.
std::string build_for_request(const std::string &rest)
{
    std::size_t dot = rest.find_last_of('.');
    if (dot == std::string::npos) return {};
    std::string what = rest.substr(0, dot), cap = rest.substr(dot + 1);
    archive::Method method = cap == "lzms" ? archive::lzms : archive::stored;
    std::vector<archive::Entry> entries;
    std::string label;
    if (what == "manifest") {
        std::string t = manifest_text();
        entries.push_back({"manifest.txt", std::vector<std::uint8_t>(t.begin(), t.end())});
        label = "the server-mod list";
    } else if (starts_with_icase(what, "mod.")) {
        std::string name = what.substr(4);
        const LocalMod *found = nullptr;
        auto mods = local_mods();
        for (auto &m : mods)
            if (m.active && (m.flags & SADKMOD_SERVER) && !_stricmp(m.name.c_str(), name.c_str()) &&
                !starts_with_icase(m.folder, ".temp_"))
                found = &m;
        if (!plain_name(name) || !found || !archive::read_folder(mod_dir(found->folder), entries)) {
            log("serve: no server mod %s to send", name.c_str());
            return {};
        }
        label = "server mod " + name;
    } else if (starts_with_icase(what, "map.")) {
        std::string file = what.substr(4);
        std::vector<std::uint8_t> data;
        std::string path = maps_dir + file;
        if (!map_file_name(path.c_str())) return {};
        if (GetFileAttributesA(path.c_str()) == INVALID_FILE_ATTRIBUTES)
            path = sadk::game_path("data\\game\\maps\\Freegamemaps\\") + file;
        if (!archive::read_file(path, data)) {
            log("serve: map file %s not found", file.c_str());
            return {};
        }
        entries.push_back({file, std::move(data)});
        label = "map file " + file;
    } else {
        return {};
    }
    CreateDirectoryA((share_dir + "out").c_str(), nullptr);
    std::string out = share_dir + "out\\" + rest + ".sas";
    archive::Method used;
    std::string error;
    if (!archive::write(out, entries, method, &used, &error)) {
        log("serve: %s", error.c_str());
        return {};
    }
    std::size_t raw = 0;
    for (auto &e : entries) raw += e.data.size();
    WIN32_FILE_ATTRIBUTE_DATA fa{};
    GetFileAttributesExA(out.c_str(), GetFileExInfoStandard, &fa);
    log("serve: %s, %u KB -> %lu KB (%s)", label.c_str(), unsigned(raw / 1024), fa.nFileSizeLow / 1024,
        used == archive::lzms ? "LZMS" : "stored");
    return out;
}

// S2Tftp_Session_ReadNextBlock's fopen_s (S 00426b14): only maps and assetshare's files are ever sent.
std::uint32_t SADK_CDECL serve_fopen(GameFILE **f, char *path, char *mode)
{
    *f = nullptr;
    if (starts_with_icase(path, share_dir) && !starts_with_icase(path, in_dir)) {
        std::string file = build_for_request(path + share_dir.size());
        return file.empty() ? 2 : fn::_fopen_s(f, file.data(), mode);   // 2 = ENOENT -> !TFTP_ERROR_FILENOTFOUND
    }
    const char *name = map_file_name(path);
    if (!name) {
        log("serve: refused a request for %s (not a map file)", path);
        return 2;
    }
    if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) {
        log("serve: map file %s (plain)", name);
        return fn::_fopen_s(f, path, mode);
    }
    std::string stock = sadk::game_path("data\\game\\maps\\Freegamemaps\\") + name;
    if (GetFileAttributesA(stock.c_str()) != INVALID_FILE_ATTRIBUTES) {
        log("serve: map file %s (plain, from the game's map folder)", name);
        return fn::_fopen_s(f, stock.data(), mode);
    }
    log("serve: %s not found", name);
    return 2;
}

// ── Host: who has assetshare ─────────────────────────────────────────────────────────────────────────────────────
struct Joiner {
    std::int32_t net_id;
    DWORD joined_at;
    bool has_assetshare;
};
std::vector<Joiner> joiners;

void joiner_asked_for_manifest(std::uint32_t net_id)
{
    for (auto &j : joiners)
        if (static_cast<std::uint32_t>(j.net_id) == net_id) j.has_assetshare = true;
}

// Every transfer goes in 4 KB blocks (the game's maximum), whatever the host's connection type; and a joiner that
// asks for the manifest runs assetshare.
using BeginSend = sadk::Hook<fn::ai::net::S2TftpSession::BeginSend>;
bool SADK_THISCALL on_begin_send(game::ai::net::S2TftpSession *s, std::uint32_t self, std::uint32_t peer,
                                 sadk::msvc::string *local_path)
{
    bool ok = BeginSend::original(s, self, peer, local_path);
    s->blockSize = 0x1000;
    if (local_path && starts_with_icase(std::string(local_path->view()), share_dir + "manifest.")) joiner_asked_for_manifest(peer);
    return ok;
}

// ── Joiner: the manifest and the plan ───────────────────────────────────────────────────────────────────────────
void finish_sync(Manager *m)
{
    if (!missing.empty()) {
        state = State::failed;
        room_list("This game needs server mods you won't download (assetshare.ini: AcceptServerMods = false):",
                  missing);
        room_message("You can't get ready in this game.");
        return;
    }
    state = State::ready;
    if (summary.empty())
        room_message("This game uses no server mods.");
    else
        room_list("Server mods for this game:", summary);
    if (m) fn::NComm_Manager::SendPlayerReadyEvent(m, false);   // refresh the room
}

void flush_deferred_maps(Manager *m);

void use_manifest(Manager *m, const std::string &text)
{
    std::vector<HostMod> host_mods;
    std::size_t pos = 0;
    bool header = false;
    while (pos < text.size()) {
        std::size_t end = text.find('\n', pos);
        std::string line = text.substr(pos, end == std::string::npos ? std::string::npos : end - pos);
        pos = end == std::string::npos ? text.size() : end + 1;
        if (line.rfind("assetshare ", 0) == 0) header = true;
        if (line.rfind("mod\t", 0) != 0) continue;
        HostMod h;
        char name[128] = {}, hash[40] = {};
        if (std::sscanf(line.c_str(), "mod\t%127[^\t]\t%u\t%39[^\t]\t%u", name, &h.version, hash, &h.flags) >= 3 &&
            plain_name(name)) {
            h.name = name;
            h.hash = hash;
            host_mods.push_back(h);
        }
    }
    if (!header) {
        log("manifest: not understood - treating the host as one without assetshare");
        state = State::legacy;
        flush_deferred_maps(m);
        return;
    }
    host_shares = true;
    state = State::syncing;
    auto locals = local_mods();
    // 1. Our server mods that the host does not run (or runs in another version): off for this game. First, so
    //    nothing we activate below conflicts with them.
    for (auto &l : locals) {
        if (!l.active || !(l.flags & SADKMOD_SERVER) || starts_with_icase(l.folder, ".temp_")) continue;
        bool kept = false;
        for (auto &h : host_mods)
            if (!_stricmp(h.name.c_str(), l.name.c_str()) && h.version == l.version && h.hash == mod_hash(l.folder))
                kept = true;
        if (kept) continue;
        int r = host().deactivate_mod(l.folder.c_str());
        switched_off.push_back(l.folder);
        room_message("Your server mod " + l.name + " is off for this game" +
                     (r == 1 ? " (its code stays loaded until it can be freed)." : "."));
    }
    // 2. The host's mods: our own copy if it is the same, else a download.
    for (auto &h : host_mods) {
        char ver[16];
        std::snprintf(ver, sizeof ver, "%u", h.version);
        const LocalMod *same = nullptr;
        for (auto &l : locals)
            if (!starts_with_icase(l.folder, ".temp_") && !_stricmp(l.name.c_str(), h.name.c_str()) &&
                l.version == h.version && mod_hash(l.folder) == h.hash)
                same = &l;
        if (same) {
            if (!same->active) {
                if (host().activate_mod(same->folder.c_str())) switched_on.push_back(same->folder);
            }
            summary.push_back(h.name + " " + ver + " (yours)");
            continue;
        }
        if (!accept_mods) {
            missing.push_back(h.name + " " + ver);
            continue;
        }
        Download d{Kind::mod, in_dir + "mod." + h.name + ".sas", "the server mod " + h.name + " (version " + ver + ")",
                   h.name, "", h.version, h.hash};
        if (!request(m, std::string(share_rel) + "mod." + h.name + "." + capability(), d))
            missing.push_back(h.name + " " + ver + " (could not ask the host)");
    }
    flush_deferred_maps(m);
    bool mods_pending = false;
    for (auto &p : pending) mods_pending |= p.kind == Kind::mod;
    if (!mods_pending) finish_sync(m);
}

// A downloaded mod: unpack into .temp_<name>, check it is what the host announced, activate.
void use_mod(Manager *m, const Download &d, const std::vector<archive::Entry> &entries)
{
    std::string folder = ".temp_" + d.name;
    char ver[16];
    std::snprintf(ver, sizeof ver, "%u", d.version);
    discard_temp(folder);   // a leftover of an earlier game
    std::string error;
    if (!archive::write_folder(mod_dir(folder), entries, &error)) {
        missing.push_back(d.name + " " + ver + " (" + error + ")");
        return;
    }
    if (!host().add_mod(mod_dir(folder).c_str())) {
        missing.push_back(d.name + " " + ver + " (not a loadable mod)");
        remove_tree(mod_dir(folder));
        return;
    }
    if (mod_hash(folder) != d.hash) {
        missing.push_back(d.name + " " + ver + " (the download differs from the host's copy)");
        discard_temp(folder);
        return;
    }
    if (!host().activate_mod(folder.c_str())) {
        missing.push_back(d.name + " " + ver + " (it failed to start, see wsock32_shim.txt)");
        discard_temp(folder);
        return;
    }
    downloaded.push_back(folder);
    summary.push_back(d.name + " " + ver + " (downloaded)");
    room_message("Server mod " + d.name + " " + ver + " downloaded and activated.");
    bool more = false;   // (this one has left `pending` already)
    for (auto &p : pending) more |= p.kind == Kind::mod;
    if (!more && state == State::syncing) finish_sync(m);
}

// ── Joiner: requests ─────────────────────────────────────────────────────────────────────────────────────────────
using RequestFile = sadk::Hook<fn::NComm_Manager::RequestFileFromHost>;

bool request(Manager *m, const std::string &remote, const Download &d)
{
    for (auto &p : pending)
        if (!_stricmp(p.local.c_str(), d.local.c_str())) return true;   // asked already
    CreateDirectoryA(in_dir.c_str(), nullptr);
    DeleteFileA(d.local.c_str());
    sadk::msvc::string r = sadk::msvc::string::borrow(remote.c_str(), remote.size());
    sadk::msvc::string l = sadk::msvc::string::borrow(d.local.c_str(), d.local.size());
    if (!m || !RequestFile::original(m, &r, &l)) return false;   // the game copies both strings
    pending.push_back(d);
    log("asked the host for %s (%s)", remote.c_str(), d.label.c_str());
    return true;
}

void request_map(Manager *m, const std::string &remote, const std::string &local)
{
    std::string file = remote.substr(remote.find_last_of('\\') + 1);
    Download d{Kind::map, in_dir + "map." + file + ".sas", "the map file " + file, file, local};
    request(m, std::string(share_rel) + "map." + file + "." + capability(), d);
}

void flush_deferred_maps(Manager *m)
{
    for (auto &[remote, local] : deferred_maps) {
        if (host_shares) {
            request_map(m, remote, local);
        } else {
            sadk::msvc::string r = sadk::msvc::string::borrow(remote.c_str(), remote.size());
            sadk::msvc::string l = sadk::msvc::string::borrow(local.c_str(), local.size());
            if (RequestFile::original(m, &r, &l))
                pending.push_back(Download{Kind::raw_map, local, "the map file " + remote.substr(remote.find_last_of('\\') + 1)});
        }
    }
    deferred_maps.clear();
}

// HandleEvent's map download (S 0040f256 / 0040f30d): repeated on every GameInformation while the map is missing.
bool SADK_THISCALL on_request_file(Manager *m, sadk::msvc::string *remote, sadk::msvc::string *local)
{
    std::string r(remote->view()), l(local->view());
    if (!starts_with_icase(r, "SAdK\\maps\\")) return RequestFile::original(m, remote, local);
    if (!accept_maps) {
        static DWORD said;
        if (GetTickCount() - said > 30000) room_message("Map downloads are switched off (assetshare.ini: AcceptServerMaps).");
        said = GetTickCount();
        return true;
    }
    if (state == State::idle || state == State::waiting_manifest) {   // asked before the manifest: wait for it
        for (auto &dm : deferred_maps)
            if (!_stricmp(dm.first.c_str(), r.c_str())) return true;
        deferred_maps.emplace_back(r, l);
        return true;
    }
    if (host_shares) {
        request_map(m, r, l);
        return true;
    }
    for (auto &p : pending)
        if (!_stricmp(p.local.c_str(), l.c_str())) return true;
    bool ok = RequestFile::original(m, remote, local);
    if (ok) pending.push_back(Download{Kind::raw_map, l, "the map file " + r.substr(r.find_last_of('\\') + 1)});
    return ok;
}

// ── Joiner: a download completes ────────────────────────────────────────────────────────────────────────────────
// No temp file: S2Tftp_Session_WriteBlock S 00426c70 answers the host with Error 2 (!TFTP_ERROR_WRITEERROR) and
// receives nothing more, the game's own refusal.
GameFILE *SADK_CDECL on_open_temp(sadk::msvc::string *out_path)
{
    bool is_map = pending.empty() || pending.front().kind == Kind::map || pending.front().kind == Kind::raw_map;
    if (is_map && !accept_maps) {
        room_message("Map downloads are switched off (assetshare.ini: AcceptServerMaps).");
        return nullptr;
    }
    GameFILE *f = fn::S2Tftp_OpenTempFile(out_path);
    if (f) {
        InterlockedIncrement(&downloads_active);
        download_bytes = download_reported = 0;
        download_last_activity = GetTickCount();
        if (pending.empty() || pending.front().kind != Kind::manifest)
            room_message("Downloading " + current_label() + " from the host...");
    }
    return f;
}

using game_size_t = game::crtdefs_h::size_t;
game_size_t SADK_CDECL on_fwrite(void *buf, game_size_t size, game_size_t count, GameFILE *f)
{
    game_size_t n = fn::_fwrite(buf, size, count, f);
    download_bytes += n * size;
    download_last_activity = GetTickCount();
    if (download_bytes - download_reported >= 256 * 1024) {
        char msg[200];
        download_reported = download_bytes;
        std::snprintf(msg, sizeof msg, "%lu KB of %s received...", download_bytes / 1024, current_label().c_str());
        room_message(msg);
    }
    return n;
}

std::int32_t SADK_CDECL on_abort_remove(char *path)
{
    std::string label = current_label();
    std::int32_t rc = fn::_remove(path);
    if (!pending.empty()) {
        Download d = pending.front();
        pending.pop_front();
        if (d.kind == Kind::manifest) {
            log("the host sent no manifest - it has no assetshare that shares server mods");
            state = State::legacy;
            flush_deferred_maps(manager());
        } else if (d.kind == Kind::mod) {
            char ver[16];
            std::snprintf(ver, sizeof ver, "%u", d.version);
            missing.push_back(d.name + " " + ver + " (the download failed)");
            bool more = false;
            for (auto &p : pending) more |= p.kind == Kind::mod;
            if (!more && state == State::syncing) finish_sync(manager());
        }
    }
    room_message("The download of " + label + " was aborted.");
    download_finished();
    return rc;
}

// S2TftpSession::CloseFile's rename of a finished download (S 00427b29, 00427b7e).
std::int32_t SADK_CDECL on_rename(char *from, char *to)
{
    bool ours = starts_with_icase(to, in_dir);
    if (!ours && !map_file_name(to)) {
        log("refused to store a download as %s", to);
        fn::_remove(from);
        download_finished();
        return -1;
    }
    DeleteFileA(to);
    std::int32_t rc = fn::_rename(from, to);
    Download d{Kind::raw_map, to, "a map file"};
    for (auto it = pending.begin(); it != pending.end(); ++it)
        if (!_stricmp(it->local.c_str(), to)) {
            d = *it;
            pending.erase(it);
            break;
        }
    Manager *m = manager();
    if (!ours) {   // a plain map file (a host without assetshare)
        room_message("Map file received: " + std::string(to + maps_dir.size()) + ".");
    } else {
        std::vector<archive::Entry> entries;
        std::string error;
        bool ok = rc == 0 && archive::read(to, entries, &error);
        if (!ok) log("%s: %s", d.label.c_str(), error.c_str());
        if (d.kind == Kind::manifest) {
            std::string text = ok && !entries.empty()
                                   ? std::string(entries[0].data.begin(), entries[0].data.end())
                                   : std::string();
            use_manifest(m, text);
        } else if (d.kind == Kind::mod) {
            if (ok) {
                use_mod(m, d, entries);
            } else {
                char ver[16];
                std::snprintf(ver, sizeof ver, "%u", d.version);
                missing.push_back(d.name + " " + ver + " (" + error + ")");
                bool more = false;
                for (auto &p : pending) more |= p.kind == Kind::mod;
                if (!more && state == State::syncing) finish_sync(m);
            }
        } else if (d.kind == Kind::map) {
            if (ok && entries.size() == 1 && map_file_name(d.final_path.c_str()) &&
                archive::write_file(d.final_path, entries[0].data.data(), entries[0].data.size())) {
                char msg[200];
                std::snprintf(msg, sizeof msg, "Map file received: %s (%lu KB, %u KB unpacked).", d.name.c_str(),
                              download_bytes / 1024, unsigned(entries[0].data.size() / 1024));
                room_message(msg);
            } else {
                room_message("The map file " + d.name + " could not be unpacked" + (ok ? "." : ": " + error + "."));
            }
        }
        DeleteFileA(to);
    }
    download_finished();
    return rc;
}

// ── Ready guard ──────────────────────────────────────────────────────────────────────────────────────────────────
bool SADK_THISCALL on_send_ready(Manager *mgr, bool ready)
{
    const char *why = nullptr;
    if (ready) {
        if (state == State::waiting_manifest || state == State::syncing)
            why = "Server mods for this game are being set up - you can get ready once that is done.";
        else if (state == State::failed)
            why = "This game needs server mods you don't have - you can't get ready.";
        else if (download_running())
            why = "Still downloading - you can get ready once it is complete.";
        else if (!session_map_present(mgr))
            why = "You don't have this map (yet) - you can't get ready.";
    }
    if (why) {
        room_message(why);
        return fn::NComm_Manager::SendPlayerReadyEvent(mgr, false);
    }
    return fn::NComm_Manager::SendPlayerReadyEvent(mgr, ready);
}

// ── Session events ───────────────────────────────────────────────────────────────────────────────────────────────
using HandleEvent = sadk::Hook<fn::NComm_Manager::HandleEvent>;
bool SADK_THISCALL on_handle_event(Manager *m, game::NComm::EventBase *ev)
{
    auto type = static_cast<std::uint32_t>(ev->typeId);   // read first: the handler may consume the event
    std::int32_t source = ev->sourceNetId;
    bool ok = HandleEvent::original(m, ev);
    // Someone joins this host. The host handles its own UserInformation too, under the host id 0xEFFFFFCC (the id
    // RequestFileFromHost sends to; KickPlayer S 0040b470 never kicks it): only remote players count.
    if (type == EV_USER_INFORMATION && is_host_online(m) && static_cast<std::uint32_t>(source) != HOST_NET_ID &&
        source != fn::NComm_Manager_NetworkVcall_30(m)) {
        bool known = false;
        for (auto &j : joiners) known |= j.net_id == source;
        if (!known) joiners.push_back(Joiner{source, GetTickCount(), false});
    }
    if (type == EV_GAME_INFORMATION && is_joiner(m) && state == State::idle) {
        state = State::waiting_manifest;
        manifest_asked_at = GetTickCount();
        Download d{Kind::manifest, in_dir + "manifest.sas", "the host's list of server mods"};
        if (!request(m, std::string(share_rel) + "manifest." + capability(), d))
            state = State::idle;   // not connected yet (RequestFileFromHost refuses): again at the next one
    }
    return ok;
}

using MainLoop = sadk::Hook<fn::NComm_Manager::Process_MainLoop>;
bool SADK_THISCALL on_main_loop(Manager *m)
{
    bool ok = MainLoop::original(m);
    DWORD now = GetTickCount();
    if (state == State::waiting_manifest && now - manifest_asked_at > MANIFEST_TIMEOUT_MS) {
        log("no manifest from the host within %lu s - it has no assetshare that shares server mods",
            MANIFEST_TIMEOUT_MS / 1000);
        state = State::legacy;
        flush_deferred_maps(m);
    }
    if (is_host_online(m))
        for (auto it = joiners.begin(); it != joiners.end();) {
            if (!it->has_assetshare && now - it->joined_at > KICK_AFTER_MS) {
                log("kicking net id %08x: it never asked for the manifest (no assetshare)", unsigned(it->net_id));
                fn::NComm_Manager::KickPlayer(m, it->net_id, const_cast<char *>(kick_reason), true);
                it = joiners.erase(it);
            } else {
                ++it;
            }
        }
    return ok;
}

// The end of a network session: everything this game changed is put back.
using Shutdown = sadk::Hook<fn::NComm_Manager::Shutdown>;
bool SADK_THISCALL on_shutdown(Manager *m, bool keep)
{
    bool ok = Shutdown::original(m, keep);
    if (state != State::idle || !downloaded.empty() || !switched_off.empty() || !switched_on.empty()) {
        for (auto &f : downloaded) discard_temp(f);
        for (auto &f : switched_on) host().deactivate_mod(f.c_str());
        for (auto &f : switched_off) host().activate_mod(f.c_str());
        log("session ended: %u downloaded mod(s) removed, %u of ours back on, %u off again",
            unsigned(downloaded.size()), unsigned(switched_off.size()), unsigned(switched_on.size()));
    }
    retry_leftovers();
    state = State::idle;
    host_shares = false;
    pending.clear();
    deferred_maps.clear();
    downloaded.clear();
    switched_on.clear();
    switched_off.clear();
    summary.clear();
    missing.clear();
    joiners.clear();
    InterlockedExchange(&downloads_active, 0);
    return ok;
}

// The build checksum leaves out server mods' files (see the top).
using Checksum = sadk::Hook<fn::GameData_ComputeBuildChecksum>;
std::uint32_t SADK_CDECL on_checksum(std::int32_t *count, std::int32_t *size)
{
    host().redirect_server_mods(false);
    std::uint32_t cs = Checksum::original(count, size);
    host().redirect_server_mods(true);
    return cs;
}

// The map's location type (game information +0x229) and "download allowed" (+0x228): with type 3 (Documents\SAdK\maps)
// and downloads allowed, a joiner that lacks the map asks for it (NComm_Manager::HandleEvent, docs/s2tftp.md).
using GameSettings = sadk::Hook<fn::NComm_Manager::SetGameSettings>;
void SADK_THISCALL on_game_settings(Manager *m, sadk::msvc::string *map, game::NComm::NetGUID *guid, std::int32_t max_players,
                                    std::int32_t unused, std::int32_t resources, std::int32_t win, std::int32_t fog,
                                    std::int32_t location, char downloadable, char ranked)
{
    if (is_host_online(m)) {
        location = MAP_LOCATION_USER;
        downloadable = 1;
    }
    GameSettings::original(m, map, guid, max_players, unused, resources, win, fog, location, downloadable, ranked);
}

void SADK_STDCALL append_maps(std::int32_t location, void *list, void *names, float *rgba)
{
    static float user_colour[4] = {1.0f, 0.85f, 0.55f, 1.0f};   // custom maps: warm tint
    fn::SelectMapDialog_AppendMapFiles(location, list, names, rgba);
    fn::SelectMapDialog_AppendMapFiles(MAP_LOCATION_USER, list, names, user_colour);
}

// Downloaded mods of an earlier run that ended without cleaning up (a crash): <game>\mods\.temp_*.
void remove_stale_temp_mods()
{
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(sadk::game_path("mods\\.temp_*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            log("removing %s, left over from an earlier run", fd.cFileName);
            remove_tree(mod_dir(fd.cFileName));
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}

}  // namespace assetshare

bool assetshare_start()
{
    using namespace assetshare;
    sadk::Ini ini = sadk::mod_settings();
    accept_maps = ini.get_bool("AssetShare", "AcceptServerMaps", true);
    accept_mods = ini.get_bool("AssetShare", "AcceptServerMods", true);
    char d[MAX_PATH];
    if (SHGetFolderPathA(nullptr, CSIDL_PERSONAL, nullptr, 0, d) == S_OK) {   // as Sys_GetMyDocumentsPath
        docs = std::string(d) + "\\";
        CreateDirectoryA((docs + "SAdK").c_str(), nullptr);
        maps_dir = docs + "SAdK\\maps\\";
        share_dir = docs + share_rel;
        in_dir = share_dir + "in\\";
        CreateDirectoryA(maps_dir.c_str(), nullptr);
        CreateDirectoryA(share_dir.c_str(), nullptr);
        CreateDirectoryA(in_dir.c_str(), nullptr);
    }
    if (!sadk::verifying()) remove_stale_temp_mods();
    // Single calls inside one function each, found by sadk::calls; the last number is how many there must be.
    namespace net = fn::ai::net;
    int ok = sadk::patch_calls(fn::LobbyMenu::SelectMapDialog::RefreshMapList, fn::SelectMapDialog_AppendMapFiles,
                               (void *)append_maps, "map list + Documents\\SAdK\\maps", 1);
    ok += sadk::patch_calls(fn::S2Tftp_Session_ReadNextBlock, fn::_fopen_s, (void *)serve_fopen, "what a host sends", 1);
    ok += sadk::patch_calls(net::S2TftpSession::CloseFile, fn::_rename, (void *)on_rename, "download destination check", 2);
    ok += sadk::patch_calls(fn::LobbyMenu::SetupGameDialog::HandleButtonClicks, fn::NComm_Manager::SendPlayerReadyEvent,
                            (void *)on_send_ready, "ready guard (Ready button)", 1);
    ok += sadk::patch_calls(fn::S2Tftp_Session_WriteBlock, fn::S2Tftp_OpenTempFile, (void *)on_open_temp,
                            "download start", 1);
    ok += sadk::patch_calls(fn::S2Tftp_Session_WriteBlock, fn::_fwrite, (void *)on_fwrite, "download progress", 1);
    ok += sadk::patch_calls(net::S2TftpSession::CloseFile, fn::_remove, (void *)on_abort_remove, "download abort", 1);
    int hooks = BeginSend::install(on_begin_send, "S2TFTP: 4 KB blocks; who asks for the manifest") +
                RequestFile::install(on_request_file, "map requests as archives") +
                HandleEvent::install(on_handle_event, "join: fetch the manifest / note a joiner") +
                MainLoop::install(on_main_loop, "manifest timeout, kick joiners without assetshare") +
                Shutdown::install(on_shutdown, "session end: put the mods back") +
                Checksum::install(on_checksum, "build checksum without server mods' files") +
                GameSettings::install(on_game_settings, "maps advertised as downloadable");
    log("%d of 8 patches, %d of 7 hooks active (maps folder %s; maps %s, server mods %s; this side %s LZMS)", ok, hooks,
        maps_dir.c_str(), accept_maps ? "accepted" : "refused", accept_mods ? "accepted" : "refused",
        archive::can_compress() ? "can use" : "cannot use");
    return ok == 8 && hooks == 7;
}

SADKMOD_MAIN(assetshare_start, 2, SADKMOD_CLIENT)
