// gamehostbridge: lets a player behind NAT host matches, through the lobby server (docs/bridge-protocol.md; the
// server side is sadk_lobby/bridge.py).
//
// tincat3.dll imports all of its sockets from WSOCK32.dll by ordinal, which is the shim (<game>\bin\wsock32.dll);
// SADK.exe uses WS2_32.dll directly. This mod hooks four of the shim's exports, so it sees exactly TinCat's traffic:
//   connect      to the lobby: tag the connection ("SADKB1 LOBBY <token>" before TinCat's first byte);
//                to a bridged game's virtual address: redirect to the relay ("SADKB1 JOIN <game id>").
//   send         writes a pending tag first.
//   listen       the host's match server came up: "HOSTING <port>".   closesocket  of it: "STOPPED".
// Its own sockets use WS2_32.dll directly, past the hooks.
//
// Start-up (a thread): control connection to the lobby host's bridge port ("SADKB1 HELLO <token>"), then the
// reachability test: listen on the game port, ask the stub to connect back ("CHECK"); no probe within 10 s ->
// "BRIDGED" (this client can only host through the bridge). Then "OPEN <channel>" from the stub: a data connection to
// the stub, piped to 127.0.0.1:<host port>.
//
// Settings: gamehostbridge.ini next to mod.dll, [Bridge] ForceBridge (default false: always host through the bridge,
// without the reachability test) and Port (the stub's bridge port, default 7072). The lobby's address and the game
// port come from the game's own LobbySettings.ini ([LobbyServer] Host, Port) and network.ini ([Basics] gamePort).
#include <winsock2.h>
#include <windows.h>
#include <wincrypt.h>

#include <sadkmod/sadkmod.hpp>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

using sadk::log;

namespace {

unsigned short swap16(unsigned short v) { return static_cast<unsigned short>((v << 8) | (v >> 8)); }

// ── Settings ─────────────────────────────────────────────────────────────────────────────────────────────────────
struct Config {
    std::string host;                     // LobbySettings.ini [LobbyServer] Host
    unsigned short lobby_port = 7070;     //   Port
    unsigned short game_port = 5479;      // network.ini [Basics] gamePort
    bool force_bridge = false;            // gamehostbridge.ini [Bridge] ForceBridge
    unsigned short bridge_port = 7072;    //   Port
} cfg;

void read_config()
{
    sadk::Ini lobby(sadk::game_path("data\\lobby\\config\\LobbySettings.ini"));
    cfg.host = lobby.get("LobbyServer", "Host");
    cfg.lobby_port = static_cast<unsigned short>(lobby.get_int("LobbyServer", "Port", 7070));
    cfg.game_port = static_cast<unsigned short>(
        sadk::Ini(sadk::game_path("data\\game\\settings\\network.ini")).get_int("Basics", "gamePort", 5479));
    sadk::Ini own = sadk::mod_settings();
    cfg.force_bridge = own.get_bool("Bridge", "ForceBridge", false);
    cfg.bridge_port = static_cast<unsigned short>(own.get_int("Bridge", "Port", 7072));
}

// ── State ────────────────────────────────────────────────────────────────────────────────────────────────────────
char token[33];
unsigned long lobby_ip = INADDR_NONE;   // network order
unsigned short relay_port;
unsigned long vip;                      // network order
unsigned vbase;
volatile LONG welcomed, bridged;        // WELCOME received / hosting goes through the bridge
HANDLE welcome_done;                    // set once the startup handshake has finished either way
SOCKET control = INVALID_SOCKET;
CRITICAL_SECTION control_cs;
volatile SOCKET hosting_sock = INVALID_SOCKET;
volatile unsigned short hosting_port;

enum { TAG_NONE, TAG_LOBBY, TAG_JOIN };
constexpr int MAX_TAGS = 64;
struct {
    SOCKET s;
    int kind;
    unsigned game;
} tags[MAX_TAGS];
CRITICAL_SECTION tags_cs;

void tag_set(SOCKET s, int kind, unsigned game)
{
    EnterCriticalSection(&tags_cs);
    for (auto &t : tags)
        if (t.kind == TAG_NONE || t.s == s) {
            t.s = s;
            t.kind = kind;
            t.game = game;
            break;
        }
    LeaveCriticalSection(&tags_cs);
}

int tag_take(SOCKET s, unsigned *game)
{
    int kind = TAG_NONE;
    EnterCriticalSection(&tags_cs);
    for (auto &t : tags)
        if (t.kind != TAG_NONE && t.s == s) {
            kind = t.kind;
            *game = t.game;
            t.kind = TAG_NONE;
            break;
        }
    LeaveCriticalSection(&tags_cs);
    return kind;
}

// ── Socket helpers (WS2_32 directly, past the hooks) ────────────────────────────────────────────────────────────
int send_all(SOCKET s, const char *buf, int len)
{
    DWORD start = GetTickCount();
    while (len > 0) {
        int n = send(s, buf, len, 0);
        if (n > 0) {
            buf += n;
            len -= n;
            continue;
        }
        if (WSAGetLastError() != WSAEWOULDBLOCK || GetTickCount() - start > 3000) return -1;
        fd_set w;
        FD_ZERO(&w);
        FD_SET(s, &w);
        struct timeval tv = {0, 100000};
        select(0, nullptr, &w, nullptr, &tv);
    }
    return 0;
}

void control_send(const char *line)
{
    EnterCriticalSection(&control_cs);
    if (control != INVALID_SOCKET) send_all(control, line, static_cast<int>(std::strlen(line)));
    LeaveCriticalSection(&control_cs);
}

SOCKET tcp_connect(unsigned long ip, unsigned short port, int timeout_ms)
{
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return s;
    struct sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_port = swap16(port);
    a.sin_addr.s_addr = ip;
    u_long nb = 1;
    ioctlsocket(s, FIONBIO, &nb);
    if (connect(s, reinterpret_cast<sockaddr *>(&a), sizeof a) != 0 && WSAGetLastError() != WSAEWOULDBLOCK) {
        closesocket(s);
        return INVALID_SOCKET;
    }
    fd_set w, e;
    FD_ZERO(&w);
    FD_SET(s, &w);
    FD_ZERO(&e);
    FD_SET(s, &e);
    struct timeval tv = {timeout_ms / 1000, (timeout_ms % 1000) * 1000};
    if (select(0, nullptr, &w, &e, &tv) != 1 || !FD_ISSET(s, &w)) {
        closesocket(s);
        return INVALID_SOCKET;
    }
    nb = 0;
    ioctlsocket(s, FIONBIO, &nb);
    return s;
}

// Read one '\n'-terminated line (without it); 0 on success.
int recv_line(SOCKET s, char *out, int cap, int timeout_ms)
{
    int n = 0;
    for (;;) {
        if (timeout_ms >= 0) {
            fd_set r;
            FD_ZERO(&r);
            FD_SET(s, &r);
            struct timeval tv = {timeout_ms / 1000, (timeout_ms % 1000) * 1000};
            if (select(0, &r, nullptr, nullptr, &tv) != 1) return -1;
        }
        char c;
        if (recv(s, &c, 1, 0) != 1) return -1;
        if (c == '\n') {
            out[n] = 0;
            return 0;
        }
        if (n < cap - 1) out[n++] = c;
    }
}

// ── Data channel: stub <-> 127.0.0.1:<host port> ────────────────────────────────────────────────────────────────
DWORD WINAPI channel_thread(LPVOID arg)
{
    unsigned channel = static_cast<unsigned>(reinterpret_cast<UINT_PTR>(arg));
    SOCKET up = tcp_connect(lobby_ip, cfg.bridge_port, 5000);
    SOCKET local = tcp_connect(0x0100007f, hosting_port ? hosting_port : cfg.game_port, 3000);
    if (up == INVALID_SOCKET || local == INVALID_SOCKET) {
        log("channel %u: could not connect (stub %s, local %s)", channel, up == INVALID_SOCKET ? "FAILED" : "ok",
            local == INVALID_SOCKET ? "FAILED" : "ok");
        if (up != INVALID_SOCKET) closesocket(up);
        if (local != INVALID_SOCKET) closesocket(local);
        return 0;
    }
    char line[96];
    std::sprintf(line, "SADKB1 DATA %s %u\n", token, channel);
    send_all(up, line, static_cast<int>(std::strlen(line)));
    log("channel %u: joiner connected to the local match server", channel);
    char buf[16384];
    for (;;) {
        fd_set r;
        FD_ZERO(&r);
        FD_SET(up, &r);
        FD_SET(local, &r);
        if (select(0, &r, nullptr, nullptr, nullptr) <= 0) break;
        SOCKET from = FD_ISSET(up, &r) ? up : local;
        SOCKET to = from == up ? local : up;
        int n = recv(from, buf, sizeof buf, 0);
        if (n <= 0 || send_all(to, buf, n) != 0) break;
    }
    closesocket(up);
    closesocket(local);
    log("channel %u: closed", channel);
    return 0;
}

// ── Startup: control connection, reachability test ──────────────────────────────────────────────────────────────
int reachability_test()
{
    SOCKET l = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    struct sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_port = swap16(cfg.game_port);
    if (l == INVALID_SOCKET || bind(l, reinterpret_cast<sockaddr *>(&a), sizeof a) != 0 || listen(l, 4) != 0) {
        log("reachability: cannot listen on port %u (error %d) - assuming bridged", cfg.game_port, WSAGetLastError());
        if (l != INVALID_SOCKET) closesocket(l);
        return 0;
    }
    char nonce[17], line[96];
    std::sprintf(nonce, "%08lx%08lx", static_cast<unsigned long>(GetTickCount()),
                 static_cast<unsigned long>(GetCurrentProcessId()) * 2654435761UL);
    std::sprintf(line, "CHECK %u %s\n", cfg.game_port, nonce);
    control_send(line);
    int ok = 0;
    DWORD start = GetTickCount();
    while (!ok && GetTickCount() - start < 10000) {
        fd_set r;
        FD_ZERO(&r);
        FD_SET(l, &r);
        struct timeval tv = {0, 250000};
        if (select(0, &r, nullptr, nullptr, &tv) != 1) continue;
        SOCKET in = accept(l, nullptr, nullptr);
        if (in == INVALID_SOCKET) continue;
        char got[96], want[64];
        std::sprintf(want, "SADKB1 PROBE %s", nonce);
        if (recv_line(in, got, sizeof got, 3000) == 0 && std::strcmp(got, want) == 0) ok = 1;
        closesocket(in);
    }
    closesocket(l);
    return ok;
}

// The token names this client to the stub.
void make_token()
{
    unsigned char rnd[16];
    HCRYPTPROV prov;
    bool ok = false;
    if (CryptAcquireContextA(&prov, nullptr, nullptr, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT)) {
        ok = CryptGenRandom(prov, sizeof rnd, rnd);
        CryptReleaseContext(prov, 0);
    }
    if (!ok) {
        std::srand(GetTickCount() ^ GetCurrentProcessId());
        for (auto &b : rnd) b = static_cast<unsigned char>(std::rand());
    }
    for (int i = 0; i < 16; i++) std::sprintf(token + 2 * i, "%02x", rnd[i]);
}

DWORD WINAPI bridge_thread(LPVOID)
{
    make_token();
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    const char *h = cfg.host.c_str();
    lobby_ip = inet_addr(h);
    if (lobby_ip == INADDR_NONE && *h) {
        struct hostent *he = gethostbyname(h);
        if (he && he->h_addr_list[0]) std::memcpy(&lobby_ip, he->h_addr_list[0], 4);
    }
    log("config: lobby %s:%u (%s), game port %u, bridge port %u, ForceBridge %s", h, cfg.lobby_port,
        lobby_ip == INADDR_NONE ? "UNRESOLVED" : "resolved", cfg.game_port, cfg.bridge_port,
        cfg.force_bridge ? "true" : "false");
    SOCKET c = lobby_ip == INADDR_NONE ? INVALID_SOCKET : tcp_connect(lobby_ip, cfg.bridge_port, 5000);
    char line[256];
    if (c == INVALID_SOCKET) {
        log("no bridge on the lobby server (port %u) - plain pass-through", cfg.bridge_port);
        SetEvent(welcome_done);
        return 0;
    }
    std::sprintf(line, "SADKB1 HELLO %s\n", token);
    send_all(c, line, static_cast<int>(std::strlen(line)));
    if (recv_line(c, line, sizeof line, 5000) != 0 ||
        std::sscanf(line, "WELCOME relay=%hu vbase=%u", &relay_port, &vbase) != 2) {
        log("bridge did not answer HELLO - plain pass-through");
        closesocket(c);
        SetEvent(welcome_done);
        return 0;
    }
    char *v = std::strstr(line, "vip=");
    vip = v ? inet_addr(v + 4) : INADDR_NONE;
    EnterCriticalSection(&control_cs);
    control = c;
    LeaveCriticalSection(&control_cs);
    InterlockedExchange(&welcomed, 1);
    SetEvent(welcome_done);
    log("bridge connected: token %.8s..., relay port %u, virtual ports from %u at %s", token, relay_port, vbase,
        v ? v + 4 : "?");

    int reachable = 0;
    if (cfg.force_bridge) {
        log("reachability: not tested (ForceBridge = true) - hosting goes through the bridge");
    } else {
        reachable = reachability_test();
        log("reachability: port %u %s", cfg.game_port,
            reachable ? "is reachable from the server - hosting works directly"
                      : "is NOT reachable from the server - hosting goes through the bridge");
    }
    if (!reachable) {
        InterlockedExchange(&bridged, 1);
        control_send("BRIDGED\n");
    }
    for (;;) {                                   // stub -> mod: OPEN <channel> (CHECKED is info)
        if (recv_line(c, line, sizeof line, -1) != 0) break;
        unsigned channel;
        if (std::sscanf(line, "OPEN %u", &channel) == 1)
            CloseHandle(CreateThread(nullptr, 0, channel_thread, reinterpret_cast<LPVOID>(UINT_PTR(channel)), 0, nullptr));
    }
    log("bridge control connection lost");
    EnterCriticalSection(&control_cs);
    closesocket(control);
    control = INVALID_SOCKET;
    LeaveCriticalSection(&control_cs);
    InterlockedExchange(&welcomed, 0);
    return 0;
}

// ── Hooks on the shim's exports (TinCat's sockets) ──────────────────────────────────────────────────────────────
using connect_fn = int(WINAPI *)(SOCKET, const struct sockaddr *, int);
using send_fn = int(WINAPI *)(SOCKET, const char *, int, int);
using listen_fn = int(WINAPI *)(SOCKET, int);
using closesocket_fn = int(WINAPI *)(SOCKET);
connect_fn tincat_connect;
send_fn tincat_send;
listen_fn tincat_listen;
closesocket_fn tincat_closesocket;

int WINAPI on_connect(SOCKET s, const struct sockaddr *name, int namelen)
{
    auto *in = reinterpret_cast<const sockaddr_in *>(name);
    if (name && namelen >= static_cast<int>(sizeof *in) && in->sin_family == AF_INET) {
        WaitForSingleObject(welcome_done, 3000);     // a fast login must not overtake HELLO
        unsigned short port = swap16(in->sin_port);
        if (welcomed && in->sin_addr.s_addr == lobby_ip && port == cfg.lobby_port) {
            tag_set(s, TAG_LOBBY, 0);
            log("connect: lobby connection tagged");
        } else if (welcomed && in->sin_addr.s_addr == vip && port >= vbase && port < vbase + 20000) {
            sockaddr_in to = *in;
            to.sin_addr.s_addr = lobby_ip;
            to.sin_port = swap16(relay_port);
            tag_set(s, TAG_JOIN, port - vbase);
            log("connect: bridged game %u -> relay port %u", port - vbase, relay_port);
            return tincat_connect(s, reinterpret_cast<sockaddr *>(&to), sizeof to);
        }
    }
    return tincat_connect(s, name, namelen);
}

int WINAPI on_send(SOCKET s, const char *buf, int len, int flags)
{
    unsigned game = 0;
    int kind = tag_take(s, &game);
    if (kind != TAG_NONE) {
        char line[96];
        if (kind == TAG_LOBBY)
            std::sprintf(line, "SADKB1 LOBBY %s\n", token);
        else
            std::sprintf(line, "SADKB1 JOIN %u\n", game);
        if (send_all(s, line, static_cast<int>(std::strlen(line))) != 0) log("send: could not write the bridge tag");
    }
    return tincat_send(s, buf, len, flags);
}

int WINAPI on_listen(SOCKET s, int backlog)
{
    int rc = tincat_listen(s, backlog);
    sockaddr_in a;
    int len = sizeof a;
    unsigned port = 0;
    if (getsockname(s, reinterpret_cast<sockaddr *>(&a), &len) == 0) port = swap16(a.sin_port);
    log("listen(socket %u, backlog %d) on port %u -> %d", static_cast<unsigned>(s), backlog, port, rc);
    if (rc == 0 && port == cfg.game_port) {
        hosting_sock = s;
        hosting_port = static_cast<unsigned short>(port);
        char line[32];
        std::sprintf(line, "HOSTING %u\n", port);
        control_send(line);
        log("hosting on port %u%s", port, bridged ? " - joiners come through the bridge" : "");
    }
    return rc;
}

int WINAPI on_closesocket(SOCKET s)
{
    unsigned game;
    tag_take(s, &game);
    if (s == hosting_sock && s != INVALID_SOCKET) {
        hosting_sock = INVALID_SOCKET;
        control_send("STOPPED\n");
        log("hosting stopped");
    }
    return tincat_closesocket(s);
}

template <class F>
bool hook_export(const char *name, F detour, F *original)
{
    auto *shim = static_cast<HMODULE>(sadk::host_api() ? sadk::host_api()->host_module : nullptr);
    void *target = shim ? reinterpret_cast<void *>(GetProcAddress(shim, name)) : nullptr;
    if (!target) {
        log("the shim exports no %s", name);
        return false;
    }
    std::string what = std::string("TinCat's ") + name;
    return sadk::hook_function(target, reinterpret_cast<void *>(detour), reinterpret_cast<void **>(original), what.c_str());
}

}  // namespace

bool gamehostbridge_start()
{
    if (sadk::verifying()) return true;   // nothing in SADK.exe to check
    read_config();
    InitializeCriticalSection(&control_cs);
    InitializeCriticalSection(&tags_cs);
    welcome_done = CreateEventA(nullptr, TRUE, FALSE, nullptr);
    bool ok = hook_export("connect", on_connect, &tincat_connect) && hook_export("send", on_send, &tincat_send) &&
              hook_export("listen", on_listen, &tincat_listen) &&
              hook_export("closesocket", on_closesocket, &tincat_closesocket);
    if (!ok) return false;
    CloseHandle(CreateThread(nullptr, 0, bridge_thread, nullptr, 0, nullptr));
    return true;
}

SADKMOD_MAIN(gamehostbridge_start, 1, SADKMOD_CLIENT)
