# Engagement Record — channel roster + real chat broadcast (make the lobby social)

- **Date:** 2026-07-27
- **Type:** Stub wire-change (new outbound frames on the UC/chat connection; **no flag**)
- **Status:** ⏳ proposed — awaiting user approval

## The gap, measured

From a full two-client session (`stub_refbe.out`), everything the clients actually send:

| type | count | our handling |
|---|---|---|
| `17 RequestJoinChannel` | 12 | replies, but tells the joiner about **themselves only** |
| chat-magic `id=2` ChatMessage | — | **echoed back to the sender**, `from_id = FROM_SERVER` |
| chat-magic `id=11` | 24 | no handler (now hex-dumped for identification) |
| `147 RequestPrivateMessageList` | 6 | bare ack |

Nothing errors — the lobby is simply **asocial**. You never see another player in a channel and
nothing you type reaches anyone. Note the client never sends `107 RegObserverGlobalChat` in these
sessions, so global chat is not the path; it is all channel-based (`17` + chat-magic).

## The change

1. **Per-cell roster.** Track `(cell_id → set of live UC conns)`. Built on the existing `_live`
   registry in `dispatch.py` (already used for the two-phase village leave) plus `players.of(conn)`.
2. **On `17 RequestJoinChannel`** — in addition to today's `ChannelJoined` + `StatusReply` +
   own `ChatUserInfo`:
   - send the joiner a `ChatUserInfo` for **each existing member** of that cell,
   - send **each existing member** a `ChatUserInfo` for the joiner.
3. **On chat-magic `id=2` ChatMessage** — broadcast the `Reply` to **every** conn in that cell
   (including the sender, preserving today's echo so the speaker still sees their own line),
   with `from_id` = **the sender's perm_id** instead of `FROM_SERVER`.
4. **On UC disconnect** — drop from the roster and notify the remaining members
   (`UserLeftChannel`, lobby type 6 in the inner-payload numbering).

## Grounding — what is proven vs. inferred

- **PROVEN:** `inner_user_info(perm_id, cell_id, nick)` wrapped in `reply(5, …)` is already sent on
  join and the client accepts and renders it (the joiner appears in their own list). Sending the
  same structure for other players is the same frame to a different socket.
- **PROVEN:** the `_live` registry and `players.of()` already resolve UC conns to perm_ids
  correctly — the village leave depends on it.
- **INFERRED:** that `from_id` on a `Reply` is what the client attributes the line to. Today it is
  `FROM_SERVER` and messages render, so the field is at least tolerated; using the speaker's
  perm_id is the natural reading but is **not** yet confirmed against the binary.
- **INFERRED:** inner type `6` = UserLeftChannel (from `docs/LOBBY_PROTOCOL.md`, the lobby NETMSG
  table). The chat-magic inner numbering has only been confirmed for `5`.

## Falsifiable predictions

1. **Success:** with two clients in the same channel, each sees the other in the member list, and
   a line typed by one appears on the other's screen attributed to the right name.
2. **Wrong `from_id`:** messages appear but attributed to the wrong player / "default" / blank ⇒
   revert `from_id` to `FROM_SERVER` and carry the speaker in the inner payload instead.
3. **Wrong inner type for leave:** members never disappear on disconnect ⇒ `6` is wrong; drop that
   part (it is cosmetic) and keep join+broadcast.
4. **Client rejects the extra ChatUserInfo frames:** channel UI breaks or the UC conn drops ⇒ the
   per-member fan-out is not how the real server populated the list; fall back to a single
   list-style frame and re-derive from `UserCommConnection::UserJoinedReceived@sadk_noav`.

## Verification

Cheap and entirely player-visible — two clients, join the same channel, type. No TTD needed
unless prediction 4 fires, in which case
`ttd_calls` on `UserCommConnection::ChatChannelListReceived` / `UserJoinedReceived` is the probe.
