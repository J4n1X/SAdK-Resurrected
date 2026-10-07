/* SAdK-ServerConfig: points a "Die Siedler - Aufbruch der Kulturen" install at a revival lobby server,
 * sets the bridge options and installs the bridge shim (wsock32.dll, embedded) into the game's bin folder.
 *
 * Writes (all plain Windows INI, which is how the game reads them):
 *   data\lobby\config\LobbySettings.ini  [LobbyServer] Host, Port, ForceBridge, DisableBillboards
 *       read by LobbyProfile::GetSettingString S 00465700 (GetPrivateProfileStringA)
 *   data\game\settings\network.ini       [Basics] gamePort
 *       read by NComm_NetworkConfig_LoadFromIni S 0041ede0
 *   bin\sadk_bridge.ini                  [Bridge] port   (the shim's bridge port)
 *   bin\wsock32.dll                      the bridge shim and mod host (docs/bridge-protocol.md, mods/README.md)
 *   mods\billboards\mod.dll, billboards.ini  the billboards mod, when "Disable billboards" is ticked
 *
 * The "modified" check recomputes the game's own build checksum (GameData_ComputeBuildChecksum
 * S 005ab800): the host kicks a joiner whose value differs ("!CHECKSUM MISMATCH"), so a different value
 * means only players with the same modifications can join.
 */
#include <windows.h>
#include <windowsx.h>
#include <commctrl.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <stdio.h>
#include <string.h>
#include <wincrypt.h>
#include "resource.h"

/* Build checksum of an unmodified install (data\game + data\lobby scripts *.lua and settings *.xml). */
#define VANILLA_BUILD_CHECKSUM 0x555bfa51u
/* The bridge shim calls game functions at fixed addresses: it is only installed on this exact build. */
#define SUPPORTED_EXE_MD5 "d4832bc5103c14f5445471af29b8d778"
#define BUILD_VERSION_CONST    0x06091812u      /* Crypto_GetVersionConst S 006ee670: encrypted-file header */

static const char *GAME_SUBDIR = "Ubisoft\\Die Siedler - Aufbruch der Kulturen";
static char root[MAX_PATH];                     /* the install folder (holds bin\SADK.exe) */
static int modded, have_game, exe_supported;
/* MD5 of a file as 32 lowercase hex digits; 0 on failure. */
static int file_md5(const char *path, char out[33])
{
    HCRYPTPROV prov = 0;
    HCRYPTHASH hash = 0;
    int ok = 0;
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) return 0;
    if (CryptAcquireContextA(&prov, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT) &&
        CryptCreateHash(prov, CALG_MD5, 0, 0, &hash)) {
        static unsigned char buf[65536];
        DWORD got;
        ok = 1;
        while (ReadFile(f, buf, sizeof buf, &got, NULL) && got)
            if (!CryptHashData(hash, buf, got, 0)) { ok = 0; break; }
        unsigned char digest[16];
        DWORD len = sizeof digest;
        if (ok && CryptGetHashParam(hash, HP_HASHVAL, digest, &len, 0))
            for (int i = 0; i < 16; i++) sprintf(out + 2 * i, "%02x", digest[i]);
        else
            ok = 0;
    }
    if (hash) CryptDestroyHash(hash);
    if (prov) CryptReleaseContext(prov, 0);
    CloseHandle(f);
    return ok;
}

static HBRUSH bg_brush;

/* ── Paths ───────────────────────────────────────────────────────────────── */
static void join(char *out, const char *a, const char *b) { snprintf(out, MAX_PATH, "%s\\%s", a, b); }

static int file_exists(const char *p)
{
    DWORD a = GetFileAttributesA(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

/* Accepts the install folder or its bin folder; writes the install folder to `out`. */
static int normalize_root(const char *in, char *out)
{
    char p[MAX_PATH], exe[MAX_PATH];
    lstrcpynA(p, in, MAX_PATH);
    size_t n = strlen(p);
    while (n && (p[n - 1] == '\\' || p[n - 1] == '/' || p[n - 1] == ' ')) p[--n] = 0;
    if (!n) return 0;
    join(exe, p, "bin\\SADK.exe");
    if (file_exists(exe)) { strcpy(out, p); return 1; }
    join(exe, p, "SADK.exe");
    if (file_exists(exe)) {
        char *s = strrchr(p, '\\');
        if (s) { *s = 0; strcpy(out, p); return 1; }
    }
    return 0;
}

static int from_registry_uninstall(REGSAM view, char *out)
{
    HKEY h;
    if (RegOpenKeyExA(HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall", 0,
                      KEY_READ | view, &h) != ERROR_SUCCESS) return 0;
    char name[256];
    int found = 0;
    for (DWORD i = 0; !found; i++) {
        DWORD len = sizeof name;
        if (RegEnumKeyExA(h, i, name, &len, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
        HKEY k;
        if (RegOpenKeyExA(h, name, 0, KEY_READ | view, &k) != ERROR_SUCCESS) continue;
        char disp[512] = "", path[MAX_PATH] = "";
        DWORD dl = sizeof disp, pl = sizeof path;
        RegQueryValueExA(k, "DisplayName", NULL, NULL, (BYTE *)disp, &dl);
        if (StrStrIA(disp, "Aufbruch der Kulturen") || StrStrIA(disp, "Rise of Cultures")) {
            if (RegQueryValueExA(k, "InstallLocation", NULL, NULL, (BYTE *)path, &pl) == ERROR_SUCCESS &&
                normalize_root(path, out)) found = 1;
            pl = sizeof path;
            if (!found && RegQueryValueExA(k, "UninstallString", NULL, NULL, (BYTE *)path, &pl) == ERROR_SUCCESS) {
                char *p = path;                                 /* "E:\...\Uninstall.exe" -> its folder */
                if (*p == '"') { p++; char *q = strchr(p, '"'); if (q) *q = 0; }
                char *s = strrchr(p, '\\');
                if (s) { *s = 0; if (normalize_root(p, out)) found = 1; }
            }
        }
        RegCloseKey(k);
    }
    RegCloseKey(h);
    return found;
}

static int detect_root(char *out)
{
    char self[MAX_PATH];                     /* run from inside the game folder (or its bin) */
    GetModuleFileNameA(NULL, self, MAX_PATH);
    char *s = strrchr(self, '\\');
    if (s) { *s = 0; if (normalize_root(self, out)) return 1; }
    if (from_registry_uninstall(KEY_WOW64_32KEY, out) || from_registry_uninstall(KEY_WOW64_64KEY, out)) return 1;
    static const char *pf[] = {"Program Files (x86)", "Program Files"};
    for (char d = 'C'; d <= 'Z'; d++) {
        char drive[4] = {d, ':', '\\', 0};
        UINT t = GetDriveTypeA(drive);
        if (t != DRIVE_FIXED && t != DRIVE_REMOVABLE) continue;
        for (int i = 0; i < 2; i++) {
            char p[MAX_PATH];
            snprintf(p, sizeof p, "%c:\\%s\\%s", d, pf[i], GAME_SUBDIR);
            if (normalize_root(p, out)) return 1;
        }
    }
    return 0;
}

/* ── Build checksum (GameData_ComputeBuildChecksum S 005ab800) ───────────── */
/* FileScanHolder::FindFilesInDirectory S 006e4310: recurse into every subfolder not starting with '.',
 * then match `pattern` with FindFirstFileA in this folder. */
static void scan(const char *dir, const char *pattern, unsigned *cs, int *count)
{
    char q[MAX_PATH];
    WIN32_FIND_DATAA fd;
    join(q, dir, "*.*");
    HANDLE h = FindFirstFileA(q, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && fd.cFileName[0] != '.') {
                char sub[MAX_PATH];
                join(sub, dir, fd.cFileName);
                scan(sub, pattern, cs, count);
            }
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    join(q, dir, pattern);
    h = FindFirstFileA(q, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        char p[MAX_PATH];
        join(p, dir, fd.cFileName);
        HANDLE f = CreateFileA(p, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
        if (f == INVALID_HANDLE_VALUE) continue;
        unsigned hdr[5] = {0};
        DWORD got = 0;
        ReadFile(f, hdr, sizeof hdr, &got, NULL);
        DWORD size = GetFileSize(f, NULL);
        CloseHandle(f);
        (*count)++;
        if (got == 20 && hdr[0] == BUILD_VERSION_CONST) *cs ^= hdr[2];      /* encrypted: header CRC */
        else if (got > 3) *cs ^= size ^ hdr[0];                            /* plain: size ^ first dword */
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}

static unsigned build_checksum(int *count)
{
    static const char *roots[] = {"data\\game", "data\\lobby"};     /* what "[data]" resolves to */
    unsigned cs = 0;
    *count = 0;
    for (int i = 0; i < 2; i++) {                                       /* [data]\scripts *.lua */
        char d[MAX_PATH], base[MAX_PATH];
        join(base, root, roots[i]);
        join(d, base, "scripts");
        if (GetFileAttributesA(d) != INVALID_FILE_ATTRIBUTES) scan(d, "*.lua", &cs, count);
    }
    for (int i = 0; i < 2; i++) {                                       /* [data]\settings *.xml */
        char d[MAX_PATH], base[MAX_PATH];
        join(base, root, roots[i]);
        join(d, base, "settings");
        if (GetFileAttributesA(d) != INVALID_FILE_ATTRIBUTES) scan(d, "*.xml", &cs, count);
    }
    return cs;
}

/* ── Embedded files: the shim and the billboards mod ─────────────────────── */
static const void *resource(int id, DWORD *size)
{
    HRSRC r = FindResourceA(NULL, MAKEINTRESOURCEA(id), (LPCSTR)RT_RCDATA);
    HGLOBAL g = r ? LoadResource(NULL, r) : NULL;
    *size = r ? SizeofResource(NULL, r) : 0;
    return g ? LockResource(g) : NULL;
}

/* <root>\rel compared with resource id: 1 = identical, 0 = missing, -1 = a different file */
static int file_state(const char *rel, int id)
{
    char p[MAX_PATH];
    join(p, root, rel);
    HANDLE f = CreateFileA(p, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) return 0;
    DWORD size, got = 0, have = GetFileSize(f, NULL);
    const void *want = resource(id, &size);
    int same = 0;
    if (want && have == size) {
        void *buf = HeapAlloc(GetProcessHeap(), 0, size);
        if (buf && ReadFile(f, buf, size, &got, NULL) && got == size) same = !memcmp(buf, want, size);
        if (buf) HeapFree(GetProcessHeap(), 0, buf);
    }
    CloseHandle(f);
    return same ? 1 : -1;
}

static int install_file(const char *rel, int id)
{
    char p[MAX_PATH];
    DWORD size, put = 0;
    const void *data = resource(id, &size);
    join(p, root, rel);
    if (!data) return 0;
    HANDLE f = CreateFileA(p, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return 0;
    int ok = WriteFile(f, data, size, &put, NULL) && put == size;
    CloseHandle(f);
    return ok;
}

static int shim_state(void) { return file_state("bin\\wsock32.dll", IDR_SHIM); }
static int install_shim(void) { return install_file("bin\\wsock32.dll", IDR_SHIM); }

/* The billboards mod (mods\billboards): installed when "Disable billboards" is ticked, its mod.dll removed when
   not (its billboards.ini, which a player may have edited, stays). */
#define BILLBOARDS_DLL "mods\\billboards\\mod.dll"
#define BILLBOARDS_INI "mods\\billboards\\billboards.ini"
static int set_billboards_mod(int on)
{
    char p[MAX_PATH];
    if (!on) {
        join(p, root, BILLBOARDS_DLL);
        return DeleteFileA(p) || GetLastError() == ERROR_FILE_NOT_FOUND || GetLastError() == ERROR_PATH_NOT_FOUND;
    }
    join(p, root, "mods");
    CreateDirectoryA(p, NULL);
    join(p, root, "mods\\billboards");
    CreateDirectoryA(p, NULL);
    int ok = file_state(BILLBOARDS_DLL, IDR_MOD_BILLBOARDS) == 1 || install_file(BILLBOARDS_DLL, IDR_MOD_BILLBOARDS);
    if (file_state(BILLBOARDS_INI, IDR_MOD_BILLBOARDS_INI) == 0) ok &= install_file(BILLBOARDS_INI, IDR_MOD_BILLBOARDS_INI);
    return ok;
}

/* ── Dialog ──────────────────────────────────────────────────────────────── */
static void ini_paths(char *lobby, char *network, char *bridge)
{
    join(lobby, root, "data\\lobby\\config\\LobbySettings.ini");
    join(network, root, "data\\game\\settings\\network.ini");
    join(bridge, root, "bin\\sadk_bridge.ini");
}

static void set_advanced(HWND dlg, int on)
{
    static const int ids[] = {IDC_LOBBYPORT, IDC_GAMEPORT, IDC_BRIDGEPORT,
                              IDC_L_LOBBYPORT, IDC_L_GAMEPORT, IDC_L_BRIDGEPORT};
    for (int i = 0; i < 6; i++) EnableWindow(GetDlgItem(dlg, ids[i]), on);
}

static void refresh(HWND dlg)
{
    char text[MAX_PATH], status[256] = "", warn[256] = "", shim[160] = "";
    GetDlgItemTextA(dlg, IDC_FOLDER, text, MAX_PATH);
    have_game = normalize_root(text, root);
    modded = 0;
    if (!have_game) {
        lstrcpyA(status, "SADK.exe not found - choose the game folder (or its bin folder).");
    } else {
        int n;
        unsigned cs = build_checksum(&n);
        modded = cs != VANILLA_BUILD_CHECKSUM;
        snprintf(status, sizeof status, "SADK.exe found - game data %s (checksum %08X, %d files)",
                 modded ? "MODIFIED" : "unmodified", cs, n);
        if (modded)
            lstrcpyA(warn, "Your game data differs from the original: only players with the same "
                           "modifications installed can join your games, and you can only join theirs.");
        char exe[MAX_PATH], md5[33] = "";
        join(exe, root, "bin\\SADK.exe");
        exe_supported = file_md5(exe, md5) && strcmp(md5, SUPPORTED_EXE_MD5) == 0;
        int st = shim_state();
        if (!exe_supported)
            lstrcpyA(shim, st ? "Unsupported SADK.exe - remove bin\\wsock32.dll; the shim needs the DRM-free build."
                              : "Unsupported SADK.exe - the shim needs the DRM-free build and is not installed.");
        else lstrcpyA(shim, st == 1 ? "Bridge shim (wsock32.dll): installed and up to date."
                      : st == 0 ? "Bridge shim (wsock32.dll): not installed - Save installs it."
                                : "Bridge shim (wsock32.dll): a different version - Save replaces it.");

        char lobby[MAX_PATH], network[MAX_PATH], bridge[MAX_PATH], v[256];
        ini_paths(lobby, network, bridge);
        GetPrivateProfileStringA("LobbyServer", "Host", "", v, sizeof v, lobby);
        SetDlgItemTextA(dlg, IDC_HOST, v);
        SetDlgItemInt(dlg, IDC_LOBBYPORT, GetPrivateProfileIntA("LobbyServer", "Port", 7070, lobby), FALSE);
        SetDlgItemInt(dlg, IDC_GAMEPORT, GetPrivateProfileIntA("Basics", "gamePort", 5479, network), FALSE);
        SetDlgItemInt(dlg, IDC_BRIDGEPORT, GetPrivateProfileIntA("Bridge", "port", 7072, bridge), FALSE);
        GetPrivateProfileStringA("LobbyServer", "ForceBridge", "false", v, sizeof v, lobby);
        CheckDlgButton(dlg, IDC_FORCE, (!lstrcmpiA(v, "true") || !lstrcmpA(v, "1") || !lstrcmpiA(v, "yes"))
                                           ? BST_CHECKED : BST_UNCHECKED);
        /* Ticked when the billboards mod is installed; otherwise the last choice saved (DisableBillboards), and
           ticked when there is none, since the pages behind the billboards are gone for everyone. */
        GetPrivateProfileStringA("LobbyServer", "DisableBillboards", "true", v, sizeof v, lobby);
        int choice = !lstrcmpiA(v, "true") || !lstrcmpA(v, "1") || !lstrcmpiA(v, "yes");
        CheckDlgButton(dlg, IDC_BILLBOARDS, file_state(BILLBOARDS_DLL, IDR_MOD_BILLBOARDS) || choice
                                                ? BST_CHECKED : BST_UNCHECKED);
    }
    SetDlgItemTextA(dlg, IDC_STATUS, status);
    SetDlgItemTextA(dlg, IDC_MODWARN, warn);
    SetDlgItemTextA(dlg, IDC_SHIM, shim);
    EnableWindow(GetDlgItem(dlg, IDOK), have_game);
}

static int get_port(HWND dlg, int id, const char *what, unsigned *out)
{
    BOOL ok;
    unsigned v = GetDlgItemInt(dlg, id, &ok, FALSE);
    if (!ok || v < 1 || v > 65535) {
        char m[128];
        snprintf(m, sizeof m, "The %s must be a number from 1 to 65535.", what);
        MessageBoxA(dlg, m, "SAdK-ServerConfig", MB_ICONWARNING);
        SetFocus(GetDlgItem(dlg, id));
        return 0;
    }
    *out = v;
    return 1;
}

static void save(HWND dlg)
{
    char host[256], lobby[MAX_PATH], network[MAX_PATH], bridge[MAX_PATH], num[16];
    unsigned lport, gport, bport;
    GetDlgItemTextA(dlg, IDC_HOST, host, sizeof host);
    char *h = host;
    while (*h == ' ' || *h == '"') h++;
    for (char *e = h + strlen(h); e > h && (e[-1] == ' ' || e[-1] == '"'); ) *--e = 0;
    if (!*h) {
        MessageBoxA(dlg, "Enter the lobby server's host name or IP address.", "SAdK-ServerConfig", MB_ICONWARNING);
        SetFocus(GetDlgItem(dlg, IDC_HOST));
        return;
    }
    if (!get_port(dlg, IDC_LOBBYPORT, "lobby port", &lport) || !get_port(dlg, IDC_GAMEPORT, "game port", &gport) ||
        !get_port(dlg, IDC_BRIDGEPORT, "bridge port", &bport)) return;

    ini_paths(lobby, network, bridge);
    int ok = WritePrivateProfileStringA("LobbyServer", "Host", h, lobby);
    snprintf(num, sizeof num, "%u", lport);
    ok &= WritePrivateProfileStringA("LobbyServer", "Port", num, lobby);
    ok &= WritePrivateProfileStringA("LobbyServer", "ForceBridge",
                                     IsDlgButtonChecked(dlg, IDC_FORCE) ? "true" : "false", lobby);
    ok &= WritePrivateProfileStringA("LobbyServer", "DisableBillboards",
                                     IsDlgButtonChecked(dlg, IDC_BILLBOARDS) ? "true" : "false", lobby);
    snprintf(num, sizeof num, "%u", gport);
    ok &= WritePrivateProfileStringA("Basics", "gamePort", num, network);
    snprintf(num, sizeof num, "%u", bport);
    ok &= WritePrivateProfileStringA("Bridge", "port", num, bridge);
    int shim_ok = !exe_supported || shim_state() == 1 || install_shim();
    int mods_ok = !exe_supported || set_billboards_mod(IsDlgButtonChecked(dlg, IDC_BILLBOARDS) == BST_CHECKED);

    if (ok && shim_ok && mods_ok) {
        MessageBoxA(dlg, exe_supported
                    ? "Settings saved and the bridge shim is installed.\n\nStart the game to use the new lobby server."
                    : "Settings saved. The bridge shim was NOT installed: this SADK.exe is not the supported "
                      "DRM-free build, and the shim only works with that exact version.\n\nYou can still play "
                      "on the server, but hosting needs a reachable port and map sharing is unavailable.",
                    "SAdK-ServerConfig", exe_supported ? MB_ICONINFORMATION : MB_ICONWARNING);
    } else {
        char m[512];
        snprintf(m, sizeof m, "%s%s%s\nIs the game still running? Close it and try again.",
                 ok ? "" : "Some settings could not be written.\n",
                 shim_ok ? "" : "The bridge shim (bin\\wsock32.dll) could not be installed.\n",
                 mods_ok ? "" : "The billboards mod (mods\\billboards) could not be installed or removed.\n");
        MessageBoxA(dlg, m, "SAdK-ServerConfig", MB_ICONERROR);
    }
    refresh(dlg);
}

static void browse(HWND dlg)
{
    BROWSEINFOA bi = {0};
    char name[MAX_PATH];
    bi.hwndOwner = dlg;
    bi.pszDisplayName = name;
    bi.lpszTitle = "Choose the folder of \"Die Siedler - Aufbruch der Kulturen\" (or its bin folder)";
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    PIDLIST_ABSOLUTE pidl = SHBrowseForFolderA(&bi);
    if (!pidl) return;
    char path[MAX_PATH];
    if (SHGetPathFromIDListA(pidl, path)) {
        char r[MAX_PATH];
        SetDlgItemTextA(dlg, IDC_FOLDER, normalize_root(path, r) ? r : path);
        refresh(dlg);
    }
    CoTaskMemFree(pidl);
}

static INT_PTR CALLBACK dlg_proc(HWND dlg, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_INITDIALOG: {
        HICON big = LoadImageA(GetModuleHandleA(NULL), MAKEINTRESOURCEA(IDI_APP), IMAGE_ICON,
                               GetSystemMetrics(SM_CXICON), GetSystemMetrics(SM_CYICON), 0);
        HICON small = LoadImageA(GetModuleHandleA(NULL), MAKEINTRESOURCEA(IDI_APP), IMAGE_ICON,
                                 GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON), 0);
        SendMessageA(dlg, WM_SETICON, ICON_BIG, (LPARAM)big);
        SendMessageA(dlg, WM_SETICON, ICON_SMALL, (LPARAM)small);
        SendDlgItemMessageA(dlg, IDC_HOST, EM_LIMITTEXT, 200, 0);
        for (int id = IDC_LOBBYPORT; id <= IDC_BRIDGEPORT; id++) SendDlgItemMessageA(dlg, id, EM_LIMITTEXT, 5, 0);
        char r[MAX_PATH];
        if (detect_root(r)) SetDlgItemTextA(dlg, IDC_FOLDER, r);
        refresh(dlg);
        set_advanced(dlg, FALSE);
        return TRUE;
    }
    case WM_CTLCOLORSTATIC: {
        int id = GetDlgCtrlID((HWND)lp);
        if (id == IDC_MODWARN || (id == IDC_STATUS && (modded || !have_game))) {
            SetTextColor((HDC)wp, RGB(176, 32, 16));
        } else if (id == IDC_STATUS) {
            SetTextColor((HDC)wp, RGB(0, 120, 40));
        } else {
            return FALSE;
        }
        SetBkMode((HDC)wp, TRANSPARENT);
        return (INT_PTR)bg_brush;
    }
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case IDC_BROWSE: browse(dlg); return TRUE;
        case IDC_FOLDER:
            if (HIWORD(wp) == EN_KILLFOCUS) refresh(dlg);
            return TRUE;
        case IDC_ADVANCED: set_advanced(dlg, IsDlgButtonChecked(dlg, IDC_ADVANCED) == BST_CHECKED); return TRUE;
        case IDOK: save(dlg); return TRUE;
        case IDCANCEL: EndDialog(dlg, 0); return TRUE;
        }
        break;
    }
    return FALSE;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show)
{
    (void)prev; (void)cmd; (void)show;
    INITCOMMONCONTROLSEX icc = {sizeof icc, ICC_STANDARD_CLASSES};
    InitCommonControlsEx(&icc);
    CoInitialize(NULL);
    bg_brush = GetSysColorBrush(COLOR_BTNFACE);
    DialogBoxParamA(inst, MAKEINTRESOURCEA(IDD_MAIN), NULL, dlg_proc, 0);
    CoUninitialize();
    return 0;
}
