# Referee assign — ROOT CAUSE: the s39.6 reply targets SERVER-only code (s41.7, autonomous RE)

**TL;DR.** The live probe proved `LM+0x580` (the referee server id) is **never set** on the game client
(both machines, nonstop poll, every state 1→9). Read-only RE now explains why **structurally**: the
mechanism that turns an `AssignServer` reply into `SetRefereeServerAddress(LM+0x580=60)` lives **only in
the tincat3 SERVER recv state machine, which the game never runs.** Our stub has been crafting a `170(sub5)`
reply for code only the real Funatics lobby server executed. The game client receives it and has **no case
for it** — so `SetRefereeServerAddress` never fires. The whole s39.6 model is *structurally* refuted, not
mis-tuned.

## The chain we THOUGHT fired the assign (s39.6) — and where it actually lives

```
client: RequestRefereeServer (LobbyServerList @0x468f60)
        → pGameServerManager->vtbl[0x2c] = GameServerManager_AssignServer @tincat3 0x10021830
            • builds NETMSG 189 {server_type=4, server_subtype=4}
            • CommLayer_AllocTicketId(table, category=0x108, AssignServerTicketData{type=4,sub=4})
              → ticketId  (this is the cat-0x108 binding — keyed by the ticket the CLIENT allocates)
            • puts ticketId in 189.ticket_id, sends 189
        ... stub replies 170(type4/sub5, id=60, ticket echoed) ...
   >>> reply SHOULD route: case 0xaa(170) → iVar7=LookupMsgDescriptor(ticket)→0x108
        → GameServerManager_OnGameServerAssigned @tincat3 0x10021520  (gate desc+0x28==4 && +0x29==5)
        → fires SADK observer GameServerAssigned @0x469ad0
        → callback SetRefereeServerAddress @0x4625d0  → LM+0x580 = id, LM+0x588 = 60000ms timer
```

**But `get_xrefs_to OnGameServerAssigned` = EXACTLY ONE caller: `CommLayer_ServerRecvHandler_StateMachine
@0x10025134`** — and tincat3's own annotation says *"THE REAL LOBBY SERVER ran THIS; the GAME (client) does
NOT — it runs `CommLayer_ClientRecvHandler_StateMachine @0x10023460`."*

## The game client's recv handlers have NO 170 case — checked ALL of them

tincat3 has role-variant recv state machines (selected by a role vtable; client = 0x1004f8e0, server =
0x1004f954, LAN = 0x1004f9e0, + others). I read every one that does the ticket→category lookup
(`CommLayer_LookupMsgDescriptor @0x1002a240`, xref'd all callers):

| Handler | Role | Wire cases handled |
|---|---|---|
| `CommLayer_ClientRecvHandler @0x10023460` | **GAME (lobby/UC conn)** | 0x2a CheckVersion, 0x99 ACK(153), 0xd4 token(212), 0x49/0x4a bundle |
| `CommLayer_ServerRecvHandler @0x10025134` | real lobby server | 0x2a, 0x99, 0xd4, **0xaa(170)→cat-0x108→OnGameServerAssigned**, 0xd6(214), … |
| `FUN_10027080` | role variant | 0x2a, 0x99, 0xd4, 0x49/0x4a |
| `FUN_100268e0` | role variant (ranking) | 0x2a, 0x99, 0xd4, 0x49/0x4a, **0xfd/0xff/0x101 (ranking: perm_id_a/b, ranktable, points)** |

Only the **server** handler has `case 0xaa`. Every client-side handler with no match → `default:` logs
**"Invalid message-type %u received"** and drops (jump-table bound `CMP 0xAA / JA`). So an inbound **170
reply on the game's lobby connection is dropped** before any lookup. The cat-0x108 routing never runs on
the client.

## The 170 LIST path works, but does NOT fire the assign

The server browser works because 170 *list* entries reach SADK observers
`LobbyServerList_GameServerDataReceived @0x469700` (iterates `count` descriptors, stride 0x5c, →
`AddOrUpdateDescriptor`) and `GameServerAdded @0x469610` (→ `AddOrUpdateDescriptor`). **Both only populate
the list.** Neither touches the pending-assign callback. So "advertise the referee in the list and the
pending RequestRefereeServer matches it" is **refuted** — there is no such match in the list-receive path.

## Conclusion (well-supported)

`SetRefereeServerAddress` (the ONLY writer of `LM+0x580`) is fired **only** by `GameServerAssigned`, fired
**only** by `OnGameServerAssigned`, reachable **only** from the **server** recv handler. The game client
runs none of that on its lobby connection ⇒ `LM+0x580` is **never** set ⇒ `InitRefereeServerConnection`
never dials a real referee ⇒ the match-start referee gate (`LobbyGameScreen_Update`) retries 5× and aborts.
**Exactly what the live probe shows.** All the s41.2–s41.5 downstream work (LoginSuccess framing/timing,
the observer fan-out, the commSystem gate) was chasing a conn that never exists.

> Side note reconciling the stub's `:5481 referee connection opened` log: with `LM+0x580=0` the real
> `RefereeServerConnection@LM+0x490` never gets a transport (probe: `+0x4c4 == 0`). Whatever briefly hits
> our :5481 is a side-effect of our 170/192 reply, NOT the conn the match needs; the stub mislabels it.

## What this means for the fix — and the OPEN QUESTION

We **cannot** make the referee work by crafting a lobby reply: the client has no handler to process it.
That kills the entire "reply to the 189" approach. So the real question is now:

**How did the genuine game ever get a referee?** Hypotheses to investigate next session (read-only):
1. **The referee address is NOT lobby-assigned to the client at all** — it may come from the MATCH/host
   setup (the host hands it to joiners over NComm), or be a fixed/config value. `RequestRefereeServer`'s
   callback may be effectively dead on the client (it can't fire), making the whole `AssignServer` round
   a vestigial/no-op for the client.
2. **There is another writer of `LM+0x580`** we haven't found (verify: is `SetRefereeServerAddress@0x4625d0`
   truly the only writer? a direct byte-scan / data-xref for writes to `LM+0x580` would settle it).
3. **The match can proceed WITHOUT a real referee** and the abort we see is a *different* failure — re-read
   `LobbyGameScreen_Update`'s abort branch precondition with this in mind (`FUN_00408430()==0` = NComm
   handler gone, which the comm.log ShutDown would cause regardless of the referee).
4. **Role subtlety**: confirm the game truly only ever runs the CLIENT handler on the lobby conn (it does
   run the SERVER handler when it *hosts* a P2P game — could the referee handshake be intended to happen in
   a host/server-role context we haven't reproduced?).

## Addresses (sadk_noav / tincat3, confirmed live = sadk_noav via LobbyBaseConnection.cpp:119)
- SADK: `RequestRefereeServer 0x468f60`, `GameServerAssigned 0x469ad0`, `GameServerDataReceived 0x469700`,
  `GameServerAdded 0x469610`, `AddOrUpdateDescriptor 0x46a440`, `SetRefereeServerAddress 0x4625d0`,
  `InitRefereeServerConnection 0x462910`, `RefereeServerConnection_Login 0x4793f0`,
  `LobbyManager_GetCommSystem 0x462510` (returns LM+0x54c).
- tincat3: `GameServerManager_AssignServer 0x10021830`, `GameServerManager_OnGameServerAssigned 0x10021520`
  (xref: server handler ONLY), `CommLayer_ClientRecvHandler 0x10023460`, `CommLayer_ServerRecvHandler
  0x10025134`, `CommLayer_LookupMsgDescriptor 0x1002a240` (ticket→category, key=ticket_id), other recv
  variants `FUN_10027080` / `FUN_100268e0`.
- LobbyManager offsets: state +0x57c, refereeId +0x580, refConn +0x490 (transport +0x34 → +0x4c4),
  connectTimer +0x588, commSystem +0x54c.

---

## s41.8 — SESSION-END HANDOFF (J4n1X continuing in a FRESH session)

Reconciles the contradiction that cost the prior session its coherence, and states the CURRENT model.
**Supersedes any earlier "referee connects then dies / LM+0x580 transiently 60" framing.**

### Confirmed this session — two independent reproductions [PROVEN]
- **`SetRefereeServerAddress@0x4625d0` is the SOLE writer of a real `LM+0x580`.**
  - J4n1X's `tools/ghidra_find_field_writes.py` (OFFSET=0x580): hits = `0x4625fb`, `0x462614`
    (SetRefereeServerAddress) + `0x46419e` (ctor `FUN_00463fd0`, sentinel-init). The two `[ESP+0x580]` hits
    (`FUN_00550e40@0x551cfd`, `FUN_00741360@0x743417`) are STACK locals — false positives.
  - Background agent (full Ghidra trace + cross-checked the build-34688 decomp): identical, exhaustive.
- **Referee address is NOT from NComm/match-host (Q2)** — `Manager_HandleNCommEvent@0x40e560` case
  NE_StartLoading only sets `Manager+0x3cc`. **Nor config/ini (Q4)** — no key/host/IP; resolved by the *id*
  in `LM+0x580`.
- **`LM+0x580 == 0` on the live client, BOTH machines, every state 1→12** (nonstop fast-latch probe).

### The contradiction, RESOLVED
s41/s41.2/s41.3 claimed "connects at village entry, LM+0x580 transiently 60, dies before match-start." That
is **REFUTED** by s41.6 (LM+0x580==0 at EVERY state incl 6) + s41.7/agent routing proof. The referee is
**never** assigned. `:5481 referee connection opened` in `tincat_server.log` is a **SIDE-EFFECT** of our
170/221/222 reply (stub mislabels any :5481 socket "referee" by port) — NOT the gate's
`RefereeServerConnection` (+0x490, needs `LM+0x580` for a transport).

### J4n1X's session-end observation
> "A referee connection, per the tincat log, IS being set up. But the field for the ref is never set, so I
> assume what we're sending the client is not the correct schema."

Reconciled: the :5481 conn is up (side-effect); `LM+0x580` never set. The "wrong schema" instinct is
reasonable, **but** the agent found **NO client-side path to `GameServerAssigned` at all** — every route to
`SetRefereeServerAddress` runs through the SERVER handler `0x10025134` (`OnGameServerAssigned`); the game
runs the CLIENT handler `0x10023460`. So the gap is likely deeper than the wire schema. The schema lead is
worth ONE check (does our advertised 170 referee LIST descriptor meet the client's match criteria for a
pending `RequestRefereeServer`?), but the routing proof says even a match won't fire SetRefereeServerAddress.

### `ARM_REFEREE` LoginSuccess push — a HACK that does NOT work [keep OFF]
Config was `ARM_REFEREE=True` + `REF_USE_GAMEDATA_ENVELOPE=True`. The push fires (tincat log) yet the match
STILL ShutDowns ~13s — empirical proof it does not clear the abort (wrong socket). The `referee.py`
"genuine message... NOT a forced bypass" docstring was FALSE; corrected to honest status this session.
**Recommend `ARM_REFEREE=False` + `ADVERTISE_REFEREE_SERVER=False`** (wire change — J4n1X's call; NOT
flipped here, per the harness).

### Next-session frontier (priority; read-only until an approved ER)
1. **Q1 — referee armed for EVERY match or ranked-only?** s39.5 decomp @42976 sets `doRefereeLogin(+0x3625)
   =1` with **no ranked branch** ⇒ statically every match. **VERIFY LIVE** (J4n1X debugging: BPs `0x4625d0`
   / `0x4793f0` / `0x5eed00`; or `ghidra_find_field_writes.py` OFFSET=0x3624 for the arm + decompile for
   conditionality). **If casual actually skips it → the entire referee wall is moot for host+join.**
2. **Any client-reachable referee path?** Agent: none via the lobby. UNEXPLORED: the host/P2P server-role
   context (the game runs the SERVER recv handler when it hosts). If genuinely none → the referee/ranked
   subsystem required the Funatics server = the stub-approach's structural limit; report honestly.
3. **Identify the :5481 side-effect connection** (read-only capture: what dials it, which connection class).

⚠ OPEN: confirm whether the gate's `RefereeServerConnection` is at **LobbyManager+0x490** (the probe's
assumption) or **LobbyGameScreen+0x490** (the gate's `this` is the LobbyGameScreen). LobbyGameScreen
(WorldScreen, alloc 0x3670): doRefereeLogin +0x3624, armed +0x3625, retry +0x362c (abort at 5).
