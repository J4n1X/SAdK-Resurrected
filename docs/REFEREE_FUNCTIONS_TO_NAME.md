# Functions to name in Ghidra (s39.5–39.6 RE harvest)

> ## ✅ STATUS s40: SECTIONS A–C + E APPLIED to `sadk_noav.exe` (32 functions, names+signatures+plate
> comments+local renames), via the xebyte GhidraMCP `run_script_inline` endpoint (`tools/ghidra_inline.py`
> + `tools/apply_ghidra_names.py`; plan = `docs/referee_naming_plan.json`, derived by the `referee-fn-naming`
> workflow). Verified 32/32 renamed + commented in a separate read-back. **Apply in ONE combined script** —
> 32 rapid separate POSTs race on async commit and silently drop most. Corrections found live: `0x00479ab0`
> = **GiveUpGame** (not FinishGame); the real SEND methods **FinishGame=`0x00479c40`**, **ClaimChest=`0x00479670`**;
> NComm `Manager_HandleNCommEvent` entry = **`0x0040e560`** (old `0x40e720` is mid-body); referee-login pump =
> **`LobbyGameScreen_Update`=`0x00435980`**, arm = **`LobbyGameScreen_OnVillageConnectionLoggedOut`=`0x004316c0`**.
> **Section D (tincat3.dll) DONE too:** cross-program apply+`df.save` (`docs/tincat3_naming_plan.json`) named the
> 3 unnamed ones — **`GameServerManager_AssignServer`=`0x10021830`** (NETMSG 0xbd=189), **`GameServerManager_OnGameServerAssigned`=`0x10021520`**
> (type4/subtype5 referee gate), **`CommLayer_OnUsercommServerData`=`0x10030420`** (192); the other 2 were already named
> (`CommLayer_AllocTicketId`=`0x1002a1c0`, `CommLayer_LookupMsgDescriptor`=`0x1002a240`). tincat3 is SAVED to disk;
> **sadk_noav (32 fns) is in-memory — user must Ctrl+S in Ghidra** (the plugin holds a per-script txn on the active
> program, so it can't be saved from a script: `IOException: Unable to lock due to active transaction`).


Build-34688 addresses (`decomp/sadk/SADK.exe.c`; image base 0x400000; tincat3 0x10000000). These are the
functions reverse-engineered this session that are still `FUN_xxxxxxxx` in the project. Proposed name +
signature + the evidence. **easy** = Sonnet/medium; **complex** = Opus/high.

## A. RefereeServerConnection (`.\LobbyRefereeServerConnection.cpp`) — string-anchored (PROVEN)
SEND methods (build a LobbyMessage via FUN_0048fb00(cat=3,id,size) + named fields + send vtbl[0x0c]):
| addr | name | id | difficulty |
|---|---|---|---|
| 0x004793f0 | RefereeServerConnection::Login | (channel-open) | complex |
| 0x00479540 | RefereeServerConnection::Logout | | easy |
| 0x00479840 | RefereeServerConnection::RegisterGame | 0xdb6 | complex |
| 0x00479ab0 | RefereeServerConnection::FinishGame | 0xdc0 | easy |
| (near 0x00479ab0) | RefereeServerConnection::GiveUpGame | 0xdd4 | easy |
| (near 0x00479540) | RefereeServerConnection::ClaimChest | 0xdac | easy |

RECEIVE handlers (called from the router switch — each reads a field or two; **easy** unless noted):
| addr | name | reads |
|---|---|---|
| 0x0047b090 | RefereeServerConnection::OnReceive (router) | type word → FUN_0048fa50 → switch(msgId) | **complex** |
| 0x0047ac20 | RefereeServerConnection::LoginSuccessReceived | PermID → fires login-complete fan-out (clears match gate) |
| 0x0047ad50 | RefereeServerConnection::LoginFailedReceived | PermID |
| 0x0047a3d0 | RefereeServerConnection::RegisterGameAcknowledgeReceived | GameID, Result |
| 0x0047a580 | RefereeServerConnection::RegisterGameResultReceived | GameID, Result, GameSeed (if Result==0) |
| 0x00479fb0 | RefereeServerConnection::ClaimChestAcknowledgeReceived | GameID, Result |
| 0x0047a160 | RefereeServerConnection::ClaimChestResultReceived | AvatarID, ChestID, str |
| 0x0047a810 | RefereeServerConnection::FinishGameAcknowledgeReceived | |
| 0x0047a9c0 | RefereeServerConnection::FinishGameResultReceived | |
| 0x0047ae80 | RefereeServerConnection::GiveUpGameAcknowledgeReceived | |

## B. LobbyMessage codec (the cat/id/names property bit-stream; SADK side) — **complex** for the parsers
| addr | name | role |
|---|---|---|
| 0x0048fa50 | LobbyMessage::InitFromWire | param_2=typeWord → names=bit15, cat=(>>12)&7, id=&0xfff; ByteBuffer at param_3 | complex |
| 0x0048fb00 | LobbyMessage::LobbyMessage (build ctor) | (category, id, reservedSize) | easy |
| 0x0048eef0 | LobbyMessage::GetMsgId | returns msg+0x28 | easy |
| 0x0048f490 | LobbyMessage::SelectField | (name, 0) — writes/keys the field name when names-on | easy |
| 0x0048f2c0 | LobbyMessage::WriteInt | (value, widthBits=0x20) | easy |
| 0x0048f440 | LobbyMessage::WriteBuffer | (ptr, len, ?) | easy |
| 0x0048fe20 | LobbyMessage::WriteString | (str) | easy |
| 0x0048f3c0 | LobbyMessage::WriteBool | (bool) | easy |
| 0x0048f1c0 | LobbyMessage::WriteByte | (byte, bits=8) | easy |
| 0x0048f4c0 | LobbyMessage::Finalize | flush + 0xFFF end-marker | easy |

## C. Referee assignment chain (LobbyManager + LobbyVillageServerList) — **complex**
| addr | name | role |
|---|---|---|
| 0x004625d0 | LobbyManager::SetRefereeServerAddress | callback; writes serverId→LM+0x580, arms 60000ms timer +0x588 | easy |
| 0x00468f60 | LobbyServerList::RequestRefereeServer | one-shot; calls pGameServerManager->vtbl[0x2c](4,4)=AssignServer, stores SetRefereeServerAddress callback | complex |
| 0x00462910 | LobbyManager::InitRefereeServerConnection | gated on *(LM+0x580)!=0; resolves serverId→ip:port via pComm; inits RefereeConn(LM+0x490) | complex |
| 0x00462760 | LobbyManager::DispatchInboundToConnection | routes inbound data (BitStream) to the matching conn's OnData (vtbl[0x24]) | complex |

## D. tincat3 (GameServerManager / AssignServer / tickets) — **complex**
| addr | name | role |
|---|---|---|
| 0x10021830 | GameServerManager::AssignServer | builds NETMSG 189 (server_type, subtype), registers ticket cat 0x108, sends | complex |
| 0x10021520 | GameServerManager::OnGameServerAssigned (170, cat 0x108) | gates desc.server_type==4 && subtype==5 → fires referee-assigned callback(serverId) | complex |
| 0x10030420 | CommLayer::OnUsercommServerData (192 / 0xc0) | dials advertised ip:port, stands up the UserComm-server conn (no ticket-category check) | easy |
| 0x1002a1c0 | TicketTable::Register | (category, userdata) → ticket_id | easy |
| 0x1002a240 | TicketTable::ResolveCategory | ticket_id → category | easy |

## E. Match-start / referee-login gate (game-screen state machine) — **complex**
| addr | name | role |
|---|---|---|
| 0x0040e720 | Manager::HandleMessage (NComm) | the 0x30001 join handler (version/static-data-checksum kick) | complex |
| (⚠️ NOT the NE_StartLoading handler — it is the village-conn **LoggedOut** observer, corrected 2026-07-25: `LobbyGameScreen_OnVillageConnectionLoggedOut` @`0x4316c0`) | Game::OnStartLoading | sets game+0x3cc=1, +0x3625=1 (do-referee-login), +0x362c=0 (attempts) | complex |
| (referee-login loop @~0x436000, ret 0x435ac5/0x436140) | Game::Update_RefereeLoginPump | per-frame; calls RefereeServerConnection::Login 5x ([Reconnector] timesClientRetries) then aborts | complex |

> ⚠ Apply on the program whose addresses these are (**build 34688 = SADK.exe**). On `sadk_noav.exe` (the clean
> magazine base) the addresses SHIFT — each must be re-anchored by its string/xref first (the porting method).
