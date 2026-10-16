# HUD panels in detail: statistics, goods, tooltips, messages, overlays

Tags: **[known]** = read directly at the address given (S 00xxxxxx = `sadk_noav.exe`) or in the named data file
and key; **[inferred]** = one step of reasoning from what is visible; **[TODO]** = open. Nothing here was
observed in the running game.

This file goes one level below [ingame-ui.md](ingame-ui.md). That file owns the widget toolkit, the layout XML,
input routing, the HUD inventory, the selection state machine, the info boxes, the action buttons and the screen
flow; it is not repeated here. This file owns the **content rules** of the panels: which value a label shows,
the formula behind it, when it is refreshed and what a control sends.

---

## 1. Purpose and scope

Covered:

- the statistics panel classes `nMenu::StatsGraph`, `StatsGraphPlayers`, `StatsGraphInventory`, `StatsGoodList`,
  `StatsGoodInfo`, `StatsPlayerInfo`, `StatsBuilding` and the `nUi::Graph` curve widget they drive;
- the goods bar (`GoodInfoPanel` / `GoodInfo`) and the stock / trend query behind it;
- the transport priority list, the military sliders and the goods distribution sliders of the settings panel;
- the five rich tooltips and their data sources;
- the message list (filters, expiry, sounds, minimap symbols);
- the world overlays of the HUD (building, soldier, fight, settler labels) and pointers to the overlays the
  renderer draws (build-placement icons, territory borders, military flags, resource signs);
- the minimap (image, two overlay textures, symbols, input, fog);
- the quest lines, the quest log, the sacrifice bar (summary and pointers);
- the chat widget during a match;
- what a defeated player sees.

Not covered: the counters themselves ([quests-sacrifices-stats.md](quests-sacrifices-stats.md) §3.3,
[players-victory.md](players-victory.md) §2.5, §3.11), the commands' execution
([game-commands.md](game-commands.md) §3.4), the widget toolkit ([ingame-ui.md](ingame-ui.md) §2, §3.1–§3.3).

Everything in this file is presentation. The only outputs into the simulation are the game commands and chat
events listed in §5.

---

## 2. Data model

### 2.1 Statistics panel objects

`nMenu::StatisticPanel` (0x1030 bytes, `menuStatistics.xml`) [known] S 00621d20, S 005eb780:

| Offset | Member | Meaning |
|---|---|---|
| +0x288 | `nUi::XMLHandler` | loads `menuStatistics.xml`; its callback is `OnXmlLoaded` S 006225d0 |
| +0x2a8 | `nUi::TabControl` | `Create(panel, 3)` in the constructor; the constructor fills pages 0, 1, 2. The XML declares `count="4"` and `TabControl::LoadFromXml` S 004bad00 calls `SetTabCount(4)`, which adds page 3 and `tabButton3`; page 3 gets only its XML children (the tech tree pictures, §3.1.6) |
| +0x598 | container `contPlayerInfo` | tab page 0 |
| +0x820 | `StatsPlayerInfo*[6]` | rows `playerInfo0..5`, `playerId` = 0..5 |
| +0x838 | container of the players graph | tab page 0; holds `timeScaling` and `filter` |
| +0xac0 | `StatsGraphPlayers*` (0x2b38) | `graphPlayers` |
| +0xac4 | `filter` widget (kind 0x13) | category chooser, items carry their index as user value |
| +0xac8 / +0xacc | `timeScaling` slider of the players graph / of the inventory graph (kind 2) | |
| +0xad0 / +0xad4 | `StatsGoodList*` goods (fill mode 0) / soldiers (fill mode 1), each 0x2b8 | children of `contInventory` (+0xad8), tab page 1 |
| +0xd60 | container `contGraphInventory` | tab page 1 |
| +0xfe8 | `StatsGraphInventory*` (0x1618) | `graphInventory` |
| +0xff0 | vector of `StatsBuilding*` (0x2888 each) | tab page 2, one per building type (§3.1.6) |
| +0xffc / +0x1010 | `bldOffset` / `bldSpread` (two `nUi::Position`) | grid of the building rows |
| +0x1024 | i32 `numBldPerLine` | XML attribute of the root element [known] S 006225d0 |
| +0x1028 | u8 leave-on-close | set by the end dialog's `btEnd` ([ingame-ui.md](ingame-ui.md) §3.9) |

`nMenu::StatsGraph` (base of both graph classes; a `Picture`, widget kind 0xe) [known] S 0064bef0, S 0064c0c0:

| Offset | Member | Meaning |
|---|---|---|
| +0x288 | `NLogic::IPlayerStatisticsListener` face | registered with the `PlayerStatistics` of all 8 player slots (§4) |
| +0x298 | `nUi::Label[7]` (0x228 each) | time-axis labels `textTimeInfo0..6` |
| +0x11b0 | `nUi::Label[2]` | value-axis labels `textHeightInfo0..1` |
| +0x1600 | u32 `timeRangeMinutes` | constructor default **60**; set through virtual slot 34 (`SetTimeRange`) |

`StatsGraphPlayers` adds [known] S 00642fe0, S 00642d60, S 006435c0: `nUi::Graph graphs[8]` at +0x1608 (0x298
each, XML children `graph0..7`), `u8 graphEnabled[8]` at +0x2ac8, `std::list<Position> graphPoints[8]` at
+0x2ad0 (0xc each), `i32 statisticCategory` at +0x2b34 (0..7, the series index of
[players-victory.md](players-victory.md) §2.5).

`StatsGraphInventory` adds [known] S 00642970, S 00642590: a `std::map<good id, nUi::Graph*>` at +0x1608; one
`Graph` exists per good whose row is switched on.

`StatsGoodList` (0x2b8) [known] S 00644ff0, S 00644840: item vector at +0x28c / +0x290 (`StatsGoodInfo*`, 0xe68
each), `fillMode` at +0x298 (0 goods and non-soldier jobs, 1 soldiers), `localPlayer` at +0x29c, owning
`StatisticPanel*` at +0x2a0, layout ints `itemsOffsetX`, `itemsOffsetY`, `itemsPerLine`, `itemsSpreadX`,
`itemsSpreadY` at +0x2a4..+0x2b4.

`StatsGoodInfo` (a picture button, 0xe68) [known] S 0064c8e0, S 0064c650, S 0064c5a0: good id as the widget's
64-bit user value (+0x28 / +0x2c), XML children `picDepots`, `picOutside` (pictures), `countDepots`,
`countOutside` (labels), the good icon applied to the button itself by `IconConfig`, owner list
(`StatsGoodList*`) at +0xe60.

`StatsPlayerInfo` (0x1030) [known] S 00645400, S 006458a0: `playerId` (+0x1028; −1 = unused), XML children
`name` and `state` (labels), `playerButton` (the toggle button), `textEmpty`, `avatar` (an `Avatar`); strings
`textFriendly`, `textInWar` and colours `colGreen`, `colRed` from XML attributes.

`StatsBuilding` (0x2888) [known] S 006437a0, S 00643f60: `buildingTypeId` at +0x2880; children `m_name`,
`m_building` (icon), `m_iconHouse1`, `m_iconHouse2`, `m_iconProducing`, `m_textHouse1`, `m_textHouse2`,
`m_textProducing`, `m_progress0`, `m_progress1`.

### 2.2 `nUi::Graph` (0x298 bytes): the curve widget [known] S 004c9940, S 004c7f90

| Offset | Field | XML attribute | Meaning |
|---|---|---|---|
| +0x1c0 | texture | `texture` | line texture |
| +0x1c4 | `std::list<Position>` points | – | normalised points, x and y in 0..1 |
| +0x1d0 / +0x1e0 | vertex vector (0x38 bytes per vertex) / u16 index vector | – | line mesh built from the points |
| +0x1f0 | f32 `lineThickness` | `lineThickness` | stored as read (shipped 0.009); not rescaled by the texture size |
| +0x1f4 | f32[4] | `mappingX` | four u coordinates, divided by the texture width at load |
| +0x204 | f32[2] | `mappingY` | two v coordinates, divided by the texture height at load |
| +0x20c | f32[4] colour | `color` | RGBA |
| +0x26c / +0x270 | f32 / i32 | `smoothingStrength` / `smoothingIterations` | §3.1.3 |
| +0x274 | f32[2] | `alphaani` | {rate, amplitude}; rate 0 = off |
| +0x27c | f32[2] | `lineani` | {rate, amplitude}; rate 0 = off |
| +0x284 | f32[2] `offset` | `offset` | added to the widget's absolute position when drawing |
| +0x28c | f32[2] `scale` | `scale` | multiplies the widget's width / height when drawing |

`displayMin` / `displayMax` (+0x19c / +0x1b0, two floats each) are read from the XML and copied by
`CopyPropertiesFrom` S 004c9780, but `SmoothPoints`, `BuildLineMesh` and `Draw` do not read them [known]
S 004c9410, S 004c8fd0, S 004c7f90, and no shipped layout sets them [known: data]; [inferred] they have no
effect.

Line mesh (`BuildLineMesh` S 004c8fd0) [known]: nothing is built for fewer than 2 points (the previous mesh
stays). Each point gives two vertices (0x38 bytes): position `(x, 1 − y)` at +0x00, side −1.0 / +1.0 at +0x08,
1.0 at +0x0c, a white RGBA (1, 1, 1, 1) at +0x10, `u` at +0x20, `v` at +0x24, the previous point `(x, 1 − y)` at
+0x28 and the next point at +0x30. The first point's "previous" and the last point's "next" are extrapolated
(`2 × p − neighbour`; known for the last point, [inferred] for the first). `u` = `mappingX[0]` for the first
point, `mappingX[3]` for the last, else `mappingX[1] + (mappingX[2] − mappingX[1]) × (i − 1) / (n − 2)`; `v` =
`mappingY[side]`. Each segment `k` adds the six u16 indices `{0, 1, 2, 2, 1, 3} + 2k` (table S 0087c2fc). The
width of the line is applied in the vertex shader of `[data]\gfx\fx_20\ui_graphshader.fx`, to which
`UIGraphRenderer::Render` S 004e48a0 passes colour, offset, scale and `lineThickness` as `GRAPH_COLOR`,
`GRAPH_OFFSET`, `GRAPH_SCALE`, `GRAPH_LINETHICKNESS` [known: data; inferred for the order of the four
handles, which the decompiled text shuffles]. Per vertex [known: the shader source]: position, previous and
next point are each multiplied by the scale and moved by the offset (all in UI coordinates, 0..1 of the
screen); `normal(a, b) = normalize((b − a).y, −(b − a).x)`; the vertex is moved by
`normalize(normal(prev, pos) + normal(pos, next)) × side × lineThickness`; then `x' = 2x − 1`,
`y' = −(2y − 1)`, z = 0.5. So `lineThickness` is a half width in screen fractions (0.009 = 0.9 % of the screen
on each side of the curve, not corrected for the aspect ratio or for the angle of a bend). The pixel colour is
the texture sample × vertex colour × `GRAPH_COLOR`, alpha-blended (`SrcAlpha`, `InvSrcAlpha`), no depth test.

### 2.3 Goods bar

`nMenu::GoodInfoPanel` [known] S 00628720, S 006287b0: `selector` button at +0x288, `GoodInfo goodInfos[4]`
(0x680 each, first at +0x6f0), `GoodSetsReader*`, `currentSetIndex` at +0x20f4.
`nMenu::GoodInfo` [known] S 006460d0, S 00645f60: `goodId` at +0x648 (−1 = empty; XML attribute `good`, a hex
good id), colours `textColRed` at +0x64c, `textColOrange` at +0x65c (loaded, not read by the refresh) and
`textColGreen` at +0x66c, child picture `picGood` at +0x198 with its icon image at +0x330, child `label` with
its text at +0x5b8.
`GoodSet`: a vector of `InfoSetGood` (0x30 bytes, good id at +0x2c) at set +0x4c [known] S 00628720.

### 2.4 Settings panel

`nMenu::IngameSettingsPanel` [known] S 00620970, S 00620460, S 00620580: sliders `sliderNear`, `sliderMedium`,
`sliderFar`, `sliderDefense` (value = f32 at slider +0x23c), a **local copy** `NPlayer::GoodPriorities
goodPriorities`, `goodPrioSlots[19]` (buttons `goodprioslot<N>`), `pDragSlot` (`dragslot`; its user value
+0x28 holds the rank being moved, −1 = none), the "not used" texture name (+0xad8) and its rectangle.
`nMenu::GoodArrangementPanel` [known] S 006410e0, S 006413c0: ten `waregroup<N>` buttons (good id as user
value), six pairs slider + building icon (the slider's user value +0x28 = entry index inside the good's
arrangement group).

The simulation objects behind them (`NPlayer::GoodPriorities`, `NPlayer::GoodArrangement`, `NPlayer::Military`)
are laid out in [players-victory.md](players-victory.md) §2.6.

### 2.5 Tooltips

`nMenu::Tooltip` (base; a top-level widget attached to `nUi::Root` when shown) with `kind` at +0x1a0
[known] S 0062bc70, S 006464c0:

| Kind | Class (size) | Template | Source id (the 64-bit user value at `nUi::Tip` +0x40) |
|---|---|---|---|
| 0 | `TooltipBuilding` (0x1a8) | `tipBuilding` | building type id |
| 1 | `TooltipSacrifice` (0x1a8) | `tipSacrifice` | sacrifice id |
| 2 | `TooltipGood` (0x1b0) | `tipGood` | good id |
| 3 | `TooltipSoldier` (0x1a8) | `tipSoldier` | `Unique` id of a settler |
| 4 | `TooltipInfoboxBuilding` (0x1a8) | `tipInfoboxBuilding` | building type id |

One instance per kind is kept in a cache (`TooltipCache_GetOrCreate` S 0062bfd0) and shared by every widget
whose tip names that kind [known] S 00645e90. A widget's `nUi::Tip` holds the provider pointer, a description
string and the source id.

### 2.6 Messages panel `nMenu::Messages` [known] S 005f86a0, S 005f85b0, S 005f73e0

| Offset | Field | Meaning |
|---|---|---|
| +0x198 | `NPlayer::IMessagesListener` face | bound to the local player's message store on the first update |
| +0x1a0 | i32 | number of messages that pass the filters |
| +0x1a4 | i32 `lastMessageCount` | unfiltered count seen at the last poll [inferred: offset] |
| +0x1a8 | u8 `bVisible` | |
| +0x1a9 + type | u8[9] filter | indexed by message type 0..8; the constructor sets all nine to 1 |
| +0x3e0.. | 8 slot buttons (0x3f8 each), labels at +0x23a0 (0x228 each) | |
| +0x35b0 / +0x3a18 / +0x3e80 | three buttons (0x468 each) | scroll up / scroll down / jump to last; made in code by `InitAndAttachToParent` S 005f8fa0 at (10, 35), (10, 60), (10, 85) px with the tooltips `!Scroll up.`, `!Scroll down.`, `!Jump to last one.` (XML children `up`, `down`, `last`; the shipped `last` has `visible="false"`; which position holds: [ingame-ui.md](ingame-ui.md) §3.8.5; §3.5) |
| +0x34e0.. / +0x3520.. | per slot: cell x, y / message id (16 bytes per slot) | |
| +0x35a4 | vector of `Message*` (first / last / end pointers) | the filtered list |
| +0x42e8 | u8 stick-to-newest | |
| +0x42e9 | u8 hovered | read by the world tooltip rule ([ingame-ui.md](ingame-ui.md) §4) |
| +0x42ec | i32 scroll index | first shown entry of the filtered list |
| +0x42f0 | f32 scroll repeat timer | 0.05 s |
| +0x42f4 | f32 expiry poll timer | 1.0 s |
| +0x42f8 / +0x42fc | f32 `scaleMax` / `scaleTime` | pulse of a new row; constructor 5.0 / 0.3, shipped XML 6 / 0.5 |
| +0x4300 | f32 `alphaMin` | constructor 0.1, shipped XML 0.4 |
| +0x4304 | u8 `scaleOnRefresh` | constructor 1, shipped XML false |

Offsets are of the full object; the update function runs on the face at +4 and the listener callbacks on the
face at +0x198. The message record is in [players-victory.md](players-victory.md) §2.7.

### 2.7 Minimap `nMenu::MiniMap` [known] S 005f39b0, S 005f10a0

| Offset | Field | Meaning |
|---|---|---|
| +0x1b0 / +0x1b8 | source rectangle x / y (pixels of the texture) | the visible part of the map image |
| +0x1c0 / +0x1c8 | source rectangle width / height | |
| +0x288 | `NMap::CallbackReceiver` face | slot 4 (visibility region changed) sets `dirty` |
| +0x28c | i32 `refreshCountdown` | frames until the delayed image capture; −1 = idle |
| +0x290 | `nUi::Position` last cursor position | for dragging |
| +0x2a4 / +0x2ac | f32 `textureWidth` / `textureHeight` | size of the full image, copied from the source rectangle at capture |
| +0x2b8 | `nUi::Picture overlays[2]` (0x288 each) | 0 territory, 1 objects |
| +0x7c8 / +0x7cc | u32 row cursors of overlay 0 / 1 | |
| +0x7d0 | `SymbolRenderer` | draws the symbols after the overlays |
| +0x968 | u32 `instanceId` | from a global counter; names the capture texture `minimap_captureCopy<id>` |
| +0x988 / +0x998 | f32[4] `sacrifices_color` / `chests_color` | XML |
| +0x9a8 | u8 `dirty` | constructor: 1 |
| +0x9a9 | u8 `renderFrustum` | constructor: 1; XML attribute `renderfrustrum` |

Symbol list: `nMenu::System +0x48`, a vector of `MinimapSymbol*` (0x14 bytes) [known] S 005f5af0, S 005f5560:
i32 type at +0x00, f32 x at +0x04, f32 y at +0x08, i32 `lifetime` at +0x0c and i32 `remaining` at +0x10, both
copied from the symbol definition's `lifetime` (`MapSymbolData` +0x68). Symbol definitions `MapSymbolData`
(`mapSymbols.xml`, one `symbol` element per type with `type`, `name`, `texture`, `mapping`, `center`,
`lifetime`): texture name at +0x2c, mapping rectangle at +0x48..+0x64 [known] S 005f55a0.

---

## 3. Rules and algorithms

### 3.1 Statistics panel

Opening: `Game::ToggleStatisticPanel` S 005eb780 creates the panel on first use (parent: the HUD root; the
constructor already starts a 0.2 s fade-in). Then: if the panel is visible **and** owns no running animation
(the count at `nUi::Object` +0x13c is 0; the owned-animation list is at +0x134, S 004c3c30, S 004abf70) it
calls the panel's hide slot, which fades it out over 0.2 s (`OnHide` S 006217f0); in every other case (hidden,
or still fading) it fades the panel in over 0.2 s [known]. Senders: `Game::OnButtonClick` (`btStatistics`),
the end dialogs (§3.10), a building row (§3.1.6) [known: the three callers].

#### 3.1.1 Which statistics exist

The player graph shows one of the eight per-player series; the index is the item index of `filter` [known]
S 00621910, S 00622380; labels [known: `menuStatistics.xml`]:

| Index | Label | Series ([quests-sacrifices-stats.md](quests-sacrifices-stats.md) §2.3) |
|---|---|---|
| 0 | `!Regions` | territory percent |
| 1 | `!Buildings` | number of buildings |
| 2 | `!Settlers` | population |
| 3 | `!Goods` | stored goods |
| 4 | `!Military Strength` | military strength |
| 5 | `!Coin Amount` | coin counter (cumulative) |
| 6 | `!Productivity` | average productivity percent |
| 7 | `!Defeated Enemies` | kills (cumulative) |

The inventory graph shows, per good or job, the **cumulative produced amount** history of the viewing player
(`PlayerStatistics::GetGoodHistory`) [known] S 00642590. It is not a stock history: the stock is only shown as
the current number in the rows of §3.1.5 [inferred from the counter rule in quests-sacrifices-stats.md §3.3].

Sampling: every series and every history gets one new element per 600 logic ticks and keeps at most 960
elements (quests-sacrifices-stats.md §3.3). With the 0.1 s tick ([logic-core.md](logic-core.md) §3) that is one
sample per simulated minute and 16 hours of history [inferred]; the slider's end labels are `1H` and `16H`
[known: data].

#### 3.1.2 Time range

`StatisticPanel::OnSliderChanged` S 00621820 [known], for the slider value `v` (0..1):

```
range = (uint(round(v * 900.0 + 60.0)) / 6) * 6        # unsigned integer division; 60 .. 960
graph.SetTimeRange(range)                              # virtual slot 34
```

`SetTimeRange` S 0064bea0 does nothing when the value is unchanged; otherwise it stores it, rewrites the time
labels and the subclass rebuilds its curves [known] S 00643590, S 00642940. Both sliders start at
`value="0"` and the constructor default is 60 [known: data, S 0064bef0]. Each graph has its own range.

Time labels `RefreshTimeAxisLabels` S 0064bd60 [known]:

```
now = round(gameSystem.nextTickTime / 60.0)            # simulated minutes
for i = 6 down to 0:
    label[i] = max(now - (6 - i) * (range / 6), 0)     # range / 6 is an unsigned integer division
```

The time labels are also rewritten every frame by the graph's update (S 0064be30) [known].

Value labels `SetValueAxisMax(max)` S 0064bde0 [known]: `max` clamped to ≥ 0; label 1 shows `max`, label 0
shows `max >> 1`. Label 1 sits at the top of the plot (`pos="48 40"`) and label 0 at half height
(`pos="48 156"`); `textTimeInfo0` has `visible="false"` [known: data]. `textHeightInfo1` carries
`visible="false"` on its `deployment` element, not on the label. `Deployment::LoadFromXml` S 004bcb80 reads
only `pos`, `size`, `offset`, `anchor`, `alignx` and `aligny`; `visible` is read from a widget's own element
by `Object::LoadFromXml` S 004a76c0 [known]. [inferred] The attribute is ignored and the top value label is
drawn.

#### 3.1.3 Curve construction (`nUi::Graph`)

- Points are normalised: x and y in 0..1 of the widget rectangle. `SetPoints` S 006424e0 stores the given
  points unchanged in the graph's list (+0x1c4), smooths a **copy** and rebuilds the line mesh from the copy
  (§2.2) [known]. `LoadFromXml` does the same with the stored points [known] S 004c9940.
- Smoothing `SmoothPoints` S 004c9410 [known]: nothing for fewer than 3 points. Otherwise
  `smoothingIterations` passes; in each pass every interior point moves toward the midpoint of its two
  neighbours **as they were before the pass**: `p += ((prev + next) * 0.5 - p) * smoothingStrength`, for x and
  y; the first and the last point stay. Shipped: strength 0.2, 5 iterations (template `graph` of
  `templates.xml`), for the player curves and for the inventory curves alike: `CreateGraph` applies the
  template by name (§3.1.5) and `StatsGraphInventory::LoadFromXml` S 00642100 loads no child, so the element
  `graph` inside `graphInventory` (`smoothingStrength="0"`, `smoothingIterations="0"`, `color="1 0 1 1.0"`)
  is not read [known for the two functions; inferred for "unused"].
- Draw `Graph::Draw` S 004c7f90 [known]: only if visible, with a texture and a non-empty mesh. Rectangle:
  `x = absX + offset.x`, `y = absY + offset.y`, `w = width * scale.x`, `h = height * scale.y`. Colour = the
  graph colour with alpha × the widget opacity (+0x140). If `alphaani[0] ≠ 0`:
  `alpha *= 1 - (sin(totalSeconds * alphaani[0]) * alphaani[1] + alphaani[1])`. The line width passed to the
  renderer is `lineThickness`; if `lineani[0] ≠ 0` it gets `+ lineani[1] * lineThickness` in the frames where
  `rand() & int(lineani[0])` is 0 [known: disassembly at 0x004c814e..0x004c8163; the conversion is the C
  runtime's float-to-int helper S 006f2af0]. The shipped template sets both
  rates to 0, so neither animation runs [known: data `alphaani="0 0.06"`, `lineani="0 0.1"`]. The mesh is
  drawn between `EnableStencilNoOverdraw(true)` and `(false)` [known]; [inferred from the name] overlapping
  segments of one curve do not add up.
- The template has `clipping="true"` and the plot area `pos="48 34" size="722 240"` inside the 821 × 320 graph
  background [known: data].

#### 3.1.4 Player graph `StatsGraphPlayers::RefreshGraphs` S 00642fe0 [known]

1. For each slot `i` = 0..7: the curve is shown only if `graphEnabled[i]`, the player is active (`bActive`),
   `Player::IsShownInPlayerLists` is true (false only on a campaign map, map type 1, for a player with an empty
   name, S 005be7a0) and the **viewing player has spotted player `i`** (`viewer.spotted[i]`, Player +0x98).
   Otherwise the curve widget is hidden.
2. For each shown player, with `n` = number of samples of series `statisticCategory`:
   - if `n > 1` the point list is resized to `n` and `max` is raised to the largest sample of the **whole**
     series (not only of the visible window); a series with 0 or 1 samples keeps its old point list;
   - `scale.x = pointCount / timeRangeMinutes` (float; `pointCount` is the size of the curve's point list
     after the step above), `offset.x = W - W * scale.x` with `W` the curve
     widget's width: the curve is anchored at the right edge and one sample is `W / timeRangeMinutes` wide, so
     the plot shows the last `timeRangeMinutes` samples and older ones are clipped at the left [inferred for
     the reading of `W`; the two assignments are known];
   - colour = the entry of the RGBA table at S 0087f8c8 (16 bytes per entry) selected by the player's
     `colorIndex` (`Table_0087f8c8_GetEntryForPlayer` S 0060ee20), written to all four colour floats; it
     replaces the colours of the XML children `graph0..7`.
3. `yScale = 1 / max`, with `max = 1` when it is 0. One maximum is shared by all shown players.
4. Points of each shown player: `x_j = j / (n - 1)`, `y_j = sample_j * yScale`, for `j` = 0..n−1 over the whole
   series; then `Graph::SetPoints`.
5. `SetValueAxisMax(max)`.

Nothing is rebuilt when no player is shown. [inferred] When players are shown but none has more than one
sample, `max` keeps its start value (the smallest i32), so the labels show 0; the curves keep whatever points
they had. In the first minute of a free game the graph lists only the own player (the enemy is not spotted yet)
and shows no data; by the end of a match it shows curves [live, 2026-10-12, maintainer].

Category change (`SetStatisticCategory` S 00642d60): the 8 point lists are emptied and the index stored; the
caller then refreshes [known]. A player row's toggle button writes `graphEnabled[playerId]` and refreshes
[known] S 00621910.

#### 3.1.5 Inventory tab

**Rows** (`StatsGoodList::Update` S 00644840, every frame while the list is updated) [known]:

- Goods list (fill mode 0, 22 rows, 11 per line) `FillFromGoodVectors` S 00644430: first every good of the
  viewing player's tribe (`TribeProperty.goods`, script order) whose `type` is 0 (`Ware`); then every entry of
  `TribeProperty.jobs` whose `settlerType` is not 3 (`Soldier`); rows are filled in that order until the list
  is full, the rest are hidden.
- Soldier list (fill mode 1, 6 rows, 3 per line) `FillFromGoodTable` S 006446c0: for class 0 (sword) and
  class 1 (bow), every level of the tribe's soldier ladder (`MilitaryConfig::GetSoldierId(tribe, class,
  level)`), in level order.
- Each row (`StatsGoodInfo::SetGoodData` S 0064c8e0): icon and tooltip text (the good's `name`) from
  `IconConfig` and the good property; the row's colour field (+0x1e4, four floats) = `IconConfig::GetGoodColor`,
  the colour its curve gets; `countDepots` = `pStock.count(good) + pMobileStock.count(good)`
  (Player +0x34 and +0xa0), drawn red (255, 0, 0) when 0, else white; `countOutside` = the trend value of
  §3.2.2, with a leading `+` when positive, red when negative, else white. Counts are those of the player
  the list stored at construction (the local player); the trend is queried for the screen's local player.
- Layout `LayoutItems` S 00644a50: row `k` at pixel `(itemsOffsetX + col * itemsSpreadX, itemsOffsetY + line *
  itemsSpreadY)`; the goods list wraps after `itemsPerLine`; the soldier list starts a new line per class.
  Nothing is laid out when `itemsPerLine` < 1; in that case each row is loaded from its own XML child
  `goodInfo<k>` after the shared `goodInfos` (S 00644ff0). The row count comes from the XML attribute `count`
  (shipped: 22 goods rows with offset 10, 10, spread 50, 80; 6 soldier rows) [known: code and data].

**Curves**: clicking a row (`StatsGoodInfo::OnClick` S 0064c650) toggles the row's marked state and calls
`StatisticPanel::SetGoodGraphShown(good, marked)` [known]:

- on: `CreateGraph` S 00642970 (nothing if the good already has a curve) makes a `Graph`, applies template
  `graph` by name (`Configurable::ApplyTemplate`, which looks only in `templates.xml`,
  [ingame-ui.md](ingame-ui.md) §3.1.3), colour = `IconConfig::GetGoodColor(good)` with alpha **0.9**, stores it
  in the map and refreshes;
- off: `DestroyGraph` S 00642bb0 detaches and deletes it and refreshes.

`StatsGraphInventory::RefreshGraphs` S 00642590 [known], for the viewing player's histories:

1. For each curve: `n` = history length; if `n ≠ 0` the point list is resized to `n` and `max` is raised to the
   largest element with index ≥ 1 (element 0, the seed, is skipped). `scale.x` and `offset.x` as in §3.1.4.
2. `yScale = 1 / max` (1 when `max` is 0); one maximum for all shown goods.
3. Points: `x_j = j / (n - 1)`, `y_j = history_j * yScale` for all `j`, element 0 included. A history of
   exactly one element gives `0 × (1 / 0)`, not a number, as x; the mesh needs two points, so nothing is drawn
   [inferred from the two formulas].
4. `SetValueAxisMax(max)`; with no curve, or only histories of one element, `max` is still the smallest i32
   and both labels show 0.

Because the histories are cumulative, the curves never fall [inferred].

#### 3.1.6 Players and buildings tabs

**Player rows** `StatsPlayerInfo::Refresh` S 00645400 (every frame) [known]: a row with a valid `playerId`
whose player is active, shown in player lists and spotted by the viewer shows: the display name in the player's
colour; the state text `textInWar` in `colRed` if `viewer.IsEnemyOf(player)`, else `textFriendly` in
`colGreen`; the toggle button; the avatar (`Avatar::SetupForPlayer`). Any other row shows only `textEmpty`.
The name colour is the same table entry as the curve colour (§3.1.4). Shipped: `textInWar="!IN WAR"`,
`textFriendly="!FRIENDLY"`, `colRed="1 0 0 1"`, `colGreen="0 1 0 1"`, `textEmpty` = `!EMPTY` [known: data].
There are six rows (ids 0..5) while the graph handles eight slots; players 6 and 7 have a curve but no row and
their curves cannot be switched off [inferred from the two loop bounds].

**Building rows**: the constructor makes one row per entry of the viewing tribe's `TribeProperty.buildings`
whose property has `constructionTime > 0` and `size ≠ 0`, in tribe order [known] S 00621d20. `OnXmlLoaded`
S 006225d0 loads each row from the XML element `building` and places row `k` at pixel `(bldOffset.x + col ×
bldSpread.x, bldOffset.y + line × bldSpread.y)`, starting a new line after `numBldPerLine` rows (shipped
`26 22`, `128 128`, 7) [known: disassembly].

**Tech tree tab.** The same function shows the child `techtree<TribeName>` of the viewing player's tribe
(`techtreeBavarian`, `techtreeEgyptian`, `techtreeScots`: 1024 × 1024 pictures `techtree_bavaria.dds`,
`techtree_egypt.dds`, `techtree_scots.dds`, all `visible="false"` in the XML). They are children of `tab3`,
the fourth tab page (`tabButton3`, `!TECHTREE`), which exists because the XML sets `count="4"` (§2.1). The
tab buttons are `!STATISTIC`, `!INVENTORY`, `!BUILDINGS`, `!TECHTREE` [known: code and data]. The tab opens
like the other three and shows a text-only tree, with different colours for products, end products and
buildings [live, 2026-10-12, maintainer].

`StatsBuilding::Refresh` S 00643f60 [known]:

- icon (`IconConfig::ApplyBuildingIcon`, tribe and type) and the localised type name;
- `m_textHouse1` = `Player::GetBuildingCount(type)`, `m_textHouse2` = `Player::GetConstructionCount(type)`;
  row opacity 0.4 when their sum is < 1, else 1.0;
- if the property's `health` (+0x8c) is < 1:
  - if `productivity` (+0xf4) is false, or the type has neither a `plantingDeposit` nor goods in slot 0: both
    bars, `m_textProducing` and `m_iconProducing` are hidden;
  - else `m_progress1` is hidden, `m_progress0` fill = `avgProductivity * 0.01` and `m_textProducing` is
    `trunc(avgProductivity + 0.5)` followed by `%`, where `avgProductivity` = 100 × the mean of the
    productivity entries (quests-sacrifices-stats.md §2.3) of the player's **finished** buildings of that type
    (both construction floats ≤ 0), 0 when there is none (`GetAverageBuildingProductivity` S 00533160);
    `m_textProducing` and `m_iconProducing` are shown;
- else (a building with hit points) `m_progress0` is hidden, `m_progress1` fill = the mean of
  `Hitpoints::GetRatio` over the player's buildings of that type (finished or not), 0 when there is none, and
  `m_textProducing` is `trunc(mean × 100.0)` followed by `%` (`GetAverageBuildingHealth` S 00533e60);
  `m_textProducing` and `m_iconProducing` are shown. That mean also includes buildings of another type when the other
  type is a `territoryBuilding`, the building's tribe (+0x34) differs from its owner's tribe and both types
  have the same `size` mask, i.e. captured buildings of another tribe count under the own type of the same
  size [known for the test; inferred for the reading].

Click on a row (`StatsBuilding::OnButtonClick` S 00643a90) [known]: `FindNearestBuildingOfType(viewer, cell
(0, 0), type, 0, 9999999)`; if one exists the game selection is reset and set to it, the selection cell is
copied into `MenuSelection`, the selection UI is refreshed and the statistics panel is toggled (closed, by
the rule of §3.1). No command. [inferred] The search starts at cell (0, 0), not at the camera, so "nearest"
means nearest to the map origin.

### 3.2 Goods bar and the stock / trend query

#### 3.2.1 The bar [known] S 006460d0, S 006287b0, S 00628720, S 00628780

- Four entries; entry `i` shows good `i` of the current set. On entering a match the set with index
  `currentSetIndex` of the local tribe is applied (`RefreshGoodSet`, called by `Game::OnEnter`).
- `selector` click: `currentSetIndex += 1`, wrapping to 0 at `CountSetsForTribe(tribe)`; apply.
- Per frame, for an entry with a good: the icon from `IconConfig` (the picture is hidden when the icon map has
  no entry for the good); the text `"<amount> / <delta>"` with `+` before a positive delta; the colour
  `textColRed` when `amount < -delta`, else `textColGreen` (`textColOrange` is loaded but not used); the
  tooltip is kind 2 with the good's `name` as description and the good id as source (§3.4, S 00645e90). An
  entry whose `goodId` is −1 is not refreshed.

#### 3.2.2 `GameQuery_GetPlayerGoodStockAndPending(player, good)` S 00533c40 [known]

```
amount = player.pMobileStock.count(good) + player.pStock.count(good)
delta  = 0
if good == tribe.workerToolGoodId:                       # TribeProperty +0xbc
    for each entry of village.orderSystem's list (+0xc .. +0x10) owned by the player:
        job = entry[+0x48]
        if job != -1 and GoodProperty(job).costs has a positive amount of good:
            delta -= 1
for each entry of the transport system's list (+0x448 .. +0x44c) owned by the player with entry[+0x48] == good:
    if the entry's target id (+0x18 / +0x1c) is negative, or the target building's property is not a depot:
        delta -= 1
for each building of the player:
    if property.HasGoods(0) and property.GetGoods(0)[0] == good and building.workers.count > 0
       and worker 0's virtual slot +0x28 returns true:
        delta += 1
```

So `delta` = (producing buildings whose first worker reports "busy") − (open requests for the good that do not
lead into a depot) − (for the tool good: queued jobs whose recipe needs a tool) [inferred for the three
readings; the list owners and the tested fields are known]. It is a count of buildings and orders, not a rate.
[TODO] not established: the exact meaning of the worker's slot +0x28 and of the two lists; a read of the list
element classes in [streets-transport.md](streets-transport.md) / [settlers-jobs.md](settlers-jobs.md) terms
settles it.

Used by the goods bar and by both statistics lists (same numbers in both places).

### 3.3 Settings panel: priorities, military sliders, distribution

Structure and the confirm sequence are in [ingame-ui.md](ingame-ui.md) §3.8.2. Rules added here:

**Transport priority list** [known] S 00620460, S 00620970, S 00620580, S 00620c90:

- 19 slots = ranks 0..18. Slot `r` shows `GoodPriorities::GetGoodAtRank(r)` of the **local copy**; −1 → the
  slot is disabled and drawn with the "not used" texture rectangle; else the good's icon, the good's name as
  tooltip, enabled.
- Ranks need not be a permutation [known] S 005c2690, S 005c27c0: the default ranks of the Scots are not
  (several goods share the ranks 0, 4, 5 and 13). `GetGoodAtRank` returns the first entry in list order holding
  the rank, so of goods sharing a rank only one has a slot. `MoveRank(from, to)` walks every entry: each entry
  holding `from` gets `to`, and each entry whose rank lies between the two (inclusive of `to`) moves one step
  toward `from`'s side (−1 when `from < to`, else +1); so all goods sharing the picked-up rank move together,
  including those the panel does not show.
- Clicks are handled only while the panel is visible. Click on a slot while nothing is picked up: the drag
  widget gets `rank = slot index`, becomes visible and shows that good's icon. Any click in the panel other
  than `btConfirm` while a rank is picked up: the first slot whose hover flag (+0x144) is set is the target;
  if it differs, `GoodPriorities::MoveRank(from, to)` on the local copy and the slots are redrawn; the drag
  widget is hidden and reset to −1 in every case (also when no slot is hovered). `CancelSlotDrag` S 00620c90
  plays `uiCancel`, hides the drag widget and resets it. Its one caller S 00620d60 is the panel's override of
  the event-face handler that `nMenu::Dialog` fills with `OnMouseButton1Down` S 0060e440: while a rank is
  picked up it cancels the drag and reports the event handled, otherwise it runs the dialog's handler
  [known]. The dialog's handler calls the panel's virtual slot +0x8c unless the dialog's lock value (+0x13c)
  is set [known] S 0060e440. [inferred] Button 1 is the right mouse button (event-face slot 15,
  [ui-toolkit.md](ui-toolkit.md) §2), so a right click drops a picked-up good back, and a right click with
  nothing picked up closes the panel like any unlocked dialog (slot +0x8c read as "hide").
- The "not used" slot picture is texture `ui_ingame.dds`, rectangle 688, 856, 40 × 40 [inferred: the
  constructor's plate comment; the constants were not read in the code].
- Nothing reaches the simulation until `btConfirm`; closing the panel otherwise discards the local copy
  [inferred: no other sender].

**Sliders**: on `btConfirm` the float at slider +0x23c is sent as raw bits, without conversion or clamping, in
this order: `sliderNear` → `SendSetMilitaryValue2Command`, `sliderMedium` → `SendSetMilitaryValue1Command`,
`sliderFar` → `SendSetMilitaryValue0Command`, then the local priority copy (`SendSetGoodPrioritiesCommand`),
then `sliderDefense` → command `0x20011`; the panel then fades out over 0.2 s [known] S 00620970. The
executors store the values unchecked ([game-commands.md](game-commands.md) §3.4).

**Goods distribution** [known] S 006410e0, S 006413c0, S 006412f0:

- A `waregroup` button is made for each arrangement group of the local player (in group order) that has **more
  than one unlocked entry** (`CountUnlockedEntries`: entries whose building type does not have
  `arrangementLocked`), at most 10; the button carries the group's good id and the good tooltip (kind 2).
- Clicking one marks it and unmarks the other nine (`HandleWaregroupClick` S 00641570), then fills up to 6
  pairs with the group's unlocked entries in entry order: building icon and name tooltip, slider value = the
  entry's `weight`, slider user value = entry index; unused pairs are hidden. Further unlocked entries are
  not shown.
- Moving a slider: if a group button is selected (visible and marked, `GetSelectedGoodId` S 006412a0) and its
  good is found among the player's groups, send `0x2001F` (good id, entry index, slider float bits) at once.

**Tools and soldier training.** The game has no separate tool or training panel [inferred: no such class
among the `nMenu` classes]. Tool supply is steered through the transport priority and distribution lists above
like any good; soldier training is switched per barracks in `InfoBoxCasern` (action buttons 15..20 and the
soldier buttons → `0x2001E`), and stock acceptance per depot in `InfoBoxDepot`
([ingame-ui.md](ingame-ui.md) §3.6).

### 3.4 Tooltips

Timing, the plain text popup and the list of kinds are in [ingame-ui.md](ingame-ui.md) §3.2.2. `Tooltip::Open`
S 006464c0 [known]: if the popup is not already attached, attach it to `nUi::Root`, apply the template of §2.5,
clear `canReceiveFocus`, fade in over 0.2 s. `Tooltip::Update_adjC` S 006463c0 closes the popup when its
visibility slot reports false while it is attached [known].

**Good slots.** `FillGoodSlots(list, count, prefix)` S 00646830 with `ApplyGoodSlots` S 006465e0 [known]:
slot `i` (0 ≤ i < `count`) is the child named `<prefix><i>` (`costs0`, `needs4`, `good2`, …; widget kind 0xe)
and its amount label is that child's own child `goodnum` (kind 9). For `i` < min(`count`, list length) the
slot is shown, gets the good's icon from `IconConfig` (a good without icon entry gets the source rectangle
0, 0, 1024, 1024 of the current texture) and `goodnum` shows the amount as a plain integer. The remaining
slots are hidden; list entries beyond `count` are dropped.

**Kind 0, building** `TooltipBuilding::ShowFor` S 00647150 [known]:

- `lbName` = the type's name (localised);
- 4 slots `costs` = `BuildingProperty::GetAllCosts`;
- products: the first good of goods slot 0 if the type has one, else the `good` of its `plantingDeposit` if
  that is not −1; plus the first good of goods slot 1 if present; each with amount 1, into 4 slots
  `production`;
- 5 slots `needs` = the recipe (`costs`) of the **first** product, shown only if there is a product and
  (`ignoreGoodCosts` is false or `casern` is true); else empty.

**Kind 1, sacrifice** `TooltipSacrifice::ShowFor` S 00647740 [known]: `lbSacrificeName` = the sacrifice name;
`description` (a text block, kind 0x18) = label `!Description:` + the sacrifice's description key
(`SacrificeProperty::GetDescTextKey`), both localised, in the two-colour format below; 4 slots `good` = its costs; `runningtime` = duration, `researchtime` = research
duration, formatted by S 00647590: value < 100 → `!immediate`; value ≥ 100000 → `-`; else
`"%02d:%02d"` of `(value / 10) / 60` and `(value / 10) % 60`, i.e. the value is in logic ticks of 0.1 s
[inferred for the unit]. `lbResearchTime` and `researchtime` are visible only when the research duration is
positive.

**Kind 2, good** `TooltipGood::ShowFor` S 00647d20 [known]: `lbGoodName` = the good's name; `lbBuildingName` =
label `!Produced by:` (S 007c88a0) + the localised names of the viewing tribe's producer buildings
(`Economy_CollectProducerBuildings(tribe, good)`) joined with `", "`, or `-` when there is none; 4 slots `good`
= the good's recipe.

**Kind 3, soldier** `TooltipSoldier::ShowFor` S 00648070 [known]: nothing unless the id resolves to a settler
of type `Soldier`. `lbName` = the soldier good's name; `lbHealth` = `"<current> | <max>"`; `lbArmor` =
`"<base> + <total - base>"` when `Soldier::GetArmor()` exceeds the property's `armor`, else the total;
`lbDamage` the same with `GetHitDamage()` and `hitDamage`; `lbRank` = localised `!RANK`, a space, and
`FindSoldierLevel(viewer tribe, soldier good) + 1`.

**Kind 4, info box help** `TooltipInfoboxBuilding::ShowFor` S 00648700 [known]: `lbName` = the type's name;
`lbDesc` = the text of key `!<type name>_tipp_lang`; `lbDepends` = the localised names of all building types
of the viewing tribe that consume a product of this type (products as for kind 0;
`Economy_CollectConsumerBuildings`), each once, ordered by building type id, joined with `", "`.

**Two-colour line** `nMenu_Tooltip_FormatLabelValue` S 00646e90 [known]: the string
`<r g b a>label <r g b a>value` (one space between the label and the second tag) using the text block's colour
tag; two flags choose whether the label and the value are looked up in the text tables. The colours are two
global RGBA constants in initialised data: label (0.8, 0.8, 0.7, 1.0) at S 008809a0, value (1, 1, 1, 1) at
S 008809b0 [known: the bytes of the image; the only reference to S 008809a0 is this reader].

**Other tooltip texts** [known unless tagged]: statistics good rows and priority slots: the good's `name`
(S 0064c8e0, S 00620460); distribution building icons: the building type name (S 006413c0); message rows:
`!Left Click for go to, right click for delete.`; HUD buttons: the `<tip description>` keys of
`menuingame.xml` (e.g. `!game_ui_openquestlog`, `!game_ui_haus`, `!game_ui_lines`, `!game_ui_v`); the world
hover tooltip: [ingame-ui.md](ingame-ui.md) §3.4. Text keys starting with `!` are looked up in the text tables
([ingame-ui.md](ingame-ui.md) §3.10).

### 3.5 Message list

Rows, icons, alpha and click behaviour: [ingame-ui.md](ingame-ui.md) §2.10, §3.8.5. Which event raises which
message: [quests-sacrifices-stats.md](quests-sacrifices-stats.md) §3.6.2. Rules added here, all [known]
S 005f86a0, S 005f73e0, S 005f85b0 unless tagged:

1. The panel does nothing while `ai::player::PlayerTable::HasActiveType2` is false (no active local human player).
2. **New messages** are detected by comparing the store's message count with the last count. If it grew and
   the panel is visible, the **newest** message decides: type 1 → sound `uiMessage1`, minimap symbol 1; type 5
   → `uiMessage0`, symbol 5; any other type → `uiMessage0`, symbol 0. The symbol is added only if the message
   has a cell (x ≠ −1), at that cell. Only one sound and one symbol per poll, even if several arrived
   [inferred].
3. **Filter**: a message is listed when its type is < 9 and the filter byte of that type is set. All nine
   bytes start set. `OnFilterButtonToggled` S 005f8e80 flips the clicked entry's mark, writes it to the filter
   byte whose index is the entry's user value and refreshes the list when the byte changed; it then tints every
   entry's text white when marked, else (0.8, 0.8, 0.8, 1). The seven check entries of `cbMessages` carry the
   user values 1..7 ([ingame-ui.md](ingame-ui.md) §3.4, S 005ecaf0); types 0 and 8 (letters) have no entry
   and are always listed.
4. **Scrolling**: `count` is the filtered count and the window is 7 rows (the panel has 8 slot widgets). A
   click on `last` jumps to `count − 7` (not below 0) and sets stick-to-newest (the shipped `last` button is
   hidden). While the `GameAction` query +0x34(0) is true ([inferred] primary mouse button held) and the repeat
   timer is 0: `up` pressed decrements the index and
   clears stick; else `down` pressed increments it and sets stick when the index equals `count − 7`; either
   restarts the 0.05 s timer. After any change: with stick set the index becomes `count − 7`; then it is
   clamped to `0 .. count − 7` (0 when `count` < 7). `down` is **shown** while `index < count − 7`, `up` while
   `index > 0` (visibility slot, not an enabled flag).
5. **Clicks** on a row (only in a frame without a new message, on a visible slot that holds a message): left
   is tested first → set the record's read flag (+0x78) and, if it has a cell, put the camera into standard
   mode (if it is not) and `FocusOnCell`; else right → `Messages::RemoveById`, sound `uiRemove`.
6. **Expiry**: once per **1.0 s** of frame time `Messages::RemoveExpired` is called on the local player's
   store; it removes every record for which `!(timeRemaining > 0)` holds (S 005c1c10). The remaining time
   itself falls in the simulation (players-victory.md §3.9).
7. **Row opacity**, every frame, for the slot button and its label: `alphaMin + (1 − alphaMin) ×
   timeRemaining / 600` (`timeRemaining` = the record's float at +0x18).
8. **Pulse**: the listener's "added" callback refreshes and restarts a scale animation `scaleMax → 1.0` over
   `scaleTime` on the row's button and label (S 005f8c30); the "updated" callback does the same only when
   `scaleOnRefresh` is set (S 005f8dd0; shipped false).
9. **The store behind the list**: `Messages::AddWithPosition` S 005c2360 appends a record with no limit on the
   count, so the list grows until the expiry removes records; `PlayerMessages_SendOrRefreshToPlayer` S 005c0270
   looks for `FindMatchingWithArg(type, text, arg, cell, 1)` and, on a match, sets its `timeRemaining` back to
   600 instead of adding a record ([quests-sacrifices-stats.md](quests-sacrifices-stats.md) §3.6.1).
10. **Rows** (geometry, row text, the code-made scroll buttons): [ingame-ui.md](ingame-ui.md) §3.8.5;
   `Messages::Refresh` S 005f8b90 applies the nine filters and the 7-row window with stick-to-newest.

In a network match the three NComm message callbacks of the game screen (player joined / left / kicked
notices and errors) all become a letter (type 8) of the local player: `Game::ShowCommMessageAsLetter`
S 005eb120 → `PlayerMessages_SendLetterToPlayer` [known for the call; inferred for the list of notices,
[network-session.md](network-session.md)].

### 3.6 World overlays

#### 3.6.1 HUD overlay widgets (`overlayPanel`)

Creation, categories, positioning and the colour thresholds: [ingame-ui.md](ingame-ui.md) §3.8.6.
`OverlayBuilding::UpdateFromBuilding` S 006403c0 decides the warning icons as follows [known], with
"under construction" = one of the two remaining-work floats of the construction object > 0:

| Child | Visible when |
|---|---|
| `hammers` | under construction |
| `notShooting` | property `catapult` (+0xb0) is set and the building's production is not enabled (paused catapult) |
| `noWorker` | under construction: the construction is not paused (construction +0x78 = 0) and the id at construction +0x40 / +0x44 is negative ([inferred] no builder assigned). Finished: `workerLimit` ≥ 1 and the building has no worker |
| `productionStopped` | only when `noWorker` is not shown. Under construction: the construction is paused (+0x78 ≠ 0). Finished: property `productivity` is true, the type has goods in slot 0 or a `plantingDeposit`, and production is not enabled |
| `noCoins` | property `casern` is set, the type is not both `depot` and `territoryBuilding` (i.e. a barracks, not a headquarters), and the byte at +0x14 of the object at building +0x124 is 0: the `enabled` flag of the `SoldierUpgrade` embedded at +0x10 of the building's `SoldierTraining` ([military.md](military.md) §2.5), i.e. promotion with coins is switched off in that barracks [known for the test; the field identity rests on military.md] |
| `ship` (+0x1280; name string at S 007f6f0c) | hidden at the start of every update of this function; [TODO] not established: who shows it |

The widgets are, in object order, `hammers` (+0x440), the name `label` (text at +0x860), `progressBar`
(+0x8f0), `textProductivity` (text at +0x11f0), `ship` (+0x1280), `notShooting` (+0x1508), `noWorker`
(+0x1790), `productionStopped` (+0x1a18), `noCoins` (+0x1ca0), `swordsMen` (+0x1f28), `bowMen` (+0x23d8)
[known: S 0063ef50 loads them in this order; the offsets are those the update writes to].
[TODO] not established: the exact conditions of the soldier counts and of the hit-point bar on military
buildings, and of `exclamation0..2` (the same function, second half; the decompiled text there is not
reliable enough to quote; a disassembly read of S 006403c0 from 0x00640533 on settles it).

Under construction the bar shows `((1 − remainingA) + (1 − remainingB)) × 0.5` [known] and
`textProductivity` an integer followed by `%` ([inferred] that value × 100; the operand of the conversion is
not visible in the decompiled text). `swordsMen` and `bowMen` are hidden. The 10 missing-material icons
come from `UpdateMissingGoodIcons` S 0063fd10, or are all hidden when a byte flag is set that the decompiled
text does not resolve ([TODO] not established: that flag; the disassembly of S 006403c0 settles it).

#### 3.6.2 Overlays drawn by the renderer (pointers)

| Overlay | Owner | Where specified |
|---|---|---|
| Build-placement icons on the cells (info-map mode; not while placing a building) | `ConstructionMapRenderer` | [rendering.md](rendering.md) §3.14; the flags per cell: [map-resources.md](map-resources.md) §3.5 |
| Selection markers (decals under the selected object, its targets) | `CMapRenderer::UpdateSelectionMarkers` | [rendering.md](rendering.md) §3.14 |
| Territory borders | renderer | [rendering.md](rendering.md) §3.8 |
| Fog of war / unexplored area | renderer | [rendering.md](rendering.md) §3.7, [map-resources.md](map-resources.md) §3.7 |
| Flags on military buildings and the headquarters | `S2CG::CMilitaryFlagRenderer` | [rendering.md](rendering.md) §3.8 ff. (section on the flag meshes); summary below |
| Resource signs (geologist results) | doodads of type `Sign` | [map-resources.md](map-resources.md) (doodads; lifetime 3000 ticks, empty sign 30000, [properties-data.md](properties-data.md)) |

Military flags, as far as the HUD meaning goes [known] S 0055fd00, S 006d2820, S 006d2d80: a building gets a
flag when its property has `territoryRange` (+0x94) > 0 and `soldierLimit` (+0x98) ≠ 0
([properties-data.md](properties-data.md) §2 for the two fields), or is a headquarters (`depot`, `casern` and
`territoryBuilding` all set). It is drawn only for finished buildings (both construction floats ≤ 0), in the
owner's colour (`ai::player::Player::GetColorEntry`). Mesh 0 (`[data]\buildings\MilitaryFlagInactive.KEX`) when
`Building::IsOccupied` is false or the byte at +8 of the object at building +0xc4 is 0 ([inferred] the flag
component's "active" byte); else mesh `1 + count` (`MilitaryFlagSword00..10.KEX`) or `12 + count`
(`MilitaryFlagBow00..10.KEX`), `count` = `Military::GetFlagSoldierCount()`: the flag shows the garrison size
to every player. The bow set (+11) is taken when the i32 at +0x68 of the building's `Military` object is not 0
[known: disassembly of S 006d2820 at 0x006d2a17]; that field is the wanted soldier kind, 0 sword / 1 bow
([military.md](military.md) §2). The flag texture is one of three, `MilitaryFlag1.dds`..`MilitaryFlag3.dds`
(index 0..2, loaded by S 006d2ec0): for a building for which `Military::IsMilitaryBuilding` S 0055fb80 is
true the index is `Military::GetProximityZoneA` S 0055fbb0 when that is ≥ 1, else 0; the zone is −1 when the
byte at +8 of the object at building +0xc4 is 0, else 2 for a distance value (`Military` +0x5c) < 19, 1 for
19..24, 0 for > 24 [known] S 0055fbb0, S 00553f20. So the texture shows how close the nearest enemy is
[inferred: the reading of +0x5c as enemy distance rests on [military.md](military.md)]. Colour and texture
are not set in the shadow pass.
[TODO] not established: whether a separate marker exists for "attackable" buildings beyond the
selection kinds 6 / 7 and the attack slider ([ingame-ui.md](ingame-ui.md) §3.6); an observation in the game
settles it.

`btInfoMap1` (space) toggles info-map mode with a 0.2 s colour fade; `btInfoMap2` / `btInfoMap3` toggle overlay
categories 0 / 1 ([ingame-ui.md](ingame-ui.md) §3.4, §3.8.6).

The build-placement icons have no switch of their own [known]: the renderer draws them only while the alpha of
its overlay tint is > 0 (S 00688c40). The tint is 0 from the `CMapRenderer` constructor S 006890f0 and is changed
only by `nMenu::Game::StartOverlayColorFade` S 005eac30, called by `btInfoMap1` (`OnButtonClick` S 005eb850) and by
the cinematic screen (S 005fb3e0, S 005faee0). The fade is linear over 0.2 s from the last drawn colour to
`(1, 1, 1, on ? 1 : 0)`, and `nMenu::Game::Update` S 005efea0 does not advance it while the game is paused.
Opening the build menu on a cell (placement, [ingame-ui.md](ingame-ui.md) §3.5) does not show them.

### 3.7 Minimap

**Image** [known] S 005f3dd0, S 005f16d0, S 005f1980: the scene supplies a render target with the map; when
the refresh countdown reaches 0 the widget copies it into a temporary texture, applies the exploration mask
(every pixel whose map cell is unexplored for the local player becomes 0 = transparent black, every other
pixel gets alpha 0xff), copies the result into its persistent texture `minimap_captureCopy<id>` and sets
`textureWidth / Height` from the current source rectangle. The countdown is 0 after construction and after
the XML load, so the first capture happens in the first update; each update then decrements it down to −1.
The countdown path (virtual slot 34, S 005f1070) first has the scene render the image at 512 × 512; the copy
and mask step alone (slot 35) is repeated by `Render` whenever `dirty` is set (§4), [inferred] which is how
newly explored area appears on the image.
The mask is applied only while the byte Game +0xfff8 is set; [inferred] it is constant true (the plate
comment of S 005f16d0 records one writer, the `Game` constructor storing 1; that search was not repeated).
The widget is drawn through the round mask `ui_mask_minimap.tga` [known: data]. Nothing of the minimap is
drawn while the developer variable `ui.MiniMapRender` is false, and no symbol while `ui.MiniMapRenderSymbols`
is false [known] S 005f49e0, S 005f5bb0; both default to true (value bytes 1 at S 0087f5d0 and S 0087f61a
in the image) [known].

**Overlays** [known] S 005f49e0, S 005f3fc0, S 005f4390: rebuilt completely in `Render` when `dirty` is set
and no capture is pending; `dirty` is set by the map's "visibility region changed" callback (S 005f11a0) and by
`MarkDirty` (building created / removed, sacrifice started: [ingame-ui.md](ingame-ui.md) §3.8.5). Every frame
the two overlay pictures get the minimap's source rectangle × 0.5 (their textures have half the resolution).

- Overlay 0, territory: per cell, owner −1 → 0; else the owner's colour as ARGB, from
  `ai::player::Player::GetColorEntry` S 005be2c0, the table `g_PlayerColors` the military flags use (§3.6.2);
  `& 0x99ffffff` (alpha 0x99)
  unless the cell's grid state has bit 0x20 (territory border); alpha 0 when the cell is unexplored for the
  local player.
- Overlay 1, objects: the loop runs over the pixels of the overlay texture, row by row; pixel (px, row) maps
  to the cell (px × mapWidth / textureWidth, and the row likewise, y flipped). A cell whose object-layer-1
  entry is a valid id (a building): `0xffaaaaaa`; a type with `territoryBuilding`: `0xffffffff` if it is also
  a `depot`, else `0xffff8888`; a type without `territoryBuilding` whose `workingMode` (+0x80) is 9:
  `sacrifices_color`; a chest on that cell (`LogicChestSystem::FindChestAt`, tested only for cells that hold
  a building) overrides all of them with `chests_color`. Alpha is forced to 0xff, or to 0 on an unexplored
  cell. The colour is written to four pixels: (px, row), (px − 1, row), (px − 1, row − 1), (px, row − 1). A
  pixel whose cell holds no building gets 0 (only that pixel). The function contains a second loop (it would
  write `0xffffffff` / `0x00ffffff` by exploration); it is entered only when the map width, as a float, is
  negative, so it never runs [known: disassembly of S 005f4390, the `FLDZ` / `FCOMP` test at 0x005f44d4].
- Shipped colours: `sacrifices_color="1 1 0 1"`, `chests_color="0 1 0 1"` [known: data].

Coordinates: cell (x, y) → texture (x / mapWidth, 1 − y / mapHeight), then into the current view
(`MapCellToViewPos` S 005f20c0) [known].

**Symbols** `RenderSymbols` S 005f5bb0 [known], all tinted (1, 1, 1, widget opacity), each drawn centred on its
cell with the texture rectangle of `mapSymbols.xml` and the minimap mask:

1. symbol 3 for every ship of the local player whose two movement floats (ship +0x20 → +0x48, +0x4c) are ≤ 0;
2. symbol 4 for every fight in which the local player is one side and whose id is valid, at the fight cell;
3. symbol 4 at **half opacity** for every other valid fight, except those whose two sides are both enemies of
   the local player (not drawn): fights of allies are shown dimmed;
4. the camera frustum, if `renderFrustum` (default true; the shipped XML does not set it);
5. the list symbols (messages, `menu.addMinimapSymbol`). `MinimapSymbolList_Add` ignores a negative x or y
   (S 005f5af0). `MinimapSymbolList_TickExpire` S 005f2690 decrements `remaining` once per menu update
   ([ingame-ui.md](ingame-ui.md) §4) while it is positive and removes the symbol when it reaches 0; a negative
   lifetime is permanent. Shipped `mapSymbols.xml`: types 0 `Message`, 1 `Military` and 5 `Chest` have
   `lifetime="100"`; 2 `Quest`, 3 `Ship`, 4 `Fight` have −1; all use texture `ui_ingame4` and `center="2 3"`
   [known: data].

**Input** [known] S 005f18e0, S 005f2130, S 005f2390, S 005f1af0, S 005f1520:

- Press (left button): store the cursor position, move the camera to the map point under the cursor
  (`u = srcX / texW + cursorX × srcW / texW`, the same for v; x = u × width, y = height − v × height, in map
  vertex units (`g_MapVertexWidth` / `g_MapVertexHeight`), each clamped to `0 .. size − 1`;
  `Camera::FocusOnVertex`) and run the base press handler. [inferred] for the two multiplications, which the
  decompiled text hides in float-to-int conversions.
- Move while hovered: with the pan button held (event face byte +0x13; the middle button per
  [ingame-ui.md](ingame-ui.md) §3.8.5) the source rectangle moves by −cursor delta × source size, clamped to
  `0 .. texture size − source size`; else with the left button held the camera follows the cursor.
- Wheel while hovered: `factor = (15 − delta) / 15.0`; a factor < 1 is refused when the source width is below
  `textureWidth / 10` or the source height below `textureHeight / 10`; else the source rectangle is scaled
  around the cursor point, its size capped at the texture size and its position clamped inside the texture.

### 3.8 Quest and sacrifice panels (summary)

Both are specified in [ingame-ui.md](ingame-ui.md) §3.8.4 (quest lines, quest log) and §3.8.9 (sacrifice bar,
target chooser); the simulation side is [quests-sacrifices-stats.md](quests-sacrifices-stats.md) §3.1, §3.2.
Data points used by a reimplementation [known: `menuingame.xml`]: `questInfo` is 400 × 180 at bottom right,
offset 0 −300, with lines 16 px apart; `questlog` has `questsXOffset="30"`; `sacrificePanel` has
`itemsSpreadX="50"`; the target chooser's entry is 100 × 20. The only command of the two panels is `0x20026`
from the target chooser; the quest panels send nothing.

### 3.9 Chat in a match

Widget: `nUi::ChatSystem` at Game +0xcc88 (template `LobbyChat`, 320 × 384 at bottom left, offset 4 −250,
clipping on) with one channel `Chat` (id 1) [known: data; [ingame-ui.md](ingame-ui.md) §3.4].

**Sending** (`Game::OnKeyDown` S 005ec340, key Enter) [known]:

1. Input not focused and the tutorial panel hidden: show the chat opaque and focus an empty input line.
2. Input focused: offline (NComm role 0) the line is first compared with the five cheat strings
   ([ingame-ui.md](ingame-ui.md) §8). Then, whatever the result, the line is sent: `SendTeamChat` if the Shift
   flag (Game +0xffe0, set on Shift down, cleared on Shift up) is set, else `SendChatToAll`; the input is
   cleared and the widget faded out over `chatFadeOutTime`.

There are exactly two channels: **all** and **allies**; there is no per-player whisper in a match [inferred:
no third sender]. An empty line is not sent (`SendChatToAll`, [network-session.md](network-session.md)).

**Receiving** (`Game::OnChatToAll` S 005ef320, `OnChatToAllied` S 005ef530) [known]: the line
`"<sender name> (<tag>): <text>"`, with `<tag>` the localised `!ALL` or `!TEAM`, is added in white (1, 1, 1, 1)
with `ChatSystem::AddText(channel −2, sender's player index, line, colour)`; the widget is shown opaque and,
unless the input line has focus, faded out over `chatFadeOutTime` (shipped 15.0 s). A team line arrives only
at clients for which the session reports sender and receiver as allied (filtered before the HUD,
network-session.md). The pause key sends the text of `!Pause` to all ([ingame-ui.md](ingame-ui.md) §3.3.3).

`ChatSystem::AddText` S 004ae200 [known]: channel id 0 is ignored, −1 adds the line to every channel's log,
−2 (or the id of the active channel) adds it to the **active** log, any other id to the first channel slot
with that id, and only if that slot has a log (the search stops at the first match); an unknown id is dropped. The sender's player index is stored with the line.

`chatFadeInTime` (shipped 0.1, Game +0xb09c) is written by the `Game` constructor S 005ee5d0 (0.1) and by the
XML load S 005ecaf0 [known]; [inferred] nothing reads it: the decompiled program has no other reference to
the field, also not through the offsets of the screen's other faces, and the chat is shown opaque at once.

### 3.10 Defeated player, observers

There is no observer or spectator mode in the client [inferred: no such state in `nMenu::Game`, and the
flow below]. When the local player's victory state becomes non-zero ([players-victory.md](players-victory.md)
§2: 1 eliminated, 2 lost, 3 quest failed), `Game::Update` opens the `Defeat` dialog
([ingame-ui.md](ingame-ui.md) §3.9). `Defeat::LoadFromXml` S 005fe6c0 sets the title / text from
`defeatTitle` / `defeatDesc` and calls slot +0x20 of `btContinue` with 0 [known]; slot +0x20 (index 8) of the widget
vftable is `SetEnabled` (base S 0049fdd0, button override S 004af6d0), slot +0x24 is `SetVisible`
S 004a1090, so "Continue Game" stays visible and is disabled [known for the slot order in the vftable at
S 007f73fc; inferred that the button's vftable keeps it]. The remaining button `btEnd` (`!Quit`) opens the
statistics panel with leave-on-close; closing
it leaves the match [known] S 0061ff50, S 006217f0. So a defeated player sees the final statistics (all tabs,
with the "spotted" restriction of §3.1.4 still applied) and then leaves; the simulation of the others goes on
without that client's input ([network-session.md](network-session.md) for the "user leaves" event).
While the `Defeat` dialog is open the camera can still be moved [live, 2026-10-12, maintainer]; whether selection
works is [TODO] (the player in that test had no building left); the explored area is not changed by the
defeat (§9, Defeat).

After a win (`Victory`) or a completed free map (`Report`), `btContinue` opens the statistics **without**
leave-on-close, so the player can close it and play on [known] S 0061ff50.

---

## 4. Update order

Per frame, inside the widget tree update ([ingame-ui.md](ingame-ui.md) §4, step 4.2), for widgets that are
visible [inferred: the tree only updates children of visible widgets]:

- `StatsGraph` update (S 0064be30) [known]: if its listener is registered nowhere yet (the listener's own list
  size at +0x294 is 0) and a game system exists, register it with the `PlayerStatistics` of slots 0..7; base
  update; `RefreshTimeAxisLabels`. The players graph additionally calls `RefreshGraphs` every frame (its
  update thunk S 00643570). The inventory graph's update is a plain jump to the base (S 006420f0).
- Both graphs also refresh from the statistics listener callback (slot 1 of the listener face: S 00643560 →
  players `RefreshGraphs`, S 00642930 → inventory `RefreshGraphs`), which `PlayerStatistics::NotifyListeners`
  S 0053ae10 fires from `AddGoodAmount`, `AddSample` and `CommitSamplePeriod` [known: the three callers];
  [inferred] i.e. from inside the logic tick at each production event and each sample. The inventory graph has
  no per-frame refresh: it changes on the listener, on a time-range change (S 00642940) and when a curve is
  added or removed.
- `StatsGoodList` (S 00644840), `StatsPlayerInfo` (S 00645630 → S 00645400), `StatsBuilding` (S 00643780 →
  virtual slot 34 = `Refresh` S 00643f60): base update, then a full refill, every frame [known].
- `GoodInfo` (goods bar): refresh, then base update, every frame (S 00646310 → S 006460d0) [known].
- `Messages::Update` S 005f86a0 (slot 1 of the `IUpdateable` face at Messages +4, vftable S 007ef63c): called
  by the frame function S 004018e0 through `game.messages`, only while the game screen reports open, after the
  `nGame::System` update and before the menu system ([ingame-ui.md](ingame-ui.md) §4 step 3) [known]. Order
  inside [known]: base update; hovered flag cleared; return if `ai::player::PlayerTable::HasActiveType2` is false; bind the
  listener to the local player's store if unbound; new-message poll; `last` button; scroll repeat; slot
  clicks; expiry poll (1 s); rebuild of the filtered list (only after a poll, removal or expiry reported a
  change) and of the slots (after any change); row opacity.
- `MiniMap` update (S 005f1980) [known]: base update; if `refreshCountdown == 0` call virtual slot 34
  (`RefreshMapTexture` S 005f1070: the scene's virtual slot +0x78 is called with (512, 512), [inferred] it
  renders the map overview into the scene's render target; then slot 35 `CaptureMapTexture` S 005f3dd0);
  decrement the countdown while it is ≥ 0 (it rests at −1); set both overlay pictures' source rectangles to
  the minimap's × 0.5. The countdown is set to 0 by the constructor, by `LoadFromXml` S 005f10a0 and by
  `OnDeviceReset` S 005f1170, and by nothing else [known for the three writers; inferred for "nothing else":
  search of the decompiled program].
- `MiniMap::Render` S 005f49e0 [known]: nothing while `ui.MiniMapRender` is false; else the sprite; then, if
  `dirty` is set and the countdown is −1: slot 35 `CaptureMapTexture` again (copy of the scene's render target
  and exploration mask, without a new scene render), `UpdateTerritoryOverlay` and `UpdateObjectOverlay` over
  all rows, `dirty` cleared. Symbols are drawn by the `SymbolRenderer` child (S 005f5ed0 → `RenderSymbols`),
  [inferred] after the two overlay pictures (child order).
- Overlays (S 0063d790, shared by the building, fight and settler overlays) [known]: the overlay's virtual
  slot +0x84, then the base update; [inferred] slot +0x84 is the repositioning. `OverlayBuilding::Update`
  S 00641030 first calls `UpdateFromBuilding`, only while the overlay and the widget at +0x150 are visible.
- Tooltip popups: `Tooltip::Update_adjC` S 006463c0.

Per logic tick the HUD does nothing by itself; it is called back (statistics listener, message listener,
building / soldier / fight / sacrifice callbacks) at the point of the tick where the event occurs [inferred].

On entering a match (`Game::OnEnter` S 005eed00) [known]: `SetupHud` S 005ed700 re-attaches the HUD widgets;
`GoodInfoPanel::RefreshGoodSet` if the goods bar is attached. The minimap symbol list is cleared by
`System::ActivateGameScreen` S 005d9f10, `System::StartPendingMap` S 005d9fd0 and `Game::OnLeave` S 005eb030
[known: the callers of `MinimapSymbolList_Clear` S 005f2820]. The statistics panel does not exist until first
opened; `DestroyHudWidgets` S 005ea650 (called by `Game::OnLeave`) deletes it and the settings panel, and only
detaches (virtual slot +0xc) the other HUD widgets, whose objects live as long as the `Game` screen object
(§7) [known].

---

## 5. Inputs and outputs

**Reads** (never writes) from the simulation: `NLogic::Statistics` / `PlayerStatistics` (series, histories,
productivity map), `Player` (stocks, tribe, `spotted`, enemy relation, building counts, colour, name),
`NPlayer::Messages`, `GoodPriorities`, `GoodArrangement`, `Military`, buildings (property, workers,
construction, production, hit points, soldiers), ships, fights, chests, the map (territory, grid states,
exploration, object layer 1), properties (goods, buildings, sacrifices, military config), the transport and
order lists (§3.2.2).

**Game commands** ([game-commands.md](game-commands.md) §3.4, §5.1), all queued with
`NComm_Manager::QueueGameCommand` [known] S 00782060, S 007821d0, S 007822b0, S 00783070, S 007820f0,
S 00781f60, S 00626c20:

| Control | Command (event class) | Payload |
|---|---|---|
| Settings `btConfirm` | `0x20013`, `0x20014`, `0x20015` (`Event1Integer` each) | `sliderNear` / `sliderMedium` / `sliderFar` float bits |
| | `0x20021` (`EventData`) | the whole local priority list: 8 bytes per entry, `{good id, rank}` per [game-commands.md](game-commands.md) |
| | `0x20011` (`Event1Integer`) | `sliderDefense` float bits |
| Distribution slider | `0x2001F` (`Event3Integer`) | good id, entry index, weight float bits |
| Sacrifice target button | `0x20026` (`EventInt64_1Integer`) | the 64-bit building id the chooser was opened for, then the clicked button's user value (+0x28), the target player index; the chooser then fades out over 0.2 s |

The five settings commands leave in the order `0x20013`, `0x20014`, `0x20015`, `0x20021`, `0x20011` [known]
S 00620970. The statistics panel, the goods bar, the tooltips, the message list, the minimap, the quest panels
and the overlays send no command [inferred: no sender among the functions of §11].

**Session events** ([network-session.md](network-session.md), [NCOMM_GAME_PROTOCOL.md](../NCOMM_GAME_PROTOCOL.md)):
`0x30006` NE_Chat_ToAll (`SendChatToAll` S 00410410) and `0x30007` NE_Chat_ToAllied (`SendTeamChat`
S 00409f60), both `EventText`, sent on Enter and received through the chat sink; neither is sent for an empty
line [known].

**Local effects**: camera focus (message click; minimap click; building row, through
`MenuSelection::RefreshFromGameSelection(…, focusCell = 1)` S 00617800), game selection (building row),
sounds `uiMessage0`, `uiMessage1` (S 005f73e0), `uiRemove` (S 005f86a0), `uiCancel` (S 00620c90), minimap
symbols, the read flag and removal of messages in the local player's store (see §8) [known].

**Lua** [known] S 005dd990, S 005dd9e0, S 005d9530: `menu.addMinimapSymbol(kind, x, y)` and
`menu.removeMinimapSymbol(kind, x, y)` (kind as integer, x and y as floats, on the symbol list of §2.7);
`menu.showMinimap()` calls the minimap's virtual slot +0x24 (`SetVisible`) with 1
([lua-runtime.md](lua-runtime.md) §3.7).

---

## 6. Data-driven parameters

All files are under `[data]\ui\layout\` unless noted ([ingame-ui.md](ingame-ui.md) §6 for the general list).

| File | Keys | Example values |
|---|---|---|
| `menuStatistics.xml` | root `bldOffset`, `bldSpread`, `numBldPerLine` | `26 22`, `128 128`, `7` |
| | `tab count` | `4` |
| | `timeScaling` (`slider2`, `value`), children `min` / `max` | `0`; texts `1H`, `16H` |
| | `filter` (`ComboBoxNew`) `size`, `string0..7` | `8`; `!Regions` … `!Defeated Enemies` |
| | `textTimeInfo0..6` positions | x = 48 + 120 × i, y = 276; `textTimeInfo0` hidden |
| | `textHeightInfo0..1` positions | `48 156`, `48 40` |
| | `graphPlayers` background, `graph0..7` (`template="graph"`, `color`) | 821 × 320; colours are replaced by player colours |
| | `goods` (goods list) `itemsOffsetX/Y`, `itemsPerLine`, `itemsSpreadX/Y`, `count` | `10`, `10`, `11`, `50`, `80`, `22` |
| | `soldiers` (soldier list), same keys | `10`, `10`, `3`, `50`, `80`, `6` |
| | `techtreeBavarian`, `techtreeEgyptian`, `techtreeScots` | hidden pictures, one shown |
| `templates.xml` | `graph`: `lineThickness`, `mappingX`, `mappingY`, `texture`, `color`, `smoothingStrength`, `smoothingIterations`, `alphaani`, `lineani`, `clipping` | `0.009`, `806 825 847 866`, `633 657`, `ui_ingame2`, `1 1 1 1`, `0.2`, `5`, `0 0.06`, `0 0.1`, `true`; deployment `pos="48 34" size="722 240"` |
| | `tipBuilding`, `tipSacrifice`, `tipGood`, `tipSoldier`, `tipInfoboxBuilding`, `tipDefault` | tooltip layouts (children named in §3.4) |
| | `overlayBuilding` and the other overlay templates | children of §3.6.1; `textColRed/Orange/Green`, `offsetSmall/Medium/Large`, `casern…`, `production…`, `constructionGoodIconsOffset/StartPos/AlignX` |
| `menuingame.xml` | root `chatFadeOutTime`, `chatFadeInTime` | `15.0`, `0.1` |
| | `miniMap` `sacrifices_color`, `chests_color`, `intersectionType`, mask | `1 1 0 1`, `0 1 0 1`, `1`, `ui_mask_minimap.tga`; 188 × 188 |
| | `messages` `scaleMax`, `scaleTime`, `alphaMin`, `scaleOnRefresh` | `6`, `0.5`, `0.4`, `false` |
| | `cbMessages` `size`, `string0..6` | `7`; `!Military`, `!Scholar`, `!Economic`, `!Sacrifice`, `!Chest`, `!Navy`, `!Misc` |
| | `goodInfoPanel` | 420 × 32, `selector` tip `!game_ui_v` |
| | `goodInfoPanel` → `goodInfo` `textColGreen`, `textColOrange`, `textColRed`; `goodInfo0..3` `good` | `0.85 0.99 0.83 1`, `1 0.55 0.196 1`, `0.99 0.46 0.46 1`; a hex good id each (replaced by the good set on entering a match, §4) |
| `menuIngameSettings.xml` | `goodprioslot<N>`, `dragslot`, `sliderNear/Medium/Far/Defense`, `waregroup<N>`, `building<N>`, `slider<N>`, root `texturePrioNotUsed`, `mappingPrioNotUsed` | `ui_ingame.dds`, `688 856 40 40` |
| `goodinfosets.xml` | `<Set name tribe><Good name/>×4` | 15 sets, five per tribe (`constructionWares`, `foodWares`, `minerWares`, `militaryWares`, `miscWares`); `constructionWares` / `Bavarian`: `Wood`, `Plank`, `Stone`, `Tool` |
| `mapSymbols.xml` | `<symbol type name texture mapping center lifetime>` | 0 `Message` `852 460 22 18` 100; 1 `Military` `820 460 23 17` 100; 2 `Quest` `902 460 8 19` −1; 3 `Ship` `880 460 17 20` −1; 4 `Fight` `916 460 19 16` −1; 5 `Chest` `944 460 17 16` 100; all: texture `ui_ingame4`, `center="2 3"` |
| `[data]\gfx\fx_20\ui_graphshader.fx` | parameters `GRAPH_COLOR`, `GRAPH_OFFSET`, `GRAPH_SCALE`, `GRAPH_LINETHICKNESS`; technique `Default`, pass `RenderGraph` | the curve shader (§2.2): alpha blend `SrcAlpha` / `InvSrcAlpha`, no depth test |
| `iconconfig.xml` | good icons, small icons, good colours | [ingame-ui.md](ingame-ui.md) §6 |
| `menugameend.xml` | `defeatTitle`, `defeatDesc`, `btContinue` (`!Continue Game`), `btEnd` (`!Quit`) | `!TitleDefeat`, `!DescDefeat` |
| `[data]\buildings\` | `MilitaryFlagInactive.KEX`, `MilitaryFlagSword00..10.KEX`, `MilitaryFlagBow00..10.KEX`; `MilitaryFlag1.dds`, `MilitaryFlag2.dds`, `MilitaryFlag3.dds` | 23 flag meshes (index 0, 1..11, 12..22, S 006d2d80) and the three flag textures (S 006d2ec0; §3.6.2) |
| property scripts | `tp_addGood`, `tp_addJob`, `tp_addBuilding`, `tp_setWorkerToolGoodId`, `gp_setType`, `gp_setSettlerType`, `gp_addCost`, `bp_setNoProductivity`, `bp_setHealth`, `bp_setIgnoreGoodCosts`, `bp_setArrangementLocked` | which rows, tooltips and bars exist ([properties-data.md](properties-data.md)) |
| text tables | `!ALL`, `!TEAM`, `!RANK`, `!Produced by:`, `!Description:`, `!immediate`, `!<building>_tipp_lang`, the filter and state texts | [ingame-ui.md](ingame-ui.md) §3.10 |

Debug variables (CVars, group `ui`): `MiniMapRender` (draw the minimap), `MiniMapRenderSymbols` (draw the
symbols) [known] S 005f49e0, S 005f5bb0.

---

## 7. Save and load

None of the panels has saved state of its own [inferred: no store function among the classes of §2]. What
survives from one match to the next inside one program run depends on the object's lifetime:

- The statistics panel and the settings panel are deleted when the match is left (`DestroyHudWidgets`
  S 005ea650) and built again on first use, so the graphs' time ranges (60), the chosen category, the shown
  good curves, the player toggles and the local priority copy start from their defaults [known for the
  deletion; inferred for the consequence].
- The goods bar, the message list, the minimap and the chat widget are members of the `Game` screen object,
  which `nMenu::System::Initialize` constructs once (S 005ee5d0, one caller); on leaving they are only
  detached and `SetupHud` S 005ed700 attaches them again [known]. Of their state:
  - the goods bar's `currentSetIndex` is written by the constructor (0) and by the `selector` click only
    (S 0062a560, S 006287b0), so the set chosen in one match is the set shown at the start of the next
    [inferred from the writers];
  - the message list's scroll index, both counts and both timers are zeroed when it is attached (S 005f8fa0)
    [known]; its nine filter bytes are not written there. [TODO] not established: whether marking the seven
    `cbMessages` entries in `Game::LoadFromXml` S 005ecaf0 also sets the filter bytes back (a read of the
    combo box's mark function and of `OnFilterButtonToggled` S 005f8e80 settles it);
  - the minimap's XML load sets `refreshCountdown` to 0 and `dirty` to 1 (S 005f10a0), and the next capture
    takes the texture size from the source rectangle (§3.7) [known]. [TODO] not established: whether zoom and
    pan (the source rectangle) are reset between matches; a read of `Picture::LoadFromXml` for the `mapping`
    attribute and of where the layout is reloaded settles it;
  - [TODO] not established: whether the chat log is emptied between matches (a read of the `ChatSystem`
    attach and detach functions settles it).
- What the panels display is saved with the simulation: series and histories
  ([players-victory.md](players-victory.md) §2.5, [save-format.md](save-format.md) §3.3, item 9), priorities,
  distribution weights and military factors (`Good Priorities`, `Good Arrangement`, `Player Military` of the
  player record), and the messages: `Message::Store` S 005c0300 writes the remaining time, the cell, text,
  text2, type, read flag, id and arg [known]. Messages of type 8 (letters) are written but dropped by
  `Messages::Load` S 005c2520 [known: the type test in the loader].
- Minimap list symbols are not saved: the list is emptied by `StartPendingMap` and `ActivateGameScreen` (§4)
  and no store function reads it [known for the two calls; inferred for "not saved"]. [TODO] not established:
  whether the shipped scripts add their quest symbols again after a load ([lua-runtime.md](lua-runtime.md)).

---

## 8. Determinism notes

- The panels read simulation state and send commands; commands go through the lockstep queue, so the settings
  change on every machine at the same tick ([game-commands.md](game-commands.md) §3.1).
- The settings sliders send raw float bits; the simulation stores them unchecked. A remake must send the same
  bit pattern the widget holds, not a re-rounded value.
- Two local writes touch objects that live in the simulation's player data: a left click sets a message's read
  flag, a right click and the 1 s expiry poll remove messages from the **local** player's store only.
  `Messages::RemoveById` S 005c1ad0 and `Messages::RemoveExpired` S 005c1c10 have no caller but
  `nMenu::Messages::Update` [known], so no machine removes the messages of a player who is not its local
  player: those records stay, with a remaining time that keeps falling below 0, until the player is reset or
  a save is loaded [inferred] ([players-victory.md](players-victory.md) §3.9, §8, which states the consequence
  for checksums and saves). The poll also needs the game screen to be open and an active local human player
  (§4).
- Statistics listeners are called from inside the logic tick but only rebuild widget data [inferred].
- `nUi::Graph` uses the C runtime `rand()` (S 006f41e2) and the total wall time (`Timer_GetTotalSeconds`
  S 0057b8a0) for its two optional animations [known] S 004c7f90; both are off in the shipped data, and
  neither touches the simulation generator.
- The trend value of §3.2.2 is computed on demand from simulation lists and is never stored.

---

## 9. Notes for a Godot reimplementation

- **Graphs**: a `Line2D` (or a mesh) inside a clipping `Control`. Reproduce the mapping exactly if the look
  matters: all samples are plotted, the plot is right-anchored, one sample is `width / range` wide, the y scale
  is the maximum over the whole history of all shown curves, and the curve is smoothed with 5 passes of 0.2.
  The line is a ribbon of half width 0.009 of the screen, extruded along the averaged segment normals and
  textured from `ui_ingame2` (§2.2). A simpler alternative is to plot only the last `range` samples with the
  same y scale; it differs at the left edge, because the smoothing of the original runs over all samples.
- **Sampling** stays in the simulation (one sample per 600 ticks, 960 kept). The UI must not resample.
- **Player rows / curves**: apply the "spotted" rule and the campaign rule for unnamed players; decide
  deliberately whether to give slots 6 and 7 a row.
- **Goods numbers**: implement the query of §3.2.2 as a function of the simulation, used by the bar and the
  statistics rows alike; refresh on a timer or signal rather than every frame (the result only changes on
  ticks).
- **Settings panel**: keep the local copy / confirm model for priorities and the immediate model for
  distribution sliders, or unify them; if unified, keep the command set (`0x20021` carries the whole list).
- **Tooltips**: five scene templates fed by the property database; the building and good tooltips need the
  producer / consumer lookups of [properties-data.md](properties-data.md) §3.5.
- **Messages**: the list is a view on the player's message store with a per-type filter; expiry belongs in the
  simulation in a remake (do it for every player on every machine) instead of the local 1 s poll, which is a
  source of divergence in the original.
- **Minimap**: render the terrain once into a 512 × 512 texture (a `SubViewport` capture; the original renders
  it after the layout load and after a device reset, §4), keep two overlay images (territory, objects; §3.7
  for their resolution), and on each of the events listed redo the exploration mask of the terrain image and
  both overlays; draw symbols as sprites. The converter must provide `ui_mask_minimap`, the symbol atlas
  `ui_ingame4` and `mapSymbols.xml`.
- **World overlays**: `Control` nodes positioned from `Camera3D.unproject_position`; the icon rules of §3.6.1
  are the game's "what is wrong with this building" logic and should be kept.
- **Chat**: two scopes (all, allies), Shift+Enter for allies, auto-hide after 15 s. A server-based remake can
  route team chat on the server instead of filtering on the receiver.
- **Defeat**: the original offers no spectating: "Continue Game" is disabled in the `Defeat` dialog (§3.10).
  A remake that adds spectating needs a visibility rule of its own. The original does not change the
  exploration mask of a defeated player [known]: the defeat path (`VictoryCond_Update` S 00535d70,
  `CheckPlayerEliminated` S 00535b90, `DeclareWinner` S 00535990; [players-victory.md](players-victory.md) §3.6)
  calls no exploration function, and the mask is written only by `NMap::Exploration::RevealHexArea` S 00677570
  (from `MapModifier::ExploreArea` S 00674800), `Clear` S 00677930 and `Init` S 00677af0 (match reset, load,
  map export). The player stays active, so his remaining buildings and settlers, and his allies', go on
  revealing cells for him through `ExploreArea` [inferred: none of its callers tests the victory state].

---

## 10. Open questions

| # | Question | What settles it |
|---|---|---|
| 1 | Exact meaning of the three lists / flags in the trend query (§3.2.2): the order list at `village.orderSystem`, the transport list at +0x448, worker slot +0x28 | static read of the element classes and of the worker vftable |
| 2 | Second half of `OverlayBuilding::UpdateFromBuilding`: soldier counts, hit-point bar, name colour of military buildings, `exclamation0..2`, the flag that hides the missing-material icons (§3.6.1) | disassembly read of S 006403c0 from 0x00640533 on |
| 3 | Answered (§3.1): the tech tree tab opens like the other three and shows a text-only tree [live, 2026-10-12] | — |
| 4 | What a defeated player can still do while the `Defeat` dialog is open: the camera moves [live, 2026-10-12]; open: selection. Answered (§9, Defeat): the defeat does not change the exploration mask (no exploration writer on the defeat path; writers S 00677570, S 00677930, S 00677af0) | observation in the game (selection) |
| 5 | Whether attackable enemy buildings get a marker of their own (§3.6.2) | observation in the game |
| 6 | Answered (§3.1): in the first minute the graph lists only the own player and shows no data [live, 2026-10-12] | — |
| 7 | State that survives from one match to the next in one program run: the message filter bytes, the minimap zoom and pan, the chat log (§7) | read of the combo box mark function and `OnFilterButtonToggled` S 005f8e80; of `Picture::LoadFromXml` and where the HUD layout is reloaded; of the `ChatSystem` attach / detach functions |
| 8 | Whether the shipped scripts add their minimap quest symbols again after a load (§7) | read of the campaign scripts' load hooks |
| 9 | Whether the scene call of `MiniMap::RefreshMapTexture` S 005f1070 (scene slot +0x78 with 512, 512) renders terrain only or also objects (§4) | read of the scene's vftable slot +0x78 |
| 10 | What the virtual slot +0x84 of the overlay classes does per frame (§4; read as repositioning) | read of the three overlay vftables |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 005eb780 | `nMenu::Game::ToggleStatisticPanel` | create / show / hide the statistics panel |
| 00621d20 / 006225d0 / 00622380 | `nMenu::StatisticPanel::ctor` / `OnXmlLoaded` / `BindWidgets` | panel construction, building rows, slider and filter binding |
| 00621820 / 00621910 | `StatisticPanel::OnSliderChanged` / `OnButtonClick` | time range; player toggles and category |
| 006217c0 / 006217f0 | `StatisticPanel::SetGoodGraphShown` / `OnHide` | good curve on / off; fade out, leave-on-close |
| 0064bef0 / 0064c0c0 | `nMenu::StatsGraph::ctor` / `LoadFromXml` | labels, default range 60 |
| 0064be30 / 0064bd60 / 0064bde0 / 0064bea0 | `StatsGraph::Update` / `RefreshTimeAxisLabels` / `SetValueAxisMax` / `SetTimeRange` | listener registration, axis labels |
| 00642fe0 / 00642d60 / 006435c0 | `StatsGraphPlayers::RefreshGraphs` / `SetStatisticCategory` / `LoadFromXml` | player curves |
| 00642590 / 00642970 / 00642bb0 | `StatsGraphInventory::RefreshGraphs` / `CreateGraph` / `DestroyGraph` | good curves |
| 00644840 / 00644430 / 006446c0 / 00644a50 / 00644ff0 | `StatsGoodList::Update` / `FillFromGoodVectors` / `FillFromGoodTable` / `LayoutItems` / `LoadFromXml` | inventory rows |
| 0064c8e0 / 0064c650 | `StatsGoodInfo::SetGoodData` / `OnClick` | one row; curve toggle |
| 00645400 | `StatsPlayerInfo::Refresh` | player row |
| 00643f60 / 00643a90 / 006437a0 | `StatsBuilding::Refresh` / `OnButtonClick` / `LoadFromXml` | building row |
| 00533160 / 00533e60 | `GameQueryHelper::GetAverageBuildingProductivity` / `GetAverageBuildingHealth` | building row bars |
| 00533c40 | `GameQuery_GetPlayerGoodStockAndPending` | stock and trend of a good |
| 005be7a0 | `ai::player::Player::IsShownInPlayerLists` | campaign rule for unnamed players |
| 004c9940 / 004c7f90 / 004c9410 / 004c8fd0 / 006424e0 | `nUi::Graph::LoadFromXml` / `Draw` / `SmoothPoints` / `BuildLineMesh` / `SetPoints` | curve widget |
| 006460d0 / 00645e90 / 006287b0 / 00628720 / 00628780 | `GoodInfo::Refresh` / `SetupGoodTooltip` / `GoodInfoPanel::OnChildClicked` / `ApplyGoodSet` / `RefreshGoodSet` | goods bar |
| 00620970 / 00620460 / 00620580 / 00620c90 | `IngameSettingsPanel::OnButtonClick` / `RefreshGoodSlots` / `CommitSlotDrag` / `CancelSlotDrag` | confirm, priority slots |
| 005c2690 / 005c27c0 | `NPlayer::GoodPriorities::GetGoodAtRank` / `MoveRank` | first good at a rank; move every entry of a rank |
| 006410e0 / 006413c0 / 006412f0 / 006412a0 | `GoodArrangementPanel::RefreshWaregroupButtons` / `ShowGoodDistribution` / `OnSliderValueChanged` / `GetSelectedGoodId` | distribution |
| 0062bc70 / 0062bfd0 / 006464c0 / 006463c0 | `nMenu::Tooltip::CreateByKind` / `TooltipCache_GetOrCreate` / `Tooltip::Open` / `Update_adjC` | rich tooltips |
| 00647150 / 00647740 / 00647d20 / 00648070 / 00648700 | `TooltipBuilding` / `TooltipSacrifice` / `TooltipGood` / `TooltipSoldier` / `TooltipInfoboxBuilding` `::ShowFor` | tooltip content |
| 00646e90 / 00647590 / 00646830 | `nMenu_Tooltip_FormatLabelValue` / `nMenu_Tooltip_SetDurationText` / `Tooltip::FillGoodSlots` | tooltip helpers |
| 005f86a0 / 005f73e0 / 005f85b0 / 005f8c30 / 005f8dd0 | `nMenu::Messages::Update` / `PollNewMessages` / `RebuildFilteredList` / `PulseSlotForMessage` / `PulseSlotForMessageIfEnabled` | message list |
| 005f8fa0 / 005f8b90 / 005f75a0 | `nMenu::Messages::InitAndAttachToParent` / `Refresh` / `SetupSlot` | rows and code-made scroll buttons; filters and window; row text and icon |
| 005c2360 / 005c0270 / 005c1e40 | `NPlayer::Messages::AddWithPosition` / `PlayerMessages_SendOrRefreshToPlayer` / `Messages::FindMatchingWithArg` | the message store: unbounded append, refresh of a matching message |
| 005be2c0 | `ai::player::Player::GetColorEntry` | player colour of the minimap's territory overlay and of the military flags |
| 005eb120 | `nMenu::Game::ShowCommMessageAsLetter` | session notices as letters |
| 006403c0 / 0063fd10 / 00641030 | `OverlayBuilding::UpdateFromBuilding` / `UpdateMissingGoodIcons` / `Update` | building overlay |
| 0055fd00 / 006d2820 / 006d2d80 | `NVillage::Military::HasMilitaryFlag` / `CMilitaryFlagRenderer::DrawFlags` / `GetFlagMeshPath` | military flags |
| 005eac30 / 00688c40 | `nMenu::Game::StartOverlayColorFade` / construction overlay draw test | info-map tint fade; the build icons draw only while its alpha > 0 |
| 005f39b0 / 005f10a0 / 005f1980 / 005f49e0 | `nMenu::MiniMap::ctor` / `LoadFromXml` / `Update_Face4` / `Render` | minimap life cycle |
| 005f1070 / 005f3dd0 / 005f16d0 | `MiniMap::RefreshMapTexture` (slot 34) / `CaptureMapTexture` (slot 35) / `MiniMap_ApplyExplorationMask` | scene render of the map image; copy into the minimap texture; fog mask |
| 005f3be0 / 005f1170 / 005f1190 | `MiniMap::Create` / `OnDeviceReset` / `MarkDirty` | 512 × 512 capture texture; new capture after a device reset; overlay rebuild request |
| 005f5ed0 / 005f2820 / 005f2690 | `MiniMap::SymbolRenderer::Draw` / `MinimapSymbolList_Clear` / `MinimapSymbolList_TickExpire` | symbol pass entry; list reset on map start and leave; lifetime countdown |
| 005f3fc0 / 005f4390 | `MiniMap::UpdateTerritoryOverlay` / `UpdateObjectOverlay` | overlay textures |
| 005f5bb0 / 005f55a0 / 005f20c0 / 005f5af0 | `MiniMap::RenderSymbols` / `MiniMap_DrawMapSymbol` / `MapCellToViewPos` / `MinimapSymbolList_Add` | symbols |
| 005f18e0 / 005f2130 / 005f2390 / 005f1af0 / 005f1520 | `MiniMap::OnMouseButton0Down` / `OnMouseMove_Face8` / `OnMouseWheel_Face8` / `ZoomAroundPoint` / `FocusCameraOnCursor` | minimap input |
| 005ec340 / 005eaed0 / 005ef320 / 005ef530 | `nMenu::Game::OnKeyDown` / `CloseChatInput` / `OnChatToAll` / `OnChatToAllied` | chat |
| 005fe6c0 / 0061ff50 | `nMenu::Defeat::LoadFromXml` / `nMenu::GameEnded::OnButtonClick` | end dialogs |
| 00643570 / 006420f0 / 00643560 / 00642930 | players graph update thunk / inventory graph update thunk / `StatsGraphPlayers::RefreshGraphs_thunk_m288` / `StatsGraphInventory::RefreshGraphs_thunk_m288` | per-frame update and statistics listener callbacks of the two graphs |
| 00643590 / 00642940 | `StatsGraphPlayers::SetTimeRange` / `StatsGraphInventory::SetTimeRange` | slot 34 overrides: base setter, then `RefreshGraphs` |
| 00643780 / 00645630 / 00646310 | `StatsBuilding::Update_adj4` / `StatsPlayerInfo::BaseUpdateThenRefresh_adj4` / `GoodInfo::Update_adj4` | per-frame refresh of a building row, a player row, a goods bar entry |
| 0053ae10 | `NLogic::PlayerStatistics::NotifyListeners` | calls slot 1 of every statistics listener |
| 004e48a0 | `ai::render::UIGraphRenderer::Render` | draws a curve with `ui_graphshader.fx` |
| 00620d60 / 0060e440 | settings panel button-1-down override / `nMenu::Dialog::OnMouseButton1Down` | cancel of a picked-up priority slot; dialog close on button 1 |
| 00782060 / 007821d0 / 007822b0 / 007820f0 | `nGame::System::SendSetMilitaryValue2Command` / `…Value1Command` / `…Value0Command` / `SendCommand_20011` | `0x20013` / `0x20014` / `0x20015` / `0x20011` |
| 00783070 / 00781f60 / 00626c20 | `nGame::System::SendSetGoodPrioritiesCommand` / `SendCommand_2001F` / `nMenu::SacrificeTargetPanel::OnChildClicked` | `0x20021` / `0x2001F` / `0x20026` |
| 00410410 / 00409f60 | `NComm_Manager::SendChatToAll` / `SendTeamChat` | `0x30006` / `0x30007` |
| 005ed700 / 005eed00 / 005ea650 | `nMenu::Game::SetupHud` / `OnEnter` / `DestroyHudWidgets` | HUD attach on entering a match; detach and deletion on leaving |
| 005c1c10 / 005c1ad0 / 005c0300 / 005c2520 | `NPlayer::Messages::RemoveExpired` / `RemoveById` / `NPlayer::Message::Store` / `NPlayer::Messages::Load` | the two removals the HUD performs; message save and load |
| 0055fbb0 / 00553f20 / 0055fd40 / 006d2ec0 | `NVillage::Military::GetProximityZoneA` / `ClassifyIndex_0_1_2` / `GetFlagSoldierCount` / `CMilitaryFlagRenderer::InitGraphicsResources` | flag texture index, zone thresholds, flag soldier count, flag meshes and textures |
| 00617800 | `nMenu::MenuSelection::RefreshFromGameSelection` | selection UI refresh, optional camera focus (building row click) |
| 005dd990 / 005dd9e0 / 005d9530 | `LuaMenu_AddMinimapSymbol` / `LuaMenu_RemoveMinimapSymbol` / `LuaMenu_ShowMinimap` | Lua minimap functions |
