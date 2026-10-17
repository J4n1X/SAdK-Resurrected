// mpsave: saving and loading in a network match (docs/multiplayer-save.md). Changes what happens in a match: every
// player of a match needs it (SERVER). Live 2026-10-12 (two players): saving in a network match, loading a save in the
// running match, the automatic resync and loading such a save offline work (docs/multiplayer-save.md).
//
// What the game does today. A save is the map part plus the logic part of the running world
// (GameFile_Save S 005aa260: GameFile_SaveMap + GameFile_SaveLogic), and the save code does not care whether the match
// is a network match. Only the menu does:
//   - nMenu::Game::LoadFromXml S 005ecaf0 removes the first two entries of the in-game menu (Save, Load) when
//     NComm_Manager_IsRole0 is false;
//   - nMenu::Game::OnMenuComboSelected S 005eb310 ignores those two entries when NComm_Manager_IsRole0 is false.
// Loading (nMenu::System::StartPendingMap S 005d9fd0) shuts the network session down and starts an offline one, so
// it cannot be used in a match as it is.
//
// What this mod does.
//   1. Menu. The three NComm_Manager_IsRole0 calls above answer "offline", so "Save" and "Load" are in the menu of a
//      network match and open the game's own panel (nMenu::LoadSavePanel).
//   2. Save. Unchanged: the panel calls GameFile_Save(0x6e, name), which writes <My Documents>\SAdK\saves\<name>.aav
//      on the player who saved.
//   3. Load in a network match (host only). The panel hands the chosen name to nMenu::System::pendingMapPath and
//      nMenu::System::Update calls StartPendingMap; in a network match the mod takes over there (sync_load):
//        0. the save must be of the session's map (is_session_map) and its players must fit (load_table), or
//           nothing is sent;
//        a. the host offers the file to everyone (name, size, CRC-32) and sends it in pieces. Offer and pieces are
//           NComm::EventText events with ids of the mod's own, sent like chat (NComm_Manager::BroadcastEvent
//           S 0040fd80); each player's game hands every event to NComm_Manager::HandleEvent S 0040e560, where
//           sadk::events::on_net_event sees it. An event with one of the mod's ids counts only as an EventText of
//           the session's host ("have": of a connected human), by the sender the event names (net_event);
//        b. each joiner answers "have" once it holds a file of that CRC (its own copy or the received one);
//        c. when every connected human has answered, the host queues a LOAD command as a lockstep game command
//           (NComm_Manager::QueueGameCommand S 00408b10), which every game executes at the same net tick
//           (NComm_Manager::AdvanceNetTick S 00411990 -> ExecuteEventPackage S 00410530 -> HandleEvent);
//        d. on LOAD every game stops ticking at once (NComm_Manager::CanAdvanceTick S 004088b0 answers "no", which
//           ends the tick loop of NLogic::System::Update S 00527070) and, at the start of the next frame, leaves and
//           re-enters the game screen the way StartPendingMap does for a save, without the session calls
//           (load_now): the old world and its scene are destroyed and a new world is built from the file. Then it
//           ticks on. The sub-tick counter is 0 on everyone at that point, so all games continue from the same
//           state at the same tick.
//      A save keeps who the local player is (Player::kind 2 local human / 3 remote human, Player::Store S 005be3c0;
//      the lockstep checksum leaves it out, Player::StoreChecksum S 005be6e0), so after a load in a match each game
//      makes its own player the local one again.
//      Who plays which of the save's players is decided by the host, by name (assign_players; AssignByName), and
//      travels in the LOAD command as the player index of each of the six session slots. Every game writes those
//      indices into its session's slots when it executes the command (apply_table), because the session's slots are
//      where the game takes "which player is this human" from: a command's sender slot becomes a player index in
//      NComm_Event_GetSenderPlayerIndex S 00412490 (EventGameInformation::GetSlotPlayerIndex S 00413290), the local
//      player's index is the index of the slot with the local GUID (NComm_Manager::GetLocalPlayerIndex S 00408300)
//      and the winner's slot is found by player index (EventGameInformation::FindSlotByPlayerIndex S 00413380, from
//      ai::game::VictoryConditions::DeclareWinner S 00535990).
//   4. Loading such a save offline. The other humans' players are "remote human" (kind 3) in the file; nothing would
//      control them. With FormerHumans = ai they become AI players: their slots become AI slots
//      (GameFile_LoadMapInfo's result inside StartPendingMap) and after the load each is handed to the AI the way the
//      Lua function ai_enable does it (NAI::System::ActivatePlayer S 00581c40).
//   5. Resynchronising. When the game detects a desync it only says so (AdvanceNetTick: "!DESYNC DETECTED",
//      NComm_WriteDesyncDump S 0041f5e0). With AutoResync the host then saves its state and runs sync_load on it.
//
// [TODO live] Built from the binary and not tested in the game: the assignment of players by name (assign_players,
// the slot table in LOAD), the sender check of the mod's events (net_event) and the map check (is_session_map). What
// the next live test has to answer is listed in docs/multiplayer-save.md ("Risks and open questions").
#include <windows.h>

#include <sadkmod/sadkmod.hpp>
#include <sadkmod/game/sadk_noav/fn/GameLoadDescriptor.hpp>
#include <sadkmod/game/sadk_noav/fn/NAI.hpp>
#include <sadkmod/game/sadk_noav/fn/NComm.hpp>
#include <sadkmod/game/sadk_noav/fn/NComm_Manager.hpp>
#include <sadkmod/game/sadk_noav/fn/NCore.hpp>
#include <sadkmod/game/sadk_noav/fn/NLogic.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/game/sadk_noav/fn/ai.hpp>
#include <sadkmod/game/sadk_noav/fn/nMenu.hpp>
#include <sadkmod/game/sadk_noav/vars.hpp>

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace game = sadk::game;
namespace fn = sadk::game::fn;
namespace var = sadk::game::var;
namespace msvc = sadk::msvc;

namespace {

using Manager = game::NComm_Manager;

constexpr std::int32_t kSaveType = 0x6e;      // MapPath type of a savegame: <My Documents>\SAdK\saves\<name>.aav
constexpr std::uint32_t kNoPlayerId = 0xefffffee;   // a slot without a network player (NComm_Manager::CanAdvanceTick)
constexpr std::int32_t kKindAi = 1, kKindLocal = 2, kKindRemote = 3;          // ai::player::Player::kind

// Event ids of the mod, outside the game's own (0x20002..0x2002b game commands, 0x30001.. session events). The game
// ignores an id it does not know: HandleEvent leaves it to nGame::System::HandleGameCommand S 007845a0, whose switch
// has no default. [inferred; TODO live: no "Error Executing Event" line in the game's log]
// The ids are the format's version: format 1 (0x20f01..0x20f05, LOAD without the slot table) is not spoken any
// more. A game with the other format never answers an offer, so the host's load times out and nobody loads.
constexpr std::uint32_t kOldFirst = 0x20f01, kOldLast = 0x20f05;   // format 1: only recognised, to say so
constexpr std::uint32_t kOffer = 0x20f11;   // host -> all:  "<crc>|<size>|<pieces>|<name>"
constexpr std::uint32_t kPiece = 0x20f12;   // host -> all:  "<crc>|<index>|<base64>"
constexpr std::uint32_t kHave = 0x20f13;    // joiner -> host: "<crc>"
constexpr std::uint32_t kAbort = 0x20f14;   // host -> all:  "<crc>"
constexpr std::uint32_t kLoad = 0x20f15;    // lockstep command, from the host: "<crc>|<slot table>" (table_text)

constexpr std::int32_t kSlots = 6;      // NComm::EventGameInformation::slots
constexpr std::int32_t kPlayers = 8;    // ai::player::PlayerTable, NLogic::MapInfo's per-player arrays

const char kResyncName[] = "mpsave_resync";

// mpsave.ini
bool g_auto_resync = false;
bool g_assign_by_name = true;         // the host's value counts: only the host computes the assignment
bool g_same_map_only = true;          // host: refuse a save of another map than the session's (maintainer 2026-10-12)
bool g_former_humans_ai = true;
std::int32_t g_ai_level = 2;          // 1..3, as Game_CreatePlayersFromDescriptor S 005abb60 passes it
std::size_t g_piece_bytes = 2100;     // per event, before base64 (2800 characters)
std::int32_t g_pieces_per_frame = 2;
DWORD g_ack_timeout_ms = 120000;
DWORD g_resync_pause_ms = 60000;

// ── Small helpers ────────────────────────────────────────────────────────────────────────────────────────────────
std::uint32_t crc32(const std::uint8_t *p, std::size_t n)
{
    std::uint32_t c = 0xffffffffu;
    for (std::size_t i = 0; i < n; ++i) {
        c ^= p[i];
        for (int k = 0; k < 8; ++k) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return ~c;
}

const char kB64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

std::string b64_encode(const std::uint8_t *p, std::size_t n)
{
    std::string out;
    out.reserve((n + 2) / 3 * 4);
    for (std::size_t i = 0; i < n; i += 3) {
        std::uint32_t v = p[i] << 16 | (i + 1 < n ? p[i + 1] << 8 : 0) | (i + 2 < n ? p[i + 2] : 0);
        out += kB64[v >> 18 & 63];
        out += kB64[v >> 12 & 63];
        out += i + 1 < n ? kB64[v >> 6 & 63] : '=';
        out += i + 2 < n ? kB64[v & 63] : '=';
    }
    return out;
}

bool b64_decode(const char *s, std::size_t n, std::vector<std::uint8_t> &out)
{
    std::uint32_t v = 0;
    int bits = 0;
    for (std::size_t i = 0; i < n && s[i] != '='; ++i) {
        const char *at = static_cast<const char *>(std::memchr(kB64, s[i], 64));
        if (!at) return false;
        v = v << 6 | static_cast<std::uint32_t>(at - kB64);
        if ((bits += 6) >= 8) out.push_back(static_cast<std::uint8_t>(v >> (bits -= 8)));
    }
    return true;
}

bool read_file(const std::string &path, std::vector<std::uint8_t> &out)
{
    FILE *f = std::fopen(path.c_str(), "rb");
    if (!f) return false;
    std::uint8_t buf[16384];
    for (std::size_t n; (n = std::fread(buf, 1, sizeof buf, f)) > 0;) out.insert(out.end(), buf, buf + n);
    std::fclose(f);
    return true;
}

bool write_file(const std::string &path, const std::vector<std::uint8_t> &data)
{
    FILE *f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    bool ok = std::fwrite(data.data(), 1, data.size(), f) == data.size();
    return std::fclose(f) == 0 && ok;
}

// The game's own path of a savegame (ai::game::MapPath, ai::game::MapPath::BuildDirectory S 0052c320).
std::string save_path(const std::string &name)
{
    msvc::string n = msvc::string::borrow(name.c_str(), name.size());
    game::ai::game::MapPath path;
    fn::ai::game::MapPath::CtorWithFileName(&path, kSaveType, &n);
    std::string result(path.fullPath.view());
    fn::Stl_Pair_IntString_Destroy(&path);
    return result;
}

Manager *manager() { return fn::NComm_GetManager(); }

// A network match that is running: the only time the mod's network side does anything.
bool in_net_match()
{
    Manager *m = manager();
    return m && !fn::NComm_Manager_IsRole0(m) && m->eManagerState == game::ai::ncomm::EManagerState::EManagerState_GameRunning;
}

// A line for the player, on the channel the game uses for "!DESYNC DETECTED" (AdvanceNetTick S 00411990: a
// std::string* to NComm_Manager::NotifyObservers_Slot1 S 0040e3a0). Logged as well.
// [TODO live: where the line shows]
void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void say(const char *fmt, ...)
{
    char line[400];
    va_list args;
    va_start(args, fmt);
    std::vsnprintf(line, sizeof line, fmt, args);
    va_end(args);
    sadk::log("%s", line);
    if (!in_net_match()) return;
    msvc::owned_string s{std::string_view(line)};
    fn::NComm_Manager::NotifyObservers_Slot1(manager(), &s);
}

// ── Events ───────────────────────────────────────────────────────────────────────────────────────────────────────
// One NComm::EventText with an id of ours, built the way NComm_Manager::SendChatToAll S 00410410 builds a chat line
// (sender net id, sender slot, text; the ctor copies the text) and destroyed by the class's destructor: slot 0 of
// its vftable is NComm_StringEvent_ScalarDeletingDtor S 00420b30, called here by its declaration with flags 0 (frees
// the text, not the object). (The vftable struct's slot type has no `this` parameter, so it is not called through.)
// `lockstep`: as a game command, executed by every game at the same net tick; else at once, like chat.
bool send(std::uint32_t id, const std::string &text, bool lockstep = false)
{
    Manager *m = manager();
    if (!m) return false;
    game::NComm::EventText ev{};
    msvc::string t = msvc::string::borrow(text.c_str(), text.size());
    fn::NComm::EventText::ctor(&ev, id, fn::NComm_Manager::GetLocalNetId(m), fn::NComm_Manager::FindLocalPlayerSlot(m), &t);
    // Cast kept: QueueGameCommand takes the map's flat NComm_Event, a struct unrelated to EventText (same header).
    bool ok = lockstep ? fn::NComm_Manager::QueueGameCommand(m, reinterpret_cast<game::NComm_Event *>(&ev), true)
                       : fn::NComm_Manager::BroadcastEvent(m, &ev);
    fn::NComm_StringEvent_ScalarDeletingDtor(&ev, 0);
    return ok;
}

// The address of the EventText vftable (007d43a8). The generated headers have no constant for it (the map has no
// typed label there), so it is read once from an EventText the game's constructor built. ctor S 00409ea0 and
// ctor_Deserialize S 00420340 write the same vftable, so sent and received events have it.
const void *g_event_text_vftable = nullptr;

bool is_event_text(const game::NComm::EventBase *ev)
{
    if (!g_event_text_vftable) {
        game::NComm::EventText probe{};
        msvc::string none = msvc::string::borrow("", 0);
        fn::NComm::EventText::ctor(&probe, kOffer, kNoPlayerId, -1, &none);
        g_event_text_vftable = probe.vftable;
        fn::NComm_StringEvent_ScalarDeletingDtor(&probe, 0);
    }
    const void *table = ev->vftable;
    return table == g_event_text_vftable;
}

std::string text_of(const game::NComm::EventText *ev) { return std::string(ev->text.view()); }

// ── Synchronised load: one operation for "the host loads a save" and for a resync ─────────────────────────────────
// Files this game holds, by CRC: what a LOAD command names. (The same save may have another name on each player.)
std::map<std::uint32_t, std::string> g_files;

// How the host fills the slot table of a load: `resync` and `seats` leave every slot the player index it has
// (`seats` after save_fits_match), `names` is assign_players.
enum class Assign { resync, seats, names };

struct HostSync {
    enum { idle, offering, queued } state = idle;
    Assign assign = Assign::resync;
    std::string name;
    std::vector<std::uint8_t> data;
    std::uint32_t crc = 0;
    std::size_t next_piece = 0, pieces = 0;
    std::uint32_t need = 0, have = 0;   // bit per slot: connected humans other than the host / those who answered
    DWORD started = 0, last_sent = 0;
} g_host;

struct Incoming {
    bool active = false;
    std::string name;
    std::uint32_t crc = 0;
    std::size_t size = 0, pieces = 0, next_piece = 0;
    std::vector<std::uint8_t> data;
} g_in;

bool g_frozen = false;            // a LOAD was executed: no logic tick until the file is loaded
bool g_reloading = false;         // inside load_now's leave and re-enter of the game screen
std::uint32_t g_load_crc = 0;
bool g_load_failed_said = false;
bool g_logic_loaded = false;      // GameFile_LoadLogic ran during the load in progress
bool g_offline_start = false;     // inside StartPendingMap's own (offline) start
bool g_resync_wanted = false;
DWORD g_last_resync = 0;
bool g_old_format_said = false;

std::uint32_t other_humans(Manager *m)
{
    game::NComm::EventGameInformation *info = fn::NComm_Manager::GetGameInformation(m);
    std::int32_t self = fn::NComm_Manager::FindLocalPlayerSlot(m);
    std::uint32_t mask = 0;
    for (std::int32_t i = 0; i < 6; ++i) {
        game::NComm::PlayerInfo *slot = fn::NComm::EventGameInformation::GetSlot(info, i);
        if (i != self && fn::NComm::PlayerInfo::IsHuman(slot) && fn::NComm::PlayerInfo::GetPlayerId(slot) != kNoPlayerId)
            mask |= 1u << i;
    }
    return mask;
}

// ── Who plays which of the save's players ────────────────────────────────────────────────────────────────────────
// The players of a save, from its MapInfo (GameFile_LoadMapInfo S 005aaa30): per player index the controller (the
// value Game_CreatePlayersFromDescriptor S 005abb60 gives Player::kind) and the name. In a network match
// SetupGameDialog::SetupSession S 004562d0 wrote both from the session's slots, by the slot's player index: the
// slot's name, and 2 for the slot with the local GUID, 3 for any other human's, 1 for an AI slot.
struct SavePlayers {
    std::int32_t kind[kPlayers] = {};
    std::string name[kPlayers];
    bool session_map = false;   // the file's map GUID is the session's (is_session_map)
    bool human(std::int32_t i) const { return i >= 0 && i < kPlayers && (kind[i] == kKindLocal || kind[i] == kKindRemote); }
};

// Whether `info` is of the session's map, compared the way the game looks for the host's map on a joiner
// (HandleEvent S 0040e560 -> GameFile_FindMapNameByGuid S 005ab3d0): the session's map GUID
// (EventGameInformation::GetMapGuid S 00413c20, as an NCore::UUID through NetGUID::ToUUID S 004163e0) against the
// UUID in the MapInfo (NCore::UUID::Equals S 005a9d00: the 16 bytes). A save keeps the UUID of the map it was made
// on: MapInfo::Load S 0052bd40 reads it from the map file and MapInfo::Store S 00529db0 writes it again.
// [TODO map] the UUID's accessor S 00529520 is still the generic GameDesc_GetField_1d4(void *) -> void *, and
// MapInfo +0x1d4 has no field: hence the one cast of its result.
bool is_session_map(Manager *m, game::NLogic::MapInfo *info)
{
    game::NComm::NetGUID guid{};      // filled by GetMapGuid
    game::NCore::UUID session{};      // constructed by ToUUID
    fn::NComm::EventGameInformation::GetMapGuid(fn::NComm_Manager::GetGameInformation(m), &guid);
    fn::NComm::NetGUID::ToUUID(&guid, &session);
    return fn::NCore::UUID::Equals(static_cast<game::NCore::UUID *>(fn::GameDesc_GetField_1d4(info)), &session);
}

std::string session_map_name(Manager *m)
{
    msvc::owned_string s;   // GetMapName S 004141f0 builds a std::string in it (a copy)
    fn::NComm::EventGameInformation::GetMapName(fn::NComm_Manager::GetGameInformation(m), &s);
    return s.str();
}

bool read_save_players(Manager *m, const std::string &name, SavePlayers &out)
{
    alignas(8) std::uint8_t raw[sizeof(game::NLogic::MapInfo)];
    auto *info = reinterpret_cast<game::NLogic::MapInfo *>(raw);   // storage for an object the game constructs
    fn::NLogic::MapInfo::ctor(info);
    msvc::string n = msvc::string::borrow(name.c_str(), name.size());
    bool ok = fn::GameFile_LoadMapInfo(&n, kSaveType, info, true);
    for (std::int32_t i = 0; ok && i < kPlayers; ++i) {
        out.kind[i] = *fn::NLogic::MapInfo::GetPlayerKindPtr(info, &i);
        out.name[i] = std::string(fn::NLogic::MapInfo::GetPlayerNamePtr(info, &i)->view());
    }
    out.session_map = ok && is_session_map(m, info);
    fn::NLogic::MapInfo::dtor(info);
    return ok;
}

// Host, a load from the menu: false (`why`) for a save that was made on another map than the session's. The running
// world must itself carry the session's map GUID for the answer to count; if it does not (a map file from before
// MapInfo version 7 gets a new random UUID at every load, MapInfo::Load S 0052bd40), the check cannot tell and lets
// the save pass, with a line in the log.
bool save_is_of_this_map(Manager *m, const std::string &name, std::string &why)
{
    if (!g_same_map_only) return true;
    SavePlayers save;
    if (!read_save_players(m, name, save)) { why = "its map information cannot be read"; return false; }
    if (save.session_map) return true;
    game::NLogic::System *logic = *var::g_pGameSystem;
    if (!logic || !logic->mapInfo || !is_session_map(m, logic->mapInfo)) {
        sadk::log("map check skipped: the running world does not have the session's map GUID");
        return true;
    }
    why = "it was saved on another map than this match's (\"" + session_map_name(m) + "\")";
    return false;
}

// The player index of each session slot, -1 for a slot without one (open and closed slots have 0xff).
struct SlotTable {
    std::int8_t player[kSlots];
};

game::NComm::PlayerInfo *slot_at(Manager *m, std::int32_t i)
{
    return fn::NComm::EventGameInformation::GetSlot(fn::NComm_Manager::GetGameInformation(m), i);
}

std::string slot_name(game::NComm::PlayerInfo *slot)
{
    msvc::owned_string s;   // GetPlayerName S 00415430 builds a std::string in it (a copy of the slot's name)
    fn::NComm::PlayerInfo::GetPlayerName(slot, &s);
    return s.str();
}

SlotTable current_table(Manager *m)
{
    SlotTable t;
    for (std::int32_t i = 0; i < kSlots; ++i) {
        std::int32_t index = fn::NComm::PlayerInfo::GetPlayerIndex(slot_at(m, i));
        t.player[i] = index >= 0 && index < kPlayers ? static_cast<std::int8_t>(index) : std::int8_t(-1);
    }
    return t;
}

// The table as text in a LOAD command: one character per slot, '0'..'7' or '-'.
std::string table_text(const SlotTable &t)
{
    std::string text;
    for (std::int8_t p : t.player) text += p < 0 ? '-' : static_cast<char>('0' + p);
    return text;
}

// False for anything but six characters of '0'..'7' and '-' with no player index twice.
bool parse_table(const std::string &text, SlotTable &t)
{
    if (text.size() != static_cast<std::size_t>(kSlots)) return false;
    bool used[kPlayers] = {};
    for (std::int32_t i = 0; i < kSlots; ++i) {
        char c = text[static_cast<std::size_t>(i)];
        if (c == '-') { t.player[i] = -1; continue; }
        if (c < '0' || c >= '0' + kPlayers || used[c - '0']) return false;
        used[c - '0'] = true;
        t.player[i] = static_cast<std::int8_t>(c - '0');
    }
    return true;
}

// The table every game uses since the last LOAD of this session. The session's slots are the game's own record of
// it; this copy is what apply_table writes again when the host's session data arrives (net_event).
bool g_table_set = false;
SlotTable g_table{};

// Writes the table into the session's slots (NComm::PlayerInfo::SetPlayerIndex S 00414e20, the setter the game's own
// slot changes use, HandleEvent 0x30002 S 0040e560). A slot with '-' is left as it is. True when a slot changed.
bool apply_table(Manager *m, const SlotTable &t, bool log_changes)
{
    bool changed = false;
    for (std::int32_t i = 0; i < kSlots; ++i) {
        if (t.player[i] < 0) continue;
        game::NComm::PlayerInfo *slot = slot_at(m, i);
        std::int32_t before = fn::NComm::PlayerInfo::GetPlayerIndex(slot);
        if (before == t.player[i]) continue;
        fn::NComm::PlayerInfo::SetPlayerIndex(slot, static_cast<char>(t.player[i]));
        changed = true;
        if (log_changes) sadk::log("slot %d (%s): player %d -> player %d", i, slot_name(slot).c_str(), before, t.player[i]);
    }
    return changed;
}

// The humans who play: human slots with a connected player, the host's own among them.
std::uint32_t playing_humans(Manager *m)
{
    std::int32_t self = fn::NComm_Manager::FindLocalPlayerSlot(m);
    return other_humans(m) | (self >= 0 && self < kSlots ? 1u << self : 0u);
}

// AssignByName = false: a save fits the running match when every human slot's player index is a human's player in
// the file. Nobody changes players. (That the save is of the session's map is save_is_of_this_map's question.)
bool save_fits_match(Manager *m, const std::string &name)
{
    SavePlayers save;
    if (!read_save_players(m, name, save)) return false;
    for (std::int32_t i = 0; i < kSlots; ++i) {
        game::NComm::PlayerInfo *slot = slot_at(m, i);
        if (fn::NComm::PlayerInfo::IsHuman(slot) && !save.human(fn::NComm::PlayerInfo::GetPlayerIndex(slot))) return false;
    }
    return true;
}

// AssignByName = true: the host decides who continues which of the save's players.
//   a. A playing human whose name is the name of a human player of the save gets that player. Names are compared
//      byte for byte. A name that two playing humans have, or two human players of the save, or that is empty, is
//      no match for any of them.
//   b. A playing human without a match keeps the player index of their slot when that is a human player of the save
//      and no name match took it.
//   c. Anyone left has no player: the load is refused, `why` names them. (Two humans on one player cannot come out
//      of a and b: a name match is one to one, and b only gives away a player nobody has.)
// Every other slot (AI, closed, a human who left) keeps its index, unless a human now has it: then it gets one of
// the indices the humans gave up (lowest first, in slot order), so that no two slots share a player index. The
// game's lookups by player index take the first slot that has it (FindSlotByPlayerIndex S 00413380), and
// DeclareWinner S 00535990 names that slot's avatar to the referee.
bool assign_players(Manager *m, const std::string &name, SlotTable &table, std::string &why, bool tell)
{
    SavePlayers save;
    if (!read_save_players(m, name, save)) { why = "its player list cannot be read"; return false; }
    const SlotTable now = current_table(m);
    std::uint32_t humans = playing_humans(m);
    std::string names[kSlots];
    for (std::int32_t i = 0; i < kSlots; ++i)
        if (humans >> i & 1) names[i] = slot_name(slot_at(m, i));

    bool taken[kPlayers] = {};
    for (std::int32_t i = 0; i < kSlots; ++i) table.player[i] = -1;
    for (std::int32_t i = 0; i < kSlots; ++i) {                                                  // a
        if (!(humans >> i & 1) || names[i].empty()) continue;
        std::int32_t same_here = 0, same_there = 0, player = -1;
        for (std::int32_t k = 0; k < kSlots; ++k) same_here += (humans >> k & 1) && names[k] == names[i];
        for (std::int32_t k = 0; k < kPlayers; ++k)
            if (save.human(k) && save.name[k] == names[i]) { ++same_there; player = k; }
        if (same_here != 1 || same_there != 1) continue;
        table.player[i] = static_cast<std::int8_t>(player);
        taken[player] = true;
    }
    std::string unplaced;
    for (std::int32_t i = 0; i < kSlots; ++i) {                                                  // b, c
        if (!(humans >> i & 1) || table.player[i] >= 0) continue;
        if (save.human(now.player[i]) && !taken[now.player[i]]) {
            table.player[i] = now.player[i];
            taken[now.player[i]] = true;
        } else {
            unplaced += (unplaced.empty() ? "" : ", ") + (names[i].empty() ? "slot " + std::to_string(i) : names[i]);
        }
    }
    if (!unplaced.empty()) {
        why = "no player in it for " + unplaced + " (no human player of that name, and the seat's player is not a free human player)";
        return false;
    }
    bool given_up[kPlayers] = {};
    for (std::int32_t i = 0; i < kSlots; ++i)
        if ((humans >> i & 1) && now.player[i] >= 0 && !taken[now.player[i]]) given_up[now.player[i]] = true;
    for (std::int32_t i = 0; i < kSlots; ++i) {                                                  // the other slots
        if (humans >> i & 1) continue;
        table.player[i] = now.player[i];
        if (now.player[i] < 0 || !taken[now.player[i]]) {
            if (now.player[i] >= 0) taken[now.player[i]] = true;
            continue;
        }
        std::int32_t free_index = 0;
        while (free_index < kPlayers && !given_up[free_index]) ++free_index;
        if (free_index == kPlayers) { why = "this match's slots do not have distinct player indices"; return false; }
        given_up[free_index] = false;
        taken[free_index] = true;
        table.player[i] = static_cast<std::int8_t>(free_index);
    }
    for (std::int32_t i = 0; tell && i < kSlots; ++i)
        if ((humans >> i & 1) && table.player[i] != now.player[i])
            say("mpsave: %s continues the save's player \"%s\" (player index %d; the seat has %d).", names[i].c_str(),
                save.name[table.player[i]].c_str(), table.player[i], now.player[i]);
    return true;
}

// The slot table of a load, by the host's way of filling it. False: no load (`why`).
bool load_table(Manager *m, const std::string &name, Assign assign, SlotTable &table, std::string &why, bool tell)
{
    if (assign == Assign::names) return assign_players(m, name, table, why, tell);
    table = current_table(m);   // a resync, or seats only: every slot keeps the player index it has
    return true;
}

// Host: offers the save `name` to every player and, once all have it, has every game load it at the same tick.
bool sync_load(const std::string &name, Assign assign)
{
    Manager *m = manager();
    if (!in_net_match() || !fn::NComm_Manager::IsHost(m)) return false;
    if (g_host.state != HostSync::idle || g_frozen) {
        say("mpsave: a load is already under way.");
        return false;
    }
    std::vector<std::uint8_t> data;
    if (!read_file(save_path(name), data) || data.empty()) {
        say("mpsave: cannot read the save \"%s\".", name.c_str());
        return false;
    }
    // A load from the menu: only a save of the session's map. A resync's save is of the running match and is not
    // asked (nothing may stand between a desync and its repair).
    std::string why;
    if (assign != Assign::resync && !save_is_of_this_map(m, name, why)) {
        say("mpsave: \"%s\" cannot be loaded in this match: %s. Nothing was sent.", name.c_str(), why.c_str());
        return false;
    }
    if (assign == Assign::seats && !save_fits_match(m, name)) {
        say("mpsave: \"%s\" does not fit this match (its human players are not this match's players).", name.c_str());
        return false;
    }
    // Refused here, before anything is sent, when a player cannot be placed. The table that is sent is computed
    // again when the load is queued (host_frame): a player may leave in between.
    SlotTable table;
    if (!load_table(m, name, assign, table, why, true)) {
        say("mpsave: \"%s\" cannot be loaded in this match: %s.", name.c_str(), why.c_str());
        return false;
    }
    g_host = HostSync{};
    g_host.assign = assign;
    g_host.state = HostSync::offering;
    g_host.name = name;
    g_host.crc = crc32(data.data(), data.size());
    g_host.pieces = (data.size() + g_piece_bytes - 1) / g_piece_bytes;
    g_host.data = std::move(data);
    g_host.need = other_humans(m);
    g_host.started = g_host.last_sent = GetTickCount();
    g_files[g_host.crc] = name;
    char head[64];
    std::snprintf(head, sizeof head, "%08x|%u|%u|", unsigned(g_host.crc), unsigned(g_host.data.size()), unsigned(g_host.pieces));
    send(kOffer, head + name);
    say("mpsave: sending \"%s\" to the other players (%u KB).", name.c_str(), unsigned(g_host.data.size() / 1024));
    return true;
}

void host_stop(const char *why)
{
    char crc[16];
    std::snprintf(crc, sizeof crc, "%08x", unsigned(g_host.crc));
    send(kAbort, crc);
    say("mpsave: load cancelled (%s).", why);
    g_host = HostSync{};
}

void host_frame()
{
    if (g_host.state != HostSync::offering) return;
    if (!in_net_match()) { g_host = HostSync{}; return; }
    g_host.need &= other_humans(manager());   // a player who left is not waited for
    if ((g_host.have & g_host.need) == g_host.need) {
        SlotTable table;
        std::string why;
        if (!load_table(manager(), g_host.name, g_host.assign, table, why, false)) { host_stop(why.c_str()); return; }
        char crc[16];
        std::snprintf(crc, sizeof crc, "%08x|", unsigned(g_host.crc));
        g_host.state = HostSync::queued;
        g_host.data.clear();
        if (!send(kLoad, crc + table_text(table), true)) host_stop("the load command was refused");
        return;
    }
    DWORD now = GetTickCount();
    // The time to answer counts from the last piece sent, so a large save is not cut off while it is on its way.
    if (now - g_host.last_sent > g_ack_timeout_ms) {
        host_stop("not every player received the save, or a player's mpsave is another version");
        return;
    }
    if (now - g_host.started < 1500) return;   // players who hold the same file answer without a transfer
    if (g_host.next_piece < g_host.pieces) g_host.last_sent = now;
    for (std::int32_t n = 0; n < g_pieces_per_frame && g_host.next_piece < g_host.pieces; ++n, ++g_host.next_piece) {
        std::size_t from = g_host.next_piece * g_piece_bytes;
        std::size_t len = g_host.data.size() - from < g_piece_bytes ? g_host.data.size() - from : g_piece_bytes;
        char head[32];
        std::snprintf(head, sizeof head, "%08x|%u|", unsigned(g_host.crc), unsigned(g_host.next_piece));
        send(kPiece, head + b64_encode(g_host.data.data() + from, len));
    }
}

void answer_have(std::uint32_t crc)
{
    char text[16];
    std::snprintf(text, sizeof text, "%08x", unsigned(crc));
    send(kHave, text);
}

// Joiner: the host offers a save. Our own file of that name and content counts; else the pieces are awaited.
void on_offer(const std::string &text)
{
    unsigned crc = 0, size = 0, pieces = 0;
    int used = 0;
    if (std::sscanf(text.c_str(), "%8x|%u|%u|%n", &crc, &size, &pieces, &used) < 3 || used <= 0) return;
    std::string name = text.substr(static_cast<std::size_t>(used));
    // A plain file name only: it becomes <saves>\<name>.aav on this player's disk.
    if (name.empty() || name.size() > 120 || name.find_first_of("\\/:*?\"<>|") != std::string::npos ||
        name.front() == '.' || name.front() == ' ' || name.back() == '.' || name.back() == ' ')
        return;
    for (unsigned char c : name)
        if (c < 0x20) return;
    if (size == 0 || size > 64u * 1024 * 1024 || pieces == 0 || pieces > size) return;
    g_in = Incoming{};
    char crc_text[16];
    std::snprintf(crc_text, sizeof crc_text, "%08x", crc);
    // Our own file of that name counts, and so does the copy an earlier offer of this content left.
    for (int attempt = 0; attempt < 2; ++attempt) {
        std::vector<std::uint8_t> mine;
        bool exists = read_file(save_path(name), mine);
        if (exists && crc32(mine.data(), mine.size()) == crc) {
            g_files[crc] = name;
            answer_have(crc);
            sadk::log("the host's save \"%s\" is the same as ours", name.c_str());
            return;
        }
        // Never over a save of the player's own; the resync save is the mod's and is replaced.
        if (!exists || attempt == 1 || name == kResyncName) break;
        name += std::string("_") + crc_text;
    }
    g_in.active = true;
    g_in.name = name;
    g_in.crc = crc;
    g_in.size = size;
    g_in.pieces = pieces;
    g_in.data.reserve(size);
    say("mpsave: receiving the host's save \"%s\" (%u KB).", name.c_str(), size / 1024);
}

void on_piece(const std::string &text)
{
    unsigned crc = 0, index = 0;
    int used = 0;
    if (!g_in.active || std::sscanf(text.c_str(), "%8x|%u|%n", &crc, &index, &used) < 2 || used <= 0) return;
    if (crc != g_in.crc || index != g_in.next_piece) return;
    if (!b64_decode(text.c_str() + used, text.size() - static_cast<std::size_t>(used), g_in.data) ||
        g_in.data.size() > g_in.size) {   // more than was offered: not this transfer
        g_in = Incoming{};
        say("mpsave: the host's save did not arrive intact.");
        return;
    }
    if (++g_in.next_piece < g_in.pieces) return;
    g_in.active = false;
    std::string path = save_path(g_in.name);
    std::string dir = path.substr(0, path.find_last_of('\\'));
    CreateDirectoryA(dir.substr(0, dir.find_last_of('\\')).c_str(), nullptr);   // <My Documents>\SAdK
    CreateDirectoryA(dir.c_str(), nullptr);                                     // ...\saves
    if (g_in.data.size() != g_in.size || crc32(g_in.data.data(), g_in.data.size()) != g_in.crc ||
        !write_file(path, g_in.data)) {
        g_in = Incoming{};
        say("mpsave: the host's save did not arrive intact.");
        return;
    }
    g_files[g_in.crc] = g_in.name;
    answer_have(g_in.crc);
    sadk::log("received the host's save as %s", path.c_str());
    g_in = Incoming{};   // frees the buffer
}

// Every game, at the same net tick: stop ticking; the load itself runs at the start of the next frame (frame()).
// The slot table is written here, not at the next frame: this point is the same place in the event stream on every
// game (a lockstep command inside ExecuteEventPackage S 00410530), so whatever command follows in the same or a later
// tick package finds the same slot-to-player mapping on every game.
void on_load(Manager *m, const std::string &text)
{
    g_load_crc = static_cast<std::uint32_t>(std::strtoul(text.c_str(), nullptr, 16));
    g_frozen = true;
    g_load_failed_said = false;
    g_resync_wanted = false;   // the load replaces whatever was out of sync
    g_host = HostSync{};
    SlotTable table;
    if (text.size() < 9 || text[8] != '|' || !parse_table(text.substr(9), table)) {
        // Not a command of this format: the other games load and this one cannot know with which players.
        say("mpsave: the host's load command cannot be read. Leave the match.");
        g_load_failed_said = true;   // stays stopped (load_now)
        return;
    }
    g_table = table;
    g_table_set = true;
    sadk::log("load command: players of the slots %s", text.c_str() + 9);
    apply_table(m, table, true);
}

// The load itself. The game's own load of a save out of a running match is nMenu::System::StartPendingMap S 005d9fd0:
//   1. DeactivateAllScreens S 005d9e70 closes the game screen: nMenu::Game::OnLeave S 005eb030 unregisters the
//      screen's receivers, clears the session's chat and message sinks, calls NComm_Manager::Shutdown, destroys the
//      HUD widgets, calls nGame::System::Shutdown S 007834e0 (street modes, then ShutdownAndDestroyGameSystem
//      S 00781cb0: NLogic::System::Shutdown S 00527c40 switches the logic callbacks off and resets every system, the
//      receivers are unregistered, g_pGameSystem is deleted; then the map script) and Scene_DestroyGlobal;
//   2. nGame::System::Shutdown once more if the game still runs;
//   3. GameLoadDescriptor::SetMapName S 005a9c10 (type 0x6e, the name) on the screen's descriptor;
//   4. NComm_Manager Shutdown, StartUpNetwork(0), ConnectAndJoin, SetGameSettings, SetSlotSetup: a new offline session;
//   5. the statements of nMenu::System::ActivateGameScreen S 005d9f10: nMenu::Game::OnEnter S 005eed00 sets the HUD up,
//      calls NComm_Manager::BeginGameStarting, registers the sinks, creates the scene, and nGame::System::BuildWorld
//      S 00784d40 constructs a new g_pGameSystem and scene and loads the file into the empty world
//      (Game_LoadWorldFromDescriptor S 005ac770, GameScript_CallOnLoaded included); then SendGameLoadedEvent.
// Here: 1, 2, 3 and 5 with the game's functions; 4 is left out, and the three session calls inside 1 and 5 (Shutdown,
// BeginGameStarting, SendGameLoadedEvent) do nothing while g_reloading is set (net_shutdown, begin_game_starting,
// send_game_loaded), so the session stays as it is. The sinks and the manager's event handler (+0x50) are cleared by
// 1 and set again by 5.
//
// Why not nGame_File_load into the running world (what this mod did first, crash live 2026-10-12 at 006B5874): the
// map part's first loader, NMap::System::Load S 00672030, ends in NotifyMapInitialized S 00677db0, on which the scene
// rebuilds its terrain cells with empty object lists (S 0067efe0 -> S 00688d20 -> CMapRenderer::InitForMap S 006883e0
// -> CTerrainCellMgr::DestroyCells / CreateTerrainCells); the next loader, NResources::System::Load S 00540fd0,
// first deletes the old world's deposits (Reset S 0053f0b0), each of which tells the scene (callbacks still on) to
// remove its render object from a cell that no longer lists it (docs/multiplayer-save.md, "The in-place load").
// [TODO live] untested: whether the session survives the seconds of loading with every game stopped.
void load_now()
{
    if (g_load_failed_said) return;   // stopped for good; the player was told
    auto file = g_files.find(g_load_crc);
    if (file == g_files.end()) {
        // Cannot happen while the host waits for every "have". Stays stopped: ticking on would only desync.
        if (!g_load_failed_said) say("mpsave: this game does not have the save to load. Leave the match.");
        g_load_failed_said = true;
        return;
    }
    std::string name = file->second;
    // The file must still be the one that was confirmed: nGame_File_load returns nothing, and GameFile_LoadImpl
    // S 005aaed0 falls back to a map of the same name when the save is missing. A game that cannot load stays
    // stopped, as above.
    std::vector<std::uint8_t> check;
    game::nMenu::System *menu = fn::nMenu::System::GetInstance();
    game::nMenu::Game *screen = menu ? menu->game : nullptr;
    if (!*var::g_pGameSystem || !screen || !screen->gameSystem || !screen->gameSetupInfo ||
        !read_file(save_path(name), check) || crc32(check.data(), check.size()) != g_load_crc) {
        if (!g_load_failed_said) say("mpsave: the save \"%s\" is gone or was changed. Leave the match.", name.c_str());
        g_load_failed_said = true;
        return;
    }
    check = {};
    sadk::log("loading \"%s\": leaving the game screen", name.c_str());
    msvc::string n = msvc::string::borrow(name.c_str(), name.size());
    g_logic_loaded = false;
    g_reloading = true;
    fn::nMenu::System::DeactivateAllScreens(menu);                                              // 1
    if (screen->gameSystem->bRunning) fn::nGame::System::Shutdown(screen->gameSystem);          // 2
    fn::GameLoadDescriptor::SetMapName(screen->gameSetupInfo, &n);                              // 3
    sadk::log("loading \"%s\": entering the game screen", name.c_str());
    fn::nMenu::System::ActivateGameScreen(menu);                                                // 5
    g_reloading = false;
    if (!*var::g_pGameSystem) {
        // BuildWorld constructs it unconditionally; without it nothing can tick.
        say("mpsave: loading \"%s\" failed. Leave the match.", name.c_str());
        g_load_failed_said = true;
        return;
    }
    g_frozen = false;
    say("mpsave: loaded \"%s\".", name.c_str());
}

// ── Players after a load ─────────────────────────────────────────────────────────────────────────────────────────
// In a network match: our player (the player index of our slot, which the LOAD command set) is the local human, the
// file's local human (whoever saved) a remote one. A human player of the file that no slot has stays kind 3: nothing
// controls it.
// Offline: the humans who are not there are handed to the AI (FormerHumans = ai) or left without a controller.
void fix_players()
{
    game::NLogic::System *logic = *var::g_pGameSystem;
    Manager *m = manager();
    if (!logic || !m) return;
    bool offline = fn::NComm_Manager_IsRole0(m);
    std::int32_t local = offline ? -1 : fn::NComm_Manager::GetLocalPlayerIndex(m, 0);
    for (std::int32_t i = 0; i < 8; ++i) {
        std::int32_t index = i;
        game::ai::player::Player *p = fn::ai::player::PlayerTable::GetEntry(logic->playerTable, &index);
        if (!p || !p->bActive) continue;
        std::int32_t kind = p->kind;
        if (!offline) {
            kind = i == local ? kKindLocal : kind == kKindLocal ? kKindRemote : kind;
        } else if (kind == kKindRemote && g_former_humans_ai) {
            std::int32_t *start = logic->mapInfo->startPositionsFirst;
            if (!start || logic->mapInfo->startPositionsLast - start < (i + 1) * 2) {
                sadk::log("player %d: no start position, left without a controller", i);
                continue;
            }
            // As ai_enable S 005b2660: only a player the AI does not run yet.
            if (!logic->ai || !logic->ai->players[i] || logic->ai->players[i]->bActive) continue;
            kind = kKindAi;
        }
        if (kind == p->kind) continue;
        p->kind = kind;
        fn::NLogic::MapInfo::SetPlayerKind(logic->mapInfo, &index, &kind);   // what the next save writes for this player
        if (!offline) continue;
        // A network match does not shuffle start positions (SetupSession S 004562d0 clears the descriptor's +0x24),
        // so player i started at the map's start position i.
        fn::NAI::System::ActivatePlayer(logic->ai, &p->index, logic->mapInfo->startPositionsFirst + i * 2, g_ai_level);
        sadk::log("player %d: was another human's, now an AI player (level %d)", i, g_ai_level);
    }
}

// ── Hooks ────────────────────────────────────────────────────────────────────────────────────────────────────────
// The menu's three "is this an offline game?" questions: yes, so Save and Load stay in the menu and open the panel.
bool SADK_FASTCALL menu_is_offline(void *) { return true; }

using CanAdvanceTick = sadk::Hook<fn::NComm_Manager::CanAdvanceTick>;
bool SADK_THISCALL can_advance_tick(Manager *m) { return !g_frozen && CanAdvanceTick::original(m); }

using LoadLogic = sadk::Hook<fn::GameFile_LoadLogic>;
void SADK_CDECL load_logic(void *stream)
{
    LoadLogic::original(stream);
    g_logic_loaded = true;
}

using FinishLoad = sadk::Hook<fn::GameFile_FinishLoad>;
void SADK_CDECL finish_load(bool resume)
{
    FinishLoad::original(resume);
    if (!g_logic_loaded) return;   // a map, not a save
    g_logic_loaded = false;
    fix_players();
}

// The session calls of the game screen's leave and enter (nMenu::Game::OnLeave S 005eb030, OnEnter S 005eed00) do
// nothing during load_now: the session of the running match is kept. Shutdown would end it (and the host's
// session_end event, which comes after this detour, is not raised); BeginGameStarting only acts in the pre-game state
// and logs an error in any other; SendGameLoadedEvent would send GameLoaded (0x30004) into the running match, on
// which the host broadcasts the game information again (HandleEvent S 0040e560).
using NetShutdown = sadk::Hook<fn::NComm_Manager::Shutdown>;
bool SADK_THISCALL net_shutdown(Manager *m, bool keep_error)
{
    return g_reloading || NetShutdown::original(m, keep_error);
}

using BeginGameStarting = sadk::Hook<fn::NComm_Manager::BeginGameStarting>;
bool SADK_THISCALL begin_game_starting(Manager *m) { return !g_reloading && BeginGameStarting::original(m); }

using SendGameLoaded = sadk::Hook<fn::NComm_Manager::SendGameLoadedEvent>;
bool SADK_THISCALL send_game_loaded(Manager *m, unsigned char value)
{
    return !g_reloading && SendGameLoaded::original(m, value);
}

// The save the offline load menu is about to start from: the absent humans' slots become AI slots.
using LoadMapInfo = sadk::Hook<fn::GameFile_LoadMapInfo>;
bool SADK_CDECL load_map_info(msvc::string *name, std::int32_t type, game::NLogic::MapInfo *info, bool flag)
{
    bool ok = LoadMapInfo::original(name, type, info, flag);
    if (ok && g_offline_start && g_former_humans_ai)
        for (std::int32_t i = 0; i < 8; ++i) {
            std::int32_t *kind = fn::NLogic::MapInfo::GetPlayerKindPtr(info, &i);
            if (*kind == kKindRemote) *kind = kKindAi;
        }
    return ok;
}

// The load panel's choice. Offline: the game's own start. In a network match that would end the session, so the
// host runs the synchronised load instead; nMenu::System::Update clears the name afterwards either way.
using StartPendingMap = sadk::Hook<fn::nMenu::System::StartPendingMap>;
void SADK_THISCALL start_pending_map(game::nMenu::System *system)
{
    if (in_net_match()) {
        if (fn::NComm_Manager::IsHost(manager()))
            sync_load(std::string(system->pendingMapPath.view()), g_assign_by_name ? Assign::names : Assign::seats);
        else
            say("mpsave: only the host can load a save in a network match.");
        return;
    }
    g_offline_start = true;
    StartPendingMap::original(system);
    g_offline_start = false;
}

// The game found the match out of sync (its only caller is AdvanceNetTick, in the middle of a tick): at the next
// frame the host saves and has everyone load that.
using DesyncDump = sadk::Hook<fn::NComm_WriteDesyncDump>;
void SADK_STDCALL desync_dump()
{
    DesyncDump::original();
    if (g_auto_resync) g_resync_wanted = true;
}

// False: not now (a load is under way, or the last resync was less than a minute ago); asked again at the next frame.
// The game reports a desync only once, when the match goes out of sync, so the wish must not be dropped.
bool resync()
{
    Manager *m = manager();
    if (!in_net_match() || !fn::NComm_Manager::IsHost(m)) return true;
    if (g_host.state != HostSync::idle || g_frozen) return false;
    if (g_last_resync && GetTickCount() - g_last_resync < g_resync_pause_ms) return false;
    g_last_resync = GetTickCount() | 1;
    say("mpsave: the match is out of sync. Saving the host's state for everyone.");
    msvc::string n = msvc::string::borrow(kResyncName, sizeof kResyncName - 1);
    fn::GameFile_Save(kSaveType, &n);
    sync_load(kResyncName, Assign::resync);   // nobody changes players: names are not looked at
    return true;
}

// ── Events ───────────────────────────────────────────────────────────────────────────────────────────────────────
void frame(void *)
{
    if (g_frozen) {
        if (in_net_match())
            load_now();
        else
            g_frozen = false;
    }
    if (g_table_set && !in_net_match()) g_table_set = false;   // the table belongs to the running match
    if (g_resync_wanted && resync()) g_resync_wanted = false;
    host_frame();
}

// ── Who sent an event ────────────────────────────────────────────────────────────────────────────────────────────
// An event names its sender itself: the header's net id (+8) and slot (+0xc) are what the sending game wrote
// (EventText::ctor; the mod and the game's chat pass NComm_Manager::GetLocalNetId and the local slot). Nothing on
// the way replaces them: an immediate event is queued without the transport's sender id
// (TinCatNetwork::cb_Received_Data S 0041d720 -> AppendReceivedImmediateEvents S 004082c0), and the host copies a
// joiner's lockstep package into the tick package byte for byte (AddClientGameEventsToServerGameEvents S 0040e0d0
// only tests that the transport's sender has a slot; TickPackage::AppendEvents S 00412e80). So the checks below keep
// out events of games that are honest about themselves (a joiner's game that offers or loads, an event of another
// class under one of the mod's ids); a changed game can name any sender, as it can in the game's own events.
//
// The host's net id: the player id of the slot that NComm::PlayerInfo::IsHost S 00414eb0 accepts. A hosting game's
// own net id is that id (TinCatNetwork::StartUp S 0041e610), and the slots are the host's, copied to every game.
// [TODO live] that a joiner's copy has the host's slot with that id (nMenu::NetInfo::RefreshInfo S 005fd5a0 labels
// the host by it on every game [inferred]).
bool host_net_id(Manager *m, std::uint32_t &id)
{
    for (std::int32_t i = 0; i < kSlots; ++i) {
        game::NComm::PlayerInfo *slot = slot_at(m, i);
        if (!fn::NComm::PlayerInfo::IsHost(slot)) continue;
        id = fn::NComm::PlayerInfo::GetPlayerId(slot);
        return true;
    }
    return false;
}

// An event that is not accepted: one line in the log per sender, then silence.
std::vector<std::uint32_t> g_rejected;

void reject(const game::NComm::EventBase *ev, const char *why)
{
    std::uint32_t sender = static_cast<std::uint32_t>(ev->sourceNetId);
    for (std::uint32_t known : g_rejected)
        if (known == sender) return;
    g_rejected.push_back(sender);
    sadk::log("ignoring mpsave events of net id %08x (first: event %05x, slot %d): %s", unsigned(sender),
              unsigned(ev->typeId), int(ev->playerId), why);
}

void net_event(void *, Manager *m, game::NComm::EventBase *ev)
{
    std::uint32_t id = static_cast<std::uint32_t>(ev->typeId);
    if (!in_net_match()) return;
    // The host's session data (EventGameInformation; HandleEvent S 0040e560 copies it over this game's with
    // AssignGameData, slots and their player indices included: 0x30003, 0x30005, 0x3000f, 0x30012) was just taken
    // over. If the host sent it before it executed the last LOAD, it has the indices from before: the table is
    // written again. This listener runs right after the game handled the event, before any tick.
    if (g_table_set && (id == 0x30003 || id == 0x30005 || id == 0x3000f || id == 0x30012) && apply_table(m, g_table, false))
        sadk::log("session data from the host had other player indices: the last load's are kept");
    if (id >= kOldFirst && id <= kOldLast && !g_old_format_said) {
        g_old_format_said = true;
        say("mpsave: another player's mpsave is an older version. Loading works only with the same version for everyone.");
    }
    if (id < kOffer || id > kLoad) return;
    // Only an EventText (by its vftable), and only from the right sender. Cast kept: the map has EventBase and
    // EventText as unrelated flat structs; the vftable test above it is what makes the event an EventText.
    if (!is_event_text(ev)) { reject(ev, "it is not a text event"); return; }
    auto *text_ev = reinterpret_cast<const game::NComm::EventText *>(ev);
    std::uint32_t sender = static_cast<std::uint32_t>(ev->sourceNetId);
    bool host = fn::NComm_Manager::IsHost(m);
    if (id == kHave) {
        // For the host only (every game receives it: BroadcastEvent sends to all). From a connected human's slot,
        // whose net id is the event's.
        if (!host) return;
        std::int32_t slot = ev->playerId;
        if (slot < 0 || slot >= kSlots || !(other_humans(m) >> slot & 1) || fn::NComm::PlayerInfo::GetPlayerId(slot_at(m, slot)) != sender) {
            reject(ev, "its sender is not a connected player of this match");
            return;
        }
        if (g_host.state == HostSync::offering && std::strtoul(text_of(text_ev).c_str(), nullptr, 16) == g_host.crc)
            g_host.have |= 1u << slot;
        return;
    }
    // Offer, piece, abort and LOAD: from the session's host only. For a LOAD every game must decide alike; all do,
    // as long as their copies of the session's slots agree (the event's bytes are the same on every game).
    std::uint32_t host_id = 0;
    if (!host_net_id(m, host_id) || sender != host_id) {
        reject(ev, "its sender is not the host");
        if (id == kLoad && host && g_host.state == HostSync::queued && sender == fn::NComm_Manager::GetLocalNetId(m)) {
            // The host's own command, and this game does not find itself as the host in the slots.
            g_host = HostSync{};
            say("mpsave: the load command was not accepted (the session's slots do not name this game as the host).");
        }
        return;
    }
    if (id == kLoad) {
        on_load(m, text_of(text_ev));
    } else if (host) {
        // the host's own offer, pieces and abort
    } else if (id == kOffer) {
        on_offer(text_of(text_ev));
    } else if (id == kPiece) {
        on_piece(text_of(text_ev));
    } else if (id == kAbort) {
        if (g_in.active) say("mpsave: the host cancelled the load.");
        g_in = Incoming{};
    }
}

void session_over(void *)
{
    g_host = HostSync{};
    g_in = Incoming{};
    g_files.clear();
    g_frozen = false;
    g_resync_wanted = false;
    g_last_resync = 0;
    g_table_set = false;
    g_old_format_said = false;
    g_rejected.clear();
}

}  // namespace

bool mpsave_start()
{
    sadk::Ini ini = sadk::mod_settings();
    g_auto_resync = ini.get_bool("MpSave", "AutoResync", g_auto_resync);
    g_assign_by_name = ini.get_bool("MpSave", "AssignByName", g_assign_by_name);
    g_same_map_only = ini.get_bool("MpSave", "SameMapOnly", g_same_map_only);
    g_former_humans_ai = _stricmp(ini.get("MpSave", "FormerHumans", "ai").c_str(), "idle") != 0;
    g_ai_level = ini.get_int("MpSave", "AiLevel", g_ai_level);
    if (g_ai_level < 1 || g_ai_level > 3) g_ai_level = 2;
    std::int32_t piece = ini.get_int("MpSave", "PieceBytes", static_cast<int>(g_piece_bytes));
    g_piece_bytes = static_cast<std::size_t>(piece < 256 ? 256 : piece > 2900 ? 2900 : piece);
    g_pieces_per_frame = ini.get_int("MpSave", "PiecesPerFrame", g_pieces_per_frame);
    if (g_pieces_per_frame < 1) g_pieces_per_frame = 1;
    std::int32_t timeout = ini.get_int("MpSave", "TransferTimeoutSeconds", 120);
    g_ack_timeout_ms = static_cast<DWORD>(timeout < 10 ? 10 : timeout > 3600 ? 3600 : timeout) * 1000;

    int menu = sadk::patch_calls(fn::nMenu::Game::LoadFromXml, fn::NComm_Manager_IsRole0, (void *)menu_is_offline,
                                 "mpsave: Save and Load stay in the menu of a network match", 1) +
               sadk::patch_calls(fn::nMenu::Game::OnMenuComboSelected, fn::NComm_Manager_IsRole0,
                                 (void *)menu_is_offline, "mpsave: Save and Load open their panel in a network match", 2);
    int hooks = CanAdvanceTick::install(can_advance_tick) + LoadLogic::install(load_logic) +
                FinishLoad::install(finish_load) + LoadMapInfo::install(load_map_info) +
                StartPendingMap::install(start_pending_map) + DesyncDump::install(desync_dump) +
                NetShutdown::install(net_shutdown) + BeginGameStarting::install(begin_game_starting) +
                SendGameLoaded::install(send_game_loaded);
    int events = sadk::events::on_frame(frame) + sadk::events::on_net_event(net_event) +
                 sadk::events::on_session_end(session_over);
    bool ok = menu == 3 && hooks == 9 && events == 3;
    char absent[32] = "idle";
    if (g_former_humans_ai) std::snprintf(absent, sizeof absent, "AI, level %d", g_ai_level);
    sadk::log(ok ? "saving and loading in network matches: on (players of a loaded save: %s; resync after a desync: %s; "
                   "absent humans offline: %s)"
                 : "mpsave NOT fully active (players %s, resync %s, absent humans %s)",
              g_assign_by_name ? "by name" : "by seat", g_auto_resync ? "automatic" : "off", absent);
    return ok;
}

SADKMOD_MAIN(mpsave_start, 1, SADKMOD_SERVER)
