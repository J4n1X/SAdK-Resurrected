// oscursor: the game's mouse cursors are shown as Windows cursors instead of Direct3D's, so the cursor stays visible
// on current Windows at any display scaling (docs/BINARY_PATCHES.md, "Windows cursor").
//
// The game (engine.ini [Engine] hardwareCursor = 1, the default; read once by CGraphicDevice::Init S 004da2a0) loads
// each cursor of game\ui\layout\cursors.xml (all 32x32, 32-bit TGA) into a Direct3D texture
// (HwCursorSlot::LoadFromFile S 004d4b70, managed pool, the file's format; the default cursor in SetHWCursor S 004d6b50)
// and shows it with IDirect3DDevice9::SetCursorProperties / ShowCursor (ShowHWCursor S 004d69d0, SetCustomCursor
// S 004d6ca0; on WM_SETCURSOR, HandleWindowMessage S 004da8d0 shows it again). Direct3D 9 only turns such a cursor
// into a Windows cursor when its size is the system's cursor size (32x32 up to 125% display scaling, 48x48 at 150%);
// otherwise it draws the cursor itself, and on current Windows that cursor is invisible (PCGamingWiki: the pointer
// of The Settlers II 10th Anniversary, the same engine, disappears above 125% scaling).
//
// The mod makes a Windows cursor (CreateIconIndirect) from each cursor texture's pixels and the slot's hotspot, and
// shows it with SetCursor where the game would show its Direct3D cursor: ShowHWCursor, SetCustomCursor (cursor
// changes and the animated clock) and WM_SETCURSOR in the client area. Direct3D's cursor is never switched on.
// With hardwareCursor = 0 the game uses the Windows arrow already and the mod does nothing.
#include <sadkmod/game/sadk_noav/fn/S2CE.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/sadkmod.hpp>

#include <windows.h>
#include <d3d9.h>

#include <cstring>
#include <vector>

namespace game = sadk::game;
namespace fn = sadk::game::fn;
using Device = game::S2CE::CGraphicDevice;
using ShowHW = sadk::Hook<fn::S2CE::CGraphicDevice::ShowHWCursor>;
using SetCustom = sadk::Hook<fn::S2CE::CGraphicDevice::SetCustomCursor>;
using WindowMessage = sadk::Hook<fn::S2CE::CGraphicDevice::HandleWindowMessage>;

namespace {

constexpr std::int32_t kDeviceLost = 1;   // CGraphicDevice::deviceState: ShowHWCursor does nothing then

// A Windows cursor made from one cursor texture, kept while the texture is the same.
struct Made {
    IDirect3DTexture9 *texture;
    std::int32_t hotspotX, hotspotY;
    HCURSOR cursor;
};
std::vector<Made> g_made;

// The texture's top mip level as a 32-bit colour cursor. Only A8R8G8B8 / X8R8G8B8 textures (what a 32-bit TGA
// becomes); anything else gives no cursor and the game's own path stays in charge.
HCURSOR make_cursor(IDirect3DTexture9 *texture, std::int32_t hotspotX, std::int32_t hotspotY)
{
    D3DSURFACE_DESC desc;
    if (FAILED(texture->GetLevelDesc(0, &desc))) return nullptr;
    bool alpha = desc.Format == D3DFMT_A8R8G8B8;
    if (!alpha && desc.Format != D3DFMT_X8R8G8B8) {
        sadk::log("cursor texture format %d not supported, Direct3D cursor kept", static_cast<int>(desc.Format));
        return nullptr;
    }
    D3DLOCKED_RECT locked;
    if (FAILED(texture->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) return nullptr;
    BITMAPV5HEADER header = {};
    header.bV5Size = sizeof header;
    header.bV5Width = static_cast<LONG>(desc.Width);
    header.bV5Height = -static_cast<LONG>(desc.Height);   // top-down, as the texture
    header.bV5Planes = 1;
    header.bV5BitCount = 32;
    header.bV5Compression = BI_BITFIELDS;
    header.bV5RedMask = 0x00ff0000;
    header.bV5GreenMask = 0x0000ff00;
    header.bV5BlueMask = 0x000000ff;
    header.bV5AlphaMask = 0xff000000;
    void *bits = nullptr;
    HDC screen = GetDC(nullptr);
    HBITMAP colour = CreateDIBSection(screen, reinterpret_cast<BITMAPINFO *>(&header), DIB_RGB_COLORS, &bits, nullptr, 0);
    ReleaseDC(nullptr, screen);
    if (colour && bits) {
        for (UINT y = 0; y < desc.Height; ++y) {
            auto *from = reinterpret_cast<const std::uint32_t *>(static_cast<const char *>(locked.pBits) + y * locked.Pitch);
            auto *to = static_cast<std::uint32_t *>(bits) + y * desc.Width;
            for (UINT x = 0; x < desc.Width; ++x) to[x] = alpha ? from[x] : (from[x] | 0xff000000u);
        }
    }
    texture->UnlockRect(0);
    if (!colour || !bits) {
        if (colour) DeleteObject(colour);
        return nullptr;
    }
    HBITMAP mask = CreateBitmap(static_cast<int>(desc.Width), static_cast<int>(desc.Height), 1, 1, nullptr);
    ICONINFO info = {};
    info.fIcon = FALSE;
    info.xHotspot = static_cast<DWORD>(hotspotX);
    info.yHotspot = static_cast<DWORD>(hotspotY);
    info.hbmMask = mask;
    info.hbmColor = colour;
    HCURSOR cursor = CreateIconIndirect(&info);
    DeleteObject(colour);
    DeleteObject(mask);
    return cursor;
}

HCURSOR cursor_for(void *texture, std::int32_t hotspotX, std::int32_t hotspotY)
{
    if (!texture) return nullptr;
    auto *tex = static_cast<IDirect3DTexture9 *>(texture);
    for (Made &m : g_made)
        if (m.texture == tex && m.hotspotX == hotspotX && m.hotspotY == hotspotY) return m.cursor;
    HCURSOR cursor = make_cursor(tex, hotspotX, hotspotY);
    if (cursor) g_made.push_back({tex, hotspotX, hotspotY, cursor});
    return cursor;
}

// The cursor the game would show now: the current slot's (cursors.xml), else the default one, as ShowHWCursor picks.
HCURSOR current(Device *dev)
{
    std::int32_t slot = dev->currentCursorSlot;
    if (slot >= 0 && slot < dev->cursorSlotCount) {
        game::ai::gfx::HwCursorSlot &s = dev->cursorSlots[slot];
        return cursor_for(s.pTexture, s.hotspotX, s.hotspotY);
    }
    return cursor_for(dev->pCursorTexture, dev->cursorHotspotX, dev->cursorHotspotY);
}

// The mod's cursors only stand in for the game's Direct3D cursor (hardwareCursor = 1).
bool active(Device *dev) { return dev->bHwCursorLoaded != 0; }

void SADK_THISCALL show_hw_cursor(Device *dev, bool show)
{
    if (!active(dev)) return ShowHW::original(dev, show);
    if (dev->deviceState == kDeviceLost) return;
    HCURSOR cursor = current(dev);
    if (!cursor) return ShowHW::original(dev, show);   // a texture the mod cannot read: the game's way
    SetCursor(show ? cursor : nullptr);
    dev->bHwCursorVisible = show;
}

void SADK_THISCALL set_custom_cursor(Device *dev, std::int32_t slot)
{
    std::int32_t before = dev->currentCursorSlot;
    SetCustom::original(dev, slot);   // slot bookkeeping (and Direct3D's cursor image, which stays hidden)
    if (active(dev) && dev->bHwCursorVisible && dev->currentCursorSlot != before)
        if (HCURSOR cursor = current(dev)) SetCursor(cursor);
}

// WM_SETCURSOR in the client area: the game's cursor (or none while the game hides it). Elsewhere (a window's frame)
// Windows' own cursor.
std::int32_t SADK_THISCALL window_message(Device *dev, game::WinDef_h::HWND hwnd, std::uint32_t msg, std::int32_t wparam,
                                          std::uint32_t lparam)
{
    if (msg != WM_SETCURSOR || dev->deviceState != 0 || !active(dev))
        return WindowMessage::original(dev, hwnd, msg, wparam, lparam);
    if (LOWORD(lparam) != HTCLIENT) return 0;
    HCURSOR cursor = current(dev);
    if (!cursor) return WindowMessage::original(dev, hwnd, msg, wparam, lparam);
    SetCursor(dev->bHwCursorVisible ? cursor : nullptr);
    return 1;
}

}  // namespace

bool oscursor_start()
{
    return ShowHW::install(show_hw_cursor, "ShowHWCursor: Windows cursor") &&
           SetCustom::install(set_custom_cursor, "SetCustomCursor: Windows cursor") &&
           WindowMessage::install(window_message, "WM_SETCURSOR: Windows cursor");
}

SADKMOD_MAIN(oscursor_start, 1, SADKMOD_CLIENT)
