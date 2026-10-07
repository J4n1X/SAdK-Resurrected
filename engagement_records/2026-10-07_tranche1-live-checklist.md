# Tranche 1 live checklist (2026-10-07, branch `server-awakening`)

The first server changes built from `docs/message-catalog.md`. All of them pass the offline tests
(`tests/test_*.py`). Behaviour marked [inferred] in the catalog still needs this live check before it can be
called [PROVEN]. Run the tests in this order; the first one touches a message that already works live.

**Setup.** Stop the running stub (it has been up since 2026-09-22 on the old code), check out
`server-awakening`, start `python -m sadk_lobby`. Two clients (host + joiner) for most steps.

## 1. Chat joins still work (StatusReply is now 12 bytes) — risk: regression

StatusReply's `result_id` changed from u16 to u32, as the client's template reads it (T 1000ef30).

- Log in with both clients and enter the lobby world. Type in the global channel and in local chat.
- **Expect:** both clients see each other's lines exactly as before. The log shows
  `JoinChatChannel cell=…` and `[CHAT] ← StatusReply from client: … → OK` (not `REJECTED`).
- **If joins break:** revert only `chat.status_reply` to `struct.pack("<H", result_id)` for the last field,
  and note it here; the leave fix below then needs another way.

## 2. Whispers

- Client A whispers client B (chat input whisper syntax / right-click the name in the member list).
- **Expect:** B sees the incoming whisper labelled with A's name; A sees its own outgoing line once. A
  third client sees nothing. Log: `→ [CHAT] whisper 'A' → 'B' delivered`.
- Whisper a name that is offline: nothing happens on screen; log says `target offline, dropped`.

## 3. Leaving a channel

- Leave a chat channel (or start/stop observing a minigame table).
- **Expect:** the client's channel UI updates as left; the other member sees you disappear from the list.
  Log: `left cell N (Left + StatusReply 0); told 1 member(s)`.

## 4. Creating a channel (refused on purpose)

- Try to create a chat channel.
- **Expect:** the client shows a creation failure (code 0x8C) instead of waiting forever. Log:
  `create channel refused: StatusReply(result 0x11)`.

## 5. Game browser rows

- A hosts a game with a password and one AI slot; B opens the game browser.
- **Expect:** B sees the row as **1 human + 1 AI** occupied (it showed "0 + AI" before) and with the
  "Protected" icon. A closes a slot or removes the password: B's row updates.
- A leaves the setup dialog (or quits the client): **the row disappears from B's browser** without B
  re-opening it. Log: `pushed 169 RemoveServer id=… to N observer(s)`.

## 6. Mail

- A sends B a mail (PostOffice). **Expect:** no error at A; log `[MAIL] A → B: '<title>' stored as #1`.
  Before this change the first send worked and every later mail action stalled.
- Within 60 s B's mailbox shows it; B opens it (text visible), marks it read, deletes it.
  Log: `[MAIL] inbox of B: sent 1 mail(s) + OK`.
- A sends a second and third mail: they also go through (this was the stall).
- Mail to a name that has never logged in: A gets a failure message.

## 7. End of match (referee)

Needs a hosted match started between A and B (the full referee chain).
- In the match, one player uses **Back to Lobby / give up**. **Expect:** the "Finalizing..." screen
  ends and the client returns to the lobby (it hung before). Log:
  `GiveUpGame(0xDD4) GameID=… → GiveUpGameAcknowledge(0xDD5, Result=0)`.
- Play a match to the end. **Expect:** log `FinishGame(0xDC0) … winner=…` once per client, then 0xDC1 and
  0xDC2. Note what the client does next (the catalog marks this [TODO]).
- Open a treasure chest in a match (if the map has one). **Expect:** no REGISTER_GAME_FAILED; log
  `ClaimChest(0xDAC) … → owner …`. Note what the client shows.

## Results

| # | result | notes |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |
| 6 | | |
| 7 | | |
