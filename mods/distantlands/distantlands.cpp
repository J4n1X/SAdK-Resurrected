// distantlands: the camera zooms out further and the distance fog no longer swallows the far view.
//
// Zoom. nGame::Camera keeps a zoom step (zoomTarget, +0x18) that the mouse wheel moves by 1 between 1 and zoomMax
// (+0x1c, 4.0 from the constructor); the eye distance is zoomCurrent * 0.3 * distanceScale (70), so one step is 21
// units. nGame::Camera::OnWheelDown S 00786a10 is the only reader of zoomMax. It is hooked and zoomMax written before
// the game's test, so the setting also holds against another patch that keeps writing its own value.
// nGame::Camera::ResetView S 007867c0 (a match starts; the view-reset key) sets the step to 3.0: it is hooked and the
// step set to the start step afterwards, by default the middle of the range.
//
// Fog. The fog is linear between a start and an end distance that the game hands to
// S2CE::CGraphicDevice::SetFogRange S 004d3ae0 every frame (100 and 200 seen in a match, live 2026-10-12): beyond the
// end distance everything takes the fog colour, which at a far zoom is the whole view. SetFogRange is hooked and both
// distances are multiplied. The fog stays enabled: switching it off altogether (the scene's flag +0x720) shows
// rendering faults.
//
// Settings: distantlands.ini next to mod.dll, [DistantLands]
//   MaxZoom   highest zoom step (game: 4; default 12)
//   StartZoom zoom step when a match starts (game: 3; default 0 = half of MaxZoom, in whole steps)
//   FogFactor both fog distances are multiplied by this (1 = the game's own fog; default 20)
#include <sadkmod/game/sadk_noav/fn/S2CE.hpp>
#include <sadkmod/game/sadk_noav/fn/nGame.hpp>
#include <sadkmod/sadkmod.hpp>

#include <cstdio>

namespace game = sadk::game;
using SetFogRange = sadk::Hook<game::fn::S2CE::CGraphicDevice::SetFogRange>;
using WheelDown = sadk::Hook<game::fn::nGame::Camera::OnWheelDown>;
using ResetView = sadk::Hook<game::fn::nGame::Camera::ResetView>;

static float g_fog_factor = 20.0f;
static float g_max_zoom = 12.0f;
static float g_start_zoom = 0.0f;   // 0: half of g_max_zoom

static void SADK_THISCALL on_set_fog_range(game::S2CE::CGraphicDevice *device, float fog_start, float fog_end)
{
    SetFogRange::original(device, fog_start * g_fog_factor, fog_end * g_fog_factor);
}

static void SADK_THISCALL on_wheel_down(game::nGame::Camera *camera)
{
    camera->zoomMax = g_max_zoom;
    WheelDown::original(camera);
}

static void SADK_THISCALL on_reset_view(game::nGame::Camera *camera, std::int32_t mode)
{
    ResetView::original(camera, mode);
    camera->zoomMax = g_max_zoom;
    camera->zoomTarget = camera->zoomCurrent = g_start_zoom;
}

// The setting `key` as a number of at least `minimum`; `value` keeps its default when the setting is not one.
static void read_setting(const char *key, float minimum, float &value)
{
    char fallback[32];
    std::snprintf(fallback, sizeof fallback, "%g", value);
    std::string setting = sadk::mod_settings().get("DistantLands", key, fallback);
    float number = 0;
    if (std::sscanf(setting.c_str(), "%f", &number) == 1 && number >= minimum) value = number;
    else sadk::log("%s = %s: not a number of at least %g, using %g", key, setting.c_str(), minimum, value);
}

bool distantlands_start()
{
    read_setting("MaxZoom", 1.0f, g_max_zoom);
    read_setting("StartZoom", 0.0f, g_start_zoom);
    read_setting("FogFactor", 1.0f, g_fog_factor);
    if (g_start_zoom < 1.0f || g_start_zoom > g_max_zoom) g_start_zoom = static_cast<float>(static_cast<int>(g_max_zoom / 2.0f));
    if (g_start_zoom < 1.0f) g_start_zoom = 1.0f;
    sadk::log("zoom steps up to %g, a match starts at %g, fog distances times %g", g_max_zoom, g_start_zoom, g_fog_factor);
    int hooks = SetFogRange::install(on_set_fog_range, "fog distances multiplied") +
                WheelDown::install(on_wheel_down, "highest zoom step") +
                ResetView::install(on_reset_view, "start zoom step");
    return hooks == 3;
}

SADKMOD_MAIN(distantlands_start, 1, SADKMOD_CLIENT)
