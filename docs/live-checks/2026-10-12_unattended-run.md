# Unattended live checks, 2026-10-12 (evening)

Process: SADK.exe started 17:46:14 on the game PC, offline free game from the developed save, local human =
player 0, five computer players, victory mode 1. Session start: tick 102,829, speed 1, not paused.
All addresses are static addresses (image base 0x400000). Every call or write into the game is listed in the
block of the entry that needed it.

### Ini files behind a byte order mark.
Status: PARTLY
What was done: read `g_NCommManager` (pointer at S 00885754) `+0x360` (the `NetworkConfig` block) at tick
103,120; read the first bytes and the text of `data\game\settings\network.ini` and `engine.ini` on the game PC
over SSH (read only); counted `*.mshraw` files below the install folder. No call, no write.
Measured: config block: gamePort 5479, broadcastPort 6582, broadcastTimeout 10000, pingFrequencyMenu 10.0,
pingFrequencyGame 2.5, timeHostWaitForClients 30.0, timeClientWaits 3.0, timesClientRetries 5,
timeClientWaitsFailed 4.0, url "<the maintainer's server>:8777", patchlevel 9212. The file starts with `EF BB BF` directly
before `[Basics]` and has `gamePort = 5478` in that first section. The file on the game PC has a SECOND
`[Basics]` section at its end (after `[Lobby]`) with `gamePort=5479`. `pingFrequencyGame` 2.5 and patchlevel
9212 are not the code defaults (3.0, -1), so the file was read. `engine.ini` also starts with `EF BB BF` before
`[Engine]`, has `useMeshCache = 1`, and there are 0 `.mshraw` files below the install folder; no `nomeshcache`
mod is installed (mods: assetshare, billboards, borderless, foresterfix, gamebridge, mpsave, navalcombatfix,
nopreview, oscursor).
Conclusion: The `gamePort = 5478` of the first section is not what the game uses: the effective value is 5479,
as `network-session.md` §6 infers (the mark hides the first section). Whether the 5479 is the fallback or the
value of the second `[Basics]` section at the end of the file cannot be told apart by this read (both are 5479).
For `engine.ini`: `useMeshCache = 1` behind the mark and no `.mshraw` file fits "the `[Engine]` section is
hidden as well", but the switch-and-restart half was not done (needs a restart).

### Debug icons.
Status: PROVEN
What was done: read the five `nUi::Icon` members of the `nMenu::Game` screen (base 0x241f8f48 in this run;
offsets +0xb338 iconDebugSession, +0xb730 iconGrab, +0xbb28 iconHideUi, +0xc480 iconSpeed, +0xc878 iconCamera)
at tick 103,120: vftable, vftable slot 10 (`+0x28`), and the `nUi::Object.visible` byte (`+0x14d`, the byte
`nUi::Object::Hide` S 004a1130 clears). No call, no write.
Measured: all five: vftable S 007e26ec, slot 10 = S 004cf210 (`nUi::Icon::Hide`, which calls
`nUi::Object::Hide`), visible = 0. The match had run for more than 100,000 ticks.
Conclusion: The five debug icons are hidden in a running match; `nUi::Icon` overrides slot 10 with its own
`Hide` S 004cf210 (not the base S 004a1130 itself as §3.13 words it, but with the same effect). Agrees with
`camera-input-cutscenes.md` §3.13.

### Walk and pick-up timing.
Status: PROVEN
What was done: observe-only hook on `NSettlers::Settler::Update` S 00656ec0 from tick 104,268 to 105,615, game
speed 1. The hook selected the first eight carriers (vftable S 007f847c) of player 0 that were at work and, after
each update, recorded tick, cell (`movement +0x128/+0x12c`), animation kind (`+0x1c`), state (`+0x54`),
interpolator progress / carry-over / step rate (`movement +0x04/+0x08/+0x0c`) and the animation's remaining /
total time (`+0x20/+0x24`) whenever cell, kind or state changed. No call, no write. Hook removed afterwards.
Measured:
- Updates: each of the eight carriers got exactly one `Update` per tick (1,347 calls in 1,347 ticks);
  1,347 ticks took 135.096 s of wall clock = 9.971 ticks per second. The function ran about 1,617 times per
  tick (all settlers of the match).
- Flat street (step rate 0.058 = `cfg_setSettlerSpeed`, slope factor 1.0), carrier 0x2b2eab88 on a street of
  three cells (43,73)-(44,74)-(44,75): walk begins in tick 104,343 (progress 0.058 after that tick), cell
  commit in tick 104,360 with carry-over 0.044, next commit in tick 104,377: 18 advances for the first cell
  (18 x 0.058 = 1.044 > 1), 17 for the second (0.044 + 17 x 0.058 = 1.030). Over all eight carriers: 59
  recorded flat steps of 17 ticks and 2 of 18 after the first step of a walk (which is always 18 advances and
  shows as a tick difference of 17 because the first advance happens in the tick the walk starts).
- Slopes (not asked, same data): step rate 0.0464 (0.8 x 0.058) gave 21 ticks (11 times) and 22 (once); step
  rate 0.0348 (0.6 x 0.058) gave 28 (5 times) and 29 (2 times).
- Pick-up and put-down: 48 phases of animation kind 2 and 48 of kind 3, every one with total 3.3 and visible
  for 3 consecutive ticks (remaining 2.3, 1.3, 0.3 after the update) followed by one tick with kind 0 in which
  the timer ran out; kind 3 starts in the tick after that. Example: kind 2 in ticks 104,279..104,281, kind 0 in
  104,282, kind 3 in 104,283..104,285, kind 0 in 104,286, next state in 104,287. So each phase takes 4 ticks
  and a whole pick-up or put-down 8 ticks.
Conclusion: Agrees with `settlers-jobs.md` §3.7 and §3.8.1: one update per logic tick, 10 ticks per second at
speed 1, 17 or 18 ticks per flat cell with the overshoot carried into the next step, and 4 ticks per pick-up /
put-down phase.

### Defence fraction of an attacked computer player.
Status: PROVEN
What was done: observe-only hooks from tick 104,663 on `NMilitary::Attack::StartAttack` S 00576500 (target
building's `military +0x64` read on entry and on return, plus the owner's `NPlayer::Military +0x1c`),
`AiAttackWatch_InitFromAttack` S 0059b3f0 (the same field read on return) and `Attack::DispatchDefenders`
S 00576400 (the `soldierFraction` argument and the return address). No call, no write. The attack was one a
computer player started by itself against another computer player.
Measured: tick 105,311: `StartAttack(attacker = player 3, target building 0x44ab9aa0 of player 2 (computer),
soldierFraction 0.0556)`. Field before the call: 0.5. Inside the call `AiAttackWatch_InitFromAttack` ran twice:
the first (the attacker's own watch, no write) left 0.5, the second (the defender's watch) left 0.862 in the
field. On return of `StartAttack` the field read 0.5 again; player 2's `NPlayer::Military +0x1c` is 0.5.
`DispatchDefenders` was then called from `Fight::Update` (return address S 00571601) at tick 105,321 with
`soldierFraction` = 0.5. (Seven more `DispatchDefenders` calls in tick 105,311 came from
`AiAttack_EstimateStrengthRatio`, return address S 0059f355, with fractions 0.656..1.044; they are the AI's
strength estimate, not a dispatch.)
Conclusion: The value the AI writes in S 0059b3f0 (here 0.862) is overwritten by the copy of the player
setting in `StartAttack` before `DispatchDefenders` reads it; the defenders were dispatched with the player
setting 0.5. Agrees with `ai-player.md` §3.13 ("overwritten before it is used"). One attack observed.

### Settler release in state 0x24.
Status: PARTLY
What was done: observe-only hooks from tick 104,663 to 105,760 on `NSettlers::Worker::Update` S 0065d7f0
(workers whose state is 0x24 on entry: first tick, number of updates, state on leaving) and on
`NVillage::SettlerSpawn::SpawnSettlerOfGood` S 00564e00 (tick, spawn object, good id, return address). No
call, no write.
Measured: 18 stays in state 0x24, by 8 workers; every stay ended in state 0x23 (`Rest`). 13 stays lasted one
update (no release from that building in that tick), 5 lasted two updates, and each of those five has one
`SpawnSettlerOfGood` call with a return address inside `Worker::Update` (S 0065d52b, part of the function's
body 0065d4d0..0065d98c) in the first of its two ticks: spawn object 0x447f4910 at ticks 104,821 / 105,211 /
105,601 (worker 0x3f5ae038, one release every 390 ticks) and 0x447e8188 at ticks 105,038 / 105,428 (worker
0x406b75c8), good id 0xD4156A5F each time. Six further `SpawnSettlerOfGood` calls came from
`OrderSystem_SpawnSettlerForOrder` (return address S 00562572) and do not involve state 0x24.
Conclusion: A mode-4 worker releases one settler in the tick it is first updated in state 0x24 and stays in
0x24; on the next tick the building cannot supply another one and he goes to `Rest`. That is the sequence of
`settlers-jobs.md` §3.5 for a supply of exactly one. The case the question asks about (a supply of several, one
release per 10-tick cooldown while he stays in 0x24) did not occur in this save: no building had more than one
to release.

### Animal idle time and unexplored targets.
Status: CONTRADICTS SPEC (idle time); the hunter half was not observed
What was done: observe-only hook on `NResources::Animal::Update` S 005420c0 from tick 104,100 to 106,616
(367,060 calls). It recorded every change of `state` (`+0x88`) from 2 to 0 with tick, `timeStamp` (`+0x20`)
and the `counter` (`+0x8c`) the function had just written, and for the same animal the tick of the following
change from 0 to 1. Then the disassembly of the state-2 branch (0054231f..0054235e) was read. No call, no
write. Hook removed afterwards.
Measured: 400 arrivals recorded. 105 got `counter = 0`. For the other 295 the counter is
`(int)((tick/10 - timeStamp) * 3.0 * 10.0)`: 233 match exactly and 62 differ by 1 (float rounding of my
re-computation), none by more. Examples (walk ticks / counter / idle ticks until state 1): 15/45/46,
23/68/69, 43/128/129, 45/135/136, 67/200/201, 89/267/268, 134/402/403, 243/728/729. In all 400 cases the
animal stayed in state 0 for exactly `counter + 1` ticks. The property float at `+0x4c` (idle time factor) read
3.00 for all 39 animals sampled (movement speeds 0.030, 0.045, 0.070). The instructions: `FILD tick`,
`FLD 10.0` (double at S 007e2508, read live = 10), `FDIV ST1,ST0`, `FLD timeStamp`, `FSUBP ST2`, store and
reload as float32, `FMUL property[+0x4c]`, `FMULP` (by the 10.0 still on the stack), `ftol`.
Conclusion: Contradicts `map-resources.md` §3.10, state 2: "if it is the only animal on its cell
`counter = (int)(tick/10 - timeStamp)`". The value is `(int)((float32)(tick/10 - timeStamp) * idleTimeFactor *
10.0)`, i.e. with the shipped factor 3.0 the animal idles three times as many ticks as its walk took (plus
one tick), so a long walk is followed by a long idle, not a short one. The decompiled text drops the two
multiplications; the disassembly and the 400 measurements agree. Whether a hunter ignores an animal whose walk
target is unexplored was not observed (needs a hunter at the edge of the explored area).

### A command in an offline game runs at once. (open item of the first results list of 2026-10-12, not a queue entry of its own)
Status: PROVEN
What was done: CALL `nGame::System::SendCycleGameSpeedCommand()` S 00782950 (stdcall, no arguments; the
function the speed button calls) once at tick 107,071 on the main thread (one-shot hook on
`nGame::Autosave::Update` S 0078b040, thread 3016); `NComm_Manager +0x3c` (the speed) read directly before and
directly after the call, inside the same hook.
Measured: speed 1 before the call, 2 after it returned.
Conclusion: In an offline game the command (`0x20023`) is executed inside the game's own send function, before
it returns (`game-commands.md` §3.1). This was also the proof that order injection works in this session.

### Time of day.
Status: PROVEN
What was done: read the `S2CG::CEnviromentMgr` singleton (pointer at S 0088cf28, vftable S 007f9358):
`timeScale` `+0xf8`, `timeOfDayHours` `+0xfc`, `daytimeCount` `+0x100`, the nine 0x4c-byte keys at `+0x108`,
and the globals `g_Env_bAnimated` S 0088cf2c and `g_Env_LocalTime` S 00881248, at tick 103,213 and again at
tick 107,580 (about 7.5 minutes of play at speed 1, then speed 2 and 3). The game PC's `daytimes.xml` is the
encrypted original (not read as text here). No call, no write.
Measured: `timeOfDayHours` = 12.0 at both reads (exactly, no fraction); `timeScale` 0.033;
`g_Env_bAnimated` = 1 at both reads (so `Update` does not re-pin the hour each frame); `g_Env_LocalTime` = 12.
Nine keys, hours 0, 4, 6, 8, 12, 16, 18, 20, 22; every key: skydome 0, `+0x18` (elevation) = 50, `+0x1c`
(heading) = 50, shadow intensity 0.9, fog 100 / 200 except hour 12 with 10240 / 10240. (Earlier today:
`GetDaytime` S 00684a20 was not called once in 2,843 frames.)
Conclusion: The hour does not advance during a match: it stays at 12.0. Every loaded key has heading =
elevation = 50 although the file gives `lightheading="55"`, as `rendering.md` §6.6 derives from the misspelt
attribute name. Agrees with the spec (§10 Q11: the hour does not run; Q17: heading = elevation).

### Zoom distances and smoothing.
Status: PROVEN (with two deviations from the spec text, see the conclusion)
What was done: per-frame recorder on `nGame::Camera::Update` S 00787530 (after each update: zoom target
`+0x18`, zoom current `+0x20`, yaw target `+0x24`, yaw current `+0x28`, focus point `+0x40`, eye `+0x64`, look
direction `+0x70`, wall clock). CALLS, all from inside that hook on the main thread, 3 s apart (4 s for the
keys), `this` = the camera 0x0766b7d8: `nGame::Camera::OnWheelUp(this)` S 00786960 six times (zoom 6 -> 0),
`nGame::Camera::OnWheelDown(this)` S 00786a10 six times (0 -> 6), `nGame::Camera::HandleKeyDown(this, 0x2e)`
S 00787790 once (Delete, yaw target +1.5; returned true), `HandleKeyDown(this, 0x2d)` once (Insert, yaw target
back to 0; returned true). These are the functions the wheel and the two keys call. The view is back where it
was (zoom target 6, yaw target 0). Observe-only one-shot hooks on `MapCamera::GetEye` S 0067fae0 and
`GetTarget` S 0067fb00; read of the graphics device's camera pointer (`*(S 00886dd0) + 0x1b4`).
Measured:
- `zoomMax` (`+0x1c`) reads 6.0 in this install and the zoom target stood at 6.0; `distanceScale` 70.0.
- Distance eye-focus at rest for the steps 0..6: 0, 21, 42, 63, 84, 105, 126 world units (focus -104.25 / 9.9 /
  57.84 throughout). Look direction y at rest: -0.5 at step 0, -0.6 at step 1, -0.8 at steps 2..6.
- Zoom step: within 0.05 of the target after 950..985 ms in all twelve steps, although the frame count for that
  varied from 43 to 101 (the frame rate changed with the zoom, about 45 to 107 frames per second); the eye was
  within 0.01 units of its rest position after 2.35..2.41 s; `zoomCurrent` never became equal to the target
  within the 3 s (5.0001, 4.0001, ... on the way in; 0.9999, ... on the way out).
- Rotation: yaw within 5 % of the target after 11 frames in both directions (220 / 229 ms at about 50 frames
  per second); eye at rest (0.01 units) after 35 / 36 frames (675 / 766 ms).
- `MapCamera::GetEye` / `GetTarget` were not called once in more than 4,500 frames. The camera object at
  graphics device `+0x1b4` is the `nGame::Camera` itself (0x0766b7d8, vftable S 00835294): slot 2 = S 00784f70
  (`GetEyePos`), slot 3 = S 00784f90 (`GetLookAtPos` = eye + lookDir).
Conclusion: 21 world units per zoom step, the three tilt values and the easing rules agree with
`camera-input-cutscenes.md` §3.1/§3.2: the zoom easing is time based (about 0.96 s to 5 % at any frame rate,
`dt x 3.0`), the yaw easing is frame based (0.245 per frame: 11 frames to 5 %, so 0.18 s at 60 frames per
second and 0.22 s at the 50 measured here). Deviation 1: `zoomMax` is 6.0 in this install, not the 4.0 the
constructor sets ("`zoomMax` | 4.0 (constructor)"); something raises it (the install carries the "Widescreen
Fix"; the writer was not looked for). Deviation 2, for `audio.md` §3.2: "that the device camera is a
`MapCamera` is [inferred]" is wrong in a match; the device camera is the `nGame::Camera`, so `target - eye` is
the unit look direction (|d| = 1) and the listener sits at `eye + lookDir x 0.8 x (eye.y - terrain height)`,
i.e. 80 % of the eye's height above the ground along the view line, not "practically at the camera eye".
Side note for the ini entry: the game ran at up to 107 frames per second, so vsync was not limiting it to 60
(the monitor's refresh rate is not known to me).

### Emitter channel after scrolling away.
Status: PARTLY
What was done: observe-only hook on `SoundEmitterManager::StopChannel` S 0056d180; the manager's address
(0x0760d01c) taken from `this` of one `SoundEmitterManager::Update` S 0056d2e0 call; the sizes of its three
maps read every 250 ms for 21 s (emitter map `+0x0c`, channel map `+0x18`, soundId->channel map `+0x24`; the
maps start at `+0x04`, `+0x10`, `+0x1c`, each {proxy, head, size}). CALLS on the main thread, from a hook on
`nGame::Camera::Update`: `nGame::Camera::FocusOnCell(camera, {4, 4})` S 00785fe0 at +3 s and
`FocusOnCell(camera, {105, 105})` at +9 s (the map is 110 x 110; the function a jump to an object uses).
WRITE at +15 s: the camera's `focusPoint` x and z (`+0x40`, `+0x48`) set back to the values saved before
(-104.253, 57.842), which is what scrolling writes; the eye returned to its old place (-104.25 / 120.97 /
-1.66).
Measured: emitter map 8, channel map 2, soundId->channel map 2 for the whole 21 s, at the old place, at both
far corners (focus -306 / -283 and 303 / 242, each held 6 s) and after the return. `StopChannel` was not
called once.
Conclusion: The channel map did not grow and no channel was freed. That is what `audio.md` §3.4 steps 1 and
3 give for this map: the nearest list is not limited by distance, so with only two different sounds among the
eight emitters each sound's channel is always claimed by its nearest emitter and never reaches the fade-out
of step 4. The question itself (is an unclaimed channel freed after the fade) needs a map with more than four
different ambient sounds and was not answered here.

### Timer precision after a long uptime.
Status: NOT POSSIBLE UNATTENDED (the PC was booted today); one read done
What was done: read `g_Timer_CurrentMs` S 0088a620 once; last boot time of the game PC over SSH.
Measured: 29,043,767 ms = 8.07 h; the PC was booted at 11:10:02 today and the game started at 17:46:14, so
the counter counts from the boot, not from the program start. `Timer_GetTotalSeconds` S 0057b8a0 returns
`ms / 1000` on the x87 stack.
Conclusion: At this uptime a float32 copy of the value has a step of 1/512 s (0.002 s), far below a frame.
The step reaches 1/64 s (about one frame at 60 per second) at 131,072 s = 36.4 h of uptime and 1/32 s at
72.8 h; only readers that keep the value in a float32 are affected, a reader that keeps the x87 value is
not. Not observed, computed from the format.

### Products per resource cell.
Status: PROVEN (for amounts 1..7; the cap at 7 and the unlimited amount 1000 did not occur)
What was done: observe-only hooks from tick 103,926 (resource hook) / 106,320 (the other three) to 119,454 on
`MapModifier::ConsumeResourceAtCell` S 00674650 (cell, amount and type before and after, read from the
resource vector `*(this+0x1c)+0x10`), `NVillage::Production::OnProductionFinished` S 00565f80,
`FieldConnection::ConsumeFieldResource` S 0055c860 (its return value) and `Production::DeliverProducts`
S 00565990 (called or not inside the same `OnProductionFinished`). No call, no write.
Measured: 896 `ConsumeResourceAtCell` calls, all through `ConsumeAnyResourceAtCell` (return address
S 00674ea5). Steps seen: 7>6 110, 6>5 125, 5>4 134, 4>3 132, 3>2 121, 2>1 133, 1>0 141; every 1>0 step also
cleared the cell's type to -1. No cell held more than 7 and none held 1000. Mine cycles (488
`OnProductionFinished` calls of mines, players 0, 2, 3, 4): for the steps 7>6 .. 2>1 (403 cycles)
`ConsumeFieldResource` returned true and `DeliverProducts` was called once; for the step 1>0 (85 cycles) it
returned false and `DeliverProducts` was not called. Complete cells, e.g. (50,70) and (27,18): 7>6 6>5 5>4
4>3 3>2 2>1 1>0 = seven cycles, six products. (265 further `ConsumeFieldResource` calls came from
`NMovie::Working::Update`, outside `OnProductionFinished`; they are not mine cycles.)
Conclusion: A cell with amount `n` gives `n - 1` products to a mine: the cycle that takes the last unit
delivers nothing. Agrees with `village-buildings.md` §3.8.

### Mines without food.
Status: NOT POSSIBLE UNATTENDED (needs fresh games with start resources "high" and "medium"); one read done
What was done: read `Player.state` (`+0xec`) and `kind` (`+0x08`) of the eight player entries.
Measured: players 0..5: state 2 for all six (kinds 2, 1, 1, 1, 1, 1); the two unused entries also read 2.
Mines of players 0, 2, 3 and 4 completed cycles in this match (see the entry above).
Conclusion: This match was started with level 2 ("low"), where `Player_IsStateNotDefault` is true for the
human and for the computer players, so it cannot show a mine working without food.

### Ware delivered during an upgrade.
Status: PROVEN
What was done: observe-only hooks on `NVillage::Depot::CollectGoods` S 0055aca0 and, only while inside it, on
`NLogic::Stock::AddOne` S 00539de0 (the stock object of each call). ORDER at tick 116,509 on the main thread
(one-shot hook on S 0078b040): `NComm_Manager::QueueGameCommand(manager, event, false)` S 00408b10 with an
`NComm::EventInt64` built the way `nGame::System::SendStartUpgrade` S 00781470 builds it (vftable S 007d5ce8,
id 0x2000F, net id from `NComm_Manager::GetLocalNetId` S 004089a0 = 0xefffffcc, slot from
`NComm_Manager_FindLocalPlayerSlot` S 00408330 = 0, building unique 217067 / 0): the upgrade order for player
0's empty `GuardHouse` 0x44ab20e8 at cell (43,92). The sender itself was not called because it takes the
building from the HUD selection. The call returned true and `Upgrade.bActive` went from 0 to 1 inside it.
Measured: before the order, 1,176 `CollectGoods` calls of the match had one `AddOne` each. The upgrading
building (depot 0x44766760) then received 8 deliveries (ticks 117,306 to 117,746; goods 0xC5C945A3 three
times, 0x733F1E03 five times); each of the 8 calls made two `AddOne` calls, the first on 0x4fb7d260 (the
upgrade construction 0x4fb7d250 `+0x10`, its site stock) and the second on 0x4476676c (the depot's
`stockA`, `+0x0c`, the input stock). At tick 117,957 the site stock held 4 units (remaining work 0.794 / 0)
and `stockA` held 8. At tick 119,454 the upgrade was finished (type name "Tower", `bActive` 0, upgrade
construction pointer 0) and `stockA` still held 8 units, `stockB` 0.
Conclusion: During an upgrade every delivered ware is credited twice, to the upgrade's site stock and to the
building's input stock, as `village-buildings.md` §3.19 reads; the eight units stay in the finished tower's
input stock. Left in the game: that guard house is now a tower.

### Blocked flag.
Status: PARTLY (cadence and the message at 180 measured for street carriers; the return at 360 did not occur)
What was done: observe-only hooks from tick 114,570 on `Transport_CarrierTryPlacePackageOnFlag` S 0064dae0
(the carrier argument), `NTransport::Package::AddFlagFullWaitTick` S 006513b0 (per package: tick of every call,
the counter `+0x104`, class and state of the calling settler), from tick 119,020 also on
`PlayerMessages_SendOrRefreshToPlayer` S 005c0270 (only while inside S 0064dae0) and on
`GoToPackageTarget::IsFlagFullWaitExceeded` S 0077a0c0 (a true return). The game ran at speed 3; all times
below are ticks. No call, no write. The jams were those of computer player 2's road net.
Measured (until tick 122,472, about 8,000 ticks):
- Street carriers (vftable S 007f847c) in state 0x12: 15 packages with 100 or more attempts. Each waiting
  spell starts with a run of attempts on consecutive ticks (run lengths 13, 16, 18, 20, 27, 33, 42) and then
  continues with one attempt every 10th tick (3,108 intervals of 10 against 3,110 of 1 over all carrier
  packages). Three carriers in state 1 (no street) tried on every tick (runs of 90, 108 and 260).
- Workers (vftable S 007f84dc, states 0x20 and 0x35): one attempt per tick (2,500 of 2,500 intervals), as
  measured earlier today.
- `!flag blocked` (message kind 3): for carriers three times, each at the attempt that made the counter 180
  (package 0x2f5f8848: first attempt tick 119,183, 180th at tick 120,827, message in tick 120,827 = 1,644
  ticks after the first attempt; package 0x66763518: 119,801 -> 121,294 = 1,493 ticks; the third at tick
  120,875). For two workers the message came every 180 ticks (119,068, 119,248, 119,428, ...).
- No carrier package got beyond 261 attempts: every wait ended earlier (the good was put down), so
  `IsFlagFullWaitExceeded` never returned true and no good went back to a storehouse.
Conclusion: Agrees with `settlers-jobs.md` §3.6.2 as far as it was reached: a waiting street carrier tries
every 10th tick (after an initial run of 13 to 42 per-tick attempts that the spec does not mention), the
message comes at every 180th attempt, a worker tries every tick. At speed 1 the 180th attempt of a carrier
falls about 150 to 165 s after the first; the 360th would fall at about 5.5 minutes [computed, not observed].
The return of the good after 360 attempts is still open.

### Carrier swap at full flags.
Status: PARTLY
What was done: observe-only hooks from tick 121,670 to 122,472 on `NTransport::System::CanSwapPackagesAtFlag`
S 0064d120 and `FindSwapPackageAtStreetEnd` S 0064d750 (calls, results), together with the per-package wait
records of the entry above. No call, no write. The two-crossing-streets set-up itself was not built.
Measured: `CanSwapPackagesAtFlag` 18,590 calls, 15,878 returned true; `FindSwapPackageAtStreetEnd` 5,216
calls, 255 returned a package (players 0, 2 and 4 among the first six). The flag-full counters of
both packages read 0 at the recorded swaps. In player 2's jammed net every carrier's wait at a full flag
ended after at most 261 attempts (110 to 261 for the 15 longest), none reached the 360 limit.
Conclusion: Swaps at flags occur all the time in normal play and the jams seen here did resolve. The
carriers' street references every 200 ticks and the kind-0 ids of the end flags of two upgraded streets
(`streets-transport.md` §10 Q4) were not read.

### Ferry waiting time and hold.
Status: PROVEN (waiting time, hold above the limit); the stopwatch at speed 1 is replaced by tick counts
What was done: observe-only hook on `NavyCargo_LoadAtHarbor` S 005bd4e0 from tick 105,200 to 123,783 (4,883
calls, 120 complete stays of four ferries of players 0, 2 and 3). Per stay: first and last tick, the return
value of every call split by the phase test `(tick + ship id) % 3 == 0`, the package count of the hold
(`(cargo+0x10 - cargo+0x0c) / 0x20`) at entry, maximum and end, `ShipConfig.stockLimit` (`+0x18`) and the
ship's `stateCountdown` (`+0x2c`) after the last call. No call, no write.
Measured:
- Phase: all 2,990 calls on non-phase ticks returned true; a false return only ever came on a phase tick.
- A stay with nothing (or one thing) to load and a hold below the limit: 39 stays, 38 of them with exactly 17
  false returns, lasting 52 ticks (20 stays), 54 ticks (17) or 49 ticks (1); one with 18 false returns in 55
  ticks. The false returns of such a stay fall on ticks 3, 6, 9, ... 51 after its first call.
  `stateCountdown` read 16 after the last call.
- A full hold: 2 false returns (sometimes 3) and the ship leaves; `stateCountdown` 16 after the last call. One
  stay became full after 14 idle phase ticks: `stateCountdown` 30 at the end (14 + 16).
- `stockLimit` read 12 for every ship. The ferry of computer player 2 carried more than that from tick
  109,703 on: 13, 15, 16, 17, ... and 37 packages at tick 121,667 (53 consecutive stays with a hold above
  12); it kept loading at every stay (pk 33 -> 35 in one stay) and the hold kept growing over the 12,000
  ticks watched. The ferries of players 0 and 3 stayed at 0..8 packages.
Conclusion: The wait agrees with `navy.md` §3.7 (`waitTime` 15: the ship leaves on the 17th idle phase tick,
i.e. after 49 to 55 ticks = about 5 s at speed 1 when there is nothing to do; "worked" is reported on the two
skipped ticks of three). The queue entry's "about 3 x `waitTime` 40" is out of date; 15 is the value in use.
The hold does exceed `stockLimit`, as §3.9 infers, and by far more than "more than one": 37 packages against
a limit of 12, still growing. The spec sentence "The only bound is then the number of matching packages lying
on the flag, which the flag's 6 stacks limit" does not bound the hold over several stays: packages that
cannot be unloaded stay aboard and each stay adds more. Whether the destination flag of that ferry was full
was not read.

### S 00658df0 ever true.
Status: PROVEN for this session (still only "not seen")
What was done: read the counter of the hook set earlier today on S 00658df0 (`__b3.FightFlag658df0`).
Measured: 31,676 calls from tick 53,306 to 124,149, every one returned 0 (431 calls at the time of the third
batch). Several fights between computer players happened in that span.
Conclusion: The function was never true in about 70,000 ticks of this match.

### Demolish countdown.
Status: PARTLY
What was done: read the recorders of the hooks set earlier today on `Military::StartDestroyCountdown`
S 0055fc10 and `Military::NotifyDestruction` S 00560890 (`__b3`); from tick 120,835 own hooks on both and on
`NVillage::System::RemoveBuilding` S 00559db0 to get the removal tick. No call, no write; no building was
demolished by this session.
Measured: `StartDestroyCountdown` was called twice, at ticks 89,270 (`Military` 0x2bb9bf08) and 90,286
(`Military` 0x2bb9c408, a building of player 0: the same object had a `ReleaseSoldier` call at tick 86,162).
`NotifyDestruction` was not called once between tick 53,306 and tick 124,149. After tick 120,835 no further
countdown started, so no removal tick was captured.
Conclusion: Two countdowns ran to their end in this match and neither produced a `NotifyDestruction` call,
which fits `village-buildings.md` §3.5 ("after a normal 300-tick countdown the two messages are not
posted"). The length of the countdown and the removal tick against it were not measured; the paused
construction site was not tried.

### Door direction and levelling.
Status: PARTLY (direction from measured coordinates; nobody looked at the screen; levelling not observed)
What was done: no extra call; the two `nGame::Camera::FocusOnCell` calls of the emitter entry give the world
position of two cells (the function sets `focusPoint` = cell world position with z - 18), and the camera's
look direction at rest was read in the zoom entry.
Measured: cell (4,4) -> world x -306.0, z -265.0; cell (105,105) -> world x 303.0, z 259.8: 6.03 world units
per cell in x and 5.196 (= 6 x sin 60 deg) per row in z; cell x grows with world x and cell y grows with
world z. The camera's look direction at rest is (0, -0.8, 0.6), i.e. it looks towards +z.
Conclusion: Rows with a larger y are farther from the camera, so they are higher on the screen; if the
renderer is left-handed as Direct3D usually is (+x to the right when looking along +z with +y up; not
measured), direction 1 (dy = -1, dx = 0 or +1) is the lower right neighbour and direction 4, the door step
(dy = +1, dx = -1 or 0), is the upper left one, which fits the name `DoorOffsetNorthWest`. This needs one look
at the screen to confirm the handedness. The builder's levelling phase was not observed.

### Blocked flag. (addendum, ticks 122,472 to 125,653)
Status: PARTLY (as above)
What was done: the same hooks, read once more before they were removed.
Measured: a carrier of player 2 without a street (vftable S 007f847c, state 1, package 0x430834b0, good
0x7D610A43) tried on every tick from tick 123,410: counter 180 at tick 123,591 and 360 at tick 123,771, each
with a `!flag blocked` message in that tick, then 361, 362 ... up to 416 at tick 123,838, when the wait ended.
`IsFlagFullWaitExceeded` S 0077a0c0 did not return true once in the whole session. No street carrier (state
0x12) reached 360.
Conclusion: The 360 limit is not applied to a carrier in state 1: his counter ran to 416 and the good was
not handed to a storehouse. That fits the spec's statement that the limit sits in state 0x12 only
(`settlers-jobs.md` §3.6.2); the state-0x12 return itself remains unobserved.

### Ferry waiting time and hold. (addendum)
Measured: the hold of player 2's ferry had reached 39 packages when the hooks were removed (tick 126,500).

### Garrison slider during an attack order.
Status: NOT DONE (kept for last as instructed; then no longer possible)
What was done: nothing was called. Around tick 125,653 (19:20 on the game PC) the game stopped advancing:
the main thread sits in `S2CE::CGraphicDevice::WaitForDeviceRestore` S 004da170 (called from
`GraphicDevice_EnsureDeviceReady` S 004dab00), the Direct3D device is lost because another window has the
foreground on the game PC (`GetForegroundWindow` / `GetWindowTextA` read from the debugger: title
"? Sadkmod and sadklobby subrepositories"). The game ran for about 30 s once in between (ticks 125,653 to
126,500) and stopped again. While it stands still `IsGameHanging` is true and `QueueGameCommand` drops
commands: a `SendCycleGameSpeedCommand` call at tick 125,664 left the speed at 3.
Conclusion: Not measured. The other entry marked "May end the process" (second own ship to an occupied exit)
was not touched either.

### Entries of "A free game alone" not attempted, with the reason
- Enclosed planter; Carrier sent home while his street exists; Ship on another sea adopts a route; Founding
  and a lost expedition target; Two players' ships at one exit; One ship-building visit: each needs a set-up
  built by hand (placing buildings or routes at chosen places); passive hooks on
  `NMovie::ShipConstruct::Update` S 0077f9c0 and `NNavy::Expedition::Update` S 005b8ac0 ran from tick
  114,570 to 126,500 and recorded no call (no ship was built, no expedition ran).
- Waiting attackers without an enemy: the maintainer's note of today says the situation cannot be ordered.
- Cell demolish trigger; Script-moved NPC; Book reopened in quest view: campaign only.
- Floating-point control word in the scripts: marked "Needs permission"; needs a new game.
- Good exchange output; Heal with soldiers in a barracks: need a sacrifice ordered with the right stock.
- Info pages; Defeated player; Marker on attackable buildings; Loudness over distance; Reference
  screenshots: need a menu, eyes or ears.
- Save and load are checksum-neutral; Saves in special states; Property values after a reload: need a save,
  a load or a second game.
- Main menu group: only "Ini files behind a byte order mark" and "Timer precision" could be read in a match.
