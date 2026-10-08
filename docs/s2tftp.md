# S2TFTP: file transfer between match players

The game's own file transfer between the players of a match: TFTP-like packets as TinCat message `0x3eb` (1003) on
the match connection (`NComm::TinCatNetwork`, module `0x27d9`). The game uses it to fetch a map the joiner lacks; the
assetshare mod builds on it (`docs/BINARY_PATCHES.md`, "Map sharing").

- Binary: the DRM-free `SADK.exe` (Ghidra `/sadk_noav.exe`). Tags: **[known]** = read in the binary at the given
  address; **[inferred]** = follows from what was read, not observed; **[live]** = seen in the running game.
- Classes: `ai::net::S2TftpManager` (one per TinCatNetwork, `TinCatNetwork+0xe4`), `ai::net::S2TftpSession` (one per
  peer, 0x9c bytes, in the manager's map by peer net id).

## Packets [known]

All fields little-endian; strings are NComm strings (u16 length + bytes).

| Opcode | Name | Fields after the opcode (u16) | Sent by |
|---|---|---|---|
| 1 | WriteRequest | — | never by this client; answered with Error 5 `!TFTP_ERROR_NO_WRQ_ALLOWED` (`S2TftpManager::OnReceive` 00428110) |
| 2 | ReadRequest | file name | `S2TftpManager::SendRequest` 00425f00 |
| 3 | Data | u16 block size, u16 block number (from 1), u16 total blocks, payload | `S2TftpSession::SendData` 00425d10 |
| 4 | Ack | u16 block number | `S2TftpSession::SendAck` 00425df0 |
| 5 | Error | u16 code, message | 0 `!TFTP_ERROR_FILENOTFOUND`, 1 `!TFTP_ERROR_READERROR`, 2 `!TFTP_ERROR_WRITEERROR`, 5 `!TFTP_ERROR_NO_WRQ_ALLOWED`, 6 `!TFTP_ERROR_NO_CONNECTION` |

## Requesting a file [known]

- `NComm::TinCatNetwork::RequestFileFromHost(remoteName, localPath)` 004190f0 (TinCatNetwork vtable `+0xa4`): if
  connected, `S2TftpManager::RequestFile(0xEFFFFFCC /*the host*/, remoteName, localPath, queueIfBusy = true)`
  00427140; returns true even if the request was refused as a duplicate.
- `RequestFile`: a peer's session that is idle (or finished) starts receiving (`BeginReceive` 004269c0) and the
  ReadRequest goes out. While a transfer with that peer runs, the request is queued (unless an identical one is
  already queued); `S2TftpManager::ProcessQueue` 00427400 starts one queued request per call when the previous one
  has finished. **One transfer per peer at a time.**
- The host answers a ReadRequest by reading `<My Documents>\<file name>` (`OnReceive` 00428110, `BeginSend`
  00426a30), the name unchecked in the game (the assetshare mod restricts it to maps).
- The receiver writes the blocks to a temp file `%LOCALAPPDATA%\s2temps\S2TFTP*` (`S2Tftp_OpenTempFile` 004262e0)
  and renames it to `localPath` when done (`S2TftpSession::CloseFile` 00427990).
- Progress goes to a listener at NComm manager `+0x3d0`: vtable `+0x4` progress (path, block, total), `+0xc`
  started, `+0x10` completed.

## Speed [known; numbers inferred]

The transfer is **stop-and-wait**: the sender sends the next block only when the Ack for the current one has come
back (`S2TftpSession::OnAck` 00427f10), and the receiver acks each block as it arrives (`OnData` 00427cf0). So a
transfer moves **one block per round trip**: throughput = block size / round-trip time. Through the host bridge the
round trip runs joiner → lobby server → host and back, so it is longer than a direct connection.

The block size is chosen by the **sender** (the host) from its own connection type, the option `cConnectionType`
(UserProfile `+0x94`, `UserProfile_GetConnectionType` 0041f220; labels in `nMenu::NetInfo::RefreshInfo` 005fd5a0):

| Connection type | Block size | At 100 ms round trip |
|---|---|---|
| 0 none, 1 modem | 512 bytes | 5 KB/s |
| 2 ISDN | 1 KB | 10 KB/s |
| 3 DSL/cable | 2 KB | 20 KB/s |
| 4 LAN | 4 KB | 40 KB/s |

4 KB is the most the game allows: the session buffer is 0x1000 bytes (`S2Tftp_Session_ReadNextBlock` 00426ac0,
`OnData`). Block numbers and the total are u16, so a file can have at most 65535 blocks (32 MB at 512 bytes, 256 MB at
4 KB).

## Pitfalls [inferred]

- A file whose size is an exact multiple of the block size ends without a short block: the receiver only completes
  on a block shorter than the block size (`OnData`), so it stays in "receiving" while the sender has finished on the
  last Ack. Anything sent this way should not be an exact multiple of 4 KB (or 512 bytes, depending on the host).
- The receiver does not check a Data payload's length against its 0x1000-byte buffer (`OnData`).
