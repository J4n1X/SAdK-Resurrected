# Map editor and developer tools inside the client

Binary: `sadk_noav.exe` (addresses `S 00xxxxxx`). Tags: **[known]** = read at the address or in the named data
file, **[inferred]** = one step of reasoning from what is visible, **[TODO]** = open.

Related documents: [../map-format.md](../map-format.md) (the `.s2m` file, grid bits, harbour and route rules),
[map-resources.md](map-resources.md) (grids, `MapModifier`, deposits, doodads), [save-format.md](save-format.md)
(the container, `GameFile_Save`, the loader), [logic-core.md](logic-core.md) (tick loop, map-update batch),
[navy.md](navy.md) (harbours, routes, ships), [camera-input-cutscenes.md](camera-input-cutscenes.md) (typed
cheats, debug icon row), [app-shell.md](app-shell.md) (command line, log files), [lua-runtime.md](lua-runtime.md)
and [../lua-surface.md](../lua-surface.md) (script libraries), [../subsystems.md](../subsystems.md) §5,
[../BINARY_PATCHES.md](../BINARY_PATCHES.md) (the CVar-server patch).

---

## 1. Purpose and scope

The shipped client still contains the developers' in-game map editor and several debugging aids. This document
specifies them as far as they change or expose game state:

- the editor screen `nMenu::Debug` (a dialog of the in-game menu system) with 19 tool modes: what each tool
  writes into the running world, under which placement rules, with which constants;
- `NLogic::Edit`, the editing interface of the logic system, and its **batch-editing** flag;
- how the editor saves and loads a map, and which derived data it recomputes before saving;
- the editor's own files: the copy buffer `copypaste.dat` and the two preset scripts in `scripts\editor\`;
- the Lua library `editor`;
- the image-driven map generator ("Infomap" tool) and the unreachable noise terrain generator;
- the developer variables (`CVar`), their TCP server and its text protocol;
- the Lua debugger hook, log switches, debug overlays, typed cheats (summary with links).

It is the reference for a map editor in the remake and for the editing rules a converter has to respect. The
map file itself is specified in [../map-format.md](../map-format.md) and is not repeated here.

**Reachability.** `nMenu::System::Initialize` S 005dda30 constructs the `Debug` dialog (0x6608 bytes) and stores
it in the menu system (`System + 0x14`) [known]. No code path that opens it has been found: in the decompiled
image the typed field is referenced only by `Initialize` [known for the cached image; a write through an
untyped pointer would not show]. All editor behaviour below is therefore read from code, not from a running
editor. See §10 question 1.

---

## 2. Data model

### 2.1 `NLogic::Edit` (0x0c bytes, vftable S 007e7c28, `NLogic::System + 0x38`)

| Offset | Type | Field | Meaning | Evidence |
|---|---|---|---|---|
| +0x00 | ptr | vftable | 13 slots, below | [known] S 00538c70 |
| +0x04 | u8 | `batchEditing` | 0 at construction. While non-zero the logic tick is skipped and several subsystems take their "set-up" branch (§3.2) | [known] S 00538a60, S 00527070 |
| +0x05 | u8[3] | `flags[0..2]` | three flags, 0 at construction; get / set by slots 11 / 12. Flag 1 is read by the free-fly camera (`nGame::Camera::UpdateFreeFlyMode` S 00786ae0): with the game screen's byte +0x3b clear, mouse look needs the menu system's `uiSuppressed` byte and `GetFlag(1)` both non-zero. No call of slot 12 and no reader of flags 0 and 2 is in the decompiled image | [known] S 00538c50, S 00538c60, S 00786ae0; [TODO] who sets them (§10 question 4) |
| +0x08 | ptr | `gameSystem` | owning `NLogic::System` | [known] S 00538c70 |

Virtual slots [known: vftable bytes at S 007e7c28]:

| Slot | Address | Method | Effect |
|---|---|---|---|
| 0 | 00538a60 | `SetBatchEditing(active)` | stores the flag; on a change **from non-zero to another value** it first calls `MapModifier_FlushDirtyRects` (§3.3) |
| 1 | 00538c90 | `GetBatchEditing()` | returns the byte at +4 |
| 2 | 00538aa0 | `SetVertexElevation(vertex, height)` | `MapModifier::SetVertexElevation(vertex, height, deferred = 1)` |
| 3 | 00538ac0 | `SetCellPattern(cell, patternId)` | `MapModifier::SetCellPattern(cell, id, deferNotify = 1)` |
| 4 | 00538ae0 | `CreateDeposit(cell, &depositId)` | only if `GameQuery::CanPlaceDepositAt(cell, property)`; then `NResources::System::CreateDeposit(&id, cell, true)`; otherwise nothing |
| 5 | 00538b20 | `RemoveResourceAt(cell)` | removes the deposit on the cell, if any |
| 6 | 00538b50 | `PlaceBuilding(player, cell, &typeId)` | only if `GameQuery::CanPlaceBuildingAt(size = property +0x3c, cell, player, 0, null, 0)`; then `NVillage::System::PlaceBuilding` |
| 7 | 00538bb0 | `RemoveBuildingAt(cell)` | `FindBuildingAtOrNearest(cell, 0)`, then `RemoveBuilding(unique, spill = true)` |
| 8 | 00538bf0 | `AddDoodad(&doodadId, finePos)` | `NDoodads::System::AddDoodadAtFinePos`, no check |
| 9 | 00538c10 | `RemoveDoodadAt(finePos)` | removes the doodad found at that fine position, if any |
| 10 | 00538ca0 | `AddStartPosition(cell)` | appends to `MapInfo` start positions, no duplicate check |
| 11 | 00538c60 | `GetFlag(i)` | `flags[i]` |
| 12 | 00538c50 | `SetFlag(i, v)` | `flags[i] = v` |

None of these slots has a direct caller in the image; they are reached through the vftable. The editor screen
itself uses slot 0 only (around building placement and removal) and calls the subsystems directly for everything
else [known] S 00604dd0. The terrain generator (§3.11) writes through slots 0 and 2 [inferred from its
call pattern].

### 2.2 `nMenu::Debug` (0x6608 bytes, vftables S 007f0614 / 007f069c / 007f06ac / 007f0740)

Derived from `nMenu::Overlapped` (a movable dialog, style name `uiBigDialog`). Only the editor's own state is
listed [known] S 00607d20 unless tagged.

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0xc00 | ptr | `showParent` (member of the base `nMenu::Overlapped`, stored by `Overlapped::OnShow`, cleared by `OnHide`) | the parent desktop the dialog was shown on: the `nUi::Desktop` face of the game screen `nMenu::Game`; `Game = showParent - 0x20`. `Game + 0xffe8` → `nGame::System` with the cursor cell at +0x24 (x), +0x28 (y) and the cursor fine position at +0x2c; `Game + 0xfff4` → the local player [inferred from use] |
| +0xc08 | `nUi::Edit` | `filenameEdit` | map name for save and load; initial text = `MapInfo + 0x24` (map name) |
| +0xf38 | `nUi::Button` | `saveMapButton` | label `!Save Map`; enabled only while the name is not empty |
| +0x13a0 | `nUi::Button` | `loadMapButton` | label `!Load Map` |
| +0x1808 | `nUi::Button` | third button | label `!Overview Map`; `Update` never reads its click latch [known] S 00609130: no function |
| +0x1c70 | `nUi::ComboBox` (0x930) | mode list | item ids = tool modes (§2.3); selected id at +0x1c98 |
| +0x25a0 | `nUi::Listbox` (0x4020) | element list | entries carry a text and one i32 of data. Listbox +0x3ffc (= Debug +0x659c): selected index, -1 none. Listbox +0x4004 (= Debug +0x65a4): the list's "row clicked this frame" byte: the list's per-frame update S 007663f0 clears it and sets it to 1 when one of the visible rows was clicked (it then selects that row); also zeroed by the list's constructor, `Init` and `Clear`. While it is non-zero the tools do not react (§3.1) [known] |
| +0x65c0 | i32 | `toolMode` | current mode, copied from the combo on change |
| +0x65c4 | u8 | `panelShown` | 1 after `OnShow`; Enter toggles it (§3.1) |
| +0x65c8 | vector&lt;`EditorSetting`&gt; | scatter presets | filled by `scatter.lua` (§3.8) |
| +0x65d8 | i32 | `anchorX` | copy-region centre, fine x; -1 = none |
| +0x65dc | i32 | `anchorY` | fine y; -1 = none |
| +0x65e0 | vector&lt;`CopyPasteCell`&gt; | copy buffer | §3.7 |
| +0x65f0 | vector&lt;`EditorListItem`&gt; | paste presets | filled by `copypaste.lua` (§3.8) |
| +0x6600 | `DebugShipRouteTool` | route builder | one pointer: the `NavyShipRoute` being drawn, null = idle |

Global `g_pMapEditor` S 0088b8fc = the one `Debug` object (set by the constructor, cleared by the destructor
S 00607ff0); the Lua `editor` functions do nothing while it is null [known].

### 2.3 Tool modes (`toolMode`, the combo item ids) [known] S 0060a340

Order in the combo box: 1, 2, 3, 4, 10, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19. Mode after `OnShow`: 6.

| Id | Label | Element list (`RefillElementList` S 00608160) |
|---|---|---|
| 1 | Start Positions | empty |
| 2 | Trees | every deposit property whose resource good is `wood` (0xCD6EC133); data = deposit id |
| 3 | Stones | every deposit property whose resource good is `stone` (0x55E952D3) |
| 4 | Patterns | every pattern property; data = pattern id |
| 5 | Elevations | empty |
| 6 | Buildings | the building types of the local player's tribe (`TribeProperty.buildings` +0x40; [inferred] `Player + 0x48` is the tribe property) |
| 7 | Resources | seven goods, in this order: `gold` 0x4F41C633, `stone` 0x55E952D3, `ironOre` 0xEC5020BE, `coal` 0x7068DCD3, `water` 0xA9676263, `fish` 0x4012E5A3, `salt` 0x09D2D623 |
| 8 | Doodads | every doodad property |
| 9 | Players | one entry per active player slot 0..7: name followed by the slot number; the local player's row is selected. The mode has no tool (§3.4) |
| 10 | Animals | every animal property |
| 11 | Tools | 0 `Forest`, 1 `Stones`, 2 `Infomap`, 3 `Fill with gras`, 4 `Create Seaground`, 5 `Create Mountain`, 6 `Create Fish`, 7 `Validate Map` |
| 12 | Scatter | runs `[data]\scripts\editor\scatter.lua`, then one entry per scatter preset; data = index |
| 13 | Ambients | every sound property of type 0 (Ambient; `SoundProperty + 0x34`, [audio.md](audio.md) §2) |
| 14 | Harbors | every harbour property |
| 15 | ShipRoutes | empty; entering the mode finishes a route under construction (§3.6) |
| 16 | CopyPaste | runs `[data]\scripts\editor\copypaste.lua`, then one entry per paste preset; data = index |
| 17 | Spawnpoints | every spawn-point property |
| 18 | Ships | empty (no case) |
| 19 | Chests | goods of the local player's tribe (vector at tribe property +0x20) whose `GoodProperty.type == 0` |

The resource good of a deposit and the good type are fields of the property records
([properties-data.md](properties-data.md)). Good names for the ids: `Goods.lua`, `Jobs.lua` [known: data].

### 2.4 Editor records

**`ai::editor::EditorSetting`** (scatter preset, 0x44 bytes) [known] struct, S 00605c60, S 00602f20:

| Offset | Type | Field |
|---|---|---|
| +0x04 / +0x08 / +0x0c | vector | elements: 8-byte entries `{ i32 propertyId, f32 weight }` |
| +0x14 / +0x18 / +0x1c | vector | patterns: 8-byte entries `{ i32 patternId, f32 weight }` |
| +0x20 | std::string (0x1c) | name (compared case-insensitively) |
| +0x3c | i32 | `size`: scatter distance in vertex units, default 7 |
| +0x40 | i32 | constructor argument, always 1 (S 00609ce0); only copied with the record, read by none of the functions that use the preset [known for the decompiled image] |

**`ai::editor::EditorListItem`** (paste preset, 0x28 bytes) [known] S 00608f50, S 006098d0..00609b50, S 00601300:

| Offset | Type | Field | Default |
|---|---|---|---|
| +0x00 | std::string (0x1c) | name (case-insensitive) | |
| +0x1c | u8 | `usePattern` | 0 |
| +0x1d | u8 | `useDeposit` | 0 |
| +0x1e | u8 | `useAnimal` | 0 |
| +0x1f | u8 | `useBuilding` | 0 |
| +0x20 | u8 | `useDoodad` | 0 |
| +0x21 | u8 | `useAmbient` | 0 |
| +0x22 | u8 | `invertX` | 0 |
| +0x23 | u8 | `invertY` | 0 |
| +0x24 | i32 | `heightMode`: 0 leave heights, 2 add, 3 subtract, any other value set | 0 |

**`ai::editor::CopyPasteCell`** (0x24 bytes, nine i32) [known] S 006011b0, S 00600f70:

| Index | Field | Value when captured |
|---|---|---|
| 0 | `dx` | vertex x minus anchor x |
| 1 | `dy` | vertex y minus anchor y |
| 2 | `height` | elevation of the vertex |
| 3 | `pattern` | pattern id of the cell that contains the vertex [inferred: the argument is register-aliased in the decompile] |
| 4 | `deposit` | deposit property id on that cell, or -1 |
| 5 | `animal` | property id of the first animal on that cell, or -1 |
| 6 | `building` | building type id of `FindBuildingAtOrNearest(cell, 0)`, or -1 |
| 7 | `doodad` | property id of the doodad at exactly this vertex, or -1 |
| 8 | `ambient` | ambient type on that cell, or -1 |

### 2.5 Developer variables

**`CVar`** [known] S 005c6270, S 005c6370, S 005c64a0: `{ std::string group, std::string name, RemoteCVarEntry*
pRemoteVar }`. A CVar does not own its value: it is bound to a variable of the program by pointer. Three kinds:
bool (bound to a byte), int and float (each with minimum, maximum and step given at construction). The two
strings are filled only on the toggle-window path; on the server path they stay empty and group and name live in
the server's map and in the `RemoteCVarEntry`. The step reaches only the toggle window.

**`ai::debug::RemoteCVarEntry`** (0x34 bytes) [known] S 005c5fd0, S 005c6090, S 005c6180:

| Offset | Type | Field |
|---|---|---|
| +0x00 | std::string | name |
| +0x1c | char | type: `'b'` bool, `'f'` float, `'i'` int (the formatter also knows `d`, `u`, `l`, `g`; no constructor makes them) |
| +0x20 | u32 | value size: 1 for bool, 4 for int and float |
| +0x24 | ptr | the live variable |
| +0x28 | ptr | shadow copy (last value sent): 1 byte for bool; for int and float one allocation of 12 bytes: shadow, min, max, each copied in the variable's own type |
| +0x2c / +0x30 | ptr | min / max, null for bool |

**`ai::debug::CVarRemoteServer`** (0x760 bytes) [known] struct, S 0067e690, S 0067df40: +0x00 listen socket;
+0x04 listen address; +0x14 thread handle; +0x18 thread id; +0x1c eight client slots of 0x20 bytes
(`{ +0x00 socket (-1 free), +0x04 peer address, +0x14 send list, +0x18 list head, +0x1c list size }`); +0x11c and
+0x220 the read and write `fd_set`; +0x324 message buffer, 1024 bytes; +0x724 message length; +0x728 critical
section; +0x740 stop flag; +0x744 map group name → vector of entries (head +0x748, size +0x74c); +0x754 / +0x758
first / last of the vector of custom-message listeners.

Globals [known: data bytes]:

| Address | Type | Value | Meaning |
|---|---|---|---|
| S 0088ca50 | u8 | 0, never written | gate: the server is created only when non-zero (S 0067c6d0) |
| S 008810bc | u16 | 1234 | listen port |
| S 008810c0 | u32 | 200 | sleep per loop of the server thread, milliseconds |
| S 008810c4 | std::string | `DefaultApp` | application name sent in `APP$`: assigned by the static initialiser S 007caa10; the only other references are the server thread's read and the exit-time destructor [known: xrefs] |
| S 0088ca54 | i32 | 0 | when > 0: maximum messages flushed to one client per loop |
| S 0088ca58 | ptr | | server singleton holder |
| S 0088b81c | ptr | never assigned in the decompiled image | the native `DebugToggleWindow`; when set, CVars register there instead of with the server [inferred: only a shutdown reference and the readers exist] |

### 2.6 `ai::terrain::TerrainGenerator` (object at `S2CG::CMapRenderer + 0x58`) [known] S 006b0e60

| Offset | Type | Field | Default |
|---|---|---|---|
| +0x00 | i32 | constructor argument, not read by the generator | |
| +0x04 | ptr | height source: slots 0 / 1 give vertex-grid width / height, slot 3 the height of a vertex | |
| +0x08 | ptr | height sink: slot 0 `(1)` before and `(0)` after a run, slot 2 `(vertex, height)` per vertex; the slot numbers and arguments match `NLogic::Edit` (§2.1) [inferred] | |
| +0x0c | RNG | own generator, seed 0x5432ACE0 | |
| +0x14 | i32 | mode: 0 Perlin, 1 fault lines, 2 FBM, 3 multifractal | 0 |
| +0x18 | 8 × 4 bytes | parameters | 0, 0, 8, then five times 1.0f |
| +0x38 / +0x3c | f32 | noise scale in x / y | 1.0 / 1.0 |
| +0x40 | i32 | fault amplitude; stored as the integer 1000 [known], read by the fault-line pass as a number [inferred: the decompile does not show whether the load converts from integer; the instruction at the multiply in S 006b1dd0 settles it] | 1000 |
| +0x44 | u8/i32 | write into a float buffer instead of the map | 0 |
| +0x48 / +0x4c | | buffer count / buffer | 0 / null |
| +0x50 / +0x54 | f32 | minimum / maximum of the buffer run | |

---

## 3. Rules and algorithms

### 3.1 The editor screen

**Construction** S 00607d20 [known]: `Overlapped` base with the texture style `uiBigDialog`; `Edit`, three
`Button`s of kind 10, `ComboBox`, `Listbox`; `toolMode = 0`; the three vectors empty; anchor = (-1, -1); route
builder idle; `g_pMapEditor = this`.

**Show** (`OnShow` S 0060a340, a virtual of the face at +0x20) [known], in this order:

1. register the Lua library `editor` with 13 functions (§3.8);
2. load `copypaste.dat` into the copy buffer (§3.7);
3. `S2CG::Scene::SetFlag710(0)` on the global scene `g_pScene` S 0088ca60 (primary vftable S 007f8f2c slot 23,
   S 00680110: stores the byte `Scene + 0x710`) [known for the slot and the store; the argument 0 is inferred,
   `OnHide` passes 1]. The byte is 1 from the scene constructor; no reader of it is in the decompiled image
   [TODO] not established: what the byte gates;
4. switch the fog-of-war overlay of the landscape off for the whole map:
   `CLandscape::SetFogOfWarOverlay(0, null, 1)` ([rendering.md](rendering.md) §3.7);
5. slot +0x24 with argument 0 on the game screen's HUD root (`nMenu::Game + 0x968`, `MenuGameRootObject`;
   `OnHide` passes 1) [known: instructions at S 0060a57d, S 005eaa80]: the slot is `SetVisible` in `nUi::Object`,
   so the HUD is hidden while the editor is shown [inferred: the root's own vftable was not read]; and a write
   of **180.0** to the float at
   (`nGame::System + 0x2d0`) + 0x2c, the camera's distance scale
   ([camera-input-cutscenes.md](camera-input-cutscenes.md) §3.13; `OnHide` restores 70.0 [known] S 00602000).
   The camera stands 2.5 times further out while the editor is shown (`+0x2c` read 70.0 in a match and 180.0 with
   the editor open [live, 2026-10-12]); at a zoom step above the game's own maximum 4 (an install whose `zoomMax`
   is 6.0, [camera-input-cutscenes.md](camera-input-cutscenes.md) §2.1) the whole world view lies in the distance
   haze and shows one light blue colour; writing 70.0 back with the editor open brings the world back
   [live, 2026-10-12, screenshots];
6. base `Overlapped::OnShow`; title `Debug`;
7. lay out the widgets top-down from pixel (50, 30) with a row height of 28 pixels: name edit, `!Save Map`,
   `!Load Map`, `!Overview Map`, mode combo with the 19 items of §2.3, element list (11 rows);
8. `panelShown = 1`; select combo item 6 (Buildings); `toolMode = 6`; `RefillElementList`.

**Hide** (`OnHide` S 00602000) [known]: undo steps 3 to 5 (fog overlay back on for the local player:
`SetFogOfWarOverlay(1, localPlayer, 0)`; distance scale 70.0), destroy the six widgets, base `OnHide`, then
**recompute derived map data**: `MapModifier::RefreshWaterAndCliffsAll` and the continent rebuild request (§3.3).

**Per frame** (`Update` S 00609130, a virtual of the face at +0x24) [known]:

1. base `Overlapped::Update`; if the dialog's close was requested: `System::CloseDialog(this)`, return.
2. Enable the save button iff the name edit is not empty.
3. Save button clicked → §3.9 save, close the dialog, return.
4. Load button clicked → §3.9 load, close the dialog, return.
5. Mode combo changed → `toolMode` = selected id, `RefillElementList`, return.
6. If a list row was clicked this frame (Listbox +0x4004, §2.2): nothing further (in mode 9 the selected player
   entry is looked up and discarded). Otherwise:
   1. only while `nMenu::System + 0x0a` is 0 (no focused dialog was updated this frame,
      [ingame-ui.md](ingame-ui.md) §2.7):
      - **left mouse button held** (`GameAction` slot +0x34 `IsLeftButtonDown(1)`, a level query) →
        `HandleToolClick(0)`;
      - left button not held, an anchor is set and the copy buffer is empty → capture the copy region (§3.7);
      - **right mouse button held** (slot +0x3c `IsRightButtonDown(1)`) → `HandleToolClick(1)`;
   2. Enter pressed (edge, virtual key 0x0d): toggle `panelShown`. Hiding moves the dialog to the relative
      position (-3.0, 0) and calls `nUi::Object::Hide` (slot +0x28) on the object at +0xc00 (the game screen's
      face, §2.2) and on the dialog's own face at +0x20; showing moves it back to (0, 0) and calls
      `SetVisible(1)` (slot +0x24) on both [known for the own face, vftable S 007f06ac slots 9 / 10 = S 004a1090 /
      S 004a1130; inferred for the game screen's face, whose vftable was not read]. This step does not depend on the `nMenu::System + 0x0a` test.
      Hiding blanks the whole screen, so the game screen's face carries the world view as well, not only the HUD
      [live, 2026-10-12]; whether a second Enter restores it is [TODO].

Because steps 6.1 test levels, a tool is applied **once per rendered frame while the button stays down**
[known: `GameAction` vftable S 007dec84 slots 13 / 15 = S 004910a0 / S 004910d0 forward virtual key 1 / 2 with
source 1 to `IsKeyDown` S 00490ff0, which then
returns "asynchronous hold counter > 0"]. Tools that toggle or add guard
themselves with "nothing there yet" checks; the elevation and resource tools accumulate per frame.

`HandleToolClick(button)` S 00604dd0 also has branches for `button` 2 (pick the element under the cursor into the
list: deposit id in modes 2 and 3, pattern id in mode 4, doodad id in mode 8 with `Beep(5000, 100)` when there is
none) and 3 (mode 5: smoothing brush, §3.5). `Update` is the function's only caller and passes only 0 and 1, so
both branches are unreachable in this build [known: caller list].

The cursor cell `C` and the cursor fine position `F` used below come from the game screen (§2.2). The **sample
vertex** of a cell is `(4·x + 2·(y & 1), 4·y)` on the elevation vertex grid ([../map-format.md](../map-format.md)
§5.2); the cell of a vertex `(fx, fy)` is `y = fy / 4`, `x = (fx - 2·(y & 1)) / 4` with C integer division
[known] S 0052d0d0, S 00675160.

### 3.2 Batch editing

`Edit::SetBatchEditing(1)` … `SetBatchEditing(0)` brackets an edit that should not run game logic. While the
flag is set [known]:

- `NLogic::System::Update` does not execute logic ticks (the tick time still advances) and does not call the
  script's `onLogicTick` ([logic-core.md](logic-core.md) §3.1) S 00527070;
- a placed building is complete at once and gets its workers without construction
  ([village-buildings.md](village-buildings.md) §3.2); removing a building uses `spill = false`,
  `destroyed = true` (same document §3.5) S 00559db0; workers and soldiers of a removed building are deleted
  instead of released S 0055b620, S 005665f0; an upgrade or construction started through
  `Construction::StartWithType` S 0055efa0 completes at once instead of requesting materials;
- a street attached to its two flags gets its carrier spawned at once (`NNet::System::AttachStreetToFlags`
  S 006662f0); a destroyed street deletes its carrier instead of releasing it (`Street` destructor S 00669210);
  a flag placed on an existing street starts the two halves with an empty carrier reference instead of the
  old street's carrier (`NNet::System::PlaceFlag` S 00666900) [inferred for the last];
- `NNavy::Construction::SetBuildPosition` S 005ba640 would zero both remaining-work values of a ship, but no
  shipped caller reaches it under the flag: a ship-building site placed with the flag set is completed at
  placement, no constructor comes and no ship is ever made ([navy.md](navy.md) §3.2) [known];
- `NResources::System::Update` S 00540340 skips its animal pass and `S2CG::Scene::Update` S 006805e0 passes no
  local player to its visibility step [inferred: one layer read; neither runs a tick while the flag is set].

Clearing the flag flushes the map modifier's dirty rectangles (§3.3). The only call of slot 0 found is the
editor's Buildings tool (§3.4) [known for the cached image]; whether map set-up sets the flag is open
([players-victory.md](players-victory.md) §3.4).

### 3.3 Terrain writes and what they recompute

All terrain edits go through `ai::map::MapModifier` ([map-resources.md](map-resources.md) §2.4, §3.3, §3.4):

- `SetVertexElevation(vertex, h, deferred)` S 006736a0 [known]: no-op when the height is unchanged. Otherwise
  store; if the vertex crossed the water threshold (`Elevations + 0x0c`, `minHeight`) recompute the water bit 0x4
  and the shore bit 0x8 in the cell square ±2 around the vertex's cell; then either (not deferred) notify the
  elevation listeners for this vertex and invalidate the construction map around the cell, or (deferred) extend
  the elevation dirty rectangle by the vertex. Returns true when the height was already equal.
- `SetCellPattern(cell, id, deferNotify)` S 00674360 [known]: no-op when unchanged. Otherwise, comparing old and
  new pattern property: `blocked` differs → set or clear bit 0x1; `forMining`, `forBuilding`, `forShip` differ
  → re-derive bits 0x10, 0x200, 0x20000; then either (not deferred) notify the cell listeners and invalidate
  the construction map around the cell, or (deferred) extend the cell dirty rectangle by the cell. A change of bit 0x4, 0x10, 0x200 or
  0x20000 resets the cell's ground resource to `{0, -1}` ([map-resources.md](map-resources.md) §3.3).
- `MapModifier_FlushDirtyRects` S 006730e0: publishes both dirty rectangles (elevation rectangle inflated by 16
  vertices: listeners, cliff bits, construction flags; cell rectangle: listeners, construction flags) and
  empties them ([map-resources.md](map-resources.md) §3.4).
- `RefreshWaterAndCliffsAll` S 00672f30 [known]: water bit and shore bit for the whole map, all cliff markers
  rebuilt, full construction-map recompute requested.
- Continent rebuild request S 00532120 [known]: with no map-update batch open
  (`MapUpdateBatch.counter > 0`) `MapModifier::RebuildContinents` runs at once; otherwise the batch's
  `rebuildContinents` byte is set and the rebuild happens when the batch closes.
- `MapModifier_RefreshPatternBitsAll` S 00673050 [known]: for every cell re-derive bits 0x200, 0x10, 0x1,
  0x20000 from its pattern.

Grid bits of placed objects (deposit 0x80, harbour 0x2000, exit 0x4000, dock 0x800, route 0x8000, …) are set by
the constructors and cleared by the destructors of those objects ([../map-format.md](../map-format.md) §6.5,
[map-resources.md](map-resources.md) §3.9).

**What the editor recomputes, and when** [known]:

| Derived data | Recomputed |
|---|---|
| water 0x4, shore 0x8 | around every vertex whose height crosses the threshold; whole map on save and on hide |
| cliff 0x40, construction flags | at every dirty-rectangle flush; cliff markers of the whole map on save and on hide |
| pattern bits 0x1, 0x10, 0x200, 0x20000 | for a cell when its pattern changes; whole map by tool "Validate Map" |
| continents | on save and on hide only |
| navy bits | by creating and deleting harbours and routes |

### 3.4 The tools, by mode

Left = `HandleToolClick(0)`, right = `HandleToolClick(1)`; `sel` = data of the selected list entry; a tool that
needs `sel` does nothing while no entry is selected [known] S 00604dd0.

| Mode | Left button | Right button |
|---|---|---|
| 1 Start Positions | if `C` is not yet a start position: append it to `MapInfo` start positions (`MapInfo + 0x04`) | erase the first start position equal to `C`; **crashes on a cell that is not a start position** (below) |
| 2 Trees, 3 Stones | if `GameQuery::CanPlaceDepositAt(C, property(sel))` (§3.10): `NResources::System::CreateDeposit(&sel, C, true)` | if a deposit lies on `C`: `RemoveResourceAt(C)` |
| 4 Patterns | pattern brush with `sel` (§3.5) | pattern brush with `pattern_meadow` 0xBFE4E8E3 |
| 5 Elevations | elevation brush, direction +1 (§3.5) | elevation brush, direction -1 |
| 6 Buildings | building rule below | if a building is found at `C`: `SetBatchEditing(1)`, `RemoveBuilding(unique, spill = false)`, `SetBatchEditing(0)` |
| 7 Resources | `MapModifier::AddResourceAtCell(C, &sel, 2)`: only if the cell can hold that type; an empty cell takes the type; same type: amount (1000 = unlimited counts as 7) + 2, capped at 7; another type: nothing | `ConsumeResourceAtCell(C, &sel)`: same type and not unlimited: amount - 1; at 0 the cell becomes empty (type -1) |
| 8 Doodads | if (the property is not `blocking`, or `FindDoodadAtCell(C, property.type)` S 00543dc0 finds nothing) and no doodad lies at exactly `F`: `AddDoodadAtFinePos(&sel, F)`. That lookup tests only the sample vertex of `C`: with a non-zero `type` it scans the temporary doodads for one of exactly that type, with type 0 it also consults the static and the blocking index ([map-resources.md](map-resources.md) §3.11) | remove the doodad at exactly `F` |
| 9 Players | none | none |
| 10 Animals | if `Map_IsCellWalkable(C)` and no animal is on `C`: `SpawnAnimal(&sel, C)` | remove the first animal on `C` |
| 11 Tools | by `sel`, §3.5 and §3.11 | none |
| 12 Scatter | `ScatterAtCursor(preset[sel])` (§3.5) when `sel` is a valid index | none |
| 13 Ambients | if no ambient is on `C`: `NLogic::Ambients::Add(sel, C)` | remove the ambient on `C` |
| 14 Harbors | if `GameQuery::CanPlaceHarborAt(sel, C)` (§3.10): `HarborList::Create(C, sel)` (creates the exits, [navy.md](navy.md) §3.1) | if a harbour is at `C`: erase it |
| 15 ShipRoutes | route tool (§3.6) | route tool (§3.6) |
| 16 CopyPaste | buffer empty and no anchor: anchor = sample vertex of `C`; buffer not empty and `sel` a valid preset index: paste (§3.7) | clear the copy buffer |
| 17 Spawnpoints | if no spawn is on `C` and `Map_IsCellWalkable(C)`: `LogicSpawnSystem::AddSpawn(sel, C)` | remove the spawn on `C` |
| 18 Ships | if no ship is at `C`: `NNavy::System::CreateShip(localPlayer, C)`; no water check | erase the ship at `C` |
| 19 Chests | if no chest is on `C` and `Map_IsCellWalkable(C)`: `AddChest(1, C)` (clears the cell first), then `SetContentGood(sel, 10)` | none |

`Map_IsCellWalkable` S 0052df20: none of the grid bits 0x1, 0x4, 0x40, 0x100, 0x400
([../map-format.md](../map-format.md) §5.4).

**Start Positions, right button, on a cell that is not a start position** [known; live 2026-10-12: crash log
`EXCEPTION_ACCESS_VIOLATION` at S 00674f20]: the erase goes through `Stl_VectorMapPos_EraseValue` S 00674ed0,
which searches the vector for the position and then shifts the following entries down without testing "not
found": the shift loop starts at `end + 8` and runs until it leaves mapped memory, which ends the process. The
function's other caller is `NAI::Player::AllowHarborPosition` S 005824c0 (the first is
`NLogic::MapInfo::RemoveStartPosition` S 005294d0), so a map script's `logic.ai_allowHarborPosition` with a
position that was never forbidden ends the process the same way.

**Seen working** [live, 2026-10-12, dialog opened through the debugger, §10 Q1]: the Buildings tool with both
buttons and list entries 3 and 35, the Elevations tool with both buttons (17,549 tool calls), and mode 11 Tools
with entry 2 (`Infomap`), all without a fault (`HandleToolClick` S 00604dd0 hooked). The unreachable button 3
branch (mode 5 smoothing brush, §3.5) works when a debugger hook after `Update` S 00609130 calls it for the
middle mouse button (3,202 calls without a fault).

**Buildings, left button** [known]: only if no building is found at `C` (`FindBuildingAtOrNearest(C, 0)`).
Let `ok = (Village_CheckBuildingPlacement(localPlayer, &sel, C) == 0)` S 005576e0 (0 = the type is not locked for
the player and the cell's construction flags fit the type). The placement is **refused with `Beep(1000, 100)`**
when `ok` is false and at least one of these holds:

- the building property is not a territory building (`BuildingProperty.territoryBuilding`), or
- a territory-giving building lies within hex radius 4 of `C`
  (`GameQuery::HasNoTerritoryBuildingWithinRadius4` S 0052dc30 is false), or
- `C` is not walkable.

Otherwise (normal check passed, or a territory building on free walkable ground far enough from other territory
buildings): `SetBatchEditing(1)`, `NVillage::System::PlaceBuilding(localPlayer, &sel, C)`, `SetBatchEditing(0)`.
So the editor can found a new territory outside the player's land, and every placed building is complete at once
(§3.2).

### 3.5 Brushes and whole-map tools

A **hex disc of radius r around a start position** is walked as: the start; then for ring = 1..r one step in
direction 4 from the position visited last and `ring` steps in each of the directions 0..5
([map-resources.md](map-resources.md) §3.1). The same walk is used on the cell grid and on the vertex grid;
positions outside the grid are skipped but still walked [known] S 00601920, S 00601a40.

**Pattern brush** `PaintPatternBrush(id)` S 00601920 [known]: radius 0 (the cursor cell only); **Shift → 4**;
**Ctrl → 2** (Ctrl wins over Shift). For every cell of the disc around `C`:
`SetCellPattern(cell, id, deferNotify = 0)`. Modifier state is the asynchronous key state (left Shift 0xA0,
Control 0x11).

**Elevation brush** `ApplyElevationBrush(direction)` S 00601a40 [known]:

```
amount = direction * 150;  radius = 5
if Shift:  radius = 7;   amount = direction * 750
if Ctrl:   radius = 12;  amount = amount * 10        # after the Shift rule: 1500 or 7500 in size
h0 = height(sample vertex of C)                       # read once, before any write
for ring, v in hex disc of `radius` on the vertex grid around the sample vertex of C:
    h = height(v)
    if (amount >= 1 and h <= h0) or (amount < 1 and h >= h0):
        SetVertexElevation(v, h + (radius - ring) * (amount / radius), deferred = 1)   # C integer division
FlushDirtyRects()
```

Steps per ring: 30 (plain), 107 (Shift), 125 (Ctrl), 625 (Shift + Ctrl); the outermost ring adds 0. Vertices
already above the centre are not raised and vertices already below it are not lowered, so repeated application
grows a cone or a pit. The walk starts on the sample vertex of `C` [known: instructions at S 00601b00..00601b18].

**Smoothing brush** `SmoothElevationBrush()` S 00601c00 [known from the instructions; unreachable, §3.1]:

| Modifier | Radius | Strength `s` | Passes |
|---|---|---|---|
| none | 5 | 0.3 | 1 |
| Shift | 9 | 0.7 | 1 |
| Ctrl | 15 | 1.0 | 1 |
| Shift + Ctrl | 15 | 1.0 | 3 |

Per pass, for every vertex `v` of the disc around the sample vertex of `C`, in walk order and **in place** (later
vertices see earlier results): `avg` = mean height of the in-grid vertices among the six ring-1 neighbours of
`v`; `SetVertexElevation(v, trunc(h + (avg - h) * s), deferred = 1)`. After all passes `FlushDirtyRects()`.

**Scatter** `ScatterAtCursor(preset)` S 00602f20 [known from the instructions]. Inside one map-update batch, for
every element entry `{id, weight}` of the preset, in order:

1. `r = (rand() & 0x7fff) / 32767.0`; the entry is **skipped when `weight > r`** (so an entry is used with
   probability 1 - weight; all shipped weights are 0.2, §6).
2. `a = (rand() % 6) * (2π / 6)`; target vertex = sample vertex of `C` + (`trunc(sin(a) * size)`,
   `trunc(cos(a) * size)`), `size` = the preset's size (default 7 vertex units).
3. `MapEditor_PlaceObjectByPropertyId(target, id)` S 00602ac0: the vertex must be in the grid and `id != 0`. The
   id is looked up in the property tables in this order, the first table that knows it decides:
   - building type → if no building is found at the vertex's cell: `PlaceBuilding(player 0, &id, cell)` (no
     placement check, no batch-editing bracket);
   - deposit → if the cell has no deposit and `CanPlaceDepositAt`: `CreateDeposit(&id, cell, true)`;
   - doodad → if no doodad lies at exactly the vertex: `AddDoodadAtFinePos(&id, vertex)`;
   - animal → if no animal is on the cell and the cell is walkable: `SpawnAnimal(&id, cell)`;
   - sound → if no ambient is on the cell: `Ambients::Add(id, cell)`.
4. If something was placed and the preset has pattern entries: draw `t = ((rand() & 0x7fff) / 32767.0) * W`
   with `W` = sum of the pattern weights, pick the first entry `i` with `acc_i <= t <= acc_i + weight_i`
   (`acc_i` = sum of the weights before `i`) and `SetCellPattern(cell of the target vertex, pattern_i,
   deferNotify = 1)`.

After the loop the batch is closed and, if anything changed, `FlushDirtyRects()`.

**Tools list (mode 11)** [known] S 00604dd0:

| `sel` | Label | Action |
|---|---|---|
| 0 | Forest | in one map-update batch, 5 times: cell = `C` + (`rand() % 3 - 1`, `rand() % 3 - 1`); `PlaceRandomDepositSetA(cell)`; then `FlushDirtyRects()` (S 00602890) |
| 1 | Stones | the same with `PlaceRandomDepositSetB` (S 006029a0) |
| 2 | Infomap | image-driven generation, §3.11 |
| 3 | Fill with gras | `SetCellPattern(cell, pattern_meadow 0xBFE4E8E3, deferred)` for every cell; close a map-update batch; `FlushDirtyRects()` (S 00601120) |
| 4 | Create Seaground | for every water cell (bit 0x4): pattern `pattern_seaground` 0xBABEB00B on the cell and on the eight positions reached by one step in directions 0..7 (the six neighbours plus (0, +2) and (0, -2)), deferred; close a map-update batch; `FlushDirtyRects()` (S 006021d0) |
| 5 | Create Mountain | nothing (no case) |
| 6 | Create Fish | for every water cell: consume its ground resource until empty, then `AddResourceAtCell(cell, fish 0x4012E5A3, rand() % 7 + 1)` (S 006020e0) |
| 7 | Validate Map | `MapModifier_RefreshPatternBitsAll` (§3.3); it checks nothing and reports nothing (S 006010d0) |

Tools 3 and 4 call `MapUpdateBatch_End` without a matching `Begin` [known], which raises the batch counter by
one for the rest of the session [inferred].

`MapEditor_PlaceRandomDepositSetA(cell)` S 00601750 [known], cell inside the map:

1. placement test `CanPlaceDepositAt(cell, property(tree_02 0x063287B3))`; stop if false;
2. deposit id = entry `rand() % 6` of { `tree_02` 0x063287B3, `tree_03` 0x489CCB83, `tree_04` 0x119F47B3,
   `tree_05` 0xE6CF21D3, `tree_06` 0xADEF44C3, `tree_07` 0x732D0E73 } (a seventh table entry, `tree_08`
   0xE6CF0E73, is never drawn); `CreateDeposit(&id, cell, true)`;
3. `SetCellPattern(cell, rand() % 2 ? pattern_meadow5 0x4545FAC5 : pattern_meadow4 0x4545FAC4, deferred)`;
4. vertex = sample vertex of the cell, moved `rand() % 2` steps (drawn first) in direction `rand() % 6`; if it
   is in the grid and carries no doodad: add doodad entry `rand() % 3` of { `doodad_grass_0` 0x3AD137AE,
   `doodad_plants_5` 0xA12431CE, `doodad_plants_6` 0x89F5AE33 }.

`MapEditor_PlaceRandomDepositSetB(cell)` S 006025d0 [known]: the same shape with the test on `stone_01`
0x9F1BD60E; deposit = entry `rand() % 6` of { `stone_01` 0x9F1BD60E, `stone_02` 0x5BB1115E, `stone_03`
0x21EF5BEE, `stone_04` 0x1946CD8E, `stone_05` 0x5D936A9E, `stone_06` 0xE42BA2FE }; pattern `pattern_meadow2`
0x4545FAC2; doodad = entry `rand() % 4` of { `doodad_stones_0` 0x455C1F4E, `doodad_stones_1` 0xEA36023E,
`doodad_stones_2` 0x9F41D88E, `doodad_stones_3` 0xA7CBBE6E }.

All random numbers of the editor come from the C runtime `rand()`, not from the simulation's generator [known].

### 3.6 The ship-route tool (mode 15)

State: one route pointer (`DebugShipRouteTool`, 0 = idle) [known] S 0078d7c0, S 0078d960, S 0078d800, S 0078d880.

- **Left, idle** (`Begin`): if `C` is a harbour exit without a route (`GameQuery::IsFreeHarborExitAt`
  S 0052dbb0): `ShipRouteList::Create(C)` (a new route whose path is `[C]`) becomes the route under construction.
- **Left, drawing** (`AddPoint(C)`): if `C` is already on the path, cut the path back so that it ends at `C`.
  Otherwise run the navy's route path-finder (`NNavy::ShipRouteAStar`, `NNavy::System + 0x14`) from `C` to the
  path's last cell; if a path is found, drop the last cell and append the found cells from the old end to `C`.
  The path is stored with `NavyShipRoute::SetPath`. The path-finder only steps over free water of one continent
  and never over a cell that already carries the route bit 0x8000 ([navy.md](navy.md) §3.4,
  [../map-format.md](../map-format.md) §6.4 R4, R5). Then, if the route is **valid**, finish it.
- **Valid** (`GameQuery::CheckHarborExitPair(first, last)` S 0052d920): first and last path cell are exits of two
  **different** harbours, neither exit has a route yet, and the hex distance between the two cells is > 2.
- **Finish**: valid → attach the route to both harbours (`NavyLink_LinkHarborRoute`), tool idle; not valid →
  erase the route from the route list, tool idle.
- **Right, drawing**: finish (which discards an incomplete route).
- **Right, idle**: if `C` is an exit of a harbour and that exit has a route: erase that route.
- Selecting mode 15 in the combo while a route is under construction finishes it.

### 3.7 Copy and paste (mode 16) and `copypaste.dat`

**Capture** [known] S 00609130, S 006011b0. The left button sets the anchor (sample vertex of `C`) when the buffer
is empty. In the first frame in which the button is up, an anchor is set and the buffer is still empty:

1. `r = HexDistance(anchor, sample vertex of the cursor cell)`, both taken as positions of the vertex grid;
2. for every vertex `v` of the hex disc of radius `r` around the anchor that lies in the vertex grid, append a
   `CopyPasteCell` (§2.4) with `dx = v.x - anchorX`, `dy = v.y - anchorY`;
3. write the buffer to the file `copypaste.dat`;
4. anchor = (-1, -1).

The buffer holds **vertices**, about 16 per cell, each carrying the objects of the cell that contains it; the
paste guards below make the repetition harmless [inferred]. While an anchor is set the overlay draws the ring
of radius `r` (§3.12).

**Paste** `PasteCopyBuffer(preset)` S 00602780, `MapEditor_PasteCell` S 00601300 [known]. Inside one map-update
batch, for every buffer entry `e`: target vertex `t` = sample vertex of `C` + (`±e.dx`, `±e.dy`), negated per axis
when `invertX` / `invertY`; target cell = cell of `t`.

1. `t` in the vertex grid and `heightMode != 0`: `SetVertexElevation(t, H, deferred = 1)` with `H` = `e.height`,
   or current + `e.height` (mode 2), or current - `e.height` (mode 3).
2. Target cell in the map:
   - `usePattern` and `e.pattern != -1`: `SetCellPattern(cell, e.pattern, deferred)`;
   - `useDeposit`, `e.deposit != -1`, no deposit on the cell, `CanPlaceDepositAt`: `CreateDeposit`;
   - `useAnimal`, `e.animal != -1`, no animal on the cell, cell walkable: `SpawnAnimal`;
   - `useBuilding`, `e.building != -1`, no building found at the cell: `PlaceBuilding(player 0, &e.building,
     cell)` (no placement check);
   - `useAmbient`, `e.ambient != -1`, no ambient on the cell: `Ambients::Add`.
3. `t` in the vertex grid, `useDoodad`, `e.doodad != -1`, no doodad at exactly `t`: `AddDoodadAtFinePos`.

After the loop the batch is closed; if any entry changed something, `FlushDirtyRects()`.

**File `copypaste.dat`** [known] S 006015f0, S 00606050, S 00600f70, S 00601000. A plain (not encrypted)
`NCore::FileStream`, opened by the bare name, i.e. relative to the process's current directory
([formats-inventory.md](formats-inventory.md) §3.11):

```
u32  1                      # file version, ignored by the reader
u32  count
count × {
    u32  1                  # record version, ignored by the reader
    i32  dx, dy, height, pattern, deposit, animal, building, doodad, ambient
}
```

Integers in the stream's native order (little-endian, [save-format.md](save-format.md) §2.2). The reader loads
the file only if it exists; it is read once per `OnShow` and written at every capture. The right button clears
the buffer in memory only.

### 3.8 The Lua library `editor`

Registered by `OnShow` (§3.1) into the global script state; every function is a no-op while `g_pMapEditor` is
null; none returns a value [known] S 0060a080..0060a280, S 006098d0..00609b50. Names are resolved by
`PropertiesDb::FindIdByNameAnyTable` S 00546100: the first property with that **display name** in the order
building, deposit, good, pattern, remains, doodad, animal, sound, ai, harbour, tribe, sacrifice, spawn point; -1
when unknown.

| Function | Effect |
|---|---|
| `editor.scatter_addElement(preset, elementName, weight)` | find or create the scatter preset (name compared without case; a new preset has size 7); append `{id(elementName), weight}` to its elements unless that id is already listed |
| `editor.scatter_addPattern(preset, patternName, weight)` | the same for the pattern list |
| `editor.scatter_removeElement(preset, elementName)` | erase the first element entry with that id (the preset is created if missing) |
| `editor.scatter_setSize(preset, size)` | `EditorSetting.size = size` (integer) |
| `editor.paste_usePattern(preset, flag)` | find or create the paste preset (all options 0); `usePattern = (flag != 0)` |
| `editor.paste_useDeposit(preset, flag)` | `useDeposit` |
| `editor.paste_useAnimal(preset, flag)` | `useAnimal` |
| `editor.paste_useBuilding(preset, flag)` | `useBuilding` |
| `editor.paste_useDoodad(preset, flag)` | `useDoodad` |
| `editor.paste_useAmbient(preset, flag)` | `useAmbient` |
| `editor.paste_invertX(preset, flag)` | `invertX` |
| `editor.paste_invertY(preset, flag)` | `invertY` |
| `editor.paste_heightMode(preset, mode)` | `heightMode = mode` (integer, §2.4) |

`RefillElementList` clears the preset vector, runs the script file in a temporary script thread and lists the
presets, each time mode 12 (`scatter.lua`) or 16 (`copypaste.lua`) is selected [known] S 00608160.

### 3.9 Saving and loading a map from the editor

**Save** [known] S 00609130:

1. `MapModifier::RefreshWaterAndCliffsAll()`;
2. continent rebuild request (§3.3);
3. `GameFile_Save(mapType = 1, name)` S 005aa260 ([save-format.md](save-format.md) §3.1): the name is sanitised
   (`* / : < > ? \` → `_`), the file is `[data]\maps\campaignMaps\<name>.s2m` (type 1), an encrypted container;
   `MapInfo.mapName` = name and `MapInfo` width / height = the map's; then, because the type is a map type,
   **`GameFile_ResetWorldForMapExport()`** removes buildings, remains, orders, streets, flags, settlers, ships,
   animals on blocked cells and the per-player map grids from the **running world** and resets the tick timing
   (tick counter -1); then `GameFile_SaveMap` writes the map part;
4. close the dialog.

The map part, in write order ([save-format.md](save-format.md) §3.2, layouts in
[../map-format.md](../map-format.md) §3, §4): `Game File Map`, `MapInfo`, `LogicSystem`, `MapSystem` with its
seven grids (`ElevationMap`, `PatternMap`, `GridStatesMap`, `Map Resources`, `Map Territory`, `Map Exploration`,
`Map Continents`), `resources` (deposits, animals, animal areas), `DoodadsSystem`, `Logic Ambients`,
`Navy System` (ships, routes, harbours), `Logic SpawnSystem`. Nothing of the logic part (players, village, streets,
settlers, military, chests, scripts) is written; chests placed with mode 19 and buildings placed with mode 6 are
therefore **not part of the exported map** [inferred from the section list and the reset].

A failed write is not reported ([save-format.md](save-format.md) §3.1).

**The file must already exist** [known: S 007805d0, S 006e3fd0, S 006ef8a0; live 2026-10-12]. On close the
stream resolves its `[data]\...` path through the start-up file index, which knows only files that existed when
the game started: an unknown file name resolves to the empty string, `CreateFileA("")` fails, and nothing is
written. With an empty `data\game\maps\campaignMaps\<name>.s2m` created before start-up the save writes the
map into it (530,513 bytes in the test); saving under the name of a shipped map overwrites that map. After the
save the running world is black: buildings, streets, settlers, ships and the per-player exploration grids are
gone (step 3) [live, 2026-10-12]. A map exported this way starts as a new free game [live, 2026-10-12].

**Load** [known] S 00609130: `nGame_File_load(1, name, suspend = true)` S 005ab180
([save-format.md](save-format.md) §3.4) replaces the running world by the map `campaignMaps\<name>.s2m`; then
the dialog closes. Nothing is recomputed at load ([../map-format.md](../map-format.md) §5.5). The name edit starts
with the running world's map name; pressing `!Load Map` ended the game [live, 2026-10-12]. [inferred] the cause is
the same path resolution: a name with no file resolves to the empty path, which is passed to
`File_ReadAndDecrypt`.

### 3.10 Placement and validity rules used by the editor

| Object | Rule | Source |
|---|---|---|
| Deposit | `CanPlaceDepositAt(cell, property)` S 0052eb10: the terrain check and none of the bits 0x8 (shore), 0x80 (deposit), 0x2000 (harbour). Terrain check S 0052e150: object layer 0 of the cell is empty; none of 0x2, 0x4, 0x40, 0x100, 0x400; the cell's pattern is neither `blocked` (+0x3c) nor `forMining` (+0x3d) nor `forShip` (+0x3f); if the deposit property has tree types (`treeTypes` not empty) the pattern's `treeType` (+0x44) must not be -1; if the deposit's `needForPlantablePattern` (+0x70) is set the pattern must be `forPlanting` (+0x48) | [known]; [inferred] the vector tested is `treeTypes`; fields in [properties-data.md](properties-data.md) §2, [map-resources.md](map-resources.md) §3.9 |
| Harbour | `CanPlaceHarborAt(propertyId, cell)` S 0052eda0: in the map; the cell has none of 0x2000, 0x20, 0x4, 0x40, 0x400, 0x1, 0x80, 0x100; at least one of the four orientations passes `IsHarborOrientationValid` (exit and docks: [../map-format.md](../map-format.md) §6.4 E1..E4). The "no harbour on the six neighbours" loop reads the centre cell's word each time, so the neighbour test has no effect | [known] |
| Ship route | §3.6; [../map-format.md](../map-format.md) §6.4 R1..R10 | [known] |
| Building | §3.4 | [known] |
| Animal, spawn point, chest | cell walkable; at most one animal (first-animal test), one spawn, one chest per cell | [known] |
| Ambient | at most one per cell | [known] |
| Doodad | at most one per fine position; a `blocking` doodad property is additionally refused when the lookup of §3.4 mode 8 finds a doodad on the cell's sample vertex | [known] |
| Ground resource | one type per cell, amount 1..7 (1000 = unlimited); the cell must be able to hold the type (`MapModifier::CanHoldResourceAtCell`, [map-resources.md](map-resources.md) §3.8) | [known] |
| Start position | no duplicates through the tool; no upper count and no terrain test | [known] |
| Ship | none except "no ship on the cell" | [known] |

The editor has **no validation pass**: nothing checks start positions against player counts, reachability,
harbours without routes or stale grid bits. The consistency rules a map must satisfy are the cross-section rules
of [../map-format.md](../map-format.md) §7; a map is unusable for sea travel when the harbour, exit, dock and
route bits or the continents do not match the stored navy objects (same document §6.6, §6.7).

### 3.11 Generators

**"Infomap" tool** `Tool_GenerateFromImageMaps` S 006048f0 [known]: inside one map-update batch run the
`infoMap` pass and then the `landMap` pass. Both obtain a texture from the UI resource manager by its **resource
name** (`infoMap`, `landMap`), lock it and read 32-bit pixels at `pixels[y * width + x]`; the pixel (x, y) is the
vertex (x, y), so an image is expected to be (4W + 1) × (4H + 1) [inferred]. A name the manager does not hold yet is
loaded from `[data]\gfx\<name>.dds` (`UiResourceManager_LoadGfxTexture` S 00493500, `ai::ui::ResourcePath`
S 004bdc60), so the two images are `data\game\gfx\infoMap.dds` and `landMap.dds` [known]; the install holds
neither file [known: folder listing], and no UI layout file defines the names.

*Pass 1, `MapEditor_ApplyInfoMapImage`* S 006033d0. For every pixel whose vertex is in the grid:

```
h = ((pixel & 0xff) - 90) / 255.0 * 30000.0 + (rand() % 400 - 200)     # low byte = blue in A8R8G8B8
SetVertexElevation(vertex, trunc(h), deferred)
cell = cell of the vertex; if the cell is in the map:
    h < 20              : AddResourceAtCell(cell, fish, rand() % 6 + 1)
    20 <= h < 3000      : pattern = (rand() % 100 < 41) ? pattern_meadow1 0x4545FAC1 : pattern_meadow 0xBFE4E8E3
                          if rand() % 100 > 95 and no doodad at the vertex:
                              add doodad { stones_0, stones_1, stones_2 }[rand() % 3]
    3000 <= h < 5000    : AddResourceAtCell(cell, water 0xA9676263, 1); pattern_meadow
    5000 <= h < 9000    : AddResourceAtCell(cell, water, 1); pattern_meadow3 0x4545FAC3
    9000 <= h < 15000   : pattern { pattern_rock 0xD00FAFFE, pattern_rock1 0xDEADBEEF, pattern_rock2 0xCAFECAFE }[rand() % 3]
    h >= 15000          : pattern_snow 0x0FADE0FF
```

Then, for every pixel again: if its cell is water (bit 0x4), paint `pattern_seaground` on the cell and its eight
direction-0..7 positions (as tool 4); finally `FlushDirtyRects()` and release the texture. The bands are tested on the
untruncated float `h`; band edges, pattern ids and percentages are read from the decompiled comparisons and
literals [known]. [inferred] for the resource type of the `fish` and the two `water` calls: the decompile
assigns the id to a register and passes a stack address (§10 question 8).

*Pass 2, `Tool_ApplyLandMapImage`* S 00603d60 [known from the instructions]. Colours are compared as whole
32-bit values. Both loops walk rows, then columns, set the game cursor's cell (`nGame::Cursor::SetCell` on
`nGame::System + 0x10`) to the cell of every pixel, and skip pixels whose cell is outside the map or is water.
The cursor is therefore left on the cell of the last pixel.

- Loop A: pixel 0xFFFF0000 (red), 0xFFFFFF00 (yellow) or 0xFFFF00FF (magenta) → `SetCellPattern(cell,
  { pattern_rock, pattern_rock1, pattern_rock2 }[rand() % 3], deferred)`.
- Loop B:

| Pixel | Action on the pixel's cell |
|---|---|
| 0xFFFF0000 red | one `rand()` result drawn and discarded; pattern `pattern_rock3` 0xCAFECAFF (deferred); `AddResourceAtCell(coal 0x7068DCD3, rand() % 6 + 1)` |
| 0xFFFFFF00 yellow | the same with `gold` 0x4F41C633 |
| 0xFFFF00FF magenta | the same with `ironOre` 0xEC5020BE |
| 0xFF0000FF blue | `PlaceRandomDepositSetB(cell)` (stones) |
| 0xFF00FF00 green | if the pixel's vertex is in the grid, `rand() % 100 > 70` and no doodad is there: add doodad { `doodad_grass_0`, `doodad_plants_5` }[`rand() % 2`] (the table's third entry `doodad_plants_6` is never drawn); then always `PlaceRandomDepositSetA(cell)` (trees) |
| 0xFFFFFFFF white | `MapInfo::AddStartPosition(cell)`, without a duplicate test |

Then unlock, `FlushDirtyRects()`, release the texture. Since every pixel of a cell repeats the cell action, a
resource cell fills up to the cap of 7 and a white area adds one start position per pixel [inferred].

**Noise terrain generator** `ai::terrain::TerrainGenerator` [known] S 006b24f0, S 00688540. `Run`: sink slot 0
`(1)`; `w` = source width - 1, `h` = source height - 1; by mode: 0 `ApplyPerlin`, 1 `ApplyFaultLines`, 2
`ApplyFBM`, 3 `ApplyMultiFractal`; sink slot 0 `(0)`. It is started by
`CMapRenderer::RunTerrainGenerator(mode, scaleX, scaleY, params8, faultAmplitude)`, a virtual of the map renderer
(vftable S 007f9504 slot 1) with no caller in the image; a second virtual `RunTerrainGeneratorToBuffer`
S 00688590 fills a float buffer instead. One layer:

- Perlin S 006b1910: for every vertex (x, y) with x < w, y < h: value = `PerlinNoise.GetValue(x * scaleX / w,
  y * scaleY / h)` with the 8 parameters; height = `trunc(value)` written through sink slot 2.
- Fault lines S 006b1dd0: collect the border vertices of the w × h grid; `params[2]` times (default 8): pick two
  different random border vertices with the generator's own RNG, build the vertical plane through them,
  `d = rand01 * faultAmplitude`; every vertex gets `height + d` on one side of the plane and `height - d` on the
  other.
- FBM S 006b1a90 and multifractal S 006b1c30: the same loop with `NBase::FBMNoise::GetValue` S 006b1760 /
  `NBase::MultiFractalNoise::GetValue` S 006b1800 on the same scaled coordinates; in map mode the result is
  **added**: height = `trunc(current height (source slot 3) + faultAmplitude * value)` through sink slot 2
  [known for the calls; inferred that the multiplied operand is the noise value, a stack slot in the decompile].
- In buffer mode, modes 0, 2 and 3 store the value at `buffer[y * w + x]` and keep the
  running minimum and maximum at +0x50 / +0x54 instead of writing the map [known].
- [TODO] not established: the three noise functions themselves and the meaning of the 8 noise parameters
  (§10 question 6). The code is unreachable, so the remake does not need it.

### 3.12 Editor overlay

`DrawEditorCellOverlay` S 006066d0 (the dialog's draw slot) [known at summary level]: prints the cursor cell as
`XxY`, then per mode text labels at projected map positions: in every mode without a case of its own (1, 2, 3,
4, 6, 10, 11, 12, 17, 18, 19) the start positions as `P<n>`, `n` = zero-based index in `MapInfo`; mode 5 the
slope class towards each of the six neighbours (`0`, `+1..+3`, `+M`, `-1..-3`, `-M`) and, at a hex distance
below 20 from the cursor, `X` on cliff cells (0x40) and `C` on shore cells (0x8); mode 7, on every cell that holds a
ground resource, a letter for its type followed by the amount when it is not 0 (1000 shown as 7): `G` gold,
`S` stone, `I` ironOre, `C` coal, `W` water, `F` fish, `s` salt, `J` gemstones 0xCB98C903, no label for any
other type [known]; mode 8 a marker at the cursor vertex and, at a hex distance below 20, `X` on cells with bit
0x400; mode 9 the territory owner digit and `B` on border
cells (0x20); mode 13 the ambient sound names; mode 15 `SR` on route cells (0x8000) and then the mode-14
drawing; mode 14 a preview of the selected harbour type at the cursor when `CanPlaceHarborAt` passes, and the
existing harbours (`MapEditor_DrawHarborOverlay` S 00604340 [known]: `H` at the harbour cell; for each of the
four orientations of the harbour property `S` at every defined ship position and `WS` at the water-street
position when it is not (0, 0); for an existing harbour `WS ShipRoute` at every exit that carries a
route); mode 16 the ring of the copy region. Presentation only.

### 3.13 Developer variables and the CVar server

**Registration** [known] S 005c6270: a `CVar` constructor registers with the native toggle window when the
pointer S 0088b81c is set, otherwise with the remote server through `RemoteCVarEntry`; with the server absent
(gate byte 0) the registration is a no-op and the bound variable simply keeps its compiled default.

**Server** [known] S 0067c6d0, S 0067cc10, S 0067df40. Created only when the gate byte S 0088ca50 is non-zero
(never in the unmodified image; the two-byte patch is in [../BINARY_PATCHES.md](../BINARY_PATCHES.md)). Then:
`WSAStartup(2)`, a TCP socket bound to 0.0.0.0, port **1234**, `listen` backlog **10**, a worker thread. The
thread loops until the stop flag: `select` with zero timeout over the listen socket and up to **8** clients;
accept into a free slot (none free: the connection stays in the backlog); read up to 1023 bytes per client and
parse them; for every writable client send its queue and broadcast changes; `Sleep(200)`.

**Wire format** [known]: ASCII text. Every message from the server is followed by one `&`; fields are separated
by `$`. Messages from a client are parsed from one `recv` buffer; a message split across two reads is not
reassembled.

| Direction | Message | Meaning |
|---|---|---|
| server → client | `APP$<appName>&` | first message after accept; the name is `DefaultApp` (§2.5) |
| server → client | `CREATE$<group>$<name>$<type>$<value>[$<min>$<max>]&` | one per registered variable after `APP`, on `REFRESH`, and when a variable is registered later; `type` is the type character; min and max only for int and float |
| server → client | `CHANGE$<group>$<name>$<value>&` | the program changed the variable (shadow comparison once per loop and writable client) |
| server → client | `DESTROY$<group>$<name>&` | variable unregistered |
| client → server | `CHANGE$<group>$<name>$<value>&` | set the variable; unknown group or name is ignored silently; no range check; no echo |
| client → server | `REFRESH$` | resend every `CREATE` (8 bytes consumed, no `&` needed) |
| client → server | `CUSTOM$<text>&` | printed as `Custom Message: <text>` and passed to every registered custom listener |
| client → server | anything else | printed as `Unknown Message`, rest of the buffer dropped |

Value text: bool `0` / `1` (a `CHANGE` sets true iff the first character is `1`); int `%d` (parsed with `atol`);
float `%f` (parsed with `atof`); ranges `$%d$%d` and `$%f$%f`. The range formatter S 0067c960 loads the stored
minimum and maximum as float32 for every type and converts to integer for `%d`; an int variable's bounds were
stored as integers (§2.5), so its `CREATE` carries their bit patterns read as floats and truncated (0 for small
positive bounds) and not the bounds themselves [inferred from the decompile of S 0067c960 and S 005c6180; the
load instruction settles it]. A client is dropped when `recv` returns 0 or an error. A reference client is `tools/cvar_client.py`; its `set` command splits at spaces, so a name with spaces needs
`raw CHANGE$<group>$<name>$<value>`.

**Seen running** [live, 2026-10-14], without the patched executable: `CVarRemoteServer::ctor` S 0067e690 called
in the running game on a 0x760-byte block from `operator new` S 006f2524 opens its listen socket
(`0.0.0.0:1234 LISTENING`), is reachable from the LAN and sends `APP$DefaultApp`; with its pointer written into
the holder `g_pCVarServer` S 0088ca58, CVars constructed afterwards register (the `Lobby` and `CharSelection`
groups, 16 variables). A CVar constructed before the server exists stays unregistered; calling `RegisterVar`
S 0067c760 with its `RemoteCVarEntry` (`CVar +0x38`) registers it. `CHANGE` from the client sets the variable
(the lobby physics switches, [lobby-extras.md](lobby-extras.md) §6.1). Why the patched executable of
[../BINARY_PATCHES.md](../BINARY_PATCHES.md) did not start the server is [TODO].

**Native toggle window** `ai::debug::DebugToggleWindow` [known for the functions S 005c5840..005c5ce0]: a
window with categories (group names) of entries (bool checkbox, int, float) under a critical section. Nothing
creates it in this build (§2.5).

**The variables.** 134 construction sites in the decompiled image, 4 of them with a name built at run time
[known: call list]; all are tweaks of rendering, UI and the lobby, none touches simulation state:

| Group | Names |
|---|---|
| `ui` | `Hide UI`, `DumpToFile` (writes the UI tree to `c:\ui_dump.txt` and clears itself, S 004919e0), `BatchUiRendering`, `bRenderMultipleChars`, `drawbatch`, `AlwaysSetSharedParameter`, `MiniMapRender`, `MiniMapRenderSymbols` |
| `SceneInfo` | `General`, `Profile`, `Items`, `Shadow`, `Freeze Shadow`, `Clip Shadow` (int 0..6), `Particle`, `PostFX`, `Building`, `Ship`, `Freeze Culling`, `Terrain`, `Working Times`, `FogOfWar`, `AmbientAnimals`, `EnviromentSpheres`, `StreetAABB` |
| `SceneDetail`, `MapDetail` | one bool per render pass and per map layer (names built at run time; [rendering.md](rendering.md) §2.2) |
| `Character` | `Info`, `Debug`, `Animals`, `ForceLOD` (int -1..3) |
| `Street` | `DepthBias` (float -1..1, step 0.001) |
| `Water` | `TextureScaleFFP` (1..32), `TextureAnimSpeedFFPms` (500..10000), `TextureOpacityFFP` (0..255), `TextureMoveSpeedFFPms` (1000..50000), `TexScale0U/0V/1U/1V` (-1..1), `TexRot0/1` (0..360) |
| `Shader` | `MaxShader` (int 0..2) |
| `GraphicDevice`, `ResourceMgr`, `VideoMemSink` | `EffectStateCache`, `DumpDetailedStats`, `AllocVideoMem (MB)` and `AllocAGP (MB)` (0..512) |
| `ItemTypes`, `InstanceRenderer` | `Animated`, `Instanced`, and one bool per item type / instanced mesh |
| `Lobby`, `Lobby GfxSettings`, `LobbyTesting`, `CharSelection`, `MiniGamePawnChess` | 72 lobby tweaks (46 + 19 + 1 + 3 + 3): debug displays (`Show DBG`, `Show PhysicDBG`, `Show CameraDBG`, …), camera and bubble offsets, LOD borders, render-mode switches `rm*`, `Toggle Toon Shading`, … |
| `Evil Hacks` | `CustomizeNPCHack`, `NPCIndex`, `color1..color8` (int 0..32), `SAVE` (the NPC look designer, S 004f84b0) |

### 3.14 Other developer aids (summary)

| Aid | Behaviour | Reference |
|---|---|---|
| Typed cheats | offline only (network mode 0), exact text in the chat line: `WhatTheHell` (local game speed 20.0), `WhatCanEyeSee` (explore the whole map), `DontWantToLose` (mark the map as completed), `ThatsANiceView` (free-fly camera on / off), `ItsLikeAJackpot` (10 of every ware into the first completed store) | [camera-input-cutscenes.md](camera-input-cutscenes.md) §3.12 [known] S 005ec340 |
| Debug toggles of the game screen | four toggle buttons: AI (views `r` resources, `m` military, `i` systems, `c` cells), harbours (ship id and state per ship), flags (flag id; near the camera also packages and targets; the planned street path as `X`), military (cycle: buildings with attackers, soldiers with state and target, fight groups, off) | same document §3.13; S 0061f3b0, S 0061a900, S 0061a080, S 00619570 |
| Continent overlay | info-map mode 1 with a flag of the local player entry set: the continent id of every visible cell as text | S 005ef060 [known at summary level] |
| Scene debug draws | per-CVar overlays: statistics, shadow map, character state text, animals, effects, post FX, building instances, ships, flags, quadtrees, shadow casters | S 00683850; [rendering.md](rendering.md) |
| Lobby camera debug | F7 with no focused widget toggles the lobby camera / render statistics overlay | S 00429800 [inferred] |
| Lua debugger hook | five lazy thunks into an optional `LuaDebugger.dll` (not shipped): `_AddLuaState@4`, `_RemoveLuaState@4`, `_NewFile@16`, `_Break@4`, `_Hide@0`; `LoadLibraryA` on first use, silent when the DLL or export is missing. The script function `Default.Break()` calls `_Break` for the calling script thread | [../lua-surface.md](../lua-surface.md) §1.5 [known] S 005cdc90..005cdd30, S 005cdf10 |
| Cutscene debug list | `menu.addCutsceneDebugName`, `dbg_addCinematics`, `dbg_playCinematic` | [lua-runtime.md](lua-runtime.md) §4.3 |
| Log switches | `-log_disabled` / `-log_error` / `-log_warn` / `-log_info` = log level 0 / 1 / 2 / 3 (default 1); `-log_path <dir>`; ten rotating `Logfile_N.txt` | [app-shell.md](app-shell.md) §3.2, §3.12 [known] S 00403ac0 |
| Start switches | `-map <name>` (start a free-game map directly), `-start <name>` (start a save), `-nolobby`, `-mptest` (sets a byte nothing reads), `-lobbyfast`, `-localhostmode`, `-net` | [app-shell.md](app-shell.md) §3.2 |
| Crash files | `crashdump.dmp`, `crashlog.txt` in the log directory | [app-shell.md](app-shell.md) §3.12 |

---

## 4. Update order

- **Program start**: `nMenu::System::Initialize` S 005dda30 constructs the `Debug` dialog [known]; CVar
  constructors run where their owners are constructed (static initialisers, scene, renderer, lobby) or, for
  function-local statics, at the first call of the owning function (e.g. `ui/DumpToFile` in S 004919e0)
  [known for the cited example; inferred for the rest from the caller list of S 005c6270]; the CVar server
  holder is initialised by the first `RemoteCVarEntry` constructor and stays empty [known] S 0067cba0,
  S 0067c6d0 (gate byte 0).
- **Editor shown**: §3.1 "Show". **Editor hidden**: §3.1 "Hide".
- **Per rendered frame while the editor dialog is open**: `Update` (§3.1), then the dialog's draw slot with the
  overlay (§3.12). The editor runs in the UI update, outside the logic tick, and writes the world directly. In
  `CApplicationEx::FrameTick_InGame` S 004018e0 the menu system's update is called before
  `NLogic::System::Update` [known], so an edit is seen by the logic ticks of the same frame [inferred: the
  dialog update is dispatched from the menu system's update; [app-shell.md](app-shell.md) §3.5]. Logic ticks
  are skipped only while `batchEditing` is set (S 00527070), which the editor does only for the duration of one
  building placement or removal [known] S 00604dd0.
- **Per CVar-server loop** (own thread, every 200 ms, only when enabled): accept, read and apply `CHANGE`
  messages directly to the bound variables under the server's critical section, send, compare shadows.
  A client's write is not synchronised with the main thread [inferred: the variables are plain memory].
- **Per logic tick**: nothing of this subsystem.

---

## 5. Inputs and outputs

**Consumes**: mouse buttons and modifier keys through `nUi::GameAction`; the game screen's cursor cell and fine
position; the property database (lists, placement rules); `scripts\editor\*.lua`; `copypaste.dat`; map files of
type 1.

**Produces**: direct changes of the running world through `MapModifier`, `NResources::System`,
`NDoodads::System`, `NVillage::System`, `NLogic::Ambients`, `NNavy::System` (harbours, routes, ships),
`LogicSpawnSystem`, `LogicChestSystem`, `MapInfo` (start positions, name, size); a map file
`campaignMaps\<name>.s2m`; `copypaste.dat`; `c:\ui_dump.txt` (CVar `ui/DumpToFile`).

**Lockstep and network**: the editor sends **no command and no network message**; every edit bypasses the
command path ([game-commands.md](game-commands.md)). The CVar server's TCP protocol (§3.13) is a local developer
channel and not part of the game or lobby protocols ([../message-catalog.md](../message-catalog.md) has no entry
for it).

**Interfaces offered to other code**: `NLogic::Edit` (§2.1), whose `GetBatchEditing` (slot 1) is read by the
tick loop, the village (building placement and removal, construction start, workers, soldiers), the street net,
ship construction, the resources update and the scene update (list with addresses in §3.2), and whose
`GetFlag(1)` (slot 11) is read by the free-fly camera S 00786ae0 [known: every use of the accessor S 00695ea0 on
`g_pGameSystem` in the decompiled image]; the `editor` Lua table.

---

## 6. Data-driven parameters

| File | Content | Example values |
|---|---|---|
| `data\game\scripts\editor\scatter.lua` (encrypted) | 28 `editor.scatter_addElement` and 8 `editor.scatter_addPattern` calls; presets `Stones` (8 elements), `Trees` (10 elements, 8 patterns), `Grass` (4), `Cactus` (4), `Animals` (2); no `scatter_setSize` | `editor.scatter_addElement("Trees", "BirchA", 0.2)`, `editor.scatter_addPattern("Trees", "meadow yellow flowers", 0.2)`; every weight is 0.2 [known: data] |
| `data\game\scripts\editor\copypaste.lua` (encrypted) | five presets | `Height` (`paste_heightMode` 1), `HeightAdd` (2), `HeightSub` (3), `Doodads` (`paste_useDoodad` 1), `Deposit` (`paste_useDeposit` 1) [known: data] |
| `data\game\scripts\properties\patterns.lua`, `deposits.lua`, `doodads.lua`, `Goods.lua` | the ids the tools hard-code | `pattern_meadow = properties.pa_create("bfe4e8e3")`, `pattern_seaground = properties.pa_create("babeb00b")`, `pattern_snow = properties.pa_create("fade0ff")`, `tree_02 = properties.dp_create("063287b3")`, `stone_01 = properties.dp_create("9f1bd60e")`, `doodad_stones_0 = properties.dd_create("455c1f4e")`, `fish = properties.gp_create("4012e5a3")` [known: data] |
| `harbors.lua`, `spawnpoints.lua`, `animals.lua`, `sounds.lua`, `buildings.lua`, `tribes.lua` | the element lists of modes 6, 10, 13, 14, 17, 19 | [properties-data.md](properties-data.md) |
| Textures `infoMap`, `landMap` | inputs of the generator. `UiResourceManager::GetOrLoadTexture` S 00494000 loads an unknown name through `ai::ui::ResourcePath` S 004bdc60 (kind Gfx): `[data]\gfx\<name>` plus `.dds` when the name holds no `.`, so the files are `data\game\gfx\infoMap.dds` and `landMap.dds` [known]. Neither file is in the install [known: folder listing] | §3.11 |
| `data\game\Editor\LogicalEditor\Presets\*.lep` | eight preset files of an external editor; not read by the client | [formats-inventory.md](formats-inventory.md) §3.7 |
| Texture `uiBigDialog` (`data\game\gfx\uiBigDialog.dds`) | the dialog's style name, a string in the constructor S 00607d20 [known]. The overlay text uses the UI system font (`UiResourceManager::GetSystemFont`, S 006066d0) [known]. The install also holds a font `language\<lang>\fonts\editor.fnt`; no code names it (the only string `editor` in the image is the Lua library name, S 0060a340) [known: string search of the decompiled image] | [ui-toolkit.md](ui-toolkit.md) |

Constants compiled into the editor: brush radii and amounts (§3.5), scatter size default 7, chest content 10,
resource step 2 and cap 7, the generator's bands and percentages (§3.11), CVar server port 1234, backlog 10,
8 clients, 200 ms.

---

## 7. Save and load

- The editor's own state (mode, presets, copy buffer, anchor, route under construction) is not part of any save
  [known: no `Store` function in the class].
- `copypaste.dat` persists the copy buffer between editor sessions (§3.7).
- The edited world is persisted only by the editor's save (§3.9), as a type-1 map file holding the map part.
  `NLogic::Edit` has no stored state: `batchEditing` and the three flags start at 0 with every logic system
  [known] S 00538c70.
- CVar values are not stored anywhere; they return to their compiled defaults at every start [known: no writer].

---

## 8. Determinism notes

- The editor **does** touch simulation state: terrain, grids, resources, deposits, doodads, animals, buildings,
  harbours, routes, ships, spawn points, chests, start positions. It does so outside the lockstep command path,
  from the UI update, using the C runtime `rand()` and the frame rate (tools repeat per frame). It is therefore
  usable only where no second machine has to agree: it is a single-machine authoring tool. Nothing in the code
  restricts it to offline sessions [known: no network-mode test in S 00609130 or S 00604dd0]; since no opener
  exists this has no consequence in the shipped game.
- `batchEditing` changes simulation behaviour (ticks skipped, instant buildings); in the shipped game it is only
  ever set by editor code [known for the cached image, §3.2].
- The typed cheats change simulation state and are limited to network mode 0
  ([camera-input-cutscenes.md](camera-input-cutscenes.md) §3.12).
- CVars, the CVar server, the toggle window, the overlays, the Lua debugger hook and the log are presentation
  and diagnostics: all registered variables are render, UI or lobby parameters (§3.13), and the overlays only
  read. `Default.Break()` hands control to an external debugger and would stall a lockstep session if a
  debugger DLL were present [inferred].
- The noise terrain generator has its own seeded RNG (0x5432ACE0) and would be reproducible; the image-driven
  generator is not (`rand()`).

---

## 9. Notes for a Godot reimplementation

- **Build the remake's editor as its own tool**, not as a port of this dialog. What must be kept is the *data
  contract*: every edit has to leave the map in the state the game expects at load, because the game recomputes
  nothing ([../map-format.md](../map-format.md) §5.5). The original editor keeps this contract by construction:
  object constructors and destructors set and clear their grid bits, pattern changes re-derive the pattern
  bits, elevation changes re-derive water and shore, and save re-derives water, shore, cliffs and continents.
  A remake editor (and the converter, when it repairs or re-exports maps) should run the full derivation of
  [map-resources.md](map-resources.md) §3.3 and [../map-format.md](../map-format.md) §5.6, §5.7 on export
  instead of trusting incremental updates.
- **Reuse the placement rules exactly** (§3.10): deposit, harbour, route validity, one-object-per-cell guards.
  The harbour neighbour test is ineffective in the original; shipped maps nevertheless keep harbours at least
  3 cells apart ([../map-format.md](../map-format.md) §6.4 H4), so the remake editor should enforce the
  intended rule (no harbour on the six neighbours).
- **Ground resources**: amounts 1..7, 1000 = unlimited, one type per cell; a change of the water, mining,
  buildable or ship-ground bit clears the cell's resource. An editor should apply patterns and heights first and
  resources last.
- **Brushes** map onto ordinary editor tools; the hex-disc walk and the cell ↔ vertex conversion (§3.1) are the
  only parts that must match, because doodads and deposits are positioned on the vertex grid. The numeric brush
  constants are free.
- **Ship routes**: reproduce the tool's contract, not its UI: a route is a list of pairwise adjacent free-water
  cells of one continent between two exits of different harbours, more than 2 cells apart, sharing no cell with
  another route; creating it must set the route bit on every path cell and link both exits.
- **Map export** corresponds to the map part only (§3.9). A remake editor that wants prepared scenarios
  (pre-built villages, chests) needs its own format or the original's logic part
  ([save-format.md](save-format.md) §3.3); the original editor cannot export those.
- **Batch editing** is worth keeping as an explicit "set-up mode" of the simulation core: instant buildings and
  no ticks while a script or the editor populates a world ([village-buildings.md](village-buildings.md) §3.2).
- **Generators and presets** (`Infomap`, scatter, copy and paste) are conveniences; if wanted, Godot's noise
  resources and scene instancing replace them. `scatter.lua` and `copypaste.lua` need not be read.
- **Developer variables**: Godot's project settings, debug draw flags and remote debugger replace CVars, the
  server and the toggle window. Nothing of §3.13 needs a wire-compatible implementation. Cheats: keep the five
  strings as an offline-only developer console if desired.
- **A converter** has to provide nothing from this subsystem beyond reading maps; `copypaste.dat` and the `.lep`
  presets can be ignored.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered: nothing in the shipped build opens the `Debug` dialog. Every call of the four functions that reach a dialog slot by index passes a constant, and none activates slot 1 (`ActivateScreenById`: 4, 6; `ToggleScreen`: 2, 7, 5, 0, 3); slot 1 is only tested by `Game::Update` and `Game::Draw`; the typed field `System + 0x14` has no reader; the Lua libraries have no opener. Left: a load through an untyped pointer. Opened by the debugger with `nMenu::Game::ToggleScreen(game, 1)` S 005ea960 on the main thread in an offline match, the dialog shows a menu for placing objects and runs: `Update` S 00609130 once per frame, `toolMode` (+0x65c0) 6, `panelShown` (+0x65c4) 1, combo selection 6, list selection -1, `Scene + 0x710` 0 (the state `OnShow` leaves), the logic ticking on [live, 2026-10-12] | static: S 005d97a0, S 005ea960, S 005d95f0, S 005d97e0 and their call sites (S 005dfef0, S 005e27c0, S 005eb310, S 005dd5e0, S 005eb180, S 005efea0, S 005eae90, S 005e3810, S 005efdd0) |
| 2 | Partly answered: opened through the debugger the editor runs; the Buildings, Elevations and Tools modes work and the Start Positions tool's right button crashes on a non-start cell (§3.4); `GameFile_Save(1, …)` writes only into a `campaignMaps` file that existed at start-up (§3.9) [live, 2026-10-12]. Open: the other tools, the `editor` Lua library, whether a second Enter restores the view | observation in the running game after opening the dialog through the debugger |
| 3 | What the scene byte `Scene + 0x710` gates (cleared while the editor is shown, §3.1 step 3). Typed users: the constructor (1), `SetFlag710` S 00680110, and `RenderPreviewTexture` S 00681300, which saves, clears and restores it around the scene's `Update` and `Render`; `Scene::Update` S 006805e0 does not test it, so the reader is below `Render` | static: raw reads of `[scene + 0x710]` in the render path; live: a read watch on the byte for one frame |
| 4 | Whether anything sets `NLogic::Edit.flags[0..2]`: no call of slot 12 exists in the decompiled image, so the free-fly camera's test of flag 1 (§2.1) never passes through that path. In a free game with ships the three bytes read 0 [live, 2026-10-12] | live: watch the three bytes `Edit + 5..7` with a write watch |
| 5 | Whether map set-up or scripts set `batchEditing` by a path the static search does not see. Every use of the `Edit` accessor S 00695ea0 and of the typed field `System + 0x38` was read: slot 0 is called only by the editor's Buildings tool (S 00604dd0); the noise generator's sink (§2.6) is the one untyped holder left. In a running free game (a loaded save with ships) `SetBatchEditing` S 00538a60 was not called and `Edit + 4` read 0 [live, 2026-10-12] | live: watch the byte `Edit + 4` during a match start; static: the sink argument in the `CMapRenderer` constructor S 006890f0 |
| 6 | The noise functions behind terrain modes 2 and 3 (`FBMNoise::GetValue` S 006b1760, `MultiFractalNoise::GetValue` S 006b1800), `PerlinNoise::GetValue`, and the meaning of the 8 noise parameters | static read of the three functions; low priority, unreachable code |
| 7 | Answered (§3.13): the server works when created at run time: `CVarRemoteServer::ctor` S 0067e690 listens on 0.0.0.0:1234, answers `APP$DefaultApp`, registers CVars constructed afterwards (earlier ones through `RegisterVar` S 0067c760) and applies `CHANGE` [live, 2026-10-14]. Still open: why the patched executable (gate byte S 0088ca50 forced) did not start it, and thread safety | live: the patched executable with a breakpoint on S 0067c6d0 and S 0067e690 |
| 8 | The resource-type argument of the three `AddResourceAtCell` calls in the `infoMap` pass (fish below 20, water in the two bands from 3000 to 9000): the decompile assigns the id to a register and passes a stack address (§3.11) | disassembly of S 006033d0 at the three call sites |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 00538c70 | `NLogic::Edit::ctor` | edit interface, vftable S 007e7c28 |
| 00538a60 | `NLogic::Edit::SetBatchEditing` | batch-editing flag, flush on clear |
| 00538aa0 / 00538ac0 | `NLogic::Edit::SetVertexElevation` / `SetCellPattern` | deferred terrain writes |
| 00538ae0 / 00538b20 | `NLogic::Edit::CreateDeposit` / `RemoveResourceAt` | deposits |
| 00538b50 / 00538bb0 | `NLogic::Edit::PlaceBuilding` / `RemoveBuildingAt` | buildings |
| 00538bf0 / 00538c10 | `NLogic::Edit` slot 8 / `RemoveDoodadAt` | doodads |
| 00538ca0 | `NLogic::Edit::AddStartPosition` | start positions |
| 005dda30 | `nMenu::System::Initialize` | constructs the `Debug` dialog |
| 00607d20 / 00607ff0 | `nMenu::Debug::ctor` / `dtor` | editor screen, `g_pMapEditor` |
| 0060a340 / 00602000 | `nMenu::Debug::OnShow` / `OnHide` | widgets, `editor` library, fog overlay, recompute on hide |
| 00609130 | `nMenu::Debug::Update` | save, load, mode change, mouse dispatch, copy capture |
| 00608160 | `nMenu::Debug::RefillElementList` | element list per mode, runs the preset scripts |
| 00604dd0 | `nMenu::Debug::HandleToolClick` | all tools by mode and button |
| 00601920 | `nMenu::Debug::PaintPatternBrush` | pattern brush |
| 00601a40 / 00601c00 | `nMenu::Debug::ApplyElevationBrush` / `SmoothElevationBrush` | elevation brushes |
| 00602f20 / 00602ac0 | `nMenu::Debug::ScatterAtCursor` / `MapEditor_PlaceObjectByPropertyId` | scatter tool |
| 00609ce0 / 00608f50 | `nMenu::Debug::FindOrCreateSetting` / `FindOrAddPasteSetting` | presets by name |
| 00609e80 / 00609f20 / 00609fd0 | `Scatter_AddElement` / `Scatter_AddPattern` / `Scatter_RemoveElement` | scatter preset lists |
| 0060a080..0060a280, 006098d0..00609b50 | `Lua_editor_*` | the 13 functions of the `editor` library |
| 00602780 / 00601300 | `nMenu::Debug::PasteCopyBuffer` / `MapEditor_PasteCell` | paste |
| 006011b0 | `MapCellInfo_Query` | fills a `CopyPasteCell` from a vertex |
| 006015f0 / 00606050 | `nMenu::Debug::SaveCopyPasteBuffer` / `LoadCopyPasteBuffer` | `copypaste.dat` |
| 00600f70 / 00601000 | `ai::editor::CopyPasteCell::Save` / `Load` | one record |
| 00602890 / 006029a0 | `Tool_ScatterDepositSetA` / `Tool_ScatterDepositSetB` | tools "Forest", "Stones" |
| 00601750 / 006025d0 | `MapEditor_PlaceRandomDepositSetA` / `SetB` | random tree / stone with pattern and doodad |
| 00601120 | `MapEditor_FillAllCellsPattern` | tool "Fill with gras" |
| 006021d0 | `MapEditor_Tool_PaintPatternAroundFlaggedCells` | tool "Create Seaground" |
| 006020e0 | `MapEditor_Tool_ReseedResourceOnFlaggedCells` | tool "Create Fish" |
| 006010d0 / 00673050 | `GameSystem_CallSub673050` / `MapModifier_RefreshPatternBitsAll` | tool "Validate Map" |
| 006048f0 | `nMenu::Debug::Tool_GenerateFromImageMaps` | tool "Infomap" |
| 006033d0 / 00603d60 | `MapEditor_ApplyInfoMapImage` / `Tool_ApplyLandMapImage` | generator passes |
| 0078d7c0 / 0078d960 / 0078d800 / 0078d880 | `DebugShipRouteTool` `Begin` / `AddPoint` / `IsRouteValid` / `Finish` | ship-route tool |
| 0052dbb0 / 0052d920 | `GameQuery::IsFreeHarborExitAt` / `CheckHarborExitPair` | route end-point rules |
| 0052eda0 | `GameQuery::CanPlaceHarborAt` | harbour placement |
| 0052eb10 / 0052e150 | `GameQuery::CanPlaceDepositAt` / `_TerrainCheck` | deposit placement |
| 005576e0 / 0052dc30 | `Village_CheckBuildingPlacement` / `HasNoTerritoryBuildingWithinRadius4` | building rule of mode 6 |
| 006066d0 / 00604340 | `nMenu::Debug::DrawEditorCellOverlay` / `MapEditor_DrawHarborOverlay` | overlay |
| 006736a0 / 00674360 | `MapModifier::SetVertexElevation` / `SetCellPattern` | terrain writes |
| 006745e0 / 00674650 / 00674e70 | `MapModifier::AddResourceAtCell` / `ConsumeResourceAtCell` / `ConsumeAnyResourceAtCell` | ground resources |
| 006730e0 / 00672f30 | `MapModifier_FlushDirtyRects` / `MapModifier::RefreshWaterAndCliffsAll` | derived data |
| 00532120 | `GameCmdRouter_Route_00672d80` (a `MapUpdateBatch` member) | continent rebuild request: at once when the batch counter is > 0, else flagged for the batch end |
| 00532180 / 005321c0 | `MapUpdateBatch_Begin` / `MapUpdateBatch_End` | map-update batch (counter - 1 / + 1, flush when > 0) |
| 006010f0 | `MapEditor_AddResourceAtCell` | mode 7: `AddResourceAtCell(cell, &type, 2)` |
| 00605c60 | `ai::editor::EditorSetting::ConstructNamed` | new scatter preset: size 7, +0x40 = argument |
| 00557780 | `Village_CanPlaceBuilding` | `Village_CheckBuildingPlacement(...) == 0`, the form the Buildings tool calls |
| 007663f0 | `nUi::Listbox::Update` | per-frame list update: sets the "row clicked this frame" byte |
| 00786ae0 | `nGame::Camera::UpdateFreeFlyMode` | reader of `Edit` flag 1 (slot 11) |
| 00695ea0 | `Generic_GetDword_38` | accessor of `NLogic::System + 0x38` (the `Edit` object) |
| 00494000 / 00493500 / 004bdc60 | `UiResourceManager::GetOrLoadTexture` / `UiResourceManager_LoadGfxTexture` / `ai::ui::ResourcePath::ctor` | texture by name → `[data]\gfx\<name>.dds` |
| 004919e0 | `nUi::Root::ProcessDumpToFileCVar` | CVar `ui/DumpToFile` → `c:\ui_dump.txt` |
| 0067cba0 | `CVarServer_GetHolder` | lazy holder of the CVar server |
| 004018e0 | `CApplicationEx::FrameTick_InGame` | frame order: menu update, then logic update |
| 005aa260 / 005a9fa0 / 005ab180 | `GameFile_Save` / `GameFile_SaveMap` / `nGame_File_load` | map export and load |
| 00688540 / 00688590 | `CMapRenderer::RunTerrainGenerator` / `RunTerrainGeneratorToBuffer` | unreachable entry of the noise generator |
| 006b0e60 / 006b24f0 | `ai::terrain::TerrainGenerator::ctor` / `Run` | noise terrain generator |
| 006b1910 / 006b1dd0 / 006b1a90 / 006b1c30 | `ApplyPerlin` / `ApplyFaultLines` / `ApplyFBM` / `ApplyMultiFractal` | generator modes 0 / 1 / 2 / 3 |
| 005c6270 / 005c6370 / 005c64a0 | `CVar::ctor_Bool` / `ctor_Float` / `ctor_Int` | developer variables |
| 005c5fd0 / 005c6090 / 005c6180 | `RemoteCVarEntry::ctor_Bool` / `_Float` / `_Int` | server-side records |
| 0067c6d0 / 0067e690 / 0067cc10 | `CVarServerHolder_Init` / `CVarRemoteServer::ctor` / `OpenListenSocket` | server creation, gate, socket |
| 0067df40 | `CVarServer_ThreadMain` | accept, read, send loop |
| 0067d870 | `CVarRemoteServer::ProcessClientMessages` | `CHANGE$`, `CUSTOM$`, `REFRESH$` |
| 0067cdf0 / 0067cfc0 / 0067cf30 | `BuildCreateMsg` / `BuildChangeMsg` / `BuildDestroyMsg` | outgoing messages |
| 0067c840 / 0067c960 / 0067ca70 | `RemoteCVarEntry::FormatValue` / `FormatRange` / `ParseValue` | value text |
| 0067d0a0 / 0067d500 / 0067d6c0 | `FlushClientQueue` / `CVarServer_BroadcastChangedVars` / `SendAllVarsToClient` | framing with `&`, change polling |
| 005c5840..005c5ce0 | `ai::debug::DebugToggleWindow::*` | native toggle window (never created) |
| 005cdc90 / 005cdce0 / 005cdc40 / 005cdd30 / 005cdbf0 | `LuaDebugger_AddLuaState` / `RemoveLuaState` / `NewFile` / `Break` / `Hide` | thunks into `LuaDebugger.dll` |
| 005cdf10 | `LuaDefault_Break` | script function `Default.Break()` |
| 005ec340 / 005eba50 | `nMenu::Game::OnKeyDown` / `Cheat_FillStoreWithGoods` | typed cheats |
| 0061f3b0 / 0061a900 / 0061a080 / 00619570 | debug toggle overlays (AI / harbour / flag / military) | in-game debug overlays |
| 00683850 | `S2CG::Scene::RenderDebugOverlays` | scene debug draws |
| 00403ac0 | `ParseCommandLine` | log and start switches |
