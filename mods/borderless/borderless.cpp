// borderless: "fullscreen" becomes a borderless window covering the monitor, at the monitor's resolution. Switching
// to other windows is instant and the device is never lost; windowed mode is unchanged.
//
// S2CE::CGraphicDevice keeps its display settings as a 9-dword block at +0xa8: width, height, and in the third
// dword's low byte the windowed flag (+0xb0); +0xc8 marks a window the game does not own. Init S 004da2a0 takes such
// a block (from start-up, CApplicationEx::InitEngineLayer S 00405590; from the options, S2CG::Settings::
// ApplyDisplayMode; and its own block back from HandleWindowMessage S 004da8d0 on WM_DISPLAYCHANGE) and turns it into
// D3D present parameters (InitPresentParameter S 004d3f70: windowed -> Windowed = 1, otherwise an exclusive
// fullscreen mode); ApplyWindowStyle S 004d4190 then shapes the window (windowed: a caption window sized to the
// backbuffer; fullscreen: a topmost popup at 0,0).
//
// This mod: when Init is asked for fullscreen, it asks for a windowed device at the size of the game window's monitor
// instead and remembers that borderless is on; ApplyWindowStyle then makes the window a borderless popup over that
// monitor. Init calls with the device's own block (the re-initialisation after a desktop change) keep the mode.
#include <sadkmod/game/sadk_noav/fn/S2CE.hpp>
#include <sadkmod/sadkmod.hpp>

#include <windows.h>

#include <cstring>

namespace game = sadk::game;
using Device = game::S2CE::CGraphicDevice;
using Init = sadk::Hook<game::fn::S2CE::CGraphicDevice::Init>;
using ApplyStyle = sadk::Hook<game::fn::S2CE::CGraphicDevice::ApplyWindowStyle>;

namespace {

constexpr std::size_t WINDOWED = 0xb0, EXTERNAL_WINDOW = 0xc8;
bool borderless;

RECT monitor_of(Device *dev)
{
    HWND w = static_cast<HWND>(dev->hWnd);
    HMONITOR m = MonitorFromWindow(w ? w : GetActiveWindow(), MONITOR_DEFAULTTOPRIMARY);
    MONITORINFO mi = {};
    mi.cbSize = sizeof mi;
    if (m && GetMonitorInfoA(m, &mi)) return mi.rcMonitor;
    return RECT{0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)};
}

bool SADK_THISCALL init(Device *dev, std::int32_t *mode)
{
    if (!mode || *sadk::at<std::uint8_t>(dev, EXTERNAL_WINDOW)) return Init::original(dev, mode);
    bool own_block = mode == reinterpret_cast<std::int32_t *>(&dev->backBufferWidth);
    if (!own_block) borderless = (mode[2] & 0xff) == 0;            // the caller asks for fullscreen
    if (!borderless) return Init::original(dev, mode);
    std::int32_t changed[9];
    std::memcpy(changed, mode, sizeof changed);
    RECT r = monitor_of(dev);
    changed[0] = r.right - r.left;
    changed[1] = r.bottom - r.top;
    changed[2] = (changed[2] & ~0xff) | 1;                          // windowed device
    sadk::log("fullscreen %dx%d -> borderless %dx%d", mode[0], mode[1], changed[0], changed[1]);
    return Init::original(dev, changed);
}

void SADK_THISCALL apply_style(Device *dev)
{
    if (!borderless || *sadk::at<std::uint8_t>(dev, EXTERNAL_WINDOW) || !dev->hWnd) return ApplyStyle::original(dev);
    HWND w = static_cast<HWND>(dev->hWnd);
    RECT r = monitor_of(dev);
    SetWindowLongA(w, GWL_STYLE, WS_POPUP | WS_VISIBLE);
    SetWindowLongA(w, GWL_EXSTYLE, GetWindowLongA(w, GWL_EXSTYLE) & ~WS_EX_TOPMOST);
    SetWindowPos(w, HWND_TOP, r.left, r.top, r.right - r.left, r.bottom - r.top, SWP_FRAMECHANGED | SWP_SHOWWINDOW);
}

}  // namespace

bool borderless_start()
{
    return Init::install(init, "CGraphicDevice::Init: fullscreen -> borderless window") &&
           ApplyStyle::install(apply_style, "CGraphicDevice::ApplyWindowStyle: borderless popup");
}

SADKMOD_MAIN(borderless_start)
