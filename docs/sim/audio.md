# Audio: sound effects, ambience and music

Specification of the sound side of `sadk_noav.exe`: the FMOD 3 wrapper (`ai::audio::SoundManager`), the game sound
system on top of it (`ai::sound::SoundSystem` with its five players), the sound definitions in `sounds.lua`, the
places in the renderer, the UI and the menu that start sounds, ambient emitters, the music playlist and the volume
settings. Tags: [known] = read at the address given (S 00xxxxxx) or in the named data file; [inferred] = one step
of reasoning from what is visible; [TODO] = open. Nothing here was observed in the running game.

Related documents, not repeated here: `properties-data.md` §2.9 (the `SoundProperty` record and the `sn_*` Lua
setters), `formats-inventory.md` §3.11 and §3.13 (`settings.cfg`, audio file types), `../map-format.md` (the
`Logic Ambients` section), `game-commands.md` §2.1 and §4 (the `nGame::System` frame update), `logic-core.md` §3.3
(the simulation random generator), `players-victory.md` (the `spotted` flags), `military.md` (fights).

## 1. Purpose and scope

The audio subsystem turns five kinds of requests into FMOD channels:

| Kind | Entry point | Player object | Typical content |
|---|---|---|---|
| positional one-shot or tracked effect | `SoundSystem::Play3D` S 0056a2f0 | `NSound::ActiveChannels` | steps, tools, doors, work loops, impacts |
| ambient emitter at a fixed place | `SoundEmitterManager::AddEmitter` S 0056d0e0 | `SoundEmitterManager` | terrain ambience, lobby ambience |
| UI sound | `SoundSystem::PlayUiSound` S 00569ee0 | `UiSoundPlayer` | clicks, messages, minigame and NPC sounds |
| music | `SoundSystem::PlayMusicGroup` S 0056a410, `SoundPlaylist` | `MusicPlayer` | menu themes, tribe tracks, battle loop |
| voice-over | `Menu_PlayVoiceOver` S 005db000 | `VoiceOverPlayer` | campaign book and cinematic speech |

It is presentation only. It reads simulation and renderer state (positions, the fight list, the players'
`spotted` flags, the game speed) and writes none of it (§8).

In scope: namespaces `ai::audio`, `ai::sound`, `NSound`, the `Sound_*` and `GameMusic_*` functions, `nGame::Sound`,
`S2CG::SoundEvent`, the audio calls of `nMenu::System` and the lobby's use of the same system. Out of scope: the
FMOD library itself (`fmod.dll`, FMOD 3 API, 29 imports), video sound tracks (`menu.setVideoVoiceStream`
S 005dd6c0 only stores its integer argument under the video name in the map at `nMenu::System + 0xa8` [known]).

## 2. Data model

Coordinates: world space as used by the renderer, **y is up**; ambient emitters placed from map cells have
`y = 0` [known] S 0078c320. Volumes handed to FMOD are integers `0..255`. Sound ids are the 32-bit values of the
hexadecimal strings given to `properties.sn_create` (`sounds.lua`: `sound_steps = sn_create("80d14ee3")`; the code
plays `0x80d14ee3` for steps) [known] S 006904f0.

### 2.1 `ai::properties::SoundProperty` (0x5c): the definition of one sound

Layout and Lua setters are in `properties-data.md` §2.9. What the audio code does with each field [known]:

| Offset | Field | Use |
|---|---|---|
| +0x00 | `id` | key of the group map (§2.3) |
| +0x04 | `name` | looked up by `PropertiesDb::FindSoundIdByName` S 00545f70 for sounds named in XML and for UI sounds |
| +0x20 | `fileNames` (vector of strings, element 0x1c) | one FMOD entry per file; several files = random variants |
| +0x30 | `looping` (bool, `sn_setLooping`) | three effects: loop mode at load (§3.1); exempts the sound from the game-speed cut-off of `Play3D` (§3.3); makes the sound stop when its source object goes away (§3.3) |
| +0x34 | `type` (i32) | 0 Ambient, 1 Music, 2 GUI, 3 Sound. Music is loaded as a stream, all others as samples. The type is also the **index of the category volume** (§2.3) |
| +0x38 | `volume` (i32, 0..255) | base volume of every channel playing this sound |
| +0x3c | `priority` (i32) | FMOD sample priority (non-music); UI pre-emption rule (§3.5) |
| +0x40 | `minDistance3D` (f32) | FMOD 3D minimum distance (3D sounds only) |
| +0x44 | `maxDistance3D` (f32) | FMOD 3D maximum distance; default 1e9; `sounds.lua` never sets it |
| +0x48 | `is3D` (bool) | FMOD mode `FSOUND_HW3D` (true) or `FSOUND_2D` (false) at load |
| +0x4c | `distance2D` (f32) | radius `r` of the emitter volume formula (§3.4) |
| +0x50 | `musicTribe` (tribe id, -1) | playlist group key (§3.6) |
| +0x54 | `percussion` (bool) | playlist map B instead of map A (§3.6) |
| +0x58 | `maxDistanceSq` (f32) | audibility cut-off of `Play3D`: `(minDistance3D * 30)²`, written by `Set3DMinDistance` S 00555a40; the constructor leaves 1.0 (S 00555a80), so a sound without `sn_set3DMinDistance` is audible only within 1 world unit of the listener. The cut-off does not look at `is3D` |

### 2.2 `ai::audio::SoundManager` (0x64): the FMOD wrapper

Singleton `g_pSoundManager` (S 0088b820), created by `Audio::SoundManager::CreateInstance` S 005c71e0, constructor
S 005c7150 [known].

| Offset | Field | Type | Meaning |
|---|---|---|---|
| +0x00 | `output` | i32 | FMOD output type; constructor value 2 (DirectSound) |
| +0x04 | `mixRate` | i32 | 44100 |
| +0x08 | `maxChannels` | i32 | 32 software channels; FMOD frees a channel the moment its sound ends, so no player stops a one-shot's channel (§3.5) |
| +0x10/14/18 | `entries` | vector of `SoundEntry*` | every loaded sound file; the index is the **sound id** used by all players |
| +0x1c/20/24 | `tracks` | count, capacity, array of `{i32 channel, void* source}` | channels whose 3D position is polled each frame |
| +0x28 | `listenerProvider` | interface pointer | slot 0 returns position, velocity, forward, up |
| +0x30/34/38 | `listenerPos` | f32 × 3 | last listener position; read by `Play3D` and the emitter manager |
| +0x40/44/48 | `streams` | vector of `{handle, channel}` | open streams, closed when their channel is stopped |
| +0x50/54/58 | `samples` | vector of `{handle, channel}` | one-shot samples loaded for one play (voice-over), freed when stopped |
| +0x5c | `muted` | bool | window inactive or minimised |
| +0x60 | `savedSfxVolume` | i32 | last master volume set (`SetSfxMasterVolume` S 005c6770) or read at mute; restored on unmute |

`SoundEntry` (0x34) [known] S 005c7250: +0x00 valid byte, +0x04 path string (as given, before path resolution),
+0x20 `type` (0 sample, 1 stream), +0x24 `mode3d` (0 = 2D, 1 = 3D), +0x28 `durationSec` (f32; streams only, from
`FSOUND_Stream_GetLengthMs / 1000.0`), +0x2c FMOD sample handle (samples only), +0x30 `loopMode` (0, 1, 2; §3.1).

### 2.3 `ai::sound::SoundSystem` (0xe0): the game sound system

Singleton `g_pSoundSystem` (S 0088a2fc), `Sound_CreateSystemInstance` S 0056ae10, constructor S 0056ac60 [known].

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | `enabled` (bool) | set by `Sound_Init` only if FMOD initialised; the play, stop, pause and volume entry points return at once while false (`SetDucking` S 0056a0b0 does not test it) |
| +0x04 | `groups`: `map<i32 soundPropId, vector<i32 soundId>>` | the variants of each sound property |
| +0x10 | `activeChannels` → `NSound::ActiveChannels` (0x18) | effects started by `Play3D` |
| +0x14 | `emitters`: `SoundEmitterManager` (0x2c) | ambient emitters |
| +0x40 | `uiPlayer`: `UiSoundPlayer` | +0 owner, +4 enabled byte, +8 vector of FMOD channels |
| +0x58 | `music`: `MusicPlayer` | +0 owner, +4 `currentSoundId` (-1 = none), +8 `map<i32 channel, MusicChannel>` |
| +0x6c | `playlist`: `SoundPlaylist` (0x34) | §2.5 |
| +0xa0 | `voice`: `VoiceOverPlayer` (0x2c) | +0 owner, +4 pending path (string), +0x20 `startDelay` f32, +0x24 `paused` bool, +0x28 channel (-1 = idle) |
| +0xcc | `categoryVolume[0]` | Ambient (emitters); f32 0..1; default 1.0 |
| +0xd0 | `categoryVolume[1]` | Music; default **0.3** |
| +0xd4 | `categoryVolume[2]` | GUI and voice-over; default 1.0 |
| +0xd8 | `categoryVolume[3]` | Sound (effects); default 1.0 |
| +0xdc | `ducked` (bool) | set during cinematics; quarters effects, emitters and music (§3.7) |

Defaults: `Sound_ResetVolumesToDefaults` S 0056a110 [known]. The category array is indexed with
`SoundProperty.type` in `SoundChannelEntry_ApplyVolume` S 0056d8d0 (`FLD [sys + type*4 + 0xcc]`) [known].

### 2.4 Channel records

`NSound::ActiveChannels` (0x18, vftable S 007e9984) [known] S 0056dd70: +0 vftable (slot 0 =
`GetChannelPositionAndVelocity` S 0056dca0), +4 owner, +8 flag byte (set by `Sound_Init`), +0xc count, +0x10
capacity, +0x14 array of 16-byte entries:

| Offset | Field | Meaning |
|---|---|---|
| +0x0 | `source` | object that emits the sound (an `NSound::ICallback` face: slot 0 returns position and velocity), or null for a fixed position |
| +0x4 | `channel` | FMOD channel |
| +0x8 | `soundId` | the **sound property id** passed to `Play3D` (used to stop "this sound of this source") |
| +0xc | `soundProperty` | cached `SoundProperty*` |

`SoundEmitterManager` (0x2c) [known] S 0056d010: +0 owner, +4 emitter map, +0x10 channel map, +0x1c
`map<i32 soundId, i32 channel>`, +0x28 `paused` byte.

- Emitter record (map key = `emitterKey`, a process-wide counter `g_SoundEmitterNextKey`): `{i32 emitterKey,
  SoundProperty* prop, f32 pos[3], i32 soundId (the variant chosen), i32 channel (-1 = silent)}` [known]
  S 0056d0e0.
- Channel record (map key = FMOD channel): `{i32 channel, i32 emitterKey, bool keep, f32 targetVolume,
  f32 currentVolume}` [known] S 0056d2e0 (stores at `0056d81b..0056d839`).

`MusicChannel` (map key = FMOD channel): `{i32 channel, i32 soundId, f32 targetVolume, f32 currentVolume}` [known]
S 0056f480. `ai::sound::RampedFloat` is the `{target, current}` pair of both records.

### 2.5 `ai::audio::SoundPlaylist` (0x34) and `GameMusicState` (0x14)

`SoundPlaylist` [known] S 0056eb30, S 0056e190:

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | `owner` | the `SoundSystem` |
| +0x04 | enabled byte | set by `Sound_Init`; not read by `Update` |
| +0x08 | `elapsed` f32 | seconds since start-up, advanced by every `Update` |
| +0x0c | `nextStartTime` f32 | `elapsed` value at which the next track is picked |
| +0x10 | `pickNewGroup` bool | true: next pick comes from map A; false: from map B |
| +0x14 | `currentGroup` i32 | key (tribe id) of the last pick from map A; -1 |
| +0x18 | map A: `map<i32 tribe, vector<i32 soundPropId>>` | melody tracks (`percussion == false`) |
| +0x24 | map B: same type | percussion tracks (`percussion == true`) |
| +0x30 | `forcedGroup` i32 | sound property id forced over the playlist; -1 = playlist runs |

`GameMusicState` (`nGame::System + 0x61c`) [known] S 0078c2b0: +0 `initialized` byte, +1 `tribeTracksAdded[8]`
(one byte per player index), +0xc `battleMusicUntil` f32 (simulation seconds), +0x10 `battleMusicActive` byte.

`nMenu::System`: +0x84 `currentMusicIndex` (-1 = none), +0x88 `musicSoundIds[7]` (offsets [inferred] from the
struct typing; the seven values [known] S 005dda30, written only when `Initialize` is called with its second
flag set):

| Index | Sound property id | `sounds.lua` name | File |
|---|---|---|---|
| 0 | 0x88795c63 | `music_main` | `maintheme.ogg` |
| 1 | 0xda79b9c3 | `music_briefing` | `Briefing.ogg` |
| 2 | 0x6b9cd9c3 | `music_won` | `Jingle_Success.ogg` |
| 3 | 0x75274083 | `music_lost` | `Jingle_Failure.ogg` |
| 4 | 0xafac25d3 | `music_credits` | `Credits.ogg` |
| 5 | 0x38965d63 | `music_lobbyOutside` | `Lobby_Outside_01.ogg` |
| 6 | 0x07b36453 | `music_lobbyInside` | `Lobby_Inside_01.ogg` |

### 2.6 `S2CG::SoundEvent` (0x28): a timed sound on an animation

Created by `EventCreator<SoundEvent>::Create` S 00685970 from a descriptor [known]. The creator (0x30, descriptor
embedded at +4) is built per `<Sound>` element by `LoadAnimEvents` S 006867d0, which zeroes `start` and `duration`
before the loaders run. Descriptor (`SoundEvent::Desc`, loaders S 00685b30 and S 006b0920): +0x04 `start` f32
(seconds, XML `start`, 0 when absent), +0x08 `duration` f32 (XML `duration`, 0 when absent), +0x0c `slot` string
(XML `slot`; when not empty the constructor S 006b0350 resolves it with `CAnimatedObject::GetBoneIndex` on the
model the event is attached to), +0x28 sound property id (XML `name` resolved by `FindSoundIdByName`, -1 when no
sound has that name). The event object
carries an `NSound::ICallback` face at +0x24 whose slot 0 (S 006b0500) returns the translation of the event's
world transform as position and the constant vector at S 0088f1b0 as velocity [known].

## 3. Rules and algorithms

### 3.1 Start-up and loading

`Sound_Init` S 0056b310, called once from `CApplicationEx::Initialize` S 004075d0 [known]:

1. Create the `SoundManager`; `FSOUND_SetOutput(2)`, `FSOUND_Init(44100, 32, 0)`. If either fails, retry with
   output 0 (no sound). If that fails too the system stays disabled for the whole run (S 005c65e0).
2. `Sound_LoadSoundsFromProperties` S 0056b190: for every sound property, in id order, and for every file name:
   - `type = (prop.type == 1)` → 1 stream, else 0 sample;
   - `loopMode = prop.looping ? (prop.type == 1 ? 1 : 0) : 2`;
   - `mode3d = prop.is3D`;
   - `soundId = SoundManager::LoadSound(path, type, mode3d, loopMode)`; append `soundId` to `groups[prop.id]`;
   - if `mode3d == 1`: `FSOUND_Sample_SetMinMaxDistance(sample, minDistance3D, maxDistance3D)`;
   - if `type == 0`: `FSOUND_Sample_SetDefaults(sample, -1, -1, -1, priority)`.
3. Enable the UI player and the playlist, `FSOUND_3D_SetRolloffFactor(4.0)`, enable the active channel list,
   reset the volumes to defaults (§2.3), `ducked = false`, `enabled = true`.

`SoundManager::LoadSound` S 005c7250 [known]:

- An entry with the same path string, type and `mode3d` is reused (`FindEntry` S 005c6d00); its index is returned.
- FMOD mode bits: `mode3d` 0 → `0x2000` (`FSOUND_2D`), 1 → `0x1000` (`FSOUND_HW3D`); `loopMode` 0 → `0x2`
  (`FSOUND_LOOP_NORMAL`), 1 → `0x4` (`FSOUND_LOOP_BIDI`), 2 → `0x1` (`FSOUND_LOOP_OFF`).
- The path goes through `FileScanHolder::ResolvePath` S 006e3fd0 (`../data-loading.md`) [known]: a file path
  without a `:` is handed to `FileScan::ResolvePath` S 006ef8a0, which turns `/` into `\`, lower-cases the
  string, takes the part after the last `\` and looks that file name up in the index built by the start-up scan
  of `data\game` and `data\lobby`; a name that is not indexed yields an empty path. The directory written in
  `sounds.lua` therefore only matters when several indexed files share the name (the candidate whose parent
  directory occurs in the request is taken [inferred from the callee `ai::file::FileScan::PickCandidateByParentDir`]), and
  the bare names of the lobby records (`"shake0.wav"`) resolve the same way as the `[data]\sound\...` ones.
- Sample: `FSOUND_Sample_Load(FSOUND_FREE, path, mode, 0, 0)`; the whole file is decoded into memory at start-up.
- Stream: `FSOUND_Stream_Open(path, mode, 0, 0)` only to read the length, then closed. Each later play opens the
  stream again (`Audio_OpenEntryStream` S 005c6c10) and closes it when its channel is stopped.
- A file that fails to load yields id -1, which is still appended to the group [known]; playing such a variant
  is an out-of-range vector access guarded only by the checked-iterator handler [inferred].

Consequence of step 2 [known]: looping music gets `FSOUND_LOOP_BIDI`, looping effects and ambients
`FSOUND_LOOP_NORMAL`, everything else no loop. On the Ogg music streams the bidirectional flag acts as a plain
forward loop: `maintheme.ogg` restarts cleanly at its end [live, maintainer, 2026-10-14].

Variants: `SoundSystem::PickRandomVariant` S 0056a2a0 returns `groups[id][rand() % count]` with the C runtime
`rand()` (`Stl_VectorInt_PickRandom` S 0056f880) [known]. No "not the same twice" rule.

Starting an entry, `SoundManager::PlayEntry` S 005c7550 [known]: sample → `FSOUND_PlaySoundEx(FSOUND_FREE,
sample, NULL, startpaused = 1)`; stream → open, `FSOUND_Stream_PlayEx(FSOUND_FREE, stream, NULL, startpaused = 1)`,
remember `{stream, channel}`; a stream that gets no channel is closed again. Returns the channel or -1. Every
channel therefore starts paused; the caller sets volume and position and then calls
`FSOUND_SetPaused(channel, false)` (`Sound_SetPaused` S 005c6690). Which channel `FSOUND_FREE` takes when all 32 play is decided inside
`fmod.dll`, which is not in the Ghidra project [TODO: import `fmod.dll` and read `FSOUND_PlaySoundEx`'s channel
search]. The game feeds that choice: every sound that is not of type 1 gets its `sn_setPriority` value as the
sample's default priority (`SoundManager::SetEntryPriority` S 005c6820, from `Sound_LoadSoundsFromProperties`
S 0056b190), and channels are marked reserved (`Sound_SetReserved` S 005c6710, from the emitter manager, its
channel stop and the voice-over) [known].

### 3.2 Listener

`SoundManager::Update` S 005c68b0 asks `listenerProvider` once per frame for position, velocity, forward and up,
stores the position at +0x30 and calls `FSOUND_3D_Listener_SetAttributes` [known]. With no provider the listener
is left where it was. Providers [known], the writers of +0x28:

- in a match: the `I3DSoundListener` face of `S2CG::Scene` (`Scene::Init` S 006824c0 sets it, `Scene::Shutdown`
  S 006803f0 clears it), slot 0 = `Scene::GetListenerTransform` S 00681c10;
- in the lobby world: `Lobby::CLobbySoundListener`, set and cleared by `CLobby::ProcessModeTransition`
  S 004f5950; slot 0 (S 004f56c0) returns its stored position and forward vector, up `(0, 1, 0)`.

`Scene::GetListenerTransform` [known] S 00681c10 (disassembly): `eye` and `target` are the results of slots 2 and
3 of the camera object at graphics device +0x1b4. In a match that object is the `nGame::Camera` (vftable
S 00835294) [known: live 2026-10-12; `MapCamera::GetEye` S 0067fae0 and `GetTarget` S 0067fb00 were not called
in 4,500 frames]: slot 2 is `GetEyePos` S 00784f70 (the eye, `+0x64`) and slot 3 `GetLookAtPos` S 00784f90
(eye + look direction `+0x70`) [known], so `d` is the look direction, of length 1. With `d = target − eye`
and `h` = the terrain height sampled at the eye's x and z (`TerrainGrid::SampleHeightAndNormal` S 00687e60):

```
inv      = |d|² > 0 ? 1 / |d|² : 0
listener = eye + d * inv * (eye.y − h) * 0.8          // 0.8 at S 007e7ad8
forward  = normalize(d)
axis     = dot(forward, (0, 1, 0)) == 0 ? (0, 0, 1) : (0, 1, 0)
up       = normalize(axis − forward * dot(forward, axis))
```

Velocity is the constant vector at S 0088f1b0 (zero in the image), so there is no Doppler shift. The unusual
choice of world Z exactly when the view is horizontal is as coded.

The listener is thus moved from the eye along the view line by `0.8 * (eye.y − h) / |d|` world units. In a
match `|d|` is 1, so the listener sits `0.8 * (eye.y − h)` units down the view line: 80 % of the eye's height
above the terrain, measured along the look direction, not at the camera eye [known: S 00784f90; live
2026-10-12 for the camera object].

### 3.3 Positional effects: `SoundSystem::Play3D(soundPropId, pos, source)` S 0056a2f0

1. Skip if the system is disabled.
2. Skip if the game speed (`UserProfile + 0x24`) is above **3.0** and `prop.looping` is false.
3. Skip unless `|listenerPos − pos|² < prop.maxDistanceSq`, i.e. the listener is closer than `30 * minDistance3D`
   (all three axes). The test is made once, when the sound starts.
4. `soundId = PickRandomVariant(soundPropId)`, `channel = PlayEntry(soundId)`; give up if -1.
5. Append `{source, channel, soundPropId, prop}` to `ActiveChannels` (grows by 1.5×).
6. `source == null`: `FSOUND_3D_SetAttributes(channel, pos, velocity S 0088f1b0)` once. Otherwise register the
   channel for tracking (`SoundManager::Set3DTracking` S 005c6b30): it appends the pair, asks the source at once
   (`ActiveChannels::GetChannelPositionAndVelocity` S 0056dca0, vtable S 007e9984 slot 0) and sets the attributes,
   so a tracked sound starts at its source's position; from then on the manager polls the source each frame
   [known].
7. Volume: `FSOUND_SetVolume(channel, trunc(prop.volume * v))` with `v = categoryVolume[prop.type]`, and
   `v *= 0.25` if `prop.type == 3` and `ducked` (S 0056d8d0; 0.25 at S 007e5df8).
8. Unpause.

All [known]. Distance attenuation and panning of 3D sounds are FMOD's: minimum distance `minDistance3D`, maximum
1e9, roll-off factor 4.0. In FMOD 3 the gain beyond the minimum distance follows the inverse-distance model
`min / (min + rolloff * (d − min))` [inferred from the FMOD 3 documentation, not from this binary]. A sound with
`is3D == false` (e.g. the UI and minigame sounds played through `Play3D` by the lobby) plays at its set volume
without attenuation [inferred from `FSOUND_2D`]. The steps 2 and 3 apply to such sounds as well [known]: a 2D
sound played through `Play3D` still needs a position within `30 * minDistance3D` of the listener (1 world unit
when the record sets no minimum distance).

Lifetime [known]:

- `ActiveChannels::Update` S 0056d9b0, each frame: a channel FMOD no longer reports playing is stopped and its
  entry removed (swap with last).
- `SoundSystem::StopSourceSound(soundPropId, source)` S 00569f10 stops the first entry with that source and sound
  property (used when a timed `SoundEvent` ends).
- `SoundSystem::RemoveSource(source)` S 00569f60, called from the destructors of sound-emitting objects
  (`SoundEvent`, `EffectMovieElement` and its `Stop`, `CharacterSettler`, `TreeInstance`, the effect list clear):
  entries of that source whose sound is `looping` are stopped and removed; non-looping ones keep playing to their
  end at their last position, detached from the source (S 0056dad0).
- `SoundManager::StopChannel` S 005c6fc0: `FSOUND_StopSound`, close the stream or free the one-shot sample bound
  to the channel, drop the tracking entry.

### 3.4 Ambient emitters: `SoundEmitterManager`

`AddEmitter(soundPropId, pos)` S 0056d0e0 stores an emitter record with a random variant and no channel.
`RemoveEmitter(soundPropId, pos)` S 0056d270 finds the emitter with that property whose position is within
squared distance 0.1 on all three axes (`FindEmitter` S 0056b760), stops its channel if it has one and erases it
[known]. There is no branch for "not found": the end iterator is dereferenced and erased behind the checked-iterator
handler only, so callers must remove only what they added.

`SoundEmitterManager::Update(dt)` S 0056d2e0, each frame [known]:

1. **Nearest list.** Offer every emitter to a list of at most **4** entries `{emitterKey, distSq, soundId}`,
   sorted by ascending squared **horizontal** (x, z) distance to the listener (`Sound_NearestEmitters_Offer`
   S 0056fda0). At most one entry per `soundId`: an emitter replaces the entry of the same sound only if it is
   strictly closer. A candidate that would be fifth is rejected.
2. Clear the `keep` flag of every channel record.
3. **Claim.** For each nearest entry whose `soundId` already has a channel (`soundId → channel` map):
   - if that channel belongs to this emitter: `keep = true`;
   - otherwise the channel changes owner: the previous owner gets `channel = -1` and a new random variant, this
     emitter gets the channel, the channel record gets this `emitterKey` and `keep = true`. The sound keeps
     playing without a restart; only the position used for its volume changes.
4. **Fade out.** For each channel record with `keep == false`: update its volume (below) with the listener
   position replaced by `(-FLT_MAX, -FLT_MAX, -FLT_MAX)`; if afterwards `trunc(currentVolume) == 0` and
   `trunc(targetVolume) == 0`, stop the channel (`FSOUND_SetReserved(channel, false)`, `StopChannel`, erase the
   record and the `soundId → channel` entry); otherwise set `keep = true`.
5. **Start.** The channel-record count is read once, before this loop. For each nearest entry: if its sound has a
   channel, update that channel's volume with the real listener position; else if that count `!= 4`:
   `channel = PlayEntry(emitter.soundId)`; on success create the channel record
   `{channel, emitterKey, keep = false, 0, 0}`, map `soundId → channel`, update the volume,
   `FSOUND_SetReserved(channel, true)`, `FSOUND_SetPaused(channel, manager.paused)`. The count is not updated as
   channels start, so with fewer than four records every nearest entry without a channel starts in the same frame
   (two or more new channels at once), and with four records (fading ones included) none starts: a nearby new
   sound waits until a fading channel is freed [known, S 0056d2e0].

Volume of one emitter channel, `UpdateChannelVolume(record, listenerPos, dt)` S 0056bab0 [known]; `e` = owning
emitter, `r = e.prop.distance2D`:

```
dXZ    = sqrt((L.x − e.x)² + (L.z − e.z)²)
near   = min(1, (2r − dXZ) / r)            // 1 inside radius r, 0 at 2r, negative beyond (no lower clamp)
height = max(0, 1 − |L.y − e.y| / 80)      // 80.0 at S 007e9978
record.targetVolume = (float) trunc(near * height * e.prop.volume)
ramp record.currentVolume towards targetVolume at 255 units per second   // S 0056f8f0, 255.0 at S 007deef4
v = categoryVolume[0]; if ducked: v *= 0.25
FSOUND_SetVolume(channel, trunc(trunc(record.currentVolume) * v))
```

`RampedFloat::RampTowardTarget(rate, dt)` S 0056f8f0 [known]: `delta = target − current`; if `|delta| < rate * dt`
then `current = target`; else `current += rate * dt * sign(delta)`.

So an emitter is at full volume within `distance2D` of the listener (horizontally), fades linearly to silence at
twice that distance, and fades with camera height over 80 units. With `distance2D = 50` and the listener far above
the ground the height term dominates. Up to four different ambient sounds play at once, each from its nearest
emitter, and each fades in over at most one second; the fade-out is below.

**Outcome of step 4** [known, disassembly of S 0056bab0 and S 0056d5f4..0056d64f]. With the listener at
`-FLT_MAX` (S 007e51c0) the three differences are `-FLT_MAX` as f32; `dx² + dz²` becomes `+inf` when it is
stored as f32 before `_CIsqrt`, so `near = −inf` (the minimum with 1 keeps it); `height` is the maximum of 0
and a large negative number, 0; `−inf × 0` is a NaN (floating-point exceptions are masked, S 0057b9b0). The
conversion `__ftol2_sse` S 006f2af0 then decides:

- with the runtime's SSE2 flag `[00898044]` set it is `CVTTSD2SI`, which returns `0x80000000` for a NaN:
  `targetVolume = −2147483648.0`. `trunc(targetVolume)` is never 0, so `StopChannel` is not called: the record
  stays, `currentVolume` falls by 255 per second without a bound, and the channel keeps one of the four
  places. A sound that is claimed again ramps up from that value (silent for about as long as it was
  unclaimed); with four records the start test of step 5 fails and a sound without a channel cannot start;
- with the flag clear the fallback (S 006f2b26, `FISTP qword`) yields a low dword of 0 for a NaN:
  `targetVolume = 0`, the volume ramps to 0 within a second and the channel is freed.

The fade-out is entered only by a channel whose sound id is not among the four nearest distinct ids; the
nearest list has no distance limit (S 0056fda0), so with at most four distinct ids on the map every sound
keeps its channel and step 4 never runs. Besides step 4 only `RemoveEmitter` S 0056d270 of the owning emitter
frees a channel (S 0056d180 has these two callers). `[00898044]` is the runtime's SSE2 flag [known]: its one
writer S 007110d8 stores the result of S 00711078, which is 1 when CPUID leaf 1 reports EDX bit 26 and the
system test S 00711028 succeeds. Not read: what FMOD does with a negative volume.

### 3.5 UI sounds: `UiSoundPlayer`

`UiSoundPlayer::Play(soundPropId)` S 0056f700 [known]:

1. For each channel in the player's list whose FMOD play position (`FSOUND_GetCurrentPosition`) is still 0
   (started and not yet mixed; in practice started in the same frame [inferred]; the position is FMOD's, decided
   inside fmod.dll, so only a running game settles it) and that maps back to a sample
   entry: if that channel's sound has
   `priority >= ` the new sound's priority, **return without playing**; otherwise stop that channel and remove
   it from the list.
2. `channel = PlayEntry(PickRandomVariant(soundPropId))`; on success append it to the list,
   `FSOUND_SetVolume(channel, trunc(prop.volume * categoryVolume[2]))`, set the channel loop mode to off
   (`Sound_SetChannelLoopMode(channel, 2)` S 005c66b0 → `FSOUND_SetLoopMode(channel, 1)` = `FSOUND_LOOP_OFF`),
   unpause. A UI sound therefore never loops, whatever its record says.

So of several UI sounds requested in one frame only the one with the highest priority is heard, and of equal
priorities the first. Example priorities in `sounds.lua`: clicks 100, `uiMessage0` 200.

`UiSoundPlayer::PruneChannels` S 0056f550, each frame: entries whose channel has ended are dropped from the list;
a playing channel stays listed only while its sound property has `type == 2` [known]. Channels are mapped back
to their entry through `FSOUND_GetCurrentSample` (`SoundManager::FindSampleEntryByChannel` S 005c6a00), which
finds sample entries only. For a listed channel that is playing but maps to no sample entry (a stream, i.e. a
`type == 1` record played as UI sound) the loop jumps back without advancing (`JZ` at S 0056f5de) and so spins
until FMOD stops reporting the channel as playing [known]; in step 1 of `Play` such a channel is skipped.

The interface player never stops a channel whose sound has ended: `PruneChannels` only drops it from its list, and
FMOD has already freed it [known: S 0056f550, `Sound_IsChannelPlaying`]. A reimplementation whose mixer keeps a
channel until it is stopped must free ended channels itself; otherwise about 32 clicks exhaust the 32 channels and
every later sound, the music rotation included, is refused.

UI sounds are addressed by name: `UiResourceManager::RegisterSound(name)` S 00494080 finds the sound property whose
`name` equals the string (its own scan of the sound table, first match in id order) and caches its id;
`PlaySoundByName` S 00494180 looks the name up in that cache and calls `PlayUiSound` [known]. Names registered at menu
start-up (S 005dda30): `uiClick0`, `uiClick1`, `uiCancel`, `uiMessage0`, `uiMessage1`, `uiDialog0`, `uiKey0`,
`uiRemove` [known]. A name without a matching property is cached as id -1 [known].

### 3.6 Music

**`MusicPlayer`** [known]:

- `Play(soundId)` S 0056f480: if a channel already plays `soundId`, it becomes current again (no restart).
  Otherwise `PlayEntry`, register `{channel, soundId, target 0, current 0}`, `FSOUND_SetVolume(channel, 0)`,
  unpause, `currentSoundId = soundId`.
- `Update(dt)` S 0056f1f0, for every channel: `UpdateChannelVolume`; then if `trunc(current) == 0` and
  `trunc(target) == 0`, or FMOD reports the channel ended: stop it and erase the record.
- `UpdateChannelVolume` S 0056ec40: `target = prop.volume` if `soundId == currentSoundId` (integer-divided by 4
  when `ducked`), else 0; ramp `current` towards `target` at **256 units per second** (S 007df10c);
  `FSOUND_SetVolume(channel, trunc(trunc(current) * categoryVolume[1]))`.
- `SoundSystem::StopMusic` S 00569f50: `currentSoundId = -1`; every channel then fades out and is removed.

Every change of track is therefore a cross-fade: the new track rises from 0 and all others fall, each within one
second for a volume of 255. A newly started track is silent for its first frame.

**Direct play**: `SoundSystem::PlayMusicGroup(soundPropId)` S 0056a410 picks a random variant of the property and
calls `MusicPlayer::Play`; `SoundSystem::PlayMusic(soundId)` S 00569f40 does the same for an already chosen
variant and is what the playlist uses [known].

**Playlist**, `SoundPlaylist::Update(dt)` S 0056e190, each frame [known]:

1. `elapsed += dt`. Stop here if `forcedGroup != -1` or `elapsed <= nextStartTime`.
2. If `pickNewGroup`: if map A is empty, nothing happens. Otherwise pick the group at index
   `rand() % groupCount` (map order = ascending tribe id), in it the sound property at `rand() % count`, a random
   variant of that property (`PickRandomVariant`), `SoundSystem::PlayMusic(variant)`,
   `nextStartTime = elapsed + duration(variant) − 2.0`, `currentGroup = group key`, `pickNewGroup = false`.
3. Else: look for the group with key `currentGroup` in map B; if present, pick and play from it the same way and
   set `nextStartTime`; in both cases `pickNewGroup = true`.

The result is an endless alternation "melody track of a random tribe, then a percussion track of the same tribe",
each next track starting 2 seconds before the current one ends, cross-faded by the music player. Tribe tracks are
not looping (their records in `sounds.lua` have no `sn_setLooping`), so they end by themselves. While map A is
empty nothing is picked, and a tribe without an entry in map B simply gets no percussion turn.

- `SoundPlaylist::AddTrack(soundPropId)` S 0056ebf0 appends the id to `mapB[musicTribe]` if `percussion`, else to
  `mapA[musicTribe]`. Adding the same tribe twice duplicates its entries [inferred]; the caller guards per
  player index, not per tribe (§7).
- `SetForcedGroup(id)` S 0056e150: if `forcedGroup != id`: store it and `PlayMusicGroup(id)`.
- Release, S 0056e170: if `forcedGroup != -1`: `forcedGroup = -1`, `nextStartTime = elapsed`; the playlist picks
  its next track on the next update and the forced track fades out.
- `SoundPlaylist_Reset` S 0056e680: clear both maps, `nextStartTime = elapsed`, `pickNewGroup = true`,
  `currentGroup = -1`, `forcedGroup = -1`, `StopMusic`.

**In a match**, `GameMusicState` [known]:

- `GameMusic_Init` S 0078c2b0 (end of `nGame::System::BuildWorld` S 00784d40, skipped when the menu system's
  `uiSuppressed` flag is set): if a local player exists, add the
  tracks of its tribe and mark its player index; `battleMusicUntil = 0`, `battleMusicActive = false`; run one
  `GameMusic_Update`.
- `GameMusic_AddTribeTracks(tribe)` S 0078c180: `AddTrack` for every sound property with `type == 1` and
  `musicTribe == tribe`.
- `GameMusic_Update` S 0078c220, each frame from `nGame::System::Update` S 00780d20 (only while the tick counter
  is not -1 and the UI is not suppressed): for each player index `i` in `0..7` with `localPlayer.spotted[i]` set
  and `tribeTracksAdded[i]` clear, add the tracks of player `i`'s tribe and set the flag; then
  `UpdateBattleMusic(localPlayerIndex)`.
  **The music of another tribe joins the rotation when the local player first sees a player of that tribe.**
- `UpdateBattleMusic` S 0078c0e0, with `now = g_pGameSystem.nextTickTime` (simulation seconds):
  - if `FightList::IsPlayerInvolved(localPlayer)` (S 00573ad0: the player is the attacker of a fight, owns a
    fight's target building, or owns the first soldier of the fight's second side): if
    `battleMusicUntil < now` and no group is forced, force `music_battle` (0x41ed5533) and set
    `battleMusicActive`; in any case `battleMusicUntil = now + 20.0`;
  - else if `battleMusicActive` and `battleMusicUntil < now`: release the forced group if it still is
    `music_battle`; `battleMusicActive = false`.
  The battle loop therefore plays from the first frame of involvement until 20 simulation seconds after the last,
  and never interrupts another forced group (a briefing). If another group is forced at that first frame, the
  timer is armed all the same, so the battle loop does not start later in the same stretch of fighting; it can
  start only after 20 seconds without involvement [inferred from the two conditions].
- `nGame::System::Shutdown` S 007834e0 resets the playlist and clears `initialized` (S 0078c0c0), unless
  `uiSuppressed` is set.

**Menu music**, `nMenu::System::PlayMusic(index)` S 005d9f60 [known]: nothing if `index == currentMusicIndex`.
If the game screen is not open: `nMenu::System::StopMusic` (below, so the playlist is reset too; not
`SoundSystem::StopMusic` alone), then `PlayMusicGroup(musicSoundIds[index])`. If it is open:
`playlist.SetForcedGroup(musicSoundIds[index])`. `nMenu::System::StopMusic` S 005d9850: game screen closed →
`SoundSystem::StopMusic` and `SoundPlaylist_Reset`; open → release the forced group; `currentMusicIndex = -1`.

Entering a match: `nMenu::Game::OnEnter` S 005eed00 calls `nMenu::System::StopMusic` after the game desktop is
attached, so it takes the "open" branch and only releases a forced group; the menu theme keeps playing until the
playlist's first track (playlist step 2 above) cross-fades it out [known].

| Caller | Index | When |
|---|---|---|
| `nMenu::Main::Activate` S 005deee0 | 0 main theme | main menu shown |
| `nMenu::Main::HandleButtonClicks` S 005e27c0 | 4 credits | credits opened |
| `nMenu::Main::SwitchPanel` S 005df8b0, `HandleButtonClicks` | 0 | credits closed; lobby entry requested |
| `nMenu::Cinematic::Update` S 005fb3e0 | 1 briefing | cinematic starts (state 0), together with `SetDucking(true)` |
| `nMenu::Cinematic::Update` | stop | cinematic ends (state 2), with `SetDucking(false)` |
| `Lobby_PlayZoneMusic` S 004f5430 | 5, 6, 0 | lobby camera zone changes: zone 0 → 5 (outside), zones 1..3 → 6 (inside), other → 0 |
| `nMenu::Game::OnEnter`, `Book::OnHide`, quit, shutdown | stop | |

Indices 2 (`music_won`) and 3 (`music_lost`) are never played. No direct caller of `nMenu::System::PlayMusic`
passes them and no other code references the two ids [known]; with S 005d9f60 hooked, a won free game
(`DeclareWinner(0)`) and a lost one made no `PlayMusic` call from the end of the match until the next load or the
return to the menu, and no jingle was heard [live, 2026-10-12]. A sound effect plays when the end dialog opens
(the same one on a win and a loss, as far as the maintainer remembers). Leaving a match through the menu calls
`PlayMusic(0)` twice within 6 ms [live, 2026-10-12]. The maintainer takes the two unused jingles for a remnant of
the 10th Anniversary game [TODO] not checked.

### 3.7 Volumes, ducking, pause, mute

Effective FMOD volume per channel kind [known]:

| Kind | Formula | Where |
|---|---|---|
| master | `FSOUND_SetSFXMasterVolume(trunc(master * 255))`, `master` 0..1 | S 0056a050, 255.0 at S 007df6e0 |
| effect (`Play3D`) | `trunc(prop.volume * categoryVolume[prop.type])`; category × 0.25 if type 3 and ducked | S 0056d8d0 |
| emitter | `trunc(trunc(current) * categoryVolume[0])`; category × 0.25 if ducked | S 0056bab0 |
| UI | `trunc(prop.volume * categoryVolume[2])` | S 0056f700 |
| music | `trunc(trunc(current) * categoryVolume[1])`; target `prop.volume / 4` if ducked | S 0056ec40 |
| voice-over | `trunc(categoryVolume[2] * 255)` | S 0056df80 |

- `SoundSystem::SetCategoryVolume(category, v)` S 00569f80 stores the value and re-applies it to the running
  channels of the matching player: 0 emitters, 1 music, 2 UI and voice-over, any other value active effects
  [known]. Re-applying to active effects (`ActiveChannels::ApplyVolumeAll` S 0056db90) uses the same formula as
  at start, each channel with the category of its own record [known].
- Options screen (`nMenu::OptionsPanel::ApplyOptionValue` S 005e5bd0) [known]: option 16 master
  (`SetSfxVolume`), 17 music (category 1), 18 effects (**categories 0 and 3 together**), 19 interface
  (category 2). The effects slider shows category 0's value (`LoadOptionValue` S 005e55b0).
- Ducking: `SoundSystem::SetDucking(flag)` S 0056a0b0, set by the cinematic screen. It re-applies the emitter
  and music volumes only: effects already playing keep their volume, effects started while the flag is set get
  the quartered one. Voice-over and UI sounds are not ducked [known].
- Pause: `nMenu::Game::SetPaused` S 005ea9b0 calls `Sound_PauseAll` S 00569ff0 / `Sound_ResumeAll` S 0056a020:
  active effects, emitter channels (and the manager's `paused` byte, applied to emitters started later) and the
  voice-over are paused. **Music and UI sounds keep playing** [known].
- Mute: on `WM_ACTIVATE` (`CApplicationEx::HandleWindowMessage` S 00401f30), if the sound manager exists,
  `SoundManager::SetMuted(!active || minimized)` S 005c6730: nothing if the state is unchanged; muting saves
  `FSOUND_GetSFXMasterVolume()` and sets the master volume to 0; unmuting restores the saved value [known]. This is
  `SetMuted`'s only caller: nothing else mutes the game [known].
- Game speed above 3.0 suppresses new non-looping positional effects (§3.3) [known].

### 3.8 Voice-over

`Menu_PlayVoiceOver(name)` S 005db000 builds `voices\<name>.ogg`, maps it into the current language folder
(`Localization::BuildLanguagePath`), resolves the path and calls `VoiceOverPlayer::Play` [known].

- `Play(path)` S 0056e100: stop the current voice, store the path, `startDelay = 0.2` s.
- `Update(dt)` S 0056e070: idle with a pending path and not paused → count `startDelay` down; when it is
  `<= 0`, `SoundManager::PlayOneShotFile(path)` S 005c7510 (`FSOUND_Sample_Load` with mode `0x2021` = 2D, mono,
  no loop; the sample is freed when the channel is stopped), set the volume, unpause, reserve the channel.
  Playing and FMOD reports the end → `Stop`.
- `Stop` S 0056e030: unreserve and stop the channel, clear the path and the delay.

One voice at a time. Callers: the cinematic screen (one voice file per text page, S 005fb3e0) and the campaign
book (S 005fc9f0); `Sound_StopVoiceOver` S 005d98b0 when the book shows the quest view [known].

### 3.9 What triggers which sound

All triggers are in the renderer (`S2CG`), the UI (`nUi`, `nMenu`) or the lobby client; none is in `NLogic` [known
from the caller lists of `Play3D`, `PlayUiSound`, `AddEmitter`].

| Trigger | Sound | Position / source | Evidence |
|---|---|---|---|
| animation event `<Sound>` of a settler animation or a building animation | by `name` | event transform (model or its `slot`), tracked | `SoundEvent::Start` S 006b0550 |
| a moving settler, each time its accumulator of frame time reaches `0.5 / g_AnimTimeScale` s (interval computed once and cached; the accumulator is set to 1.0 while the settler stands, and is reduced by the interval at each step whether or not the sound plays), if visible and its proximity level > 0 | `sound_steps` 0x80d14ee3 | settler position, fixed | `CCharacter::UpdateFootstepSound` S 006904f0 |
| a work cycle is triggered on a building with none pending (a settler passes the entrance, a worker works; door opens) | `sound_dooropen` 0xe29ef893 | building position | `Building::TriggerWorkCycle` S 006aa640; `PlayStateAnimation(0)` S 006aa3b0 has the same sound but its one caller passes state 1 |
| building enters animation state 1 (door closes): 0.6 s after the **latest** trigger of the pending work cycle, each trigger moving the time out again | `sound_doorclose` 0x9c700243 | building position | `Building::Update` S 006abcf0 → `PlayStateAnimation(1)` S 006aa3b0 |
| building demolition starts | `sound_building_collapsed` 0xc5243073 | building position | `Building::StartDemolition` S 006ab840 |
| catapult shot begins | `sound_catapult_shoot` 0x8489cc23 | building position | `CatapultBuilding::Update` S 006d6000 |
| projectile impact: only for projectile type 1 (catapult stones); `Scene::OnShipFxEnded` S 0067f340 removes the other types at once | `impactSound` of its `projectiles.xml` template, a name looked up with `FindSoundIdByName` (`ProjectileTable::LoadProjectilesXml` S 006a4440) | target position | `Projectile::OnImpact` S 006a3af0 |
| effect movie keyframe with a `sound` | by name | the element is its own source; its position from `GetSoundPositionAndVelocity` S 006c6910; stopped with the keyframe or the movie (`Stop` S 006c6790) | `EffectMovieElement::Start` S 006c6bc0 |
| a tree starts falling | `sound_treefall` 0x01c27b83 | tree position | `TreeInstance::StartFalling` S 006dd050 |
| UI widget events (button click, edit box key, list item, ...; 13 callers) | by name (§3.5) | none | `UiResourceManager::PlaySoundByName` S 00494180 |
| a layout button is clicked; an `EditEx` field takes the focus; a list item is clicked | `uiClick0` | none | `Button::OnClicked` S 004b12d0, `EditEx::OnMouseButton0Down` S 0049b7b0, `Item::WasClicked` S 004c6da0 |
| a layout hotkey of a shown, enabled button (`Object::HandleHotkey` S 0049ffc0 → vftable slot 20 S 004af9a0 → `OnClicked`) | `uiClick0` | none | S 0049ffc0 |
| the HUD's round buttons, action buttons 1–4, good buttons, the free game's team, colour and start-position buttons; the combo box (`ComboBoxNew`) header and rows, slider arrows, tabs, `ListBox2` rows | `uiClick0` | none | `RoundIngameButton::OnClick` S 00622d10, `ActionButton::OnClick` S 006243c0, `GoodButton` S 0062fe50, `OverlayButton` S 004b24b0 |
| the selection is cancelled; the selection's click cases 0, 1 and 3 | `uiCancel` / `uiClick0` | none | `MenuSelection::Cancel` S 006162e0, `HandleClick` S 00617910 |
| the close icon of an `Overlapped` window | `uiClick1` | none | `Icon::PlayClickSound` S 004cf3a0; hidden in `menurequester.xml` and `menugameend.xml` (`close visible="false"`), so neither shows it |
| a typed character, Space, Backspace or Delete in an `nUi::Edit` field | `uiKey0` | none | S 004c07e0, S 004c0a40 |
| a row of the HUD message list is clicked: the rows are `nUi::Icon`s (S 005f8fa0), so a left click plays the icon click | `uiClick1` | none | `Icon::OnMouseButton0Up` S 004ce980 → `PlayClickSound` S 004cf3a0 |
| a new player message arrives (not for a list restored from a save) | `uiMessage0` / `uiMessage1` | none | `Messages::PollNewMessages` S 005f73e0 |
| a message row is removed | `uiRemove` | none | `Messages::Update` S 005f86a0 |
| an `Overlapped` window opens: the book (S 005fc310), the network info (S 005fd350), the message box (S 005feec0), the requester (S 005ffef0), the debug screen (S 0060a340), the end-of-game dialog (S 0061ff20) and any shown through vtable S 007f4574; only the cinematic screen (S 005fbd30) turns this sound off (`ClearPlayOpenSound` S 0062e1b0) | `uiDialog0` | none | `Overlapped::OnShow` S 0062e750 |
| a picked slot of the settings panel is dropped back: `CancelSlotDrag` has no "silent" flag and plays whenever a slot is picked | `uiCancel` | none | `CancelSlotDrag` S 00620c90 |
| lobby minigame and NPC actions | by id | none (`PlayUiSound`) or a fixed position (`Play3D`) | `CLobbyClient_MiniGame::PlaySound` S 00523720, `PlaySoundAt` S 00523770; both skipped while the local avatar is engaged at a different minigame table |

The click rule [known]: `Button::OnMouseButton0Up` S 004aecf0 calls vftable slot 34, `Button::OnClicked` S 004b12d0,
which plays `uiClick0`, only on the release, while the button and every parent are enabled and the cursor is over it.
Silent clicks: `SacrificeButton::OnClicked` S 0062f390 does not call the base; the anti-buff button's slot 34 is the
empty S 005657b0 (vftable 007f3414, RTTI 008801fc); `StatsGoodInfo::OnClick` S 0064c650 plays nothing; the
`SliderEx` throttle (S 004b95a0: throttle +0x260, decrease arrow +0x4e8, increase arrow +0x9e8) is no button;
typing in an `EditEx` is silent (only the debug `nUi::Edit` plays `uiKey0`). No sound name comes from a layout XML:
every name is a string literal in the binary. GUI records of `sounds.lua` with no trigger in the binary:
`clock_5sec` (registered by name at 0042abca, never played), `chipOnBoard`, `chipOnChip`, `sound_npc_helper`,
`sound_chesstakepiece`, `sound_chesspiecechange` [known: the callers of `PlaySoundByName`, `PlayUiSound`,
`UiSoundPlayer::Play`, `PlayClickSound` and the vftable click slots].

The three building sounds are played only when the building's virtual slot 1 returns 0; the two door sounds in
addition need a model and a building that is not under construction [known]. Slot 1 of the `S2CG::Building`
vftable S 007fa79c is S 006ab260, which returns the `hidden` integer at `Building + 0xc0`; slot 0
(`Building::SetHidden` S 006aa320) writes it and switches the model, shadow caster, scaffold and attachments
accordingly [known]. So a hidden building makes none of the three sounds. Slot 0's only caller is
`TerrainCell::SetVisible` S 006b4f80, driven every frame by the main view's quadtree cull (S 006db440 → S 006db220 →
S 006daff0 / S 006da740): a building is hidden unless its anchor's terrain block is both revealed and in the view
frustum [known]. [TODO] not established: whether a subclass overrides slot 1. The catapult shot has no such test.

`SetHidden` also sets the model's event `enabled` flag (model +0x50): not hidden and fog-visible (+0xc4). Every active
building's model is updated every frame, in view or not (`BuildingRenderer::Update` S 0069ff70 → `UpdateTransform`
S 006aaab0), so the `<Sound>` events of its clips tick everywhere and start only where the building is shown [known].
`TriggerWorkCycle` marks the cycle pending even under construction; only the clip and the door sound wait for a
finished building. The door's close is tested per logic tick against `timeInfo[0]` (`Building::Update` runs per
logic tick, from `CMapRenderer::SyncLogicTick` S 006882c0) [known].

Footstep gate [known]: the proximity level (`CCharacter + 0x90`, 0..100) is stepped once per frame by
`CCharacter::UpdateProximityLevel` S 006903f0: +5 (capped at 100) while the settler is visible and the squared
distance from its render position to the position handed in by `CCharacterMgr::Update` S 00692a30 is at most
50.0; otherwise −3 (floored at 0). `CCharacter::UpdateCameraDistance` S 00691060 computes that squared distance
on all three axes and sets it to `FLT_MAX` for an invisible settler. At the start of a walk the accumulator stands at
1.0, so the first step sounds at once and leaves 0.5 + dt: the second follows on the next frame [known]. Steps are
thus heard only from settlers
within about 7.07 world units of that position, and for up to 33 frames after one leaves the range (100 / 3).
That the position is the camera eye (device camera slot 2, as in §3.2) is [inferred] from the function's
description, not read in its body.

Driver of `SoundEvent` [known]: `S2CG::AnimatedVisual::Callback_OnAnimUpdate` S 006d8570, the per-animation
update callback of the animated model, calls `EventBase::Tick(time, enabled)` S 006b00f0 for every event attached
to the updated animation. `Tick` does nothing for an inactive event; computes
`localTime = (time − event.startTime) * g_AnimTimeScale`; calls `Start(time, localTime)` once, when
`localTime >= desc.start`, the visual's `enabled` flag is set and the event has not started; and from then on
calls `Update(localTime)` every time, keeping the event active while it returns true. `time` is the animation's
own time plus the slot's offset, or the global clock when that offset is 0. The event objects are created once per
play of an animation, not per loop cycle (`AnimatedVisual::PlayAnimationWithEffects` S 006d8670) [known]: a `<Sound>`
of a looping clip fires once per play.

`SoundEvent` rules [known]:

- `Start(time, localTime)` S 006b0550: play unless the sound is non-looping, the event has no duration and
  `localTime > start + 0.5` (a one-shot more than half a second late is dropped, e.g. after scrolling into view
  mid-animation).
- `Update(localTime)` S 006b01f0: an event with `duration > 0` lives until `localTime >= start + duration`, then
  calls `StopSourceSound(soundId, this)`; an event without duration ends at once (its sound plays on).
- The destructor calls `RemoveSource` (S 006b0180).

### 3.10 Ambient sound by location

Ambient sounds are **placed objects, not derived from terrain** [known]: the map carries a list of
`{type = sound property id, cell}` records (`NLogic::Ambients`, section `Logic Ambients`, `../map-format.md`).
`nGame::Sound` (`nGame::System + 0x610`, vftable S 008353dc) is the observer of that list:

- slot 0 `Sound_AddEmitterAtCell(soundId, cell)` S 0078c320: world position of the cell centre
  (`TerrainGrid::CellToWorldPos`), `y = 0`, `AddEmitter`;
- slot 1 `Sound_RemoveEmitterAtCell` S 0078c370: the same position, `RemoveEmitter`.

It is called by `Ambients::Add` S 00536f40 (map editor and debug tool only), `Ambients::RemoveAt` S 00536970 and,
for every record, by `Ambients::PostLoad` S 005366f0 after a map or save game is loaded [known]. The observer
pointer (`Ambients + 0x18`) is set to the `nGame::Sound` member at the end of `nGame::System::BuildScene`
S 007842e0 (called from `BuildWorld`) and cleared in `nGame::System::ShutdownAndDestroyGameSystem` S 00781cb0
[known]. `Add` and `PostLoad` skip a null observer; `RemoveAt` calls it unchecked.

The lobby world places its emitters from `lobby\scene\scene_ambient_sounds.xml` (`<obj type="sound:<hex id>"
scene="<zone>" pos="x y z">`); on a camera zone change all started emitters are removed and, if the lobby is in
mode 3 and the new zone is 0..3, those of the new zone added (`CLobby::UpdateZoneAmbientSounds` S 004f5480,
`CLobbyScene::StartAmbientSoundGroup` S 00500fe0, `StopAmbientSounds` S 00501040) [known].

## 4. Update order

Per frame, `SoundSystem::Update(dt)` S 00569e60, called from `CApplicationEx::FrameTick_InGame` S 004018e0 and
`FrameTick_Menu` S 00401780 with `Timer_GetFrameDeltaSeconds()` (`logic-core.md` §4.1, step 10: after the
simulation ticks of the frame, before the device-lost check and the rendering). Nothing happens while
`SoundSystem.enabled` is false [known]:

1. `SoundManager::Update` S 005c68b0: walk the tracked channels from the last to the first; a paused channel is
   skipped; a channel FMOD no longer reports playing is dropped from the tracking array (swap with last); for a
   playing channel with a source, poll the source and `FSOUND_3D_SetAttributes`. Then, if a listener provider is
   set, poll it and `FSOUND_3D_Listener_SetAttributes`; `FSOUND_Update`.
2. `ActiveChannels::Update` (remove ended effects; `dt` unused).
3. `SoundEmitterManager::Update(dt)` (§3.4).
4. `UiSoundPlayer::PruneChannels` (`dt` unused).
5. `MusicPlayer::Update(dt)` (fades).
6. `SoundPlaylist::Update(dt)` (next track).
7. `VoiceOverPlayer::Update(dt)`.

`dt` is the unscaled frame time: `Timer_GetFrameDeltaSeconds` S 0057b850 returns the last frame's duration in
milliseconds / 1000, or the constant 0.025 while the timer's fixed-step flag is set [known]. The game speed
(`UserProfile + 0x24`) is multiplied in only by the simulation (`logic-core.md` §3.1), not here. Music fades, the
playlist clock, emitter ramps and the voice-over delay therefore run in real time at every game speed and keep
running while the game is paused (speed 0); the pause itself is applied to channels (§3.7) [known].

`GameMusic_Update` runs earlier in the frame, inside `nGame::System::Update` S 00780d20 (step 5 of
`logic-core.md` §4.1), so a group forced there is picked up by the same frame's `MusicPlayer::Update` [known].
`Lobby::CLobby::Update` S 004fb460 calls `SoundManager::Update` a second time per frame (after
`SoundSystem::Update`) while the lobby is in mode 2 or 3 and a sound manager exists [known].

Per logic tick: nothing.

- Program start: §3.1.
- Match start: `Scene::Init` installs the listener; `nGame::System::BuildScene` S 007842e0 sets the `Ambients`
  observer; `Ambients::PostLoad` creates the emitters; `nGame::System::BuildWorld` S 00784d40 sets the
  `nGame::Sound` byte +4 and, unless `uiSuppressed`, calls `GameMusic_Init` [known].
- Match end: `nGame::System::Shutdown` S 007834e0 clears the `nGame::Sound` byte and, unless `uiSuppressed`,
  resets the playlist (S 0078c0c0); `Scene::Shutdown` clears the listener; `nMenu::Game::OnLeave` S 005eb030
  calls `Sound_ResumeAll` if the game was paused [known]. The emitters go with the simulation: `Ambients::Clear`
  S 00536a70 (called from `NLogic::System::Reset` S 00526f80 and at the start of `Ambients::Load`) removes every
  record through `RemoveAt`, i.e. through observer slot 1 and `RemoveEmitter` [known]; `Reset` is called from
  `NLogic::System::Shutdown`, which `ShutdownAndDestroyGameSystem` S 00781cb0 runs before it clears the observer
  [known from the caller lists and the call order in S 00781cb0]. Effects still playing are not stopped: they end
  by themselves or with their source object.
- Program end: `Sound_Shutdown` S 0056a830, called from `CApplicationEx::Shutdown` S 00401cb0 [known]: reset the
  playlist and clear its enabled byte, clear the UI player's enabled byte, stop and remove all active effects,
  `SoundManager::Shutdown` S 005c6e00 (free every entry, close every open stream, free every one-shot sample,
  `FSOUND_Close`), destroy the manager, empty the group map, `enabled = false`. Emitter and music channels are
  not stopped one by one.

## 5. Inputs and outputs

Consumes:

- the sound property table of `PropertiesDb` (`+0x78`) and the files it names;
- from the renderer: positions of settlers, buildings, trees, projectiles and effect elements; animation event
  timing; the camera;
- from the simulation, read-only: `NLogic::Ambients` records (through the observer), `FightList` (battle music),
  the local player's `spotted[8]` (`Player + 0x98`) and every player's `tribeId` (playlist),
  `GameSystem.nextTickTime` (battle timer);
- from the application: unscaled frame delta, game speed (`UserProfile + 0x24`, read only by `Play3D`), window
  activation, pause;
- from the menu: music index requests, voice-over names, the four volume sliders.

Produces: FMOD calls only. What other code takes back from it [known]:

- a sample's length: `SoundManager::GetEntryDuration` S 005c6840 (`FSOUND_Sample_GetLength` / the sample's
  default frequency; valid for sample entries only) is used by the lobby emote loader
  `LobbyEmotePlayer::LoadDefinitions` S 0051c710 to time emote animations; the lobby is not simulation;
- the volume values, read back by the options screen and by `UserProfile::StoreSettings` (§7).

Interfaces:

- `NSound::ICallback`, slot 0 `(float* outPosition, float* outVelocity)`: the position of a sound source. All five
  implementations write a position and the constant vector at S 0088f1b0 as velocity [known]: `SoundEvent`
  S 006b0500 (event world transform), `EffectMovieElement` S 006c6910 (element world position; slot 0 of its
  primary vftable), `CharacterSettler` S 006c7050 (the character's render position), `CatapultBuilding`
  S 006d5de0 and `TreeInstance` S 006dc940 (translation of the object's world matrix). Of the ten callers of
  `Play3D` only `SoundEvent::Start` and `EffectMovieElement::Start` pass a source; the other eight pass null, so
  the settler, catapult and tree implementations are never polled for a sound started in this binary [known].
- the listener interface (§3.2);
- the `Ambients` observer (§3.10).

## 6. Data-driven parameters

**`data\game\scripts\properties\sounds.lua`** [known]: 156 `sn_create` records, 311 file names. Types: 22
Ambient, 14 Music, 32 GUI, 88 Sound. Keys used and their observed values:

| Key | Values in the file | Notes |
|---|---|---|
| `sn_setName` | `"steps"`, `"opening Door"`, `"scythe"`, `"uiClick0"`, `"Beach"` | the name referenced by XML `name` attributes and by the UI |
| `sn_addFileName` | `"[data]\\sound\\human\\Footsteps_01.wav"` (10 variants), `"[data]\\sound\\music\\Egyptians_01.ogg"` | 1 to 10 per record (108 records have one file); 277 names carry the `[data]\sound\...` path, the 34 of the lobby records are bare file names such as `"Lob_Atmo_03_Brook_Loop.ogg"`, `"shake0.wav"` |
| `sn_setType` | `SoundType_Ambient` 0, `_Music` 1, `_GUI` 2, `_Sound` 3 (globals defined at the top of the file) | set on all 156 records; constructor default 3 |
| `sn_setLooping` | 39 `true` (ambients, work loops, the menu themes, `music_battle`), 110 `false` (among them `music_won`, `music_lost`) | not called for 7 records, among them the six tribe music records; default false |
| `sn_setVolume` | 32 (`ambient_lava`), 64 (17 terrain ambients), 120, 128, 160, 190 (clicks), 200, 220, 255 | 70 records; default 255 |
| `sn_setPriority` | 0, 8..12 (effects), 100 (ambients, clicks), 150, 200 (messages, NPC) | 142 records; default 0 |
| `sn_set3DMinDistance` | 1, 3, 10, 13..16, 20, 25; mostly 15 (36) and 20 (27) | 88 records; audible within 30× this value; default 1.0 |
| `sn_set3DSound` | `false` on 68 records (ambients, music, GUI), `true` written out on 6 | default true |
| `sn_set2DDistance` | 50 (18 terrain ambients), 1000 (lobby indoor and outdoor), 5 (lobby fireplace), 10 (lobby brook) | 22 records; default 10 |
| `sn_setMusicTribe` | `bavarians`, `egyptians`, `scots` (tribe globals, not strings) | 6 records: melody and percussion per tribe; default -1 |
| `sn_setPercussion` | `true` on the three `music_*Per` records | default false |
| `sn_set3DMaxDistance` | not used | default 1e9 |

Defaults: `SoundProperty` constructor S 00555a80 [known].

Music records: per tribe three melody files (`Bavarians_0x`, `Egyptians_0x`, `Scotsmen_0x`) and three percussion
files (`Perc_*_0x`); `music_battle` (`Battle_loop.ogg`, looping); the seven menu ids of §2.5, looping except
`music_won` and `music_lost`. Terrain ambients (18): `ambient_beach`, `desert1..3`, `forest1..2`, `meadow1..2`,
`water1..4`, `lava`, `highlands1..3`, `ice`, `mountains`; one file each under `[data]\sound\ambients\` (`.wav`
for the first twelve, `.ogg` for lava, highlands, ice and mountains), looping, 2D, radius 50, priority 100, volume
64 (`ambient_lava` 32). The other four Ambient records are the lobby's (`ambient_lobby_indoor`, `_outdoor`,
`_fireplace`, `_brook`).

**`data\game\character\settler_animations.xml`** (78 `<Sound>`), **`data\game\settings\buildings.xml`** (538)
[known]: `<Sound start="seconds" name="<sn name>" [duration="seconds"] [slot="<slot name>"]/>` as a child of an
`<Animation>` element (all 78 in `settler_animations.xml`) or of a `<Working>` element (all 538 in
`buildings.xml`). Examples: `<Sound start="0.3" name="scythe"/>`, `<Sound start="10" name="ox"/>`,
`<Sound start="4" duration="56" name="sawmill blades"/>`. 125 of the 616, all in `buildings.xml`, carry a
`duration` (timed loops such as fires and saws). No element in either file carries a `slot`: the attribute is
read by the loader (§2.6) but unused by the installed data.

**`data\game\settings\effectMovies.xml`**: `<FX ... sound="<sn name>"/>`; five occurrences with three names
(`"sacrificefire loop"`, `"sacrifice thunder"`, `"smithy fire ignite"`). **`projectiles.xml`**: one
`impactSound="catapult impact"` [known].

**`data\lobby\scene\scene_ambient_sounds.xml`**: 7 emitters in 4 zones (§3.10) [known].

**Files** [known]: `data\game\sound\{ambients,Buildings\*,Human\*,misc,music}` plus a few files directly in
`data\game\sound`, and `data\lobby\sound\*`: 198 `.ogg` (194 game, 4 lobby) and 126 `.wav` (85 game, 41
lobby), not encrypted (`formats-inventory.md` §3.13). Voice files:
`data\game\language\<language>\voices\<name>.ogg` (540 in the German install, e.g. `B1_1_2.ogg`). Formats found
in the install:

| Container | Format | Count |
|---|---|---|
| `.wav` | PCM 16-bit mono 44.1 kHz | 103 |
| `.wav` | IMA ADPCM (format tag 17) stereo 32 kHz: the twelve `.wav` terrain ambients | 12 |
| `.wav` | IMA ADPCM mono 44.1 kHz: `Buildings\HouseCrash01/02.wav`, `Buildings\Catapult\Impact.wav`, `Fire.wav` | 4 |
| `.wav` | IEEE float 32-bit (format tag 3) stereo 44.1 kHz: `lobby\sound\miniGamePoker\*` | 7 |
| `.ogg` | Vorbis 44.1 kHz mono (162 sound files, all 540 voices) or stereo (36 sound files) | 738 |

**Constants in code** [known]: 32 channels at 44.1 kHz; roll-off 4.0; audibility factor 30; emitter limit 4,
height fade 80, ramp 255/s; music ramp 256/s, overlap 2.0 s; battle hold 20.0 s; ducking 0.25; voice delay 0.2 s;
late one-shot limit 0.5 s; footstep interval 0.5 s; door close 0.6 s after open; speed cut-off 3.0; default music
volume 0.3.

## 7. Save and load

- **Save games contain no audio state** [inferred: none of the classes in §2 has a store or load function; the
  sound system is application-wide and `GameMusicState` is rebuilt by `GameMusic_Init`]. What a save does carry is
  the simulation-side `Logic Ambients` list (`save-format.md`, `../map-format.md`), from which the emitters are
  rebuilt by `Ambients::PostLoad`.
- Rebuilt on load: emitters (`Ambients::Load` first clears the list, removing the emitters of the previous
  world, S 00536a70); the playlist (the local player's tribe first, then the tribe of each player the local
  player has already `spotted`, in player index order, during the `GameMusic_Update` call at the end of
  `GameMusic_Init`); battle music state (off, timer 0). The playlist position, the running track and all channels
  are not restored [known].
- `GameMusicState.tribeTracksAdded[8]` is per **player index**, and is zeroed only by the constructor S 0078c0a0
  (called once, from `nGame::System::ctor` S 00783190, itself called from `nMenu::Game::ctor`); neither
  `GameMusic_Init` nor the shutdown path S 0078c0c0 clears it [known: these are its only writers in the mapped
  code]. Two consequences [inferred]: a tribe played by several spotted players is appended once per such player
  (harmless: the playlist picks a group by tribe key and the group's entries are then the same record); and from
  the second match of one program run on, a player index whose flag was set in an earlier match does not get its
  tribe added again, so that tribe's music stays out of the rotation unless it is also the local player's tribe.
  The object lives for the whole process [known]: `nMenu::Game::ctor` S 005ee5d0 has one caller,
  `nMenu::System::Initialize` S 005dda30, which `CApplicationEx::Initialize` S 004075d0 calls once from `WinMain`
  S 00407cf0; the shutdown S 0078c0c0 resets the playlist and clears only byte +0x00. So the second consequence
  holds in every run with more than one match (presentation only).
- **User settings**: `settings.cfg`, section `UserSettings` (`formats-inventory.md` §3.11). Five consecutive f32
  after `smartCursor` [known] S 00579640 / S 00579960: master (`Sound_GetSfxVolume` S 0056a080: the manager's
  cached `savedSfxVolume / 255`, so the value from before a focus-loss mute; 1.0 when the sound system is
  disabled), then `categoryVolume[1]` music, `[2]` GUI, `[3]` effects, `[0]` ambient. On load each value is
  applied immediately through `SetSfxVolume` / `SetCategoryVolume`, both of which do nothing while the sound
  system is disabled. Defaults before the file is read (`UserProfile_ResetSettingsDefaults` S 00579c00 →
  `Sound_ResetVolumesToDefaults`): master 255 (1.0), music 0.3, the others 1.0. Because the master is kept as an
  integer 0..255 (`trunc(v * 255)`), a stored value is a multiple of 1/255 [known].

## 8. Determinism notes

Presentation only [known unless marked]:

- **No writes to simulation state.** The audio functions of §11 (namespaces `ai::audio`, `ai::sound`, `NSound`,
  the `Sound_*` and `GameMusic_*` functions) write only to the objects of §2, to FMOD and to
  `g_SoundEmitterNextKey`. The simulation-side reads are `FightList::IsPlayerInvolved` S 00573ad0 (a walk over
  the fight list that writes nothing), the local player's `spotted`, `Player.tribeId`, `nextTickTime`, and the
  ambient records handed over by the observer.
- **No use of the simulation random generator.** Variant and playlist choices call the C runtime `rand()`
  (S 0056f880, and three calls in S 0056e190), not `LogicRandom_*` (`logic-core.md` §3.3). The draws depend on
  frame timing and on what is on screen, so two machines in the same match generally play different variants
  and different music orders.
- **The C runtime `rand()` is not a simulation input.** `_rand` S 006f41e2 has 26 calling functions [known, from
  its cross-references]: the two audio ones; the pre-game slot shuffle `AssignRandomPlayerIndicesAndTeams`; lobby
  client code (avatar dialog, village connection, dice and poker minigames); UI (`nUi::Graph::Draw`, loading
  panel, building overlay); the map editor and debug tools; the renderer (`S2CG::FarmBuilding::ctor`); the
  cinematic camera (`NSettlers::System::PickRandomCinematicTarget` S 006556a0,
  `nGame::System::UpdateCinematicMode`); and the Lua binding `math.random` S 005ca190. None is an `NLogic`
  function. A Lua script calling `math.random` would share the sequence with the audio draws; none of the 355
  `.lua` files of the installed data does [known].
- **No call from a logic tick.** No `NLogic` function calls `Play3D`, `PlayUiSound` or the music functions; the
  only `NLogic` → audio path is the `Ambients` observer, and `Ambients` itself is static data during a match
  (added or removed only by the editor and debug tools).
- **Frame-rate dependent, and independent of the game speed.** Everything runs on the unscaled frame delta (§4)
  and on renderer events (animation events fire when a model's animation passes their start time; steps only for
  visible, near settlers).
- **Nothing in the simulation waits for a sound.** The one consumer of an audio result is the lobby emote timing
  (§5), outside any match.
- The sound system may be disabled entirely (FMOD failure) without any other effect [inferred from the `enabled`
  guards].

## 9. Notes for a Godot reimplementation

Maps onto engine features:

- **Buses.** One bus per category under a master bus: `Ambient`, `Music`, `GUI` (UI and voice), `Sound`. Slider
  values are linear gains (0..1) multiplied into the channel volume, not decibels: use `linear_to_db`. Default
  music gain 0.3. Ducking = × 0.25 on `Sound`, `Ambient` and `Music`. Mute on focus loss = master bus mute.
- **Volumes.** `prop.volume / 255` is a linear gain as well; FMOD 3 channel volume is linear.
- **Effects** → `AudioStreamPlayer3D` for `is3D` records, plain `AudioStreamPlayer` otherwise. Use
  `ATTENUATION_INVERSE_DISTANCE`, `unit_size = minDistance3D` scaled so that the gain matches
  `min / (min + 4 (d − min))`; Godot's inverse model has no roll-off factor, so either bake the curve into a
  custom attenuation (attenuation disabled and volume set per frame from the formula) or accept an approximation.
  Reproduce the start-time culling exactly: do not start a sound when the listener is `30 * minDistance3D` or
  farther, or when the speed is above 3 and the record is not looping. Variants: `AudioStreamRandomizer` with
  `PLAYBACK_RANDOM` (the original allows immediate repeats).
- **Listener**: an `AudioListener3D` placed by the rule of §3.2, not on the camera.
- **Tracked sources**: parent the player node to the emitting node; on the emitter's removal free looping players
  and reparent non-looping ones to the scene root at their last position.
- **Ambient emitters**: a small manager node reproducing §3.4 (nearest four distinct sounds, linear fade between
  `r` and `2r`, height fade over 80, ramp 255/s). These are non-positional streams whose volume the manager sets;
  do not use engine attenuation for them.
- **Music**: two or more `AudioStreamPlayer`s on the `Music` bus with a manual linear cross-fade at 256 volume
  units per second of real time (one second for a record volume of 255);
  the playlist logic of §3.6 (melody, then percussion of the same tribe, next track 2 s before the end);
  `AudioStreamOggVorbis.loop = true` for looping records. Tribe sets join when a tribe is first seen.
- **UI sounds**: one player pool; apply the same-frame priority rule of §3.5.
- **Voice**: one `AudioStreamPlayer` on the `GUI` bus, 0.2 s start delay, at full gain (no per-record volume).
- **Pause**: pause effects, emitters and voice; keep music and UI running (`process_mode` per node).
- **Clock**: drive fades, the playlist, emitter ramps and the voice delay with the unscaled frame delta, not with
  the simulation's speed-scaled time (§4). Only the battle-music hold uses simulation seconds.

Must be reproduced exactly for the game to sound the same: the category mapping by record type; the default
volumes; the culling radius and speed cut-off; the emitter formula; the playlist order rule and the 20 s battle
hold; which triggers exist (§3.9) and the timings from the XML files; the late-start rule of `SoundEvent`.
Exact FMOD mixing, hardware 3D and the bidirectional loop flag need not be reproduced.

Converter output:

- **Audio files**: `.ogg` loads as `AudioStreamOggVorbis` and the 103 PCM 16-bit `.wav` files as
  `AudioStreamWAV`, either copied into the cache with their relative paths or loaded at run time from the
  install (`AudioStreamOggVorbis.load_from_file`, `AudioStreamWAV.load_from_file`). The other 23 `.wav` files
  (16 IMA ADPCM, 7 IEEE float; table in §6) must be checked against the engine's WAV loader and decoded to PCM by
  the converter where it refuses them. Records reference files by name: resolve a name the way the game does,
  by file name alone, case-insensitively, over `data\game` and `data\lobby` (§3.1).
- **Sound table**: evaluate `sounds.lua` (after decryption) into one resource or JSON file: per record
  `{id (u32), symbol, name, files[], looping, type, volume, priority, min_distance_3d, max_distance_3d, is_3d,
  distance_2d, music_tribe, percussion}` with the defaults of `properties-data.md` §2.9 for absent keys.
- **Animation sound events**: per animation of `settler_animations.xml` and `buildings.xml` a list
  `{start, duration, slot, sound_name}`; either as method-call or audio tracks of the converted `Animation`, or
  as a side table consumed by the node that plays the animation (needed anyway for the late-start rule).
- **Effect movies and projectiles**: keep the `sound` / `impactSound` names in their converted tables.
- **Ambient emitters**: per map the `Logic Ambients` records as `{sound_id, cell}`; world position = cell centre,
  height 0.
- **Menu music table** (§2.5) and the eight UI sound names are code constants; put them in the remake's data.

## 10. Open questions

| # | Question | Settled by |
|---|---|---|
| 1 | Answered (§3.4, outcome of step 4): on a processor with SSE2 the fade-out never frees the channel (`targetVolume` becomes −2147483648.0); without SSE2 it does. To hear once: a map with more than four ambient sound ids | static: S 0056bab0, S 0056d2e0, S 006f2af0, S 0056fda0 |
| 2 | Answered (§3.2): in a match the device camera is the `nGame::Camera`, `target − eye` is its look direction of length 1, and the listener sits `0.8 * (eye.y − h)` units down the view line | static: S 00784f70, S 00784f90; live 2026-10-12 |
| 3 | Answered (§3.6): `music_won` and `music_lost` (menu indices 2, 3) are never played: the five callers of `nMenu::System::PlayMusic` pass only the constants 0, 1, 4, 5, 6 [known], and no `PlayMusic` call followed a won or a lost free game [live, 2026-10-12] | — |
| 4 | Answered (§3.1): `FSOUND_LOOP_BIDI` on the music streams loops forward; `maintheme.ogg` restarts cleanly [live, maintainer, 2026-10-14] | — |
| 5 | What reads the `nGame::Sound` byte +4 (`nGame::System + 0x614`; set by `BuildWorld`, cleared by `nGame::System::Shutdown`). The two observer slots do not test it: they test `SoundSystem.enabled` only [known] | static: accesses to `nGame::System + 0x614` |
| 6 | Answered in part (§3.9): `SetHidden`'s only caller is `TerrainCell::SetVisible` S 006b4f80 (the view's block cull). Open: subclass overrides of slot 1 | static: the slot 1 entries of the `S2CG::Building` subclass vftables |
| 7 | Answered (§3.9): event objects are made once per play of an animation (`PlayAnimationWithEffects` S 006d8670), so a looping clip's `<Sound>` fires once per play | — |
| 8 | Which position `CCharacterMgr::Update` hands to `UpdateCameraDistance` for the footstep range (§3.9) | static: the argument set-up in S 00692a30 |
| 9 | Whether `nMenu::Game` (and with it `GameMusicState`) is constructed once per program run (§7) | static: callers of `nMenu::Game::ctor` S 005ee5d0 |
| 10 | FMOD 3 attenuation curve and hardware-3D fallback as actually mixed | live: record the output at known distances; or the FMOD 3.7x documentation |
| 11 | Whether Godot's WAV loader accepts the IMA ADPCM and IEEE float `.wav` files of the install (§6, §9) | test load of `ambients\Beach.wav` and `miniGamePoker\cards_mixing.wav` |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 0056b310 | `Sound_Init` | start-up: FMOD, load all sounds, defaults |
| 0056b190 | `Sound_LoadSoundsFromProperties` | sound table → FMOD entries and variant groups |
| 0056a830 | `Sound_Shutdown` | teardown |
| 00569e60 | `ai::sound::SoundSystem::Update` | per-frame order of all players |
| 0056a2f0 | `SoundSystem::Play3D` | positional effect: culling, variant, volume |
| 00569f10 | `SoundSystem::StopSourceSound` | stop one sound of one source |
| 00569f60 | `SoundSystem::RemoveSource` | source destroyed |
| 00569ee0 | `SoundSystem::PlayUiSound` | UI sound entry |
| 0056a410 | `SoundSystem::PlayMusicGroup` | play a music record directly |
| 00569f40 / 00569f50 | `SoundSystem::PlayMusic` / `StopMusic` | current track set / cleared |
| 00569f80 | `SoundSystem::SetCategoryVolume` | per-type volume |
| 0056a050 / 0056a080 | `SoundSystem::SetSfxVolume` / `Sound_GetSfxVolume` | master volume |
| 0056a0b0 | `SoundSystem::SetDucking` | cinematic ducking |
| 0056a110 | `Sound_ResetVolumesToDefaults` | default volumes |
| 00569ff0 / 0056a020 | `Sound_PauseAll` / `Sound_ResumeAll` | game pause |
| 0056a2a0 | `SoundSystem::PickRandomVariant` | `rand()` variant choice |
| 0056a190 | `SoundSystem::FindPropertyBySoundId` | entry index → sound property |
| 0056d8d0 | `SoundChannelEntry_ApplyVolume` | effect volume formula |
| 0056d9b0 / 0056dad0 / 0056dee0 | `NSound::ActiveChannels::Update` / `RemoveSource` / `Add` | effect channel list |
| 0056dca0 | `ActiveChannels::GetChannelPositionAndVelocity` | tracked position callback |
| 0056d0e0 / 0056d270 | `SoundEmitterManager::AddEmitter` / `RemoveEmitter` | ambient emitters |
| 0056d2e0 | `SoundEmitterManager::Update` | nearest four, claim, fade, start |
| 0056bab0 | `SoundEmitterManager::UpdateChannelVolume` | emitter volume formula |
| 0056fda0 | `Sound_NearestEmitters_Offer` | nearest list insertion |
| 0056f8f0 | `ai::sound::RampedFloat::RampTowardTarget` | linear ramp |
| 0056f700 / 0056f550 | `UiSoundPlayer::Play` / `PruneChannels` | UI sounds, priority rule |
| 0056f480 / 0056f1f0 / 0056ec40 | `MusicPlayer::Play` / `Update` / `UpdateChannelVolume` | music cross-fade |
| 0056e190 | `SoundPlaylist::Update` | playlist scheduler |
| 0056ebf0 / 0056e150 / 0056e170 / 0056e680 | `SoundPlaylist::AddTrack` / `SetForcedGroup` / `ClearForcedGroup` (release of the forced group) / `SoundPlaylist_Reset` | playlist control |
| 0056e100 / 0056e070 / 0056e030 | `VoiceOverPlayer::Play` / `Update` / `Stop` | voice-over |
| 005db000 | `Menu_PlayVoiceOver` | voice file path |
| 005c65e0 | `ai::audio::SoundManager::Init` | `FSOUND_SetOutput`, `FSOUND_Init` |
| 005c7250 | `SoundManager::LoadSound` | sample or stream entry, mode flags |
| 005c7550 | `SoundManager::PlayEntry` | start an entry on a free channel |
| 005c7510 | `SoundManager::PlayOneShotFile` | unmanaged one-shot sample (voice) |
| 005c68b0 | `SoundManager::Update` | 3D tracking, listener, `FSOUND_Update` |
| 005c6fc0 | `SoundManager::StopChannel` | stop and release |
| 005c6b30 | `SoundManager::Set3DTracking` | register a tracked channel |
| 005c6730 | `SoundManager::SetMuted` | focus-loss mute |
| 005c6840 | `SoundManager::GetEntryDuration` | sample length in seconds |
| 0078c2b0 / 0078c220 | `GameMusic_Init` / `GameMusic_Update` | in-match playlist filling |
| 0078c180 | `GameMusic_AddTribeTracks` | tribe tracks into the playlist |
| 0078c0e0 | `GameMusicState::UpdateBattleMusic` | battle loop on and off |
| 0078c320 / 0078c370 | `Sound_AddEmitterAtCell` / `Sound_RemoveEmitterAtCell` | `nGame::Sound` observer slots |
| 005366f0 | `NLogic::Ambients::PostLoad` | re-announce ambients after load |
| 005d9f60 / 005d9850 | `nMenu::System::PlayMusic` / `StopMusic` | menu music by index |
| 005dda30 | `nMenu::System::Initialize` | UI sound names, menu music ids |
| 00494080 / 00494180 | `UiResourceManager::RegisterSound` / `PlaySoundByName` | UI sounds by name |
| 006b0550 / 006b01f0 / 006b0920 | `S2CG::SoundEvent::Start` / `Update` / `Desc::LoadFromXml` | animation sound events |
| 006904f0 | `S2CG::CCharacter::UpdateFootstepSound` | steps |
| 006aa3b0 / 006aa640 / 006ab840 | `S2CG::Building::PlayStateAnimation` / `TriggerWorkCycle` / `StartDemolition` | door and collapse sounds |
| 006d6000 | `S2CG::CatapultBuilding::Update` | catapult shot sound |
| 006a3af0 | `S2CG::Projectile::OnImpact` | impact sound |
| 006c6bc0 | `S2CG::EffectMovieElement::Start` | effect movie sound |
| 006dd050 | `S2CG::TreeInstance::StartFalling` | tree fall sound |
| 00681c10 | `S2CG::Scene::GetListenerTransform` | in-match listener |
| 004f56c0 | `Lobby::CLobbySoundListener::GetListenerAttributes` | lobby listener |
| 004f5430 / 004f5480 | `Lobby_PlayZoneMusic` / `CLobby::UpdateZoneAmbientSounds` | lobby zone music and ambience |
| 00579640 / 00579960 | `UserProfile::StoreSettings` / `LoadSettings` | volumes in `settings.cfg` |
| 005e5bd0 / 005e55b0 | `nMenu::OptionsPanel::ApplyOptionValue` / `LoadOptionValue` | volume sliders |
| 005ea9b0 | `nMenu::Game::SetPaused` | pause and resume of sounds |
| 00401f30 | `CApplicationEx::HandleWindowMessage` | mute on deactivation |
| 004018e0 / 00401780 | `CApplicationEx::FrameTick_InGame` / `FrameTick_Menu` | per-frame callers of `SoundSystem::Update` |
| 0057b850 | `Timer_GetFrameDeltaSeconds` | the unscaled frame delta all players run on |
| 004fb460 | `Lobby::CLobby::Update` | second `SoundManager::Update` per frame in lobby modes 2 and 3 |
| 005c6e00 | `SoundManager::Shutdown` | free entries, streams, samples; `FSOUND_Close` |
| 005c6770 / 005c6790 | `SoundManager::SetSfxMasterVolume` / `Sound_GetSfxMasterVolume` | master volume set and cached (+0x60) / read back |
| 0078c0a0 / 0078c0c0 | `GameMusicState` constructor / match-end reset | zero all fields / reset the playlist, clear `initialized` |
| 007842e0 / 00784d40 / 007834e0 | `nGame::System::BuildScene` / `BuildWorld` / `Shutdown` | observer set; music init; playlist reset |
| 00536a70 / 00536970 | `NLogic::Ambients::Clear` / `RemoveAt` | emitters removed with the simulation |
| 005eb030 | `nMenu::Game::OnLeave` | resume sounds when leaving a paused game |
| 00573ad0 | `ai::military::FightList::IsPlayerInvolved` | battle music condition |
| 006b00f0 / 006d8570 | `S2CG::EventBase::Tick` / `AnimatedVisual::Callback_OnAnimUpdate` | start and update of animation events |
| 006903f0 / 00691060 | `S2CG::CCharacter::UpdateProximityLevel` / `UpdateCameraDistance` | footstep range gate |
| 006aa320 / 006ab260 | `S2CG::Building::SetHidden` / vftable slot 1 (returns `hidden`) | gate of the building sounds |
| 006b0500 / 006c6910 / 006c7050 / 006d5de0 / 006dc940 | `NSound::ICallback` slot 0 of `SoundEvent`, `EffectMovieElement`, `CharacterSettler`, `CatapultBuilding`, `TreeInstance` | source position callbacks |
| 006e3fd0 / 006ef8a0 | `FileScanHolder::ResolvePath` / `FileScan::ResolvePath` | sound file lookup by file name |
| 006f41e2 / 005ca190 | `_rand` / Lua `math.random` | the random source of variant and playlist choices |
