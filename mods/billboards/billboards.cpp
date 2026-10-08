// billboards: the lobby's advertising screens show a plain plank area of their own board instead of the dead
// web pages (docs/BINARY_PATCHES.md, "Billboards").
//
// Lobby::CGfxTextureMgr::GetTexture S 00504650: textures named ad0/ad1/ad2.tga become an embedded Internet Explorer
// rendering http://www.funatics.de/sadk/forwardingN.html. Those pages are gone (HTTP 404), so the screens show red
// plus IE's "navigation canceled" page. This mod
//   - renames the three compare literals, so the screens load from file like any other texture;
//   - turns GetTexture's file load, the virtual call `MOV EDX,[ESI+0x28]; MOV ECX,EAX; CALL EDX` at 00504806
//     (S2CE::CTexture::CreateFromFile S 004e80d0), into `MOV ECX,EAX; CALL billboard_load`, which loads Texture
//     instead of adN.tga and crops Rect of it with the game's own D3DX (d3dx9_38.dll, which also decodes DXT) into a
//     512x512 texture that replaces the full sheet. No game art is shipped.
// Settings: billboards.ini next to mod.dll, [Billboards] Enabled (default true; SAdK-ServerConfig's "Disable
// billboards"), Texture (default sign_ad0.dds), Rect = x0,y0,x1,y1 (default 305,680,730,1005).
#include <sadkmod/game/sadk_noav/types.hpp>
#include <sadkmod/sadkmod.hpp>

#include <d3d9.h>

#include <cstdio>
#include <string>

using sadk::log;
using sadk::game::S2CE::CTexture;

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

// Stands in for the loader call at 00504806: CreateFromFile through the texture's vtable, as GetTexture did.
bool SADK_THISCALL billboard_load(CTexture *tex, void *path, bool single_level, bool default_pool, bool full_quality)
{
    auto *name = static_cast<const sadk::msvc::string *>(path);
    bool screen = name->equals_icase("ad0.tga") || name->equals_icase("ad1.tga") || name->equals_icase("ad2.tga");
    bool ok = tex->vftable->CreateFromFile(tex, screen ? &texture_name : path, single_level, default_pool, full_quality);
    if (ok && screen) billboard_crop(tex);
    return ok;
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
    int ok = 0;
    static const std::uintptr_t literals[3] = {0x007e6240, 0x007e6208, 0x007e61d0};   // "ad0.tga" .. "ad2.tga"
    for (int i = 0; i < 3; i++) {
        auto digit = static_cast<std::uint8_t>('0' + i);
        ok += sadk::patch(literals[i], {'a', 'd', digit}, {'#', 'd', digit}, "billboard texture from disk");
    }
    ok += sadk::patch(0x00504806, {0x8B, 0x56, 0x28, 0x8B, 0xC8, 0xFF, 0xD2},
                      sadk::Bytes{0x8B, 0xC8} + sadk::call_to(sadk::Module::sadk, 0x00504808, (void *)billboard_load),
                      "billboard screen texture swap");
    log("%d of 4 patches active (screens show %.15s, crop %s)", ok, texture.c_str(), crop ? "on" : "off");
    return ok == 4;
}

SADKMOD_MAIN(billboards_start, 1, SADKMOD_CLIENT)
