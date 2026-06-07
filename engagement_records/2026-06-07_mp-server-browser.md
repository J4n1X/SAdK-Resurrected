# Engagement Record

| Field | Value |
|---|---|
| Date | 2026-06-07 |
| Author (agent/session) | Claude (s39, server-browser implementation; RE workflow wf + indep review agent aab8732aea87beeb9) |
| Tool to be run | Enable `config.ADVERTISE_GAME_SERVERS = True` in `sadk_lobby/config.py` (and confirm `config.LOBBY_PROTOCOL_VERSION` matches the live client), then run the stub against the game. |
| Tool category | **wire-stub change** (the stub emits a NETMSG 170 with `server_subtype=1` that it does not emit today) |
| One-line goal of THIS action | Make WorldScreen's **BrowseGameDialog** (the dead bottom-left BROWSE button in the lobby) populate with a joinable GAME server, and ensure the village browser's Enter button enables — i.e. a FUNCTIONAL server browser. |

---

## 0. Classification check (why this needs the gate)

- [x] This action mutates the **wire protocol** (the stub starts sending a subtype-1 GameServerData(170) it never sends today).
- [x] It is NOT achievable by a read-only probe / Ghidra read (the *test* requires the stub to send the new message to the live client and observe the browser populate + a join reach LobbyManager state 9).

---

## 1. The verified model (MODEL BEFORE MUTATION)

Image base 0x400000, program `sadk_noav.exe` (clean magazine build). All `0x4xxxxx` are SADK.exe addresses.

- **Functions in the path:**
  - `0x46a440` — **LobbyServerList_AddOrUpdateDescriptor** — routes an inbound 170 server descriptor by `ServerSubtype` (descriptor byte **+0x29**): **2 → village list** (this+0x68), **1 → game list** (this+0x7c); `opCode (desc+0x4c)` 1=add/update, 0=remove. **[PROVEN static]** (decompile, this session + s38 workflow).
  - `0x481640` — **VillageServerInfo::FillFromDescriptor** — builds a VILLAGE entry; sets `validity(+0x35)` then GATES it on an embedded **ServerDataBlock**: `if (desc+0x58==5 || desc+0x54!=0) { roomId(+0x30) = read first field BIG-ENDIAN } else { log "Invalid Server Data Block"; validity(+0x35)=0 }`. **[PROVEN static + s15 live]** (live trace read ECX=0xE8030000 from data bytes `E8 03 00 00` ⇒ BE).
  - `0x48da70` — **GameServerInfo fill** (called by GameServerInfo ctor `0x48dc10`) — builds a GAME entry; copies **plain fields only** (server_id, name, map/version string, the literal "Multiplayer", player counts `param_2[0xc..0xe]`, a 4-dword block via `0x416360`, flags `param_2[9]/[0x11]`). **NO ServerDataBlock parse, NO roomId(+0x30), NO validity(+0x35) gate.** **[PROVEN static, decompiled this session]** ⇒ a subtype-1 entry needs no data block to be built.
  - `0x439f30` — **UpdateEnterButton** + `0x468560` — **HasJoinableServerForProtocol** — VILLAGE Enter enables iff `not-busy(+0x21c) && avatar-ready(+0x1ec) && (∃ entry: roomId(+0x30)==DAT_0087aed8 && (cap==0 || load<0x5a) && validity(+0x35)!=0)`. **[PROVEN static]**.
  - `0x465380` — **LobbyClient_LoadProtocolVersion** → `0x4651c0` — `GetPrivateProfileIntA(section, key, default=-1, iniPath@this+0x20)` writes **DAT_0087aed8** (the village match key) only if `!= -1`. **[PROVEN static]**.
- **Stub side (our code, this session):** `sadk_lobby/dispatch.py::server_data_block()` (BE u32 roomId + pending byte) and `_send_server_list()` (now upgrades the demo game entry to `server_subtype=1` **only when** `config.ADVERTISE_GAME_SERVERS`). Village path unchanged.
- **State / offsets:** `desc+0x29` = subtype; `entry+0x30` = roomId; `entry+0x35` = validity; `DAT_0087aed8` = client ProtocolVersion / match key.

- **The model in prose (proven vs hypothesized):**

> The **village** browser already works through the stub: we send a 170 with `server_subtype=2` whose
> `data` MEMBLOCK is a ServerDataBlock (`roomId=1000` BE + pending 0). FillFromDescriptor sets
> `entry.roomId=1000`, keeps `validity=1`; UpdateEnterButton enables Enter when `roomId==DAT_0087aed8`.
> s28 RPM **live-confirmed** the entry JOINABLE with the live match key == 1000. **[PROVEN]**
> The **game** browser (BrowseGameDialog) is empty because the stub **never sends `server_subtype=1`**
> (it sends 2=village and 0=inert; subtype 0 routes to *neither* list). Routing a subtype-1 170 to the
> game list builds a GameServerInfo via `0x48da70`, which needs **no** ServerDataBlock — so a plain
> subtype-1 170 should make the entry appear. **[PROVEN the routing + fill; HYPOTHESIS that "appears +
> joinable" needs nothing more — see §3/§5 and the independent review.]** The change reuses the existing,
> golden-tested 170 encoder; only one field value changes (0→1). The village wire is byte-identical
> (proven by `tests/test_codec_golden.py` still passing + `test_village_data_block_default_byte_identical`).

**Independent review** (mandatory — per `memory/independent-review-protocol-changes.md`):
- [x] **DONE — verdict LOGICALLY SOUND** (read-only agent `aab8732aea87beeb9`, this session, 82 Ghidra
  tool-uses, no writes). Independently re-derived from the binary and CONFIRMED: (1) AddOrUpdateDescriptor
  @0x46a440 branches on `desc+0x29` in TWO independent `if` blocks — subtype 2 → village vector (base+0x70),
  subtype 1 → game vector (base+0x84) via ctor `0x48dc10`/fill `0x48da70`; subtype-1 has no opcode/remove
  handling (every subtype-1 desc is add/update). (2) `0x48da70` copies plain fields only — NO ServerDataBlock
  parse, NO `+0x30` roomId, NO `+0x35` validity (those fields don't even exist on GameServerInfo; confirmed via
  copy-ctors 0x48d310 game[size 0x9c] vs 0x481540 village[0x38]). (3) The GAME join gate is `FUN_004588e0` →
  `FUN_00468480` (look up selected server-id `entry+4` in the game vector) — requires only **a selected row +
  the id present + current < max**; **DAT_0087aed8 (ProtocolVersion) is NOT consulted on the game path at all**
  (its xrefs are exclusively village/connection). UI fill `0x46a3c0` lists the game vector with no
  protocol/validity filter.
  - **ONE correction folded in:** the join gate disables with `"!LOBBY_MATCHMAKING_GAMEISFULL"` unless
    `max_players > current` (entry+0x74 > entry+0x70). The stub now guarantees this in the gated block
    (`cur_players=0`, `max_players≥2`); `tests/test_server_browser.py::test_game_server_subtype_gated`
    asserts `current < max`.
  - **Net de-risk:** the user's actual target — the bottom-left BROWSE button → BrowseGameDialog — needs
    NO ProtocolVersion match (unlike the village Enter button). So the game browser is the *higher-confidence*
    half of this change.

---

## 2. Read-only precondition checks (live system in the EXACT expected state)

⚠️ **Live preconditions are NOT YET CHECKED** because the user is away and the game is not running.
They are read-only and MUST be run (with the user present) **before** flipping the flag. The independent
review (§1) REMOVED the ProtocolVersion precondition from the GAME-browser path (it is village-only) and
confirmed the capacity gate is satisfied — so the only open live item for the user's BROWSE-button target
is which `server_type` BrowseGameDialog actually requests:

| What | Read-only source | REQUIRED value | OBSERVED value | OK? |
|---|---|---|---|---|
| **(VILLAGE browser only)** Client ProtocolVersion = match key `DAT_0087aed8` | RPM read of abs `0x87aed8` on the live game | `== config.LOBBY_PROTOCOL_VERSION` (1000) | **UNKNOWN — game not running** | ❌ NOT YET (village path) |
| **(GAME browser)** Which `server_type` BrowseGameDialog requests (so the stub's type-5 branch fires) | live capture of the 166/171 the dialog sends, or read `bin/<data>/lobbyBrowseGameDialog.xml` / lobbyWorldScreen.xml | `5` (game) | **UNKNOWN** | ❌ NOT YET |
| **(GAME browser)** Capacity gate `max_players > current` | review §1 + `test_game_server_subtype_gated` | `current < max` | **SATISFIED** (gated block sets cur=0, max≥2) | ✅ |
| **(GAME browser)** ProtocolVersion match required? | review §1 (xrefs of DAT_0087aed8) | not required for games | **CONFIRMED not required** | ✅ |
| Offline codec / gating correctness | `python tests/test_server_browser.py` + `tests/test_codec_golden.py` | all pass; default wire byte-identical | **ALL PASS** (this session) | ✅ |
| Default wire unchanged with flag OFF | `test_village_data_block_default_byte_identical`, golden `test_170_matches_legacy_byte_for_byte` | byte-identical to legacy | **PASS** | ✅ |

```
$ python tests/test_server_browser.py
  PASS  test_advertise_game_servers_off_by_default
  PASS  test_fake_game_default_subtype_unchanged
  PASS  test_game_server_subtype_gated
  PASS  test_server_data_block_encoding
  PASS  test_village_170_roundtrip
  PASS  test_village_data_block_default_byte_identical
  All server-browser tests PASSED
$ python tests/test_codec_golden.py
  PASS  test_170_decode_roundtrip
  PASS  test_170_matches_legacy_byte_for_byte   <-- village 170 byte-identical to the working legacy
  PASS  test_registry_loaded
  All golden tests PASSED
```

---

## 3. ⛔ Is the game legitimately WAITING? (THE trap that was hit before)

This is the decisive question, and here it **resolves in favour of the action** — because the action
*is* providing the awaited thing through the game's genuine mechanism, not forcing past it.

- Is the subsystem in a wait-for-message state?
  - **YES.** The server browser is, by design, **waiting for the lobby SERVER to push GameServerData(170)
    descriptors.** The client even *requests* them (NETMSG 166 RequestServers / 171 RegObserverServerList).
    With no server sending subtype-1 descriptors, the game list stays empty — a legitimate wait, not a bug.
- Can we provide it through the GENUINE mechanism instead of forcing?
  - **YES — that is exactly this action.** The stub *is* the lobby server; sending a 170 is the designed,
    real intake (`AddOrUpdateDescriptor` is the client's own observer handler). We are **not** force-calling
    a UI/FSM function, **not** injecting, **not** patching. The client's own code populates the list and
    enables the button in response to a legitimate server message. **[PROVEN: 166/171 request → 170 reply →
    AddOrUpdateDescriptor is the client's designed flow.]**
- **Ruling-out statement:** "The game IS waiting (for server descriptors), and this action supplies them
  through the real wire mechanism (be the server, send 170) — the OPPOSITE of the past trap (force-calling
  `ActivateScreenById` while parked in state 8). No client-side state is forced; the client advances itself."
- [x] I confirm we are **satisfying** a legitimate wait-state via the real mechanism, not forcing past one.

---

## 4. Why this is the GENUINE mechanism, not a shortcut to fake a result

- Sending NETMSG 170 in reply to the client's RequestServers/RegObserverServerList is **literally what the
  original Funatics lobby server did**; `AddOrUpdateDescriptor @0x46a440` is the client's designed handler for
  it. We reproduce real server behaviour, we do not invent client state. **[PROVEN]**
- Where the game itself does this: the client SENDS 166/171 expecting 170 replies (the stub's existing
  `_h_request_servers`/`_h_reg_observer_servers` handlers already answer the village case this way and it
  works live, s28). The game-server case is the same handler, one field value different.
- [x] This is a **genuine feature implementation** (act as the server), not a forced diagnostic. Honesty
  clause: the *effect* on the GAME browser is a hypothesis (village is live-proven; game is new). The result
  will be reported exactly as observed — "the game browser listed/did not list the entry; join reached/did
  not reach state 9" — and never as "MP works" if it does not.

---

## 5. Expected observable + how it is verified READ-ONLY afterward

- Precise expected observable:
  - GAME browser (the BROWSE button) with `ADVERTISE_GAME_SERVERS=True`: **BrowseGameDialog lists "Revival
    Test Game"**, and selecting the row enables Join (gate = selected row + id present in the game vector +
    current<max; NO ProtocolVersion). For the **village** browser (separate, already-working path): with the
    live ProtocolVersion == `LOBBY_PROTOCOL_VERSION`, the Enter button is **enabled** (not greyed) on the
    world1 entry, and a join drives **LobbyManager → state 9** (the stub then pushes msg 1000 unprompted).
- Read-only verification afterward:
  - success: RPM-probe the game list (`this+0x7c` entries) / the village entry `validity(+0x35)!=0` &
    `roomId(+0x30)==ProtocolVersion` via a `read_village_state.py`-style probe; on-screen the button is
    enabled; `probe_appfsm.py` shows LobbyManager state 9 after join.
  - failure / no-op: game list stays empty after the subtype-1 170 (⇒ routing/type assumption wrong); or
    village Enter stays grey (⇒ ProtocolVersion mismatch — fix `LOBBY_PROTOCOL_VERSION`).
- What would FALSIFY the model:
  - A well-formed subtype-1 170 is sent (confirm via the stub log / a capture) but **no game entry appears**
    ⇒ the subtype-1→game-list routing or the dialog's requested server_type is not as modelled ⇒ set the flag
    back OFF and re-RE (do not rationalise). A *crash* on the subtype-1 170 ⇒ the game-fill path has an
    unmodelled precondition ⇒ revert + investigate.

---

## 6. Rollback / blast radius / safety

- Threading/contention: **none** — this is the stub (our Python server) sending a normal application message;
  no injection, no remote thread, no `WriteProcessMemory`, no binary patch. The game is an ordinary network peer.
- Blast radius if the model is wrong: the stub sends **one extra, well-formed 170** (same format the client
  already parses for villages, only `server_subtype` differs) on type-5 server-list requests when no real game
  exists. The **village path is untouched** (golden test byte-identical). Worst realistic case: the client
  ignores the descriptor (empty browser) — no corruption. A crash is possible only if `0x48da70` has an
  unmodelled precondition (the independent review §1 + the live test gate this).
- Rollback plan: set `config.ADVERTISE_GAME_SERVERS = False` (one line) ⇒ wire output **byte-identical to
  today** (golden-tested). Instant, complete, no game/binary state to undo. `LOBBY_PROTOCOL_VERSION` defaults
  to 1000 (the long-standing literal) so it is a no-op unless deliberately changed.
- Disposable / relaunchable target: **yes** — the change is entirely in the stub; the game is relaunchable;
  no user data at risk; no `force_*.py` / `harness_gate.py` token is involved (this is not an injector).

---

## 7. Decision

- [ ] Sections 1–6 completed with real, binary-grounded evidence — **EXCEPT** the two live read-only
  preconditions in §2 (ProtocolVersion value; dialog's requested server_type), which are **NOT YET CHECKED**
  (user away). **This record is STAGED, not ready-to-run, until those are verified.**
- [x] Independent review verdict recorded — **LOGICALLY SOUND** (§1); the one correction (max>current) is
  implemented in the gated block + asserted by `test_game_server_subtype_gated`.
- [x] We are satisfying a legitimate wait-state via the real mechanism (be the server, send 170), not forcing.
- [x] The expected observable and its read-only verification are defined.
- [x] I will report the result as observed, never as a working feature if it is not.

**Requested of the user (when present):**
1. Run the two read-only precondition checks in §2 (live `DAT_0087aed8`; confirm BrowseGameDialog's requested
   server_type) — these are ungated probes.
2. Review the independent-review verdict (§1) once the agent completes.
3. If both pass: approve enabling `config.ADVERTISE_GAME_SERVERS = True` (and set `LOBBY_PROTOCOL_VERSION` to
   the observed live ProtocolVersion if it is not 1000), then run the stub + game and observe per §5.

> No `harness_gate.py` token is required (this is a stub wire change, not a `force_*.py` injector). "Approval"
> here = the user, present, reviewing this record and flipping `config.ADVERTISE_GAME_SERVERS` to test. Default
> stays OFF until then; with it OFF the stub's wire behaviour is unchanged from today.
