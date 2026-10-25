# Camera, input and cutscenes

Tags: **[known]** = read directly at the address given (S 00xxxxxx, binary `sadk_noav.exe`) or in the named data
file and key; **[inferred]** = one step of reasoning from what is visible; **[TODO]** = open, with what would
settle it. Nothing here was observed in the running game.

Related documents, not repeated here: [game-commands.md](game-commands.md) (the command events that clicks end
in, `nGame::System`, the action buttons), [logic-core.md](logic-core.md) (game speed, pause, the tick loop),
[lua-runtime.md](lua-runtime.md) (the `menu` and `cutscene` Lua tables, quest scripts),
[rendering.md](rendering.md) (scene, frame order, pick access, `graphics.xml`), [audio.md](audio.md) (listener,
voice-over, ducking), [streets-transport.md](streets-transport.md) (street planner),
[formats-inventory.md](formats-inventory.md) (`settings.cfg`, `cursors.xml`, user folder),
[../subsystems.md](../subsystems.md) §2.1 and §5 (main loop, developer leftovers), [../map-format.md](../map-format.md)
(grid and world coordinates).

---

## 1. Purpose and scope

This subsystem is everything between the player's hands and the simulation that is not a widget:

- the in-game camera `nGame::Camera` (five modes: standard RTS view, look-around, free fly, an automatic
  "screensaver" view that follows settlers, and the scripted mode used by cutscenes);
- the cutscene camera (`ai::camera::CutsceneCamera` with its `CameraSpline`) and the cutscene script files;
- the cinematic screen `nMenu::Cinematic` that plays briefing pages (text, speaker portraits, voice-over, one
  camera path per page) and what it switches off in the simulation while it runs;
- mouse and keyboard input in a match: from the window message to the UI tree, the map cursor `nGame::Cursor`
  (ray picking of cells, vertices and objects), click selection, the placement modes of the selection controller
  `nMenu::MenuSelection` (building placement, street building), key bindings;
- screenshots, typed cheats, and the developer features that are present in the shipped binary (debug icon row,
  AI debug keys, the CVar tweak server).

It does not own any simulation state. The lobby world has its own camera classes (`Lobby::CLobbyCamera`,
`ai::lobby::OrbitCameraRig`, `Lobby::CLocalController`); they are not part of this document.

Conventions used below: world space is left-handed with **Y up** (the view matrix is built with a
`LookAtLH` helper, the projection with `PerspectiveFovLH`, S 004d9300 [known]); "cell" is a logic map cell,
"vertex" a terrain grid vertex ([../map-format.md](../map-format.md)); `dt` is the frame time in seconds returned
by `Timer_GetFrameDeltaSeconds` S 0057b850; "local player" is the player of this machine.

---

## 2. Data model

### 2.1 `nGame::Camera` (0xe0 bytes, embedded at `nGame::System + 0x2d0`) [known: Ghidra struct, uses below]

Vftable S 00835294. The graphics device holds a pointer to the active camera (`CGraphicDevice + 0x1b4`) and
asks it every frame through these slots (S 004d9300) [known], in the call order 2, 3, 5, 4, 0, 1: 0 receive the
view matrix and 1 receive the projection matrix (both are the empty function S 0064b9c0 in this class), 2
`GetEyePos` S 00784f70, 3 `GetLookAtPos` S 00784f90 (= `eyePos + lookDir`), 4 field of view S 00784fc0
(returns +0x0c; it is the **horizontal** angle, §3.1 Projection), 5 `GetNearFarPlanes` S 00784fd0. Slot 6
`TryGetTargetPos` S 00785000 (returns `hasTargetPos`,
fills the position when set) is not called by S 004d9300; [TODO] not established: its caller (a virtual call
through `CGraphicDevice + 0x1b4` with offset 0x18).

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x04 | u8 | `isActive` | set by `Activate`, cleared on world shutdown |
| +0x08 | i32 | `mode` | §2.2 |
| +0x0c | f32 | field of view | horizontal, radians; `50 × π/180` (set in `ResetView`; the factor `π/180` is the global S 0088a69c, filled by the static initialiser S 007c3210; the Ghidra name `viewDistance` is misleading) |
| +0x10 / +0x14 | f32 | `nearPlane` / `farPlane` | 1.0 / 500.0 world units |
| +0x18 | f32 | `zoomTarget` | zoom step the player asked for, 0..`zoomMax`, whole numbers |
| +0x1c | f32 | `zoomMax` | 4.0 (constructor S 007876e0, constant S 007d6980). The game has no other writer: the field's only other user is the read in `OnWheelDown` S 00786a10, and no ini key, Lua binding or XML attribute reaches it [known]. The reference install read 6.0 in a match with the constructor and its constant unchanged in memory [known: live 2026-10-12]; the value is written at run time by a module that is not the game's, [inferred] the `d3d9.dll` proxy in the install's `bin` folder (the widescreen fix), the only loaded module that belongs neither to the game nor to this project's mods |
| +0x20 | f32 | `zoomCurrent` | eased towards `zoomTarget` |
| +0x24 | f32 | yaw offset target | −1.5, 0 or +1.5 radians (Ghidra name `rotateRateTarget`) |
| +0x28 | f32 | yaw offset current | eased towards the target (Ghidra name `rotateRateCurrent`) |
| +0x2c | f32 | `distanceScale` | 70.0; eye distance per zoom unit is `0.3 × distanceScale` |
| +0x30 | f32 | `cachedFocusHeight` | −1.0 = invalid |
| +0x34 | vec3 | `desiredEye` | target eye position of the follow view; scratch elsewhere |
| +0x40 | vec3 | `focusPoint` | the ground point the standard view is built around |
| +0x4c | vec3 | `moveDir` | view direction after the yaw offset; the direction keys move along it |
| +0x58 | vec3 | `lookDirTarget` | unsmoothed view direction |
| +0x64 | vec3 | `eyePos` | eye position handed to the renderer |
| +0x70 | vec3 | `lookDir` | view direction handed to the renderer (look-at = eye + this) |
| +0x7c | vec3 | `savedLookDir` | `lookDirTarget` saved while in look-around mode |
| +0x88 | i32 | `followStyle` | 1 (only value written, S 007868f0) |
| +0x8c | map<int, u8> | keys down | the held keys among Shift (0x10) and the four arrows (0x25..0x28); head +0x90, size +0x94 |
| +0x98 | ptr | `followTarget` | render character followed by the screensaver view |
| +0x9c | u8 | `hasTargetPos` | +0xa0 is valid |
| +0xa0 | vec3 | `targetPos` | world position of the followed settler (slot 6) |
| +0xac | u8 | `slowLookSmoothing` | selects the direction smoothing factor (§3.2) |
| +0xad | u8 | `isUpdating` | set to 1 by every `Update`; not written by the constructor and no clearing write exists in the decompiled code, so the tests on it in the mode handlers always pass [inferred] |
| +0xb0 | ptr | `cinematicSettler` | logic settler of the screensaver view |
| +0xb4 | f32 | `cinematicTimer` | seconds left in the current screensaver state |
| +0xb8 | i32 | `cinematicState` | 0 follow, 1 orbit, 2 fly away (§3.6) |
| +0xbc | f32 | `orbitSign` | −1 or +1 |
| +0xc0 | f32 | `orbitRandom` | 0..0.995 in steps of 1/200; written, no reader found [inferred] |
| +0xc4 | vec3 | `flyAwayOrigin` | written when state 2 starts; no reader found [inferred] |
| +0xd0 | `NLogic::Unique` | follow id | id of the followed settler (hi +0xd8, lo +0xdc; −1 = none) |

### 2.2 Camera modes (`ECameraMode`, +0x08) [known: enum, S 00787530]

| Value | Name | Entered by | Per-frame handler |
|---|---|---|---|
| 0 | Standard | `ResetView(0)`, `ResetToStandardMode` | `UpdateStandardMode` S 00786e70 |
| 1 | LookAround | standard mode while the right mouse button is held | `UpdateLookAroundMode` S 00787310 |
| 2 | FreeFly | `ResetView(2)`: typed cheat `ThatsANiceView` (§3.12) | `UpdateFreeFlyMode` S 00786ae0 |
| 3 | Cinematic (screensaver) | nothing [inferred, below] | `UpdateCinematicMode` S 00786140 |
| 4 | Frozen | nothing [inferred, below] | hides the mouse cursor, nothing else |
| 5 | scripted | `ai::camera::CutsceneCamera::Start` S 0078a840 | none: the cutscene camera writes `eyePos` and `lookDir` |

Writers of `mode` in the decompiled code of the whole binary [inferred: search of every function's decompiled C
for the field and for the raw offsets `Camera + 8` / `nGame::System + 0x2d8`; a write through an untyped pointer
would not show]: 0 in `ResetToStandardMode` S 00784eb0, both wheel handlers and the look-around handler; 1 in
`UpdateStandardMode`; the argument of `ResetView`, whose two callers pass 0 or 2 (S 007868f0, S 005ec340); 5 in
S 00784e90. Nothing writes 3 or 4, so the screensaver and frozen modes cannot be entered in the shipped binary.

### 2.3 Cutscene camera

`ai::camera::CutsceneCamera` (8 bytes, pointer at `nGame::System + 0x630`, S 0078a710) [known]: +0 the driven
`nGame::Camera*`, +4 `CameraSpline*` (null until the first script is loaded).

`ai::camera::CameraSpline` (0x44 bytes, constructor S 0078d6f0) [known: Ghidra struct and constructor]:

| Offset | Type | Field | Initial value |
|---|---|---|---|
| +0x00 | u8 | `loaded` | 0; 1 after the constructor call in `LoadScript` |
| +0x01 | u8 | `playing` | 0 |
| +0x02 | u8 | `paused` | 0 |
| +0x04 | f32 | `time` | 0.0 seconds |
| +0x08 | vec3 | current position | not written by the constructor |
| +0x14 | vec3 | current look vector | not written by the constructor |
| +0x20 | map<f32, key> | position track | empty (head +0x24, size +0x28) |
| +0x2c | map<f32, key> | look track | empty (head +0x30, size +0x34) |
| +0x38 | f32 | `loopEndTime` | `FLT_MAX` |
| +0x3c | f32 | `loopLength` | 0.0 |
| +0x40 | u8 | loop flag | 0 |
| +0x41 | u8 | `relative` | 0 |

Track node (`std::map` node, key = time) [known, S 0078d2b0, S 0078c870]: +0x0c f32 time, +0x10 vec3 value,
+0x1c vec3 in-tangent, +0x28 vec3 out-tangent. The x component −100000.0 marks "no tangent".

### 2.4 `nGame::Cursor` (0x2c0 bytes, embedded at `nGame::System + 0x10`) [known: uses below]

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x04 | u8 | shown | set to 1 by `Init` S 00788460, cleared on world shutdown (S 007834e0) |
| +0x05 | u8 | enabled | `Update` returns at once when it is 0 (S 0078a2b0); set to 1 by the constructor S 00787e70, no other write exists in the decompiled code [inferred: always 1] |
| +0x06 | u8 | `bPlacementMode` | street placement is running |
| +0x08 | i32 | `placementKind` | 0, 1 or 2 (constructor: 1); which step tests the street overlay uses (§3.10) |
| +0x0c | i32[2] | street anchor cell | start flag, then the last accepted waypoint |
| +0x14 / +0x18 | i32 | `cellX` / `cellY` | map cell under the mouse (the "cursor cell") |
| +0x1c | i32[2] | vertex | terrain vertex under the mouse |
| +0x28 | `nUi::Picture` | marker widget | sprite at +0x1c0, texture rectangle at +0x1d8 |
| +0x2b0 | ptr | hover building | render object of the building under the mouse |
| +0x2b4 | ptr | hover ship | logic ship under the mouse |
| +0x2b8 | ptr | hover ship route | |
| +0x2bc | u8 | `bActive` | picking, marker and click selection run only when 1; 0 during a cinematic |

The mouse position itself belongs to the UI cursor `nUi::Cursor` (singleton): +0x24 x and +0x2c y as fractions
of the screen (0..1), +0x38 / +0x40 the position of the previous frame (`StorePreviousPosition` S 00492540, once
per frame), a visible flag at +0x70 [known for the offsets used here: S 004925c0, S 0078a2b0].

### 2.5 Selection controller `nMenu::MenuSelection` [known: S 00617910, S 00617bc0]

`mode` at +0x88: **1** normal, **2** building placement (the create-building box is open on a cell), **3** street
building, **4** a transient state that falls back to 1 on the next click. `hoveredCellX/Y` at +0x8c / +0x90 is
the cursor cell copied at the last click. The selected object itself is `ai::game::Selection`
([game-commands.md](game-commands.md) §2.4).

### 2.6 `nMenu::Cinematic` (menu screen, `nMenu::System + 0x30`) [known: S 005fb3e0, S 005fc110]

Offsets from the object start. Four interface faces: +0x00 `nMenu::Overlapped`, +0x20 `nUi::Desktop`, +0x24
`NCore::IUpdateable`, +0x28 `nUi::Event`.

| Offset | Type | Field |
|---|---|---|
| +0xc08 | i32 | phase: 0 fade in, 1 playing pages, 4 ending, 2 restore HUD, 3 restore speed (§3.8) |
| +0xc0c | f32 | phase timer, seconds, counts down |
| +0xc10 | f32 | minimum page time left, seconds |
| +0xc14 | f32 | game speed saved at `OnShow` |
| +0xc18 | u32 | index of the next page |
| +0xc1c | vector<string> | page captions (title text keys) |
| +0xc2c | vector<string> | page text keys (also the voice-over name) |
| +0xc3c | u32 | page count |
| +0xc40 | vector<string> | cutscene name per page ("" = keep the running path) |
| +0xc50 | vector<i32[2]> | anchor cell per page (−1, −1 = none) |
| +0xc60 | `nMenu::PanelCinematic` | bars, text, two speaker slots (+0x25ac, +0x25b0 from the screen start) |
| +0x24d8 | `nUi::Text` | subtitle text |
| +0x25b8 | widget | `blackDesktop` of the layout |
| +0x2840 | u8 | info-map overlay state saved at `OnShow` |
| +0x2841 | u8 | speakers preloaded |

### 2.7 Input state and user settings

- `nMenu::Game` (the in-game screen; its `nUi::Event` face is at +0x28) [known, S 005eab40..S 005eaba0,
  S 005ec340]: +0x3a u8 right mouse button held, +0x3b u8 middle mouse button held, +0xffe0 u8 Shift held (team
  chat), +0xffe8 `nGame::System*`.
- `UserProfile` (singleton, `settings.cfg`, layout in [formats-inventory.md](formats-inventory.md) §3.11), the
  fields this subsystem reads [known for the reads; defaults from S 00579c00]:

| Offset | Type | Default | Read by | Effect |
|---|---|---|---|---|
| +0x24 | f32 | 1.0 | cinematic, cheats | local game speed ([logic-core.md](logic-core.md) §3.1) |
| +0x28 | u8 | 0 | S 00786e70 | inverts the middle-button drag direction ("invertScrolling") |
| +0x2c | f32 | 0.25 | S 00786e70, S 00787310 | scroll speed `s`; enters squared (§3.2) |
| +0x30 | u8 | 1 | S 00786e70 | screen-edge scrolling on ("borderScrolling") |
| +0x31 | u8 | 1 (S 00579c00) | `nMenu::MessageBox2::Show` S 0062c0d0 (warp to its first button, S 00492850); `ActionButtonPanel::PositionAtCursor` S 005f0880; its mirror S 0087b808 by `CenterCursor` S 004a0f30 (Lua `centerCursor`, the splash screen) | "smart cursor" (`menuoptions.xml` `cSmartCursor`, `!SMART CURSOR`): warp the mouse to the centre of a message box's first button, and of the focused action button when the action panel opens ([ingame-ui.md](ingame-ui.md) §3.7) |
| +0x33 | u8 | 0 | S 00787310 | inverts the vertical mouse axis of the look-around mode |

### 2.8 Screenshot state [known: S 0067ea50, S 006833a0, S 004ddc50]

`S2CG::Scene`: +0x711 u8 screenshot requested, +0x714 i32 tiles per side (1..8, 1 = plain screenshot), +0x71c f32
on-screen message timer (3.0 s after a change of the tile count). `S2CE::ScreenshotTool` (0x30 bytes): +0x00 D3D
device, +0x04 capture surface, +0x08 render target, +0x0c tiles per side, +0x10 tile rectangle table (16 bytes
per tile: left, top, right, bottom), +0x14 series base name (`std::string`). A global series counter follows the
base name (§3.11).

### 2.9 CVar server [known: S 0067c6d0, S 0067e690, S 0067cc10]

`ai::debug::CVarRemoteServer` (0x760 bytes): listen socket, worker thread, 8 client slots of 0x20 bytes, a map
group name → variables, a critical section. Created only when the byte `g_bCVarServerEnabled` (S 0088ca50) is
non-zero; port from the u16 at S 008810bc (1234 in the file, [../BINARY_PATCHES.md](../BINARY_PATCHES.md)).
A `CVar` binds a group name, a variable name and a pointer to a bool, int or float with optional minimum,
maximum and step (constructors S 005c6270, S 005c6370, S 005c64a0).

---

## 3. Rules and algorithms

### 3.1 Camera life cycle and common per-frame step

- **Construction** (S 007876e0) [known]: `zoomMax = 4.0`, `cachedFocusHeight = −1.0`, `isActive = 0`, empty key
  map, no follow target, `distanceScale = 70.0`, follow id −1.
- **`Activate`** (S 007868f0, called by `nGame::System::BuildWorld` on every world build, new game or load)
  [known]: registers itself as the device's active camera, `followStyle = 1`, `isActive = 1`, clears the follow
  fields, `distanceScale = 70.0`, then `ResetView(0)`.
- **`ResetView(mode)`** (S 007867c0) [known]: sets `mode`; field of view `50°`; near 1.0, far 500.0;
  `lookDirTarget = moveDir = lookDir = (0, −1, 1)` (not normalised here); `focusPoint = eyePos = desiredEye =
  (0, 10, −10)`; `zoomTarget = zoomCurrent = 3.0`; both yaw offsets 0; then `FocusOnLocalPlayerBuilding` and the
  mouse cursor is shown.
- **`FocusOnLocalPlayerBuilding`** (S 007860e0) [known]: when the player table has an active human player, takes
  the first completed building of the local player in the village system's building list +0x20
  (`NVillage::System::FindCompletedBuildingOfPlayerInList20` S 00558730: first entry whose owner is the player
  and whose two progress floats at `building + 0x44 → +0x70 / +0x74` are both ≤ 0) and calls `FocusOnCell` with
  its cell (+0x20, +0x24). List +0x20 is the village system's list of buildings whose type has `depot`
  (headquarters, storehouses and the other storage types; [village-buildings.md](village-buildings.md) §2.2), so
  the target is the player's first finished storage building in that list's order: the headquarters as long as
  it stands and was entered first [inferred: the list's insertion order was not read here].
- **`FocusOnCell(cell)`** S 00785fe0 / **`FocusOnVertex(vertex)`** S 00786060 [known]: `focusPoint` = world
  position of the cell or vertex with **z − 18.0**; both yaw offsets 0; `moveDir = normalize(0, −1, 1)`; then one
  `UpdateStandardView(false, 0.3)`.
- **Projection** [known, S 004d9300, S 006e97e0]: `fov` from slot 4, aspect = viewport width / height, near and
  far from slot 5. The engine's `Matrix44::PerspectiveFovLH(fov, aspect, near, far)` S 006e97e0 is not the D3DX
  function: it sets the X scale to `1 / tan(fov / 2)` and the Y scale to `aspect / tan(fov / 2)`, so `fov` is the
  **horizontal** field of view (50° at every aspect ratio) and the vertical one follows as
  `2 × atan(tan(25°) × height / width)` (38.6° at 4:3, 29.4° at 16:9). The device adds its own near offset
  `CGraphicDevice + 0x518` to the near plane; `SetNearPlaneOffset` S 004d9e10 is its only writer and is called
  by the map renderer, the street renderer and the overview-texture render (S 006898f0, S 006c3ab0, S 00680d90),
  which use it as a depth bias for decals and streets and put it back to 0 [inferred for the values passed], so
  the camera's near plane is 1.0 for everything else. The streets' offset of 0.1 makes their near plane 1.1,
  which depth-tests a point at view depth `d` like one at `d / 1.1`: a pull of about 9 % of the depth, not of
  0.1 units ([world-objects-rendering.md](world-objects-rendering.md) §3.8). Slot 5 doubles the far plane while
  `nMenu::System.uiSuppressed` is set; no write of that byte other than the constructor's 0 was found (§3.13),
  so the far plane is 500 in the shipped game [inferred].
- **Every frame**, `Camera::Update` S 00787530 [known]: `isUpdating = 1`; zoom easing
  `step = (zoomTarget − zoomCurrent) × dt × 3.0`, limited so that it never passes the target, `zoomCurrent +=
  step` (time based: a zoom step is within 5 % of its target after 0.95 to 0.99 s at 45 to 107 frames per
  second, and `zoomCurrent` approaches the target without reaching it) [known: live 2026-10-12, twelve steps]; then the handler of the current mode (§2.2).

### 3.2 Standard mode (mode 0)

`UpdateStandardMode` S 00786e70, in this order [known]:

1. `slowLookSmoothing = 1`.
2. Scroll step `v = (5 s)² × min(25 dt, 1.0)` with `s = UserProfile + 0x2c`. `MoveForward` and `Strafe` move
   the focus point by **twice** the distance passed, so one frame of scrolling moves `2 v` world units (default
   `s = 0.25`: 78.1 units per second at frame rates of 25 Hz and above, 3.125 units per frame below).
3. **Edge scrolling**, only when `UserProfile + 0x30` is 1 and the game window is the foreground window: with the
   mouse position in pixels, `x ≤ 1` → strafe left by `v`; `x ≥ screenWidth − 1` → strafe right; `y ≤ 1` →
   move forward; `y ≥ screenHeight − 1` → move backward. The four tests are independent, corners scroll diagonally.
4. **Arrow keys** (held keys of the key map): Up → forward `v`, Down → backward, Left → strafe left, Right →
   strafe right.
5. **Middle-button drag** (`Game + 0x3b` set): the mouse cursor is hidden; with the mouse movement of this frame
   `(dx, dy)` in screen fractions and `k = (10 s)²`: when `invertScrolling` is 0, `MoveForward(−dy × k × 40)`
   and `Strafe(dx × k × 40)`; when it is 1 both signs are swapped. Nothing moves when the movement is zero.
   Afterwards the mouse is put back to its position of the previous frame, clamped to 0.01..0.99 on both axes
   (`RestorePreviousPositionClamped` S 00492880), so the pointer stays in place while dragging. When the button
   is not held the mouse cursor is shown.
6. **Right button held** (`Game + 0x3a` set, and `uiSuppressed` clear): switch to look-around mode:
   `savedLookDir = lookDirTarget`, `lookDirTarget = moveDir`, `mode = 1`; the frame ends here.
7. Otherwise `UpdateStandardView(false, 0.3)`.

Movement primitives [known]:

- `MoveForward(d, flatten, fromEye)` S 00785460: direction = `moveDir`, with y set to 0 when `flatten`,
  normalised; new position = base + direction × `2 d`, base = `eyePos` when `fromEye`, else `focusPoint`; the
  result goes through `SetFocusPointClamped`; when `fromEye`, `eyePos = focusPoint` afterwards.
- `Strafe(d, fromEye)` S 00785530: with `f = normalize(moveDir.x, 0, moveDir.z)`, the offset is
  `(2 d × f.z, 0, −2 d × f.x)`; same base and clamp rule. Positive `d` is "right" for a view along +z.
- `MoveVertical(d)` S 00785b90: `focusPoint.y += 2 d` through the clamp.
- `SetFocusPointClamped(p)` S 007851c0: the nearest terrain vertex `(vx, vy)` of `p` is looked up
  (`TerrainGrid::FindNearestVertex`). x is accepted when `0 < vx < vertexWidth − 1`, z when
  `0 < vy < vertexHeight − 1`; y is accepted when either is. A rejected axis keeps its old value, so the focus
  point slides along the map border and never reaches the outermost vertex row or column.

`UpdateStandardView(keepOrientation, eyeLerp)` S 00785c10 [known; constants read at S 00835258..S 00835264,
S 007e7820, S 007ea340, S 007d4a80, S 007e2ac8, S 007fa8d8]:

1. **Focus height.** Sample the terrain height (`Camera_SampleTerrainHeight` S 007852b0: 0 outside the map
   interior) at the focus point and at ±10 in x and ±10 in z; `h = mean of the five`. With `w` = the terrain
   grid's water level in world units (`TerrainGrid + 8` × height scale, S 00687050; "minHeight = water level" in
   [../map-format.md](../map-format.md)): `h = max(h, w + 5) + 5`. If `cachedFocusHeight < 0` or
   `|cachedFocusHeight − h| ≥ 10`, the cache takes `h`; otherwise the cached value stays. `focusPoint.y =
   cachedFocusHeight`. The focus height therefore changes in jumps, only when the smoothed terrain is 10 or more
   units away from the last value.
2. **Tilt by zoom step**: `lookDirTarget.y = −0.5` when `trunc(zoomTarget)` is
   0, `−0.6` when 1, `−0.8` otherwise; `lookDirTarget` is normalised. Steps 2 to 4 are skipped when
   `keepOrientation` is set; all three callers pass `false`.
3. **Yaw offset**: `yaw += (yawTarget − yaw) × 0.245` (per frame, no `dt`: within 5 % of the target after 11
   frames, 0.22 s at 50 frames per second) [known: live 2026-10-12]. `moveDir = lookDirTarget` rotated
   about the Y axis by `yaw` radians: `x' = x cos − z sin`, `z' = z cos + x sin`, y unchanged; normalised.
4. **Direction smoothing**: `lookDir += (moveDir − lookDir) × f`, `f = 0.4` when `slowLookSmoothing` is set, else
   `0.9`; normalised (per frame, no `dt`). The flag is 0 after construction and after a wheel step in standard
   mode (S 00786960, S 00786a10); step 1 of `UpdateStandardMode` sets it on every standard-mode frame. So 0.9 is
   only used by the direct callers `FocusOnCell` / `FocusOnVertex` when they run before the next standard-mode
   frame: on the first world build and right after a wheel step [inferred].
5. **Eye**: `d = normalize(dir.x, 1.4 × dir.y, dir.z)` with `dir = lookDir` (`moveDir` when `keepOrientation`);
   `eye = focusPoint − d × (zoomCurrent × 0.3 × distanceScale)` (`ComputeEyeFromFocus` S 00785040; 21 world
   units per zoom unit with the default scale). Then only the **z** component is blended with the previous
   frame: `eye.z = eye.z + (oldEye.z − eye.z) × eyeLerp`.
6. **Ground clearance**: `m = max(terrain(eye) + 10, w + 5)`; if `eye.y < m`, `eye.y = m`.

The renderer looks from `eyePos` along `lookDir`, which is flatter than the offset direction `d` (factor 1.4 on
y), so the focus point lies below the screen centre [inferred from steps 4 and 5].

**Zoom** [known, S 00786960, S 00786a10]: one wheel message forward lowers `zoomTarget` by 1.0 while it is above
0; one backward raises it by 1.0 while it is below `zoomMax` (4.0). The number of notches in the message is not
used (`nMenu::Game::OnMouseWheel` S 005eb140 looks at the sign only). Start value 3.0. Eye distances at rest:
21 world units per step, 0, 21, 42, 63, 84 for the steps 0..4 [known: live 2026-10-12, measured as 0, 21, ...
126 for the steps 0..6 of an install whose `zoomMax` is 6.0, §2.1].

**Rotation** [known, S 00787790]: Delete (0x2e) sets the yaw target to +1.5, or to 0 when it is −1.5; Insert
(0x2d) sets it to −1.5, or to 0 when it is +1.5. The view therefore has three positions (about ±86° and
straight). Both keys are ignored while a text input has the focus. The handler does not test the camera mode;
the yaw offset is only applied by `UpdateStandardView`.

### 3.3 Look-around mode (mode 1)

`UpdateLookAroundMode` S 00787310 [known]:

1. If `uiSuppressed` is clear, `isUpdating` is set and the right button is no longer held: `mode = 0`,
   `lookDirTarget = savedLookDir`, mouse cursor shown; the frame ends here.
2. Steps 2 to 5 run only when `25 dt ≤ 6.25` (`dt ≤ 0.25 s`); a longer frame does nothing. Step
   `v = (5 s)² × 25 dt` (no cap); arrow keys as in standard mode
   but with `fromEye = true` (the eye itself moves over the ground; the focus point follows it).
3. The mouse cursor is hidden; with the mouse movement `(dx, dy)` of this frame, `dy` negated when
   `UserProfile + 0x33` is set: `RotateLook(dx, dy)`.
4. `lookDir = moveDir = lookDirTarget` (no smoothing); the mouse is put back as in §3.2 step 5.
5. `eye.y` is raised to `max(terrain(eye), w + 5)` when below.

`RotateLook(yaw, pitch)` S 00785350 [known; constants S 007e2508 = 10.0, S 007e2210 = −1.0, S 007fa778 = 0.6]:
angle `a = −10 × yaw` radians; `x' = x cos a − z sin a`, `z' = z cos a + x sin a` on `lookDirTarget`;
`y' = clamp(y + 6 × pitch, −0.9, +0.9)`; the vector is normalised and stored. A mouse movement of the full screen
width turns the view by 10 radians.

### 3.4 Free-fly mode (mode 2)

`UpdateFreeFlyMode` S 00786ae0 [known]. Base step `v = 15 dt`, factor `f = 0.2`, or `1.0` while Shift is held.

- Left / Right: `Strafe(∓ v f)` from the focus point.
- Up / Down: `focusPoint ± normalize(moveDir) × 2 v f` (not flattened: the camera flies along its view
  direction), through `SetFocusPointClamped`.
- Mouse look: only while the middle button is held (the alternative condition needs `uiSuppressed`):
  `RotateLook(2 f × dx, 2 f × dy)`.
- Wheel forward: `MoveVertical(−10 dt)` (× 5 with Shift), wheel backward: the same upward (S 00786960,
  S 00786a10).
- Every frame: `eyePos = desiredEye = focusPoint`, `lookDir = moveDir = lookDirTarget`. There is no terrain or
  water clearance in this mode; only the map border test of `SetFocusPointClamped` applies.

### 3.5 Jumps

- `'h'` (character 0x68, `nMenu::Game::OnChar` S 005eb180) [known]: in mode 0, `FocusOnLocalPlayerBuilding`.
- Minimap press and drag: `nMenu::MiniMap::FocusCameraOnCursor` S 005f1520 (called from the minimap's mouse
  press and mouse move handlers S 005f18e0, S 005f2130) converts the mouse position inside the minimap to a
  vertex (`y = vertexHeight − v`), clamps it to `0 .. vertexWidth − 1` and `0 .. vertexHeight − 1`, and calls
  `FocusOnVertex` S 00786060 [known; the exact scaling is in [hud-panels.md](hud-panels.md) §3.7 "Input"]. The press
  and every move while button 0 is held (and the middle button is not) call it, so a drag refocuses on each move.
- Selection: `MenuSelection::RefreshFromGameSelection(.., focusCell = 1)` S 00617800 calls `FocusOnCell` with
  the controller's `hoveredCellX/Y`; it is called with `focusCell = 1` by `nMenu::Game::OnButtonClick` S 005eb850
  (the back / forward buttons that cycle through buildings of the same type [inferred: that function was not
  re-read]) and by `nMenu::StatsBuilding::OnButtonClick` S 00643a90, which first copies the selection's map
  position into `hoveredCellX/Y`. `MenuSelection::Update` S 006163f0 calls `FocusOnCell(hoveredCell)` on every
  frame in which a byte at +0x19 of one of its sub-objects is set and the cell is inside the map [known for the
  calls; [TODO] not established: what sets that byte].
- Message list: `nMenu::Messages::Update` S 005f86a0 leaves a non-standard camera mode first
  (`ResetToStandardMode` when `mode ≠ 0`) and then calls `FocusOnCell` with the message's cell [known].
- "Go to" by id: `nMenu_FocusCameraOnUnique(id)` S 00648de0 (only caller `nMenu::GoodButton::OnClicked`
  S 0062fe50) [known]: when the id has a map-object render instance, the camera is first placed with
  `SetEyePosition` S 00784f10 (`desiredEye` and the eye, or the focus point in free-fly mode, set to the
  object's position; `lookDir = lookDirTarget`). The id is looked up in the package system (S 00573720 on
  `NTransport::System +8`), not among the fights: a package on a flag gives the flag's cell; a package with a carrier
  the carrier's movement cell; a package in a ship the ship's cell. Otherwise the id is a settler
  (`FindSettlerByUnique` S 006546b0): aboard a ship (S 005b9d00) it gives the ship's cell, else the settler's own cell.
  An unknown id, or a cell outside the map, finds nothing. If a cell inside the map was found,
  `FocusOnCell(cell)` (S 00785fe0), and the action panel is closed again unless it waits for a confirmation.
- `ResetToStandardMode` S 00784eb0 [known]: `mode = 0`, `lookDirTarget = (0, −1, 1)`, `hasTargetPos = 0`,
  `cachedFocusHeight = −1`, mouse cursor shown. `focusPoint` is not touched: after a cutscene or the screensaver
  the standard view returns to where it was.

### 3.6 Screensaver mode (mode 3)

`UpdateCinematicMode` S 00786140 [known for the body; reachability open, §2.2]. All random draws use the C
library `rand()` (S 006f41e2), never the simulation generator. "Start orbit" below means: clear settler, follow
target and target position, `cinematicState = 1`, `orbitSign = +1 if rand() % 100 > 50 else −1`,
`orbitRandom = (rand() % 200) / 200`.

Each frame the mouse cursor is hidden and `cinematicTimer −= dt`. When it falls below 0: follow target and
target position are cleared; from state 0 → state 1 with `timer = rand() % 5 + 5` s and a new orbit sign and
random; from any other state → state 0 with `timer = rand() % 15 + 20` s. Then, by state:

- **1 orbit**: `eye.y += 0.84 dt`; `lookDir` is rotated about Y by `0.07 × dt × orbitSign` radians and
  normalised.
- **2 fly away**: `eye −= lookDir × 1.75 dt`; `eye.y += dt`. Without a settler: start orbit with `timer = 2`.
  Otherwise `lookDir += ((target − eye) − lookDir) × 0.025`, normalised (`target` = the followed character's
  position).
- **0 follow**:
  1. Without a follow target: `NSettlers::System::PickRandomCinematicTarget(previous settler)` (weights in
     [settlers-jobs.md](settlers-jobs.md) §4); none → start orbit with `timer = 7`; else take the settler's
     render character as follow target and remember its id; the frame ends.
  2. If the remembered id no longer resolves to a settler: start orbit with `timer = 2`.
  3. `UpdateFollowTargetView` (below).
  4. If the settler's movement is not busy (`ai::settlers::SettlerMovement::IsBusy` false), it is a Worker (settler type 0)
     and it stands on its workplace's work cell (`Worker::IsAtWorkplaceWorkCell`): with `rand() % 100 ≤ 50`
     switch to state 2 (`flyAwayOrigin = eye + lookDir`, `timer = rand() % 35 + 10` s), else start orbit with
     `timer = 7`.
  5. Otherwise, if the settler is no longer in one of the "cinematic" job states
     (`NSettlers::Settler::IsInCinematicState`) and `timer < 3`: start orbit with `timer = 7`.

`UpdateFollowTargetView` S 00785610 [known for the arithmetic; the meaning of the three vectors of the render
character's anchor object is inferred from their use]: `T` = anchor position (+0x30), `O` = anchor offset (+0x00),
`D` = anchor direction (+0x20). `targetPos = T`, `hasTargetPos = 1`.

- If a building is found at or nearest to the settler's cell (`NVillage::System::FindBuildingAtOrNearest`):
  `P` = world position of the building's cell stepped once in map direction 1; `E = P + (0, 1.15, 0)`;
  `lookDirTarget = normalize((T + (0, 1.1, 0)) − E)`; `desiredEye = E − 3 × lookDirTarget + O`;
  `eye += (desiredEye − eye) × 0.05`; `lookDir += (lookDirTarget − lookDir) × 0.05`; done.
- Otherwise (`followStyle` is always 1): `desiredEye = T − 4 D + O + (0, 2, 0)`;
  `lookDirTarget = normalize((T + (0, 2, 0)) − desiredEye)`; the same two 0.05 blends; then
  `eye.y = max(eye.y, max(terrain(eye) + 1, w + 3))`. (For `followStyle ≠ 1` the code uses `T + 5 D` and a
  target height of 1.25.)

Leaving the mode [known]: any wheel message (S 00786960, S 00786a10) or Escape (S 00787790) calls the
`ResetToStandardMode` sequence. While the mode is 3 the in-game screen draws no HUD and skips its click handling
and hover tooltip (`nMenu::Game::Draw` S 005efdd0, `Update` S 005efea0).

### 3.7 Cutscene camera and script files

**Script file** [known: data, S 0078ac10]. A cutscene is a Lua file made of calls to the `cutscene` table,
executed once in a temporary Lua thread; the table is registered on that thread for each load:

| Call | Effect |
|---|---|
| `cutscene.addPosition(dt, x, y, z)` | S 0078a5b0: adds a key to the position track at time `span + dt`, where `span` = (time of the last key − time of the first key) of that track, 0 when empty |
| `cutscene.addLookAt(dt, x, y, z)` | S 0078a660: the same on the look track, which keeps its own times |
| `cutscene.setRelative()` | S 0078a640: sets `CameraSpline + 0x41`. No reader of that byte was found: the call has no effect of its own [inferred] |
| `cutscene.createLoopAtEnd()` | S 0078a6f0: `CameraSpline::SetLoop(true)` (below) |

Units: time in **seconds** (the spline is advanced with the frame time, S 0078a8a0), positions in world units.
The look key is a **view direction**, not a point: after sampling, the vector is copied to `Camera.lookDir` and
normalised (S 0078a840, S 0078a8a0); in the shipped files the look keys are unit vectors (1161 of 1162 within
0.001 of length 1), for example `(0, −0.624695, 0.780869)`, the standard view direction of §3.2 for the tilt
−0.8 [known: data].
A key whose time already exists in the track is dropped (`std::map` insert, S 0078cf90). In the install: 187
files, 1162 position keys and as many look keys, 3..18 keys per track, the first `dt` of every track is 0, both
tracks of a file have equal length, path durations 9..230 s, 40 files call `setRelative`, one calls
`createLoopAtEnd` (`scripts/mapTools/cutscene_circle.lua`) [known: data].

**File name** [known, S 0078a940, S 005fb3e0]. A page gives a cutscene name and optionally an anchor cell.
- Without a cell (`x = −1`): the file is `<map directory><map name>_<cutscene name>.lua`, e.g.
  `maps\campaignMaps\C01_1intro.lua` for map `C01`, cutscene `1intro`. When the map directory starts with `[`,
  its first 7 characters (the length of `[data]\`) are removed and the rest goes through the file system's
  path resolver (`FileScanHolder::ResolvePath`; its file-name lookup is described two items below).
- With a cell: the name is used as a **full path** (the shipped scripts pass
  `[data]\maps\campaignMaps\C02_12smallBUILD.lua`), and every position key is shifted by the cell's flat world
  position `(x, 0, z)` (`TerrainGrid::CellToWorldPosFlat` S 00687190, `CameraSpline::OffsetPositions`
  S 0078d4a0). Look keys are not shifted. These are the files that call `setRelative`: their positions are small
  offsets around the anchor, their heights are absolute.
- Six places in the shipped campaign scripts name `[data]\scripts\campaignMaps\C..._....lua` (three files:
  `C02_11bigBUILD`, `C03_5miliFokus`, `C03_7enemyHQs`; in `C01.lua`, `C03.lua` and `C05.lua`), a folder that
  does not exist in the install [known: data]. They load all the same: every file read goes through
  `NBase::gReadFileData` S 006e6d40 → `FileScanHolder::ResolvePath` S 006e3fd0 → `FileScan::ResolvePath`
  S 006ef8a0, which looks a file up **by its lower-cased name alone** in the index built at start-up and, when
  exactly one file of that name exists, returns that file's real directory whatever directory was asked for
  [known]; the three files exist once each, in `maps\campaignMaps\` [known: data]. A converter must resolve
  script and cutscene paths the same way: by file name, case-insensitive. Several files of one name
  (S 006ef8a0, `FileScan::PickCandidateByParentDir` S 006ef680) [known]: if the request contains a `\`, the
  first directory of the name's index list whose last component (lower-cased, with its `\`) occurs anywhere
  in the lower-cased request wins (a plain substring test, so `maps\` also matches `...\campaignmaps\...`;
  only one component is ever compared); no candidate matches, or the request has no directory, → the empty
  path, which then fails like a missing file (next item). A name that is not in the index gives the empty
  path as well. The order of a name's list is the order of the start-up scan [inferred]
  ([../data-loading.md](../data-loading.md)).
- A file that really is missing: `gReadFileData` logs `Can't open file: %s` and returns a null buffer with size
  0; `File_ReadAndDecrypt` S 006e7770 then calls `NBase::gDecryptData` S 006e6660, which reads the header at
  buffer + 4 without a null test [known], so the game faults [inferred]. `LuaScriptHost::RunFile` S 005c9690
  itself has no missing-file branch.
- A script that adds no key leaves both tracks empty; sampling then leaves the spline's current position and
  look vector as they are, and the constructor does not initialise them, so the pose copied to the camera at
  start is undefined; the first `ai::camera::CutsceneCamera::Tick` finds `time ≥ span = 0`, stops the spline and returns the
  camera to standard mode [inferred from S 0078d6f0, S 0078d2b0, S 0078d190].

**Loading** (`CutsceneCamera::LoadScript` S 0078ac10) [known]: the old spline is destroyed, a new empty one is
created (`loaded = 1`), the file is run, the thread is destroyed. The Lua callbacks reach the spline through the
active game screen: `nGame::System + 0x630 → +4`. **Start** (`ai::camera::CutsceneCamera::Start` S 0078a840) [known]:
the spline gets `playing = 1`, `time = 0`, `paused = 0` (S 0078d170), the camera gets `mode = 5`,
`hasTargetPos = 0` and the mouse cursor is hidden (S 00784e90), the spline is sampled at `t = 0` and the pose is
copied. `CutsceneCamera::Play(name)` S 0078aeb0 is load then start; `PlayAtOffset` S 0078aed0 is load,
`OffsetPositions`, start.

**Tangents** (`CameraSpline_KeyMap_RecomputeTangents` S 0078c870, after every added key) [known]: for keys
`p0 .. pn` of one track, the out-tangent of `pi` is `p(i+1) − pi`; the in-tangent of a middle key `pi` is also
`p(i+1) − pi`; the in-tangent of the last key is `pn − p(n−1)`; the first in-tangent and the last out-tangent are
the "none" marker. (`CameraSpline_ComputeTangent` S 0078c4b0 returns the plain difference, `(1, 0, 0)` for
identical points.)

**Sampling** (`CameraSpline_SampleTrack` S 0078d2b0) [known]: find the last key with time ≤ `t`; none → the
output keeps its previous value; if its out-tangent is the marker (last key) → its value; else
`D3DXVec3Hermite(p_i, outTangent_i, p_(i+1), inTangent_(i+1), u)` with `u = (t − t_i) / (t_(i+1) − t_i)`.
The tangents are not scaled by the segment duration.

**Advance** (`CameraSpline::Update(dt)` S 0078d420) [known]: when playing and not paused, `time += dt`; while
`time > loopEndTime`, `time −= loopLength`; then both tracks are sampled (also when not playing). Per frame,
`ai::camera::CutsceneCamera::Tick` S 0078a8a0 (from `nGame::System::Update`; only while a spline exists and is playing) does
this with the frame time, copies position → `Camera.eyePos` and look vector → `Camera.lookDir`
(normalised), and when `time ≥ span of the position track` (S 0078d190) clears `playing` and calls
`Camera::ResetToStandardMode`. The cutscene pose bypasses all terrain, water and border rules.

**Loop** (`CameraSpline::SetLoop(true)` S 0078d1c0, `CameraSpline_KeyMap_AppendLoopSegment` S 0078d030) [known]:
the loop flag +0x40 is set; the rest runs only while `uiSuppressed` is clear (§3.13: always).
`loopEndTime` = position span; to each track two keys are appended, repeating the second-to-last and then the
last key value, at `span + d` each (span re-read after the first append), `d` = time of the last key − time of
the second-to-last key of that track; `loopEndTime += d` and `loopLength = 2 d` with the position track's `d`.
Playback then repeats the stretch `[span − d, span + d]` and the "finished" test never
holds, because the position span grew by `2 d`. The call must come after the keys: on a track with fewer than
two keys the function reads past the track [inferred: no size test before the two iterator steps].

### 3.8 The cinematic screen

**Start** [known]. A map script calls `menu.startCinematic()` (S 005dd3c0: closes all dialogs, opens the screen
unless it is open), then `menu.addCinematicPage(textKey, titleKey, cutscene [, x, y])` per page (S 005dd410:
`x, y` are read only when argument 4 is a number, else −1, −1; `AddPage` S 005fc110 appends to the four vectors),
then `menu.updateCinematic()`. The shipped caller is `quest_setupCinematic` in `scripts/mapTools/quests.lua`: a
briefing text key without text but with `_1`, `_2`, ... variants is expanded to one page per variant (up to 20),
and only the first of them keeps the cutscene name [known: data].

**`OnShow`** (S 005fbd30) [known]: title = map name; `timer = 1.0`; the local game speed is saved (+0xc14);
`nGame::System::BeginCinematic` (below); page index, page count and the four page vectors cleared; the screen's
layout file is reloaded (`menucinematic.xml` [inferred: the name is a string member, the file exists in
`ui/layout`]); if the simulation clock (`NLogic::System.nextTickTime`) is at least 2.0 the HUD is faded out
and the black desktop (+0x25b8) faded in over 1.0 s and `timer = 1.5`; otherwise the HUD is hidden at once
and `timer = 0`. `phase = 0`. The speaker
panel gets the map name and `<map name>_sub`; the info-map overlay state is saved; `Cursor.bActive = 0`.

**`BeginCinematic`** S 00782b60 / **`EndCinematic`** S 00782bb0 [known]: on begin, the AI system's enabled byte
is saved (`nGame::System + 0x634`) and cleared, the chest system's enabled byte is cleared, the simulation flag
`NLogic::System + 0xec` (`cinematicActive`) and `nGame::System + 0x635` are set, and the sacrifice system is
paused (`NSacrifice::System::PauseForCinematic` S 0065f550: paused byte and the pause start tick). On end the
saved AI byte is restored, the chest system is enabled again (`LogicChestSystem::Enable`), both flags are
cleared and `ResumeAfterCinematic` S 0065f610 clears the paused byte and shifts the start ticks of all 8
players' sacrifice data by the number of ticks the pause lasted. The simulation itself keeps ticking during a
cinematic; what
the flag stops is listed in [logic-core.md](logic-core.md) §2 (+0xec), [military.md](military.md) §4,
[ai-player.md](ai-player.md) §4 and [game-commands.md](game-commands.md) §3.4. The autosave timer does not run
while `+0x635` is set (S 00780d20).

**Per frame** (`Cinematic::Update` S 005fb3e0) [known]: `timer −= dt`, then by phase:

| Phase | While `timer ≥ 0` | When `timer < 0` |
|---|---|---|
| 0 fade in | local game speed = `timer × (saved − 1) + 1` | music track 1; sound ducking on; info-map overlay faded out; game speed 1.0; fog-of-war overlay off; if the simulation clock ≥ 2.0: `timer = 1.0`, panel faded in, black desktop faded out, else panel shown at once; → phase 1 and the page step below in the same frame |
| 1 playing | `delay −= dt`; once `delay < 0` and a voice-over is playing, `timer = −1` | page step |
| 4 ending | — | overlay state restored; fog-of-war overlay on; voice stopped; cutscene camera stopped (`ResetToStandardMode` if it was playing); `EndCinematic`; `timer = 0.5`; → 2 |
| 2 restore HUD | — | HUD faded in and black desktop faded out over 1.0 s; music stopped; ducking off; `timer = 1.0`; → 3 |
| 3 restore speed | local game speed = `saved − (saved − 1) × timer` | all dialogs closed, which runs `OnHide` |

**Page step** (phase 1, `timer < 0`) [known]: speaker portraits are preloaded once. If a voice-over is still
playing, wait. If pages remain:
1. If the page's cutscene name is not empty: `CutsceneCamera::Play(name)` when the anchor cell x is −1, else
   `PlayAtOffset(name as full path, flat world position of the cell)` (§3.7). An empty name leaves the running
   path alone.
2. Caption = the page's title key.
3. The text is the localised string of the text key. Leading **speaker tags** `[Name:N]` are stripped
   (`Cinematic_ParseSpeakerTag` S 005faf50: name up to `:`, one digit, `]`); the first tag fills speaker slot 0,
   a second one slot 1; flag = `N == 1`. A text that does not start with `[` clears the slot. Example from
   `language/de/briefings.txt`: `[McDoyle:0][Moped:1]McDoyle, Garibald ist zurück!`; the title key
   `<textKey>_title` holds the speaker's display name [known: data]. [inferred] the flag marks the slot that is
   speaking; `SetSpeaker` S 0062d7b0 was not read.
4. The remaining text becomes the **subtitle** (`nUi::Text` +0x24d8); `Menu_PlayVoiceOver(textKey)` starts the
   voice file of the same key ([audio.md](audio.md) §3.8).
5. `page index += 1`; `timer = 0.1 s × length of the subtitle text in bytes`; `delay = 0.5`.

So a page lasts until its voice-over ends (at least 0.5 s), or `0.1 s` per character when no voice plays. When
no page remains: `BeginEnding` S 005fb040 (both speaker slots cleared, panel faded out and black desktop faded in
over 1.0 s, `timer = 1.0`, phase 4).

**Keys while the screen is open** (`Cinematic::OnKeyDown` S 005fae80; phase 1 only) [known]: Space (0x20) calls
slot 12 of the screen's event face (`OnAdvanceInput` S 005fae40): once `delay < 0`, `timer = 0` and the
voice-over is stopped, so the next frame shows the next page; Escape (0x1b) calls slot 15 (`SkipCinematic`
S 005fb3b0): voice-over stopped and `BeginEnding`. Every other key is swallowed, in every phase. Slots 12 and
15 are the left-press and right-press handlers of an event face (§3.9), so a left click advances like Space
and a right click ends the cinematic like Escape [inferred: slot roles read from `nMenu::Game`'s face].

**`OnHide`** (S 005faee0) [known]: `Cursor.bActive = 1`; overlay state restored; panel and black desktop hidden;
the map script's `quest_cinematicDone()` is called (`GameScript_CallQuestCinematicDone` S 005b2360); the local
game speed is set back to the saved value.

The pause key does nothing while the cinematic screen is open (`nMenu::System::TogglePause` S 005da400) [known].

### 3.9 From window message to handler

`CApplicationEx::HandleWindowMessage` S 00401f30 [known]. Input is ignored while the window is inactive or
minimised or the device is lost. The graphics device sees every message first. Then:

| Message | UI event (type, arg) | Notes |
|---|---|---|
| `WM_MOUSEMOVE` | 3 (x, y) | updates `nUi::Cursor` from pixels |
| `WM_L/R/MBUTTONDOWN` | 0, button 0 / 1 / 2 | the cursor position is set from the message first; the UI's result is discarded and the active `nUi::GameAction` map always receives the button (e.g. `WM_RBUTTONDOWN` 0x204: vtable +0x18 (2, 1) → `BaseAction::OnKeyEvent` S 00490f50 sets `keyState[VK_RBUTTON]`), so a press on a widget still reaches the action map [known] |
| `WM_L/R/MBUTTONUP` | 2, button | |
| `WM_L/R/MBUTTONDBLCLK` | 1, button | |
| `WM_XBUTTONDOWN/UP` | 0 / 2, button 3 or 4 | `WM_XBUTTONDBLCLK` is handled like the up message |
| `WM_MOUSEWHEEL` | 4 (delta / 120) | |
| `WM_KEYDOWN` / `WM_KEYUP` | 5 / 6 (virtual key) | if the UI does not consume it, the key goes to the scene's key handler (`S2CG::Scene::HandleKey` S 0067ea50, §3.11) with flag 0 for down and 1 for up (S 00401e50, S 00401ea0) |
| `WM_CHAR` | 7 (character), then 8 if unhandled | |

`nUi::Root::HandleInputEvent` S 004913f0 [known]: events 0..4 go to the input-capturing widget when one is set,
otherwise through the widget tree; unhandled key events 5 / 6 go to the active `nUi::GameAction` map; an
unhandled character event 7 is dispatched again as event 8. `nUi::Event::DispatchEvent` S 004ab060 maps the
event type to a virtual slot of the receiving widget's event face [known]: 0 → slot 9 (mouse down), 2 → slot 10
(up), 1 → slot 11 (double click), 3 → slot 27, 4 → slot 28 (wheel), 5 → slot 29 (key down), 6 → slot 30 (key
up), 7 → slot 31 (character), 8 → slot 32 (**hotkey**).

The in-game screen `nMenu::Game` (event face vftable S 007eec1c) [known]:

| Input | Handler | Behaviour |
|---|---|---|
| left press | `OnMouseButton0Down` S 005eaae0 | swallowed while the network game hangs; else widget default, then `Cursor::SelectAtCursor` and `MenuSelection::HandleClick` (§3.10) |
| right press / release | S 005eab40 (`Game::OnMouseButton1Down`) / S 005eab70 (stock `nUi::Event::OnMouseButton1Up`) | the press calls `MenuSelection::HandleRightClick` S 00617bc0 and sets `buttonPressed[1]` (`Game + 0x3a`) in both the consumed and the not-consumed case, and returns the consumed flag; the release clears the flag and returns 0 (look-around) |
| middle press / release | S 005eab80 / S 005eaba0 | `ActionButtonPanel::CloseUnlessConfirming`; `Game + 0x3b` = 1 / 0 (drag); a middle press reaches this handler even when the base dispatch refuses the event (S 005eaaa0) |
| wheel | `OnMouseWheel` S 005eb140 | sign only → `Camera::OnWheelUp` / `OnWheelDown`; never consumed |
| key down | `OnKeyDown` S 005ec340 | Shift sets the team-chat byte; then `Camera::HandleKeyDown`; then Enter (chat, cheats, §3.12) |
| key up | `OnKeyUp` S 005eb230 | Shift clears the team-chat byte; `Camera::HandleKeyUp` |
| character | `OnChar` S 005eb180 | below |

The left click on the world is the PRESS: `nMenu::Game::OnMouseButton0Down` S 005eaae0 (swallowed while `IsGameHanging`)
calls `Cursor::SelectAtCursor` S 00788370 and `MenuSelection::HandleClick` S 00617910. The release is the stock
`nUi::Object::OnMouseButton0Up` S 005f1150 (click latch, focus state, `buttonPressed[0]`), and the Game desktop has no
mouse-move handler (S 0072db80 returns 0), so there is no drag threshold, no selection rectangle and no left-button
scroll (`UpdateStandardMode` S 00786e70). The second press of a double click arrives as `WM_LBUTTONDBLCLK` (event 1) and
reaches Game's slot 14 = S 005eab30, which only sets focus state 2: it clicks nothing [known: decompile]. The remake
clicks on the press with the original camera (`BuildController.LeftClickFires`); with its free camera (left drag pans) on
a release within 4 px of the press [the remake's own].

`OnChar` [known]: every character except `p` is swallowed while the network game hangs. Then the AI debug keys
(§3.13). Then: `h` → camera home (§3.5); `p` → `nMenu::System::TogglePause` (no effect in network modes 1..4,
[logic-core.md](logic-core.md) §3.1); `x` → in network modes 1..4, toggles menu screen 7. Other characters are
not handled and reach the hotkeys.

`Camera::HandleKeyDown` S 00787790 / `HandleKeyUp` S 00787610 [known]: both do nothing while a text input widget
is focused. Key down: Delete / Insert (§3.2); Escape in mode 3 → standard mode; Shift and the four arrow keys
are recorded in the key map (and consumed). Key up removes the key from the map.

**Key bindings** are in three places [known]:
1. hard-coded virtual keys and characters in the handlers above (arrows, Shift, Insert, Delete, Escape, Enter,
   `h`, `p`, `x`, PrintScreen, numpad + and −);
2. the `hotkey` attribute of a widget in the UI layout XML (`nUi::Object::LoadFromXml` S 004a76c0): a value of
   one character is that character's code; a value of exactly two digits is the decimal code (`27` Escape, `13`
   Enter). A widget whose hotkey equals the character of event 8, and which is enabled, visible and has no
   disabled ancestor, is clicked (`nUi::Object::HandleHotkey` S 0049ffc0). Hotkeys are therefore **character
   codes, case-sensitive**, and follow the keyboard layout;
3. nothing is rebindable by the player: no settings file holds keys [inferred: no reader of key bindings was
   found in `UserProfile::LoadSettings`'s field list].

Hotkeys of `data/game/ui/layout/menuingame.xml` [known: data]: `1`..`4` action buttons 1..4, `,` previous and
`.` next building of the same type, space `btInfoMap1` (info-map overlay), `e` `btInfoMap2`, `m` `btInfoMap3`,
`o` options, `q` quest log, `l` in-game settings, `v` speed button, `s` statistics, `t` tutorial, `27` on the
close buttons of info boxes and dialogs.

### 3.10 Map cursor, picking and clicks

**Per frame** (`nGame::Cursor::Update(streetPath)` S 0078a2b0, called from `nGame::System::Render`) [known]: only
when `enabled` (+5) and `bActive` are set. If the mouse cursor is visible: pixel position = `round(size ×
nUi::Cursor fraction)` with the width / height pair the graphics device returns from +0xa8 (back buffer size
[inferred]), stored in the global `ai::render::ScreenPickHelper` (S 0088d488); pick the
**cell** (`ScreenPickHelper::PickCell` S 0068c8d0); if nothing is hit or the cell is outside the map the frame
ends with the old values; then pick the **vertex** (`PickHex` S 0068cc10). If the cursor cell is inside the map:
in placement mode with a street path the slope overlay is drawn, then the cell marker is updated.

**Pick ray** (`CGraphicDevice::BuildPickRay` S 004d9ae0) [known]: origin = the active camera's eye position,
direction = the normalised world direction through the pixel, length 1000.0. Terrain picks
(`CLandscape::PickRayCell` S 0068a0d0, `PickRayHex` S 0068a080) run a broad phase over the bounding boxes of the
currently **visible** terrain cells and a narrow phase on the terrain mesh triangles of the candidates
(`TerrainMesh::PickRayCells` S 006bf520, `PickRayVertices` S 006bfca0; not read further). The pick is against the
rendered terrain surface, not against a flat plane.

**Click selection** (`Cursor::SelectAtCursor` S 00788370, on every left press that reaches the game screen)
[known]. Requires `bActive`. The selection is cleared, then the first match wins:

1. a **flag of the local player** on the cursor cell (`NNet::System::FindFlagAt`) → flag;
2. a **building hit by the ray** (`PickVisibleEntityAtMouse` S 00787cc0): the map-object layer's objects of kind
   6 or 8 are tested in list order, bounding box first, then the object's own ray test (slot 9); the first hit
   ends the search, and it counts only when it is kind 6 and its slot 1 returns 0; the building is looked up by
   id and is rejected when its cell is not explored (`NMap::Exploration::IsExplored` with the building's cell and
   owner) → building (any owner);
3. a **building on or next to the cursor cell** (`PickSelectableEntityAtCell` S 00787f40,
   `NVillage::System::FindBuildingAtOrAdjacentCell`) that has a render instance → building;
4. a **ship** hit by the ray (`ShipMgr::PickShip`) → ship;
5. a **ship route** marker hit by the ray (map object of kind 8) → ship route;
6. the **street** on the cursor cell (looked up in the street net), when it is valid and owned by the local
   player → street;
7. otherwise nothing is selected.

Settlers are not selectable by a click [inferred: no branch of this function selects one].

**Left click** (`MenuSelection::HandleClick` S 00617910) [known]: the cursor cell is copied to
`hoveredCellX/Y`, then by `mode`:
- **1**: the selection UI is refreshed. If no info box is open and nothing is selected, the construction flags
  of the cursor cell for the local player are read (`Cursor::GetBuildFlagsAtCell` S 00787df0: 0 when the cell is
  outside the map or blocked in the grid-state map, else `ConstructionMap::GetCellFlags`,
  [map-resources.md](map-resources.md) §2.3): any of bits `0x1f` → **building placement** (`BeginBuildPlacement`
  S 006176d0: the create-building box 0xc gets the flags, `mode = 2`, the cell is highlighted in the scene);
  exactly `0x20` → the cell menu (`SelectCell` S 00617770, info box 0x13) from which a flag can be placed.
- **2**: if the create-building box holds a chosen building type (+0x1630 ≠ −1) the click sends "place building
  at the cursor cell" (`0x20002`, [game-commands.md](game-commands.md)); otherwise `mode = 1`, the selection is
  reset and the click is handled again as a mode-1 click.
- **3** (street building): `StreetBuildMode::HandleClick(cursor cell)` S 0078bed0 returns 0 waypoint accepted
  (sound `uiClick0`), 1 refused (sound `uiCancel`), 2 the last waypoint was clicked again (selection reset, cell
  menu 0x12 on that cell), 3 the start cell was clicked (cancel).
- **4**: `mode = 1`, selection reset, then handled again.

**Right click** (`MenuSelection::HandleRightClick` S 00617bc0) [known]: mode 2: reads the box
`infoBoxes[0xc]` (`InfoBoxCreateBuilding`, ctor S 00634bc0); a hidden box is shown again (vslot 0x24 `SetVisible(1)`) and
the click is consumed, else `mode = 1` and the selection is reset (details below); mode 3: cancel street building unless the
planned street can already be completed (S 0078b180: `planner0.IsConstructionActive() && CanComplete()`; then
the click keeps mode 3 and `MenuSelection::Update` ends the mode, [ingame-ui.md](ingame-ui.md) §3.5)
(`MenuSelection::Cancel` S 006162e0: sound `uiCancel`, `mode = 1`, `StreetBuildMode::Cancel`
S 0078b1d0, selection reset; the street mode switches the cursor's placement mode off and sends `0x20007`
when a waypoint beyond the start cell exists, otherwise it is just ended without a command); mode 4 →
`mode = 1`, reset; mode 1: the selection is reset. The action panel is closed unless it is waiting for a
confirmation (not on the two consumed paths). Because the right button is also the look-around button, a right click both deselects and starts
turning the view.

Detail of the modes [known: decompile]: mode 3: if the system has no street build mode (`streetModes.size == 0`) the click is
consumed and returns true without cancelling and without closing the panel. Otherwise `GetActiveStreetBuildMode` S 00783490;
if the planner is not (`IsConstructionActive() && CanComplete()`, S 0078b180), `Cancel(this, 0)` S 006162e0 and return
true; if it can be completed the mode stays 3 and the action panel is closed (`CloseUnlessConfirming` S 005f0510), return
false. Mode 2: vslot 0x2c is `nUi::Object::IsVisible` S 004a0100 and vslot 0x24 is `nUi::Object::SetVisible` S 004a1090 (the box's
vftable 007f541c does not override slots 9 and 11). When `IsVisible` returns 0 the box is shown again (`SetVisible(1)`) and the
press is consumed (return true); the mode stays 2, no reset, the panel stays open. A visible box: `mode = 1`,
`ResetSelection` S 00615d10 (which includes `CloseUnlessConfirming` S 005f0510), return false. What hides the box while the
mode is 2 is not found [TODO]. [ingame-ui.md](ingame-ui.md) ("if the create-building box is not visible, show it") agrees.
Mode 4: `mode = 1`, `ResetSelection`, panel closed, handled like the default path (not consumed); the writer of mode 4 is
not found [TODO]. Any other mode: reset, not consumed.

The consumed result: `nMenu::Game::OnMouseButton1Down` S 005eab40 sets `buttonPressed[1]` (Game+0x3a) in both cases and
returns the result of `HandleRightClick` to `nUi::Object::DispatchEvent` S 004a07a0, which stops offering the press to the
widgets behind at the first child that returns 1. `CApplicationEx::HandleWindowMessage` S 00401f30 (case 0x204) ignores the
result. The camera's look-around (`UpdateStandardMode` S 00786e70: `buttonPressed[1] != 0 && uiSuppressed == 0`) starts whether
the press was consumed or not [known].

The right button on the press [known: decompile]: S 005eab40 has no `IsGameHanging` gate, stores no position and checks no
camera style, modifier or pause state. It never picks an object (no `SelectAtCursor`). S 005eab70 is not a Game override
but the stock `nUi::Event::OnMouseButton1Up` shared by every widget; `Object::DispatchMouseUp` S 0049ff40 reaches it only if
a press set the flag. The second press arrives as `WM_RBUTTONDBLCLK` (S 00401f30 case 0x206): `Root->HandleEvent(1, 1, 0)` ->
`Object::DispatchMouseDoubleClick` S 0049ff20 -> `Event::DispatchMouseDoubleClick` S 004ab1f0 -> the Game's slot 17 =
`Generic_ReturnZero` S 0072db80 (the left double click is slot 14, S 005eab30). The second press of a double click neither calls `HandleRightClick` nor sets `Game + 0x3a`, so it does not deselect and
does not start the look-around; the release after it is not dispatched (the flag was cleared by the first release, S 005eab70). [inferred] open: for every
double click the window layer calls `GameAction vtbl+0x18(1, 1)` (S 00401f30), a left-button-down game action, not traced. There
is no drag threshold and no click suppression for the right button: the press has deselected / cancelled before the
look-around (S 00786e70: `buttonPressed[1] != 0 && uiSuppressed == 0` -> mode LookAround) turns the view, and the
look-around starts also when `HandleRightClick` returned true (consumed).

**Street building** [known for the calls; the planner itself is in
[streets-transport.md](streets-transport.md)]. Action 9 of a selected flag calls `MenuSelection::BeginStreetBuild`
S 00615e30: `mode = 3`, `nGame::System::BeginStreetBuildMode(selection cell)` creates an
`ai::game::StreetBuildMode` (0x3c bytes) for the local player and starts it; the cursor gets placement mode
(true, 2) and the start cell as anchor. `StreetBuildMode::HandleClick` S 0078bed0 tests in this order: the
clicked cell is the first waypoint → 3; it is the last waypoint → 2; else the segment is planned on the first
planner (`PlanSegment`), result 1 → refused. On an accepted first click (one waypoint so far) the mode sends
`0x20006` and the cursor's `placementKind` becomes 0 for a path of kind 2 and 1 otherwise. A later click whose
plan result is 4 is refused and switches the cursor's placement mode off. Every accepted click appends the
cell to the waypoints, moves the anchor to it (or, when the first planner reports through its slot 5 that it
is done, switches the cursor's placement mode off instead), refreshes the preview and sends `0x20008`. Per frame `nGame::System::Render` refreshes the preview for the cursor cell
(`StreetBuildMode::UpdatePreview` S 0078bbe0: only when the cursor cell changed; the cell is appended
temporarily to the waypoints, the path is re-planned on the mode's second planner; the shorter of the two
paths is drawn as a preview street and the rest of the longer one as a second, alpha or red tinted, preview
street, [world-objects-rendering.md](world-objects-rendering.md) §3.6). `MenuSelection::Update` S 006163f0
cancels mode 3 as soon as the street mode is gone, has no waypoints, is invalid, flagged cancelled, or its
planned street can already be completed (S 0078b180).

**Cell marker** (`Cursor::UpdateCellMarker` S 007885e0, called by `Cursor::Update` S 0078a2b0 from
`nGame::System::Render` S 007835d0) [known]: every frame, whether info-map mode is on or off, only with
`bActive` and an active human player, and only when the cursor cell projects onto the screen. It is what fills
the hovered cell, which the build-placement overlay leaves out ([rendering.md](rendering.md) §3.14).
- Placement mode: a sprite of atlas `ui_ingame5`, rectangle `(u, 600, 82, 85)` with `u = 179` when a street
  cannot pass the cell (`GameQuery::CanStreetPassCell`), `u = 92` when a flag can be placed there
  (`GameQuery::CanPlaceFlagAt`), `u = 4` otherwise.
- Normal mode: nothing when the construction flags are 0 or a building is under the mouse. Icon index: base 0
  for bit 4, else 1 for bit 2, else 2 for bit 1, else 3 for bit 8, else 4 for bit 0x10 (16 with no further
  offset when none is set); then +5 when only 0x40 is set, +8 when 0x20 and 0x40 are set, +11 when neither is
  set, +0 when only 0x20 is set. The icon is an 88 × 88 pixel cell of `ui_ingame3.dds` (1024 wide), taken from
  a 17-entry table with a step of 0.0859375 (= 88 / 1024): entries 0..10 are `i × 0.0859375`, entries 11..16
  are `1.0 + (i − 11) × 0.0859375`; with `x = entry + 0.015625` (S 008352e0), row = `int(x)`, u = `frac(x)`,
  v = 0.625 (S 008352d8) + row × 0.0859375 (S 00835328), so icon `i` is at pixel
  `(16 + 88 × (i mod 11), 640 + 88 × (i div 11))`: the glowing rows of the atlas, 168 px above the rows at 808
  that the build-placement overlay uses.
- The marker quad is 3.5 world units wide and 3.5 high (constants 0.5 S 007d877c and 3.5 S 007e6954) with its
  bottom centre on the cell's world position (corners `(∓1.75, 0)` and `(±1.75, 3.5)`), camera-facing about the
  world axis (0, 1, 0) in a basis taken from the device matrix at `CGraphicDevice + 0x1f8`, projected to the
  screen and drawn as a UI sprite.

**Street slope overlay** (`Cursor::DrawStreetSlopeMarkers` S 00788f90) [inferred from its summary, not re-read]:
a marker on the anchor cell and, on each of its 6 neighbours, either "already on the path" or a slope-class
sprite when the neighbour is a valid next step (`CanStreetPassCell` for kinds 1 and 2, `CanStreetStepTo` for
kinds 2 and 0); sprites from `ui_ingame5`.

**Hover tooltip** (`nMenu::Game::UpdateWorldHoverTooltip` S 005ef740) [inferred from its summary]: per frame,
names the thing under the mouse (own building with productivity or construction state, flag, carrier, soldier,
ship, deposit) and selects mouse cursor 2 over an own object, else 0 (`cursors.xml`,
[formats-inventory.md](formats-inventory.md) §3.10).

### 3.11 Screenshots

[known: S 0067ea50, S 006833a0, S 004dd420..S 004ddc50] The scene's key handler receives keys the UI did not
consume and acts when its second argument is non-zero, which the application passes for the **key-up** message
(§3.9):
- **PrintScreen** (0x2c) released: request a screenshot for the next rendered frame.
- **Numpad +** (0x6b) / **numpad −** (0x6d) released: tiles per side ±1, clamped to 1..8; a message timer is set
  to 3.0 s (the debug overlay prints the resulting image size, `ScreenshotTool::EstimateScreenshotSize`
  S 004dcf60 = viewport size × tiles) [inferred for what the timer shows].

`Scene::CaptureScreenshot` S 006833a0: with 1 tile, the frame is rendered once into a render target of viewport
size and copied to a system-memory surface. With `n > 1`, the capture surface is `n ×` the viewport in both
directions; the device's camera is wrapped in a `HighresShotCamera` and the scene is rendered `n²` times, tile
`row × n + col` being copied to `(col × width, row × height)`. Per-tile projection
(`ScreenshotTool::GetProjectionMatrix` S 004dd740, disassembly) [known]: with `w = near × tan(fov / 2)` and
`h = w × viewport height / viewport width` (the frustum of the normal projection, §3.1; `near` includes the
device's near offset), `row = tile div n`, `col = tile mod n`, the matrix is
`PerspectiveOffCenterLH(left = −w + 2w × col / n, right = −w + 2w × (col + 1) / n,
bottom = h − 2h × (row + 1) / n, top = h − 2h × row / n, near, far)`. The tile count returns to 1 after each
capture. The UI is not part of the image: only the scene's render function is called [inferred].

File (`ScreenshotTool::SaveScreenShot` S 004ddc50): BMP written with `D3DXSaveSurfaceToFileA`; name
`Pic_YYYYMMDD_hhmmss.bmp` (local time) in `<My Documents>\SAdK\screenshots\`, created on demand. When a series
base name is set on the tool the name is `<base>_%05d.bmp` with a global counter instead; the base name is only
written by the tool's creation (empty) and destructor, so this branch is not reached [inferred: text search of
the decompiled code].

### 3.12 Typed cheats

`nMenu::Game::OnKeyDown` S 005ec340 [known]. Enter while the chat input is not focused (and the tutorial is
hidden) opens the chat input with an empty line. Enter with the chat input focused, **in network mode 0 only**, compares the whole line
(case-sensitive, exact) with five strings, then sends the line as chat anyway (team chat when Shift is held)
and closes the input:

| Line | Effect |
|---|---|
| `WhatTheHell` | local game speed (`UserProfile + 0x24`) = 20.0 |
| `WhatCanEyeSee` | `MapModifier::ExploreArea((g_MapWidth / 2, g_MapHeight / 2), radius = g_MapHeight, local player)` |
| `DontWantToLose` | records the current map as completed in the user profile and saves the map states |
| `ThatsANiceView` | camera mode 0 → `ResetView(2)` (free fly), mode 2 → `ResetView(0)`; other modes unchanged |
| `ItsLikeAJackpot` | `Cheat_FillStoreWithGoods` S 005eba50: the target is the building S 00558730 returns, the first building of the village's depot list (`depotBuildings`, +0x20) owned by the local player whose two remaining construction fractions are both ≤ 0; into its `stockB` (`Depot +0x28`) it adds 10 of each entry of the tribe property's goods list (+0x24..+0x28), then of its jobs list (+0x34..+0x38), skipping good types 2 and 3; the soldiers are in the jobs list too |

Two of these change simulation state directly, outside the command path, which is why they are limited to
offline play ([game-commands.md](game-commands.md) §8).

### 3.13 Developer features in the shipped binary

- **Debug icon row** [known for the construction, S 005ed700]: `nMenu::Game::SetupHud` builds five icons with
  the tooltips "!Start debug session.", "!Hide Ui for screenies...", "!Toggle Camera Mode.",
  "!Toggle Game Speed.", "!Toggle Grabbing Mode." whenever `uiSuppressed` is 0, i.e. always. Right after
  creating them it calls slot 10 of each icon, which in the base `nUi::Object` vftable is `Hide` S 004a1130
  (`visible = false`); slot 10 of the `nUi::Icon` vftable S 007e26ec is `Icon::Hide` S 004cf210, which clears
  the tooltip and ends in `Object::Hide` [known], so the icons are hidden. Nothing shows them again: the
  visible byte of a widget is written only by `Object::ctor` S 004a3cc0 and `InitAndAttachToParent`
  S 004a56d0 (true), `Object::SetVisible` S 004a1090 and `Object::Hide`; showing a parent does not write a
  child's byte (`OnParentShown` S 004a1230 only marks the layout dirty), and no loop over a widget's children
  calls `SetVisible` or a fade-in [known: decompiled image]. In the decompiled
  code of the whole binary the five icon members are touched only by the screen's constructor, destructor, `SetupHud` and `DestroyHudWidgets` S 005ea650: nothing reads a click from
  them, and nothing writes camera modes 3 or 4 (§2.2) [inferred]
  ([../subsystems.md](../subsystems.md) §5). In a running match all five have `visible` = 0 [live, 2026-10-12].
  Shown by a debugger call of slot 9 (`SetVisible(true)`, `+0x24`) on the five icons (`nMenu::Game +0xb338`,
  `+0xb730`, `+0xbb28`, `+0xc480`, `+0xc878`) and on the HUD root (`+0x968`), their visible byte (`+0x14d`) went
  to 1; they appear in the top right of the screen and clicking each does nothing [live, 2026-10-12].
- **Debug toggles** [known]: four toggle buttons (AI, harbour, flag, military; S 0061aa90, S 0061a290,
  S 006197a0, S 00617f30) are polled every frame in `nMenu::Game::Update`, and their overlays are drawn by
  `nMenu::Game::Draw` S 005efdd0. While the AI toggle is on, the characters `r`, `m`, `i`, `c` switch between
  four AI overlay views; pressing the active one again turns it off (`HandleDebugKey` S 0061a9c0). These
  characters are consumed before `h` / `p` / `x`.
- **`uiSuppressed`** (`nMenu::System + 0xa4`): a "no UI" state that is read by the camera (double far plane,
  no look-around mode, free-fly mouse look without a button), the cutscene loop, the autosave, the music, the
  HUD construction and drawing of `nMenu::Game`, and the world build and load paths
  ([save-format.md](save-format.md) §3.4). The only write found is the constructor's 0 [inferred: text search of
  the decompiled code; a write through a pointer would not show]. This document treats it as always 0.
- **CVars** [known: constructors' callers]: variables are registered with a group and a name, among them group
  `ui` (`Hide UI`, which makes `nUi::Root::Render` S 00491660 skip the UI; `DumpToFile`; `BatchUiRendering`;
  `MiniMapRender`; `MiniMapRenderSymbols`), the scene's show flags (general, profile, characters, items,
  shadow, particles, post FX, buildings, ships, terrain, fog of war, ...; struct `S2CG::Scene`), `Shader /
  MaxShader`, `Street / DepthBias`, `Character / ForceLOD`, and lobby groups. Their only front ends are the CVar
  server and a native `DebugToggleWindow`.
- **CVar server** [known: S 0067c6d0, S 0067cc10; protocol in `tools/cvar_client.py`]: disabled, because no
  code sets its gate byte; with the gate forced ([../BINARY_PATCHES.md](../BINARY_PATCHES.md)) it listens on TCP
  port 1234 on all interfaces (backlog 10, 8 clients) and speaks a text protocol with `&`-terminated,
  `$`-separated messages (`APP`, `CREATE`, `CHANGE`, `DESTROY` from the game; `CHANGE`, `REFRESH`, `CUSTOM` to
  the game).
- **Command line**: `-start`, `-map`, `-nolobby`, `-mptest` ([../subsystems.md](../subsystems.md) §5).
- **Map editor screen** `nMenu::Debug`: present, no opener found ([../subsystems.md](../subsystems.md) §5). Its
  `OnHide` resets the camera's `distanceScale` to 70.0 (S 00602000), so the editor is the one place that changes
  it [inferred].
- **Cutscene debug list**: `menu.addCutsceneDebugName(name)` and the script functions `dbg_addCinematics` /
  `dbg_playCinematic` ([lua-runtime.md](lua-runtime.md) §4.3) fill and use a list of quest cinematics in that
  debug UI.

---

## 4. Update order

The main loop (`WinMain` S 00407cf0) alternates `CApplicationEx::FrameTick` S 00401bd0 with a drain of the
window message queue (`PeekMessage` / `DispatchMessage` until empty) [known]. One cycle in a match
(`CApplicationEx::FrameTick_InGame` S 004018e0 [known for the order of the calls]; the simulation side of the
list is in [game-commands.md](game-commands.md) §4):

1. Window messages of the queue: mouse position, UI events, camera key map, zoom target, selection clicks,
   commands queued or (offline) executed. They arrive between two frames, never inside one.
2. Frame timer update, UI layout reload when requested, the `nUi::GameAction` map is told whether the window is
   active and not minimised.
3. If the in-game screen is open: `nGame::System::Update` S 00780d20 [known], in this order: on the host of a
   network game in session state 3 with every slot loaded, the start-game broadcast; the autosave timer (skipped
   during a cinematic and while `uiSuppressed`); the embedded cursor's update slot, which is an empty function
   (vftable S 008352b8 slot 1 = S 005657b0); `Camera::Update` (zoom easing, mode handler, i.e. scrolling and the
   view solve); then, only once the first logic tick has run (`tickCounter ≠ −1`): the update of the `Script`
   member at `nGame::System + 0x60c`, and (unless `uiSuppressed`) the music and `ai::camera::CutsceneCamera::Tick`. The
   cutscene pose therefore overwrites `eyePos` / `lookDir` after the camera's own update of the same frame.
   After it, the message list of the in-game screen is updated.
4. `nMenu::System::Update` S 005da500 [known]: language reload check; `nUi::Cursor::Update`; each open dialog of
   the nine slots is updated (among them `nMenu::Cinematic`, whose `Update` S 005fb3e0 does the page timing and
   the game-speed blend); the UI tree is updated, which is where `nMenu::Game::Update` S 005efea0 runs
   [inferred: it is slot 1 of the screen's update face S 007eeca4 and has no direct caller]:
   `MenuSelection::Update`, the debug toggles and, while the camera mode is not 3, the HUD button clicks and the
   hover tooltip; then the minimap symbol timers and a pending map start.
5. NComm pump, Lua threads, `NLogic::System::Update` (simulation ticks; the map script's `onLogicTick` and with
   it `menu.startCinematic`), then the sound system update.
6. Rendering (`App_RenderWorldFrame` S 00401260) [known]: `CGraphicDevice::UpdateTransformations` pulls eye,
   look-at, field of view and planes from the active camera (`UpdateCameraMatrices` S 004d9300), then
   `nMenu::System::Render` S 005d9800 draws the UI tree, inside which the in-game screen draws the scene
   [inferred: the scene and `nGame::System::Render` are reached through virtual calls only].
   `nGame::System::Render` S 007835d0 refreshes the street preview and runs `Cursor::Update` (picking with this
   frame's matrices, marker); a requested screenshot is captured inside `S2CG::Scene::Render` S 006836b0, after
   the shadow and reflection passes and before the main passes, and the request is cleared.
7. Back in `FrameTick`: `nUi::Cursor::StorePreviousPosition` S 00492540, the last call of the frame. The mouse
   delta that the camera reads in step 3 (`GetMoveDelta`) is therefore "position after this cycle's messages
   minus position at the end of the previous frame".

Per logic tick: nothing of this subsystem runs. On load or new game: `BuildWorld` S 00784d40 → `Cursor::Init`,
`Camera::Activate`.

---

## 5. Inputs and outputs

Consumes:
- window messages (mouse, keyboard, wheel, activation), the foreground-window test for edge scrolling;
- terrain: height sampling, nearest vertex, cell and vertex world positions, water level, the visible terrain
  cells and mesh for picking ([rendering.md](rendering.md) §5);
- simulation, read-only: player table (local player), village (buildings by cell, by id), street net (flags and
  streets by cell), navy (ships, routes), settlers (by id; screensaver targets), exploration map, construction
  map, `GameQuery` street and flag tests;
- user profile (§2.7), UI layout XML (hotkeys, `menucinematic.xml`), text and voice files, cutscene scripts.

Produces:
- eye position, look-at point (`eyePos + lookDir`), field of view and clip planes for the renderer; the same eye
  and look-at point feed the sound listener ([audio.md](audio.md) §3.2), and the device frustum built from them
  is what the minimap draws as the view trapezoid (`nMenu::MiniMap::DrawCameraFrustum` S 005f2a50 [known]: rays
  from the camera through the frustum corners 0, 1, 7 and 6 (near pair, far pair) are cut with the plane y = 0
  (`Terrain_RayHitGroundApprox` S 0068a610: no hit when the ray points up, and the point then stays the corner);
  the far pair takes the hit only when it is nearer than the far-plane corner; nothing is drawn when all four
  miss; uv = ((x − originX) ÷ extentX, 1 − (z − originZ) ÷ extentZ); the edges are clipped against the round
  minimap (`Math_IntersectLineCircle2D`, radius = half the widget width) and drawn with the shape's alpha; a corner whose ray
  misses keeps its original frustum position; the world extent is `(mapW - 1) * tileStepX` (S 00686f80, S 00686fa0) while
  the cell symbols use `cell / mapWidth`, a systematic offset of about one cell in 256; the frustum is drawn with
  `DrawLine2D` S 004e1cb0 (white, widget alpha, 1 px), clipped by hand to the circle, not through the mask;
  `renderFrustum` (obj+0x9a9) defaults to 1 in the constructor, so the in-game minimap draws it although
  `menuingame.xml` does not set `renderfrustrum`; the cinematic layout sets it to true explicitly);
- the local selection (`ai::game::Selection`) and, through the menus, command events
  ([game-commands.md](game-commands.md) §5.1): this is the only way input changes the simulation;
- during a cinematic: the three switches of `BeginCinematic` (AI off, chests off, sacrifices paused), the
  `cinematicActive` flag, the local game speed, the music track and sound ducking, the fog-of-war overlay, the
  callback `quest_cinematicDone()`;
- with cheats, in network mode 0 only: exploration, stock contents, the map-completed record of the user
  profile, local game speed, the free-fly camera;
- screenshot files.

---

## 6. Data-driven parameters

| Source | Keys | Example values | Used for |
|---|---|---|---|
| `settings.cfg` (`UserSettings`) | scroll speed, invert scrolling, border scrolling, smart cursor, byte +0x33 | 0.25, 0, 1, 1, 0 (defaults) | §2.7 |
| `data/game/ui/layout/menuingame.xml` | `hotkey` attributes | `btSpeed hotkey="v"`, `closeButton hotkey="27"` | §3.9 |
| `data/game/ui/layout/menucinematic.xml` | `blackDesktop`; `panel` with `avatar0` / `avatar1` (`start`, `end`, `dist="5.5"`, `heading="-50"` / `"50"`, `elevation`, `alignRight`), `barTop`, `barBottom`, `textMissionBlock`, `textHeadline`, `textDescription` (`wrapSize="600 100"`), `miniMap`, `miniMapFrame` | — | cinematic layout |
| `data/game/ui/layout/cursors.xml` | `cursor0`..`cursor3` | main, clock, main, build | mouse cursors |
| `data/game/maps/campaignMaps/C<nn>_<name>.lua`, `data/game/scripts/mapTools/cutscene_circle.lua` | `cutscene.*` calls | `cutscene.addPosition(9.2, -113.602, 30.32, -203.047)` | camera paths (§3.7) |
| `data/game/scripts/mapTools/quests.lua`, map scripts | `briefingPages` entries: text key, `cutscene`, `x`, `y`, `callback`, `data` | `{ text = "waitsec", cutscene = "[data]\\maps\\campaignMaps\\C02_12smallBUILD.lua", x = GoldResourcesX, y = GoldResourcesY }` (`C02.lua`); a `callback(data)` that returns a position replaces `x`, `y` | which pages a quest shows |
| `data/game/language/<lang>/briefings.txt` | `<key>`, `<key>_title` | `B10_0_2` = `[McDoyle:0][Moped:1]...` | subtitles, speaker tags, captions |
| atlases `ui_ingame5`, `ui_ingame3.dds` | fixed rectangles in code | §3.10 | cell and street markers |

The `Camera` element of `data/game/settings/graphics.xml` (`moveSpeed`, `zoomSpeed`, `turnSpeed`, `tiltSpeed`,
`nearPlane`, `farPlane`, `minElevation`, `maxElevation`, `minZoomLevel`, `maxZoomLevel`, `targetRelativeHeight`,
`cameraRelativeHeight`, `doTerrainCollision`; e.g. `moveSpeed="20.0"`, `nearPlane="0.1"`, `minElevation="-85"`)
is **not** read by the game: none of its thirteen attribute names exists as a string in the binary in the file's
spelling [known: string search over the program; the only near match is a capitalised `TurnSpeed` at S 007e7138,
[TODO] not established: its reader, settled by its references], and every camera constant of §3 is a literal in
the code. Its values differ from the
ones in use (near plane 0.1 against 1.0) and must not be taken over.

---

## 7. Save and load

Nothing of this subsystem is in a save game: camera, cursor, selection, open windows, cutscene and cinematic
state are not written ([save-format.md](save-format.md) §7). After a load `BuildWorld` runs `Camera::Activate`,
so the view starts at the local player's first finished storage building (§3.1) with zoom 3 and no yaw offset,
and `Cursor::Init`.

Of the simulation-side switches of a running cinematic (§3.8), two are saved with their owners and two are not:

| State | Saved | Evidence |
|---|---|---|
| `NAI::System.enabled` (cleared) | yes | [ai-player.md](ai-player.md) §7 |
| chest system `enabled` (cleared) | yes | [known] `LogicChestSystem::Save` S 0052d200 writes it last |
| sacrifice system `bPaused` (+5) and `pauseStartTick` (+8) | no | [known] `NSacrifice::System::Store` S 0065f500 writes only the initialised byte and the per-player table; the constructor S 0065f9b0 sets `bPaused = 0` |
| `NLogic::System.cinematicActive` (+0xec) | no | [logic-core.md](logic-core.md) §2 [inferred there] |

The screen's own state (`nGame::System` +0x634 saved AI byte, +0x635, the saved game speed) is not saved either.
A save written while a cinematic runs would therefore load with the computer players and the chests switched
off and nothing left to switch them on again [inferred]. The autosave cannot produce one: its timer does not
run while `nGame::System + 0x635` is set (S 00780d20) [known]. Ways to write a save while the cinematic screen is open [known]: `GameFile_Save` S 005aa260 has five
callers. The autosave is gated (above). The save panel is created only by the HUD's menu combo
(`nMenu::Game::OnMenuComboSelected` S 005eb310) as a child of the HUD container `Game +0x968`, which
`Cinematic::OnShow` fades out over 1.0 s or hides at once (§3.8); `CloseAllDialogs` S 005d9650 does not close
it (it covers the nine system dialogs), and every key goes to the cinematic screen. `nMenu::System::EmergencySave`
S 005da7d0 (`WM_POWERBROADCAST`, battery low) writes `_EmergencySave_` whenever the game screen is attached and
does not test the cinematic flag. The Debug dialog S 00609130 is not reachable in the shipped game. [TODO] not
established: whether a mouse click reaches the menu combo or an open save panel during the 1.0 s fade.
Scroll and cursor options live in `settings.cfg`; screenshots are write-only.

---

## 8. Determinism notes

- Camera, cursor, picking, selection, hotkeys, screenshots: presentation and local input only. They read
  simulation objects and write none; the only path from input to the simulation is the command event
  ([game-commands.md](game-commands.md) §3.1). The camera's time base is the frame time, and several smoothing
  factors are applied per frame without `dt` (0.245, 0.4 / 0.9, 0.3, 0.05, 0.025), so camera motion depends on
  the frame rate; this cannot affect the simulation.
- The screensaver view uses the C library `rand()`, not the simulation's `LogicRandom` [known, S 00786140,
  S 006556a0].
- Cutscene playback is local: files are evaluated in a temporary Lua thread, the spline is advanced by frame
  time.
- **The cinematic is the exception**: `BeginCinematic` / `EndCinematic` write simulation state (AI enabled,
  chest system enabled, `cinematicActive`, sacrifice pause with a tick shift) from a UI screen. The begin runs
  where the script calls `menu.startCinematic` (inside a tick when that is `onLogicTick`) [inferred: the Lua
  function shows the screen through a virtual call, `OnShow` was not traced from it]; the end runs in the
  screen's per-frame `Update`, at frame time and not at a tick boundary, and the screen's duration depends on
  local voice playback and key presses. The blend of the local game speed is local as well. A network match
  would diverge. Nothing in the start path tests the network mode (no NComm call in S 005dd3c0, S 005dd410,
  S 005fbd30, S 005fb3e0) [known]; in the shipped data `menu.startCinematic` is called only by
  `quest_setupCinematic`, and `quest_setup` is used only by the scripts under `maps/campaignMaps` [known:
  data]. [TODO] not established: whether a campaign map can be played as a network match
  ([logic-core.md](logic-core.md) question 9). Offline the cinematic is deterministic only relative to the
  frame at which it ends.
- Cheats change simulation state outside the command path and are accepted in network mode 0 only.

---

## 9. Notes for a Godot reimplementation

- **Camera rig.** One `Camera3D` driven by a script that keeps the state of §2.1 (focus point, zoom target and
  current, yaw offset target and current, look direction, eye) and reproduces §3.2: fixed **horizontal** field
  of view of 50° (`keep_aspect = Camera3D.KEEP_WIDTH`, `fov = 50`; §3.1 Projection), near 1, far 500. The
  original is left-handed with Y up; convert positions with the same axis flip the map converter uses. To keep
  the look, reproduce: five zoom steps (0..4, start 3) with an eye distance of 21 units × step (0 at step 0,
  where only the clearance rule lifts the eye), the three tilt values by zoom step, the 1.4 factor between view
  direction and offset direction, the stepped focus height (10-unit hysteresis over a five-point average), the
  eye clearance (terrain + 10, water + 5), the per-axis border rule, and the three-position rotation (Insert / Delete).
  Replace the per-frame smoothing factors by frame-rate independent ones (for a factor `f` tuned at a reference
  rate `r`: `1 − (1 − f)^(dt × r)`); the reference rate is not known (question 2).
- **Scrolling.** Edge scrolling within 1 pixel of the screen border, arrow keys, middle-button drag with the
  pointer held in place (`Input.MOUSE_MODE_CAPTURED` gives the same feel), speed proportional to the square of
  the user's scroll-speed setting.
- **Picking.** `PhysicsDirectSpaceState3D.intersect_ray` against the terrain collision (or the terrain mesh
  directly) for the cell and vertex under the mouse, ray length 1000; object picks against per-object boxes plus
  a precise test. Keep the selection priority order of §3.10, including "own flag on the cell beats everything"
  and "building on or next to the cell".
- **Placement modes.** The four-state selection controller (§2.5) maps onto a small state machine; the cell
  marker is a billboarded quad of 3.5 world units with the icon chosen from the construction flags.
- **Key bindings.** Use the `InputMap` with the defaults of §3.9. The original's layout hotkeys are characters;
  a remake can bind physical keys instead and offer rebinding.
- **Cutscenes.** Convert each cutscene Lua file once (by running it against a recording `cutscene` table) into
  two key lists of `{time, vec3}` with cumulative times in seconds, plus a `loop` flag; `setRelative` carries no
  information beyond "this file is played with an anchor". Evaluate with the Hermite form of §3.7 exactly
  (tangent = difference to the next key, not scaled by duration; the last key's in-tangent is the difference
  from the key before it); Godot's `Curve3D` uses a different tangent
  convention, so either write the tangents explicitly as Bezier handles (`handle = tangent / 3`) or evaluate the
  Hermite polynomial in script. The second track is a view direction to normalise, not a look-at point. Anchored
  paths add the anchor cell's flat world position to positions only.
- **Cinematics.** A `CanvasLayer` scene with two bars, title, subtitle, two portrait slots, driven by the phase
  machine of §3.8 (timers 1.0 / 1.5, 0.5, 1.0, 1.0; page length = voice length or 0.1 s per character; minimum
  0.5 s; Space advances, Escape ends). The simulation switches of `BeginCinematic` must be applied by the
  simulation layer, ideally at a tick boundary, and the quest script must get `quest_cinematicDone`.
- **Text.** `briefings.txt` is single-byte (ISO-8859-1 in the German install) [known: data]; convert to UTF-8 and
  split the speaker tags `[Name:N]` off at conversion time.
- **Screenshots.** `Viewport.get_texture().get_image()`; the tiled high-resolution mode has no need to be
  reproduced.
- **Not needed.** The CVar server, the debug icon row, `uiSuppressed`, the tiled screenshot, camera modes 3 and
  4, which nothing enters (§2.2; the screensaver view is a self-contained extra that can be offered as a
  feature).

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.13): the five debug icons of `SetupHud` are hidden right after their creation (`Icon::Hide` S 004cf210 in slot 10) and nothing shows them again | static: vftable S 007e26ec; writers of the visible byte S 004a3cc0, S 004a56d0, S 004a1090, S 004a1130 |
| 2 | The frame rate the per-frame smoothing factors were tuned for (vsync default is on). Measured: the zoom easing is time based (0.96 s to 5 %), the yaw easing frame based (11 frames to 5 %), 21 units per zoom step (§3.1, §3.2; live 2026-10-12). Open: the intended frame rate itself | not recoverable from the binary |
| 3 | Range of the scroll-speed option and the option labels of `UserProfile` +0x28, +0x30, +0x33. Answered for +0x31: `cSmartCursor`, `!SMART CURSOR` (§2.7) | Static read of the options panel's sliders and check boxes |
| 4 | Writes through untyped pointers that a search of the decompiled code cannot show: `nMenu::System.uiSuppressed` (+0xa4; the command-line parser S 00403ac0 does not write it), `Cursor` +0x05, `Camera.mode` values 3 and 4 | Ghidra data-flow references to the three fields |
| 5 | Can a campaign map (the only maps whose scripts start a cinematic, §8) be played as a network match? The save half is narrowed (§7): the panel cannot be opened by key and its parent is faded out; open is a mouse click on the HUD during the 1.0 s fade | [logic-core.md](logic-core.md) question 9; for the click: confirm an open save panel in the first second of a cinematic |
| 6 | The narrow phase of the terrain pick (triangle order, which hit wins, the cell of a hit point) | Static read of S 006bf520 and S 006bfca0 |
| 7 | The anchor object of a render character (vectors at +0x00, +0x20, +0x30) used by the follow view | Static read of the character class's slot 2 |
| 8 | What the flag of a speaker tag changes: it is stored in the speaker slot (`CinematicSpeakerSlot::SetSpeaker` S 0062d7b0) and passed as the last argument of `S2CG::InGameAvatar::RenderAvatar`; and which files a speaker name loads (`InGameAvatar::LoadAvatar` S 0068bf30; the name `none` is skipped by `PreloadSpeaker` S 0062d520) | Static read of S 0068c490 and S 0068bf30 |
| 9 | The slope classes and sprite rectangles of the street overlay | Re-read of S 00788f90 against `ui_ingame5` |
| 10 | Answered (§3.7): the first indexed directory whose last component occurs in the lower-cased request wins (S 006ef8a0, S 006ef680); no match or no directory in the request → empty path, the read fails | — |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 00401f30 | `CApplicationEx::HandleWindowMessage` | window messages → UI events |
| 004913f0 | `nUi::Root::HandleInputEvent` | UI input entry, capture, fallback to actions and hotkeys |
| 004ab060 | `nUi::Event::DispatchEvent` | event type → handler slot |
| 0049ffc0 / 004a76c0 | `nUi::Object::HandleHotkey` / `LoadFromXml` | hotkey match; `hotkey` attribute |
| 004925c0 / 00492880 | `nUi::Cursor::GetMoveDelta` / `RestorePreviousPositionClamped` | mouse movement per frame; pointer hold |
| 004d9300 | `S2CE::CGraphicDevice::UpdateCameraMatrices` | view and projection from the active camera |
| 004d9ae0 | `S2CE::CGraphicDevice::BuildPickRay` | pick ray |
| 0068c8d0 / 0068cc10 / 0068c920 / 0068ca90 | `ScreenPickHelper::PickCell` / `PickHex` / `Pick_MapObjectAtScreenPos` / `PickLogicShip` | picks |
| 007876e0 / 007868f0 / 007867c0 | `nGame::Camera::ctor` / `Activate` / `ResetView` | life cycle |
| 00787530 | `nGame::Camera::Update` | zoom easing, mode dispatch |
| 00786e70 / 00785c10 | `UpdateStandardMode` / `UpdateStandardView` | standard mode input and view solve |
| 00787310 / 00785350 | `UpdateLookAroundMode` / `RotateLook` | look-around |
| 00786ae0 | `UpdateFreeFlyMode` | free fly |
| 00786140 / 00785610 | `UpdateCinematicMode` / `UpdateFollowTargetView` | screensaver view |
| 00785460 / 00785530 / 00785b90 / 007851c0 | `MoveForward` / `Strafe` / `MoveVertical` / `SetFocusPointClamped` | movement and border rule |
| 00785040 / 007852b0 | `ComputeEyeFromFocus` / `Camera_SampleTerrainHeight` | eye distance; terrain height |
| 00786960 / 00786a10 | `OnWheelUp` / `OnWheelDown` | zoom |
| 00787790 / 00787610 | `HandleKeyDown` / `HandleKeyUp` | rotation keys, key map |
| 00785fe0 / 00786060 / 007860e0 / 00784f10 / 00784eb0 | `FocusOnCell` / `FocusOnVertex` / `FocusOnLocalPlayerBuilding` / `SetEyePosition` / `ResetToStandardMode` | jumps |
| 00648de0 / 005f1520 | `nMenu_FocusCameraOnUnique` / `nMenu::MiniMap::FocusCameraOnCursor` | "go to" callers |
| 0078ac10 / 0078a940 | `CutsceneCamera::LoadScript` / `Cutscene_BuildScriptPath` | cutscene file |
| 0078aeb0 / 0078aed0 / 0078a840 / 0078a8a0 | `CutsceneCamera::Play` / `PlayAtOffset` / `ai::camera::CutsceneCamera::Start` / `ai::camera::CutsceneCamera::Tick` | playback |
| 0078a5b0 / 0078a660 / 0078a640 / 0078a6f0 | `cutscene.addPosition` / `addLookAt` / `setRelative` / `createLoopAtEnd` | Lua library |
| 0078d420 / 0078d2b0 / 0078c870 / 0078d1c0 / 0078d030 / 0078d4a0 | `CameraSpline::Update` / `CameraSpline_SampleTrack` / `CameraSpline_KeyMap_RecomputeTangents` / `CameraSpline::SetLoop` / `CameraSpline_KeyMap_AppendLoopSegment` / `CameraSpline::OffsetPositions` | spline |
| 005dd3c0 / 005dd410 / 005fc110 | `menu.startCinematic` / `menu.addCinematicPage` / `nMenu::Cinematic::AddPage` | pages |
| 005fbd30 / 005fb3e0 / 005fb040 / 005faee0 | `nMenu::Cinematic::OnShow` / `Update` / `BeginEnding` / `OnHide` | cinematic screen |
| 005fae80 / 005fae40 / 005fb3b0 / 005faf50 | `Cinematic::OnKeyDown` / `OnAdvanceInput` / `SkipCinematic` / `Cinematic_ParseSpeakerTag` | keys, speaker tags |
| 00782b60 / 00782bb0 | `nGame::System::BeginCinematic` / `EndCinematic` | simulation switches |
| 00780d20 | `nGame::System::Update` | per-frame order |
| 0078a2b0 / 007885e0 / 00788f90 | `nGame::Cursor::Update` / `UpdateCellMarker` / `DrawStreetSlopeMarkers` | map cursor |
| 00788370 / 00787cc0 / 00787f40 / 00787a30 / 00787b00 / 00787bf0 | `Cursor::SelectAtCursor` and its picks | click selection |
| 00787df0 | `Cursor::GetBuildFlagsAtCell` | construction flags of the cursor cell |
| 00617910 / 00617bc0 / 006163f0 | `MenuSelection::HandleClick` / `HandleRightClick` / `Update` | placement modes |
| 006176d0 / 00617770 / 00615e30 / 006162e0 | `BeginBuildPlacement` / `SelectCell` / `BeginStreetBuild` / `Cancel` | mode changes |
| 0078bed0 / 0078bbe0 / 00784220 | `StreetBuildMode::HandleClick` / `UpdatePreview` / `nGame::System::BeginStreetBuildMode` | street building UI |
| 005eaae0 / 005eab40 / 005eab80 / 005eb140 | `nMenu::Game` mouse handlers | clicks, button flags, wheel |
| 005ec340 / 005eb230 / 005eb180 | `nMenu::Game::OnKeyDown` / `OnKeyUp` / `OnChar` | chat, cheats, `h` / `p` / `x` |
| 005eba50 | `nMenu::Game::Cheat_FillStoreWithGoods` | `ItsLikeAJackpot` |
| 005da400 | `nMenu::System::TogglePause` | pause key |
| 005ed700 / 0061a9c0 | `nMenu::Game::SetupHud` / `GameAiDebugToggle::HandleDebugKey` | debug icons and keys |
| 0067ea50 / 006833a0 | `S2CG::Scene::HandleKey` / `CaptureScreenshot` | screenshot keys and capture |
| 004ddc50 / 004dd610 / 004dd940 | `ScreenshotTool::SaveScreenShot` / `PrepareHighResolutionShot` / `EndHighResolutionShot` | file, tiles |
| 0067c6d0 / 0067e690 / 0067cc10 / 0067df40 | `CVarServerHolder_Init` / `CVarRemoteServer::ctor` / `OpenListenSocket` / `CVarServer_ThreadMain` | CVar server |
| 005c6270 / 005c6370 / 005c64a0 | `CVar::ctor_Bool` / `ctor_Float` / `ctor_Int` | variable registration |
| 00407cf0 / 00401bd0 / 004018e0 / 00401260 | `WinMain` / `CApplicationEx::FrameTick` / `FrameTick_InGame` / `App_RenderWorldFrame` | main loop, frame order (§4) |
| 005da500 / 005d9800 / 005efea0 | `nMenu::System::Update` / `Render` / `nMenu::Game::Update` | dialog and UI tree update, UI render, in-game screen update |
| 007835d0 / 006836b0 | `nGame::System::Render` / `S2CG::Scene::Render` | street preview and map cursor per frame; where a screenshot is taken |
| 00492540 | `nUi::Cursor::StorePreviousPosition` | end-of-frame mouse position |
| 006e97e0 / 006e8e80 | `ai::math::Matrix44::PerspectiveFovLH` / `PerspectiveOffCenterLH` | projection; `fov` is horizontal |
| 004d9e10 | `S2CE::CGraphicDevice::SetNearPlaneOffset` | only writer of the near offset +0x518 |
| 004dd740 | `S2CE::ScreenshotTool::GetProjectionMatrix` | projection of one screenshot tile |
| 00784e90 | `Unk_SetMode5_HideCursor` | camera `mode = 5`, `hasTargetPos = 0`, cursor hidden |
| 00558730 | `NVillage::System::FindCompletedBuildingOfPlayerInList20` | first finished storage building of a player |
| 006e7770 / 006e6d40 / 006e6660 | `File_ReadAndDecrypt` / `NBase::gReadFileData` / `gDecryptData` | file read; missing-file behaviour |
| 006e3fd0 / 006ef8a0 | `FileScanHolder::ResolvePath` / `FileScan::ResolvePath` | file lookup by name in the start-up index |
| 005c9690 | `ai::script::LuaScriptHost::RunFile` | runs a cutscene file |
| 005dda30 | `nMenu::System::Initialize` | registers `startCinematic`, `addCinematicPage`, `updateCinematic` |
| 0065f500 / 0065f550 / 0065f610 / 0052d200 | `NSacrifice::System::Store` / `PauseForCinematic` / `ResumeAfterCinematic` / `LogicChestSystem::Save` | what of a cinematic is saved (§7) |
| 0062d7b0 / 0062d520 | `CinematicSpeakerSlot::SetSpeaker` / `PanelCinematic::PreloadSpeaker` | speaker slots |
| 004a1130 | `nUi::Object::Hide` | base slot 10, called on the debug icons |
| 005f2a50 | `nMenu::MiniMap::DrawCameraFrustum` | view trapezoid on the minimap |
