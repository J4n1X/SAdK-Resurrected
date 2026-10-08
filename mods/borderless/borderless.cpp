// borderless: the game's "fullscreen" becomes a borderless window covering one monitor, the picture (at the resolution
// chosen in the game's options) stretched to it. Switching to other windows is instant and the device is never lost.
// The game's own settings are not changed: it still believes it runs fullscreen, so its options, resolution changes
// and saved profile behave as without the mod. Windowed mode is unchanged.
//
// S2CE::CGraphicDevice keeps its display settings as a 9-dword block at +0xa8: width, height, bWindowed (+0xb0), ...;
// bExternalWindow (+0xc8) marks a window the game does not shape. The block comes from the
// player's profile (S2CG::Settings::Load S 006960a0 -> ApplyDisplayMode, options: SetDisplaySize S 00695ab0) and is
// written back by Settings::Store S 00696270, so the mod never touches it. Instead:
//   - CGraphicDevice::InitPresentParameter S 004d3f70 (device creation and every reset, e.g. a resolution change):
//     after the game picked its fullscreen mode, the present parameters become windowed (Windowed = 1, refresh 0);
//     the backbuffer keeps the game's resolution.
//   - CGraphicDevice::ApplyWindowStyle S 004d4190: in fullscreen, the window becomes a WS_POPUP over the monitor
//     (not topmost) instead of the game's topmost popup at 0,0.
//   - The cursor: in fullscreen the game takes cursor positions as screen pixels of a mode starting at 0,0
//     (UiCursor_QueryRelativePosition S 00492410, nUi::Cursor::SetPixelPosition S 00492620, WarpToPosition
//     S 004926d0). Around those three calls the windowed flag reads 1, so they use the window's client area.
//   - The lobby's mouse look (right button): LobbyMenu::LobbyAction warps the cursor to the centre of the window's
//     client area (clientWidth/Height from GetClientRect) and measures the offset from it each frame, but its
//     OnMouseMove S 00429360 gets picture pixels (LobbyDesktop::OnMouseMove S 0042e8c0: cursor position x
//     nUi_RelativeToPixelsX/Y). Stretched, the two differ and the camera keeps turning; in borderless mode the
//     mod passes the cursor's real client position instead (exact, so no slow drift from rounding).
// Settings: borderless.ini next to mod.dll, [Borderless] Monitor = primary | n (\\.\DISPLAYn).
#include <sadkmod/game/sadk_noav/fn/LobbyMenu.hpp>
#include <sadkmod/game/sadk_noav/fn/S2CE.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/game/sadk_noav/fn/nUi.hpp>
#include <sadkmod/sadkmod.hpp>

#include <windows.h>
#include <d3d9.h>

#include <cstdio>
#include <cstring>
#include <string>

namespace game = sadk::game;
namespace fn = sadk::game::fn;
using Device = game::S2CE::CGraphicDevice;
using Present = sadk::Hook<fn::S2CE::CGraphicDevice::InitPresentParameter>;
using ApplyStyle = sadk::Hook<fn::S2CE::CGraphicDevice::ApplyWindowStyle>;
using QueryCursor = sadk::Hook<fn::UiCursor_QueryRelativePosition>;
using CursorSetPixel = sadk::Hook<fn::nUi::Cursor::SetPixelPosition>;
using Warp = sadk::Hook<fn::nUi::Cursor::WarpToPosition>;
using MouseLook = sadk::Hook<fn::LobbyMenu::LobbyAction::OnMouseMove>;

namespace {

std::string monitor_setting = "primary";

Device *device() { return static_cast<Device *>(fn::GetGraphicDevice()); }
// The game's fullscreen, on a window it shapes itself: what the mod turns into a borderless window.
bool borderless(Device *dev) { return dev && !dev->bWindowed && !dev->bExternalWindow; }

struct FindMonitor {
    char name[32];
    RECT rect;
    bool found;
};

BOOL CALLBACK match_monitor(HMONITOR m, HDC, LPRECT, LPARAM p)
{
    auto *f = reinterpret_cast<FindMonitor *>(p);
    MONITORINFOEXA mi = {};
    mi.cbSize = sizeof mi;
    if (GetMonitorInfoA(m, &mi) && !lstrcmpiA(mi.szDevice, f->name)) {
        f->rect = mi.rcMonitor;
        f->found = true;
        return FALSE;
    }
    return TRUE;
}

// The configured monitor; the primary one when the setting names none or a display that is not there.
RECT target_monitor()
{
    int n = 0;
    if (std::sscanf(monitor_setting.c_str(), "%d", &n) == 1 && n > 0) {
        FindMonitor f = {};
        std::snprintf(f.name, sizeof f.name, "\\\\.\\DISPLAY%d", n);
        EnumDisplayMonitors(nullptr, nullptr, match_monitor, reinterpret_cast<LPARAM>(&f));
        if (f.found) return f.rect;
        static bool warned;
        if (!warned) sadk::log("Monitor = %s: no such display, using the primary one", monitor_setting.c_str());
        warned = true;
    }
    MONITORINFO mi = {};
    mi.cbSize = sizeof mi;
    GetMonitorInfoA(MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY), &mi);
    return mi.rcMonitor;
}

// While a fullscreen-only cursor path runs, the game sees windowed (client-area) coordinates.
struct PretendWindowed {
    Device *dev;
    bool active;
    PretendWindowed() : dev(device()), active(borderless(dev)) { if (active) dev->bWindowed = true; }
    ~PretendWindowed() { if (active) dev->bWindowed = false; }
};

// The game fills `pp` (a D3DPRESENT_PARAMETERS) for fullscreen; turning it into a windowed device of the same
// backbuffer size is what makes D3D stretch the picture to the window.
bool SADK_THISCALL present_parameters(Device *dev, std::int32_t *pp)
{
    bool ok = Present::original(dev, pp);
    if (ok && borderless(dev)) {
        auto *params = reinterpret_cast<D3DPRESENT_PARAMETERS *>(pp);
        params->Windowed = TRUE;
        params->FullScreen_RefreshRateInHz = 0;   // must be 0 for a windowed device
        sadk::log("fullscreen %dx%d -> borderless window (picture stretched to the monitor)",
                  int(params->BackBufferWidth), int(params->BackBufferHeight));
    }
    return ok;
}

// The window covers the chosen monitor without a frame. Not topmost (unlike the game's fullscreen window), so other
// windows can come to the front.
void cover_monitor(HWND w)
{
    RECT r = target_monitor();
    SetWindowLongA(w, GWL_STYLE, WS_POPUP | WS_VISIBLE);
    SetWindowLongA(w, GWL_EXSTYLE, GetWindowLongA(w, GWL_EXSTYLE) & ~WS_EX_TOPMOST);
    SetWindowPos(w, HWND_TOP, r.left, r.top, r.right - r.left, r.bottom - r.top, SWP_FRAMECHANGED | SWP_SHOWWINDOW);
}

void SADK_THISCALL apply_style(Device *dev)
{
    if (!borderless(dev) || !dev->hWnd) return ApplyStyle::original(dev);
    cover_monitor(static_cast<HWND>(dev->hWnd));
}

float *SADK_STDCALL query_cursor(float *out)
{
    PretendWindowed p;
    return QueryCursor::original(out);
}

void SADK_THISCALL set_pixel(game::nUi::Cursor *c, std::int32_t x, std::int32_t y)
{
    PretendWindowed p;
    CursorSetPixel::original(c, x, y);
}

void SADK_THISCALL warp(game::nUi::Cursor *c, game::nUi::Position *to)
{
    PretendWindowed p;
    Warp::original(c, to);
}

void SADK_THISCALL mouse_look(game::LobbyMenu::LobbyAction *action, std::int32_t x, std::int32_t y)
{
    Device *dev = device();
    POINT p;
    if (borderless(dev) && dev->hWnd && GetCursorPos(&p) && ScreenToClient(static_cast<HWND>(dev->hWnd), &p)) {
        x = p.x;
        y = p.y;
    }
    MouseLook::original(action, x, y);
}

}  // namespace

bool borderless_start()
{
    monitor_setting = sadk::mod_settings().get("Borderless", "Monitor", "primary");
    sadk::log("monitor: %s", monitor_setting.c_str());
    return Present::install(present_parameters) && ApplyStyle::install(apply_style) && QueryCursor::install(query_cursor) &&
           CursorSetPixel::install(set_pixel) && Warp::install(warp) && MouseLook::install(mouse_look);
}

SADKMOD_MAIN(borderless_start, 1, SADKMOD_CLIENT)
