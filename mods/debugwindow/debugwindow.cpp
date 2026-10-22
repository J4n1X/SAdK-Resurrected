// debugwindow: F12 in an offline match opens the developers' "Debug" window (the map editor, nMenu::Debug) and hides
// the HUD; F12 again closes it and brings the HUD back. What the debugger did by hand on 2026-10-12
// (docs/mod-concepts/mapedit.md §1-3, docs/sim/map-editor-devtools.md).
//
// Key. The game samples every key with GetAsyncKeyState once per frame while its window is active
// (nUi::BaseAction::PollAsyncKeys S 00490e90, from nMenu::System::Update S 005da500) into asyncDown; nothing in the
// game reads F12 (no key handler compares 0x7b). nMenu::Game::Update S 005efea0 is hooked and acts on the frame F12
// goes down. nMenu::System::Update can run more than once per frame (the mouse-button messages call it too), so the
// mod keeps the last state it saw instead of asking for the first frame down.
//
// Window. nMenu::Game::ToggleScreen(game, 1) S 005ea960 opens dialog slot 1 when it is closed (closing the other
// dialogs first) and closes it when it is open; nothing in the game passes slot 1. The window's own OnShow
// S 0060a340 hides the HUD (nMenu::Game +0x968) and the fog of war, and its OnHide S 00602000 restores both.
// Offline only, through the gate the game puts on its typed cheats (NComm_Manager_IsRole0, nMenu::Game::OnKeyDown
// S 005ec340): every tool of the window changes the simulation outside the command stream.
//
// Two faults of the window are taken out, as the debugger did:
// - Enter inside it hides the window and the whole game screen, world included (nMenu::Debug::Update S 00609130 asks
//   nUi::GameAction::IsEnterTriggered S 004912c0). While that update runs, Enter reads as not pressed.
// - OnShow sets the camera's distance scale (nGame::System +0x2d0 +0x2c) from 70 to 180, which at a far zoom puts
//   the whole view into the distance haze. The scale the camera had is kept; OnHide writes the game's 70 as before.
#include <sadkmod/game/sadk_noav/fn/_global.hpp>
#include <sadkmod/game/sadk_noav/fn/nMenu.hpp>
#include <sadkmod/game/sadk_noav/fn/nUi.hpp>
#include <sadkmod/sadkmod.hpp>

namespace game = sadk::game;
using GameUpdate = sadk::Hook<game::fn::nMenu::Game::Update>;
using EditorUpdate = sadk::Hook<game::fn::nMenu::Debug::Update>;
using EditorShow = sadk::Hook<game::fn::nMenu::Debug::OnShow>;
using EnterTriggered = sadk::Hook<game::fn::nUi::GameAction::IsEnterTriggered>;

constexpr std::int32_t EDITOR_SCREEN = 1;   // nMenu::System dialog slot of nMenu::Debug

static bool g_f12_down = true;   // true at start: a key already held when a match begins does not toggle
static bool g_in_editor_update = false;

static bool f12_pressed()
{
    game::nUi::GameAction *input = game::fn::nUi::GameAction::GetInstance();
    bool down = game::fn::nUi::BaseAction::IsAsyncKeyDown(&input->base, VK_F12);
    bool pressed = down && !g_f12_down;
    g_f12_down = down;
    return pressed;
}

static void SADK_THISCALL on_game_update(game::nMenu::Game_offset_0x24_ face)
{
    game::nMenu::Game *screen = face->object();
    if (screen->desktop.base.attached && f12_pressed() &&
        game::fn::NComm_Manager_IsRole0(game::fn::NComm_GetManager()))
    {
        bool open = game::fn::nMenu::System::IsScreenAttached(screen->menuSystem, EDITOR_SCREEN);
        sadk::log("F12: %s the debug window", open ? "closing" : "opening");
        game::fn::nMenu::Game::ToggleScreen(screen, EDITOR_SCREEN);
    }
    GameUpdate::original(face);
}

static void SADK_THISCALL on_editor_update(game::nMenu::Debug_offset_0x24_ face)
{
    g_in_editor_update = true;
    EditorUpdate::original(face);
    g_in_editor_update = false;
}

static bool SADK_THISCALL on_enter_triggered(game::nUi::GameAction *input, std::int32_t source)
{
    return !g_in_editor_update && EnterTriggered::original(input, source);
}

static void SADK_THISCALL on_editor_show(game::nMenu::Debug_offset_0x20_ face, void *parent)
{
    game::nMenu::Game *screen = game::fn::nMenu::System::GetInstance()->game;
    float scale = screen->gameSystem->camera.distanceScale;
    EditorShow::original(face, parent);
    screen->gameSystem->camera.distanceScale = scale;
}

bool debugwindow_start()
{
    int hooks = GameUpdate::install(on_game_update, "F12 toggles the debug window") +
                EditorUpdate::install(on_editor_update, "debug window: Enter does not blank the screen") +
                EnterTriggered::install(on_enter_triggered) +
                EditorShow::install(on_editor_show, "debug window: camera keeps its distance scale");
    return hooks == 4;
}

SADKMOD_MAIN(debugwindow_start, 1, SADKMOD_CLIENT)
