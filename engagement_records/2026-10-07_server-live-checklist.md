# Server live checklist (2026-10-07, branch `server-awakening`)

Everything below was implemented from `docs/message-catalog.md` and passes the offline tests
(`for t in tests/test_*.py; do python3 $t; done`). None of it has run against the real client yet. Most
of the behaviour is [inferred] in the catalog, so each step says what to expect and what to look for in
the stub log if it does not happen. Fill in the results table at the end.

## Setup

1. Stop the running stub. It has been up since 2026-09-22 on the old code (PID 1176 at the time of
   writing).
2. `git checkout server-awakening`, then `python -m sadk_lobby`.
3. Two clients, A and B, with different login names. Steps 8–11 need the NPCs: set
   `config.VILLAGE_NPCS_ENABLED = True` for those, because the shop, tailor, minigames and mailbox are all
   reached through NPC buttons.

## Part 1: lobby

### 1. Chat joins still work (StatusReply is now 12 bytes) — regression risk

`chat.status_reply` now packs `result_id` as u32, as the client's template reads it. Joins worked before
with the 2-byte-shorter body.
- Log in both clients, enter the lobby world, type in global and local chat.
- **Expect:** both see each other's lines as before. The log shows `StatusReply from client: … → OK`, not
  `REJECTED`.
- **If joins break:** change the last field of `chat.status_reply` back to `"<H"` and note it here.

### 2. Whispers
- A whispers B. **Expect:** B sees the incoming whisper with A's name; A sees its own outgoing line once; a
  third client sees nothing. Log: `whisper 'A' → 'B' delivered`.
- Whisper an offline name: nothing on screen; log `target offline, dropped`.

### 3. Leaving and creating chat channels
- Leave a channel. **Expect:** the channel UI shows it as left; the other member sees you disappear. Log:
  `left cell N (Left + StatusReply 0)`.
- Try to create a channel. **Expect:** a creation-failure message (code 0x8C) instead of waiting forever.

### 4. Game browser rows
- A hosts a game with a password and one AI slot; B opens the game browser.
- **Expect:** **1 human + 1 AI** occupied (it showed "0 + AI" before) and the "Protected" icon. A changes a
  slot or removes the password: B's row updates.
- A leaves the setup dialog or quits: **the row disappears from B's browser** by itself. Log:
  `pushed 169 RemoveServer id=…`.

### 5. Mail
- A sends B a mail. **Expect:** no error at A; log `[MAIL] A → B: '<title>' stored as #1`.
- Within 60 s B's mailbox shows it. B opens it (text visible), marks it read, deletes it.
- A sends two more: they go through too. Before, every mail action stalled after the first send.
- Mail to a name that never logged in: A gets a failure message.

### 6. Buddies
- A adds B as a buddy. **Expect:** B appears in A's list; log `[BUDDY] … adds …: OK`. A list refresh keeps
  B there.
- B logs out and back in. **Expect:** A sees B go offline and online without refreshing (61 pushes). Log:
  `is now offline — told 1 player(s)` / `online`.
- Adding yourself or adding B twice: the client keeps its list unchanged.

### 7. End of match (referee)
Needs a hosted match between A and B.
- One player uses **Back to Lobby / give up**. **Expect:** "Finalizing..." ends and the client returns to
  the lobby (it hung before). Log: `GiveUpGame(0xDD4) … → GiveUpGameAcknowledge(0xDD5, Result=0)`.
- Play a match to the end. **Expect:** `FinishGame(0xDC0) … winner=…` once per client, then 0xDC1 and
  0xDC2. Note what the client does next; the catalog has no trace of what it waits for.
- Open a treasure chest, if the map has one. **Expect:** no REGISTER_GAME_FAILED; log
  `ClaimChest(0xDAC) … → owner …`. Note what the client shows.

## Part 2: village (set `VILLAGE_NPCS_ENABLED = True`)

### 8. Gold and items at world entry
- Enter the world. Log: `StatsUpdate(3201) ownr=<you> gold=1000` and `ItemsFullSync(3102)`.
- **Expect:** the client's gold display (if visible) shows 1000. **If it does not:** the client may not
  have its own avatar under that id, in which case it drops these silently. Note it; the catalog lists
  "send each client its own 1001" as the open experiment for that.

### 9. Shop
- Click the shop NPC (Händler Hinnerk, "Zum Laden").
- **Expect:** log `OpenShop NPC … → shop 1` and the shop dialog opens **only after the click**. If the log
  shows nothing at all, the client still does not send 0x2E10. That was the 2026-08-02 blocker, and it
  needs a live trace of the button handler.
- Buy an item. **Expect:** `ShopBuy … OK`, the item appears in the backpack, gold drops by the price. The
  stock uses probe item ids 1–8, so note which ids render as real wares (the real ids are in the
  encrypted game data).
- Buy something too expensive: the client reports failure.
- Sell the item back: gold rises by 0.9 × the sell price; the item disappears.

### 10. Inventory
- Drag an item between backpack slots and onto an equipment slot. **Expect:** the move sticks
  (`MoveItem … applied`). Equipment containers are assumed to be 2–5 [inferred].
- Drop an item into the 3D world and confirm the delete box. **Expect:** it disappears (`DeleteItem`).
- If items show wrong or blank, note the `sltt` value: occupied slots are sent as `sltt = 1`, which is a
  guess.

### 11. Tailor / hairdresser
- Use the hairdresser NPC (Magd Mathilde, "Neue Frisur", action 1).
- **Expect:** the tailor dialog. Change colours: 50 gold is charged (`AvatarColorChange … charged 50 gold`)
  and **B sees A's new colours**.
- **If the button does nothing:** the binary's action dispatcher (S 00434230) handles the tailor as code 17,
  and code 1 is not dispatched. But the NPC button-label table in `npcs.py` hides codes above 11. Try
  changing the NPC's action to 17 and note which one shows a button and which one opens the dialog.

### 12. Minigames
- Use Spielmeister Silas ("Minispiel") to open the matchmaking dialog, then create a **Dice** table.
- **Expect:** log `table (1, 0) created …` and a 3D table appears for both A and B. If nothing appears,
  check the log for the 0xDA/0xD9 sends; the `scntbl` byte (tavern low nibble, table index high nibble)
  is a guess.
- B joins. **Expect:** B sits at the table and the credits show the stake. **If the seat does not show for
  someone:** that client rejected the seat block because it has no 3D avatar for a seated player (the
  joiner's own avatar is the suspect). Note who.
- Place bets and roll. **Expect:** dice show, payouts match the client's own calculation, and 5 s later
  betting reopens. Log: `rolled x+y=…`.
- Leave the table: credits return to gold. When the last player leaves, the table disappears.
- Poker and PawnChess tables appear and seat players, but **their game logic is not implemented**: actions
  are logged only.

## Not implemented (and why)

- **Poker and PawnChess rules.** The game-state layouts are only [inferred]; a capture of a real table
  update or more RE is needed first.
- **Trades.** The client has no outbound trade message in this build.
- **Channel creation.** Refused on purpose until there is a feature for it.
- **Ignore-list additions.** Not looked at in this tranche.
- **Persistence.** Mail, buddies, gold and items live in memory and reset on a server restart (perm_ids are
  not stable across restarts).

## Results

| # | result | notes |
|---|---|---|
| 1 chat joins | | |
| 2 whispers | | |
| 3 channels | | |
| 4 browser rows | | |
| 5 mail | | |
| 6 buddies | | |
| 7 end of match | | |
| 8 gold/items at entry | | |
| 9 shop | | |
| 10 inventory | | |
| 11 tailor | | |
| 12 minigames | | |
