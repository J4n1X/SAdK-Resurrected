# Live session queue

Checks for the next session at the game PC (Frida MCP `frida-sadk`, server log). Each entry settles one
statement that the docs carry as `[inferred]` or `[TODO]`. Addresses: `S` = sadk_noav.exe, `T` = tincat3.dll.
Hooks only observe unless an entry says otherwise. Entries marked **needs permission** write game memory or
change what the server sends, and need the maintainer's explicit go-ahead first (`HARNESS.md` §2).

## Standing notes (maintainer, 2026-10-12)

- Mail, buddy lists, whispers, the shops (they open and list their items) and per-match server mods work in live
  play; they need no check beyond the specific entries below.
- Accounts are created at the first login; the client's registration form is not used, because it needs a CD key
  many players no longer have. A failed login therefore means the name exists with another password.
- There is no third test player. Entries that need three players stay open and rest on static evidence.

## Lobby and account

- [x] **E-mail change (88).** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Change the e-mail address in the client.
  Observe: the 88 body in the server log: `property_mask` 8, `active` 1, `banned` 0, empty `name`.
  Settles: `docs/message-catalog.md` 0x058, T43 ("the client sends only mask 8" `[inferred]`).
- [x] **ChangeCharacter (90) is unused.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Play a full session: tailor, shop, logout.
  Observe: hook T 10016550, or watch the server log for message 90. A hit gives the caller and the mask.
  Settles: message-catalog 0x05A, T49 ("this client is not known to send 90" `[inferred]`).
- [x] **Mail `creation_time`.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Receive a mail, open the mailbox and the mail.
  Observe: read watch on `Mail+0x2c` of that mail. A hit names the reader; no hit means the field is unused.
  Also send two mails with very different `creation_time` values and look for any change in order or text.
  Settles: message-catalog 0x095 field 4 and T15 (unit `[TODO]`).
- [x] **Own whisper echo.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Whisper to a player whose name the client has not resolved yet.
  Observe: whether the own line appears in the chat.
  Settles: `docs/types.md` §1.5, `+0x54` (the echo is dropped when the target's name is not cached).
- [ ] **LobbyManager list `+0x34`.** Log in, enter the village, play a match, log out.
  Observe: hook `ObserverList_NotifyAll` S 00464300 and S 0045f620; log calls whose list pointer equals
  `g_pLobbyManager + 0x34`.
  Settles: types.md §1.2, `+0x34` (never fired; purpose `[TODO]`).
- [ ] **LobbyMessage `+0x38`.** One outgoing message (`SendPing` S 0046c150) and one incoming
  (`HandleMessage` S 00470a90).
  Observe: read watch on `msg+0x38`.
  Settles: types.md §1.8, `+0x38` (write-only `[inferred]`).

## Village and NPCs

- [x] **One-action NPC runs on selection.** Select a shop NPC (one action, 11).
  Observe: hook `DispatchSlotAction` S 00434230 (slot, code) and `SendOpenShop` S 0046ddf0: one call with
  slot 0 / code 11 on the selection frame, one 0x2E10 in the server log, and the selection ring back on the
  own avatar. If nothing is dispatched: read the base handler's result and CLobby vtbl+0x8c in S 00437760.
  Settles: `docs/village-and-character-protocol.md` §5.2 and §6.1 (auto-dispatch; the silent click of
  2026-08-02).
  **Result, live 2026-10-12:** selecting a trader set the action slots to `[11,0,0]`, `DispatchSlotAction(slot 0)` ran about 30 ms later and `SendOpenShop` returned 1 (NPC ids 1000009 and 1000001); the server logged OpenShop and answered 3601; the shop opened; the slots went back to `[8,9,0]`.

- [x] **Two-action NPC.** Select "Herold Hartmut" (list games + host game).
  Observe: no `DispatchSlotAction` call; whether any action button is visible; if one is, click it and watch
  the hook.
  Settles: village doc §5.2 ("no established way to run an action" `[inferred]`; what button vtbl+0x24(0)
  does `[TODO]`).
  **Result, live 2026-10-12:** selecting Herold Hartmut set the slots to `[9,8,0]`; no `DispatchSlotAction` call followed and nothing happened on screen (maintainer). A two-action NPC is not usable as it stands. Not observed: whether an action button was visible.

- [x] **Shop action in slot 0 plus a second action.** *(settled or narrowed by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* **Needs permission** (a changed NPC record). Send
  an NPC with `act` 11 in slot 0 and another action in slot 1; select it.
  Observe: whether 0x2E10 arrives.
  Settles: message-catalog 0xE10 (the hypothesis for the 2026-08-02 click).
- [x] **Matchmaker NPC.** Select the matchmaker.
  Observe: hook S 00434230 and `MiniGameMatchMakingDialog::Open` S 00444cb0. No dispatch: the stop is in
  S 00437760. Dispatch and `Open` run: the stop is inside the dialog (then hook CLobby vtbl+0xd4 S 004fad00).
  Settles: village doc §5.2, "the matchmaker NPC does nothing when clicked" `[TODO]`.
  **Result, live 2026-10-12:** selecting the matchmaker set the slots to `[3,0,0]`; `DispatchSlotAction(slot 0)` ran, then `CLobby::SetSelectionEnabled(0)` and `MiniGameMatchMakingDialog::Open(show 1, gameKind 1, tableIndex 255, mode 0)`; selection was enabled again 4 s later. The NPC spoke (maintainer). So the dialog is opened; the earlier "does nothing" does not hold for this NPC record.

- [x] **NPC speech.** Select NPCs with codes 2-6, 10, 11 and 7, 17.
  Observe: a speech bubble and the chat line `[name] ... : text` for the first group, nothing for the second.
  Settles: village doc §5.1 / §5.2 (`actChat` is a spoken line; `[known]` statically, not seen live).
  **Result, live 2026-10-12:** the traders (11), the matchmaker (3) and the hall of fame NPC (10) spoke; the tailor (17) and the others did not (maintainer). Matches the static reading.

- [x] **Re-sent 1004.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* **Needs permission** (an extra server message). Send a 1004 for an existing NPC
  id with a new position and label.
  Observe: whether the visible NPC moves or its label changes.
  Settles: village doc §5.1 ("whether a re-sent 1004 moves the visible NPC" `[TODO]`).
- [x] **1001 for the own id.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* **Needs permission** (an extra server message). Send the own client a
  1001 with Location + Style (changed colours).
  Observe: the look changes, the avatar neither moves nor vanishes, later messages still parse.
  Settles: village doc §4.1 (what the pushed movement sample does to the own avatar `[TODO]`).

## Shop

- [x] **Shop title.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Open both shops.
  Observe: how the `ShopName` text is shown (umlauts, a leading `!`).
  Settles: the open point on `ShopName` encoding in `mapping/work/protocol_gaps/stub_differences.md`.
- [x] **Sell price shown and credited.** Sell an item at the shop that lists it and one at the shop that
  does not (SellMod 0.9).
  Observe: the price in the confirm box (expected: stock Sell, and trunc(base value x 0.9)) and the gold
  credited afterwards.
  Settles: message-catalog 0xE24 and V30; the sell-price difference of the server.
  **Result, live 2026-10-12:** at the shop that lists it, the client computed 75 for item 23 (`GetShopSellPriceByItemId`; the stock's Sell value, 150 // 2) and the server credited 67 (x 0.9 on top). The server now credits the stock's Sell value for a listed item, else base price x SellMod (`lobby/sadk_lobby/economy.py`, effective at the next server restart). Not observed: an item sold at a shop that does not list it.

- [ ] **Cannot-sell box.** **Needs permission** (a changed stock entry). Send a stock entry with Sell 0 and
  try to sell that item.
  Observe: which box appears (`!LOBBY_TRADER_NOT_WANTS_ITEM` expected).
  Settles: message-catalog 0xE24 (price 0 branch).
- [ ] **Unknown item id.** **Needs permission** (server sends an id outside 1..36; may crash the client).
  (a) 3102 with `itmid` 999 in an active slot: is anything attached, does the client survive.
  (b) an id > 36 in a backpack slot, open a shop, hover that slot.
  Settles: message-catalog V23 (whether the checked-iterator path in S 0046d6d0 ends the process; how an
  unknown id renders on an avatar).
- [ ] **ItemsClient.txt tokens 3 and 4.** Stack, split, equip and sell items.
  Observe: read watches on `ItemInfo+0x3c` and `+0x44` of one item.
  Settles: village doc §4.3 (meaning of tokens 3 and 4 `[TODO]`).

## Pre-game room and match start

- [x] **Avatar fields in the slot.** Join a room with a known avatar (tribe, gender, level, colours).
  Observe: read the slot's `+0x41`, `+0x43`, `+0x47` and compare with the avatar.
  Settles: `docs/NCOMM_GAME_PROTOCOL.md` slot table (nibble order of `+0x41`, body part per `+0x43` nibble).
  **Result, live 2026-10-12:** host's slot `+0x41` = `0x0105`, `+0x43` = `0x2E918519`, `+0x47` = 100000; the avatar in the
  server's save: body 1, gender 0, level 5, colours `[9,1,5,8,1,9,14,2]`. So `+0x41` is body << 8 | gender << 4 | level,
  and `+0x43` holds the eight colours low nibble first in the save's order (hair, skin, shirt, trousers, addColor1..4);
  `+0x47` is the avatar id (= perm id).

- [x] **Map type values.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Host once with a stock map and once with a user map from My Documents.
  Observe: read session `+0x229` (and `MapInfo+0x1d0`) on the host.
  Settles: types.md §2.2, `+0x229` (names of the type values `[TODO]`).
  **Partly done, live 2026-10-12:** hosting two stock maps (a 2-player map, then `MP_4P_butterfly_isle`) gave session
  `+0x229` = 3 and `+0x228` = 1 both times, with the assetshare mod active (it may set `+0x228` itself). Still to do: a
  custom map from the Documents folder, and the same without assetshare.

- [ ] **Map fetch branch.** **Needs permission** (writes game memory on the host). With a user map the
  joiner lacks, set session `+0x228` to 1 on the host.
  Observe: on the joiner, `RequestFileFromHost` S 004084d0 runs and the `.s2m` / `.bmp` arrive instead of
  the kick.
  Settles: types.md §2.2, `+0x228` (name `[inferred]`).
- [x] **Random teams.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Start a match with a slot whose team is unset.
  Observe: slot `+0x3f` on the host's own session and on a joiner after StartLoading.
  Settles: NCOMM doc, team note (whether the host's session receives the random values `[TODO]`).
- [ ] **Which seed a client uses.** Start a two-player match.
  Observe: on each client, session `+0x22f` at the `GetGameSeed` call S 00775e1f and the values passed to
  `LogicChest_SetContentKind` S 00539200.
  Settles: `docs/MATCH_START.md`, Open item 2 (does the host's payload replace a client's seed before its
  chest pass).
- [ ] **Different seeds.** **Needs permission** (the server sends each client another GameSeed). Repeat the
  entry above, then open a chest.
  Observe: chest `+0x28` values on both sides; `ChecksumLog::VerifyLatest` S 00415a60 for a mismatch.
  Settles: MATCH_START Open item 2 and message-catalog H17 (desync or only different chest contents).

## In match

- [x] **Left-game notice.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Three players; one leaves mid-match.
  Observe: on a non-host, hook `SetField4B` S 00414e80 and the getter S 0046b5f0: the byte before and after,
  and that the notice appears exactly once.
  Settles: NCOMM doc slot `+0x4b` (`[inferred]`; its value on a non-host `[TODO]`).

## Wager dialog (added 2026-10-12)

- [x] **Wager is stored in the session.** Live 2026-10-12: the host set a wager through the bet button; session `+0x233`
  read 100356 with the host's gold (`AvatarProxy +0xd0`) at 100357, and `settingsCrc` (`+0x237`) changed with the map and
  the wager. Not settled: whether the dialog stops at the host's own gold (static: its maximum is that value); the
  maintainer's impression was "unlimited", with a balance of about 100,000.
- [ ] **Team of a seat.** A team cannot be chosen while the host is alone in the room (maintainer, 2026-10-12), so the
  random-team check needs a second player.
- [x] **A wagered match, one player gives up.** Live 2026-10-12, match 100, wager 357: player 100000 gave up (`GiveUpGame`,
  re-sent three times within 5 ms and answered each time); 1.8 s later the remaining player's game sent `FinishGame`
  naming itself (100001), so a give-up in a two-player match makes the other player's game declare victory; the server
  moved 357 gold from 100000 to 100001 and kept both notices for the next village entry. The match lasted under two
  minutes, so no XP or reward gold was given.

## From the specifications (docs/sim)

Entries per group: main menu and settings 9; free game alone 57; lobby village alone 12; pre-game room 7; network
match with two players 12; three or more players 3; map editor and developer tools 5. Total 105.
One player alone: 85 (groups 1 to 3, three of the pre-game room, four of the tools).
A second player is needed for 17 (four in the pre-game room, the twelve of the network match, the LAN test).
Three players are needed for 3; they stay open and rest on static evidence.
**Needs permission**: 10 (one free game, three village, one pre-game room, one network match, four tools).

Sources: §10 of every `docs/sim/*.md` (§11 in `minigames-client.md`) and the body statements that name an
observation. Already covered by entries above and not repeated: `lobby-client-state.md` §10 Q5 (`LM+0x34`) and Q9
(`ItemsClient.txt` tokens), `lobby-screens.md` §10 Q7 (NPC actions), `players-victory.md` §10 Q3 (number of
`GiveUpGame` messages: three within 5 ms, wager result above).

### Main menu and settings

- [ ] **Ini files behind a byte order mark.** Start the game with the install's `network.ini` and `engine.ini`
  as they are; then switch `useMeshCache` in `engine.ini` and start again.
  Observe: the `network.ini` block at manager `+0x360` (`g_NCommManager` S 00885754): `gamePort` 5478 = the file
  was read, 5479 = fallback because the mark hides the first section. For `engine.ini`: whether `.mshraw` files
  appear or stop appearing with the switch.
  Settles: `network-session.md` §6 and §10 Q8; `lan-and-transport.md` §10 (effective `gamePort`);
  `formats-inventory.md` §10 Q9.
- [x] **Closed row on a taken start position.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Set up a free game in which a closed row's number equals the
  start position chosen by another row; start it.
  Observe: which player stands on that position and whether one is missing (expected: the later row's write
  wins, the copy loop does not skip closed rows).
  Settles: `frontend-screens.md` §3.4, §10 Q1.
- [x] **Stale click latch.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Click a button whose owner does not poll it, later press on it and release outside.
  Observe: hook `nUi::Button::OnClicked` S 004b12d0 and `Widget_ReadClearClickLatch` S 0049fdb0: a call of
  `OnClicked` on the outside release = the latch is stale; none = not visible in play.
  Settles: `ui-toolkit.md` §3.4, §10 Q1.
- [ ] **Activate-main latch and Info gate.** Use the main menu and drag a dialog by its title bar.
  Observe: write watches on `Main +0x228` and `Overlapped +0xbfc`: no write = both are dead; a write names the
  writer.
  Settles: `frontend-screens.md` §2.1, §3.11, §10 Q4.
- [x] **`-nolobby` and the lobby button.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Start with `-nolobby` and press the lobby button.
  Observe: `g_App +0xaa` = 1 and `+0x88` = NULL; what the screen does (expected: the request flag is set and
  never consumed, nothing happens).
  Settles: `app-shell.md` §10 Q9.
- [x] **File name with an upper-case umlaut.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Put a user map with an upper-case umlaut in its name into the
  maps folder and open the map list.
  Observe: whether the map is listed and loads (the name key keeps the umlaut under the "C" locale; under
  another active locale it is folded and found).
  Settles: `engine-core.md` §10 Q3.
- [x] **Timer precision after a long uptime.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Leave the PC running for several days, then start the game.
  Observe: hook `Timer_GetTotalSeconds` S 0057b8a0 and log the return value of consecutive frames: equal values
  or steps much larger than a frame = precision is lost.
  Settles: `app-shell.md` §10 Q10.
- [ ] **Widget drawing details.** Look at a tiled frame whose size is no multiple of the tile, at an edit box
  caret, and at a boxed text with a narrow wrap width.
  Observe (screenshots): last partial tile squeezed or cropped; caret colour; a stale glyph where a break
  candidate overflows the line.
  Settles: `ui-toolkit.md` §10 Q4, Q5 (§3.1).
- [ ] **Loop of the main theme.** Listen to `maintheme.ogg` across its loop point.
  Observe: the music restarts (normal loop) or plays backwards (`FSOUND_LOOP_BIDI` taken literally).
  Settles: `audio.md` §3.1 (line on `FSOUND_LOOP_BIDI`), §10 Q4.

### A free game alone

#### Economy and buildings

- [x] **Mines without food.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Free game, start resources "high", one computer player; build a mine and deliver
  no food. Repeat once with "medium".
  Observe: `Player.state` of both players (0 = high) and whether each mine produces: expected human at "high"
  yes, computer player only at level 3, "medium" no.
  Settles: `players-victory.md` §3.4, §10 Q4; `village-buildings.md` §3.8, §10 Q1.
- [x] **Products per resource cell.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Let a mine empty one cell of known amount and count its products.
  Observe: hook `ConsumeResourceAtCell` S 00674650: the amount after each call (`min(7, amount - 1)`, 1000 left
  alone) and the number of products: `n - 1` for amount `n` as read, or `n`.
  Settles: `village-buildings.md` §3.8, §10 Q10.
- [x] **Ware delivered during an upgrade.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Upgrade a guard house and watch its stock when the materials arrive.
  Observe: hook `Depot::CollectGoods` S 0055aca0; compare the upgrade stock and the building's stock before and
  after one delivery (expected: both grow by one).
  Settles: `village-buildings.md` §3.19, §10 Q8.
- [x] **Demolish countdown.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Demolish a military building; separately pause a construction site and leave it.
  Observe: hook `StartDestroyCountdown` S 0055fc10 and `Military::NotifyDestruction` S 00560890: the countdown
  (300 ticks), whether the two messages appear after a normal countdown, and the tick of the removal against the
  tick of the messages. The paused site: whether it ever disappears by itself.
  Settles: `village-buildings.md` §3.5, §3.4, §10 Q7; `game-commands.md` §10 (removal tick).
- [x] **Enclosed planter.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Build a forester whose reachable area is small (water or buildings around it).
  Observe: whether he ever plants (expected: never, the search result is dropped when the flood fill runs out).
  Settles: `map-resources.md` §3.9, §10 Q1.
- [x] **Aborted hunt.** *(settled, results of 2026-10-12 at the end of this file)* Destroy a hunter's hut while the hunter walks to an animal; watch the animal.
  Observe: hook `VillageLink_UnlinkHuntedAnimal` S 0053c580 and read the animal's state in `Animal::Update`
  S 005420c0: stays 4 and stands still for the rest of the match, or walks again.
  Settles: `map-resources.md` §3.10 step 6, §10 Q2.
- [x] **Animal idle time and unexplored targets.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Watch animals after long and short walks, and a hunter at the
  edge of the explored area.
  Observe: idle ticks after a walk in `Animal::Update` S 005420c0 (short idle after long walks as read); whether
  the hunter ignores an animal on explored ground whose walk target is unexplored.
  Settles: `map-resources.md` §3.10, §10 Q3, Q4.
- [ ] **Door direction and levelling.** Place a farm on uneven ground and watch the builder and the door.
  Observe: which screen direction the door step (direction 4, `DoorOffsetNorthWest`) is, whether direction 1 is
  the lower right neighbour, and whether the builder plays a levelling phase (expected: levelling is
  instantaneous, `cfg_setBulldozeTime` unused).
  Settles: `village-buildings.md` §10 Q2, Q3; `settlers-jobs.md` §10 Q6.

#### Settlers and transport

- [x] **Walk and pick-up timing.** *(measured unattended, 2026-10-12: `docs/live-checks/2026-10-12_unattended-run.md`)* Watch one carrier on a flat street at speed 1.
  Observe: hook `Settler::Update` S 00656ec0 for that settler: updates per second (10 at the 0.1 s tick),
  updates per cell (about 17.2 with the carry-over, so 17 and 18 mixed), and the 4-tick pick-up phases.
  Settles: `settlers-jobs.md` §3 (movement), §10 Q2; `game-commands.md` (logic tick interval 0.1 s).
- [ ] **Settler release in state 0x24.** Supply a casern or an oxen breeder continuously.
  Observe: the worker's state in S 0065d7f0 (stays 0x24 until the supply ends) and the settlers released per 10
  ticks.
  Settles: `settlers-jobs.md` §10 Q1.
- [ ] **Blocked flag.** Block a flag so that a loaded carrier cannot put his good down.
  Observe: hook S 006513b0 (the attempt counter `pkg +0x104`): attempts per tick, `!flag blocked` at every 180th
  attempt, the good's return to a storehouse after 360; the real time of both.
  Settles: `settlers-jobs.md` §3.6.2, §10 Q5.
- [ ] **Carrier swap at full flags.** Two crossing streets with full flags.
  Observe: hook `CanSwapPackagesAtFlag` S 0064d120 and `FindSwapPackageAtStreetEnd` S 0064d750; the two
  carriers' street references every 200 ticks; whether the jam resolves. On two upgraded streets that both lost
  their first carrier: the end flags' kind-0 ids afterwards.
  Settles: `settlers-jobs.md` §3.6.2, §10 Q4; `streets-transport.md` §3.5, §10 Q4.
- [x] **Carrier sent home while his street exists.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Push a street carrier off his street (a building placed
  next to it); do the same on an upgraded street.
  Observe: hook `Carrier::Update` S 0065b710 (the call of `StopAndSetState3`); the street's carrier slot until
  he has entered a building: no new order before that (as read) or a replacement at once. Upgraded street: does
  the pack animal go on alone.
  Settles: `streets-transport.md` §3.8 "Losing the job", §3.7, §10 Q1, Q2.
- [x] **Product on a full flag.** *(settled, results of 2026-10-12 at the end of this file)* Let a workshop's flag fill up to 12 packages while it keeps producing.
  Observe: hook `FlagPackageStacks::AddPackage` S 0066b730 (its result) for the worker's product: refused and
  kept, or attached without a stack; where that package is afterwards.
  Settles: `streets-transport.md` §3.9, §10 Q3.

#### Military

- [x] **Occupied building with wanted size 0.** *(settled; the border is open, results of 2026-10-12 at the end of this file)* Build a guard house far from any enemy and leave the sliders at
  their defaults.
  Observe: hook `Military_GetDesiredGarrisonSize` S 00574980 (returns 0 once occupied) and `ReleaseSoldier`
  S 0055fc40: all soldiers leave and the border stays, or one soldier stays.
  Settles: `military.md` §3.2, §10 Q1.
- [x] **Garrison slider during an attack order.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Lower the garrison slider while that building's soldiers wait
  to leave for an attack. May end the process.
  Observe: hook `Soldiers::GetSoldierObject` S 00566140 for index -1: the process terminates (CRT handler) or
  goes on with the entry before the garrison vector.
  Settles: `military.md` §3.2, §10 Q4.
- [x] **Waiting attackers without an enemy.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Attack with more soldiers than can engage; let the defenders die.
  Observe: whether the waiting soldiers (state 0xf) give up, and who captures the undefended building.
  Settles: `military.md` §10 Q8.
- [x] **S 00658df0 ever true.** *(measured unattended, 2026-10-12: `docs/live-checks/2026-10-12_unattended-run.md`)* Play through several fights.
  Observe: hook S 00658df0: any non-zero return, with the soldier's kind and settler type.
  Settles: `military.md` §3.3, §10 Q2.

#### Navy

- [x] **Second own ship to an occupied exit.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Leave the ferry docked, then order a sea attack through the same
  harbour. May end the process.
  Observe: a crash at S 0053a540 with `this` = 8 (the null write as read), or the ship waits.
  Settles: `navy.md` §3.1 rule 3, §10 Q3.
- [x] **Ferry waiting time and hold.** *(measured unattended, 2026-10-12: `docs/live-checks/2026-10-12_unattended-run.md`)* Time a ferry at a harbour with goods; repeat at a harbour flag that is
  full.
  Observe: hook `NavyCargo_LoadAtHarbor` S 005bd4e0: ticks waited (about 3 x `waitTime` 40 as read) and the
  package count against `stockLimit` 12.
  Settles: `navy.md` §3.9, §10 Q9, Q12.
- [x] **One ship-building visit.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Watch a ship being built.
  Observe: ticks between two fetches of the constructor (31 ticks of hammering per visit as read; strokes =
  `(int)constructTime`, 50).
  Settles: `navy.md` §3.3, §10 Q11.
- [x] **Ship on another sea adopts a route.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Map with two seas: keep an idle ship on the sea without the route,
  then create an own-to-own route on the other sea.
  Observe: the ship's first step (a straight line over land as read) and whether it exchanges cargo from a
  distance (harbour flag stacks and hold).
  Settles: `navy.md` §3.4, §10 Q4, Q5.
- [x] **Founding and a lost expedition target.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Found a colony; in a second run lose the target harbour while
  the ship is under way.
  Observe: hook the founding step S 005b8ac0: the harbour flag exists in the same tick; the ship's state (7 or
  8) and what it does when the target's owner changes.
  Settles: `navy.md` §3.10 step 3, §10 Q7, Q10.
- [x] **Two players' ships at one exit.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* A route shared with a computer player through an exit with two docks.
  Observe: whether both ships wait in state 1 and block each other.
  Settles: `navy.md` §10 Q8.
- [x] **Batch-editing byte in a match.** *(settled, results of 2026-10-12 at the end of this file)* Start a free game and build a ship.
  Observe: hook `NLogic::Edit::SetBatchEditing` S 00538a60 (no call expected) and read `Edit +4` and `+5..+7`
  (all 0 expected).
  Settles: `navy.md` §3.2, §10 Q1; `map-editor-devtools.md` §10 Q4, Q5.

#### Computer player

- [x] **Cadence of the modules.** *(settled for five modules, results of 2026-10-12 at the end of this file)* Free game against one computer player, 30 minutes.
  Observe: call times of `NAI::System::Tick` S 00581a30, `MilitaryLimiter::Update` S 00597c80,
  `AttackExecution::Update` S 005a0dd0, `LockSmith::Update` S 0058d130 and `AiStreetPlan::PlanPath` S 005a96b0
  against the intervals of `ai-player.md` §3 (attack cadence, build order, free tool, randomised street routes).
  Settles: `ai-player.md` §10 Q1.
- [x] **Defence fraction of an attacked computer player.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Attack a computer player once.
  Observe: the value written in S 0059b3f0, the copy in S 00576500 and the value `DispatchDefenders` S 00576400
  reads: the AI's value, or the player setting that replaced it.
  Settles: `ai-player.md` §3.13, §10 Q2.
- [x] **Cell demolish trigger.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Load each campaign save.
  Observe: read `Cell +0xe8` of every AI cell: 0 everywhere = the trigger is never armed.
  Settles: `ai-player.md` §2.3, §10 Q3.

#### Sacrifices, quests and scripts

- [ ] **Floating-point control word in the scripts.** **Needs permission** (calls the runtime's
  `_controlfp(0, 0)` from the hooks; it only reads). Start a new game.
  Observe: the control word in a hook of S 0054f8d0 (property scripts) and of S 005b2220 (`onStarted`):
  the value `Fpu_SetDefaultControlWord` S 0057b9b0 sets, or another one.
  Settles: `lua-runtime.md` §8, §10 Q1.
- [x] **Good exchange output.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Run a good exchange sacrifice and watch the building.
  Observe: by which carriers the output stock leaves and when the building's state 0 ends.
  Settles: `quests-sacrifices-stats.md` §10 Q4.
- [x] **Heal with soldiers in a barracks.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Keep wounded soldiers stocked in a barracks and make the heal
  sacrifice (effect 1003).
  Observe: hook S 00660270 (the cleared map of remembered life points) and the soldiers' life points when they
  leave.
  Settles: `quests-sacrifices-stats.md` §10 Q7.
- [x] **Script-moved NPC.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Play a campaign mission whose script moves an NPC.
  Observe: hook `se_moveNPCTo` S 005ae3b0 and read the NPC's state: 0x2f, then 0x29 with a walk to the target
  (the fall-through into the state-0x12 rule), when the NPC stood off-centre at the call.
  Settles: `settlers-jobs.md` §3.10, §10 Q3.
- [x] **Info pages.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Open the info popups of several buildings and goods.
  Observe: hook `nMenu::Info::Open` S 005f6310 (mode: 0 expected) and `GameScript_RunFile` S 005b1dc0 (no call
  for `scripts\info\*.lua` expected).
  Settles: `lua-runtime.md` §6.1, §10 Q4.
- [x] **Book reopened in quest view.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* In a campaign mission close the book while the quest list is shown, then
  open it again.
  Observe: what the book shows (page widgets, quest widgets or both).
  Settles: `lua-runtime.md` §4.3, §10 Q7.

#### HUD and statistics

- [x] **Pause and commands offline.** *(settled, results of 2026-10-12 at the end of this file)* Pause a free game for more than two seconds and give a build order.
  Observe: hook `IsGameHanging` S 00408860 and `GetHangReason` S 0040d260: true with a hang notice and the
  command dropped (S 00408b10 returns false), or nothing of that.
  Settles: `logic-core.md` §3.2, §10 Q11.
- [x] **Leaving an offline match.** *(settled, results of 2026-10-12 at the end of this file)* Leave a free game through the menu.
  Observe: hook `HandleCommand_2002B` S 00782910: no call and no castle removed expected.
  Settles: `players-victory.md` §3.8, §10 Q2.
- [ ] **Defeated player.** Lose a free game and stay on the `Defeat` dialog.
  Observe: whether camera and selection still work and whether the explored area changes.
  Settles: `hud-panels.md` §3.10, §10 Q4.
- [x] **Win and loss jingles.** *(settled: neither is played, results of 2026-10-12 at the end of this file)* Finish one free game won and one lost.
  Observe: hook `nMenu::System::PlayMusic` S 005d9f60: an index 2 (`music_won`) or 3 (`music_lost`) = played;
  only 0, 1, 4, 5, 6 = never started.
  Settles: `audio.md` §10 Q3.
- [x] **Tech tree tab.** *(settled, results of 2026-10-12 at the end of this file)* Open the fourth tab of the statistics panel.
  Observe: laid out and switched like the other three, with `techtree<TribeName>` of the own tribe.
  Settles: `hud-panels.md` §2.1, §10 Q3.
- [x] **Players graph in the first minute.** *(settled, results of 2026-10-12 at the end of this file)* Open the players graph right after the start.
  Observe: empty or useless while every player has at most one sample.
  Settles: `hud-panels.md` §10 Q6.
- [ ] **Marker on attackable buildings.** Look at enemy military buildings in reach and out of reach.
  Observe: any marker of its own besides the selection and the attack slider.
  Settles: `hud-panels.md` §3.6.2, §10 Q5.
- [x] **Info-map overlay.** *(settled, results of 2026-10-12 at the end of this file)* Toggle the info map (space).
  Observe: which overlays stay and which go, besides the 0.2 s colour fade.
  Settles: `ingame-ui.md` §10 Q5.
- [x] **Hotkeys with Caps Lock or Shift.** *(settled, results of 2026-10-12 at the end of this file)* Press the game hotkeys with Caps Lock on, then with Shift held.
  Observe: hook `nUi::Object::HandleHotkey` S 0049ffc0: the hotkeys fail (character-code comparison) or work.
  Settles: `ingame-ui.md` §10 Q7.
- [x] **Player colours.** *(settled for the component order, results of 2026-10-12 at the end of this file)* Free game with eight players.
  Observe: read the eight entries at S 0087ead8 and compare with the colours on screen: the component order is
  red, green, blue, alpha, the values are those of `menu.cfg`.
  Settles: `players-victory.md` §2.2, §10 Q5.
- [x] **Debug icons.** *(measured unattended, 2026-10-12: `docs/live-checks/2026-10-12_unattended-run.md`)* Any running game.
  Observe: read the visible byte of the five icons `SetupHud` creates: hidden for the whole match expected.
  Settles: `camera-input-cutscenes.md` §3.13, §10 Q1.

#### Camera and input

- [x] **Zoom distances and smoothing.** *(measured unattended, 2026-10-12: `docs/live-checks/2026-10-12_unattended-run.md`)* Step through all zoom levels and rotate once, with vsync on.
  Observe: `MapCamera::GetEye` S 0067fae0 and `GetTarget` S 0067fb00 at each step (21 units x step as read) and
  the number of frames a zoom step and a rotation take to settle.
  Settles: `camera-input-cutscenes.md` §10 Q2; `audio.md` §3.2, §10 Q2.

#### Audio

- [x] **Emitter channel after scrolling away.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Scroll from a sounding building far away and back.
  Observe: hook S 0056d180 or read the size of the channel map (`SoundEmitterManager +0x10`): the channel is
  freed after the fade, or the map only grows.
  Settles: `audio.md` §3.4 step 4, §10 Q1.
- [ ] **Loudness over distance.** Record one building sound at several camera distances.
  Observe: the level curve of the recording.
  Settles: `audio.md` §10 Q10.

#### Rendering

- [x] **Time of day.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Play 30 minutes on one map.
  Observe: hook `CEnviromentMgr::Update` S 00683d50 and `GetDaytime` S 00684a20: whether the hour advances;
  read `DaytimeKey +0x1c` of a loaded key (heading = elevation as derived).
  Settles: `rendering.md` §6.6, §10 Q11, Q17.
- [ ] **Reference screenshots.** Take: a shore at shader level 2; settlers at shadow levels 1 to 3; the sky; one
  walking settler from close up.
  Observe: the look of shallow water; a blob shadow under settlers (none expected); sun and moon (never drawn
  expected); the settler's facing and face winding for comparison with a converted model.
  Settles: `rendering.md` §10 Q15; `world-objects-rendering.md` §3.9, §10 Q4, Q6; `animation-models.md` §10
  Q1, Q2.

#### Saving and loading

- [ ] **Save and load are checksum-neutral.** Free game without input: save at tick N and let it run 50 ticks;
  load the save and let it run the same 50 ticks.
  Observe: hook `nGame::System::ComputeChecksum` S 00784080 and log tick and checksum in both runs: equal =
  neutral.
  Settles: `save-format.md` §8, §10 Q2.
- [ ] **Saves in special states.** Save during a cutscene, during a pause and during a sacrifice animation;
  load each.
  Observe: whether the save dialog opens at all while the cinematic screen is up; the first ticks after each
  load.
  Settles: `save-format.md` §10 Q3; `camera-input-cutscenes.md` §7, §10 Q5.
- [x] **Autosave during a pause.** *(pause half settled; cinematic half open, results of 2026-10-12 at the end of this file)* Set the interval to 5 minutes, pause for longer; repeat across a cinematic.
  Observe: hook `nGame::Autosave::Update` S 0078b040; the `!Autosave...` message and the file time of
  `Autosave.aav` (fires while paused, not during a cinematic, as read).
  Settles: `save-format.md` §10 Q4.
- [x] **Overwrite after a delete prompt.** *(settled, results of 2026-10-12 at the end of this file)* In one save panel press Delete and answer No, then save over an
  existing name and answer Yes.
  Observe: hook `LoadSavePanel::Confirm` S 0060d000 and the box answer S 0060d5b0: the marked `.aav` is deleted
  (pending action still 1) or the save is written.
  Settles: `frontend-screens.md` §3.6, §10 Q2.
- [x] **Unfinished street in a save.** *(settled, results of 2026-10-12 at the end of this file)* Save while a street is being placed, then load.
  Observe: whether a street stub remains at the start flag (expected: removed on load).
  Settles: `game-commands.md` §7, §10.
- [x] **Save after a win.** *(settled, results of 2026-10-12 at the end of this file)* Win, save, load that save.
  Observe: whether the victory screen appears again (and, online, a second `FinishGame` in the server log).
  Settles: `players-victory.md` §7, §10 Q8.
- [ ] **Property values after a reload.** Play two free games in one program run.
  Observe: read a few good, building and settler records in each game and compare the values, not only the
  record counts.
  Settles: `properties-data.md` §10 Q5.

### The lobby village alone

- [ ] **Lists that never fire.** Log in, enter the village, leave it, host a game, lose the connection.
  Observe: hook the subscriber S 005037a0 (`VSC+0x110`) and `ObserverList_NotifyAll` S 00464300 for the lists
  `VSC+0x50`, `+0x5c`, `+0x110`, `+0x14c`: any call names the firing code. Do it with the `LM+0x34` entry above.
  Settles: `lobby-client-state.md` §10 Q5; `lobby-world-client.md` §10 Q16.
- [x] **Shop result and inventory lists.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Buy and sell one item.
  Observe: in the handlers S 00470990 and S 00470a10 read the subscriber count of `VSC+0x134` and `+0x140`, and
  of `VSC+0xd4` on the inventory change: 0 = the client shows nothing on a result.
  Settles: `lobby-client-state.md` §10 Q3; `lobby-screens.md` §10 Q4.
- [ ] **Controller hit report.** Walk into a wall and into a fence. May end the process.
  Observe: hook `__purecall` S 006f371b: a call (the process aborts) = the library calls the report.
  Settles: `lobby-extras.md` §3.3, §10 Q1.
- [ ] **Limits of the walkable area.** Walk along the inner walls, to the map edge and up the steepest slope.
  Observe: the avatar's position: whether it passes ±125 or sinks below the meshes; the steepest slope it climbs
  (60 degrees as read).
  Settles: `lobby-extras.md` §6.2, §10 Q5, Q10.
- [ ] **What starts observing.** Walk up to a minigame table that others could use, and sit down.
  Observe: hook `SetObserving` S 005238e0: any call with its caller.
  Settles: `minigames-client.md` §3.6, §11 Q1.
- [ ] **Top-up maximum.** Sit at a Dice table with a known amount of gold and open the stake dialog.
  Observe: hook `OpenSetStackDialog` S 00461470: maximum = avatar money - seat `accnt`; 0 with the server's
  present `accnt` (the whole balance).
  Settles: `minigames-client.md` §10 row 1.
- [ ] **Meaning of `accnt`.** **Needs permission** (the server sends other `accnt` values). Repeat the entry
  above with `accnt` = 0 and = the buy-in.
  Observe: the dialog's maximum each time.
  Settles: `minigames-client.md` §11 Q2.
- [ ] **Failed "enter village".** **Needs permission** (the server offers no joinable village). Press the enter
  button on the avatar screen.
  Observe: after `!COULDNOT_CONNECT_TO_VILLAGE` the buttons stay disabled (`+0x218` = 0) and the player is
  stuck, or not.
  Settles: `lobby-screens.md` §3.6, §10 Q1.
- [ ] **Name outside Windows-1252.** **Needs permission** (the server sends an NPC or player name with such a
  character).
  Observe: the label: a best-fit letter or `?` (`Str_Utf8ToAnsi` S 00487620).
  Settles: `engine-core.md` §10 Q11.
- [x] **Extra mouse button as forward key.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* Press the first extra mouse button, also while the chat box has
  focus.
  Observe: the avatar walks forward in both cases (virtual key 5 in S 004295c0).
  Settles: `lobby-world-client.md` §10 Q6.
- [ ] **Handedness of the world.** Compare one visibly rotated object with its `orientation` in the scene file.
  Observe: the sense of the three turns.
  Settles: `lobby-world-client.md` §3.1, §10 Q9.
- [ ] **Web board while loading.** Watch a board from the moment the village appears.
  Observe: what the texture shows before the page is complete.
  Settles: `lobby-extras.md` §10 Q9.

### The pre-game room

- [ ] **First map of a new game.** Create a game and do not touch the map.
  Observe: the map shown (`MP_2P_fata_morgana` if the file system's first match is alphabetical).
  Settles: `match-setup-room.md` §10 Q2.
- [ ] **Game server connection.** Host a game; later join one.
  Observe: hook `GameServerConnection::Initialize` S 0048eda0 and `OnLoggedIn` S 0048edf0: no call = the object
  is never bound to a transport.
  Settles: `lobby-client-state.md` §10 Q1.
- [x] **AI seat beyond the map's positions.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Host a six-player map with computer players on high start
  positions, switch to a two-player map and start.
  Observe: the seats' start positions before the start and what the match does with a seat that has no position.
  Settles: `match-setup-room.md` §10 Q3.
- [x] **Host leaves; a kick.** *(settled or narrowed by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Two clients in a room: the host kicks the other; in a second room the host exits.
  Observe: on the client hook `cb_ConnectionClosed` S 0041bcc0, `cb_LoggedOut` S 0041b990 and
  `HandlePlayerLeft` S 00410720: which runs for the kick (connection closed as read) and which text, if any,
  the client shows for the host's exit.
  Settles: `lan-and-transport.md` §3.7, §10; `match-setup-room.md` §10 Q1.
- [x] **Joiner with less gold than the wager.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Host with a wager above the second player's gold; that player
  joins through a browser entry listed before the wager was set.
  Observe: the join succeeds, the Ready button stays disabled; `PlayerReady(0)` sent every frame only while
  ready (S 00457c13).
  Settles: `match-setup-room.md` §10 Q5.
- [ ] **Unused transport timeouts.** One join and one leave in a room.
  Observe: read watches on driver `+0x60` and `+0x68`, a hook on T 10006cf0: no hit = `usrRemove`,
  `usrLogoffTimeout` and `drvRemoveTime` are unused.
  Settles: `lan-and-transport.md` §6.2, §10.
- [ ] **Nagle on the host's sockets.** **Needs permission** (calls `getsockopt` inside the game). Host with one
  joiner.
  Observe: `TCP_NODELAY` of the host's accepted socket: off as read (driver `+0xb8` = 0), or on.
  Settles: `lan-and-transport.md` §3.4, §10.

### A network match with two players

- [ ] **Net tick length and input delay.** Play a match at speed 1; give one build order at a noted time.
  Observe: hook `AdvanceNetTick` S 00411990 and read manager `+0x2c` (net tick), `+0x38` (length, 4 expected),
  `+0x34`, `+0x40` (sub-tick) with wall time: 0.4 s per net tick; the order runs 0.8 s to 1.2 s later; every
  0x3000d event with its value.
  Settles: `logic-core.md` §3.2, §10 Q1.
- [x] **Unit of the ping samples.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Same match.
  Observe: hook `UIS_AddPingSample` S 0041d610: the stored values against the measured ping between the PCs
  (milliseconds as read), and the 0x3000d values that follow.
  Settles: `logic-core.md` §10 Q2; `game-commands.md` §3.2, §10.
- [x] **Speed button.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Look for the speed button in the match and click it.
  Observe: hook `SendCycleGameSpeedCommand` S 00782950 and `HandleSetGameSpeed` S 00782a20 on both PCs; manager
  `+0x3c` = 2 and `x2` on both screens, or the button is absent.
  Settles: `game-commands.md` §10 (speed button in a network match).
- [x] **A player leaves through the menu.** *(settled or narrowed by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* One player leaves mid-match.
  Observe: on the other PC hook `HandleCommand_2002B` S 00782910 (number of calls, one or two): the `!DEFEAT`
  letter appears and quest 0 of mode 1 advances on the next tick.
  Settles: `players-victory.md` §3.6.1, §3.8, §10 Q1; `network-session.md` §3.10, §10 Q7 (two-player part).
- [x] **Host loss.** *(settled or narrowed by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* End the host's process mid-match.
  Observe: on the other PC hook `BeginReconnect` S 00408f60 and read manager `+0x00` (reconnect state) and
  `+0x08..+0x14` (host to reconnect to, all -1 = become the host); whether the server log shows any message.
  Settles: `network-session.md` §10 Q2 (when the reconnect fires, whether the lobby server takes part).
- [x] **What a desync does.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* **Needs permission** (rides on "Different seeds" above: the server sends each
  client another seed).
  Observe: after the `ChecksumLog::VerifyLatest` S 00415a60 mismatch: message, log and dump only, or also a
  match abort or a report to the server.
  Settles: `logic-core.md` §10 Q3.
- [x] **Map with a script.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Host a user map that has a `.lua` of the same base name next to it; start.
  Observe: hook `GameScript_RunFile` S 005b1dc0 on both PCs: the script runs in a network session or not; if it
  starts a cinematic, whether the match stays in step.
  Settles: `lua-runtime.md` §2.1, §10 Q6; `logic-core.md` §10 Q9; `quests-sacrifices-stats.md` §10 Q6.
- [x] **Chest claim result.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* Open a chest in a lobby match.
  Observe: hook `ClaimChestResultReceived` S 0047a160 and `ObserverList_NotifyAll` S 00464300 for the lists
  `RefereeServerConnection +0x38` / `+0x44`: subscribers and any message or sound on the HUD.
  Settles: `quests-sacrifices-stats.md` §10 Q3.
- [ ] **Re-entry after a match.** Finish a match and return to the village.
  Observe: the order of the character list (message 60 in the server log) and `ProcessModeTransition`
  S 004f5950: the list is back before `SelectCharacter(LM+0x54c)` runs, or the re-entry fails.
  Settles: `lobby-client-state.md` §3.17, §10 Q6.
- [ ] **Walking in the village, seen by another client.** One player walks a measured stretch, the other
  watches.
  Observe: speed, the rate of position reports in the server log, and how the remote avatar is smoothed.
  Settles: `lobby-world-client.md` §3.4, §3.5, §10 Q13.
- [ ] **Poker: "back in" during the own turn.** Two players at a poker table; one sits out and comes back while
  it is his turn.
  Observe: hook `SendSitOut` S 00489340: the player has no buttons for the rest of that turn and is timed out.
  Settles: `minigames-client.md` §10 row 6.
- [ ] **Pawn Chess: king placement, check, pending capture.** Two players: place the kings on rows other than
  0; give check; let the server time a player out with a pawn picked.
  Observe: the piece shown during seat 1's placement; which king moves the client lets the player click in
  check; hook `SendCapture` S 00489fd0 and whether the board stays dead after the timeout.
  Settles: `minigames-client.md` §10 rows 9, 11; §11 Q7.

### Three or more players

- [ ] **Host loss with two survivors.** The host's process ends mid-match.
  Observe: on both survivors manager `+0x2c`, `+0x48` and the first checksums after 0x3000f; the worlds after
  commands given just before the loss.
  Settles: `logic-core.md` §10 Q4; `network-session.md` §10 Q3; `game-commands.md` §3.2, §10.
- [x] **Client chat routing.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* A non-host writes to all in a match.
  Observe: a capture on the third PC: the line arrives directly or through the host.
  Settles: `network-session.md` §10 Q1.
- [x] **Clean leave among three.** *(settled or narrowed by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`)* One non-host leaves through the menu.
  Observe: on the host the count of `HandleCommand_2002B` S 00782910 and any visible checksum-count notice.
  Settles: `network-session.md` §3.10, §10 Q7.

### Map editor and developer tools

- [x] **Open the Debug dialog.** *(settled by reading, 2026-10-12: `docs/live-checks/2026-10-12_read-from-code.md`, fourth pass)* **Needs permission** (calls the dialog-open function on `nMenu::System +0x14`).
  Observe: the dialog appears (`nMenu::Debug::OnShow` S 0060a340) and its widgets, cursor and tools respond.
  Settles: `map-editor-devtools.md` §10 Q1, Q2.
- [ ] **Editor at work.** **Needs permission** (follows the entry above). Use the terrain and Buildings tools
  and save a map.
  Observe: a read watch on `Scene +0x710`; hooks on `TerrainGenerator::Run` S 006b24f0 and
  `CMapRenderer::RunTerrainGenerator` S 00688540 (a call = generator-dependent heights reach the simulation);
  `SetBatchEditing` S 00538a60; whether the file lands in `campaignMaps`.
  Settles: `map-editor-devtools.md` §10 Q2, Q3; `engine-core.md` §10 Q5; `navy.md` §10 Q1.
- [ ] **CVar server and lobby debug switches.** **Needs permission** (the patched executable of
  `docs/BINARY_PATCHES.md`; the gate byte S 0088ca50). Connect with `tools/cvar_client.py` and set
  `Lobby/Show GfxObjStd PhysicDBG`.
  Observe: the server answers; the wireframe on a fence and on the terrain (which render meshes collide, the
  solid side of the triangles).
  Settles: `map-editor-devtools.md` §10 Q7; `lobby-extras.md` §10 Q4, Q6.
- [ ] **Dormant LAN path.** **Needs permission** (calls `StartUpNetwork(2)` S 0040a9a0 and `BC_Start`
  S 0041aa90 on one PC, role 1 on a second).
  Observe: whether the role 1 client finds and joins the role 2 host.
  Settles: `lan-and-transport.md` §10 (last row); `network-session.md` §10 Q6.
- [ ] **Flag with more than 36 goods.** Play with a mod data file that raises `cfg_setFlagPackageLimit`. May
  end the process.
  Observe: a good that finds no slot in its pile: where it is drawn (`ItemPile::AddItem` S 006cece0,
  `FindItem` S 006ce7a0 returning -1 / -1).
  Settles: `world-objects-rendering.md` §10 Q2.

### Settled by reading, not by playing

- `logic-core.md` Q5, Q6: strings in the checksum stream; checksum writers against save writers.
- `logic-core.md` Q7, `players-victory.md` Q7: writers of `GameLoadDescriptor +0x24` (start-position shuffle).
- `logic-core.md` Q8: readers of `Stock::changeStamp`. Q10: render managers of `SyncLogicTick` S 00680550.
- `game-commands.md`: forged `0x2000D` against an own target; second float of a distribution entry; research
  reference `+0x12c` after `0x20027`.
- `players-victory.md` Q6 lock map 2 readers; Q9 result screens; Q10 statistics read by the AI; Q11 `used` byte.
- `village-buildings.md` Q4, Q5, Q9: `System+0xbc`, `Building+0x38`, `Depot+0x08`, served bytes, countdown
  writers. Q6: `FindHuntableAnimalAt` S 0053ee60.
- `settlers-jobs.md` Q7 sub-movie classes; Q8 floats in the soldier checksum.
- `streets-transport.md` Q5 goods outside the priority list; Q6 goods list index 0; Q7 `SettlerMovement+0x38`.
- `map-resources.md` Q5 `elevationSize` and `GoodProperty+0x51`; Q6 directions 6 and 7; Q7 resource spawn
  points in the shipped maps (data scan).
- `military.md` Q3 unnamed fields; Q5 `Player+0x18`; Q6 reach and sea-attack helpers.
- `navy.md` Q2 `ShipConfig.size`; Q6 `HasFreeProductionOfType`.
- `ai-player.md` Q4 `ScoreSite`; Q5 functions not read line by line; Q6 old save versions; Q7 scripts inside
  skirmish maps.
- `properties-data.md` Q1 to Q3 field readers; Q4 deposit of a settler good (or a test map).
- `save-format.md` Q1 AI record layout; Q6 `Relink` bodies; Q7 `MapInfo` fields; Q8 flag-network map order;
  Q9 writers of `UserProfile +0x24`.
- `network-session.md` Q4 virtual calls on a received GUID; Q5 TinCat start-up values; Q6 LAN discovery
  messages; observer lists `+0x3d4` (§2).
- `lua-runtime.md` Q2 cutscene key time unit; Q3 building removal inside `vi_forEachBuilding`; Q5 unused
  `ui.set*` and `editor.*`.
- `quests-sacrifices-stats.md` Q1 `TribeProperty +0x50`, `MapInfo +0x204`; Q2 `pl_changePlayer`; Q5 letter
  addressee.
- `tribes-content.md` Q1 to Q7: ware group `weapons`, construction dummy types, military stock limits, tree
  creators without a forester, `sf_setBuffGfxName`, `items.xml` good attributes, Olympic flame worker.
- `camera-input-cutscenes.md` Q3 option ranges; Q4 untyped writers; Q6 terrain pick; Q7 follow anchor; Q8
  speaker flag; Q9 street overlay; Q10 `FileScan::ResolvePath`.
- `audio.md` Q5 to Q9: `nGame::Sound` byte, `SetHidden` callers, animation sound events, footstep position,
  `nMenu::Game` construction.
- `rendering.md` Q1 to Q10, Q12 to Q14, Q16, Q18 (each names its function).
- `animation-models.md` Q3 to Q14 (each names its function).
- `world-objects-rendering.md` Q1 group goods; Q3 `points0`; Q5 `decals.dds`; Q7, Q8 shader globals; Q9
  animated items.
- `ingame-ui.md` Q1 to Q4, Q6, Q8 to Q11. `hud-panels.md` Q1, Q2, Q7 to Q10.
- `formats-inventory.md` Q1 to Q8, Q10, Q11, Q13.
- `app-shell.md` Q1 to Q6, Q8, Q12. `engine-core.md` Q4, Q7. `frontend-screens.md` Q3. `ui-toolkit.md` Q2, Q3.
- `lan-and-transport.md`: relation to the `CommLayer` LAN classes of `tincat3.dll`.
- `lobby-client-state.md` Q2, Q4, Q7, Q8. `lobby-extras.md` Q2, Q3, Q7, Q8 (PhysX and MSHTML headers, mesh
  loading, class-name case).
- `lobby-screens.md` Q2, Q3, Q5, Q6, Q8, Q9. `lobby-world-client.md` Q4, Q5, Q7, Q10, Q12, Q14, Q15, Q17, Q18.
- `match-setup-room.md` Q6 readers of `slot_<n>.avo`; Q7 caller of vftable slot 24.
- `minigames-client.md` §11 Q3, Q5, Q8, Q9. `map-editor-devtools.md` Q6, Q8.

### Not answerable from the client

- `match-setup-room.md` Q4: which original server moved the wager, and the pay-out rule above two players.
- `minigames-client.md` §11 Q4, Q6: the original use of poker phases 2, 3, 4, 7 and bit 14; the original Pawn
  Chess piece order. Also the original meaning of `accnt` beyond what the client computes.
- `app-shell.md` Q7, Q11: the reader of `crashmsg.ini` and the retail `engine.ini` (an untouched install).
- `save-format.md` Q5: which build wrote `.sav` (type 10) files (a save of an old installation).
- `formats-inventory.md` Q12: the `.lep` body (the map editor's own binary, not in the install).
- `audio.md` Q11: whether Godot's WAV loader takes the install's ADPCM and float files (a test in Godot).

## Results of the free-game session of 2026-10-12 (offline, one player, debugger attached)

- [x] **Start values of a new world.** The tick counter read -1 when the world appeared and the simulation's random
  generator (S 00889b08) read its fixed start state 0x5432ACE0. Settles `docs/sim/logic-core.md` (first tick is tick 0;
  the generator's start state).
- [x] **Tick rate and game speed.** 10 logic ticks per second at speed 1, 20 at speed 2, 30 at speed 3; the manager's
  speed field (`NComm_Manager +0x3c`) read 1 / 2 / 3 and its ticks-per-net-tick field (`+0x34`) the same, offline (role
  0, state 4). Settles logic-core (one tick = 0.1 s; the speed multiplies the tick rate).
- [x] **Pause.** No tick for the 10 s of the pause; `+0x3c` stayed at 3. Settles logic-core (pause does not go through
  the manager's speed field).
- [x] **A load restores the tick counter and the random generator, not the speed.** Loading built a new world first
  (counter -1, generator at its start state), then restored the counter (1262, the tick of the save) and after it the
  generator: `LogicRandom_Save` S 005389c0 ran at tick 2328 with state 1661135933; `LogicRandom_Load` S 00538a20 was
  entered with the start state and tick 2328 already set, and left with state 1661135933. The seed word next to the
  state (S 00889b0c) stayed 0x5432ACE0. The game saved at speed 3 ran at speed 1 after the load. Settles
  `docs/sim/save-format.md` and logic-core (generator state and tick counter are in a save; game speed is not).
- [x] **Idle values of the network session in the village.** net tick -1, sub-tick -1, `+0x34` = 4, `+0x38` = 4,
  `+0x3c` = 1. Settles logic-core, the manager's initial values.
- [ ] **A command in an offline game runs at once.** Not checked: the session placed a building and a road, but no
  hook recorded when the command ran.

### 2026-10-12, free game, elimination in mode 1 (live)

Free game, victory mode 1, four players: index 0 local human and index 1 computer on one side, indices 2 and 3
computers on the other (`IsEnemyOf` matrix read live). `nGame::System::HandleCommand_2002B(2)` S 00782910 was
called once on the logic thread at the start of `VictoryCond_Update` in tick 7043.

- `[PROVEN]` The castle of player 2 was removed (`FindPlayerBuildingWithDefFlags(2)` returned 0 afterwards) and
  in the same tick `state[2]` became 1 with `stateTime[2] = 7043`.
- `[PROVEN]` Players 0 and 1 then showed `enemyCount 2, enemiesWithoutHQ 1`; no `DeclareWinner` call followed
  while player 3 kept its castle (300 ticks observed).
- `[PROVEN]` Unused slots 4..7 had state 1 from the start.
- `[PROVEN]` `HandleCommand_2002B(3)` at tick 8909: `state[3] = 1` in that tick and exactly one call
  `DeclareWinner(winnerIdx = 0)` S 00535990. Afterwards `won[0] = won[1] = 1`, `state[0] = state[1] = 0`,
  `stateTime[0] = 8909`, `stateTime[1] = 0` (only the named winner gets a time). No second `DeclareWinner` call
  for index 1. The named winner is the lowest index of the winning side; the ally is only marked in `won[]`.
- `[TODO]` The same in a network match with the lower index on the remote side: which avatar each client puts
  into FinishGame `0xDC0`.

### 2026-10-12, free game, own side eliminated in mode 0 (live)

Free game, victory mode 0 (endless), sides {0 local human, 1 computer} and {2, 3 computers}.
`HandleCommand_2002B(1)` at tick 271, `HandleCommand_2002B(0)` at tick 371, both on the logic thread.

- `[PROVEN]` `state[1] = 1` one tick after the first call and `state[0] = 1` one tick after the second; `won[]`
  stayed 0 for all four players; no `DeclareWinner` call (mode 0 never declares a winner).

### 2026-10-12, free game, own side eliminated in mode 1 (live)

Same sides, victory mode 1. `HandleCommand_2002B(1)` at tick 146, `HandleCommand_2002B(0)` at tick 246.

- `[PROVEN]` After the first call: `state[1] = 1`, `stateTime[1] = 146`, no winner.
- `[PROVEN]` In tick 246, the tick of the second call: one call `DeclareWinner(2)`. One tick later
  `state = 1,1,0,0`, `won = 0,0,1,1`, `stateTime = 246,146,246,0`. The eliminated players keep state 1 (they are
  not moved to state 2), the named winner is the lowest index of the winning side, and the ally (index 3) gets
  the `won` flag but no time.

### 2026-10-12, free game, interleaved sides in mode 1 (live)

Victory mode 1, sides {0 local human, 2 computer} and {1, 3 computers} (`IsEnemyOf` matrix read live).
`HandleCommand_2002B(2)` at tick 177, `HandleCommand_2002B(0)` at tick 277.

- `[PROVEN]` After the first call: `state[2] = 1`, `stateTime[2] = 177`, no winner.
- `[PROVEN]` In tick 277: one call `DeclareWinner(1)`. One tick later `state = 1,0,1,0`, `won = 0,1,0,1`,
  `stateTime = 277,277,177,0`. The named winner is index 1, the lowest index of the winning side, not the lowest
  index still in the game by position in a team list; index 3 gets the `won` flag only.
- `[PROVEN]` The logic kept ticking after the local player's elimination and the declaration (tick 356 read
  79 ticks later).

### 2026-10-12, free game, first batch of the specification checks (live, one player)

Free game, victory mode 1, local human index 0 against one computer player (index 1). Observe-only hooks on
`PlayMusic` S 005d9f60, `HandleCommand_2002B` S 00782910, `IsGameHanging` S 00408860, `GetHangReason`
S 0040d260, `QueueGameCommand` S 00408b10 and `ComputeChecksum` S 00784080.

- **Players graph in the first minute** — maintainer: the graph lists only the own player (the enemy has not
  been seen yet) and shows no data, because no time has passed.
- **Tech tree tab** — maintainer: a text-only tree, with different colours for products, end products and
  buildings.
- **Pause and commands offline** — maintainer: nothing can be built while the game is paused.
  `[PROVEN]` `IsGameHanging` returned true in 1,462 of 25,935 calls, first at tick 1014; `GetHangReason` was not
  called once and `QueueGameCommand` was not called once in the session (no command reached the queue).
- **Save and load are checksum-neutral** — not settled: `ComputeChecksum` was not called once in an offline
  game, so a passive hook records nothing. The check needs either a network match or a call of the function.
- Own castle removed at tick 1534 (`HandleCommand_2002B(0)` called by the debugger): `state = 1,0`,
  `won = 0,1` 38 ticks later; no `PlayMusic` call up to then.
- **Win and loss jingles** (loss half) — `[PROVEN]` no `PlayMusic` call between the defeat and the return to the
  menu: `music_lost` (index 3) was not started. Maintainer: a sound effect plays when the dialog opens, the same
  one as on a win as far as remembered. The win half is open.
- **Leaving an offline match** — `[PROVEN]` leaving through the menu made no `HandleCommand_2002B` call. On the
  way back to the menu `PlayMusic(0)` was called twice within 6 ms.
- **Players graph** — maintainer: by the end of the match the graph showed data.
- **Defeated player** — maintainer: the camera can be moved on the `Defeat` dialog. Selection and the explored
  area were not observed (the player had no building left).
- Maintainer's reading of the unused `music_lost`: a remnant of the 10th Anniversary game. `[TODO]` not checked.

### 2026-10-12, free game, second batch of the specification checks (live, one player)

Observe-only hooks on `nUi::Object::HandleHotkey` S 0049ffc0, `LoadSavePanel::Confirm` S 0060d000, the box answer
S 0060d5b0, `DeclareWinner` S 00535990 and `PlayMusic` S 005d9f60.

- **Hotkeys with Caps Lock or Shift** — maintainer: the hotkeys work neither with Caps Lock nor with Shift.
  `[PROVEN]` in the first 400 recorded `HandleHotkey` calls, key code 115 (`s`) was handled (return 1) six
  times and key code 83 (`S`) never in 22 calls: the comparison is on the character code.
- **Info-map overlay** — maintainer: space shows what can be built where (flag, small, medium, large building,
  harbour, nothing). Which other overlays go away was not reported.
  Space also works with Shift held and with Caps Lock on, unlike the letter hotkeys.
- **Unfinished street in a save** — maintainer: opening the menu does not end the street mode, it stays while
  the dialogs are open; nothing is placed until the street ends in a flag. After loading the save the street
  mode is gone and no street or stub exists.
- **Overwrite after a delete prompt** — maintainer: after Delete answered with No, saving over an existing name
  does not save; it deletes that save, and Save has to be pressed again. `[PROVEN]` three `Confirm` calls and
  two box answers were recorded in that sequence. This is the stale pending action of `frontend-screens.md`
  §3.6.
- **Save after a win / win jingle** — not settled: this game ran in victory mode 0, so removing the enemy castle
  at tick 1632 gave `state[1] = 1` and no `DeclareWinner` call. Needs a game in mode 1.
- **Info-map overlay** — maintainer: space hides no overlay.

### 2026-10-12, free game, win and save after a win (live, one player)

Free game, victory mode 1, local human index 0, one computer player index 1.
`HandleCommand_2002B(1)` called by the debugger at tick 134.

- **Win jingle** — `[PROVEN]` `DeclareWinner(0)` at tick 134, `won = 1,0`, `state = 0,1`; no `PlayMusic` call
  from then until the save was loaded: `music_won` (index 2) was not started. Maintainer: no jingle heard.
  With the loss half above: neither jingle is played.
- **Save after a win** — maintainer: after loading the save the victory dialog shows again.
  `[PROVEN]` a second `DeclareWinner(0)` call at tick 339, the first tick after the load, and
  `stateTime = 339,339` afterwards: both the elimination of index 1 and the win were detected anew, so `state`
  and `won` do not come back from the save as set. In a lobby match that second call sends a second
  `FinishGame` `[inferred]` (same code path, not observed online).

### 2026-10-12, developed save, third batch (live, one player, 1,700 ticks observed)

A saved free game loaded at tick 53,306: victory mode 1, local human index 0, five computer players (two of them
already without a castle). Twenty observe-only hooks; values below are from ticks 53,306 to 55,001.

- **Cadence of the AI modules** — `[PROVEN]` `NAI::System::Tick` S 00581a30 runs every tick (one object).
  `MilitaryLimiter::Update` S 00597c80: three objects, each every 53 ticks (31 of 31 intervals).
  `LockSmith::Update` S 0058d130: three objects, each every 337 ticks (4 of 4), 5 ticks apart from each other.
  `AttackExecution::Update` S 005a0dd0: intervals of 141 ticks (6 of 7) and one of 1,269 = 9 x 141, so it is
  not called on every 141-tick step. `AiStreetPlan::PlanPath` S 005a96b0: 169 calls in groups of three 5 ticks
  apart, the groups 37 ticks apart (the 37-tick route optimiser, one call per computer player).
- **Batch-editing byte in a match** — `[PROVEN]` no `SetBatchEditing` call; `Edit +4..+7` read 0,0,0,0, with
  ships in the game (459 `NavyCargo_LoadAtHarbor` calls: 315 returned 1, 144 returned 0).
- **S 00658df0 ever true** — `[PROVEN]` 431 calls, all returned 0. Still open for other fights.
- **Demolish countdown** — maintainer: demolishing a guard house away from enemy territory gave no message.
  `[PROVEN]` neither `StartDestroyCountdown` S 0055fc10 nor `Military::NotifyDestruction` S 00560890 was called.
  This agrees with `village-buildings.md` §3.5: the countdown is used only when the building is the target of a
  fight; otherwise the building is removed at once. The countdown case (demolish a building under attack) is
  not hooked yet. Maintainer (from play): a military building under attack takes about 30 seconds at speed 1
  before it is destroyed, which is the 300 ticks of `mi_setActionsInFightDelayTime` at 10 ticks per second.
  `ReleaseSoldier` S 0055fc40 ran four times on one building at ticks 54635, 54645, 54655, 54665;
  whether that was the demolished guard house was not established.
- **Waiting attackers without an enemy** — maintainer: more soldiers than can fight at once cannot be sent, so
  the situation does not arise from the attack dialog.
- **Carrier swap at full flags** — `[PROVEN]` in normal play `CanSwapPackagesAtFlag` S 0064d120 ran 17,218
  times and `FindSwapPackageAtStreetEnd` S 0064d750 8,286 times; 7 of the first 100 recorded searches returned
  a package. The jam case itself was not set up.
- **Defence fraction** — `DispatchDefenders` S 00576400 ran once (tick 54415); S 0059b3f0 not at all. Open.
- **Aborted hunt** — maintainer: after the hunter's hut was destroyed with the hunter on his way, the animal
  no longer moves. `[PROVEN]` (ticks 53,306 to 62,999, 55 `VillageLink_UnlinkHuntedAnimal` S 0053c580 calls: 51
  with `erase = false`, 4 with `erase = true`). The four aborts:
  tick 55826, animal in state 4, counter 101: still state 4, counter 101 at tick 62999 (7,173 ticks later);
  tick 61568, state 4, counter 18: still state 4, counter 18 at tick 62999 (1,431 ticks later);
  tick 56118, state 5: state 9 afterwards (erased, as read);
  tick 57338, state 4, counter 839: unlinked again at tick 59111 by another building with `erase = false` in
  state 9, i.e. another hunter killed it and it was removed; the address was reused afterwards.
  The animal of tick 61568 (the maintainer's destroyed hut) went the same way: unlinked at tick 64998 by
  another building in state 9. Maintainer: "it was just killed now".
  So an animal in state 4 at the abort stays in state 4 with a frozen counter and does not move, and it stays
  huntable: another hunter can take and kill it (two of three cases within 1,800 and 3,400 ticks; the third
  was still frozen after 9,500 ticks). Agrees with `map-resources.md` §3.10 step 6.
- **Ferry waiting time** — `[PROVEN]` `NavyCargo_LoadAtHarbor` S 005bd4e0, two cargo objects, the first 200
  calls: at each stay the function is called once per tick; the complete stays had 40, 38 and 35 calls that
  returned true (a package moved) and exactly 17 calls that returned false (idle) before the ship left. 17 idle
  ticks is the count for `waitTime` 15 (the value `sh_setWaitTime` sets, `navy.md` §3.7 state 2), not for the
  constructor value 40. The hold against `stockLimit` and the full-flag case were not read.
- **Occupied building with wanted size 0** — maintainer: with the sliders as they are in this save a building
  without stripes stays empty; whether these are the default settings was not known to him.
  `[PROVEN]` read at tick 82,250: `NPlayer::Military +0x08` of the local player is 0.000 / 0.494 / 1.000 (far /
  medium / near) and `+0x1c` is 0.900, so not the defaults; three computer players have 0.1 / 0.3 / 1.0 and
  0.5, the constructor defaults as read, the other two 0.1 / 1.0 / 1.0 and 0.1 / 0.24 / 0.8.
  Between ticks 67,688 and 82,250 `Military_GetDesiredGarrisonSize` S 00574980 returned 0 for 13 buildings; of
  the eight that still returned 0 at the last pass, all have an empty garrison vector (`Military +0x10` =
  `+0x14`). So an occupied building whose wanted size is 0 is emptied and goes on existing. Whether its border
  stays was not read; with the default far fraction 0.1 the case of capacity 2..4 is not yet observed.
  **With the defaults** (the debugger wrote 0.1 / 0.3 / 1.0 and 0.5 into the local player's
  `NPlayer::Military` at tick 83,668, at the maintainer's request): `[PROVEN]` over the next 2,680 ticks (127
  allocation passes) seven buildings kept returning wanted size 0 and kept an empty garrison vector; the other
  buildings that had returned 0 under the far fraction 0.0 stopped doing so. So with the default sliders an
  occupied far building can want 0 soldiers and stays empty, as `military.md` §3.2 reads. The capacity of those
  seven buildings and their border were not read.
  Maintainer, with the defaults: a soldier stays in the fortress but none in the guard hut — the formula's
  capacity 6..12 wants 1, capacity 2..4 wants 0. One soldier also stays in the guard tower. The capacities of
  the three building types were not read, so which limit separates "0" from "1" is `[TODO]`.
- **Product on a full flag** — maintainer: when the flag is full the workshop stops with the finished product;
  the building's worker puts that product on the flag when a place becomes free.
- **Blocked flag** — `[PROVEN]` `NTransport::Package::AddFlagFullWaitTick` S 006513b0 (`this` = the package):
  package A (good `a9676263`) from tick 86,411 on, one call per tick; read at tick 89,472: 3,062 calls,
  `flagFullWaitTicks` (+0x104) = 3,062, `flagFullWaitWeight` (+0x100) = 42,868 = 14 per call. Package B (good
  `0e3f885d`) from tick 86,447 to 87,948: 1,502 calls, one per tick; both fields read 0 afterwards.
  Package A is `water` (`0xA9676263`) and was still counting at tick 93,535 (7,125 attempts, one per tick): a
  product waiting at some full flag elsewhere on the map for more than 7,000 ticks. Package B's good could not
  be read after the fact (the address was reused); its 1,502 ticks fit the time the maintainer's test flag was
  full. The maintainer's setup was a woodcutter and a sawmill joined by one street and cut off from every other
  street, so the package that waited at the full flag was the sawmill worker's product: no street carrier with
  a package from another street was involved. A worker's product is therefore tried every tick and is not
  discarded at 360; that limit sits in the carrier's state 0x12 only (`settlers-jobs.md` §3.6.2), and the
  carrier case (every 10th tick, `!flag blocked` every 180 attempts, return after 360) is still `[TODO]`.
- **Player colours** — `[PROVEN]` `g_PlayerColors` S 0087ead8 read live (four floats per entry): 0 = 0.01 / 0.10 /
  0.60 / 1, 1 = 0.60 / 0 / 0 / 1, 2 = 0.20 / 0.50 / 0 / 1, 3 = 0.75 / 0.46 / 0.05 / 1, 4 = 0.65 / 0.65 / 0.65 /
  1, 5 = 0.29 / 0.29 / 0.29 / 1, 6 = 0.45 / 0 / 0.35 / 1, 7 = 0.20 / 0.60 / 0.60 / 1. `Player.colorIndex` in
  this save: index 0 → 0, 1 → 3, 2 → 1, 3 → 6, 4 → 4, 5 → 5. Maintainer on screen: the player with entry 3 is
  yellow rather than orange, entry 4 more white, entry 5 dark grey. That fits the order red, green, blue, alpha
  for entry 3 (in the reverse order it would be a blue). Entries 4 and 5 are greys and do not decide the order;
  the colours of entries 0, 1 and 6 on screen were not reported.
- **Time of day** — `[PROVEN]` in 2,843 frames (ticks 96,466 to 97,858) `CEnviromentMgr::Update` S 00683d50 ran
  once per frame and `GetDaytime` S 00684a20 was not called once. Whether the hour advances was not read.
- **Autosave** — `[PROVEN]` `nGame::Autosave::Update` S 0078b040 runs once per frame (2,843 calls in the same
  span, one object). The pause case is open.
  Maintainer on the time of day: it does not change during play.
- **Autosave during a pause** — `[PROVEN]` the game was paused with the tick counter at 99,479 from 18:53:06 to
  at least 18:58:37 (read twice, unchanged; `nGame::Autosave::Update` S 0078b040 ran 17,505 times in between).
  `Autosave.aav` was written at 18:53:44, inside the pause, exactly 10 minutes after the previous one
  (18:43:44); no further write by 18:58:59. So the autosave timer runs on wall-clock frames and fires while the
  game is paused, as read. The interval in effect was 10 minutes. The cinematic case is open.

### 2026-10-12, entries settled by reading the code

Nine entries were settled statically; evidence per entry is in `docs/live-checks/2026-10-12_read-from-code.md`.

- **Products per resource cell** — a mine gets `min(n, 8) - 1` products from a cell of amount `n`; 1000 is
  unlimited. The call that empties the cell returns false and the delivery is skipped (S 00674650, S 00674e70,
  S 0055c860, S 00565f80). The fisher ignores that return value.
- **Ware delivered during an upgrade** — the double credit is real: two unconditional `Stock::AddOne` calls in
  `Depot::CollectGoods` S 0055aca0 on two different stocks (`Upgrade::Start` S 005671a0 has its own
  `Construction`).
- **`-nolobby` and the lobby button** — the button is neither hidden nor disabled; the click sets
  `nMenu::System +0xb4` and restarts the menu music, and the flag's only reader is behind `lobby != NULL`.
- **Closed row on a taken start position** — `StartFreeGame` S 005e7350 writes the rows in order without
  skipping closed ones; a closed row carries its own row index as start position. A player in a row below the
  closed one starts at its own row's position (the choice is ignored); a player in a row above it lands on the
  chosen position and its own row's slot keeps the same player too. `[TODO]` a one-minute live check.
- **Info pages** — the info scripts never run: `Info::Open` S 005f6310 has one caller, with mode 0.
- **Time of day** — the hour does not run (`CEnviromentMgr +0xfc` is pinned by `Update`; its setter has no
  caller). Agrees with the maintainer and with the live hook (no `GetDaytime` call).
- **Chest claim result**, **Shop result and inventory lists** — the observer lists in question never get a
  subscriber (every `ObserverList::Subscribe` S 00458860 call site enumerated).
- **Garrison slider during an attack order** — an index of -1 ends the process with exit code 0xC000000D: all
  2,521 call sites of `_invalid_parameter_noinfo` terminate, and the game's crash handler does not run.
  Whether the slider can reach index -1 was not re-read.

Examined and still open: Debug icons (half: the icons are hidden at creation), Extra mouse button as forward
key, Second own ship to an occupied exit (the null write is certain, reaching it is not), Game server
connection, What starts observing.

Maintainer on the debug icons (2026-10-12): never seen in the game. `[TODO]` later: show them in the running
game (a mod or patch that un-hides the five icons, most likely with the regular HUD hidden if the debug row is
meant to take its place) and see what each does.

Second pass of the reading (same results file):

- **Defence fraction of an attacked computer player** — `DispatchDefenders` S 00576400 always gets the player
  setting: the AI's value written in S 0059b3f0 is overwritten by the next statement of `StartAttack`
  S 00576500. The AI's two random draws are still made.
- **Mines without food** — as expected: at "high" a human's mines need and request no food, a computer
  player's mines need food at every level, and at "medium" a human's mines need food (S 005be330, S 00565bd0).
- **Garrison slider during an attack order** — index -1 is reachable in play: soldiers picked for an attack
  stay inside for the 10-tick start countdown, and if the 21-tick allocation pass falls into that window while
  the wanted size is below the garrison, `FindWeakestSoldier` returns -1 and the process ends. Live recipe:
  lower the building's slider, then at once attack with all of its soldiers. `[TODO]` not observed.
- **Second own ship to an occupied exit** — the set-up of the entry cannot happen: `SendSoldiersBySea`
  S 00575510 sends nothing while the attacker already has a ship on that route. Remaining candidate for the
  null write: a ship that keeps its docking reference after the harbour at the other end is lost
  (`NavyLink_UnlinkMovementRoute`, S 005b5370 unread), then a second own ship joining the route.
- Still open after reading: Door direction and levelling (no reader of `gameConfig +0x14` found among 67
  functions; the door is a visual check), Top-up maximum.

### 2026-10-12, unattended measurements in the developed save (ticks 102,000 to 126,500)

Run by an agent through the Frida MCP with nobody at the keyboard; per-entry detail, every call made into the
game and the numbers are in `docs/live-checks/2026-10-12_unattended-run.md`. Orders were issued through the game's own
functions on the main thread (`SendCycleGameSpeedCommand` S 00782950, `QueueGameCommand` S 00408b10 with the
upgrade event 0x2000F, the camera's wheel and key handlers).

`[PROVEN]`
- **Debug icons** — all five have `visible` = 0 in a running match; slot 10 of the icon vftable is
  `nUi::Icon::Hide` S 004cf210.
- **Walk and pick-up timing** — one settler update per tick, 9.97 ticks per second at speed 1, 17 or 18 ticks
  per flat cell (18 for the first cell of a walk), 4 ticks per pick-up or put-down phase; 21 / 22 ticks per
  cell at slope factor 0.8 and 28 / 29 at 0.6.
- **Defence fraction of an attacked computer player** — the AI wrote 0.862, `StartAttack` overwrote it with the
  player setting 0.5, `DispatchDefenders` got 0.5 (one attack). Agrees with the reading.
- **Time of day** — the hour stayed 12.0 over 4,367 ticks; all nine keys have heading = elevation = 50.
- **Zoom distances and smoothing** — 21 units per step; zoom easing is time-based (about 0.96 s to 5 %), yaw
  easing frame-based (11 frames to 5 %). `zoomMax` reads 6.0 in this install (the spec has 4.0 from the
  constructor; the install carries the widescreen fix, the writer was not looked for).
- **Products per resource cell** — amount n gives n - 1 products: 85 of 85 cycles that emptied a cell delivered
  nothing, 403 of 403 others delivered. No cell above 7 and no unlimited cell occurred.
- **Ware delivered during an upgrade** — 8 of 8 deliveries made two `Stock::AddOne` calls; the 8 extra units
  stay in the finished tower's input stock.
- **Ferry waiting time and hold** — 17 idle ticks per stay (`waitTime` 15). The hold is not bounded by
  `stockLimit` 12: one computer player's ferry carried 13 and then up to 39 packages, still growing over 12,000
  ticks. **Contradicts** the bound stated in `navy.md` §3.9.
- **S 00658df0 ever true** — 31,676 calls from tick 53,306 to 124,149, all 0.
- **A command in an offline game runs at once** — the speed read 1 before and 2 after the send function
  returned.

**Contradicts the spec**
- **Animal idle time** — `map-resources.md` §3.10 has `counter = (int)(tick/10 - timeStamp)`; measured on 400
  arrivals and read in the disassembly (S 0054231f..0054235e) it is
  `(int)((float)(tick/10 - timeStamp) * idleTimeFactor (+0x4c, 3.0) * 10.0)`: an animal idles three times its
  walk ticks. The hunter half of the entry was not observed.
- `audio.md` §3.2: the device camera in a match is the `nGame::Camera` (vftable S 00835294), not a `MapCamera`
  (`MapCamera::GetEye` / `GetTarget` were never called); the listener sits 80 % of the eye's height down the
  view line.

Partly
- **Blocked flag** — a street carrier in state 0x12 tries every tick for 13 to 42 ticks and then every 10th
  tick; `!flag blocked` came at the 180th attempt (3 cases). No street carrier reached 360. A carrier in state 1
  counted to 416 with messages at 180 and 360 and did not return the good.
- **Carrier swap at full flags** — 255 packages found in 5,216 searches; one player's jams resolved after at
  most 261 attempts. The set-up of the entry was not built.
- **Demolish countdown** — two `StartDestroyCountdown` calls (ticks 89,270 and 90,286) and no
  `NotifyDestruction` call in 70,000 ticks; countdown length and removal tick not captured.
- **Settler release in state 0x24** — one settler released in the worker's first 0x24 tick, then `Rest` (5
  cases); no building had more than one to release.
- **Emitter channel after scrolling away** — the channel map stayed at 2 and `StopChannel` was not called; the
  fade-out case did not arise.
- **Ini files behind a byte order mark** — the effective `gamePort` is 5479 while the first `[Basics]` section
  says 5478; the file has a second `[Basics]` with 5479, so the two explanations cannot be told apart.
- **Door direction** — from cell-to-world coordinates direction 1 is lower right and direction 4 upper left if
  the renderer is left-handed (not measured).

Not possible unattended: Mines without food (all six players have `state` 2 in this save; settled by reading
above), Timer precision after a long uptime (the PC was booted the same day). Not done: Garrison slider during
an attack order (the game stood still before it was reached).

State left in that match: the local player's guard house at cell (43,92) was upgraded to a tower; game speed 3;
the run ended when the game window lost the foreground and the Direct3D device was lost
(`CGraphicDevice::WaitForDeviceRestore` S 004da170) around tick 126,500.

Third pass of the reading, batch 1 (same results file):

- **Second own ship to an occupied exit** — closed: not reachable through the game's rules. A ship releases
  its docking position whenever it leaves a route (`Movement::ClearRoute` S 005b9340); losing a harbour takes
  every ship of that owner off the route; every path that adds a ship tests "no ship of this player yet".
  Limits: an edited save, or data with fewer than two docks per exit.
- **Debug icons** — closed: hidden for the whole match; showing a parent never writes a child's visible byte.
- **E-mail change (88)**, **ChangeCharacter (90) is unused**, **Mail `creation_time`** (no reader), **Own
  whisper echo** (the own line is dropped when the target is not in the name cache) — settled.
- **Unknown item id**, part (b) — hovering such a slot with a shop open ends the process (S 0046d6d0);
  part (a) is open.
- **Timer precision after a long uptime** — the step is `2^(floor(log2 s) - 23)` s: 7.8 ms after 18 h, 31 ms
  after 3 days, 62 ms after 6 days.
- **Map with a script** — the script runs in a network session on every peer that has the `.lua`; only the
  `.s2m` and `.bmp` are fetched from the host, so a joiner without the script does not run it.
- **Speed button** — shown and usable in a network match.
- **What a desync does** — a letter, a log line, and a dump only when the log level is above 1; no abort and
  nothing sent.
- **File name with an upper-case umlaut** — the locale half is settled (lower-casing always runs under "C").

Third pass of the reading, batch 2 (same results file):

- **Victory state in a save** (from the live run above) — none of `state[]`, `won[]`, `stateTime[]` is stored:
  `VictoryConditions` has no store or load function, `System::Save` S 005275c0 does not touch it and `Init`
  S 005357c0 zeroes it. The first tick after a load re-runs the elimination test and declares the same winner
  again, with the dialog.
- **`zoomMax` 6.0** — the game has no writer besides the constructor (4.0, S 007876e0); the value is raised at
  run time from outside the game. Candidate `[inferred]`: the 94 KB `d3d9.dll` proxy in the game's `bin`
  folder. `[TODO]` a write watch on `Camera +0x1c` during a world build.
- **Blocked flag** — the 360 limit exists only for a carrier on a street (`IsFlagFullWaitExceeded` S 0077a0c0,
  one caller, the street loop S 0065b200). A carrier not yet on a street (`UpdateDropOffAfterSpawn` S 0065ad70,
  state 1) tests the flag every tick with no limit and never gives the good back.
- **Autosave during a pause** — fires while paused, never during a cinematic; an overdue one fires in the first
  frame after the cinematic.
- **Book reopened in quest view** — shows neither pages nor quest widgets; one click on the toggle restores
  the story view.
- **Heal with soldiers in a barracks** — stocked soldiers leave at full life.
- **Joiner with less gold than the wager** — joins, sees no message, the Ready button is disabled every frame.
- **AI seat beyond the map's positions** — the seat gets no player and no castle.
- **Left-game notice** — on a non-host the latch `+0x4b` is reset by every applied game information, so a later
  leave event for the same slot shows the notice again.
- **Random teams** — drawn with `rand()` seeded by `time()` on the host, which applies its own 0x30012.
- **Unit of the ping samples** — milliseconds of a full round trip. **Client chat routing** — client → host →
  the other clients.
- Narrowed, still open: Which seed a client uses (message timing), Name outside Windows-1252 (decided by
  `WideCharToMultiByte(CP_ACP)`), Failed "enter village".

Third pass of the reading, batch 3 (same results file):

- **A player leaves through the menu / Clean leave among three** — the host issues 0x2002B twice when a
  non-host leaves cleanly: once from the lockstep 0x3000b (S 0040e560) and once from the disconnect
  (S 00410720). Open: the host's own leave.
- **Host loss** — a client elects as soon as its connection to the host is reported removed; the successor is
  the first entry of the host's peer list (the client that connected first); the game never sets a preferred
  successor; the lobby server takes no part. Open: whether a migration works across real networks.
- **Host leaves; a kick** — the joiners get no text: the room dialog just closes.
- **Shop action in slot 0 plus a second action** — no 0x2E10; an NPC with two or three actions cannot run any
  of them (agrees with the live result of the same day).

What is left, by kind (the agent's reading of the entries):
- Look, sound or real time, for the maintainer: widget drawing details, loop of the main theme, loudness over
  distance, reference screenshots, marker on attackable buildings, defeated player (selection and explored
  area), handedness of the world, web board while loading, walking in the village seen by another client, net
  tick length and input delay, door direction.
- Timing or operating-system behaviour: ini files behind a byte order mark, name outside Windows-1252, first
  map of a new game, which seed a client uses, re-entry after a match, host loss with two survivors.
- Reading complete, a live run can only confirm: game server connection, what starts observing, lists that
  never fire, LobbyManager list `+0x34`, LobbyMessage `+0x38`, ItemsClient tokens, unused transport timeouts,
  Nagle, failed "enter village", top-up maximum, Poker, Pawn Chess, cannot-sell box.

Fourth pass of the reading, batch 1 (same results file, heading "Fourth pass"):

- **Emitter channel after scrolling away** — with SSE2 the fade-out never frees the channel: for the far
  position the volume product is NaN, `CVTTSD2SI` gives `0x80000000`, and the stop test at S 0056d620 never
  passes. The fade-out only runs when more than four distinct sound ids exist. To hear once: with four stuck
  records a fifth sound never starts.
- **Stale click latch** — reachable: `nMenu::LoadSavePanel` handles confirm and delete in `OnButtonClick`
  S 0060d430 and never polls; after one click, a press on the button released outside it runs the click again.
- **Script-moved NPC** — an off-centre NPC re-centres and stays; all three `se_moveNPCTo` calls in the shipped
  maps are commented out, so the case cannot be seen in the shipped game.
- **Ship on another sea adopts a route** — S 005b4c50 compares the ship's continent with itself; the idle ship
  takes the route, exchanges cargo from a distance for one stay, then makes one straight step. Only
  `ReturnToOwnHarbor` gets there.
- **Demolish countdown** — the 300th decrement and the removal are in the same loop iteration of S 0055a640,
  so `NotifyDestruction` is dead with the shipped value. A headquarters type skips the block, so a countdown
  started on one by a raw command never ends.
- **One ship-building visit** — strokes = `(int)constructTime` = 30 (the entry's 50 is not the shipped value),
  31 updates per visit.
- **Cell demolish trigger** — the shipped game has no campaign save to load (33 `.s2m` maps, no `.aav`).
- **Good exchange output** — the sacrifice building's own worker carries the wares out, one per walk; the
  transport system never dispatches from these buildings.
- **Carrier sent home while his street exists** — his street stays usable and is charged plain length while he
  walks home, so goods keep being routed over a street nobody serves. How often it happens is narrowed to two
  conditions (hook S 00656740).
- **Enclosed planter**, **hunter and unexplored targets**, **Founding and a lost expedition target**, **Two
  players' ships at one exit**, **Waiting attackers without an enemy** — settled; see the results file.
- Narrowed: Saves in special states (`nMenu::System::EmergencySave` S 005da7d0, the battery-low message, saves
  during a cinematic), Property values after a reload (only exists with the `propreload` mod), Floating-point
  control word (one `__controlfp` caller, no `FNINIT`). Still live: Save and load are checksum-neutral,
  Activate-main latch and Info gate.

Fourth pass of the reading, second half:

- **Extra mouse button as forward key** — `WM_XBUTTONDOWN` reaches `LobbyAction::OnKeyEvent(5, 1)` through
  `WorldScreen::OnMouseButtonDown` S 00431d60 when the cursor is over the 3D world. The world screen captures
  input only for buttons 1 and 2, so a press over the world released over a widget never delivers the key-up
  and the avatar keeps walking forward.
- **Re-sent 1004** — the model stays where it was created (the NPC proxy's interpolation mode is 2, so the
  creation transform is output); the name label changes at once.
- **Shop title** — `ShopName` is stored at `ShopDialog +0xb5c` and never displayed.
- **Map type values** — the 3 / 1 read live for stock maps comes from the assetshare mod's hook; without it a
  stock map keeps the value stored in its file.
- **1001 for the own id** — no position sample is pushed for the local controller; the new look is shown.
- **Unknown item id**, part (a) — nothing is attached and nothing crashes on the avatar path.
- **Open the Debug dialog** — no way in the shipped build: no call site activates screen slot 1.
- `[00898044]` is the SSE2 flag (writer S 007110d8, CPUID leaf 1 EDX bit 26): the emitter-channel finding
  above is `[known]`.
- Narrowed: Limits of the walkable area (whether the collision mesh confines the avatar depends on the
  character library's slope rule: faces steeper than 48 degrees enclose the origin, steeper than 60 do not —
  from a flood fill over the parsed collision mesh), Map fetch branch (`+0x228` / `+0x229` are plain arguments
  of `SetGameSettings`), Editor at work, Flag with more than 36 goods (needs `cfg_setFlagPackageLimit` >= 7,
  shipped 2). Still live: Controller hit report (needs `NxCharacter.dll` in the Ghidra project), CVar server
  (check `netstat -ano | findstr :1234` on the game PC first), Dormant LAN path.
