# UI toolkit: widget classes and their behaviour

Tags: **[known]** = read directly at the address named (S 00xxxxxx = `sadk_noav.exe`) or in the named data file and
key; **[inferred]** = one step of reasoning from what is visible there; **[TODO]** = not established, with what
would settle it. Nothing in this file was observed in the running game.

## 1. Purpose and scope

Namespace `nUi` is the game's own retained-mode widget toolkit. Front end, HUD and lobby dialogs are trees of
`nUi::Object` built from layout XML. This file specifies each widget class as a toolkit part: state, drawing,
input, events, text entry and scaling, so that a Godot `Control` scene can reproduce it.

Not repeated here (read there first):

- layout XML schema, templates, common attributes, `<deployment>`, `<shape>`, `<text>`, `<tip>`, the table of
  widget kinds and created classes, input entry and mouse-over, tooltips, localisation, font list:
  [ingame-ui.md](ingame-ui.md) §2.1 to §2.6, §3.1 to §3.3, §3.10;
- `.fnt` file format and glyph arithmetic, `cursors.xml`: [formats-inventory.md](formats-inventory.md) §2.6, §3.6,
  §3.10;
- the screens that use the widgets (`nMenu::*`): [ingame-ui.md](ingame-ui.md) §3.4 onwards;
- Lua button events and the `ui.*` library: [lua-runtime.md](lua-runtime.md) §3.7, §4.4.

Class names used by the task list and their real classes [known] S 004c28a0 (factory), S 007bf5f0 (name table):
there is no `CheckBox` class (a check box is a `Button` with `checkbutton="true"`, §3.4) and no `ScrollBar` class
(the scroll bar is `SliderEx`, §3.9). `ButtonEx` creates a plain `Button`.

## 2. Data model

Offsets are from the object start unless a line says "face": every widget has three vtables (primary +0,
`IUpdateable` +4, `Event`/`Configurable` +8, [ingame-ui.md](ingame-ui.md) §2.1); a handler that runs on the Event
face receives `this` = object + 8. The map types such a `this` as an offset pointer into the widget class, so the
decompile of a face handler shows the widget's own fields at the object offsets.

### 2.1 Event face (`nUi::Event`, 0x18 bytes at Object +8) [known] S 004ab2c0, S 004ab060, S 004ab130

| Face offset | Field | Meaning |
|---|---|---|
| +0x08 / +0x0c | template source list | [ingame-ui.md](ingame-ui.md) §3.1.3 |
| +0x10 | `receiveEvents` (u8) | default 1 |
| +0x11..+0x15 | `buttonPressed[5]` (u8 each; button 0 = Object +0x19) | per mouse button 0..4: the widget took the down and waits for the up [inferred: offset from the readers S 004d02f0, S 004d1060 and the field order of the constructor] |

Virtual slots of the face (offset in its vtable) [known] S 004ab010, S 004ab060, S 004ab130, S 004ab190, S 004ab1f0:

| Slot | Method |
|---|---|
| +0x18 | `HandleEvent(type, a1, a2)` = `GetReceiveEvents` (+0x1c) then `DispatchEvent` (+0x20) |
| +0x24 / +0x28 / +0x2c | mouse down / up / double click by button number |
| +0x30 + 12·b, +0x34 + 12·b, +0x38 + 12·b | button b (0 left, 1 right, 2 middle, 3, 4): down, up, double click |
| +0x6c | mouse move |
| +0x70 | mouse wheel (notches) |
| +0x74 / +0x78 | key down / key up (virtual key) |
| +0x7c | character |
| +0x80 | hotkey (character code) |

### 2.2 Focus, capture and text-input globals

| Global | Address | Meaning | Evidence |
|---|---|---|---|
| `Focus.state` | Object +0xf8 | 0 idle, 1 hovered, 2 pressed; forced to 0 while the owner's vtable slot +0x10 returns false | [known] S 004c1d50 |
| focus state list | `g_Ui_FocusStateList` | every widget whose state is not 0 | [known] S 004c1d50 |
| input capture | `g_pUiInputCapture` S 00885cb4 | widget that gets mouse events 0..4 instead of the tree | [known] S 004913f0 |
| `Edit` focus | `g_TextInput_FocusedWidget` S 00885ca4 | the one `Edit` that receives keys | [known] S 00497b10 |
| `Edit` buffer | S 0087c0e8 before cursor, S 0087c104 after cursor, S 0087c120 text at focus time (three `std::string`) | shared by all `Edit` widgets | [known] S 004c0a40 |
| `Edit` limit | `g_TextInput_MaxLength` S 0087c0e0, initial 20 | characters; copied from the widget's maxLength when it takes focus | [known] S 00497b10, data |
| `Edit` gate | `g_TextInput_Enabled` S 0087c0e5, initial 1 | written by `nMenu::System::Update` in every frame in which the UI is not suppressed: 0 while the message box reports itself active [inferred], else 1 | [known] S 005da500 |
| `Edit` barred char | S 0087c0e4 = 0x3c (`<`), never written | this character cannot be typed | [known] data, one reader S 004c0822 |
| `Edit` charset switch | S 00885d98 = 0, never written | 1 would restrict typing to §3.6's restricted set | [known] one reader S 004c0834 |
| `EditEx` focus | `g_pFocusedEditEx` | the one `EditEx` that receives keys | [known] S 00498c60 |
| Ctrl / Shift | `g_pActiveAction` vtable +0x20 / +0x24 (`GameAction::IsCtrlDown` S 004912a0, `IsShiftDown` S 00491280) | modifier state for widgets | [inferred] slot order |

There is **no general keyboard focus and no focus traversal** for buttons, lists or sliders: only `Edit` and
`EditEx` take keys, each family through its own global [inferred: the names index lists key-down handlers in
`nUi` only for `Edit` S 00498250, `EditEx` S 0049fb70 and `DropDownMenu` S 004b2770, which only closes itself].
Giving an `EditEx` the focus clears the `Edit` focus global [known] S 00498c60.

### 2.3 `ai::render::BitmapFont` draw state [known] S 004e2c60 (disassembly), S 004b43c0

| Offset | Field |
|---|---|
| +0x0004 + 0x24·c | glyph c: valid (u8 +0), x +4, y +8, width +0xc, height +0x10, xOffset +0x14, yOffset +0x18, xAdvance +0x20 |
| +0x2404 | lineHeight |
| +0x240c | charSpacing (added to every advance) |
| +0x2410 / +0x2414 | 1 ÷ scaleW, 1 ÷ scaleH |
| +0x2418 / +0x241c / +0x2420 | draw x, y (pixels, int), depth |
| +0x2424 | colour RGBA (4 f32) |
| +0x2434 | alignment flags: 1 VCenter, 2 Bottom, 4 Left, 8 HCenter, 0x10 Right |
| +0x2408 | base (distance from the line top to the baseline) [inferred: name from the mapped struct; used by §3.2] |
| +0x2438 / +0x243c / +0x2440 | length of the built string, number of glyph quads to draw, quad buffer (4 vertices of 0x1c bytes per character: x, y, depth, rhw = 1, packed colour, u, v; the quad of character i is at i × 0x70) |
| +0x2444 | width of the whole string in pixels |

### 2.4 `ai::render::RichTextLayout` (the engine of `TextBlock`) [known] S 004e4170, S 004e4270

x, y, maxWidth, maxHeight (pixels; −1 = unset), textWidth, textHeight (results), a font list
`{4-byte key, BitmapFont*}` (first entry = default font), the visible text with tags removed, and a linked list of
segments. Segment (0x28 bytes): font +0, lineFont +4 (the tallest font of its line), length +8, endsLine +0xc
(u8), colour RGBA +0x10 (default 1,1,1,1), alignFlags +0x20 (default Left; the flag values of §2.3), next +0x24
[known] S 004e4270, S 004e3fa0 (disassembly).

### 2.5 Widget classes: state added to `nUi::Object`

Sizes are in [ingame-ui.md](ingame-ui.md) §2.3. Member offsets are given where the constructor shows them.

| Class (kind) | Members and state | Evidence |
|---|---|---|
| `ShapedObject` (32) | one `Shape` (+0x198) | [known] S 004b5160 |
| `Picture` (14) | `Shape`, `Tip` | [known] S 004b1590 |
| `Label` (9) | `Text` | [known] S 004b1e60 |
| `TextBlock` (24) | `RichTextLayout*`, text alpha (default 1) | [known] S 004b7ae0 |
| `Button` (10) | `Shape` (+0x198), caption `Text` (+0x254), `Tip`, style (int, XML `type`; 0 after construction, `LoadFromXml` sets 12 before it reads `type`), visualState (= Focus state, +0xf8), `isCheckButton`, `marked`, four mappings (normal, cursor over, cursor over and pressed, marked), three state textures (style 6), font and fontCursorOver, three observer lists (pressed, clicked, double-clicked +0x248); `mapping` fills all four mappings, `font_cursorover` defaults to `font` | [known] S 004b0e90, S 004afed0, S 004b12d0, S 004b1470, S 004b1270 |
| `PictureButton` (12) | `Button` + one more `Shape`, XML child `background` (the icon) | [known] S 004b3970, S 004b3a90 |
| `OverlayButton` (13) | `PictureButton` + `highlight` picture, `onhover` | [inferred] S 004b2280 |
| `InventoryButton` (38) | `Button` + two shapes (the second is the XML child `item`), `slotIndex` (i16, default −1), `slotType` (i16, default −1), suppress-next-release flag, five observer lists | [known] S 004bd960, S 004bd6c0 |
| `Icon` (8) | `Shape` (+0x19c), `symbol` shape (+0x230), `Tip` (+0x2c8), displayMode (int, XML `type`, default 0), marked, four `Texture` records: selected (+0x324), not selected (+0x358), pressed (+0x38c), marked (+0x3c0) | [known] S 004cec90, S 004ce850 |
| `Edit` (6) | `ShapedObject` + style, `Text`, maxLength (default 20), maxLengthInPixels (default 500), three mappings | [known] S 00497420, S 004970e0 |
| `EditEx` (7) | `ShapedObject` + font, line layout (lines of 0x20 bytes with per-glyph x positions), three mappings (default 79 799 241 18 each), padding rectangle (default 4 1 4 2), text area (default 233 × 15), scroll line and scroll x, cursor line and column, selection anchor and signed selection length, multiLine, allowTab, wordWrap, password, readOnly, clearOnEsc, autohide, allowedChars string, maxLength (−1 none), caret timer (ms, 0..999 with focus, 1000 without), Enter-capture flag (+0x348) and Enter latch (+0x349), `Tip`, vertical `SliderEx` | [known] S 0049d720, S 0049ebd0, S 0049a090 |
| `Slider` (1) | value (f32), `Shape` ×2 (XML children `shape` and `bar`), throttle `Picture`, type (default 1), speed (default 0.2), snapcount, changed flag | [known] S 004d0bd0, S 004d0950 |
| `Slider2` (2) | value 0..1 (f32), snapCount, orientation (1 horizontal), throttle and two step buttons (`leftUp`, `rightDown`), two mappings, value `Text` with `useText`, `textValMin`, `textValMax`, `textFormat`, dragging flag, changed-this-frame flag, observer list | [known] S 004d04b0, S 004d0200, S 004d02f0 |
| `SliderEx` (4) | value (i32, +0x258), count (i32, +0x25c; 0x7fffffff = no range), throttle range min (+0x230) and max (+0x244) as `Position`, throttle `Picture` (+0x260), `Decrease` (+0x4e8) and `Increase` (+0x9e8) `PictureButton`, valueChanged (+0xee8), dragging (+0xee9), orientation (+0xeec: 0 vertical, 1 horizontal) | [known] S 004b96d0, S 004b9890 (disassembly) |
| `ListBox2` (22) | container `Picture` (kind 14, +0x198), row template `PictureButton` (+0x420), row vector (+0x920), `SliderEx` (+0x930), itemSpacing (f32, default 0), markSingleItem (default 1), observer lists "row selected" and "row double-clicked" | [known] S 004b8ea0, S 004b8c00 |
| `DropDownMenu` (20) | `Picture` + two observer lists (opened, item chosen), header `Button`, row template `Button`, row vector, isOpen, dropdownOffset (pixels) | [known] S 004b3160, S 004b36e0 |
| `ComboBoxNew` (19) | as `DropDownMenu` + selectedIndex, one observer list (selection changed) | [known] S 004cbf90, S 004cc180 |
| `TabControl` (37) | `Picture` + mappingTabActive, mappingTabInactive, page vector, tab button vector, fadeTime (default 0), activeTab (default −1) | [known] S 004ba850, S 004c28a0 |
| `ProgressBar` (34) | `ShapedObject` + child `bar`, marker child (XML name `tip`), value 0..1, full bar width and marker base position (both taken from the loaded children) | [known] S 004bd580, S 004bd470 |
| `Graph` (36) | point list, vertex and index buffers, texture, lineThickness (default 0.1), colour (default white), displayMin (0,0), displayMax (1,1), offset (0,0), scale (1,1), smoothingStrength (default 0.2), smoothingIterations (default 1), alphaani (2 f32), lineani (2 f32), mappingX (4 f32), mappingY (2 f32) | [known] S 004c2450, S 004c9940 |
| `ChatSystem` (28) | `ShapedObject` + input `EditEx`, `SliderEx`, minimise / maximise / channel-button-template `PictureButton`, channel slots `{id, ChatLog*, button, enabled}` (0x10 bytes), active channel, output rectangle x, y, width, height (pixels), lineSpacing (default 2), maxLines (default 256), font, wrap and trim character sets, minimised flag, minHeight (120 after construction), maxHeight (240 after construction; `LoadFromXml` replaces both, §3.14), observer list "line clicked" | [known] S 004ade70 |
| `Grabber` (5) | dragging flag | [known] S 004be8d0 |

### 2.6 Animations [known] S 004d21d0, S 004c37b0, S 004d24d0, S 00768e80, S 004d2b00, S 00763510

`nUi::Animation` base: listener list, duration (s, +0x14), elapsed, startTime, running (u8, +0x20), finished (u8,
+0x21).

| Class | Extra state |
|---|---|
| `AnimationAlphaFade` (0x38 bytes) | fromAlpha +0x24 (default 1), toAlpha +0x28 (default 0), recursive +0x2c (default true), easing +0x30 (0 linear, 1 smooth), target +0x34 |
| `AnimationAlphaPulse` | target, minAlpha, maxAlpha, frequency (Hz), recursive |
| `AnimationScaler` (0x84 bytes) | target, from scale (x, y), to scale (x, y), pingPong flag and speed, easing, saved base position and size |
| `AnimationMover` | target, from and to offset, reverse flag, easing, saved base position, hide-on-stop flag |
| `AnimationTransformFade` (0x7c bytes) | target, vector of keys (0x24 bytes: time, quaternion rotation, position x y, scale x y), smoothStep flag |

## 3. Rules and algorithms

### 3.1 Text: `nUi::Text` and the bitmap font

**Setting text** [known] S 004b3fe0: optional localisation (`Localization::GetText`), then `uppercase` or
`lowercase` with the C runtime `toupper` / `tolower` under the system locale (`setlocale(LC_ALL, "")`, restored
afterwards). Strings are single-byte (Windows-1252 in the German install).

**Default font** [known]: `Body_Arial`, centred, for every widget's text (S 004a56d0, S 004b3eee); a label
made by the factory gets `Subline_Garamond`, white, left (S 004b2040) ([ingame-ui.md](ingame-ui.md) §3.10).

**Draw position** [known] S 004b43c0: pixel x = round(owner absolute x × screen width) + round((pos.x + offset.x)
× screen width), y likewise with the height (round = +0.5, truncate). The font gets `align | 1`, i.e. the text is
always **vertically centred on that y**. Colour = text colour, alpha × owner opacity (+0x140). The owner's world
matrix is set before the glyphs are flushed.

`contentHidden`: every character except `|` is replaced by `*` at draw time (`|` is the `Edit` caret, §3.6).

**Single-line layout** (`BuildTextScaled` S 004e3080 → `BuildGlyphQuads` S 004e2c60) [known, disassembly]:

1. `textWidth` = Σ over valid glyphs of (xAdvance + charSpacing) (S 004e2620). Characters without a glyph get
   no quad and no advance. The quad of character i is stored at buffer index i, but only as many quads as there
   are valid glyphs are drawn, from the start of the buffer (`FlushGlyphs` S 004e2bd0): a string that contains
   a glyphless character leaves a hole in the buffer and loses its last quads [inferred from the two reads].
2. Start x = draw x; HCenter: − textWidth × sx × 0.5; Right: − textWidth × sx. Start y = draw y; VCenter:
   − lineHeight × sy × 0.5; Bottom: − lineHeight × sy. (sx, sy = the text's scale pair, default 1, 1.)
3. Per valid glyph: quad left = trunc(pen x) + xOffset × sx − 0.5, top = trunc(line y) + yOffset × sy − 0.5,
   size = width × sx by height × sy; UV = (x, y, x + width, y + height) × (1 ÷ scaleW, 1 ÷ scaleH). Then
   pen x += xAdvance × sx + charSpacing. The glyph values are those after the loader has grown each rectangle
   by the `.fnt` padding (`BitmapFontGlyph::ParseCharLine` S 004e28b0, [formats-inventory.md](formats-inventory.md)
   §3.6), and the whole grown rectangle is drawn.
4. The wrap limit of this path is textWidth + 1 and its height limit is lineHeight, so a single line never
   wraps (constant 1.0 at S 007d8a08).

There is no kerning [known: [formats-inventory.md](formats-inventory.md) §3.6].

**Sampling** [known] S 004e1350, `gfx/fx_20/ui_shader.fx`: `UIRenderer::DrawGlyphQuads` draws through the
techniques `RenderFont` and `RenderFontDepth` (the latter adds an alpha test, Greater 7); both sample the page
with `addressU` / `addressV` = Wrap and linear filtering. A padded glyph rectangle that reaches past the page
edge (for example `Subline_Garamond`'s `e` at x 0, grown to x −2) therefore reads the opposite edge of the page,
which is transparent in the shipped pages; a clamping sampler would repeat the edge texels instead.

**Boxed layout** (`wrapSize` set; `BuildTextInBox` S 004e3270, same glyph loop) [known, disassembly]:

- Break candidates: space, `.`, `!`, line feed (0x0a), and any character that has no glyph. The index of the
  last candidate is remembered and **never reset** after a break.
- Before placing a glyph: lineWidth' = lineWidth + xAdvance × sx (charSpacing is not counted here). If
  lineWidth' > maxWidth × sx: line y += lineHeight × sy, lineWidth = 0, pen x = start x, total height +=
  trunc(lineHeight × sy + 0.5). Then, if a candidate exists, the quad count is changed by
  (candidate − current index + 1) and layout continues with the character after the candidate (the characters
  between are laid out again on the new line; when the overflowing character is itself the candidate it gets
  no quad but the count still grows by 1). Without a candidate the current glyph is placed at the start of the
  new line and its advance is not added to lineWidth. Otherwise lineWidth = lineWidth'.
- Layout stops, without writing the results back, when the line top is below draw y + maxHeight × sy.
- **A line feed does not force a new line** in `nUi::Text`; it is only a break candidate.
- Horizontal alignment uses the width of the whole string, not of each line, so wrapped text is positioned
  correctly only with `align="left"` [inferred from step 2].
- Results written back: the widest line, max over placed glyphs of trunc(lineWidth + 0.5), and the total
  height, which starts at the unscaled lineHeight.

**Fitting helpers** [known]: `TruncateToWidth(maxRel)` S 004b4ba0 removes characters from the end until
width ÷ screen width < maxRel, then appends `...`; `SetTextFitted(str, maxPixels)` S 004b4e60 shortens until
width ≤ maxPixels and appends `...` to every shortened candidate (the ellipsis is part of the measured string);
returns false and leaves the text unchanged if nothing fits or if the string is empty. `TruncateToWidth` adds no
ellipsis when it removed every character.

### 3.2 Rich text: `TextBlock` markup [known] S 004e4270, S 004e3fa0, S 004e3d20

`TextBlock` (attributes `font`, `content`) feeds its text to a `RichTextLayout` whose rectangle is the widget's
rectangle in pixels (S 004b7c50). The XML `font` is registered under the 4-byte key `sys\0` and is the default
font; a `content` that starts with `!` is a localisation key (S 004b7e90).

Grammar: `<` starts a tag that ends at the next `>`; the tag is removed from the visible text. Text collected
before the tag is closed as a segment first, so a tag changes the segment that starts at it. Tag content, tested
in this order (a horizontal name and a vertical name are tested independently; the last two rows only if neither
matched):

| Tag | Effect on the segment that starts here |
|---|---|
| `left`, `hcenter`, `right` | horizontal alignment |
| `top`, `vcenter`, `bottom` | vertical flag of the segment. Rendering only tests `vcenter` (below), so `top` and `bottom` draw alike |
| exactly 4 characters, none of the above | font switch: the 4 bytes are a key into the layout's font list. A key that is not in the list is not guarded (null font) [inferred] |
| four floats (parsed with `%f %f %f %f`) | segment colour: the four values are stored in tag order as r, g, b, a [known] S 004e3fa0 (disassembly) |
| anything else | ignored |

A style applies from its tag to the end of the text (each new segment copies font, colour and alignment of the
previous one). The shipped text tables use `<hcenter>` (4 times) and no other tag [known: data].

Line building:

1. Spaces are skipped while the line width is 0.
2. Line feed ends the line (a line feed that is the last character does not).
3. Width test per character with `GetCharAdvance` (xAdvance + charSpacing): if lineWidth + advance > maxWidth,
   search backwards from the current character to the start of the current segment for a space; break after it.
   Without a space in the segment the break is before the current character. Space is the only break character
   (the first character of the segment is not examined).
4. Line height = lineHeight of the tallest font used in the line. Layout stops when total height + line
   height ≥ maxHeight, tested each time a segment is closed. The rest of the text is dropped if that sum is
   greater than maxHeight; if it is equal, the whole rest is appended to the last segment as one unwrapped line.
5. Results: textWidth (widest line), textHeight (sum of line heights).

Rendering: per line the x origin is x (left), x + maxWidth ÷ 2 − lineWidth ÷ 2 (hcenter, both divisions on
integers) or x + maxWidth − lineWidth (right), decided by the alignment of the line's first segment; lineWidth =
Σ `GetTextWidth` of its segments. Each segment is drawn left-aligned with its top at line y + (lineFont.base −
font.base), that difference halved with `vcenter`; the next segment of the line starts at x + the width the
glyph builder reports (Σ xAdvance without charSpacing, §3.1). A segment of length 0 only advances y by the line
height. Alpha = segment alpha × `TextBlock` text alpha × widget opacity (S 004b79c0).

The lobby's chat bubbles use the same layout in plain mode (tags not interpreted) [known] S 00505c10.

### 3.3 Sprites: `Shape` [known] S 004aa310, S 004a8f70, S 004a88a0

- Destination rectangle = the owner's rectangle converted to whole pixels (absolute position and size × screen
  size).
  Skipped without a texture or with a mapping of width 0 and height 0.
- All four borders 0: one quad. Otherwise nine-slice in **source pixels**: the four corners are drawn at their
  source size (border widths), then
  - `stretch="true"` (default): top, bottom, left, right edge and centre are one stretched quad each;
  - `stretch="false"`: edges and centre are tiled with the source inner size as tile size; the last tile of a
    row or column is drawn into the remaining space with the full source tile [inferred: the remainder quad
    keeps the full source rectangle].
- Every quad is offset by (−0.5, −0.5) pixels (constants S 0087c50c, S 0087c510) so texels land on pixel centres.
- `flipped`: the v coordinates of top and bottom are exchanged (vertical mirror).
- Rotation (u16 at Shape +0x92, set by code): the quad is rotated about its centre by
  −value ÷ 65536 × 2π radians (S 00882840 = 6.2831855), so 65536 is a full turn.
- Sampling is unfiltered when the owner's `pointfiltering` is set (Object +0x180).
- Colour: `disabledColor` while the owner or any ancestor is disabled (`IsFlagE4SetInHierarchy` S 0042e330),
  else `color`; then × widget opacity. Children's shapes therefore grey out with a disabled parent, each in its
  own `disabledColor` (default 0.4667, `Shape::ctor` S 004aa5a0). `AlphaFanPicture` builds its fan quads with a
  white vertex colour × alpha and never uses the disabled colour (S 004cd4a0).
- With a mask texture the quad goes through the masked path with `maskUV0`, `maskUV1`.
- `Shape::BindTexture` S 004a86d0 (a picture bound by code, such as a render-target preview) sets the texture,
  the mapping (0, 0, texture width, texture height) and the size; it keeps the borders and `stretch`, so a
  nine-slice shape draws the bound picture with its corners at the border size [known].
- The mapping is divided by the size of the texture as created, and UI textures are created with
  `D3DX_DEFAULT` sizes (`CTexture::CreateD3DTexture`, S 004e7a9e): a picture whose sides are not powers of two
  is stretched to the next powers of two, so its mapping covers the stretched image ([ingame-ui.md](ingame-ui.md)
  §3.1.6) [known].

### 3.4 Button, ButtonEx, check box, PictureButton

Additions to [ingame-ui.md](ingame-ui.md) §3.2.1.

**Visual state** (`UpdateMapping` S 004af080, run every update while the button and its ancestors are enabled and
visible) [known]: from Focus state 0 / 1 / 2 and `marked`. Style 0: normal, hover, and (pressed or marked) share
three atlas rows (208 × 32 at x 8, y 184 / 224 / 264); style 1 and 3: normal and (hover or pressed) (152 × 20 at
x 264, y 224 / 248 and 176 / 200); style 2: hover differs, pressed = normal (224 × 19 at x 264, y 8 / 32);
styles 4 and 5 (the check box look): 28 × 28 at (132, 100) unmarked, (164, 100) marked, independent of hover;
style 6: three whole textures `texture_not_selected`, `texture_selected`, `texture_pressed` for state 0 / 1 / 2;
style 7 and every number above 12: the mapping is left alone; style 8: 136 × 22 at x 8, y 848 normal, 872 hover
or pressed; styles 9, 10, 11: normal / hover / pressed at y 895 / 927 / 959, 64 × 20 at x 159 (style 9),
64 × 20 at x 511 (style 10), 288 × 20 at x 223 (style 11). Style 12 uses the four XML mappings and does not
read the Focus state: `mapping_marked` if marked, else `mapping_cursoroverandpressed` while `buttonPressed[0]`
is set (also with the cursor outside), else `mapping_cursorover` while hovered (+0x144), else `mapping`.
In styles 0 to 11 a Focus state outside 0..2 changes nothing. Atlas for the numbered styles: `uiElements0`
([ingame-ui.md](ingame-ui.md) §3.2.1).

**Caption** (`LayoutCaption` S 004afa10, `Draw` S 004afd10) [known]: the caption `Text` is positioned at the
centre of the button (half width, half height − 0.001 of the screen height) and keeps `align` centre, so it is
centred both ways. Per style:

| Style | Font | y shift | Colour idle / hover or pressed |
|---|---|---|---|
| 1, 2, 3, 7 to 11 | `Subline_Garamond` | +1 px | (229, 209, 196) / white |
| 4 | `Subline_Garamond`, left-aligned at x = 32 px | +4 px | (0.75, 0.75, 0.75) / white |
| 5 | as 4 | +4 px | (229, 209, 196) / white |
| 0 and other numbers | `Body_Arial` | −0.002 of the screen height | (229, 209, 196) / white |
| 6 | `Body_Arial` | −0.002 of the screen height | caption not drawn |
| 12 | `font`, while hovered or pressed `font_cursorover`; `Body_Arial` if the text has no font | none | the `<text color>` |

Style 7 draws through the base `Object::Render` instead of the button sprite.

**Check box**: `checkbutton="true"`; a click toggles `marked` before the click events go out (S 004b12d0).
`ui.createCheckedButton` creates one from Lua ([lua-runtime.md](lua-runtime.md) §3.7).

**Mouse** [known] S 004aeca0, S 004aecf0, S 004b1270, S 0049ff60, S 004a0020:

- Down (button 0, widget hovered or holding the capture, enabled with enabled ancestors): `OnPressed`, Focus
  state 2, `buttonPressed[0] = 1`.
- Up (only delivered if `buttonPressed[0]`): if the widget is still hovered the click latch (+0x119) is set;
  Focus state 2 → 1; `buttonPressed[0] = 0`; then `OnClicked` runs if the latch is set. Releasing outside
  does not set the latch, so it cancels the click, unless the latch is still set from an earlier click: only
  the owner's poll (`Widget_ReadClearClickLatch` S 0049fdb0) clears it, the release handler does not
  [known: over all instructions that address the byte (displacement 0x119, or 0x111 on the Event face) the
  writers are the constructor (0), the poll (0), the release handler S 0049ff9a (1), two setters of 1
  (S 0042e560, S 004af9a8) and the copy in `CopyPropertiesFrom` S 004a7f6c]. A button that nobody polls
  therefore keeps the latch after its first click, and every later release that is delivered to it runs
  `OnClicked`, hovered or not [inferred].
- Double click (event type 1): `OnPressed`, the double-click observers, then the same as a down. Because the
  second press of a double click arrives as type 1 instead of type 0, a fast double click yields
  press, click, press + double-click, click.
- Wheel over a hovered button whose parent is kind 14 and whose grandparent is kind 22 (`ListBox2`): forwarded
  to that list's slider as one step, +1 for a negative delta, else −1 (S 004aed50).

**Events** [known] S 004b12d0, S 004b1470: `OnPressed` → pressed observers, parent vtable +0x68 (bubbles),
Lua function `<name>_isPressed`. `OnClicked` → toggle (check button), sound `uiClick0`, parent `OnChildClicked`
(vtable +0x64, bubbles to the first class that overrides it), clicked observers, Lua `<name>_isClicked`. The Lua
calls are made only while the script gate is set and the function exists
([lua-runtime.md](lua-runtime.md) §4.4).

**PictureButton draw** (vtable slot 1, S 004b3a60) [known]: the picture shape (+0x468, e.g. an action or
sacrifice icon) is drawn first, then `Button::Draw` S 004afd10 draws the button's own shape (+0x198) with its
state mapping, the children (`Object::Render`) and the caption. The state picture therefore lies over the icon.

### 3.5 Icon [known] S 004ce780, S 004ceaa0, S 004cf3a0

`type` = display mode. Mode 0 and 2: draw `shape`, then `symbol`. Mode 1 (layered): draw `texture_not_selected`,
on top `texture_selected` while hovered or `texture_pressed` while pressed, then `symbol`, then `texture_marked`
if marked. In every mode except 1 `UpdateShapeTexture` swaps the shape's texture instead: marked →
`texture_marked` (if it has one, else no change), else by Focus state 0 / 1 / 2 → not selected / selected /
pressed. A mode other than 0, 1, 2 draws no sprite. Click sound `uiClick1`.

### 3.6 Edit (single line, shared buffer)

No layout shipped with the game uses `controltype="Edit"` [known: data]; code creates it.

- **Focus**: left press while hovered → `SetFocus` (copies the widget text to "before cursor", clears "after
  cursor", stores the original, copies maxLength), sound `uiClick0`, then, if the text has more than one
  character, places the caret before the first character i for which cursor x − 3 px < width of the first
  i + 1 characters; if there is none the caret stays at the end [known] S 00497b60.
- **Draw**: sprite, then the text; with focus the text is `before + "|" + after`: the caret is the glyph `|`,
  always shown, no blinking [known] S 00498100.
- **Characters** (`Edit::OnChar` S 00496fc0, `nUi_TextInput_InsertChar` S 004c07e0) [known]: the focused `Edit`
  consumes every character, whatever happens to it. Ignored if input is disabled or
  the character is `<`. Codes below 0x20 have no effect. If
  len(before) + len(after) > maxLength the character is dropped; otherwise it is appended to "before" and
  `uiKey0` plays. So the field holds at most maxLength + 1 characters. The restricted set (switch never set in
  the shipped image) is space, 0-9, A-Z, a-z and `ä Ä ö Ö ü Ü ß ! & ( ) + - _ ç â á à ô é è ê`
  (S 007e16a8).
- **XML** (S 004970e0) [known]: `type`, `maxlength`, `maxlengthinpixels`, `mapping`, `mapping_cursorover` and,
  spelled this way in the image, `m_mapping_cursoroverandpressed` (`mapping` is copied to the other two
  before they are read); children `shape`, `focus` and `text` (string at S 007d7bb4).
- **Pixel limit** (`Edit::Update` S 00497f50) [known]: each frame, while the widget has the focus and is
  enabled, if "before" + "after" is wider than `maxlengthinpixels`, the last character of "before" is removed.
- **Keys** (`nUi_TextInput_HandleKey` S 004c0a40, on key down) [known]: Left, Right move one character; Home,
  End; Backspace deletes before the caret (`uiKey0`); if len(before) > maxLength + 1 Backspace clears the whole
  field; Delete deletes after the caret (`uiKey0`); Space inserts a space; Insert is swallowed; Esc compares
  "before" with the text at focus time and, if they differ, restores it and clears "after" (and is then
  consumed, otherwise it passes on). Key-up of Left, Right, Home, End, Backspace, Delete, Space, Insert and Tab
  is consumed without effect (S 00496f80). No selection, no clipboard.
- **Tab** (S 00498250) [known]: among the parent's children of kind 6 (if there are at least two), focus moves
  to the first with a larger z-order (+0x178), with Shift to the last with a smaller one, wrapping round.
- `Enter` is not handled as a key. Its character (13) is consumed by the focused `Edit` like every other
  character, so a `hotkey="13"` button does not fire while an `Edit` has the focus [inferred from `OnChar` and
  the hotkey pass of [ingame-ui.md](ingame-ui.md) §3.3.1].

### 3.7 EditEx (the edit field of the shipped layouts)

**XML** [known] S 0049ebd0: `mapping`, `mapping_cursorover`, `mapping_cursoroverandpressed` (the first is copied
to the other two before they are read), `padding` (4 numbers: left, top, right, bottom [inferred from the default
4 1 4 2 and the text area 233 × 15 of a 241 × 18 mapping]), `multiline`, `breakonedge` (word wrap), `font`,
`isPassword`, `autohide`, `clearonesc`, `allowedChars` (UTF-8 in the file, converted to the ANSI code page),
`maxLength` (< 1 = unlimited), `readOnly`, `text` (localised if it starts with `!`), child `VScroll` (a
`SliderEx`) and the tip. Shipped examples [known: data]: `lobbyLoginDialog.xml` `Username` with
`maxLength="20"` and `allowedChars="abc…XYZ0123456789äöüÄÖÜß+-_."`, `CDKey` with `maxLength="19"` and
`allowedChars="abc…XYZ0123456789-"`, `Password` with `isPassword="true"`; `lobbySetPasswordDialog.xml`
`PasswordEdit` with `font="Head_Garamond"`, `mapping="848 80 170 34"`, `padding="6 6 6 6"`; the chat input of
`templates.xml` with `maxLength="255"`, `autohide="false"`, `clearonesc="true"`, `padding="12 4 12 4"`.

**Creation** [known] `EditEx::Create` S 0049e4a0 (the factory's creation slot): font `Body_Arial`, texture
`ui_menus`.

**Focus** [known] S 00498c60, S 0049b7b0: left press while hovered focuses it (resets the caret timer, cancels
its tooltip, clears the `Edit` focus global; `uiClick0` only when focus changed). A read-only field takes focus
but ignores keys and characters. The focus global (S 00885ca8) is written only by `SetFocus` S 00498c60, the
release S 004988f0 (Esc in `HandleKey`, `ClearInput` S 004abe00), the detach and parent-hidden handlers and Tab,
so a click on another kind of widget (a list row) leaves the field focused [known].

**Mouse** [known] S 0049b7b0, S 0049b9b0, S 0049bae0, S 0049a3a0: a press inside the text area sets the caret
from the pixel and the selection length to 0. A plain press leaves no anchor (the anchor index ends at −1), so a
drag selects nothing and the release only moves the caret to the release point. With Shift held the old caret
becomes the anchor: mouse moves set caret and selection length = caret index − anchor index (signed), and the
release does the same and clears the anchor; a release outside the text area only clears it.
`SetCursorFromPixel` S 00499cd0 returns without a change for a point outside the widget; else with
textX = x + horizontal scroll: textX < 1 gives column 0, textX ≥ the line width gives the line's length, otherwise
the column of the glyph whose [x, x + advance) holds textX, plus 1 when textX − advance ÷ 2 − glyph x ≥ 0 (the
half rounds right); a textX in no glyph (a gap) gives the line's length. Double click selects the word under the cursor
(word start to word end) and suppresses the following release.

**Characters** (`HandleChar` S 0049f100) [known]:

| Input | Effect |
|---|---|
| code ≥ 0x20 | if `allowedChars` is not empty and lacks the character: swallowed. If the text is at `maxLength` and nothing is selected: swallowed. Else inserted (replacing the selection), caret clamped, view scrolled to the caret |
| Ctrl+A (0x01) | select all |
| Ctrl+C (0x03) | copy the selection; without a selection copy the caret's line |
| Ctrl+X (0x18) | cut the selection; without a selection cut the caret's whole line |
| Ctrl+V (0x16) | paste, truncated to maxLength − length + \|selection\| characters; the pasted text is not filtered by `allowedChars` |
| Tab (0x09) | inserted only with the allow-tab flag, else not handled |
| Enter (0x0a, 0x0d) | inserted only if `multiline`, else not handled (so `hotkey="13"` buttons fire) |
| 0x08, 0x0b, 0x0c, other codes < 0x20 | not handled |

**Keys** (`HandleKey` S 0049f530, on key down) [known]: Backspace and Delete remove the selection, else one
character; Ctrl+Backspace first moves the caret to the previous word boundary and then deletes one character
(`MoveCursor` S 0049bc40); Left / Up / Right / Down move the caret (Shift extends the selection; Ctrl+Right jumps
to the next word boundary; character classes and word boundaries S 004985e0, S 00498760, S 00498fd0,
S 00499030); Home / End go to the start / end of the line (with Ctrl of the text; End on a soft-wrapped line
stops before the trailing space); Space inserts a space under the same rules as a character; Esc releases focus
and, with `clearonesc`, empties the field; Tab without the allow-tab flag moves focus to the next (Shift:
previous) `EditEx` sibling by z-order, wrapping round (S 0049c6f0, children of kind 7, at least two). Key-up of
the same keys is consumed (S 0049fba0). Enter (0x0d), on key-down and on key-up: if the Enter-capture flag
(+0x348) is set, the Enter latch (+0x349) is clear and the field is not `multiline`, the latch is set and the
key is consumed; otherwise the key is not handled. In the shipped image this path is dead [inferred: over all
instructions with a displacement of 0x348 or 0x349 the only byte accesses on an `EditEx` are the constructor's
two clears (S 0049daa4, S 0049daaa), the two tests of the flag (S 0049fabd, S 0049fc1b) and the test and set
of the latch in the two key handlers (S 0049fac6, S 0049fad8, S 0049fc24, S 0049fc36); nothing sets the flag
and nothing reads or clears the latch]. Enter in a single-line `EditEx` is therefore never consumed.

**Clipboard** [known] S 004994a0, S 0049a6d0: Windows clipboard, format `CF_TEXT` (1) only, ANSI.

**Draw** [known] S 0049ad00, S 0049a750: sprite; then, clipped to the text area, the visible lines from the
scroll line (one line if not `multiline`), each left-aligned in white × widget opacity; password mode draws `*`
per character; the selection is a white rectangle with alpha 0.33 over the selected span; the caret is a
vertical line of the line's height in colour ARGB 0xff0000ff, drawn while the caret timer ≤ 500 of its 1000 ms
cycle, only with focus and not read-only. The timer adds the frame time in ms, modulo 1000 (S 0049a090).
The mapping follows the Focus state, the mouse state (0 / 1 / 2 → the three mappings; 2 = left button pressed on
the field), not the keyboard focus, and only while the field and its ancestors are enabled; the shipped layouts
give all three the same rectangle. The horizontal scroll keeps the caret
inside the text area (`ScrollToCursor` S 0049af70).

**No IME**: text arrives only as `WM_CHAR` single bytes; the window procedure handles no `WM_IME_*` message
[known] S 00401f30. A key-down that a widget handled is not translated, so it produces no `WM_CHAR`
[inferred] S 00407cf0 (`TranslateMessage` only when the dispatch returned non-zero); that is why Space is
inserted on key-down in both edit classes.

### 3.8 Slider and Slider2

**Slider2** (the slider of the shipped layouts; value is a fraction 0..1) [known] S 004d0200, S 004d02f0,
S 004d0790, S 004d0830, S 004d0770, S 004cfdf0:

- `SetValue(v)`: with snapCount > 1, v = floor(v × (snapCount − 1) + 0.5) ÷ (snapCount − 1); clamp to 0..1; if
  changed: move the throttle, notify the observers and set the changed flag (cleared at the next update).
- Drag (only while enabled, with enabled ancestors, and visible): starts when the widget is hovered and holds a
  left press (`buttonPressed[0]`); continues until that press ends, also when the cursor leaves. Each frame
  v = (cursor − throttle size ÷ 2 − trackStart) ÷ (trackEnd − trackStart) on the slider's axis (x if
  orientation 1, else y; not divided if the range is 0).
- Track (S 004cf720, S 004cf820): trackStart = position + size of the `leftUp` button if it is visible, else 0;
  trackEnd = position of the `rightDown` button if it is visible, else the slider's own size; minus the throttle
  size. Throttle position = trackStart + v × (trackEnd − trackStart) (S 004cff30).
- Step buttons: `leftUp` → v − 1 ÷ snapCount, `rightDown` → v + 1 ÷ snapCount; snapCount 0 counts as 10.
- Wheel while hovered: +0.1 for a positive delta, −0.1 otherwise. Double click: v = 0.5.
- Value text (`useText`): `snprintf(textFormat, textValMin + (textValMax − textValMin) × v)` into 128 bytes
  (`%f` with a precision and `%%` are the forms the layouts use).
- Hover: `mapping_cursorover` while hovered, else `mapping` (S 004cf4a0, S 004cf5e0). With the `templates.xml`
  `slider` (130 px wide) the track runs from 16 to 105 px [known: data and the rule above].
- XML (S 004d04b0): children `throttle`, `leftUp`, `rightDown`, `text`; attributes `mapping`,
  `mapping_cursorover`, `useText`, `textValMin`, `textValMax`, `textFormat`, `value`, `snapCount`. There is no
  orientation attribute: the factory (`CreateObject` S 004c28a0, case 2) calls `Init` S 004d0040 with snapCount 0
  and orientation 1, so every layout slider is horizontal [known].
- The value text (`UpdateValueText` S 004cfdf0) computes the value in single precision, widens it to a double and
  formats it with the CRT formatter S 006f6ab6 into 128 bytes, then sets it without localisation; any printf
  conversion with one double argument works, and only `%.0f%%` is shipped (`menuoptions.xml`) [known].

**Slider** (older class, kind 1) [known] S 004d1060, S 004d1390, S 004d0950, S 004d0d00: XML `type`, `speed`
(default 0.2), `snapcount`, children `shape`, `bar`, `throttle`, `focus`. Types 0, 3, 4 are vertical, 1 and 2
horizontal. While it is enabled, visible and holds a left press (`buttonPressed[0]`), each frame
value += (cursor ÷ widget size − value) × 0.75 (it eases towards the cursor). Wheel while hovered: value +=
speed for delta ≤ 0, −speed otherwise. After every change `UpdateThumbPosition` clamps the value to 0..1 and,
with snapcount > 1, sets it to floor(value × (snapcount − 1) + 0.5) ÷ (snapcount − 1). Throttle position:
type 0: y = value × (slider height − throttle height), x = 0; types 1, 2: x = (slider width − 23 px) × value
+ 2 px, y = 0; types 3, 4: y = (slider height − 26 px) × value + 12 px − half the throttle's width value
[inferred: the last term mixes a pixel value with the throttle's stored width], x = 0.

### 3.9 SliderEx: the scroll bar [known] S 004b9270, S 004b92f0, S 004b9350, S 004b9890, S 004b9a40, S 004b9bb0

- XML: `Type` = `horizontal` / `h` / `horz` (1) or `vertical` / `v` / `vert` (0), `Value`, `SnapCount` (< 1 →
  no range), children `Throttle`, `Decrease`, `Increase` (S 004b94c0).
- Value is an integer 0..count − 1. `SetValue` clamps, sets valueChanged when asked to notify, repositions the
  throttle. `SetCount(n)`: n < 1 → no range; re-clamps the value. `StepValue(d)` = `SetValue(value + d)`,
  ignored while disabled or without a range.
- Throttle travel: min = 2 px, max = track length − 2 px − throttle length (per axis). Position =
  min + (max − min) × value ÷ (count − 1), 0 if count < 2.
- Press on the bar (enabled, active): takes the input capture and sets dragging; release clears both.
- While dragging, each frame: t = (cursor − throttle length × 0.5 − min) ÷ (max − min) (not divided if the
  range is 0), value = trunc(t × count), clamped by `SetValue`.
- `Decrease` / `Increase` buttons step −1 / +1 (not while dragging) (S 004b9640). Wheel while hovered: +1 for a
  negative delta, −1 otherwise. Double click: value 0.

### 3.10 ListBox2 [known] S 004b8880, S 004b8590, S 004b90d0, S 004b9180, S 004b8280, S 004b80e0

- XML: `itemSpacing`, `markSingleItem`, children `container`, `item` (row template), `slider`. Rows are clones of
  the `item` `PictureButton`; `AddTextItem(text)` clones one and sets its caption (S 004b9000, S 004b90a0).
- Layout: rows are stacked top to bottom at y = Σ of the heights of the rows before (pixels); the container's
  height becomes that sum (`itemSpacing` is not used here). If the sum fits in the list's height the slider
  gets no range, else its count is ceil((sum − list height) ÷ height of the first row) + 1 [known] S 004b8880
  (disassembly).
- Scrolling: each frame the container's y = −sliderValue × (itemSpacing + height of the first row), both as
  screen fractions (0 without a range); a row is
  visible only while it overlaps the list rectangle vertically. Wheel over the list = one slider step (down for a
  negative delta).
- Clipping: the `container` is only the rows' parent and never clips (its layout height is overwritten by the
  row sum). A list clips only through its own `clipping` attribute, to its own rectangle
  (`Object::ApplyClipRect` S 004a58a0); the rows' width comes from the `item` template [known].
- Selection: a clicked row reaches `OnItemSelected`; with `markSingleItem` every row's `marked` becomes
  (row == clicked) and the "row selected" observers are called with the row (without `markSingleItem` neither
  happens); then the click bubbles to the parent. A row's double click calls the "row double-clicked"
  observers. `SelectIndex(i, scroll)` does the same from code; `ScrollItemIntoView` does nothing if the slider
  has no range or the row already overlaps the view, else it sets the slider to i (if i is below the value) or
  to i − (rows − count) (if i is above value + rows − count).
- `Listbox` (kind 21) and `Item` (kind 0) are an older, code-created list with a fixed number of visible rows
  [inferred] S 007675d0, S 00765fc0. [TODO] not established: its row and scroll rules (static read of those two
  functions).

### 3.11 DropDownMenu, ComboBoxNew [known] S 004b38b0, S 004b2690, S 004b2700, S 004b29c0, S 004cc180, S 004cb350

- XML: `size` (number of rows), `string0`… (`!`-keys are localised), `dropdownoffset` (pixels), children
  `button` (header) and `item` (row template); `ComboBoxNew` also `selection`.
- Click on the header while closed: open = show all rows, bring the widget to the front of its siblings, take the
  input capture. `DropDownMenu` notifies its "opened" observers first; `ComboBoxNew` marks the header and lays
  the rows out again (S 004cb9e0), and unmarks the header when it closes (S 004cb2b0).
- Rows are stacked below the header starting at `dropdownoffset`, each one row-template height apart; if the
  list would end below the screen (absolute y + list end > 1.0) all rows are shifted up by the overshoot.
- Rows stand at x 0 of the widget (S 004b29c0).
- Click on a row while open: `DropDownMenu` notifies "item chosen" with the row index and closes;
  `ComboBoxNew` sets `selectedIndex`, writes the row text into the header caption fitted to combo width − header
  button width − caption x pixels, each term truncated to whole pixels (ellipsis rule of §3.1; the caption x is
  the header button's `Text` position as `LayoutCaption` leaves it: half the button's width, 32 px for button
  styles 4 and 5) [known] S 004cb350, closes and notifies "selection changed" with the
  index. A `ComboBoxNew` then passes every child click on to its parent; a `DropDownMenu` does not.
- A mouse-down anywhere that no part of the open menu handles closes it and is returned unhandled (S 004b2790);
  because the open menu holds the input capture (S 00885cb4), `Root::HandleInputEvent` S 0049141a gives that click
  to no other widget, while the window handler feeds the game's action map regardless (S 00401f30) [known]; any key-down closes a
  `DropDownMenu` (S 004b2770). Closing hides the rows and releases the capture.
- `ComboBox` (kind 18) is an older variant (`string%u`, `data%u`) [TODO] not read here (S 004bf090).

### 3.12 TabControl [known] S 004bad00, S 004b9f60, S 004ba120

XML: `count`, `mappingTabActive`, `mappingTabInactive`, `fadetime`, `defaultTab`, children `tab<N>` (pages) and
`tabButton<N>`, N from 0. A click on a tab button is not passed on to the parent; clicks of other children are.
A click on tab button N (if N is not the active tab): the old page is hidden (or `FadeOut` over
`fadetime` if it is not 0) and its button gets `mappingTabInactive` in all four state mappings; the new page is
shown at opacity 1 (or `FadeIn`) and its button gets `mappingTabActive`. On load every tab is set inactive and
`defaultTab` (if present) is activated without fading. `LayoutTabButtonsHorizontally` S 004ba3f0 packs the
visible tab buttons left to right from the first button's position.

### 3.13 ProgressBar, Graph

- **ProgressBar** [known] S 004bd580, S 004bd280: value clamped to 0..1; the `bar` child's width = full width ×
  value (the picture is squeezed to that width, not cut); the marker child sits at its base position + that
  width. The constructor sets the value to 0, but the fill is computed only when a value is written, so a bar
  that its owner never writes keeps its layout width (a full bar).
- **Graph** [known] S 004c9410, S 004c7f90: the point list is smoothed `smoothingIterations` times; one pass
  moves every interior point towards the midpoint of its two neighbours by `smoothingStrength` (new = p +
  (mid − p) × strength, using the neighbours' values of the previous pass); fewer than 3 points are not
  smoothed. The line is a textured strip (`texture`, `mappingX` 4 values, `mappingY` 2 values in texture pixels)
  of width `lineThickness`, drawn at the widget position + `offset` with size × `scale`, with the stencil test
  preventing overdraw. `alphaani = (f, a)`: if f ≠ 0, alpha × (1 − (sin(t × f) × a + a)), t = seconds since
  start (the UI timer's total seconds). `lineani = (p, k)`: if p ≠ 0, the thickness of a frame grows by
  k × lineThickness when (`rand()` & trunc(p)) = 0 [known] S 004c7f90 (disassembly). `Chart` (kind 25) is not
  read here.

### 3.14 ChatSystem [known] S 004ad150, S 004ae670, S 004ae200, S 004adb20, S 004ac430

- XML: `MinHeight` (default 72), `MaxHeight` (default 212), children `ChatInput` (an `EditEx`),
  `ChatScrollbar`, `ChatMinimize`, `ChatMaximize`, `ChatButton` (template of the per-channel buttons) and
  `<ChatOutput x y width height lineSpacing>` (defaults 0, 0, 238, 15, 2; pixels).
- Height: each frame the widget's height is `MinHeight` while minimised, else `MaxHeight`; the minimise button
  sets the flag, the maximise button clears it. A mouse-down on the chat clears its animations and shows it.
- Channels: ids are caller-defined; id 0 is invalid, −1 = every channel, −2 = the active channel. A click on a
  channel's button makes it the active channel. `SetActiveChannel` refuses a disabled channel unless forced.
- `AddText(channel, senderTag, text, colour)`: the text is word-wrapped to the output width with the break
  characters ` \t\n.:,;+-*/=` and trimmed of ` \t\n`; empty pieces are dropped; each piece becomes a line
  `{senderTag, colour ARGB, text}`. At `maxLines` (256) the oldest line is discarded. If the view is scrolled
  back it stays anchored (scroll-back count + 1), else it shows the newest line.
- Draw: nothing unless 0 < lineHeight ≤ height. Line step = font lineHeight + lineSpacing; n = (height −
  lineHeight) ÷ step (integer); up to n + 1 lines are drawn bottom-up from the newest (minus the scroll-back),
  left-aligned at x, each in its own colour × alpha; the lowest line's top is y + height − lineHeight −
  ((height − n × step − lineHeight) ÷ 2), each further line one step higher.
- Scroll bar: moving it sets scroll-back = lineCount − value − 1, floored at 0 (0 = follow newest); otherwise
  the bar is set to lineCount − scroll-back − 1 each frame [inferred: `ChatLog` +0x14 read as the line count].
- A click on the output area hit-tests the line under the cursor and calls the "line clicked" observers with
  that line (used for clicking a sender name) [inferred from S 004ae670].

No shipped layout carries `controltype="ChatSystem"`: the object is created in code (`nMenu::Game`,
`LobbyMenu::WorldScreen`) and configured by the layout node of its name with the template `LobbyChat`
(`menuingame.xml` `<chat template="LobbyChat">`, `lobbyWorldScreen.xml` `<Chat template="LobbyChat"
MinHeight="112" MaxHeight="384">`; the template itself sets `MinHeight="72"`, `MaxHeight="384"`) [known: data,
callers of S 004ade70].

### 3.15 Animations [known] S 004d1fc0, S 004d2020, S 004d2110, S 004d2220, S 004d22c0

- Base: `Start` fails for duration ≤ 0; it stamps startTime (seconds, the UI timer) and notifies "started".
  `Update` does nothing once finished; else it auto-starts an animation that is not running, and stops it when
  now − startTime ≥ duration (never for duration 0).
  Progress t = min(1, (now − startTime) ÷ duration), 0 if duration is 0. `Stop` sets finished and notifies
  "stopped". The owner deletes finished animations in its next update (§4).
- Easing 1 = smoother-step: e(t) = ((6t − 15)t + 10)t³.
- **AlphaFade**: start sets opacity = from and makes the target visible. Each update opacity =
  from + (to − from) × t, then, with easing 1, opacity = e(opacity). On stop with to = 0 the target is hidden
  and its opacity reset to 1. `FadeOut(obj, d)` S 004c3c30: nothing if the object is invisible; a running fade
  is stopped and the new one starts from the current opacity (else from 1) to 0. `FadeIn(obj, d)` S 004c3d50:
  the start value is 0, or the object's current opacity if a running fade had to be stopped; the object is
  shown, its opacity set to the start value, and the fade runs to 1 [known] S 004c3d50 (disassembly). The
  member `Object::FadeIn` S 0049fea0 calls it; a recursive fade sets the opacity of the whole subtree
  (`SetOpacity` S 004a0630).
- `nUi::Object::Hide` S 004a1130 stops no animation: a fade that runs goes on after the hide [known].
  `ClearAnimations` S 004a23a0 removes the widget's own animations only, not those of its children [known] (the
  pause panel's text pulse survives `SetPaused`, [ingame-ui.md](ingame-ui.md) §3.4).
- **AlphaPulse** S 00763510: alpha = min + (max − min) × (0.5 + 0.5 × sin(2π × frequency × elapsed)), applied
  with `SetAlpha` while the target is visible. On a `Label` `SetAlpha` (vtable +0x40, S 004b1d90) writes the
  text colour's alpha, not the opacity, so the drawn alpha is pulse × opacity (§3.1) [known].
- **Scaler** S 004d25e0, S 004d24d0, S 004d2390: start pushes a copy of the target's deployment, records base
  position and size, clears dock and alignment. Scale s = from + (to − from) × t (per axis); pingPong replaces t
  by a triangle wave of the total time × speed; easing 1 is applied to t, not to the scale
  (`AnimationScaler::Update` S 004d24d0) [known]. Applied about the centre: size = base × s,
  position = base + half × (1 − s). Stop pops the deployment copy.
- **Mover** S 00769010, S 00768e80: same push / pop; position = base + from + (to − from) × t (reverse: from and
  to exchanged); optional hide on stop.
- **TransformFade** S 004d2b00: interpolates between key 0 and key 1 (position and scale linearly, rotation by
  quaternion lerp) and writes the target's local 4×4 matrix. `nUi_AttachScaleInAnimation(target, d, angle)`
  S 004c39b0: scale 0 and a z rotation of `angle` degrees → scale 1 and no rotation, smooth; the scale-out
  variant S 004c3af0 runs the reverse.

### 3.16 Cursor

Covered by [ingame-ui.md](ingame-ui.md) §3.2.4 (cursor table, hot spots, animated cursors, wheel decay). The
toolkit cursor is the OS cursor: widgets read its position as a screen fraction (`Cursor` +0x24, +0x2c) and its
per-frame delta (`GetMoveDelta` S 004925c0). `ui.centerCursor` / `WarpToWidgetCenter` S 004927b0 move it.

### 3.17 Dragging, drag and drop

There is no generic drag-and-drop service in `nUi` [known: no such class in the namespace].

- **Grabber** (kind 5; a title-bar handle) [known] S 004bebf0, S 004bea30: when its Focus state becomes pressed
  it starts dragging; while the left button stays down (`g_pActiveAction` vtable +0x34) the **parent's**
  position += cursor delta each frame, clamped to x in 0..1 − parent width and y in 0..0.85 (screen fractions);
  the last position is kept in a global (S 0087c09c).
- **InventoryButton** (kind 38; lobby inventory slots) [known] S 004bdb10, S 004bdb60, S 004bdc10: XML
  `slotIndex`, `slotType` (clamped to i16). It only reports: press → "pressed" observers, release → "released"
  observers (after the normal button release), double click → "double-clicked" observers and the next release
  is swallowed. The item drag itself (ghost icon, drop target) is implemented by the lobby code that subscribes
  [inferred]. [TODO] not established: that code (the subscribers of the lists at +0x59c..+0x5cc).
- Sliders use the input capture or the Focus pressed state as described in §3.8, §3.9.

### 3.18 Scaling

Widget geometry is stored as fractions of the back buffer and rescaled on a mode change
([ingame-ui.md](ingame-ui.md) §3.1.5). What does **not** scale [known]: fonts (native bitmap size, §3.1), nine-
slice corners (source pixels, §3.3), `EditEx` padding and `ChatOutput` rectangle (pixels), the 2 px slider
margins. Text positions are fractions, so captions move with their widgets but keep their pixel size.

## 4. Update order

Per frame, for the whole tree (`nUi::Object::Update` S 004a3920) [known]:

1. The widget's own animations, in list order: a finished one is unlinked and deleted, the others are updated.
2. If the widget's layout flag is 1: `UpdateMouseOver` ([ingame-ui.md](ingame-ui.md) §3.3.2), flag → 0.
3. If the widget's own vtable slot +0x2c returns true [inferred: visibility]: the children, in z-order, from a copy of the
   child vector (children may be added or removed during the pass); a child is updated only if its vtable slot
   +0x10 returns true.

Class-specific work runs before or after that base call: `Button` and `Icon` update their tip (while visible)
and their visual state (while enabled, with enabled ancestors, and visible) first; `Edit` applies the pixel
limit and picks its state mapping first; `EditEx` advances the caret timer (without focus: sets it to 1000 and
updates its tip), picks the state mapping, sizes its text area and synchronises its scroll bar first, and does
only the base call while it or an ancestor is disabled; `Grabber` moves its parent first; `Slider2`,
`SliderEx`, `ListBox2`, `ChatSystem` call the base first and then process dragging, scrolling and button
latches [known] S 004af750, S 004ceb40, S 00497f50, S 0049a090, S 004bebf0, S 004d02f0, S 004b9890,
S 004b8590, S 004ae670.

Input is processed when the window message arrives, outside this pass ([ingame-ui.md](ingame-ui.md) §3.3.1).
Double clicks come from the window class style `CS_DBLCLKS` (class style 0x28, S 00407c90): messages
`WM_LBUTTONDBLCLK` 0x203, `WM_RBUTTONDBLCLK` 0x206, `WM_MBUTTONDBLCLK` 0x209 become event type 1 with button
0, 1, 2 [known] S 00401f30. The class style also carries `CS_OWNDC` (0x20). The toolkit keeps no click timer:
the double-click time and distance are the Windows settings [inferred: these three cases are the only places
in the handler that send event type 1].

Drawing is a separate pass (`RenderRecursive` S 004a1370) [known]: nothing for a widget whose vtable slot +0x2c
(the gate of step 3) returns false; else pre-render (+0x14), the widget's own draw (+4), every child's slot
+0x1c in child-vector order (ascending z-order, so the last child is on top), then post-render (+0x18). The
draw pass reads the live child vector, not a copy.

The z-order is the sort key `+0x178` [known]: `InitAndAttachToParent` S 004a56d0 sets it to the parent's child
count and appends the child, so the children stand in creation order; `SetSortKey` S 004a0ad0 writes it and, on a
change, re-sorts the parent's vector (`SortChildren` S 004a0550: `qsort` ascending with `nUi_CompareBySortKey178`
S 0049fe40; equal keys have no defined order). Events go the other way: `Object::DispatchEvent` S 004a07a0
offers an event to the children from the last to the first and stops at the first that returns 1; a return of 0
lets it go on to the siblings and then to the ancestors' own handlers.

## 5. Inputs and outputs

- **Consumes**: window messages via `nUi::Root::HandleInputEvent`; the UI timer (seconds, and frame delta in ms
  for the caret); the cursor position; textures and fonts from `ai::ui::UiResourceManager`; text tables.
- **Produces**: draw calls through `ai::render::UIRenderer` (quads, glyph quads, lines, debug rectangles) and
  `UIGraphRenderer`; sounds by name through `UiResourceManager::PlaySoundByName`: `uiClick0` (button click;
  every left press on a hovered `Edit`; a press that gives an `EditEx` the focus it did not have; `Item`
  click), `uiClick1` (icon), `uiKey0` (in `Edit`: a typed character, Space, Backspace, Delete) [known]
  S 004b12d0, S 00497b60, S 0049b7b0, S 004c6da0, S 004cf3a0, S 004c07e0, S 004c0a40; see
  [audio.md](audio.md) for the sound table. `EditEx` writes and reads the Windows clipboard (§3.7).
- **Events to code**, three mechanisms [known]:
  1. the click latch (Object +0x119), polled and cleared by the owner (`Widget_ReadClearClickLatch`
     S 0049fdb0);
  2. bubbling virtual calls on the parent: `OnChildClicked` (vtable +0x64), pressed (+0x68) S 004b12d0,
     S 004b1470;
  3. observer lists per widget (button pressed / clicked / double-clicked, slider value changed, list row
     selected / double-clicked, drop-down opened / chosen, combo selection changed, chat line clicked, inventory
     slot events, animation started / stopped).
- **Events to Lua**: `<widgetName>_isPressed` and `<widgetName>_isClicked` global functions, buttons only
  [known: `LuaUi_CallScriptFunctionIfDefined` S 004c44a0 has two callers, S 004b12d0 and S 004b1470]
  ([lua-runtime.md](lua-runtime.md) §4.4). Lua drives widgets with the `ui.*` library
  ([lua-runtime.md](lua-runtime.md) §3.7, [../lua-surface.md](../lua-surface.md)).
- **Network**: none. The toolkit sends and handles no message; chat lines and inventory actions are sent by the
  lobby code that owns the widgets ([../message-catalog.md](../message-catalog.md), "UC / chat connection
  (:7071): token login and chat" and "Inventory").

## 6. Data-driven parameters

| Source | Keys | Example values [known: data] |
|---|---|---|
| layout XML (`data\game\ui\layout\*.xml`, `data\lobby\ui\layout\*.xml`) | the attributes of §3 and [ingame-ui.md](ingame-ui.md) §3.1 | `controltype` values over the 54 shipped files (comments removed, upper and lower case counted together; the files spell them both ways): label 311, picture 288, picturebutton 119, inventorybutton 41, button 36, comboboxnew 28, editex 27, slider2 18, overlaybutton 14, listbox2 12, dropdownmenu 10, textblock 8, tabcontrol 4, container 4, sliderex 2, scroller 1, progressbar 1, stackedslider 1, shapedobject 1; the `nMenu` kinds mainmenubutton 23, sacrificebutton 16, goodbutton 10, avatar 7, roundingamebutton 2, clocksymbol 1 |
| `templates.xml` | `graph` | `lineThickness="0.009"`, `mappingX="806 825 847 866"`, `mappingY="633 657"`, `texture="ui_ingame2"`, `color="1 1 1 1"`, `smoothingStrength="0.2"`, `smoothingIterations="5"`, `alphaani="0 0.06"`, `lineani="0 0.1"`; the only other use, `menuStatistics.xml`, has `alphaani="0 0.2"`, `lineani="0 0.5"`: the first value is 0 in both, so neither animation runs (§3.13) |
| `templates.xml` | `slider` (a `Slider2`) | `value="0.5"`, `mapping="184 88 130 18"`, throttle 10 × 16 at `pos="1 1"` |
| lobby dialogs | `EditEx` | `maxLength` 10, 16, 18, 19, 20 (the most frequent) and 320; `padding="6 6 6 6"`, `"12 4 28 4"`, `"12 5 12 4"`; `allowedChars` of digits only, of letters, digits and `-`, of letters, digits and `äöüÄÖÜß+-_` with or without `.`, and one e-mail set (letters, digits and ``.!#$%&'*+-/=?^_`{\|}~@``) |
| `menufreegame.xml` | `ComboBoxNew` | `template="MatchmakingCombobox"`, `size="3"`, `string0="!LOBBY_MATCHMAKING_STARTRESOURCES_HIGH"`, `string1="…_MEDIUM"`, `string2="…_LOW"`; `lobbySetupGameDialog.xml` has the same node as a `DropDownMenu` |
| fonts | `font=` attribute values, upper and lower case counted together | `Subline_Garamond` (131 uses), `Body_Arial` (111), `Head_Garamond` (40), `Chapter_Garamond` (35), `Mini_Silk` (19), `small_no_alias_white` (9), `light_system_outlined` (1) |
| text tables | markup | `<hcenter>` (4 times, `data\game\language\de\lobby_ui.txt`) |
| atlas `uiElements0` | numbered button styles | rectangles of §3.4 |

Constants in code: caret cycle 1000 ms (visible ≤ 500); selection alpha 0.33; caret colour 0xff0000ff; slider
margins 2 px; `Slider2` wheel step 0.1; `Slider` drag gain 0.75 and default speed 0.2; `Edit` caret pick slack
3 px; chat defaults (§3.14); grabber y limit 0.85; idle caption colour (229, 209, 196).

## 7. Save and load

Nothing of the toolkit is saved. Widget state is rebuilt from the layout XML and from game state on every
screen construction; the hot reload re-reads the XML ([ingame-ui.md](ingame-ui.md) §3.1.1). The grabber's last
drag position is a process global (S 0087c09c, four dwords): `Grabber::Update` S 004bebf0 is its only writer,
and its readers are `LobbyMenu::DialogBase::OnShow` S 00460f50 and `nMenu::Overlapped::OnShow` S 0062e750,
which pass it to `nUi::Dialog::Create` as the position of the dialog being shown. Nothing else references it,
so it is not written to disk [known: cross-references of S 0087c09c].

## 8. Determinism notes

Presentation only. The toolkit reads the wall-clock UI timer, the cursor and `rand()` (graph line flicker,
S 004c7f90) and writes only widget state, renderer state and the Windows clipboard. No function listed here
writes simulation state; commands reach the simulation from `nMenu` handlers
([game-commands.md](game-commands.md)). The `rand()` call draws from the C runtime generator, which is separate
from the simulation's generator ([logic-core.md](logic-core.md) §3.3) but is shared with the host's random
slot and team assignment, Lua `math.random` and the other callers listed in
[engine-core.md](engine-core.md) §3.7. The graph calls it while drawing and only when `lineani`'s first
value is not 0 [known] S 004c7f90; both shipped graphs set it to 0 (§6), so the shipped game never reaches the
call [inferred]. A remake should give the flicker its own presentation-side generator.

## 9. Notes for a Godot reimplementation

- **Coordinates**: keep the model "fractions of the viewport, pixel-born sizes rescaled per axis on a resolution
  change" or simply lay out in pixels at the chosen resolution; fonts and nine-slice corners stay in pixels.
- **Text**: `Label` with a `FontFile` imported from the `.fnt` (after the padding arithmetic of
  [formats-inventory.md](formats-inventory.md) §3.6). Reproduce: vertical centring on the text position, no
  kerning, charSpacing, truncation of positions, the −0.5 pixel offset, the ellipsis helpers. For wrapped
  `nUi::Text` use a custom line breaker (break after space, `.`, `!`; no forced line feed).
- **TextBlock**: a custom control or `RichTextLabel` fed by a converter of the tag grammar of §3.2 (alignment
  per line, colour `r g b a`, 4-character font keys); wrap only at spaces; truncate at the box height.
- **Shape**: `NinePatchRect` with the border sizes and `stretch` → axis stretch mode (stretch or tile);
  `flipped` = flip V; rotation about the centre; masked sprites need a shader.
- **Button**: `TextureButton`-like control with four atlas regions; implement press / click / double-click
  order exactly as §3.4 (click only if released over the widget; second press of a double click is a press plus
  a double-click event). Check box = toggle mode. Sounds by name.
- **EditEx**: `LineEdit` / `TextEdit` do not match the rules; write a control with: allowedChars filter,
  maxLength, password stars, signed selection, word select on double click, Ctrl+A/C/X/V (copy or cut of the
  whole line without a selection), caret blink 500 / 1000 ms, Enter passing through when single-line, Tab moving
  between sibling edits by z-order. Text is one byte per character in the original; a remake may accept Unicode
  but must keep the length and filter rules where the server checks them (account names, passwords:
  [../message-catalog.md](../message-catalog.md), 0x0CB SelfRegistration and 0x0CC AuthenticateUser).
- **Sliders**: `Slider2` → `HSlider` / `VSlider` with step 1 ÷ (snapCount − 1) plus the two step buttons and the
  double-click reset to 0.5; `SliderEx` → `ScrollBar` with integer range and the 2 px margins.
- **ListBox2** → `ScrollContainer` + `VBoxContainer` of toggle buttons with single selection; scrolling is by
  whole rows.
- **ComboBoxNew / DropDownMenu** → `OptionButton` / popup; keep "open upwards if it would leave the screen" and
  "any outside press closes".
- **TabControl** → `TabContainer` with cross-fade (`Tween`). **Animations** → `Tween` with the smoother-step
  curve; the scaler scales about the centre by changing rectangle size, not a transform.
- **ChatSystem** → a line-buffer control (256 lines, wrap on the break set, bottom-up draw, scroll-back anchor).
- A converter has to provide: layouts (XML as is), atlases and fonts, the text tables. A server provides nothing
  for this subsystem.

## 10. Open questions

| # | Question | Settled by |
|---|---|---|
| 1 | Answered (§3.4): yes, on every button whose owner handles clicks through `OnChildClicked` or an observer and never polls the latch. Example: the confirm and delete buttons of `nMenu::LoadSavePanel` (handler S 0060d430; its `Update` S 0060dd30 does not call the poll S 0049fdb0): after one click, a press on the button released outside it runs the click again. To see once: delete prompt answered No, then press Delete and release beside it | static: S 004aecf0, S 0049ff60, S 0049ff40, S 0049fdb0 (54 callers), S 0060d430 |
| 2 | Classes not read here: `Listbox`, `Item`, `ComboBox`, `StackedSlider`, `Scroller`, `TextScroller`, `AlphaFanPicture`, `Bar`, `Chart`, `Dialog`, `Video`, `OverlayButton` hover fade | static read from the function reference of each (names index, namespace `nUi`) |
| 3 | Who implements the inventory drag (ghost, drop) | cross-references to the `InventoryButton` observer lists |
| 4 | Whether the last partial tile of a tiled nine-slice is squeezed or cropped; caret colour as seen | observation in the running game |
| 5 | Stale glyph quad when a break candidate itself overflows a boxed line (§3.1) | observation in the running game with a narrow `wrapSize` |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 004a3920 | `nUi::Object::Update` | per-frame order |
| 004ab060 / 004ab130 / 004ab190 / 004ab1f0 | `nUi::Event::DispatchEvent` / `DispatchMouseDown` / `DispatchMouseUp` / double click | event fan-out |
| 004a0020 / 0049ff60 / 004a0070 | `Object::OnMouseButton0Down` / `Up` / double click | focus state, click latch |
| 004c1d50 | `nUi::Focus::SetState` | hover / pressed state |
| 00401f30 / 00407cf0 | `CApplicationEx::HandleWindowMessage` / `WinMain` | message → event; `TranslateMessage` rule |
| 004b3fe0 / 004b43c0 | `nUi::Text::SetText` / `Draw` | text widget |
| 004e2c60 / 004e3080 / 004e3270 / 004e2620 | `BitmapFont::BuildGlyphQuads` / `BuildTextScaled` / `BuildTextInBox` / `GetTextWidth` | glyph layout, wrapping |
| 004e4270 / 004e3fa0 / 004e3d20 | `RichTextLayout::SetText` / `ApplyTag` / `Render` | markup |
| 004aa310 / 004a8f70 / 004a88a0 | `UiSprite_RenderToOwnerRect` / `Shape::DrawSliced` / `DrawQuad` | sprite, nine-slice |
| 004af080 / 004afa10 / 004afd10 | `Button::UpdateMapping` / `LayoutCaption` / `Draw` | button look |
| 004aeca0 / 004aecf0 / 004b1270 / 004b12d0 / 004b1470 | `Button::OnMouseButton0Down` / `OnMouseButton0Up` / `OnMouseButton0DoubleClick` / `OnClicked` / `OnPressed` | button events |
| 004ce780 / 004ceaa0 | `Icon::Draw` / `UpdateShapeTexture` | icon |
| 004c07e0 / 004c0a40 | `nUi_TextInput_InsertChar` / `nUi_TextInput_HandleKey` | `Edit` buffer |
| 00497b60 / 00497f50 / 00498100 / 00498250 | `Edit::OnMouseButton0Down` / `Update` / `Draw` / `OnKeyDown` | `Edit` |
| 0049ebd0 / 0049f100 / 0049f530 | `EditEx::LoadFromXml` / `HandleChar` / `HandleKey` | `EditEx` rules |
| 0049b7b0 / 0049b9b0 / 0049bae0 / 0049a3a0 | `EditEx::OnMouseButton0Down` / `OnMouseButton0Up` / `OnDoubleClick` / `UpdateMouseSelection` | selection |
| 0049ad00 / 0049a750 / 0049a090 | `EditEx::Draw` / `DrawLine` / `Update` | caret, selection, password |
| 004994a0 / 0049a6d0 | `UiClipboard_SetText` / `UiClipboard_GetText` | clipboard |
| 004d0200 / 004d02f0 / 004d0790 | `Slider2::SetValue` / `Update` / `OnChildClicked` | slider |
| 004b92f0 / 004b9890 / 004b9a40 / 004b9bb0 | `SliderEx::SetValue` / `Update` / `UpdateThrottlePosition` / `UpdateThrottleRange` | scroll bar |
| 004b8880 / 004b8590 / 004b90d0 | `ListBox2::LayoutItems` / `Update` / `OnItemSelected` | list |
| 004b38b0 / 004b29c0 / 004cc180 / 004cb350 | `DropDownMenu::OnChildClicked` / `LayoutItems` / `ComboBoxNew::OnChildClicked` / `SetSelectedIndex` | drop-downs |
| 004b9f60 / 004ba120 | `TabControl::ApplyTabState` / `OnChildClicked` | tabs |
| 004c9410 / 004c7f90 | `Graph::SmoothPoints` / `Draw` | graph |
| 004ae670 / 004ae200 / 004adb20 / 004ac430 | `ChatSystem::Update` / `AddText` / `ChatLog::AddText` / `ChatLog::Draw` | chat |
| 004d1fc0 / 004d2020 | `Animation::Update` / `GetProgress` | animation base |
| 004d2220 / 00763510 / 004d24d0 / 00768e80 / 004d2b00 | `AnimationAlphaFade` / `AlphaPulse` / `Scaler` / `Mover` / `TransformFade` `::Update` | animation kinds |
| 004c3c30 / 004c3d50 / 004c3e90 / 004c39b0 | `nUi_FadeOutObject` / `nUi_FadeInObject` / `nUi_AttachScaleAnimation` / `nUi_AttachScaleInAnimation` | helpers |
| 004bebf0 / 004bea30 | `Grabber::Update` / `MoveParentTo` | window dragging |
| 004bdb10 / 004bdb60 / 004bdc10 | `InventoryButton` press / release / double click | slot events |
