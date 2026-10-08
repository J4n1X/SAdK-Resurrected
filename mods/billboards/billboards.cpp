// billboards: the lobby's advertising screens show a plain plank area of their own board instead of the dead
// web pages (docs/BINARY_PATCHES.md, "Billboards").
//
// Lobby::CGfxTextureMgr::GetTexture S 00504650 makes each lobby texture on first use. For the names ad0.tga /
// ad1.tga / ad2.tga it does not load the file but makes a web-page texture (CTexture vtbl+0x20, CreateFromURL) of
// http://www.funatics.de/sadk/forwardingN.html. Those pages are gone (HTTP 404), so the screens show red plus IE's
// "navigation canceled" page. This mod hooks GetTexture: for a screen entry that is not made yet it makes the
// texture the way GetTexture makes every other one (S2CE::CResourceMgr::CreateTexture, then vtbl+0x28
// CreateFromFile with the entry's three flags), but from Texture instead of adN.tga, and crops Rect of it with the
// game's own D3DX (d3dx9_38.dll, which also decodes DXT) into a 512x512 texture that replaces the full sheet.
// Every other texture goes to the game's GetTexture unchanged. No game art is shipped.
// Settings: billboards.ini next to mod.dll, [Billboards] Enabled (default true; SAdK-ServerConfig's "Disable
// billboards"), Texture (default sign_ad0.dds), Rect = x0,y0,x1,y1 (default 305,680,730,1005).
#include <sadkmod/game/sadk_noav/fn/Lobby.hpp>
#include <sadkmod/game/sadk_noav/fn/S2CE.hpp>
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/sadkmod.hpp>

#include <d3d9.h>

#include <cstdio>
#include <string>

using sadk::log;
namespace game = sadk::game;
namespace fn = sadk::game::fn;
using game::S2CE::CTexture;
using GetTexture = sadk::Hook<fn::Lobby::CGfxTextureMgr::GetTexture>;

namespace {

typedef HRESULT(WINAPI *d3dx_create_texture_fn)(IDirect3DDevice9 *, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL,
                                                IDirect3DTexture9 **);
typedef HRESULT(WINAPI *d3dx_load_surface_fn)(IDirect3DSurface9 *, const PALETTEENTRY *, const RECT *,
                                              IDirect3DSurface9 *, const PALETTEENTRY *, const RECT *, DWORD, D3DCOLOR);
constexpr DWORD D3DX_FILTER_LINEAR = 3;

bool enabled = true;
std::string texture = "sign_ad0.dds";
int rect[4] = {305, 680, 730, 1005};
bool crop = true;
sadk::msvc::string texture_name;   // Texture as the game's std::string, inline (up to 15 characters)

void billboard_crop(CTexture *tex)
{
    if (!crop) return;
    auto create = sadk::proc<d3dx_create_texture_fn>("d3dx9_38.dll", "D3DXCreateTexture");
    auto load = sadk::proc<d3dx_load_surface_fn>("d3dx9_38.dll", "D3DXLoadSurfaceFromSurface");
    auto *device = static_cast<IDirect3DDevice9 *>(tex->device);
    auto *full = static_cast<IDirect3DTexture9 *>(tex->d3dTexture);
    if (!create || !load || !device || !full) {
        log("crop skipped (d3dx %s, texture %p)", create && load ? "ok" : "missing", static_cast<void *>(full));
        return;
    }
    RECT r = {rect[0], rect[1], rect[2], rect[3]};
    IDirect3DTexture9 *cropped = nullptr;
    IDirect3DSurface9 *src = nullptr, *dst = nullptr;
    HRESULT hr = create(device, 512, 512, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &cropped);
    if (SUCCEEDED(hr)) hr = full->GetSurfaceLevel(0, &src);
    if (SUCCEEDED(hr)) hr = cropped->GetSurfaceLevel(0, &dst);
    if (SUCCEEDED(hr)) hr = load(dst, nullptr, nullptr, src, nullptr, &r, D3DX_FILTER_LINEAR, 0);
    if (src) src->Release();
    if (dst) dst->Release();
    if (FAILED(hr)) {
        if (cropped) cropped->Release();
        log("crop failed (hr %08lx)", static_cast<unsigned long>(hr));
        return;
    }
    tex->d3dTexture = cropped;
    tex->width = 512;
    tex->height = 512;
    full->Release();
    log("screen = %s (%d,%d)-(%d,%d)", texture.c_str(), rect[0], rect[1], rect[2], rect[3]);
}

// GetTexture compares the entry's name with these, case-sensitively (S 00504650).
bool is_screen(const sadk::msvc::string &name)
{
    return name.view() == "ad0.tga" || name.view() == "ad1.tga" || name.view() == "ad2.tga";
}

CTexture *SADK_THISCALL get_texture(game::Lobby::CGfxTextureMgr *mgr, std::int32_t index)
{
    game::ai::lobby::GfxTextureEntry &e = mgr->entries[index];
    if (e.texture || !is_screen(e.name)) return GetTexture::original(mgr, index);
    auto *tex = static_cast<CTexture *>(
        fn::S2CE::CResourceMgr::CreateTexture(static_cast<game::S2CE::CResourceMgr *>(mgr->device), 0));
    e.texture = tex;
    if (tex->vftable->CreateFromFile(tex, &texture_name, e.flag0, e.flag1, e.flag2))
        billboard_crop(tex);
    else
        log("%.*s: %s did not load", int(e.name.size), e.name.data(), texture.c_str());
    if (e.flag3) fn::LobbyGfx_Texture_DecrementRedChannel(tex);   // as GetTexture does for every texture
    return tex;
}

void read_settings()
{
    sadk::Ini ini = sadk::mod_settings();                        // billboards.ini; defaults without a host
    enabled = ini.get_bool("Billboards", "Enabled", true);
    texture = ini.get("Billboards", "Texture", "sign_ad0.dds");
    std::string r = ini.get("Billboards", "Rect", "305,680,730,1005");
    crop = std::sscanf(r.c_str(), "%d,%d,%d,%d", &rect[0], &rect[1], &rect[2], &rect[3]) == 4 && rect[2] > rect[0] &&
           rect[3] > rect[1];
}

}  // namespace

bool billboards_start()
{
    read_settings();
    if (!enabled) {
        log("off ([Billboards] Enabled = false in billboards.ini)");
        return true;
    }
    texture_name = sadk::msvc::string::small(texture);
    bool ok = GetTexture::install(get_texture, "GetTexture: the screens (ad0/ad1/ad2.tga) from Texture");
    log("screens show %.15s, crop %s", texture.c_str(), crop ? "on" : "off");
    return ok;
}

SADKMOD_MAIN(billboards_start, 2, SADKMOD_CLIENT)
