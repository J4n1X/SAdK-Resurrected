# Engagement Record — push LoginSuccess(0xDCA) when the REFEREE conn's base login completes

- **Date:** 2026-07-27
- **Type:** Stub wire-change (trigger `referee.send_login_success` off the referee 153; **no flag**)
- **Status:** ⏳ proposed — awaiting user approval
- **Builds on:** `2026-07-27_referee-address-via-post-assign-170.md` (assign half) + the 221/222 fix
  (`835d720`), which together got the client to dial `:5481` for the first time.

## Where we are — measured this run (`stub_221ref.out`)

```
15:14:10.734  TYPE 221 RequestConnectionData  perm_id=1 server_id=77
15:14:10.734  → ConnectionData(222) server=77 → 192.168.1.130:5481  [REFEREE]
15:14:10.743  CONNECTION #19 192.168.1.134 -> :5481 [referee]
15:14:10.802  #19 HandShakeConnected → 188 CheckVersion 27.0 → 211 → 212
15:14:10.990  #19 213 SendToken perm_id=1 → AckResult(153) errorcode=0
              …then NOTHING.
15:14:11.1xx  #20 same, perm_id=2 ('test2')
```

Both clients reach the referee and complete the base TinCat login. The socket then goes silent.

## Why it stalls

`RefereeServerConnection::Login@0x004793f0` **sends no message** — its body is a log-scope prologue
plus `conn->vtbl[0x10](transport, 0)` (open the channel). So **nothing on the wire ever requests a
login result**; the referee server must PUSH `LoginSuccess(0xDCA)`.

`referee.send_login_success()` already exists and builds exactly that frame. It is only reached from
`referee.handle_frame()`, i.e. on the first referee *channel* frame the client sends — and the
client never sends one. The module's own `[VERIFY LIVE]` note flagged this trigger as unconfirmed;
this run answers it.

## The change

In `dispatch._h_send_token`, after the 153 ACK, mirror the existing `is_chat` hook:

```python
if getattr(conn, "is_referee", False):
    referee.send_login_success(conn)      # on a short timer, see below
```

`send_login_success` is already idempotent (`_ref_login_sent`) and already uses
`conn.player.perm_id`.

**Delay:** 0.5 s on a daemon `threading.Timer`, matching the previous implementation
(`stub_reflogin.out`: *"153 ACK — pushing LoginSuccess(0xDCA) in 0.5s"*). Rationale: a bare frame
sent too early was previously associated with a client-side crash
(memory `referee-loginsuccess-crash-template`), and the 153 must first drive the client's own
LoggedIn transition. Cheap insurance; revisit if it proves unnecessary.

## ⚠️ Doc correction shipped with it

`referee.py` lines 17–19 claim *"The verdict is the MESSAGE ID, not the PermID value
(RefereeServerConnection_OnLoginSuccess reads PermID but never validates it)."* **That is false and
load-bearing.** `OnLoginSuccess@0x0047ac20`:

```asm
0047acbf  MOV EDX,[0x007db510]   ; local = INVALID sentinel (measured 0)
0047ace1  CALL 0x0048f490        ; SelectField(msg,"PermID")   name string @0x7dc6f0
0047acf4  CALL EDX               ; read 32 bits into the local
0047ad04  CALL 0x00462510        ; returns LobbyManager+0x54c  (measured = 1 for 'test')
0047ad09  CMP  [ESP+0x10],EAX
0047ad0d  JNZ  skip              ; <-- mismatch => returns SILENTLY, no log, no error
0047ad15  CALL 0x00479ef0        ; +0x80 fan-out -> Lobby_HostRegisterGameWithReferee -> RegisterGame
```

So `PermID` **must** equal the client's own id — 1 for `test`, 2 for `test2`. Sending a constant
would silently work for one client and silently fail for the other. The existing per-connection
`perm_id` is correct; the comment is what needs fixing.

## Falsifiable predictions

1. **Success:** the `+0x80` fan-out runs → `Lobby_HostRegisterGameWithReferee@0x00432240` →
   **`RegisterGame(0xDB6)`** arrives on `:5481` from the host. `referee.handle_frame` then answers
   `RegisterGameAck(0xDB7,0)` + `RegisterGameResult(0xDB8,0,GameSeed)`.
2. **Silent no-op:** nothing arrives after our push ⇒ either the framing is wrong (the
   `SendGameData(74)` envelope in `referee_payload` is still `[VERIFY LIVE]`) or `PermID` mismatched.
   Distinguish with TTD: `ttd_calls 0x0047ac20` (did OnLoginSuccess run at all?) and, if it ran,
   read the compared values.
3. **Crash / disconnect on `:5481`** ⇒ the framing is wrong; fall back to capturing the raw bytes.

## ✅ OUTCOME — prediction 2 hit, and it was the framing (resolved statically)

Live 2026-07-27 (`stub_refok.out`): both pushes went out
(`LoginSuccess(0xDCA, perm_id=1)` conn #7, `perm_id=2` conn #8, 20B each), both referee sockets
stayed open, and **nothing came back** — no `0xDB6`, no disconnect.

Root cause found without a trace. `RefereeServerConnection_OnReceive` is invoked as
`vtbl[0x24](channel, &bitStream)` and passes both straight to
`LobbyMessage_InitFromWire@0x0048fa50(this, typeWord, byteBuffer)`:

```c
*(this+0x20) = (typeWord >> 15) & 1;   // names
*(this+0x24) = (typeWord >> 12) & 7;   // category
*(this+0x28) = typeWord & 0xfff;       // ID  <- from the ARGUMENT
*(this+0x08) = *(byteBuffer+4);        // field data ptr
*(this+0x0c) = *(byteBuffer+8);        // field data length
```

The id comes from the **u32 channel**; the MEMBLOCK is **pure field data** — exactly the village
shape. `referee_payload` was additionally repeating the type word as a `u16` at the head of the
MEMBLOCK, so `OnLoginSuccess` read `PermID` as `0x00013DCA` (type word + low half of perm_id 1)
instead of `1`, mismatched the guard at `0047ad09`, and returned silently. Frame accepted, ignored.

Fixed: MEMBLOCK now carries fields only (18B frame, `inner = 01000000` → PermID reads 1). The
receive-side `_inner_msg_id` was corrected the same way (type word read from offset 6, `game_id`
from inner offset 0 instead of 2).

## Verification

Cheap first: host + Start, then read `stub_221ref.out` for `RegisterGame(0xDB6)` inbound on the
referee conn. Only record TTD if it silently no-ops (prediction 2), where `ttd_calls 0x0047ac20`
is the decisive query.
