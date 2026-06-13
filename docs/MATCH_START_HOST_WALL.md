# Match-start host wall — the game-server request (FUN_0046aaa0) is silent
Status: 2026-06-14, live-debugged on the real binary (dbgeng on the host). Open — one binary question.

TL;DR: host parks on "Connecting to Game Server". Proved live: (a) not waiting on a msg we owe (never
asks); (b) the game-to-start gate is fine (real ptr); (c) the request fn never runs. Crux: does
FUN_0046aaa0 fire on Start? fires -> bails in NComm bring-up (host fix); never fires -> trigger blocked
(button state never 8) -> host waits on an earlier action the stub must feed. Opposite fixes -> capture one Start.

LM live=0x0E919040 (=*0x885890). villageList=LM+0x54; villageList+0x9c=LM+0xf0. Sentinels:
DAT_007db520=-1 (request-needed), DAT_007db524=-2 (pending). Host +0x9c live=-1.
Dialog FUN_00457a00 shows iff NComm_IsHost() AND +0x9c in {-1,-2}.
Request FUN_0046aaa0@0x46aaa0 (when +0x9c==-1): gate FUN_0046c100@0x46c100 reads LM+0x554
(villageConn=*(LM+0x540)=0x0E9195F0; +0x158->LM; LM+0x554 live=0x2D71AD28 -> PASSES) -> "!LOBBY_GAME" ->
NComm Shutdown@0x40b410/StartUpNetwork(4)@0x40a9a0/ConnectAndJoin@0x40ad60 -> AssignServer(189
type5/sub1) via tincat3 0x10021830 -> set +0x9c=-2. Reply -> GameServerAssigned@0x469ad0 -> +0xa0 cb
writes +0x9c -> connect vtbl[0x28] (FUN_004683e0/FUN_00468410) / register vtbl[0x24] (FUN_0046aff0).
Killed live: "RemoveServer nulled ref" (gate passes); "stub owes GameServerAssigned push" (host is
request-needed -1 not pending -2; FUN_0046aaa0 silent 0 hits/4s; zero game-server 189 ever, only
referee 4/4). Callers (action-gated, no auto pump): OnLeaveVillage@0x437760 (popup case0),
FUN_00434230@0x434230 (button dispatch, slot state this+0x356c+slot*4, state8=case6), FUN_004588e0 (join).

CAPTURE RECIPE (tomorrow): 1) dbgeng `python -m debugger` from C:\Users\user\Downloads\ghidra-mcp,
elevated (:8099). 2) stub minisrv .130 @ f926932, SADK_ADVERTISE_IP=.130. 3) both clients to the READY
screen, do NOT Start. 4) debugger_attach <hostPID>; POST /debugger/sync_modules
{"ghidra_bases":{"SADK":"0x400000","tincat3":"0x10000000"}}. 5) arm traces (ghidra_address):
0x46aaa0, 0x10021830 (watch type5/sub1), 0x40b410, 0x40a9a0, 0x40ad60, 0x434230. 6) continue, click
Start. 7) read debugger_trace_log: fires+reaches 0x10021830 type5/sub1 -> sent (server/connect track);
fires not-send -> bails in NComm (read ConnectAndJoin ret); not fire -> trigger blocked (trace 0x434230
state). Notes: addrs 1:1; break-in POST /debugger/interrupt; reads need stopped; detach BEFORE killing game.
Ghidra program sadk_noav.exe / project SaDK.
