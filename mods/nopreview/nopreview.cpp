// nopreview: choosing a map without a preview picture (<map>.bmp) no longer crashes the game.
//
// LobbyMenu::SetupGameDialog::UpdateMapPreviewImage S 00454fc0 (hosting) and nMenu::FreeGamePanel::UpdateMapPreviewImage
// S 005e7220 (offline free game) are the same code: when the chosen map differs from the previewed one, the old
// preview texture is destroyed (UiResourceManager::ReleaseTexture S 00493ae0) and previewMapName is cleared; only if
// the new map's .bmp exists is a new texture loaded, put into the MapPreview widget's shape and the name stored again.
// Without a .bmp the widget keeps the destroyed texture and stays visible, and the next frame draws it
// (S2CE::CTexture::LinkToStage S 004e7520 reads its null device at 004e7562). Stock maps all have a .bmp; custom maps may not.
//
// Both functions are hooked: when the game released a preview and loaded none, the widget's texture is cleared.
// nUi::Shape draws nothing without a texture (UiSprite_RenderToOwnerRect S 004aa310), so the preview area stays empty.
#include <sadkmod/game/sadk_noav/fn/LobbyMenu.hpp>
#include <sadkmod/game/sadk_noav/fn/nMenu.hpp>
#include <sadkmod/sadkmod.hpp>

namespace game = sadk::game;
using HostPreview = sadk::Hook<game::fn::LobbyMenu::SetupGameDialog::UpdateMapPreviewImage>;
using FreeGamePreview = sadk::Hook<game::fn::nMenu::FreeGamePanel::UpdateMapPreviewImage>;

// `original` is the game's UpdateMapPreviewImage for `panel`, already bound to its arguments.
template <typename Panel, typename Original>
static void update_preview(Panel *panel, Original original)
{
    bool had_preview = panel->previewMapName.size != 0;
    original();
    if (had_preview && panel->previewMapName.size == 0 && panel->mapPreview)
        panel->mapPreview->shape.texture = nullptr;
}

static void SADK_THISCALL on_host_preview(game::LobbyMenu::SetupGameDialog *dialog, void *map_name)
{
    update_preview(dialog, [&] { HostPreview::original(dialog, map_name); });
}

static void SADK_THISCALL on_free_game_preview(game::nMenu::FreeGamePanel *panel, void *map_name)
{
    update_preview(panel, [&] { FreeGamePreview::original(panel, map_name); });
}

bool nopreview_start()
{
    int hooks = HostPreview::install(on_host_preview, "host dialog: no stale preview for a map without .bmp") +
                FreeGamePreview::install(on_free_game_preview, "free game: no stale preview for a map without .bmp");
    return hooks == 2;
}

SADKMOD_MAIN(nopreview_start, 1, SADKMOD_CLIENT)
