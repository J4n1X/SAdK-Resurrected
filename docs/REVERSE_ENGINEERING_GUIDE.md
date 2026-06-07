# SAdK Asset Decoding & Modding Guide (Track A)

Reverse-engineering and modding the game data of **Die Siedler: Aufbruch der Kulturen**
(The Settlers: Rise of Cultures, Blue Byte / Ubisoft, 2008). This is the **asset /
KEX-file track** — for the online-lobby revival work see `AGENTS.md`.

The game stores its data in encrypted `.KEX` files. `AdKEd.exe` decrypts them into
readable XML / Lua / text, which can then be inspected and (re-encrypted) modded.

---

## File format & decryption

### KEX format
- **Status:** reverse-engineered and decryptable.
- **Origin:** custom encryption by Blue Byte / Ubisoft.
- **Tool:** `AdKEd.exe` — *AdK Editor* v1.11 Beta (Sept 2008) by **Rheini** (Xentax forum).
- **Source thread:** https://forum.xentax.com/viewtopic.php?f=21&t=3165

### Decryption process
`AdKEd.exe` can both decode `.KEX` → readable (XML/text) and encode back to `.KEX`
for modding. **It modifies files in place** — always work on copies.

- Single file: drag-drop onto `AdKEd.exe`, or `AdKEd File.xml` on the command line.
- A folder at once: drop files into `BatchConversion\` and run `BatchConv.bat`.
- The whole game tree: `decrypt_all.bat` / `decrypt_all.ps1` (recurse the game `data\`,
  preserve structure into `result\`). The source path is a `<PATH TO YOUR GAME>\data`
  placeholder at the top of those scripts — edit it per machine.

The bulk decrypt has been run: **`result\` holds ~1,639 files / ~116 MB** of decoded
assets under `game/` (animals, buildings, character, gfx, items, map, ships) and
`lobby/` (avatars, heightmap, objects, pets, sky).

---

## Game file structure

```
data/
├── game/
│   ├── animals/      # animal models & animations
│   ├── buildings/    # building models & definitions
│   ├── character/    # / humans — character models
│   ├── properties/   # game configuration + Lua (patterns.lua = key modding file)
│   ├── scripts/      # game logic & AI (Lua)
│   ├── gfx/ items/ map/ ships/
├── graphics/         # textures / visual assets
├── maps/             # map data (Freegamemaps/MP_2P_*.bin, not .s2m)
└── lobby/            # 3D lobby world assets (avatars, objects, pets, sky, …)
```

**File types:** `.KEX` (encrypted; decrypt first), `.XML` (data structures),
`.LUA` (logic/config/AI), mesh/model + texture assets, config/balance files.

**Notable:** decoded lobby XML still carries the original build path
(`D:\s2c\siedlerii008\development\app\client\data\...`), confirming the SAdK→S2-10th
("siedlerii") lineage.

---

## Modding workflow

1. Decrypt the target `.KEX` with `AdKEd.exe` (work on a copy).
2. Locate entries — text is searchable; names are usually `ref=` keys into a lang file,
   so search by **ID**, not display text.
3. Edit XML values or Lua tables.
4. Re-encrypt with `AdKEd.exe`.
5. Test in game. Keep backups of originals.

**Tools:** Notepad++ / VS Code (XML & Lua), grep/ripgrep (search the decoded tree),
Ghidra or IDA (binary/DLL analysis), Meld / Beyond Compare (diffing), Git (track edits).

---

## Asset-analysis checklist

Status: **decryption complete**, deeper data analysis largely **not started**. Suggested
order when mining `result\`:

1. **Inventory** — count files by type/dir, list extensions, flag largest files.
2. **Structure** — extract XML schemas (root elements, ID-ref systems) and Lua table
   shapes (config tables, event handlers, exports).
3. **Extract data** — catalogue buildings, units, resources, animals: IDs, costs,
   production rates, worker/efficiency, build times, upgrade paths, stats.
4. **Map relationships** — how IDs cross-reference (building→lang, building→model,
   production chains, prerequisites/unlocks).
5. **Document** — data dictionary + game-economy/mechanics notes; flag unknowns.

Useful searches over the decoded tree:
```
grep -r "<Building" result/game/        # building defs
grep -r "type=\""    result/game/        # resource references
grep -rn "function"  result/game/        # Lua scripts/events
grep -rn "ID="       result/game/        # ID references
```

---

## Community resources

| Resource | URL |
|----------|-----|
| Xentax (original format research) | https://forum.xentax.com/viewtopic.php?f=21&t=3165 |
| GOG forums (file decoder) | https://www.gog.com/forum/the_settlers_series/file_decoder_settlers_2_10th_anniversary_and_rise_of_cultures |
| ModDB (mods & tools) | https://www.moddb.com/games/the-settlers-rise-of-cultures |
| Siedler-Maps.de (German community) | https://www.siedler-maps.de |

**Known existing mods:** SAdK 2014 patch, English fan translation, widescreen/FOV mods,
map tools. **Known limits of public tooling:** map tools outdated (~2009), no naval/harbour
support, little official documentation, no source release.

---

## Confirmed vs open

**Confirmed:** KEX is decryptable with AdKEd; output is XML/text + Lua; ID-based
referencing with lang keys; hierarchical `data/` layout; active modding community.

**Open / to investigate:** exact XML schemas, full resource/unit/building catalogues,
animation-state definitions, save-game format. (Network/multiplayer protocol is the
separate Track B — already heavily reversed; see `LOBBY_PROTOCOL.md`.)

---

## Background

- German standalone built on the *Settlers II: 10th Anniversary* (DNG) engine.
- Decryption tool by **Rheini**; game by **Blue Byte Software / Ubisoft** (2008).
- Further reading: [awesome-game-file-format-reversing](https://github.com/VelocityRa/awesome-game-file-format-reversing),
  [Ghidra guide](https://www.retroreversing.com/ghidra).
