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
//
// Layout of this file: settings and paths, room messages, the download queue, mods (ours and the host's), the host
// side (serving, who has assetshare), the joiner side (manifest, plan, requests, finished downloads), the ready
// guard, session events, the remaining hooks, start-up.
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
constexpr DWORD STALL_MS = 60000;              // a download without data for this long no longer blocks "ready"
constexpr std::int32_t FILE_NOT_FOUND = 2;      // fopen_s result -> the game answers !TFTP_ERROR_FILENOTFOUND
const char kick_reason[] = "This game needs the assetshare mod: install it with SAdK-ServerConfig.";

bool accept_maps = true, accept_mods = true;   // assetshare.ini
std::string docs;                              // <My Documents>\ (with the backslash)
std::string maps_dir;                          // <My Documents>\SAdK\maps\ ...
std::string share_dir;                         // <My Documents>\SAdK\assetshare\  host: archives it serves
std::string in_dir;                            // <My Documents>\SAdK\assetshare\in\  joiner: downloads land here
const char share_rel[] = "SAdK\\assetshare\\";  // the same, relative to My Documents (what a joiner asks for)

Manager *manager() { return static_cast<Manager *>(fn::NComm_GetManager()); }
// NComm_Manager::nMode: 1/3 joined a network game, 2/4 hosting one.
bool is_joiner(Manager *m) { return m && (m->nMode == 1 || m->nMode == 3); }
bool is_host_online(Manager *m) { return m && (m->nMode == 2 || m->nMode == 4); }
// What this side can unpack; the host packs every archive for the joiner that asked (the request's suffix).
const char *capability() { return archive::can_compress() ? "lzms" : "stored"; }

bool starts_with_icase(const std::string &s, const std::string &prefix)
{
    return s.size() >= prefix.size() && _strnicmp(s.c_str(), prefix.c_str(), prefix.size()) == 0;
}

bool has_ext(const std::string &name, const char *ext)   // ext: 4 characters, ".s2m"
{
    return name.size() >= 4 && !_stricmp(name.c_str() + name.size() - 4, ext);
}

std::string file_part(const std::string &path) { return path.substr(path.find_last_of('\\') + 1); }

// ── File names from the other side ──────────────────────────────────────────────────────────────────────────────
// Names a host asks for or a joiner receives come from another player's machine: none may reach outside its folder.

// A plain name: no path, no drive, no "..", no control characters, at most 120 characters.
bool plain_name(const std::string &n)
{
    if (n.empty() || n.size() > 120 || n.find("..") != std::string::npos) return false;
    for (char c : n)
        if (c == '\\' || c == '/' || c == ':' || static_cast<unsigned char>(c) < 0x20) return false;
    return true;
}

// The file part of `path` if it is <maps_dir><plain name>.s2m|.bmp, else nullptr.
const char *map_file_name(const char *path)
{
    if (maps_dir.empty() || !starts_with_icase(path, maps_dir)) return nullptr;
    const char *name = path + maps_dir.size();
    std::string n = name;
    if (n.size() < 5 || !plain_name(n) || !(has_ext(n, ".s2m") || has_ext(n, ".bmp"))) return nullptr;
    return name;
}

// A file that may land in the maps folder: a plain name ending in .s2m, .bmp, .bin or .lua.
bool companion_name(const std::string &n)
{
    return n.size() >= 5 && plain_name(n) &&
           (has_ext(n, ".s2m") || has_ext(n, ".bmp") || has_ext(n, ".bin") || has_ext(n, ".lua"));
}

// ── Messages in the pre-game room ───────────────────────────────────────────────────────────────────────────────
using sadk::ui::room_message;

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
enum class Kind {
    manifest,   // the host's server-mod list (archive)
    mod,        // one server mod folder (archive)
    map,        // a map file and the files that belong to it (archive)
    raw_map     // a map file as the game itself fetches it, from a host without assetshare (no archive)
};
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

Download raw_map_download(const std::string &local, const std::string &remote)
{
    return Download{Kind::raw_map, local, "the map file " + file_part(remote)};
}

bool mods_pending()
{
    for (auto &p : pending)
        if (p.kind == Kind::mod) return true;
    return false;
}

std::string current_label() { return pending.empty() ? std::string("a map file") : pending.front().label; }

bool request(Manager *m, const std::string &remote, const Download &d);

// ── Joiner state ─────────────────────────────────────────────────────────────────────────────────────────────────
// idle -> waiting_manifest (asked the host) -> syncing (mods being switched / downloaded) -> ready or failed.
// `legacy` is not entered at present.
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

std::string mod_label(const std::string &name, std::uint32_t version) { return name + " " + std::to_string(version); }

// ── Download progress (all transfers) ───────────────────────────────────────────────────────────────────────────
// downloads_active counts the game's open temp files (on_open_temp up, on_rename / on_abort_remove down). A
// transfer the host stops serving never closes, hence the stall timeout.
volatile LONG downloads_active;
unsigned long download_bytes, download_reported;
DWORD download_last_activity;

bool download_running()
{
    if (downloads_active > 0 && GetTickCount() - download_last_activity > STALL_MS) {
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

// Whether this side has the session's map, the game's own lookup: the map's GUID from the game information, as an
// NCore::UUID, through GameFile_FindMapByGuidAnyType.
bool session_map_present(Manager *mgr)
{
    // Out-buffers for the game: NetGUID (vtable + 4 dwords, 0x14 bytes) and NCore::UUID (constructed, GUID at
    // +8..+0x17; the map search compares it there), both with room to spare. The name comes back as a std::string
    // the game may allocate.
    alignas(4) unsigned char guid[32] = {}, uuid[64] = {};
    sadk::msvc::owned_string name;   // the game may allocate it
    std::int32_t type = 0;
    auto *info = &mgr->gameInformation;
    auto *g = static_cast<game::NComm::NetGUID *>(fn::NComm::EventGameInformation::GetMapGuid(info, guid));
    fn::NComm::NetGUID::ToUUID(g, uuid);
    return fn::GameFile_FindMapByGuidAnyType(uuid, &name, &type);
}

// ── Mods: what the host has, what we have ───────────────────────────────────────────────────────────────────────
using LocalMod = sadk::host::ModInfo;
std::vector<LocalMod> local_mods() { return sadk::mods::list(); }
std::string mod_hash(const std::string &folder) { return sadk::mods::content_hash(folder); }
std::string mod_dir(const std::string &folder) { return sadk::game_path("mods\\") + folder; }

bool is_temp(const LocalMod &m) { return starts_with_icase(m.folder, ".temp_"); }
// One of our own server mods running now: what a host announces and serves, what a joiner switches off.
bool is_own_active_server_mod(const LocalMod &m) { return m.active && (m.flags & SADKMOD_SERVER) && !is_temp(m); }

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
    sadk::mods::deactivate(folder);
    sadk::mods::free_pending();
    sadk::mods::forget(folder);   // false if it was never listed or is still waiting to be freed
    if (remove_tree(mod_dir(folder))) return;
    log("%s could not be removed yet (its mod.dll is still in use) - later", folder.c_str());
    leftovers.push_back(folder);
}

// The leftovers whose mod.dll has been freed since: out of the list, deleted. Those still in use stay leftovers.
void retry_leftovers()
{
    sadk::mods::free_pending();
    std::vector<std::string> still;
    for (auto &f : leftovers)
        if (!sadk::mods::forget(f) && GetFileAttributesA(mod_dir(f).c_str()) != INVALID_FILE_ATTRIBUTES &&
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

// The manifest: a header line, then one tab-separated line per server mod (name, version, content hash, flags).
std::string manifest_text()
{
    std::string t = "assetshare 1\n";
    for (auto &m : local_mods())
        if (is_own_active_server_mod(m)) {
            char line[512];
            std::snprintf(line, sizeof line, "mod\t%s\t%u\t%s\t%u\n", m.name.c_str(), m.version,
                          mod_hash(m.folder).c_str(), m.flags);
            t += line;
        }
    return t;
}

bool manifest_entries(std::vector<archive::Entry> &entries, std::string &label)
{
    std::string t = manifest_text();
    entries.push_back({"manifest.txt", std::vector<std::uint8_t>(t.begin(), t.end())});
    label = "the server-mod list";
    return true;
}

// The whole folder of the running server mod `name` (only those: a joiner cannot fetch anything else of ours).
bool mod_entries(const std::string &name, std::vector<archive::Entry> &entries, std::string &label)
{
    const LocalMod *found = nullptr;
    auto mods = local_mods();
    for (auto &m : mods)
        if (is_own_active_server_mod(m) && !_stricmp(m.name.c_str(), name.c_str())) found = &m;
    if (!plain_name(name) || !found || !archive::read_folder(mod_dir(found->folder), entries)) {
        log("serve: no server mod %s to send", name.c_str());
        return false;
    }
    label = "server mod " + name;
    return true;
}

// A map comes with files of the same name next to it: <map>.bin, its environment data
// (CEnviromentMgr::LoadMapEnvData S 00685580), <map>.lua, its script (GameFile_LoadMap S 005aa7b0), and
// <map>_<name>.lua, its cutscene scripts (Cutscene_BuildScriptPath S 0078a940). They go with the .s2m.
void add_map_companions(const std::string &path, const std::string &file, std::vector<archive::Entry> &entries)
{
    std::string dir = path.substr(0, path.find_last_of('\\') + 1), base = file.substr(0, file.size() - 4);
    std::vector<std::string> names{base + ".bin", base + ".lua"};
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA((dir + base + "_*.lua").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do names.push_back(fd.cFileName);
        while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    for (auto &n : names) {
        std::vector<std::uint8_t> extra;
        if (archive::read_file(dir + n, extra)) entries.push_back({n, std::move(extra)});
    }
}

// A map file from Documents\SAdK\maps, else from the game's own free-game maps, with what belongs to it.
bool map_entries(const std::string &file, std::vector<archive::Entry> &entries, std::string &label)
{
    std::vector<std::uint8_t> data;
    std::string path = maps_dir + file;
    if (!map_file_name(path.c_str())) return false;
    if (GetFileAttributesA(path.c_str()) == INVALID_FILE_ATTRIBUTES)
        path = sadk::game_path("data\\game\\maps\\Freegamemaps\\") + file;
    if (!archive::read_file(path, data)) {
        log("serve: map file %s not found", file.c_str());
        return false;
    }
    entries.push_back({file, std::move(data)});
    label = "map file " + file;
    if (has_ext(file, ".s2m")) {
        add_map_companions(path, file, entries);
        if (entries.size() > 1) label += " with " + std::to_string(entries.size() - 1) + " file(s) that belong to it";
    }
    return true;
}

// Builds the archive for a request below share_dir ("manifest.lzms", "mod.<name>.stored", ...); returns its path,
// or "" (logged) if there is nothing to send.
std::string build_for_request(const std::string &rest)
{
    std::size_t dot = rest.find_last_of('.');
    if (dot == std::string::npos) return {};
    std::string what = rest.substr(0, dot), cap = rest.substr(dot + 1);
    std::vector<archive::Entry> entries;
    std::string label;
    bool found = what == "manifest"                 ? manifest_entries(entries, label)
                 : starts_with_icase(what, "mod.")  ? mod_entries(what.substr(4), entries, label)
                 : starts_with_icase(what, "map.")  ? map_entries(what.substr(4), entries, label)
                                                    : false;
    if (!found) return {};
    CreateDirectoryA((share_dir + "out").c_str(), nullptr);
    std::string out = share_dir + "out\\" + rest + ".sas";
    archive::Method used;
    std::string error;
    if (!archive::write(out, entries, cap == "lzms" ? archive::lzms : archive::stored, &used, &error)) {
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

// S2Tftp_Session_ReadNextBlock's fopen_s (S 00426b14): only maps and assetshare's files are ever sent. The path is
// what the joiner asked for, below the host's My Documents; requests for assetshare's files are built on the spot.
std::uint32_t SADK_CDECL serve_fopen(GameFILE **f, char *path, char *mode)
{
    *f = nullptr;
    if (starts_with_icase(path, share_dir) && !starts_with_icase(path, in_dir)) {
        std::string file = build_for_request(path + share_dir.size());
        return file.empty() ? FILE_NOT_FOUND : fn::_fopen_s(f, file.data(), mode);
    }
    const char *name = map_file_name(path);
    if (!name) {
        log("serve: refused a request for %s (not a map file)", path);
        return FILE_NOT_FOUND;
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
    return FILE_NOT_FOUND;
}

// ── Host: who has assetshare ─────────────────────────────────────────────────────────────────────────────────────
// A joiner with assetshare asks for the manifest as soon as the game information reaches it; one that has not done so
// KICK_AFTER_MS after joining has no assetshare.
bool runs_server_mods()
{
    for (auto &m : local_mods())
        if (is_own_active_server_mod(m)) return true;
    return false;
}

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
// The end of the sync: every host mod is either running here or listed in `missing`.
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

// A host mod that could not be set up (download or unpack failed); the sync ends with the last mod download.
void mod_failed(Manager *m, const Download &d, const std::string &why)
{
    missing.push_back(mod_label(d.name, d.version) + " (" + why + ")");
    if (!mods_pending() && state == State::syncing) finish_sync(m);
}

void flush_deferred_maps(Manager *m);

void apply_host_set(Manager *m, const std::vector<HostMod> &host_mods);

// No manifest (no assetshare on the host, or an older one): the host runs no server mods we could get, so ours are
// switched off for this game, as for a host that runs none. Its stock checksum still matches ours, since server mods'
// files are left out of it.
void no_manifest(Manager *m, const char *why)
{
    log("no manifest from the host (%s): this game runs without server mods", why);
    host_shares = false;
    apply_host_set(m, {});
}

// Parses manifest_text()'s format; lines it does not know are skipped, a missing header means "no manifest".
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
        no_manifest(m, "not understood");
        return;
    }
    host_shares = true;
    apply_host_set(m, host_mods);
}

// Our copy is the host's when name, version and content hash agree. The hash (sadk::mods::content_hash) covers every
// file of the folder, the mod's .ini included, and a download packs the whole folder (archive::read_folder): a copy
// whose settings differ from the host's is switched off for the game and the host's copy, its .ini with it, is
// downloaded and run instead. A server mod's settings are the host's for the whole match.
bool same_as_host(const LocalMod &l, const HostMod &h)
{
    return !_stricmp(l.name.c_str(), h.name.c_str()) && l.version == h.version && mod_hash(l.folder) == h.hash;
}

// 1. Our server mods that the host does not run (or runs in another version): off for this game. First, so nothing
//    activated afterwards conflicts with them.
void switch_off_unshared(const std::vector<LocalMod> &locals, const std::vector<HostMod> &host_mods)
{
    for (auto &l : locals) {
        if (!is_own_active_server_mod(l)) continue;
        bool kept = false;
        for (auto &h : host_mods) kept |= same_as_host(l, h);
        if (kept) continue;
        auto r = sadk::mods::deactivate(l.folder);
        switched_off.push_back(l.folder);
        room_message("Your server mod " + l.name + " is off for this game" +
                     (r == sadk::host::Unload::busy ? " (its code stays loaded until it can be freed)." : "."));
    }
}

// 2. One of the host's mods: our own copy if it is the same, else a download (unless refused by the ini).
void provide_host_mod(Manager *m, const std::vector<LocalMod> &locals, const HostMod &h)
{
    std::string label = mod_label(h.name, h.version);
    const LocalMod *same = nullptr;
    for (auto &l : locals)
        if (!is_temp(l) && same_as_host(l, h)) same = &l;
    if (same) {
        if (!same->active && sadk::mods::activate(same->folder)) switched_on.push_back(same->folder);
        summary.push_back(label + " (yours)");
        return;
    }
    if (!accept_mods) {
        missing.push_back(label);
        return;
    }
    Download d{Kind::mod, in_dir + "mod." + h.name + ".sas",
               "the server mod " + h.name + " (version " + std::to_string(h.version) + ")", h.name, "", h.version, h.hash};
    if (!request(m, std::string(share_rel) + "mod." + h.name + "." + capability(), d))
        missing.push_back(label + " (could not ask the host)");
}

// The host's set of server mods becomes ours for this game. Maps asked for meanwhile are requested now; the sync ends
// here unless mods are downloading (then with the last of them, use_mod / mod_failed).
void apply_host_set(Manager *m, const std::vector<HostMod> &host_mods)
{
    state = State::syncing;
    auto locals = local_mods();
    switch_off_unshared(locals, host_mods);
    for (auto &h : host_mods) provide_host_mod(m, locals, h);
    flush_deferred_maps(m);
    if (!mods_pending()) finish_sync(m);
}

// A downloaded mod: unpack into .temp_<name>, check it is what the host announced, activate. A failure goes through
// mod_failed like a failed download, so the sync still ends with the last mod.
void use_mod(Manager *m, const Download &d, const std::vector<archive::Entry> &entries)
{
    std::string folder = ".temp_" + d.name, label = mod_label(d.name, d.version);
    discard_temp(folder);   // a leftover of an earlier game
    std::string error;
    if (!archive::write_folder(mod_dir(folder), entries, &error)) {
        mod_failed(m, d, error);
        return;
    }
    if (!sadk::mods::add(mod_dir(folder))) {
        remove_tree(mod_dir(folder));
        mod_failed(m, d, "not a loadable mod");
        return;
    }
    if (mod_hash(folder) != d.hash) {
        discard_temp(folder);
        mod_failed(m, d, "the download differs from the host's copy");
        return;
    }
    if (!sadk::mods::activate(folder)) {
        discard_temp(folder);
        mod_failed(m, d, "it failed to start, see wsock32_shim.txt");
        return;
    }
    downloaded.push_back(folder);
    summary.push_back(label + " (downloaded)");
    room_message("Server mod " + label + " downloaded and activated.");
    if (!mods_pending() && state == State::syncing) finish_sync(m);   // (this one has left `pending` already)
}

// ── Joiner: requests ─────────────────────────────────────────────────────────────────────────────────────────────
using RequestFile = sadk::Hook<fn::NComm_Manager::RequestFileFromHost>;

// The game's own request (the original, not our hook); `remote` and `local` are copied by the game.
bool game_request(Manager *m, const std::string &remote, const std::string &local)
{
    sadk::msvc::string r = sadk::msvc::string::borrow(remote.c_str(), remote.size());
    sadk::msvc::string l = sadk::msvc::string::borrow(local.c_str(), local.size());
    return m && RequestFile::original(m, &r, &l);
}

// Asks the host for `remote` (below its My Documents) unless the same download is queued already.
bool request(Manager *m, const std::string &remote, const Download &d)
{
    for (auto &p : pending)
        if (!_stricmp(p.local.c_str(), d.local.c_str())) return true;   // asked already
    CreateDirectoryA(in_dir.c_str(), nullptr);
    DeleteFileA(d.local.c_str());
    if (!game_request(m, remote, d.local)) return false;
    pending.push_back(d);
    log("asked the host for %s (%s)", remote.c_str(), d.label.c_str());
    return true;
}

// A map through a host with assetshare: as an archive (map.<file>.<cap>), unpacked into the maps folder on arrival.
void request_map(Manager *m, const std::string &remote, const std::string &local)
{
    std::string file = file_part(remote);
    Download d{Kind::map, in_dir + "map." + file + ".sas", "the map file " + file, file, local};
    request(m, std::string(share_rel) + "map." + file + "." + capability(), d);
}

// The maps the game asked for before the manifest came: as archives if the host shares, else the game's own way.
void flush_deferred_maps(Manager *m)
{
    for (auto &[remote, local] : deferred_maps) {
        if (host_shares)
            request_map(m, remote, local);
        else if (game_request(m, remote, local))
            pending.push_back(raw_map_download(local, remote));
    }
    deferred_maps.clear();
}

// HandleEvent's map download (S 0040f256 / 0040f30d): repeated on every GameInformation while the map is missing.
bool SADK_THISCALL on_request_file(Manager *m, sadk::msvc::string *remote, sadk::msvc::string *local)
{
    std::string r(remote->view()), l(local->view());
    if (!starts_with_icase(r, "SAdK\\maps\\")) return RequestFile::original(m, remote, local);
    if (!accept_maps) {
        static DWORD said;   // the request repeats with every GameInformation: say it at most every 30 s
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
    if (ok) pending.push_back(raw_map_download(l, r));
    return ok;
}

// ── Joiner: a download starts, runs, ends ───────────────────────────────────────────────────────────────────────
// S2Tftp_Session_WriteBlock's temp file for the first block. No temp file: S2Tftp_Session_WriteBlock S 00426c70
// answers the host with Error 2 (!TFTP_ERROR_WRITEERROR) and receives nothing more, the game's own refusal.
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

// S2Tftp_Session_WriteBlock's fwrite of each block: progress in the room every 256 KB.
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

// S2TftpSession::CloseFile's remove of an aborted download's temp file: the running download (head of `pending`)
// failed.
std::int32_t SADK_CDECL on_abort_remove(char *path)
{
    std::string label = current_label();
    std::int32_t rc = fn::_remove(path);
    if (!pending.empty()) {
        Download d = pending.front();
        pending.pop_front();
        if (d.kind == Kind::manifest)
            no_manifest(manager(), "the transfer failed");
        else if (d.kind == Kind::mod)
            mod_failed(manager(), d, "the download failed");
    }
    room_message("The download of " + label + " was aborted.");
    download_finished();
    return rc;
}

// The queued download that the game just stored as `to` (taken out of `pending`); a raw map if none matches.
Download take_pending(const char *to)
{
    for (auto it = pending.begin(); it != pending.end(); ++it)
        if (!_stricmp(it->local.c_str(), to)) {
            Download d = *it;
            pending.erase(it);
            return d;
        }
    return Download{Kind::raw_map, to, "a map file"};
}

// A map archive: the map file and what belongs to it, plain names only, into the maps folder.
void unpack_map(const Download &d, const std::vector<archive::Entry> &entries, bool ok, const std::string &error)
{
    std::size_t written = 0, bytes = 0;
    if (ok && map_file_name(d.final_path.c_str()))
        for (auto &e : entries)
            if (companion_name(e.path) && archive::write_file(maps_dir + e.path, e.data.data(), e.data.size())) {
                written++;
                bytes += e.data.size();
            }
    if (!written) {
        room_message("The map file " + d.name + " could not be unpacked" + (ok ? "." : ": " + error + "."));
        return;
    }
    char msg[200];
    std::snprintf(msg, sizeof msg, "Map file received: %s%s (%lu KB, %u KB unpacked).", d.name.c_str(),
                  written > 1 ? (" and " + std::to_string(written - 1) + " file(s) of the map").c_str() : "",
                  download_bytes / 1024, unsigned(bytes / 1024));
    room_message(msg);
}

// One of our archives arrived as `to` (in_dir): read it and use it by kind; the archive is deleted afterwards.
void use_archive(Manager *m, const Download &d, const char *to, bool stored)
{
    std::vector<archive::Entry> entries;
    std::string error;
    bool ok = stored && archive::read(to, entries, &error);
    if (!ok) log("%s: %s", d.label.c_str(), error.c_str());
    if (d.kind == Kind::manifest)
        use_manifest(m, ok && !entries.empty() ? std::string(entries[0].data.begin(), entries[0].data.end())
                                               : std::string());
    else if (d.kind == Kind::mod && ok)
        use_mod(m, d, entries);
    else if (d.kind == Kind::mod)
        mod_failed(m, d, error);
    else if (d.kind == Kind::map)
        unpack_map(d, entries, ok, error);
    DeleteFileA(to);
}

// S2TftpSession::CloseFile's rename of a finished download (S 00427b29, 00427b7e): `to` is the name the host's side
// chose, so only our download folder and plain map files in the maps folder are allowed.
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
    Download d = take_pending(to);
    if (ours)
        use_archive(manager(), d, to, rc == 0);
    else   // a plain map file (a host without assetshare)
        room_message("Map file received: " + std::string(to + maps_dir.size()) + ".");
    download_finished();
    return rc;
}

// ── Ready guard ──────────────────────────────────────────────────────────────────────────────────────────────────
// SetupGameDialog's Ready button: "ready" goes out only when this side can start the match; otherwise "not ready"
// with the reason in the room.
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

// ── Session events (sadk::events) ────────────────────────────────────────────────────────────────────────────────
// Host: someone joins. The host handles its own UserInformation too, under the host id 0xEFFFFFCC (the id
// RequestFileFromHost sends to; KickPlayer S 0040b470 never kicks it): only remote players count.
// NComm_Manager_NetworkVcall_30 S 004089a0 (network object +0x340, vtable slot 0x30) is excluded as well
// [inferred: this side's own net id].
void note_joiner(Manager *m, std::int32_t source)
{
    if (static_cast<std::uint32_t>(source) == HOST_NET_ID || source == fn::NComm_Manager_NetworkVcall_30(m)) return;
    for (auto &j : joiners)
        if (j.net_id == source) return;
    joiners.push_back(Joiner{source, GetTickCount(), false});
}

// Joiner: the host's game information arrived: ask for its manifest (once per session).
void ask_for_manifest(Manager *m)
{
    state = State::waiting_manifest;
    manifest_asked_at = GetTickCount();
    Download d{Kind::manifest, in_dir + "manifest.sas", "the host's list of server mods"};
    if (!request(m, std::string(share_rel) + "manifest." + capability(), d))
        state = State::idle;   // not connected yet (RequestFileFromHost refuses): again at the next one
}

void on_net_event(void *, Manager *m, game::NComm::EventBase *ev)
{
    auto type = static_cast<std::uint32_t>(ev->typeId);
    if (type == EV_USER_INFORMATION && is_host_online(m)) note_joiner(m, ev->sourceNetId);
    if (type == EV_GAME_INFORMATION && is_joiner(m) && state == State::idle) ask_for_manifest(m);
}

// Host: a joiner without assetshare is only kicked by a host that runs server mods: without them it can play anyway.
void kick_joiners_without_assetshare(Manager *m, DWORD now)
{
    for (auto it = joiners.begin(); it != joiners.end();) {
        if (!it->has_assetshare && now - it->joined_at > KICK_AFTER_MS) {
            log("kicking net id %08x: it never asked for the manifest (no assetshare)", unsigned(it->net_id));
            fn::NComm_Manager::KickPlayer(m, it->net_id, const_cast<char *>(kick_reason), true);
            it = joiners.erase(it);
        } else {
            ++it;
        }
    }
}

void on_frame(void *)
{
    Manager *m = manager();
    if (!m) return;
    DWORD now = GetTickCount();
    if (state == State::waiting_manifest && now - manifest_asked_at > MANIFEST_TIMEOUT_MS)
        no_manifest(m, "none within 15 s");
    if (is_host_online(m) && !joiners.empty() && runs_server_mods()) kick_joiners_without_assetshare(m, now);
}

// The end of a network session: everything this game changed is put back.
void on_session_end(void *)
{
    if (state != State::idle || !downloaded.empty() || !switched_off.empty() || !switched_on.empty()) {
        for (auto &f : downloaded) discard_temp(f);
        for (auto &f : switched_on) sadk::mods::deactivate(f);
        for (auto &f : switched_off) sadk::mods::activate(f);
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
}

// ── Other hooks ──────────────────────────────────────────────────────────────────────────────────────────────────
// The build checksum leaves out server mods' files (see the top): sadkmod's redirection of their files is off while
// the game computes it.
using Checksum = sadk::Hook<fn::GameData_ComputeBuildChecksum>;
std::uint32_t SADK_CDECL on_checksum(std::int32_t *count, std::int32_t *size)
{
    sadk::mods::redirect_server_mods(false);
    std::uint32_t cs = Checksum::original(count, size);
    sadk::mods::redirect_server_mods(true);
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

// SelectMapDialog::RefreshMapList's one call that lists a location's maps: the custom maps are listed right after.
void SADK_STDCALL append_maps(std::int32_t location, void *list, void *names, float *rgba)
{
    static float user_colour[4] = {1.0f, 0.85f, 0.55f, 1.0f};   // custom maps: warm tint
    fn::SelectMapDialog_AppendMapFiles(location, list, names, rgba);
    fn::SelectMapDialog_AppendMapFiles(MAP_LOCATION_USER, list, names, user_colour);
}

// ── Start-up ─────────────────────────────────────────────────────────────────────────────────────────────────────
// The folders below My Documents, found as the game finds them (Sys_GetMyDocumentsPath).
void make_folders()
{
    char d[MAX_PATH];
    if (SHGetFolderPathA(nullptr, CSIDL_PERSONAL, nullptr, 0, d) != S_OK) return;
    docs = std::string(d) + "\\";
    CreateDirectoryA((docs + "SAdK").c_str(), nullptr);
    maps_dir = docs + "SAdK\\maps\\";
    share_dir = docs + share_rel;
    in_dir = share_dir + "in\\";
    CreateDirectoryA(maps_dir.c_str(), nullptr);
    CreateDirectoryA(share_dir.c_str(), nullptr);
    CreateDirectoryA(in_dir.c_str(), nullptr);
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
    make_folders();
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
                Checksum::install(on_checksum, "build checksum without server mods' files") +
                GameSettings::install(on_game_settings, "maps advertised as downloadable");
    int subscribed = sadk::events::on_net_event(on_net_event) + sadk::events::on_frame(on_frame) +   // join, manifest
                     sadk::events::on_session_end(on_session_end);   // timeout and kick; put the mods back
    log("%d of 8 patches, %d of 4 hooks, %d of 3 events active (maps folder %s; maps %s, server mods %s; this side %s LZMS)", ok, hooks, subscribed,
        maps_dir.c_str(), accept_maps ? "accepted" : "refused", accept_mods ? "accepted" : "refused",
        archive::can_compress() ? "can use" : "cannot use");
    return ok == 8 && hooks == 4 && subscribed == 3;
}

SADKMOD_MAIN(assetshare_start, 2, SADKMOD_CLIENT)
