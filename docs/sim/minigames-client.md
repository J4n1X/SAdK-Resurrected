# Tavern minigames on the client: Dice, Poker and Pawn Chess

Tags: [known] = read at the address given (S 00xxxxxx = `sadk_noav.exe`) or in the named data file;
[inferred] = one step of reasoning from what is visible; [TODO] = open. Nothing in this document was
observed in the running game unless a dated observation of another document is cited.

---

## 1. Purpose and scope

The two taverns of the lobby village hold tables at which players play three games for credits (`gold`) or
play money ("funnies", `glod`): **Dice** (type 1), **Poker** (Texas Hold'em, type 2) and **Pawn Chess**
(type 3). This document specifies the client side:

- the table mirrors `LobbyComm::MiniGameProxy` and its three subclasses (state, wire readers, senders);
- the per-table 3D clients `Lobby::CLobbyClient_MiniGame*`, the seat and board controllers
  `Lobby::CMiniGameController*`, the board objects `Lobby::CGfxObjMiniGame*_Board` and the chip renderer
  `Lobby::CChipGfxMgr`, as far as the rules and the protocol depend on them;
- the dialogs `LobbyMenu::MinigameDialog` (+ `_Dice`, `_Poker`, `_PawnChess`, `_Observer`),
  `MiniGameMatchMakingDialog`, `MiniGameManualDialog`;
- which decisions the client takes and which it waits for.

The division of labour in one sentence: **the server owns every rule except three that the client computes
itself for display** (the Dice payout, the Poker pot winners from the hand values it is sent, the Pawn Chess
move generator that decides which clicks become messages). The client never shuffles, deals, rolls, evaluates
a poker hand, detects check or mate, or times a player out.

Not repeated here (link, do not duplicate):

- wire layouts of every message, the key / settings / seat sub-records and the hard client limits:
  [`../message-catalog.md`](../message-catalog.md) section "Minigames";
- the flow around a table from the server's point of view: [`../village-and-character-protocol.md`](../village-and-character-protocol.md) §6.4;
- the base `MiniGameProxy` fields: [`lobby-client-state.md`](lobby-client-state.md) §2.15;
- how the world screen opens the dialogs, the stake dialog `SetStackDialog`, the manual dialog and the two
  error boxes: [`lobby-screens.md`](lobby-screens.md) §3.16 and §3.17;
- the 3D village, the controller stack, view modes and `OrbitCameraRig`: [`lobby-world-client.md`](lobby-world-client.md).

---

## 2. Data model

### 2.1 Table, seats, money (base `MiniGameProxy`, 0x248 bytes)

Fields are listed in `lobby-client-state.md` §2.15. What the games rely on:

| Item | Meaning | Tag |
|---|---|---|
| game type | key `mngt` low nibble: 1 Dice, 2 Poker, 3 PawnChess | [known] S 00471210, S 00471300, S 005032b0 |
| currency flag | key `mngt` bit 5: 1 = play money (avatar +0xd4 `glod`), 0 = credits (avatar +0xd0 `gold`) | [known] S 004712b0, S 00461470 |
| scene, spot | key `scntbl` low nibble = scene id of the tavern, high nibble = table spot (both select the table node of the scene) | [known] S 00471160, S 0051b950; spot range 0..14 [inferred] from the tavern scenes |
| seats | 8 records of 0x3c bytes at +0x24; a seat is occupied when its seat-index byte != 0xFF | [known] S 00471990 |
| seat `stack` (+0x34 in the seat) | wire `crdts`: the seat's chips at the table | [known] S 00471950 |
| seat `committedMoney` (+0x38) | wire `accnt`; only use: subtracted from the avatar's money to get the stake dialog's maximum (§3.2) | [known] S 00471930, S 00461470 |
| `localSeat` +0x208 | seat of the local player, -1 = not seated | [known] S 00471d10 |
| `lowestOccupiedSeat` +0x20c | lowest occupied seat index, -1 = none | [known] S 00471d10, S 00471c40 |
| primary seat | `localSeat` if seated, else `lowestOccupiedSeat`. Exactly one seat controller per table does the shared work (pawn-chess input and piece sync, pawn-chess payout animation) | [known] S 004715f0 |
| `occupiedCount` +0x210 | number of occupied seats | [known] S 00471d10, S 00471c40 |
| `phaseStartMs` +0x214 | `round(now_s * 1000 - (time & 0xffff) * 10)`; wire `time` is hundredths of a second. Written by Dice only when `phase` changes (S 00488e00), by Poker on **every** table state (S 004894a0), never by Pawn Chess (its state has no `time`; the constructor does not initialise the field) | [known] S 00471540 |
| phase elapsed | `max(0, now_ms - phaseStartMs)` | [known] S 004715a0 (disassembly) |
| `hasPassword` +0x218, `passwordCrc` +0x21c | from `psswd`, `psswdcrc` | [known] S 00471490 |
| `limitMin` +0x23c, `limitMax` +0x240 | `lmtmn`, `lmtmx`; default 0x7fffffff | [known] S 00471b70 |
| `maxPlayers` +0x244 | `mxplyr` (4 bits on the wire); default 0xFF | [known] S 00471490, S 00471b70 |
| `tableObject` +0x20 | the `CLobbyClient_MiniGame*` of the table, created by the first 0xD9 | [known] S 0046f380, S 005032b0 |

A seat occupant that is not a known avatar (actor type other than 1, or an avatar id the connection does not
know) gets a placeholder avatar and the name `npc %d` (seat index) [known] S 00471d10. A seat block that
names an avatar (actor type 1) which is unknown or has no 3D object yet is rejected as a whole: nothing of
that message is applied [known] S 00471f00. "Seat joined" is fired only once the table's seats are announced:
the first seat block with a non-zero entry count announces all occupied seats at once [known] S 00471f00,
S 00471eb0.

The clock used for every minigame timer is the client's own elapsed time since start
(`Timer_GetElapsedSecondsSinceStart`), not the village world clock [known] S 00471540.

### 2.2 Dice (`MiniGameDiceProxy`, 0x3f8 bytes)

| Offset | Type | Field | Meaning | Tag |
|---|---|---|---|---|
| +0x248 | ptr | `boardObject` | the 3D board object (`spielfeld`) | [known] S 0051b280 |
| +0x24c | 8 x 0x30 | `betRows[seat]` | `bets[11]` (i32; index k = bet on dice sum k + 2) followed by `payout` (i32) | [known] S 00488870, S 00488d60 |
| +0x3cc | i32 | `phase` | 0 at construction; 1 betting, 2 roll, 3 throw, 4 result | [known] S 00488b50, S 00524c10 |
| +0x3d0 | u8 | `dice` | low nibble = one die, high nibble = the other (1..6 expected; the client does not range-check) | [known] S 00488830 |
| +0x3d1 | u8 | `dealerSeat` | wire `dlr`: the seat that rolls; 0xFF at construction | [known] S 00488b50, S 00488e00 |
| +0x3d4 | u32 | `betUnit` | value of the chip button currently marked in the dialog (0 = none) | [known] S 00447950 |
| +0x3d8 | i32[4] | `seatAnchorMap` | {0, 2, 3, 1}: seat index -> seat node of the table model | [known] S 00488b50 |

Bet fields: 11 fields, field k <-> sum k + 2 (k = 0..10) [known] S 00488870. Dice seats: 0..3 (four chip
stack columns on the board, four anchors) [known] S 00518100; the proxy itself keeps 8 bet rows.

### 2.3 Poker (`MiniGamePokerProxy`, 0x548 bytes)

| Offset | Type | Field | Wire | Tag |
|---|---|---|---|---|
| +0x248 | 8 x 0x30 | `seats[8]` (`PokerSeatRecord`, below) | per-player block | [known] |
| +0x3c8 | u32 | `phase` | `phase` | [known] |
| +0x3cc | u8 | `round` | `round` (1 preflop, 2 flop, 3 turn, 4 river) | [known] S 00525300 |
| +0x3cd | i8 | `allInRunoutStart` | `egr` | [known] |
| +0x3ce | u8 | `potCount` | `ptncnt` & 0x7f | [known] S 004894a0 |
| +0x3cf | u8 | `dealerSeat` | `dlr` | [known] |
| +0x3d0 | u8 | `currentPlayer` | `crntplyr` | [known] |
| +0x3d1 | u8 | `lastPlayer` | `lstply` | [known] |
| +0x3d4 | u32 | `lastAction` | `lstactn` (starts as 1) | [known] S 00489dd0 |
| +0x3d8 | u32 | `lastValue` | `lstvl`; stored only together with a changed `lstply` / `lstactn` pair, zeroed when the event is popped | [known] S 004894a0, S 004892f0 |
| +0x3dc | u8 | `lastActionPending` | set when `lstply` or `lstactn` differs from the stored pair | [known] S 004894a0 |
| +0x3e0 | ptr | `boardObject` | the 3D board object (`pokertable4` / `pokertable8`) | [known] S 0051b950, S 00489dd0 |
| +0x3e4 | u16 | `allowedActions` | `actns` | [known] |
| +0x3e6 | u8[5] | `boardCards` | board `crd0..crd4`, 0xFF = none | [known] |
| +0x3eb | u8 | `showdownSeat` | `shwcrds` | [known] |
| +0x3ec | u32 | `minWager` | `minwgr` | [known] |
| +0x3f0 | u32 | `minRaise` | `mnrs` | [known] |
| +0x3f4 | 8 x 0x28 | `pots[8]`: `amount` u32, `eligibleMask` u8 (+4), `wagerMask` u8 (+5), `wagers[8]` u32 (+8) | pot block | [known] S 004894a0, S 00524f60 |
| +0x538, +0x53c | u32 x 2 | not named | zeroed by the constructor; no reader or other writer in the functions of this document | [known] store S 00489dd0, [TODO] use |
| +0x540 | i32 | `stateChangeCounter` | +1 for each of `crntplyr`, `phase`, `round` that changed in a message | [known] S 004894a0 |
| +0x544 | i32 | `answeredCounter` | -1 at construction; copy of `stateChangeCounter` at every 300 / 301 / 302 sent | [known] S 00489110, S 004891d0, S 00489340 |

Offsets without an address in the table are the fields `ReadTableState` S 004894a0 stores the named wire
field into [known]. The constructor S 00489dd0 sets `phase` 0, `dealerSeat` / `currentPlayer` / `lastPlayer`
0xFF, `lastAction` 1, the five board cards 0xFF, `minWager` / `minRaise` 0; it does not initialise `round`,
`allInRunoutStart`, `potCount`, `showdownSeat` or the pots [known].

`PokerSeatRecord` (0x30 bytes):

| Offset | Field | Meaning | Tag |
|---|---|---|---|
| +0x00, +0x01 | `card0`, `card1` | hole cards: 0..51, 0x34 = back, 0xFF = none | [known] |
| +0x02 | `action` (u16) | wire `actn` & 0x7ff: last action code | [known] S 004894a0 |
| +0x04 | `actnBit14` | wire `actn` bit 14; no reader found in the functions of this document | [known] store, [TODO] use |
| +0x05 | `actnBit15` | bit 15: "wait for next round" | [known] S 0044b3c0 |
| +0x06 | `actnBit13` | bit 13: "wait for next round" | [known] S 0044b3c0 |
| +0x07 | `sittingOut` | bit 12: sit-out marker on the board, blocks the turn, "wait for next round" | [known] S 005257f0, S 00489b80, S 0044b3c0 |
| +0x08 | `actnBit11` | bit 11: blocks the turn | [known] S 00489b80 |
| +0x0c | `wager` (u32) | the seat's bet pile of the current street (`wgrmsk` / `wgr`) | [known] |
| +0x10 | `handValue` (u32) | `hndval` | [known] |
| +0x14 | `seatText` (string) | pending speech-bubble text of the seat | [known] S 00489f30 |

Action codes (also the bits of `actns`) [known] S 00449870: CALL 2, FOLD 4, RAISE 8, CHECK 0x10, BET 0x20,
SMALLBLIND 0x40, BIGBLIND 0x80, ALLIN 0x100. Text keys `!MGPOKER_CALL`, `_FOLD`, `_RAISE`, `_CHECK`, `_BET`,
`_SMALLBLIND`, `_BIGBLIND`, `_ALLIN`; any other code gives an empty text.

Cards and the hand value encoding: `message-catalog.md` "Poker game" (card = rank + 13 * suit;
`hndval = category << 24 | n0 << 16 | n1 << 12 | n2 << 8 | n3 << 4 | n4`). Rank text key: `!MGPOKER_%d` with
the number `((hndval >> ((4 - i) * 4)) + 2 + offset) & 0xf` for nibble i [known] S 004482f0.

Hand text (`FormatHandValue`) [known] S 004484f0: "`<category text> (<ranks>)`", ranks joined with ", ". The
category text is the localisation of the key at index `hndval >> 24` of a key table in the dialog (+0xf2c;
[TODO] not established: the nine keys, set in the dialog constructor S 0044bf10). Ranks printed, as nibble
indices:

| Detail | Category | Ranks |
|---|---|---|
| 2 (used while `round == 1`) | 0 | n0, n1 |
| 2 | 1 | n0, n0 |
| 2 | any other | none (empty parentheses) |
| 5 | 0, 5 | n0, n1, n2, n3, n4 |
| 5 | 1 | n0, n0, n1, n2, n3 |
| 5 | 2 | n0, n0, n1, n1, n2 |
| 5 | 3 | n0, n0, n0, n1, n2 |
| 5 | 4, 8 | n0, n0-1, n0-2, n0-3, n0-4 (nibble 0 with offsets 0..-4) |
| 5 | 6 | n0, n0, n0, n1, n1 |
| 5 | 7 | n0, n0, n0, n0, n1 |
| 5 | above 8 | none |

Seats: 0..7. The table object is `pokertable4` at spots 0..12 and `pokertable8` at spots 13 and 14 [known]
S 0051b950.

### 2.4 Pawn Chess (`MiniGamePawnChessProxy`, 0x2bc bytes)

| Offset | Type | Field | Meaning | Tag |
|---|---|---|---|---|
| +0x248 | u16[16] | `pieceKeys` | per piece: bits 0-2 column, 3-5 row, 6 king, 7 side; bit 15 "marked" and bit 8 "capture square is row - 1" are added by the client from `pwchkmt` | [known] S 0048a6d0 |
| +0x268 | u8[64] | `board` | per square (index = col + row * 8): bits 0-3 piece index, bit 4 = empty (initial value 0x10), bit 6 = attacked by side 0, bit 7 = attacked by side 1 | [known] S 0048a6d0, S 0048a690 |
| +0x2a8 | u8 | `turnId` | wire `trnid` | [known] |
| +0x2a9 | u8 | `sentTurnId` | `turnId` at the time of the last 400 / 401 / 402; 0xFF at construction and on entering phase 1 or 6 | [known] S 0048a100, S 0048a6d0 |
| +0x2ac | i32 | `pendingCapturePiece` | index of the enemy pawn the player has clicked to take, -1 = none | [known] S 00526260 |
| +0x2b0 | i32 | `phase` | wire `phs` | [known] |
| +0x2b4 | u8 | `playerStateFlags` | wire `plrstt` (§3.5.5) | [known] |
| +0x2b5 | u8 | `bNewGameRequested` | 1 at construction and after a 403; 0 on entering phase 6 | [known] S 00489f60, S 0048a2a0, S 0048a6d0 |
| +0x2b8 | ptr | `boardObject` | the 3D board object (`pawnchesstable`) | [known] S 0051c040, S 00489f60 |

`turnId` is not initialised by the constructor; `pendingCapturePiece` is written only by the constructor
(-1), by the click that picks an enemy pawn, and by `SendCapture` (-1) [known] S 00489f60, S 0048a420,
S 00489fd0.

Board: 8 x 8, 16 pieces, all always on the board (there is no "captured" state). Side 0 moves towards
column 7, side 1 towards column 0 [known] S 00525d20. Seats 0 and 1 are the two sides (the side of a seat
is the seat index) [known] S 00526260.

Controller state (`CMiniGameControllerPawnChess_Actor`, 0x160 bytes): `selectedPiece` (-1 = none),
`movableSquares[16]` + `movableCount`, `targets[11]` + `targetCount` (target byte = square, bit 6 = attacked
square), `pieceOwnerCache[16]` (0xFF = never shown), `lastChangeCounter` (0xFF at construction), `lastPhase`,
`lastStakePhase`, `bStartSoundPlayed` (1 at construction) [known] S 005259c0.

### 2.5 Chips (`CChipGfxMgr`)

A board owns one chip manager. A **pile** (0x2d8 bytes) has a position, an integer `amount`, a label string,
a colour, a `hidden` flag, an animation mode (0 none, 1 and 2 = move to a target position, 3 = transfer to
other piles) with start and end time, and up to 8 transfer targets `{pileIndex, amount, amountMoved}` [known]
S 00520880, S 0051ef90, S 0051f0d0. A new pile has amount 0 and the colour (1, 1, 1, 1) [known] S 00520880,
data S 0087cd1c.

- Drawing an amount [known] S 0051fe80, data S 0087cd18: denominations {1, 5, 10, 25, 50, 100, 500, 1000,
  5000}; the chip count n is that of the greedy split (largest denomination first). Chips are stacked from
  the largest denomination upwards, 0.012 apart. At most 25 chips are drawn: while n > 25 the loop skips
  chips of the denomination it is at, starting with the largest (it skips `n - 25` of them if that
  denomination has enough, else all of that denomination), so the chips left out are the most valuable
  ones. A pile is drawn only if it is not hidden and its amount is > 0. The denomination index selects the
  chip's texture cell: u = `(index & 3) * 0.25`, v = `(index >> 2) * 0.25` [known] S 0051f150.
- Per-chip animation [known] S 0051f150. Each chip runs on its own clock: now + k * 100 ms (mode 3) or
  now + k * 50 ms (modes 1, 2) for the k-th chip drawn (k = 1 at the bottom); t = (clock - start) / (end -
  start) clamped to 0..1 and squared.
  - mode 1: the chip moves from the pile towards the target position by t, alpha = 1 - t;
  - mode 2: the chip rises by 0.1 * t, alpha = 1 - t (the target position is not used);
  - mode 3: one copy of the chip flies towards every target pile whose transfer amount is > 0; alpha 1
    until t reaches 1, then 0;
  - every mode plays sound 0x63c31100 once per started animation, as soon as a chip's t is > 0.
- A transfer (mode 3) raises each target pile's `amount` gradually between the start and end time (the
  target amount is increased by the part moved since the last frame; the source pile's `amount` is not
  reduced) [known] S 0051fe80; [TODO] not established: the exact progress formula of the amount (the
  converted value is not visible in the decompilation; read the disassembly around the float-to-int call).
  So the amounts shown during a transfer are computed by the client; the next table state overwrites them.
- A pile at rest (mode 0) gets a label "`<label> <amount>`" 0.03 above the pile, font
  `[data]\language\de\fonts\chapter_garamond` (S 005204b0), with alpha `(fadeEnd - cameraDistance) /
  (fadeEnd - fadeStart)` clamped to 0..1 from the CVars `Lobby.chipValueFadeStart` (3.0) and
  `Lobby.chipValueFadeEnd` (7.0), both 0..100; CVar `Lobby.renderChipStackValues` (true) switches the
  labels [known] S 00520200, S 0051f010, data S 0087cd2c..0087cd34.
- `SetPileAmount` plays sound 0x63c31103 when an amount grows and 0x63c31107 when it shrinks, at the
  manager's sound position and only if a sound player is attached [known] S 0051ee30.

### 2.6 Dialog state

- `MinigameDialog` (base): the table proxy, a chat-style log (`nUi::ChatSystem`), 6 log colours (24 floats,
  four per colour, copied from S 0087afa4..0087b000), a list of delayed log lines `{dueTime (ms, u64),
  colour index, text, sound id}`, widgets `leaveButton`, `helpButton`, the stake ("account") button and the
  stack text [known] S 00461b70.
  Log line calls: vtbl+0x9c `AddLogLine(soundId, colour, text)`: plays the sound through the table client if
  `soundId != 0`, then adds the text to chat tab 3 of the log in colour `colours[colour]`; vtbl+0xa0 the
  printf form; vtbl+0x98 the delayed form [known] S 00461370, S 00461d90. Colour indices used: 0 seat
  joined / left, 2 pot headline, 3 pot winner, 5 Dice and Pawn Chess lines [known] at the call sites of §3.
- `MinigameDialog_Dice`: five chip buttons with the values {1, 5, 10, 25, 100} (data S 0087a580), cached
  phase, result latch, two dice pictures and a countdown picture [known] S 00446a60.
- `MinigameDialog_Poker`: three action button slots (button, action code, two text widgets; 16 bytes per
  slot), `chosenWager` (-1 = unset), lower wager bound, wager edit box, slider, +/- buttons, sit-out toggle
  (`enabled`, starts 0), latches `dealLogged`, `potResultsLogged`, `tenSecondsWarned`,
  `lastCountdownSecond` [known] S 0044b3c0, S 0044aea0, S 004483b0.
- `MinigameDialog_PawnChess`: `newGameButton`, `lastAnnouncedState` (last `turnId` announced),
  `resultEventLatch` [known] S 0044cd10.
- `MiniGameMatchMakingDialog`: `phase` (1 select, 2 create, 3 join), `filterMode` (0 browse, 1 create at a
  spot, 2 join one table), `tavernId`, `tableKind` (clicked spot, 0xFF from an NPC), `gameTypeFilter`,
  `createGameType`, `playerCount` with `minPlayerCount` / `maxPlayerCount`, `betIndex` with `maxBetIndex` and
  a list of five minimum stakes at +0xba8, `usePlayMoney`, `credits`, `playMoney`, game name, password,
  `selectedTableKey`, `enteredPasswordCrc`, `pendingMode` (1 create, 2 join) [known] S 00444cb0, S 00444790.

---

## 3. Rules and algorithms

### 3.1 Table life cycle on the client

1. 0xDA creates the proxy by game type. The first 0xD9 for it fires the connection's "table shown" list;
   `CLobbyClient::OnMiniGameTableShown` creates the table client: type 1 `CLobbyClient_MiniGame_Dice`,
   2 `_Poker`, 3 `_PawnChess` (each 0x1c bytes), stored in the proxy's `tableObject` [known] S 005032b0.
2. The table client's constructor spawns the board object at the table spot's node (`slot:NN_c` of the
   tavern scene, `lobby-world-client.md`): Dice object `spielfeld` (class group `dice`), Poker `pokertable4`
   (spot < 13) or `pokertable8` (group `poker`), Pawn Chess `pawnchesstable` (group `pawnchess`), and stores
   it in the proxy's `boardObject`. Dice and Poker also push a board controller
   (`CMiniGameControllerDice_Board` 0x34 bytes, `CMiniGameControllerPoker_Board` 0x38 bytes) onto the board
   object; Pawn Chess has no board controller [known] S 0051b280, S 0051b950, S 0051c040.
3. Seat joined (`OnSeatJoined(seat)`), all three games [known] S 0051b710, S 0051be10, S 0051c240:
   - if the seat is the local player: `EnterTableView` (below) and `CLobby::SetViewMode(2)`;
   - push a seat controller onto the occupant's avatar object: `CMiniGameControllerDice_Actor` (0x188 bytes),
     `CMiniGameControllerPoker_Actor` (0x128), `CMiniGameControllerPawnChess_Actor` (0x160);
   - if the local player sits at this table (and its dialog exists): log line "`<name> ` + text of
     `!Player joined game`" (colour 0, no sound).
4. Seat left (`OnSeatLeft(seat)`): pop and delete the seat controller; if the local player sits at the table,
   log "`<name> ` + `!Player left game`"; if the seat was the local player's: `LeaveTableView` and
   `SetViewMode(1)` [known] S 0051b4f0 (Dice), S 0051bc10 (Poker and Pawn Chess).
5. `EnterTableView`: `WorldScreen::EnterMiniGameMode(table)` (opens the game's dialog, `lobby-screens.md`
   §3.17), join the table's chat channel (`chtid`) on the chat connection, subscribe to the world screen's
   deactivate and leave lists (they only clear the stored dialog pointer). Dice additionally sets
   `LobbyAction::SetMouseLookButtonMode(1)` (mouse look on the middle button only) [known] S 0051b670,
   S 0051bd90. `LeaveTableView` undoes all of it (Dice: mode 0) [known] S 0051b440, S 0051c1b0.
6. 0xD8 removes the table: seats are cleared, the table client and the board are destroyed
   (`message-catalog.md`).

A seat is taken or left **only** by a seat block of a table state (0xD9; a 0xDA runs the same reader, but
must not carry occupants, `message-catalog.md`), by the removal of the table (0xD8) or by the village
connection logging out or dropping, which clear all eight seats; the client never seats or unseats itself
[known] S 00471f00, S 00471410, S 0046f510, S 0046fd10. A seat listed with a different occupant is cleared
and then set; an occupied seat that the block does not list is cleared [known] S 00471f00.

Seat controllers and cameras [known] S 00526800, S 00523f90, S 00525670, S 005259c0 (parameters of
`OrbitCameraRig`: distance, zoom speed, min distance, max distance, pitch, yaw, pitch min, pitch max, yaw
min, yaw max; angles in radians):

| Controller | camera mode | rig |
|---|---|---|
| Dice seat, Poker seat | 1 | 1.0, 0.25, 0.4, 1.0, 0.7854, 1.5708, -0.6109, 0.6109, 0.3491, 2.7925 |
| Pawn Chess seat | 0 | 2.2, 0.25, 1.0, 3.0, 0.7854, 1.5708, 0.2618, 1.5010, 0.7854, 2.3562 |
| observer (seat -1) | 2 | same numbers as Pawn Chess, placed at the local avatar's position |

Every controller has a second rig (1.0, 0.25, 0.4, 1.0, 1.5010, 1.5708, 0.2618, 1.5010, -62.83, 62.83)
[known] S 00526800; it is the one the observer camera (mode 2) uses, aimed 1.5 above the table node [known]
S 005269e0. The rig clamps pitch and yaw to their ranges on every update (pitch += mouse dy / 300, yaw +=
mouse dx / 150), so the Dice / Poker start pitch 0.7854 becomes 0.6109 on the first update [known]
S 00522f20, [inferred] for the first update.

Seated avatars of all three games play the animation `SitChair` at speed 1.0 and are placed on the seat
node `seatAnchor` of the table spot (the three seat controller classes share this function in vtable slot
1) [known] S 00524ae0, vtables S 007e77cc, S 007e7878, S 007e78a0. The seat node index is the proxy's
virtual slot 2, called once in the controller constructor [known] S 00526800:

| Game | Seat node index | Tag |
|---|---|---|
| Dice | `seatAnchorMap[seat]` = {0, 2, 3, 1} | [known] S 00488de0 |
| Poker | the seat index (base implementation: the seat record's index byte) | [known] S 00471890, vtable S 007de740 |
| Pawn Chess | `seat * 2` (seat 0 -> node 0, seat 1 -> node 2) | [known] S 0048a290, vtable S 007de76c |

### 3.2 Finding, creating and joining a table

Opening and the list filter: `message-catalog.md` "Matchmaking dialog and tavern ids". Client rules on top
of that:

- **Game list** [known] S 00444610: entries 0 (all games; only in browse mode), 1 Dice, 2 Poker, 3 Pawn
  Chess; names from the key table `g_MinigameNameKeys`. At a spot >= 13 the list holds Poker only.
- **Player count** when a game type is selected [known] S 00444790:

  | Game | min | max | default |
  |---|---|---|---|
  | Dice | 1 | 4 | 4 |
  | Poker, opened from an NPC (spot 0xFF) | 2 | 8 | 4 |
  | Poker at a spot 0..12 | 2 | 4 | 4 |
  | Poker at a spot 13, 14 | 5 | 8 | 8 |
  | Pawn Chess | 2 | 2 | 2 |

  Info texts `!MGMMDLG_INFO_DICE`, `_POKER`, `_CHESS`.
- **Minimum stake list** (`lmtmn` of the new table) [known] S 00443100: Dice {1} only; Poker {2, 10, 50, 100,
  250}; Pawn Chess {1, 10, 50, 100, 250}; the selected index is clamped to the list when the create page
  opens. `lmtmx` is always sent as 0x7fffffff [known] S 00442f00.
- **Currency**: either arrow button toggles `usePlayMoney` [known] S 00444790.
- **Default table name**: the local avatar's name (per game type, `GetLocalAvatarName`) is put into the name
  box when a game type is selected, and used again when the name box is empty at Start [known] S 00444790,
  S 00444330.
- **Buttons** [known] S 00443eb0, S 00445cf0, S 00444790: phase 1: Create (`!MGMMDLG_ACTIONCREATE`, enabled
  when a game type other than "all" is selected; goes to phase 2) and, in browse mode, Search
  (`!MGMMDLG_ACTIONSEARCH`; goes to phase 3); phase 2: Cancel (back to phase 1) and Start
  (`!MGMMDLG_ACTIONSTART`, enabled when the chosen minimum stake <= the player's money in the chosen
  currency); phase 3: Cancel (browse mode only; back to phase 1) and Join (`!MGMMDLG_ACTIONJOIN`). **Join is
  enabled** only when a row is selected, `occupiedCount < maxPlayers`, and the player's money in the table's
  currency is >= the table's `limitMin`. The first row is selected when none is.
- **Password** [known] S 00444330, S 004432a0: joining a table with `hasPassword` opens
  `EnterPasswordDialog`; a table without it is treated as if CRC 0 had been typed. The CRC is compared with
  the table's `passwordCrc` on the client; a mismatch shows the box `!ERROR_DIALOG` / `!Invalid password`,
  sends nothing and shows the matchmaking dialog again. So a table without a password must carry
  `psswdcrc` = 0 or it cannot be joined [inferred].
- **Buy-in** (`SetStackDialog`), for create and join [known] S 00444330, S 004432a0: minimum = the table's
  minimum stake, maximum = the player's money in the table's currency, initial value = 10 x the minimum,
  clamped to the maximum (if 10 x overflows, the minimum itself). Ok sends 2001 CreateMiniGameTable
  (create) or 209 JoinTable (join, with the typed CRC) with the chosen stake; never both; a join whose table
  has disappeared meanwhile sends nothing [known] S 00442f00. Cancel shows the matchmaking dialog again.
- **Top-up at the table** (`MinigameDialog::OpenSetStackDialog`) [known] S 00461470: minimum = `limitMin`,
  maximum = avatar money in the table's currency - the local seat's `accnt`, initial = 10 x `limitMin`
  clamped to that maximum (`limitMin` itself if 10 x overflows). Ok sends 222 Amount with the value (§5.1).
  When the top-up button is offered (it then has opacity 1 and the headline is replaced):
  - Dice: local stack == 0 (headline `!MGCOMMON_NOMONEY`) [known] S 00447950;
  - Poker: the local seat is in no pot's `eligibleMask` and `stack + street wager < limitMin` (headline
    `!MGCOMMON_NOMONEY`) [known] S 0044a910;
  - Pawn Chess: `stack < limitMin` and phase is 1 or 6 (headline `!MGCOMMON_NOMONEY`) [known] S 0044cd10.
  Otherwise the button is disabled at opacity 0.5.
- **Leave**: the dialog's leave button sends 204 LeaveTable; the client leaves the table view only when a
  later 0xD9 omits its seat [known] S 004613c0, S 0051b4f0. **Help** opens `MiniGameManualDialog` for the
  table's game type.
- The matchmaking dialog registers a distance watch (radius argument 2.0) with the lobby when shown and
  cancels itself when the watch fires (the player walked away) [known] S 00444cb0, S 00443090.

### 3.3 Dice

#### 3.3.1 Phases

| Phase | Local seat | Other seats | Board | Dialog headline |
|---|---|---|---|---|
| 1 betting | on entry: bet fields lit, cup alpha 1 with the dice hidden; clicks place and remove chips (§3.3.2) | on entry: cup alpha 1 with the dice hidden | on entry: dice result cleared, all chip stack animations reset | `!MGDICE_HEAD_PHASEBET` with `max(0, 15000 - elapsed) / 1000` seconds; dice pictures blank |
| 2 roll | on entry: fields unlit, hover cleared; if the local seat is `dlr`: cursor hidden, the cup follows the mouse, a click sends 221 Roll | the `dlr` seat's cup is drawn at the table node + (0.1, 0.3, 0) | | local roller: `!MGDICE_HEAD_PHASEDICE_DEALER`; else "`<roller name> ` + `!MGDICE_HEAD_PHASEDICE_OTHER`"; dice pictures blank |
| 3 throw | cursor shown again; if the local seat is `dlr`: cup animation (§3.3.4) | the same animation by the `dlr` seat's controller | | empty; the two dice pictures show the result once elapsed > 500 ms (sprite x = `(die - 1) * 56`, y = 88) |
| 4 result | | | on entry: chip result animation with the dice sum (§3.3.4) | "X won" (§3.3.3) |

[known] S 00524c10, S 00523d60, S 00523d90, S 00523ee0, S 00523f10, S 00524aa0 (seat controller),
S 00523c10 (board controller), S 004471d0 (dialog). A seat controller does nothing in any other phase
value. The countdown of phase 1 is display only: the client sends nothing when it reaches 0, and it has no
timer at all for phases 2 to 4.

The board always shows the roller marker at seat `dlr` (`SetActiveSeat` every frame), so `dlr` must be a
valid seat in every state (`message-catalog.md`).

#### 3.3.2 Betting (client-enforced)

Per frame in phase 1, for the local seat [known] S 00523db0, S 00447950:

1. `betUnit` = value of the marked chip button, 0 if none is marked; if several are marked, the last one in
   button order counts (buttons {1, 5, 10, 25, 100}, data S 0087a580; in phase 1 a button is enabled only
   while its value <= `stack - sum(bets)`; in phases 2 to 4 all are disabled; disabled buttons are drawn at
   opacity 0.7, enabled ones at 1.0; in any other phase value the buttons are left as they are) [known]
   S 00446a60, S 00447950. The dialog unmarks all five buttons in a frame in which one of them is being
   operated, which makes them a radio group [inferred from the widget flags tested at S 00447950]. Disabling
   a button does not unmark it, so `betUnit` can exceed what is left; the add test of step 3 still holds.
2. The bet field under the mouse ray is picked: the ray is tested against the boxes of the 11 fields that
   have flag 4 (set by `SetBetFieldsLit`, i.e. lit), the nearest hit wins, no hit = none [known] S 00517000;
   [inferred] flag 4 = lit.
3. "Add" input (left click) with `betUnit > 0` on a field: accepted only if `sum(bets) + betUnit <= stack`;
   then `bets[field] += betUnit` and 220 PlaceBets is sent. A refused add does nothing.
4. Else "remove" input (right click) on a field: `bets[field] -= min(betUnit, bets[field])` and 220 is
   sent, also when the bet did not change (bet 0 or `betUnit` 0).
5. With neither input in this frame: the picked field is highlighted (no field: highlight cleared).

220 PlaceBets carries the seat's `crdts` as last received and all 11 bets [known] S 00488be0.

The two inputs are `LobbyAction` vtbl+0x4c and +0x50 (vtable S 007d6824): the left and the right mouse
button (virtual keys 1 and 2) through the edge query `IsKeyTriggered(vk, 0)`, which is true only while the
button's key-state entry is -1 [known] S 00491130, S 00491150, S 00491040; [inferred] -1 marks the frame in
which the button is released, so each click counts once. The same two predicates select and block in Pawn
Chess (§3.5.4).

The bets are local state: the stack shown (dialog and chip pile) is `stack - sum(bets)`; `crdts` is the
whole stack, bets included [known] S 00524c10, S 00447950.

Receiving a table state [known] S 00488e00: for each listed player `crdts`, `accnt` and 11 bets are read.
The bets are **discarded for the local seat while the phase stored before this message is 1**, so the
server's echo never overwrites clicks made during betting; the phase is updated after the players are read.
Consequences [inferred]: the message that moves 1 -> 2 still keeps the local bets; the message that enters
phase 1 (stored phase 4) overwrites the local bets with the server's values. A seat (re)joining or leaving
has its bets and payout zeroed [known] S 00488a60, S 00488aa0.

#### 3.3.3 Payout (client-computed)

On the transition into phase 3 the client computes every occupied seat's payout from its bets and the dice
sum `(dice >> 4) + (dice & 0xf)`; unoccupied seats get 0 [known] S 00488d60, S 00488870:

- group A = sums {2, 4, 6, 9, 11}, group B = sums {3, 5, 8, 10, 12};
- sum in group A: payout = sum over the five A fields of `bet * (5 if field == sum else 1)`;
- sum in group B: the same over the five B fields;
- sum 7: payout = (bet on 7) * 3, i.e. `bets[5] * 3`;
- bets on the other group (and on 7) return nothing; any other sum value gives 0.

The payout is the amount that comes back, stakes included; it is never negative. The dialog shows it in
phase 4 as `!MGDICE_HEAD_XCREDITSWON` / `!MGDICE_HEAD_XFUNNIESWON` with that amount (not the net result) and
plays sound 0x63c31108 once, or 0x63c31109 if the payout is 0. The branch for a negative value
(`!MGDICE_HEAD_XCREDITSLOST` / `XFUNNIESLOST`, sound 0x63c31109) exists but cannot be reached from this
formula [known] S 004471d0, [inferred] unreachability. Log lines (colour 5, no sound): on entering phase 3
`!MGDICE_LOG_DICERESULT` (low-nibble die, high-nibble die, sum); on entering phase 4
"`<local name>: <payout>`" [known] S 00446bd0, S 00446a10.

The client does not change `stack` from the payout: the new stack must come in a later table state.

#### 3.3.4 Animations and timing

- Roll (phase 2, local roller) [known] S 00524420: the cup is placed where the mouse ray meets the
  horizontal plane 0.4 above the table node, limited to a radius of 0.3 around the node; each reversal of the
  movement direction plays one of six shake sounds (0x63c31000 + rand % 6). 221 Roll is sent on **every frame
  the left-click predicate is true** (once per click, §3.3.2); the proxy keeps no "already rolled" latch, so
  every further click in phase 2 sends another 221.
- Throw (phase 3, the `dlr` seat's controller) [known] S 00524170, S 005248b0, S 005241f0: on entry the
  table node's pose is stored as the target. t = elapsed / 500 ms, limited to 2. t < 1: the cup flies from
  its last position to the target, x and z linear in t, height on an arc above the target. At t >= 1
  (500 ms), once: the dice are placed with the result faces up (sound 0x63c3110a). From 500 ms to 750 ms
  the cup rests at the target; from 750 ms to 1000 ms it moves back along the same path to its half-way
  point and fades out (alpha 1 -> 0). After 1000 ms nothing changes.
- Dice placement (`SetDiceResult`) [known] S 005175d0: each die gets a random yaw (`rand() / 32768` times a
  constant at S 00882840, [inferred] 2 pi) and the local position (sin(a) * 0.04, 0.14, cos(a) * 0.04);
  [inferred] a is the value the throw passes per die, `rand() / 4096` for the first and that + 2 +
  `rand() / 16384` for the second (the argument of the sine is not visible in the decompilation). The
  face-up rotation of the die's value is applied on top. Bet fields are
  tinted through two flag bits: the sum's field gets value 2, the other fields of its group value 1; a 7
  marks only field 7 (value 2); all are cleared first, and a call with dice (0, 0) only clears.
- Result (phase 4, board) [known] S 00518100, S 00523c10: for each of the 4 seat columns and 11 fields
  whose pile is not empty: a pile on a winning field (same group as the sum, or field 7 on a 7) gets pile
  animation mode 1 (flies to the target and fades, §2.5), a pile on a losing field mode 2 (rises 0.1 and
  fades) plus the effect `MGDice_Smoke` started at +2000 ms; both modes are given the centre of that
  seat's stack node as target; the pile on the exact sum also gets the effect `MGDice_Won` at once; all
  pile animations run from **+2000 ms to +3000 ms**, counted from the frame in which the board controller
  first sees phase 4 (not from the server's `time`).

So a server should hold phase 3 for at least 1 s and phase 4 for at least 3 s for the animations to finish
[inferred].

### 3.4 Poker

#### 3.4.1 What the client does per phase

Only phases 1, 5, 6, 8 and 9 have behaviour of their own [known] S 00525550, S 00525300, S 0044b3c0:

| Phase | Board | Dialog |
|---|---|---|
| 1 | cards placed statically by `round`; bet piles of empty seats cleared | status line `!MGCOMMON_WAITFORPLAYERS` while `round < 2` (any other phase below 6 with `round < 2`: empty) |
| 5 deal | once per entry: deal animation by `round` (§3.4.6) | once per entry: delayed log lines for the street (§3.4.6) |
| 6 betting | current-player marker at `crntplyr` (no marker in any other phase) | |
| 8 collect | once: each seat's bets fly into the pots (§3.4.5); seat bet piles are not refreshed from `wager` | |
| 9 payout | once: pots fly to the winners (§3.4.4); stack piles are not refreshed from `crdts` in this phase; bet piles of empty seats cleared (also for any phase above 9) | once: pot result log lines |
| every value except 8 and 9 | on the change into it: pot piles set from the pot amounts | |

The dialog's buttons, wager controls and countdown do not depend on `phase`: they follow the turn test of
§3.4.2. The "once" of phases 5 and 9 in the dialog and of phase 5 on the board are latches that are cleared
by any frame in another phase; the board's phase 8 and 9 animations run on the change of `phase`.

In every phase and frame: dealer button at `dlr`; each seat's hole cards and sit-out marker; stack pile =
seat `crdts` (not in phase 9); bet pile = the seat's `wager` (not in phase 8); empty seats show no cards and
no stack [known] S 005257f0, S 00525550.

The values 2, 3, 4 and 7 of `phase` have no behaviour of their own. For static card placement (every phase
but 5), phases below 5 show one street less than `round` (round 1 or any value outside 1..4 -> no hole cards
at all, 2 -> hole cards only, 3 -> hole cards + 3 board cards, 4 -> + 4), phases above 5 show the street of
`round` (1 -> hole cards, 2 -> + 3, 3 -> + 4, 4 -> + 5 board cards; another value leaves the cards as they
are) [known] S 00525300. Statically placed hole cards lie face up only for seats in the board's face-up mask
(§3.4.3); a card that is in a reveal flip is left alone; board cards are always face up [known] S 005138f0.

#### 3.4.2 The local turn

`IsLocalPlayersTurn` [known] S 00489b80: `crntplyr == localSeat` and `answeredCounter != stateChangeCounter`
and the seat's `sittingOut` (bit 12) and bit 11 are clear. `phase` is not part of the test.

- Sending 300, 301 **or 302** sets `answeredCounter = stateChangeCounter`: the buttons disappear until a
  table state changes `crntplyr`, `phase` or `round`. A state with those three unchanged does not give the
  buttons back.
- Buttons [known] S 0044b3c0, S 00449a30: every frame all three slots are reset to code 1 (hidden); on the
  local turn they are filled from `actns` in the order RAISE 8, BET 0x20, FOLD 4, CALL 2, CHECK 0x10, ALLIN
  0x100; three slots exist and the fill is not bounds-checked (a fourth and fifth code are written behind
  the slot array). The bits SMALLBLIND 0x40 and BIGBLIND 0x80 never fill a slot, although the slot drawing
  knows their labels. Labels: CALL shows `minwgr - own street wager`; RAISE and BET show `chosenWager`; the
  others no amount.
- Click [known] S 004483b0: BET and RAISE send 301 with `wgr = chosenWager`; every other code sends 300
  with the code as `actn`; a slot with code 1 sends nothing.
- Wager controls (only on the local turn) [known] S 0044aea0: lower bound L = `minwgr` if BET is allowed,
  `minwgr + mnrs` if RAISE is allowed (RAISE wins if both), else -1. If L > 0: upper bound U = `stack + own
  street wager`; `chosenWager` starts at L; the edit box (applied on the chat-send key while focused, and
  read every frame), the slider and the +/- buttons (step 1; + enabled while `chosenWager < U`, - while
  `chosenWager > L`) change it; it is clamped to [L, U]. If L <= 0 the controls are hidden and
  `chosenWager` stays -1 (sent as 0xFFFFFFFF if a BET / RAISE button is clicked anyway), so BET must come
  with `minwgr > 0`. Off turn: `chosenWager = -1`, controls hidden.
- So `wgr` is the **total the seat's street bet is raised to**, not an increment [inferred from L and U].
- Countdown [known] S 0044b3c0: only on the local turn and only if `actns & 0x13e != 0`. While elapsed <=
  5000 ms nothing is shown. After that: once per turn the log line `!MG_POKER_TEN_SECONDS_LEFT` and the
  countdown picture is shown; remaining = `max(0, 15000 - elapsed)`; the picture's digit is `remaining /
  1000` (sprite offset 56 px per digit), a tick sound plays when the digit changes, and the picture's
  opacity and size follow `|sin(remaining / 1000 * pi)|`. `elapsed` is the phase clock, which Poker resets
  from `time` with **every** table state (§2.1), so a state sent during a turn moves the countdown to its
  `time`. The client **never acts on the timeout**.
- Sit out [known] S 004483b0: the toggle flips `enabled`, marks the button accordingly and sends 302 with
  the new value (first click sends 1). [inferred] The dialog's `enabled` is not set from the table state
  (no such store in the dialog functions of §12).
- Status line when `round >= 2` or `phase >= 6` [known] S 0044b3c0: if the local seat has bit 15, bit 13
  or bit 12 set: `!MGCOMMON_WAITNEXTROUND`; else, if the local seat's two cards are not both 0xFF:
  `!MGPOKER_HANDVALUEPREFIX` + the formatted local `hndval` (detail 2 for `round == 1`, detail 5 otherwise,
  §2.3); else empty.

#### 3.4.3 Cards and hand values: who knows what

- The client **never evaluates a hand**. `hndval` arrives per seat in the table state (only when that seat's
  `trsfcrds` = 1) and for the local seat in 303 MiniGameHand [known] S 004894a0, S 00489410.
- With `trsfcrds` = 0: a non-local seat gets `card0 = card1 = 0x34` (backs) and `handValue = 0`; the local
  seat keeps the cards and value of its last 303 [known] S 004894a0.
- 303 is ignored (discarded) when the local player has no seat at that table [known] S 00489410.
- A seat that (re)joins or leaves has its cards set to 0xFF [known] S 00489c40, S 00489ca0.
- Hole cards are drawn face up only for the local seat (`faceUpSeatMask = 1 << localSeat`) until a reveal
  [known] S 005134b0, S 00513c10.

#### 3.4.4 Pot winners (client-computed, display only)

On entering phase 9, for each pot from the last to the first, skipping pots with amount 0 [known]
S 005250f0 (board), S 0044a3e0 (log):

1. best = 0, winners = {}. For seat 0..7 in `eligibleMask` (`plrmsk`): if `handValue == best` append the
   seat; else if `handValue > best` the seat becomes the only winner and best = its value.
2. share = `amount / winnerCount` (unsigned integer division; the remainder is not shown anywhere).
3. Board (times from the phase start): unless `shwcrds == 0xFE`, the winners' hole cards that are still
   face down are flipped face up (500 ms); 1000 ms later the pot pile is transferred to the winners' stack
   piles, `share` each, over 750 ms; the next pot starts another 1000 ms later. Before the pots, the seat
   `shwcrds` (unless 0xFE or 0xFF) is flipped face up. A pot whose mask names no seat is skipped without
   using time.
4. Log (delayed lines, colour 2 for the pot and 3 for a winner, times from the client's time at that
   frame): per pot at +1000 ms `!MGPOKER_MAINPOT` (pot 0) or "`!MGPOKER_SIDEPOT` n" (n = pot index), also for
   a pot without a winner; then per winner, 1 ms apart: with `shwcrds == 0xFE` "`<name>, <share>`",
   otherwise `!MGPOKER_WINRESULT` (name, share, formatted hand value; detail 2 when `round == 1`, else 5);
   +1000 ms before the next pot.

Because the comparison starts at 0, every eligible seat counts as a winner when all eligible seats have
`handValue` 0. A server that wants one winner shown must either send that pot's `plrmsk` with one seat or
send the seats' `hndval` (`trsfcrds` = 1) in the phase 9 state [inferred].

The client does not change `crdts` from this: the stacks after the hand must come in a table state.

#### 3.4.5 Bets into pots (phase 8)

On entering phase 8 [known] S 00524f60, S 00514110: for each seat, for each pot whose `wagerMask`
(`wgrplrmsk`) has the seat: the seat's `wagers[seat]` of that pot is taken out of the displayed pot amount
and transferred from the seat's bet pile to that pot's pile over 750 ms (start = phase start). The seat's
bet pile is set to the sum of its per-pot wagers (0 without them), and each pot pile to its amount minus
all wagers into it. So the pot amounts sent in the phase 8 state must already contain the street's bets,
and the per-pot wagers (`ptncnt` bit 7) must be present, or nothing moves and the bet piles vanish.

#### 3.4.6 Deal animation and log timing (phase 5)

Board, on entering phase 5 (start time = phase start, so a late joiner sees the remainder) [known]
S 00525300, S 00513e20, S 00513ce0:

| `round` | Animation |
|---|---|
| 1 | hole cards: two passes over the board's seats in seat order, only occupied seats (the cards of the others are hidden); each card flies from the deck to the seat in 700 ms, started 350 ms after the previous one; face up only for seats in the face-up mask |
| 2 | board cards 0..2, each 700 ms, 350 ms apart |
| 3 | board card 3 |
| 4 | `egr` = 1: board cards 0..4; `egr` = 2: cards 3..4; otherwise card 4 |

Dialog log, once per phase 5 entry, as delayed lines relative to the client's time at that frame [known]
S 0044b3c0:

| `round` | Line and delay |
|---|---|
| 1 | preflop line (`LogPreflop`) at `(occupiedCount + 1) * 700` ms |
| 2 | flop line at 1200 ms |
| 3 | turn line at 1200 ms |
| 4 | `egr` = 1: flop at 1200, turn at 1700, river at 2200 ms; `egr` = 2: turn at 1200, river at 1700 ms; else river at 1200 ms |

#### 3.4.7 Speech bubbles and action log

When a table state changes `lstply` or `lstactn`, and `lstply != 0xFF`, the dialog pops the event once
[known] S 004892f0, S 0044b3c0: text = action text (§2.3), plus " `lstvl`" if `lstvl != 0`; it is logged
(the arguments of the log call, seat name and colour, are not visible in the decompilation: [inferred]) and
stored as the seat's `seatText`, which the seat's controller shows once as a label over that seat on the
board [known] S 00489f30, S 005257f0. A seat joining as the local player clears a pending event [known]
S 00489c40.

### 3.5 Pawn Chess

#### 3.5.1 Phases

| `phs` | Meaning | Whose input | Pieces shown | Stakes shown (stack / bet pile) |
|---|---|---|---|---|
| 1 | waiting for players | none | none | seat stack / 0 |
| 2 | seat 0 places its king | seat 0 | none | seat stack / 0 |
| 3 | seat 1 places its king | seat 1 | **piece index 0 only** | seat 0: stack / `limitMin`; seat 1: stack / 0 |
| 4 | seat 0 moves | seat 0 | all 16 | both: stack / `limitMin`; start sound 0x63c31111 once |
| 5 | seat 1 moves | seat 1 | all 16 | as 4 |
| 6 | game over | none | all 16 | both bet piles are transferred to the winner's stack pile over 1000 ms |

[known] S 00526260 (input gate and stakes), S 00525f20 (pieces shown), S 0048a260 (phase -> side),
S 00511680 (payout). The bet piles show the table's `limitMin`, not a value from the wire. Details:

- Every seat controller sets its own seat's two piles, and only in the frame in which it first sees a new
  phase value: the stack pile shows `crdts` as it was then and is not refreshed while the phase stays. In
  phase 6 no pile is set; only the primary seat's controller starts the transfer, timed from that frame.
- The start sound is played by a controller on its first phase 4 or 5 after it has seen phase 1, 2, 3 or
  6; a controller created while the game is already in phase 4 or 5 plays none.
- The pieces are re-synchronised by the primary seat's controller only, when `trnid` or the phase differs
  from its cached pair; a phase value of 0 or above 6 shows all 16.

Dialog headline:
1 `!MGCOMMON_WAITFORPLAYERS`; 2 / 3 own turn `!MGCHESS_PLACEOWNKING`, else "`<name> ` +
`!MGCHESS_PLACEOTHERKING`"; 4 / 5 own turn `!MGCHESS_YOURTURN`, or `!MGCHESS_CAPTUREPAWN` while a capture is
pending, else "`<name> ` + `!MGCHESS_OTHERTURN`"; 6 `!MGCOMMON_WIN` (sound 0x63c31105) or `!MGCOMMON_LOOSE`
(sound 0x63c31106, each once per phase 6) [known] S 0044caf0, S 0044c7e0, S 0044c940. "Own turn" is
`localSeat` == side of the phase [known] S 0048a440.

Piece 0 being the only piece shown in phase 3 means the original layout had seat 0's king at piece index 0
[inferred]; the piece order is otherwise free, the client looks pieces up by square.

#### 3.5.2 Input gate and the turn lock

The seat controller accepts input only when all of these hold [known] S 00526260:

- its seat is the primary seat and the local player's seat;
- its seat is the side of the phase (2, 4 -> 0; 3, 5 -> 1);
- `sentTurnId != turnId`.

Every 400, 401 and 402 sets `sentTurnId = turnId`. So after any action the board is locked until a table
state carries a different `trnid`; entering phase 1 or 6 resets `sentTurnId` to 0xFF. A server must answer
every action, accepted or not, with a new `trnid` that is never 0xFF, or the player can never move again.

When the gate is closed the highlights are cleared and the selection is dropped (`selectedPiece = -1`);
`pendingCapturePiece` is **not** reset (§3.5.4).

#### 3.5.3 King placement (phases 2, 3)

The 8 squares of the side's home column are offered: square = `row * 8 + (0 for seat 0, 7 for seat 1)`. A
left click on one of them sends 402 PlaceKing with `posy` = row; a click on any other square only plays the
click sound; without a click the square under the mouse is hover-highlighted [known] S 005260f0.

#### 3.5.4 Move generation (phases 4, 5; client-enforced)

The client derives from each state [known] S 0048a6d0:

- `board[square]` = piece index for the 16 `pwnps` (squares must be distinct);
- attack bits: a **pawn** of side s at (c, r) attacks (c + d, r - 1) and (c + d, r + 1), d = +1 for side 0,
  -1 for side 1; a **king** attacks its 8 neighbours. Bit 6 = attacked by side 0, bit 7 = by side 1;
- the marked pawn: if `pwchkmt != 0xFF`, piece `pwchkmt & 0xf` gets "marked" and, if `pwchkmt & 0x10`, the
  flag "capture square is row - 1".

Marked capture square of a marked pawn at square q [known] S 0048a510: `q - 8 + d` with the row - 1 flag,
else `q + 8 + d` (d as above).

**Movable pieces** of side s [known] S 00525c00: if the side's check bit is set (`plrstt` bit 0 for seat 0,
bit 4 for seat 1): its king and its marked pawn(s) only; otherwise all its pieces.

**Targets of the selected piece** [known] S 00525d20, S 00525bb0:

- Pawn, marked: only its marked capture square (if on the board and not holding an own piece).
- Pawn, not marked, at (c, r), f = c + d:
  - (f, r) if no enemy piece stands there and no own piece stands there (i.e. it is empty);
  - (f, r - 1) if an enemy piece stands there; (f, r + 1) if an enemy piece stands there.
- King at (c, r): each of the 8 neighbours, in the order (dc, dr) = (1,-1), (1,0), (1,1), (0,1), (-1,1),
  (-1,0), (-1,-1), (0,-1) (data S 0087cfb8, S 0087cfd8), that is on the board and does not hold an own
  piece. A neighbour attacked by the other side is put into the list with flag 0x40 added to its byte
  (drawn red).
- **A king cannot be sent onto an attacked square**: the click test compares the picked square (0..63) with
  the whole target byte, so an entry with flag 0x40 never matches; such squares are shown red and are
  dead. This also holds for an enemy piece standing on an attacked neighbour [known] S 00525b70.
- No other restriction: the client does not test whether a pawn move or a king move leaves the own king
  attacked.

**Click handling** [known] S 00526260. In a frame in which the right-click predicate (`LobbyAction`
vtbl+0x50, §3.3.2) is true, picking is skipped (phases 2 to 5) [known] S 00526260, S 005260f0. Otherwise
the square under the mouse ray is picked; without a left click it is hover-highlighted; a left click on a
picked square plays sound 0x8778db83 and, while no capture is pending:

1. empty square, in the target list: send 400 Move (`pwn` = selected piece index, `trgt` = square); deselect;
2. own piece, in the movable list: select it (recompute targets);
3. enemy piece, in the target list:
   - enemy **pawn**: set `pendingCapturePiece` to it and recompute the targets in relocation mode (below);
     nothing is sent yet;
   - enemy **king**: send 400 Move onto the king's square; deselect.

Any other click changes nothing. With a capture pending, the only click that does anything is one on a
relocation square: it sends 401 Capture: `pwn` = selected piece, `trgt` = square of the pawn being taken,
`cppwn` = its piece index, `cptrgt` = the clicked square; then `pendingCapturePiece = -1` and the selection
is dropped [known] S 00526260, S 00489fd0. While a capture is pending the board shows the taken pawn's
square red and no movable-piece highlights [known] S 00525fe0.

**Relocation squares** of a taken pawn [known] S 00525d20: start with the column the taken pawn stands in;
the targets are all empty squares of that column (on the board as it is before the move, so neither the
taken pawn's nor the captor's square); if there is none, go one column towards the captor's home (side 0:
column - 1; side 1: column + 1) and repeat until a column with an empty square is found. The taken pawn
changes side: it is redrawn with the other side's mesh (§3.5.6). The loop has no end condition other than
finding a square [known]; it does not terminate if every column from the taken pawn's to the captor's home
column is full [inferred], which needs a full home column and a capture inside it.

**A pending capture cannot be abandoned.** `pendingCapturePiece` is written only by the constructor, by
step 3 and by `SendCapture`; neither the right click, nor a click elsewhere, nor a closing gate, nor a new
table state resets it [known] S 0048a420, S 00489fd0, S 00489f60, S 00526260. If the gate closes while a
capture is pending (the turn passes without the player's 401, e.g. by a server timeout), the selection is
dropped but the pending piece stays: at the next own turn the target list is empty, every click falls into
the pending branch and nothing can be selected or sent at this table any more [inferred]. A server that
times a Pawn Chess player out has to expect this; a remake should reset the pending capture with the
selection.

#### 3.5.5 Check, mate and the winner (server-decided, client-displayed)

`plrstt` holds one nibble per seat (seat 0 low, seat 1 high) [known] S 0044c2a0, S 00525c00, S 0048a490:

| Bit (seat 0 / seat 1) | Meaning on the client |
|---|---|
| 0x01 / 0x10 | in check: restricts the side's movable pieces (§3.5.4); announced |
| 0x02 / 0x20 | checkmate: announced in phase 6 |
| 0x04 / 0x40 | winner: decides win / lose headline and where the bets go |
| 0x08 / 0x80 | no reader found |

Announcements run once each time `trnid` changes [known] S 0044cd10, S 0044c2a0: in phase 4 with bit 0x01,
or phase 5 with bit 0x10: log "`<name of that seat> ` + `!MGCHESS_CHECK`" with sound 0x63c31112; in phase 6:
for each of 0x02 / 0x20 "`<name> ` + `!MGCHESS_CHECKMATE`", for each of 0x04 / 0x40 "`<name> ` + `!Winner`".

Win test for the local view [known] S 0048a490: local seat 0 and bit 0x04, or local seat 1 and bit 0x40.
In phase 6 the primary seat's controller sends both bet piles to its own stack pile if that test is true,
else to the other seat's (`seat ^ 1`) [known] S 00526260. For an observer (`localSeat == -1`) the test is
false, so the piles go to the seat other than the lowest occupied one, whoever won [inferred].

The client has **no win condition of its own**: taking the king, reaching the far column and mate are all
decided by the server and arrive as phase 6 + winner bit.

#### 3.5.6 New game

The NewGame button is shown only while `bNewGameRequested == 0`, i.e. from the first phase 6 seen until the
player clicks it; the click sends 403 NewGame with `plridx` = the local seat and hides the button again
[known] S 0044cd10, S 0044c240, S 0048a2a0. A fresh proxy starts with the flag set, so the first game at a
table needs no 403 from the client's side.

Piece drawing [known] S 00511ab0, S 00525f20: on a change of `trnid` or phase all visible pieces are
re-placed; a piece glides from its previous square in `MiniGamePawnChess.animTime` ms (CVar, default 500,
range 100..3000; data S 0087caa4) with sound 0x63c31104; a piece whose side differs from the side last shown
is flagged as captured (a copy with the old side's mesh is kept for the transition). Mesh kind = king + 2 *
side. Square highlights: movable pieces green, targets blue, attacked targets and the pending capture red,
alpha 0.2 or 0.5, pulsing with the CVars `MiniGamePawnChess.animSpeed` (10) and `animRange` (0.1), colour
fade 250 ms [known] S 00512110.

### 3.6 Observer mode

`CLobbyClient_MiniGame::SetObserving(bool)` (vtable slot 4 of the table client) [known] S 005238e0:

- on: `isObserving = true`, `CLobby::SetViewMode(3)`, a `CMiniGameController` (seat -1, camera mode 2, rig of
  §3.1, placed at the local avatar's position) is pushed onto the local avatar, the overlay
  `MinigameDialog_Observer` is shown for this table, the table's chat channel is joined, and the table client
  subscribes to the world screen's deactivate and leave lists (either one ends observing);
- off: pop and delete that controller, `SetViewMode(1)`, leave the chat channel, hide the overlay.

The overlay has one button, `leaveMiniGame`, which calls `SetObserving(false)` on the observed table; closing
the overlay only hides it and re-enables world selection [known] S 0045ed30, S 0045ed00. The table client's
destructor ends observing if still active [known] S 00523a70.

An observer sends no message for observing (only the chat channel join on the chat connection) and receives
the same 0xD9 states as everyone in the zone: all boards are animated for every client that has the table,
seated or not. An observer is not seated, so 303 is dropped and every non-local rule above applies with
`localSeat == -1`.

[TODO] not established: what calls `SetObserving(true)`. No direct or decompiled indirect call with a true
argument was found in the lobby code (0042xxxx..0052xxxx); the three ways the world screen reacts to a table
(action codes 12..15, `message-catalog.md`) all open the matchmaking dialog. To settle: a breakpoint on
S 005238e0 in the running game while clicking occupied tables, or a search of the instruction bytes for
calls through vtable offset +0x10 on a `MiniGameProxy+0x20` pointer.

Sounds of a table (`PlaySound`, `PlaySoundAt`) are played only if the local avatar is at no table or at this
one [known] S 00523720.

---

## 4. Update order

Everything runs inside the lobby frame `CLobby::Update` (`lobby-world-client.md` §4.1); nothing runs on a
match logic tick. Steps 1, 3 and 4 run once per rendered frame. Step 2 runs in the lobby's fixed **object
step** (83 ms; zero, one or several steps per frame, `lobby-world-client.md` §4.1 steps 4 to 6): the
controllers are components on the component stack of the board object and of each seated avatar's object, and
`CLobbyObj::Update` calls the top component once per object step [known] S 005029e0, S 0051b280 (board
controller pushed), S 0051b710 (seat controller pushed).

1. Network: 0xDA / 0xD9 / 0xD8 / 303 are applied in the message handler. A table body (0xD9, and 0xDA after
   it created the proxy) reads settings, then seats (per listed seat: seat left for a changed occupant, then
   seat joined; then seat left for every occupied seat that is not listed; these push and pop controllers and
   may open or close the dialog), then the game state [known] S 00471f00. Dice computes payouts inside the
   handler on the change to phase 3 [known] S 00488e00.
2. Object controllers, per board (Dice and Poker; a Pawn Chess board has none [known] S 0051c040) and per
   seated avatar:
   - Dice board controller: roller marker; on a phase change: the board is told the phase; phase 1 -> clear
     dice and chip animations, phase 4 -> result animation with the sum of the two dice [known] S 00523c10.
   - Dice seat controller: chip piles from `bets` and `stack - sum`; camera; on a phase change the enter
     action (local seat: phases 1, 2, 3; other seats: 1, 3); then the per-step action of the phase (local
     seat: betting, shaking, throw; other seats: shaking, throw) [known] S 00524c10.
   - Poker board controller: dealer button, marker, phase-change animations, cards, empty seats [known]
     S 00525550.
   - Poker seat controller: seat cards, stack pile, bet pile, pending seat label, camera [known] S 005257f0.
   - Pawn Chess seat controller: input (primary local seat only), piece sync (primary seat), stake piles on
     a phase change, camera [known] S 00526260.
3. Dialogs (`LobbyMenu::System::Update` S 0042a860): every active dialog's `Update` (dialog virtual +0x20)
   [known] S 0042a1c0. Then, only in a frame in which an object step ran: every dialog's `HandleButtonClicks`
   (virtual +0x24) [known] S 0042a020, followed by the `LobbyAction` poll that clears the mouse-button
   release latches of §5.2 [known] S 00428f30. `HandleButtonClicks` is also dispatched directly from the
   lobby's mouse-button-down and -up events [known] S 0042a020 (callers S 004f4fd0, S 004f5010). A click
   handled by the dispatch at the end of a frame is seen by `Update` in the next frame. `Update` per dialog:
   - Dice: currency icon, phase-entry actions (phases 2, 3, 4), chip buttons, stack text (`stack - bets`),
     `betUnit` from the marked button, headline, top-up button (enabled at opacity 1.0 with the headline
     `!MGCOMMON_NOMONEY` when the local stack is 0, else disabled at opacity 0.5) [known] S 00447950.
   - Poker: delayed log lines, last-action event, deal log, pot log, status line, currency icon, wager
     controls, countdown, button slots, action buttons, community card sprites, top-up button, stack text
     [known] S 0044b3c0.
   - Pawn Chess: currency icon, headline, NewGame button, announcements on a `trnid` change, top-up button
     (enabled with `!MGCOMMON_NOMONEY` when the local stack is below `limitMin` in phase 1 or 6), stack
     text [known] S 0044cd10.
4. Rendering: the boards draw cards, dice, pieces and highlights, and their chip manager draws piles,
   transfers and labels [known] S 00514260, S 00517110, S 00520200. [TODO] not established: the draw order
   inside one board (read the three board `DrawRenderItem` functions for the position of the chip call).

Animation start times:

- Poker (deal, collect, payout) and the Dice throw start at the phase start, `now - GetPhaseElapsedMs()`,
  i.e. they are derived from the `time` field; a client that receives the state late sees the remainder
  [known] S 00525300, S 00524f60, S 005250f0, S 005248b0.
- The Dice result animation and the Pawn Chess payout start at the time of the object step in which the
  controller sees the phase change, not at the phase start [known] S 00523c10, S 00518100, S 00526260,
  S 00511680.
- Every one of them is started once per entry into the phase: the latches compare the phase value (Poker
  deal: a flag cleared by any step in another phase), so a state that repeats a phase, with whatever `time`,
  does not restart an animation, and Poker phase 5 followed directly by phase 5 of the next `round` shows no
  second deal animation [known] S 00525550, S 00525300, S 00523c10, S 00526260.

---

## 5. Inputs and outputs

### 5.1 Messages (layouts: [`../message-catalog.md`](../message-catalog.md) "Minigames")

| Id | Name | Dir | Sent / handled when | Tag |
|---|---|---|---|---|
| 0x7D1 (2001) | CreateMiniGameTable (cat. 2) | C->S | Ok in the stake dialog after "Start" in the create page | [known] S 00442f00, S 0046cf20 |
| 0xD1 (209) | JoinTable (cat. 5) | C->S | Ok in the stake dialog after "Join" (and the password check) | [known] S 00442f00 |
| 0xCC (204) | LeaveTable (cat. 5) | C->S | leave button of a table dialog | [known] S 004613c0 |
| 0xDE (222) | Amount (cat. 5) | C->S | Ok in the top-up stake dialog of a table dialog | [known] S 00446930, S 00447f50 |
| 0xDC (220) | Dice PlaceBets (cat. 5) | C->S | after every accepted chip add in phase 1, and after every remove click on a bet field (also when that field's bet is already 0) | [known] S 00523db0 |
| 0xDD (221) | Dice Roll (cat. 5) | C->S | local roller, phase 2, in every object step in which the left-button release latch is set (§5.2): normally once per click, more than once when a frame runs several object steps | [known] S 00524420 |
| 0x12C (300) | Poker Action (cat. 5) | C->S | click on a slot holding CALL (2), FOLD (4), CHECK (0x10) or ALLIN (0x100); the blind codes 0x40 / 0x80 have captions but are never put into a slot | [known] S 004483b0, S 0044b3c0 |
| 0x12D (301) | Poker ActionWithWager (cat. 5) | C->S | click on a slot holding RAISE (8) or BET (0x20); `wgr` = the dialog's chosen wager | [known] S 004483b0 |
| 0x12E (302) | Poker SitOut (cat. 5) | C->S | sit-out toggle | [known] S 004483b0 |
| 0x190 (400) | PawnChess Move (cat. 5) | C->S | move onto an empty square or onto the enemy king | [known] S 00526260 |
| 0x191 (401) | PawnChess Capture (cat. 5) | C->S | relocation square chosen for a taken pawn | [known] S 00526260 |
| 0x192 (402) | PawnChess PlaceKing (cat. 5) | C->S | home-column square clicked in phase 2 / 3 | [known] S 005260f0 |
| 0x193 (403) | PawnChess NewGame (cat. 5) | C->S | NewGame button | [known] S 0044c240 |
| 0xDA (218) | MiniGameTableCreate | S->C | creates the proxy for the key's game type, then reads the same body as 0xD9 (handled in every lobby state) | [known] S 0046eb70 |
| 0xD9 (217) | MiniGameTableUpdate | S->C | settings, seats, game state. Ignored unless the lobby state is "village entered", the key's `chtid` is not 0 and the table is known. The first 0xD9 of a table stores `chtid` and announces the table (creates the table client and board) before the body is read. Apart from 303 and the body of 0xDA, the only way game state changes | [known] S 0046f380 |
| 0xD8 (216) | MiniGameTableRemove | S->C | removes the table (only in lobby state "village entered") | [known] S 0046f510 |
| 0xDB (219) / 0xDC (220) | NoTableLeft / NoPlayerSlotLeft | S->C | error boxes | catalog; dispatch [known] S 00470a90 |
| 0x12F (303) | MiniGameHand | S->C | hole cards (`crd0`, `crd1`) and `hndval` of the local seat; discarded when the local player is not seated | [known] S 00489410 |

All category-5 messages start with the table key (`msgprt` 16, `rnid` 8) [known] S 00471240 and are sent on
the village connection: the game messages through `MiniGameProxy::SendToServer` S 00471460, and 204, 209 and
222 through the same virtual of the connection called directly [known] S 00471660, S 00471720, S 00471800.

Chat connection: join / leave of the table's chat cell (`chtid`) when sitting down, leaving, starting and
stopping observing [known] S 0051b670, S 00523850.

### 5.2 Other interfaces

- Avatar money (`AvatarProxy +0xd0` credits, `+0xd4` play money) is read for the stake limits [known]
  S 00461470, S 00444790. No minigame message writes it: the writers are the avatar's stats block (read from
  the stats message 3201 and from the avatar data blocks, `message-catalog.md`) [known] S 00481da0, callers
  S 0046c9c0, S 00482c20, and the character data blob [known] S 00481e60.
- `CLobby::SetViewMode` 1 (walking), 2 (seated), 3 (observing); the controller stack of the avatar object
  (`lobby-world-client.md`).
- `WorldScreen::EnterMiniGameMode` / `LeaveMiniGameMode`, `ShowMinigameObserverDialog` /
  `HideMinigameObserverDialog` (`lobby-screens.md` §3.17).
- The mouse ray of the lobby world (`world + 0x178`) for picking bet fields and squares [known] S 00523db0,
  S 00526260.
- Clicks on the board: `LobbyAction` virtual +0x4c = `IsLeftButtonTriggered(0)` and +0x50 =
  `IsRightButtonTriggered(0)` [known] vtable S 007d6824, S 00491130, S 00491150. Both test the key-state
  entry of the button (virtual key 1 / 2) for the value -1 [known] S 00491040. That value is written by the
  button-**up** event (event type 2; type 1 = down counts the entry up, any other type sets 0) [known]
  S 00490f50, and it is reset to 0 by the `LobbyAction` poll, which `System::Update` runs only in a frame in
  which an object step ran, after the controllers [known] S 00428f30, S 0042a860. So a board click is a
  button release, and it is seen by every object step between the release and that poll: one step in the
  usual case, several when the frame catches up more than one step [inferred].
- Sound through the table client [known] S 00523720, S 00523770: virtual +0x14 plays a UI sound by id,
  virtual +0x18 a 3D sound at a position (the boards and the chip manager pass their own position). Both
  return without playing when the local avatar object is bound to another table than this one (the pointer
  read from the local avatar object is non-null and differs from this table's proxy).
- A dialog log line can carry a sound id: `MinigameDialog::AddLogLine(soundId, colour, text)` plays it
  through virtual +0x14 when it is not 0 [known] S 00461370.

Sound ids used [known at the call sites; names and files from `data/game/scripts/properties/sounds.lua`,
`sn_create("<id>")`, `sn_addFileName`, `sn_set3DSound`]:

| Id | Name in `sounds.lua` | File | 3D | Played when |
|---|---|---|---|---|
| 0x63c31000..05 | `sound_dice0..5` | `shake0..5.wav` | no | cup shake direction reverses (`rand() % 6`) S 00524420 |
| 0x63c3110a | `sound_dicethrown` | `Lob_Mini_19_dice_throw_a.wav` | no | dice placed, 500 ms into phase 3 S 005248b0 |
| 0x63c31108 | `sound_minigamewon` | `Lob_Mini_02_win_gold_a.wav` | no | Dice result with a payout S 004471d0 |
| 0x63c31109 | `sound_minigamelost` | `Lob_Mini_04_game_lost_a.wav` | no | Dice result without a payout S 004471d0 |
| 0x63c3110b | `sound_countdowntick` | `Lob_Mini_01_countdown_a.wav` | no | Poker: each time the whole second of `15000 - elapsed` changes while the countdown runs (elapsed above 5000 ms, local turn) S 0044b3c0 (disassembly S 0044bb51) |
| 0x63c31102 | `sound_dealcard1` | `Lob_Mini_05_poker_deal_card_a.wav` | yes | a card starts moving S 00514260 |
| 0x63c31100 | `sound_manychips` | `Lob_Mini_03_win_chips_a.wav` | yes | a chip transfer starts moving S 0051f150 |
| 0x63c31103 | `sound_placechip` | `Lob_Mini_17_place_chip_a.wav` | yes | a pile amount grows S 0051ee30 |
| 0x63c31107 | `sound_removechip` | `Lob_Mini_20_remove_chip_a.wav` | yes | a pile amount shrinks S 0051ee30 |
| 0x63c31104 | `sound_movechess` | `Lob_Mini_20_remove_chip_a.wav` | yes | a chess piece moves S 00511ab0 |
| 0x63c31111 | `sound_chesspiecesset` | `Lob_Mini_10_chess_pieces_set_a.wav` | no | first object step in phase 4 or 5 of a game (latch cleared by phases 1, 2, 3 and 6, not by 4 <-> 5) S 00526260 |
| 0x63c31112 | `sound_chesscheckking` | `Lob_Mini_12_chess_check_king_a.wav` | no | check log line S 0044c2a0 |
| 0x63c31105 / 06 | `sound_chesswon` / `sound_chesslost` | `Lob_Mini_15_chess_won_a.wav` / `Lob_Mini_16_chess_lost_a.wav` | no | phase 6 headline S 0044caf0 |
| 0x8778db83 | `sound_uiClick0` | `[data]\sound\uiClick0.wav` | no | click on a chess square S 00526260, S 005260f0 |

`sounds.lua` also defines ids the client code of this document never plays: 0x63c31006 / 07 / 08
(`sound_chipOnBoard`, `sound_chipOnChip`, `sound_clock_5sec`), 0x63c31101 (`sound_fewchips`), 0x63c31113 /
14 (`sound_chesstakepiece`, `sound_chesspiecechange`) [known] data; these ids occur as literals nowhere in
the decompiled code. How a bare file name is resolved to a file of the install: `audio.md`.

---

## 6. Data-driven parameters

| Source | Keys | Used for |
|---|---|---|
| `data/lobby/config/lobbyobj.xml` | `lobbyobj name="spielfeld"` (`gfxclass="minigamedice_board"`, `controllerclass="none"`; `file="maob_spielfeld.kex"`, `mesh_dicecup="becher"`, `mesh_dice="dice"`, `mesh="table"`, `node_hierarchy="table"`). The loader also reads `mesh_selectionmarker` and the integer `rank`, which the entry does not set [known] S 00517920 | Dice board; spawned by name `spielfeld` S 0051b280 |
| same | `pokertable4` (`file="pokertable.kex"`), `pokertable8` (`file="pokertable8.kex"`); `gfxclass="minigamepoker_board"`, `controllerclass="none"`; `file_current_player_marker="PawnChess_KingPlayerB.kex"`, `file_sitout_player_marker="sitout_zzz.kex"`, `mesh="table"`, `mesh_dealerbutton="dealerbutton"`, `node_hierarchy="table"` | Poker boards: `pokertable4` for table spots below 13, else `pokertable8` [known] S 0051b950 |
| same | `PawnChessTable` (`gfxclass="minigamepawnchess_board"`, `controllerclass="std"`; `file="PawnChessTable.kex"`, `mesh="table"`, `file_pawnA/B`, `file_kingA/B` = `PawnChess_Pawn/KingPlayerA/B.kex`, `mesh_field="field"`, `node_hierarchy="table"`) | Pawn Chess board; spawned by name `pawnchesstable` S 0051c040 |
| `data/lobby/objects/minigame/` | `pokerchip.KEX`, `pokerchips.dds`, `PokerCards.dds`, `dealerchip.dds`, `dice.kex`, `becher.dds`, `chessboard.dds`, `sitout_zzz.KEX`, the piece and table `.KEX` files. The Dice board model is not in this folder: the install has it as `data/lobby/objects/TestData/MaOb_Spielfeld.KEX` | meshes and textures [known] install listing |
| tavern scenes | nodes `slot:NN_c` (table spots 00..14, in `taverne02.KEX` and `taverne03.KEX`) and the seat nodes per spot | table and seat placement (`lobby-world-client.md`) |
| board models | Dice [known] S 00517920, S 00516950: meshes `board2` .. `board12` (their bounds are the 11 bet fields, one per dice sum), `stack<s>_<n>` with s = 1..4 and n = 1..3, nodes `dealer1` .. `dealer4`. Poker [known] S 00515780: per seat i = 0..7 `wager<i>`, `stack<i>`, `card<i>_0`, `card<i>_1`, `dealer<i>`, `current<i>`, `sitout<i>`; `board0` .. `board4`, `pot0` .. `pot7`, `cardDeck`. Pawn Chess [known] S 00512d70, S 00511c80: `stack0`, `stack1`, `bet0`, `bet1`, the bounds of the `field` mesh (square centre = min + extent * (2 * index + 1) / 16 on both axes) and a 9 x 9 height grid | positions |
| `data/lobby/ui/layout/` | `lobbyMinigameDialog_Dice.xml`, `_Poker.xml`, `_PawnChess.xml`, `_Observer.xml`, `lobbyMiniGameMatchMakingDialog.xml`, `lobbyMiniGameManualDialog.xml`, `lobbySetStackDialog.xml` | dialog layouts |
| localisation | `!MGDICE_*`, `!MGPOKER_*`, `!MGCHESS_*`, `!MGCOMMON_*`, `!MGMMDLG_*`, `!MGALL_GAMENAME`, `!MG_POKER_TEN_SECONDS_LEFT`, `!MINIGAME_<id>_MANUAL_PAGE<n>` (pages counted up from 1 until a key is missing, S 00442dc0), `!MINIGAME_NOTABLELEFT`, `!MINIGAME_NOPLAYERSLOTLEFT`, `!Player joined game`, `!Player left game`, `!Winner`, `!Invalid password` | texts [known] strings of the binary |
| localisation, Poker | action captions by action code [known] S 00449870: 2 `!MGPOKER_CALL`, 4 `_FOLD`, 8 `_RAISE`, 0x10 `_CHECK`, 0x20 `_BET`, 0x40 `_SMALLBLIND`, 0x80 `_BIGBLIND`, 0x100 `_ALLIN`. Hand category keys by `hndval >> 24` = 0..8 [known] S 0044bf10: `!MGPOKER_NOPAIR`, `_ONEPAIR`, `_TWOPAIR`, `_TRIPS`, `_STRAIGHT`, `_FLUSH`, `_FULLHOUSE`, `_QUADS`, `_STRAIGHTFLUSH`. Rank names `!MGPOKER_%d` [known] S 004482f0. Street log lines [known] S 0044aa90, S 0044abb0, S 0044acc0, S 0044adb0: the text of `!MGPOKER_PREFLOP` + the local hole cards (only when both are below 0x34), `!MGPOKER_FLOP` + board cards 0..2, `!MGPOKER_TURN` + board card 3, `!MGPOKER_RIVER` + board card 4, colour index 4; a card is appended as a space, the rank character `"23456789TJQKA"[card % 13]` and the suit character `"dhsc"[card / 13]` [known] S 00448490, S 0044bf10 | texts and card notation |
| card atlas as the Poker dialog addresses it | the five community-card pictures of the dialog get a source origin per card c (0..51), r = c % 13, s = c / 13: x = `(r & 7) * 256 + 28`, y = `s * 512 + (r >> 3) * 256`; an absent card (0xFF) and every slot beyond the card count: x = 1820, y = 1792 (cell column 7, row 7) [known] S 00448010. [inferred] an 8 x 8 grid of 256-unit cells, two rows per suit, in the picture's texture; [TODO] not established: the texture and the picture size, which come from `lobbyMinigameDialog_Poker.xml` (read the five card picture nodes there) | dialog card pictures |
| `data/game/scripts/properties/sounds.lua` | the sound records of §5.2 (`sn_create` id, file name, 3D flag, volume, priority) | sounds |
| `data/lobby/sound/minigame/`, `minigameDice/`, `miniGamePoker/` | e.g. `Lob_Mini_12_chess_check_king_a.wav`, `shake0..5.wav`; `miniGamePoker/` (`card_single_deal_01..04.wav`, `cards_mixing.wav`, `chip_single_*.wav`) and `throw0/1.wav`, `intoMug_*.wav` are named by no record of `sounds.lua` [known] install listing, `sounds.lua` | sound files |
| particle effects | `MGDice_Won` (per seat with chips on the field of the exact sum, at the start of the result animation), `MGDice_Smoke` (per seat pile on a losing field, 2000 ms later) [known] S 00518100. [TODO] not established: the file that defines the two effects (not found by name in the decrypted `data/lobby` and `data/game` text files; `rendering.md` / `world-objects-rendering.md` describe the particle system) | Dice result |
| CVars | `Lobby.chipValueFadeStart` 3.0 and `Lobby.chipValueFadeEnd` 7.0 (range 0..100), `Lobby.renderChipStackValues` true [known] S 00520200, data S 0087cd2c..34; `MiniGamePawnChess.animTime` 500 (100..3000), `.animSpeed` 10 (1..16), `.animRange` 0.1 (0.01..1.0) [known] S 00511ab0, S 00512110, data S 0087caa4..ac | tuning |

Constants compiled into the client (not data): chip buttons {1, 5, 10, 25, 100} [known] data S 0087a580; chip
denominations; minimum stake lists; player count ranges; 15 s countdowns; all animation times of §3.

Dice bet-field brightness [known] S 00517110: each of the 11 fields has one brightness value, sent to the
board shader as a grey colour and eased to its target. Target 0.5 over 500 ms by default; 0.75 over 100 ms
when the field's flag bit 0x02 is set; 0.35 when flag bit 0x08 is clear; 0.65 when the result tint (flag bits
0x10 / 0x20, §3.3.4) is 1 (each later condition overrides the earlier ones); with result tint 2 the value
is set to 0.65 and animated to 1.0 over 3000 ms with tween mode 3. [TODO] not established: the curve of tween
mode 3 (read `ai::lobbygfx::FloatTween::Evaluate`) and which events set flag bits 0x02 and 0x08 (the writers
of the bet-field flag byte).

---

## 7. Save and load

Nothing is persisted by the client. Table state lives in the proxies and is rebuilt from 0xDA / 0xD9 after
entering the village; the dialogs keep no settings between sessions (the matchmaking dialog resets its
filter and phase on every `Open`) [known] S 00444cb0. Credits and play money are part of the character data
kept by the server (`village-and-character-protocol.md` §1.4).

---

## 8. Determinism notes

Presentation and front end only. The minigames exist in the lobby village, outside any match: they touch no
simulation state, run in the lobby frame and its object step (§4), take the phase clock from the wall clock
(`Timer_GetElapsedSecondsSinceStart`) [known] S 00471540, S 004715a0, and use `rand()` only for cosmetic
choices (shake sound, die yaw and position) [known] S 00524420, S 005248b0. The
three client-side computations (Dice payout, Poker winners, Pawn Chess targets) are pure integer functions
of the last table state; they must match the server's rules, but no two clients need to agree bit-for-bit
on anything else.

---

## 9. Notes for a Godot reimplementation

- **Model**: one `Table` resource per table key with the base fields of §2.1 and one of three state structs
  (§2.2 to §2.4). Apply a 0xD9 atomically, then let scenes react to diffs (phase change, seat change,
  `trnid` change) exactly as §4 describes: several rules depend on "the value stored before this message"
  (Dice bets, Poker counters, Pawn Chess `sentTurnId`).
- **Must be reproduced exactly** (they are protocol behaviour, not look):
  - Dice: local bets are client state during phase 1 and are sent whole (220) after each change; the
    add test `sum + unit <= crdts`; the payout formula; `crdts` includes the bets.
  - Poker: the turn test with the two counters (including that 302 consumes the turn); the button order and
    the three-slot limit (a remake should clamp instead of overflowing); `wgr` bounds; winner selection
    starting from 0 with integer division; phase 8 needs per-pot wagers.
  - Pawn Chess: the input gate with `trnid`; the move generator of §3.5.4 including what it does not check;
    the two-step pawn capture with relocation; king placement squares; the NewGame flag.
  - Stake dialog bounds and defaults (§3.2) and the join conditions.
- **Maps onto engine features**: boards and seats are scenes placed at named nodes of the tavern model;
  chip piles are a MultiMesh fed by the greedy denomination split (cap 25); card, chip and piece motions are
  tweens with the durations of §3 and the start times of §4; highlights are per-square materials; labels are
  Label3D with distance fade; the dialogs are Control scenes built from the layout XML (`ui-toolkit.md`).
- **Timers**: every countdown is `15000 - elapsed` from the server's `time` field (Dice betting S 004471d0;
  Poker turn S 0044b3c0, drawn and ticking only once `elapsed` is above 5000 ms); never act locally at 0.
- **Step rate**: controllers (board input, 221, chess moves, animation starts) run in the lobby's 83 ms object
  step, dialogs once per frame (§4). A remake that polls input per frame must still send 221 and the chess
  messages at most once per click.
- **A server has to provide**: all dealing, rolling, hand evaluation (`hndval` in the client's encoding),
  blinds, turn order, timeouts, pot construction, check / mate / win detection, stake booking, and a table
  state after every client message (with a new `trnid` for Pawn Chess, and a changed `crntplyr`, `phase` or
  `round` to hand a Poker turn back). Minimum phase durations so animations finish: Dice throw 1 s, Dice
  result 3 s, Poker deal `(2 * seats + 1) * 350` ms preflop and 700 ms + 350 ms per extra board card, Poker
  collect 750 ms, Poker payout `2000 * n - 250` ms for n pots that have an amount and a winner (pot k starts
  at 1000 + 2000 * k ms and moves for 750 ms; 500 ms when no pot moves but cards are revealed), Pawn Chess
  game over 1 s after the client sees phase 6 [inferred] from S 00513e20, S 00513ce0, S 00514110,
  S 005250f0, S 00513fd0, S 00513c10, S 005248b0, S 00518100, S 00511680. The Dice result and the Pawn Chess
  payout are timed from the client's own step, not from `time` (§4).
- **A converter has to provide**: the three board models with their locator nodes and boxes, the card atlas
  (`PokerCards.dds`), chip mesh, piece meshes, dialog layouts, the localisation keys of §6 and the sounds.

---

## 10. Differences from the server implementation

Server: `lobby/sadk_lobby/minigames.py`, `poker.py`, `pawnchess.py`. Rules the server adds where the client
has none (blinds, turn order, timeouts, forfeits, booking) are listed in `message-catalog.md` ("Server
decisions"); below are the points where the two sides do not line up, or where the client shows something
the server does not drive.

| # | Game | Client | Server | Effect |
|---|---|---|---|---|
| 1 | all | top-up maximum = avatar money - seat `accnt` (S 00461470) | sends `accnt` = the whole account balance (`_balance`) | if the avatar money shown to the client equals that balance, the maximum is 0 and the top-up dialog cannot offer an amount [inferred]; what `accnt` meant originally is open (§11) |
| 2 | Dice | no timer in phases 2..4; throw animation ends at 1 s, result animation at 3 s | roll timeout 20 s, throw 4 s, result 4 s | compatible; server times are longer than needed |
| 3 | Dice | sends 221 in every object step that sees the left-button release (S 00524420, §5.2); no latch of its own | accepts the first in phase 2, drops the rest | compatible |
| 4 | Dice | headline in phase 4 shows the gross return as "won" | books `stack - bets + payout` at the end of phase 4 | compatible; the "lost" texts never appear |
| 5 | Poker | shows `amount / winners` per winner for every pot | gives the odd chips to the first winner after the button | the log can differ from the booked stacks by the remainder |
| 6 | Poker | 302 consumes the local turn until `crntplyr`, `phase` or `round` changes (S 00489340) | "back in" (enbl 0) during the own turn is answered with an unchanged state | the player has no buttons for the rest of that turn and is timed out [inferred] |
| 7 | Poker | phases 2, 3, 4, 7 exist as values without behaviour | uses 1, 5, 6, 8, 9 only | none visible; the original use of the other values is open |
| 8 | Poker | per-player bit 14 is stored, no reader found | never sets it | none visible |
| 9 | Pawn Chess | phase 3 shows piece index 0 only (S 00525f20) | pieces 0..7 are side 0's home column by row; the king is the piece on the chosen row | during seat 1's placement the client shows side 0's row-0 piece, which is the king only if row 0 was chosen [inferred] |
| 10 | Pawn Chess | announces checkmate from bits 0x02 / 0x20 | sets only check (0x01 / 0x10) and winner (0x04 / 0x40) | the `!MGCHESS_CHECKMATE` line never appears |
| 11 | Pawn Chess | movable pieces in check: king + marked pawn; a king cannot be clicked onto an attacked neighbour (§3.5.4, S 00525b70); no other test for leaving the king attacked | generator `legal_moves` lets the king step onto attacked squares; ends the game on mate or when the side has no legal move | the server accepts king moves the client can never send; a position in which the server counts only such moves as legal leaves the player without a usable move and no game end [inferred] |
| 12 | Pawn Chess | observers are possible in principle (§3.6) | two seats, no spectators | none |
| 13 | all | observer mode exists (§3.6) | no message or state for it; nothing needed | none |

---

## 11. Open questions

1. **What starts observing.** `SetObserving(true)` has no located caller (§3.6). Settle: breakpoint on
   S 005238e0 in the running game, or a byte search for indirect calls through table-client vtable +0x10.
2. **Meaning of `accnt`.** The client only subtracts it from the avatar's money for the top-up maximum. Settle
   in the running game: sit at a Dice table with known money, hook S 00461470, compare the dialog's maximum
   for `accnt` = 0, = the buy-in, = the balance.
3. **The two unnamed dwords at `MiniGamePokerProxy` +0x538 / +0x53c.** Zeroed by the constructor S 00489dd0;
   no other access to these two fields appears in the decompiled code [known] search over all functions.
   [inferred] unused. An access through a raw pointer into the object would not show in that search.
4. **Poker phases 2, 3, 4, 7 and per-player bit 14.** No client behaviour found. Bit 14 is stored at
   `PokerSeatRecord +0x04` by the state reader, cleared by the seat reset, and read by none of the eight
   functions that take a seat record from the proxy [known] S 004894a0, S 00489c40, accessors S 00489bc0,
   S 00489be0. The original meaning needs a capture of the original server, which does not exist.
5. **Poker dialog card pictures**: texture and size of the five community-card pictures (§6). Static:
   `lobbyMinigameDialog_Poker.xml`.
6. **Pawn Chess original piece order** (piece 0 = seat 0's king, §3.5.1) and whether the original server
   reordered pieces at king placement. Only an observation of the original server could settle it; a remake
   can simply send seat 0's king as piece 0.
7. **Pending pawn capture across a turn change** (§3.5.4): the pending piece is written only by the
   constructor, by the click that picks the pawn and by `SendCapture` [known] S 00489f60, S 0048a420,
   S 00489fd0; no table state resets it. Whether the original server ever passed the turn while a capture
   was pending is not knowable. Running game: let the server time a player out with a pawn picked and
   confirm that the board stays dead afterwards.
8. **Dice board looks**: the roller marker, the curve of tween mode 3 and the events behind the bet-field
   flag bits 0x02 and 0x08 (§6). Static: `CGfxObjMiniGameDice_Board::DrawRenderItem` S 00517110 (the part
   before the field loop), `ai::lobbygfx::FloatTween::Evaluate`, the writers of the bet-field flag byte.
9. **Definition of the particle effects `MGDice_Won` / `MGDice_Smoke`** (§6). Static: the particle system's
   effect lookup by name.

`maxPlayers` is 4 bits on the wire (`mxplyr`), the constructor default is 0xFF, and 8-seat tables need the
value 8, which fits [known] S 00471490, S 00471b70.

---

## 12. Function reference

| Address | Name | Role |
|---|---|---|
| S 00471b70 | `MiniGameProxy::ctor` | base table mirror |
| S 00471490 / 00471f00 | `ReadTableSettings` / `ReadSeats` | settings and seat blocks |
| S 00471d10 / 00471c40 | `SetSeat` / `ClearSeat` | seat join / leave, local seat, lowest seat |
| S 00471540 / 004715a0 | `SetPhaseStartFromElapsed` / `GetPhaseElapsedMs` | phase clock |
| S 004715f0 | `IsPrimarySeat` | which seat controller does shared work |
| S 00471660 / 00471720 / 00471800 | `SendAmount` / `SendJoinTable` / `SendLeaveTable` | 222 / 209 / 204 |
| S 00488b50 | `MiniGameDiceProxy::ctor` | dice state, seat anchors |
| S 00488e00 | `MiniGameDiceProxy::ReadTableState` | dice state reader, local-bet rule |
| S 00488870 / 00488d60 | `ComputeSeatPayout` / `ComputeAllPayouts` | dice payout |
| S 00488be0 / 004887a0 | `SendPlaceBets` / `SendRollDice` | 220 / 221 |
| S 00489dd0 | `MiniGamePokerProxy::ctor` | poker state |
| S 004894a0 / 00489410 | `ReadTableState` / `ReadHand` | poker state reader / 303 |
| S 00489b80 | `IsLocalPlayersTurn` (poker) | turn test |
| S 00489110 / 004891d0 / 00489340 | `SendAction` / `SendActionWithWager` / `SendSitOut` | 300 / 301 / 302 |
| S 004892f0 | `PopLastActionEvent` | last action for bubble and log |
| S 00489f60 | `MiniGamePawnChessProxy::ctor` | pawn chess state |
| S 0048a6d0 | `MiniGamePawnChessProxy::ReadTableState` | state reader, board and attack map |
| S 0048a510 | `PawnChess_GetMarkedCaptureSquare` | marked pawn's target |
| S 0048a100 / 00489fd0 / 0048a360 / 0048a2a0 | `SendMove` / `SendCapture` / `SendPlaceKing` / `SendNewGameRequest` | 400 / 401 / 402 / 403 |
| S 0048a440 / 0048a260 / 0048a490 | turn of the local player / phase -> side / local win test | pawn chess helpers |
| S 005032b0 | `CLobbyClient::OnMiniGameTableShown` | creates the table client |
| S 0051b280 / 0051b950 / 0051c040 | `CLobbyClient_MiniGame_Dice` / `_Poker` / `_PawnChess` ctor | spawn the board |
| S 0051b710 / 0051be10 / 0051c240 | `OnSeatJoined` (Dice / Poker / PawnChess) | seat controller, table view |
| S 0051b4f0 / 0051bc10 | `OnSeatLeft` (Dice / Poker and PawnChess) | leave |
| S 0051b670 / 0051bd90 / 0051b440 / 0051c1b0 | `EnterTableView` / `LeaveTableView` | dialog, chat channel |
| S 005238e0 / 00523850 / 005237c0 | `SetObserving` / `StartObserving` / `StopObserving` | observer mode |
| S 00526800 / 005269e0 | `CMiniGameController::ctor` / `UpdateCamera` | seat camera |
| S 00523c10 | `CMiniGameControllerDice_Board::Update` | dice board per phase |
| S 00524c10 | `CMiniGameControllerDice_Actor::Update` | dice seat per phase |
| S 00523db0 / 00524420 / 005248b0 | `UpdateBetting` / `UpdateLocalShaking` / `UpdateThrow` | bets, roll, throw |
| S 00525550 / 00525300 | `CMiniGameControllerPoker_Board::Update` / `UpdateCards` | poker board per phase |
| S 00524f60 / 005250f0 | `AnimateCollectBets` / `AnimatePayout` | phase 8 / phase 9 |
| S 005257f0 | `CMiniGameControllerPoker_Actor::Update` | poker seat |
| S 00526260 | `CMiniGameControllerPawnChess_Actor::Update` | input, stakes, payout |
| S 00525c00 / 00525d20 / 005260f0 | `RefreshMovablePieces` / `ComputeTargets` / `HandleKingPlacementInput` | move generator |
| S 00525f20 | `SyncPiecesToBoard` | pieces shown per phase |
| S 00518100 / 005175d0 / 00517000 | Dice board `AnimateRoundResult` / `SetDiceResult` / `PickBetField` | result, dice, picking |
| S 00513e20 / 00513ce0 / 00513c10 | Poker board `DealHoleCards` / `DealCommunityCards` / `RevealSeatCards` | card timing |
| S 00514110 / 00513fd0 | Poker board `AnimateBetsToPots` / `AnimatePotToWinners` | chip timing |
| S 00511ab0 / 00511680 / 00512110 | Pawn Chess board `SetPiece` / `AnimateBetsToStack` / square colour | pieces, payout, highlights |
| S 0051fe80 / 0051f0d0 / 0051ee30 | `CChipGfxMgr::DrawPile` / `StartTransfer` / `SetPileAmount` | chips |
| S 00461b70 / 004613c0 / 00461470 | `MinigameDialog` ctor / clicks / `OpenSetStackDialog` | common dialog |
| S 00447950 / 004471d0 / 00446a60 | `MinigameDialog_Dice::Update` / `UpdatePhaseDisplay` / `UpdateChipButtons` | dice dialog |
| S 0044b3c0 / 00449a30 / 0044aea0 / 004483b0 | `MinigameDialog_Poker::Update` / `UpdateActionButtons` / `UpdateWagerControls` / clicks | poker dialog |
| S 0044a3e0 / 0044a910 / 004484f0 / 00449870 | `LogPotResults` / `UpdateSetStackButton` / `FormatHandValue` / action text | poker dialog |
| S 0044cd10 / 0044caf0 / 0044c2a0 / 0044c240 | `MinigameDialog_PawnChess::Update` / `UpdatePhaseDisplay` / `AnnounceCheckAndResult` / clicks | pawn chess dialog |
| S 0045ed30 / 0045ed00 | `MinigameDialog_Observer` clicks / `Hide` | observer overlay |
| S 00444cb0 / 00444790 / 00445cf0 | `MiniGameMatchMakingDialog::Open` / clicks / `Update` | matchmaking |
| S 00443eb0 / 00444330 / 00443100 | `SetPhase` / `OnPhaseAction` / `UpdateOptionLimits` | pages, stake list |
| S 004432a0 / 00442f00 | `OnPasswordEntered` / `OnSetStackResult` | password check, 2001 / 209 |
| S 00442dc0 | `MiniGameManualDialog::Open` | manual pages |
| S 0046eb70 / 0046f380 / 0046f510 | `VillageServerConnection::HandleMiniGameTableCreate` / `Update` / `Remove` | 0xDA / 0xD9 / 0xD8 |
| S 0046cf20 | `VillageServerConnection::SendCreateMiniGameTable` | 2001 |
| S 00471240 | `MiniGameKey::WriteMsgPrtRnid` | table key of every category-5 message |
| S 005029e0 | `CLobbyObj::Update` | calls the top controller once per object step |
| S 0042a860 / 0042a1c0 / 0042a020 | `LobbyMenu::System::Update` / `UpdateDialogs` / `DispatchButtonClicks` | dialog update and click order |
| S 00491040 / 00490f50 / 00428f30 | `BaseAction::IsKeyTriggered` / `OnKeyEvent`, `LobbyAction::PollAsyncKeys` | click latch |
| S 00523720 / 00523770 | `CLobbyClient_MiniGame::PlaySound` / `PlaySoundAt` | UI and 3D sound of a table |
| S 00461370 / 00461d90 | `MinigameDialog::AddLogLine` / `AddDelayedLogLine` | log line with optional sound |
| S 0044aa90 / 0044abb0 / 0044acc0 / 0044adb0 | `LogPreflop` / `LogFlop` / `LogTurn` / `LogRiver` | street log lines |
| S 00448490 / 004482f0 / 00448010 | `AppendCardText` / `GetCardRankText` / `UpdateCommunityCardSprites` | card notation, rank key, card pictures |
| S 00517920 / 00515780 / 00512d70 | Dice / Poker / Pawn Chess board constructors | model keys and locator names |
| S 00517110 | `CGfxObjMiniGameDice_Board::DrawRenderItem` | bet-field brightness |
