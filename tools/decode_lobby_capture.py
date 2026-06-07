#!/usr/bin/env python3
"""
decode_lobby_capture.py — walk a raw TinCat capture and label every frame.

Use it on the REAL captured traffic to see exactly what the client does, e.g.:
    python decode_lobby_capture.py Settlers-AdK-lobby-emulator/data/tincat_lobby_onlineconnect.bin
    python decode_lobby_capture.py Settlers-AdK-lobby-emulator/data/tincat_localhost.bin
    python decode_lobby_capture.py Settlers-AdK-lobby-emulator/data/tincat_171.bin

The .bin files are raw concatenated TinCat frames (28-byte header + payload).
This prints, per frame: byte offset, frame type, From/To, the application
message type (by name), and a hex+ascii dump of the payload. For the messages
that matter for lobby-world entry (170 GameServerData, 171 GetServers,
189/192 chat-server, 221/222 ConnectToServer) it also decodes key fields.

AdK payload magic = 0x26B6. Pass --dng for the S2-10th capture (magic 0x27D8).
"""
import sys, struct, argparse

PREFIX_SIZE = 0x1C  # 28
HDR_MAGIC   = 0xDABAFBEF
FROM_CLIENT = 0xEFFFFFEE
FROM_SERVER = 0xEFFFFFCC

FRAME_TYPES = {2: "ApplicationMessage", 3: "HandshakeConnect",
               5: "HandShakeConnected", 11: "Ping"}

MSG_NAMES = {
    1:"Simple",2:"ChatMessage",3:"PrivateChatMessage",4:"RequestLogin",
    5:"ChatUserInfo",6:"ChatDisconnected",17:"JoinChatChannel",
    42:"ResultStatusMsg",53:"GetUserInfo",55:"GetPlayerInfo",
    56:"RequestUserBuddyList",59:"SendUserInfo",60:"SendPlayerInfo",
    71:"RequestCreateAccount",72:"SelectNickname",75:"SelectNicknameReply",
    77:"RegisterNickname",86:"AddCharacter",88:"ConfirmNickname",
    94:"RemoveCharacter",98:"AddUserBuddy",99:"RemoveUserBuddy",
    105:"RequestMOTD",106:"SendMOTD",107:"RegObserverGlobalChat",
    108:"DeregObserverGlobalChat",109:"UserLoggedIn",110:"UserLoggedOut",
    115:"RegObserverUserLogin",116:"DeregObserverUserLogin",
    146:"PlayerJoinedServer",153:"StatusWithId",157:"RequestUserIgnoreList",
    158:"GetCDKeys",159:"SendCDKey",161:"PropertyGet",162:"PropertyData",
    165:"Chat",168:"RegisterServer",169:"UnlistServer",170:"GameServerData",
    171:"GetServers",172:"StopServerUpdates",175:"JoinServer",
    176:"LeaveServer",177:"UpdateServerInfo",188:"VersionCheck",
    189:"GetChatServer",190:"PlayerLeftServer",192:"SendChatServerInfo",
    201:"Login",202:"LoginReply",203:"RegisterUser",204:"LoginUser",
    206:"LoginServer",207:"LoginReplyCipher",211:"LoginChat",
    212:"LoginChatReply",213:"VerifyChatLogin",221:"ConnectToServer",
    222:"ConnectToServerReply",223:"PlayerConnecting",
}

def hexdump(data, indent="      ", w=16):
    out=[]
    for i in range(0, len(data), w):
        c=data[i:i+w]
        h=' '.join(f'{b:02x}' for b in c)
        a=''.join(chr(b) if 32<=b<127 else '.' for b in c)
        out.append(f"{indent}{i:04x}  {h:<{w*3}}  |{a}|")
    return '\n'.join(out)

class R:
    def __init__(s,d): s.d=d; s.p=0
    def u8(s):  v=s.d[s.p]; s.p+=1; return v
    def u16(s): v=struct.unpack_from('<H',s.d,s.p)[0]; s.p+=2; return v
    def u32(s): v=struct.unpack_from('<I',s.d,s.p)[0]; s.p+=4; return v
    def i32(s): v=struct.unpack_from('<i',s.d,s.p)[0]; s.p+=4; return v
    def boolean(s): return s.u8()!=0
    def s(s):
        l=s.i32()
        if l<=0: return ""
        v=s.d[s.p:s.p+l]; s.p+=l
        return v.rstrip(b'\x00').decode('iso-8859-15','replace')
    def blob(s):
        l=s.i32()
        if l<=0: return b""
        v=s.d[s.p:s.p+l]; s.p+=l; return v
    def rem(s): return len(s.d)-s.p

def decode_170(payload, off):
    """Try both 170 layouts and report which parses cleanly to the end."""
    body = payload[off:]
    # AdK byte-count layout
    try:
        r=R(body)
        f=dict(ServerId=r.u32(), Name=r.s(), OwnerId=r.u32(), Description=r.s(),
               Ip=r.s(), Port=r.u32(), ServerType=r.u8(), LobbyId=r.u32(),
               Version=r.s(), MaxPlayers=r.u8(), CurPlayers=r.u8(), AiPlayers=r.u8(),
               Level=r.u8(), GameMode=r.u8(), Hardcore=r.boolean(), Map=r.s(),
               Running=r.boolean())
        dl=r.i32(); f['DataLen']=dl
        if dl>0: r.p+=dl
        f['TicketId']=r.u32()
        f['_layout']='adk-byte'; f['_leftover']=r.rem()
        return f
    except Exception as e:
        return {'_layout':'adk-byte FAILED','_err':str(e)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--dng", action="store_true", help="use S2-10th payload magic 0x27D8")
    ap.add_argument("--max", type=int, default=0, help="stop after N frames (0=all)")
    args=ap.parse_args()

    pmagic = 0x27D8 if args.dng else 0x26B6
    data=open(args.file,"rb").read()
    print(f"# {args.file}  ({len(data)} bytes)  payload_magic=0x{pmagic:04X}\n")

    pos=0; idx=0
    while pos + PREFIX_SIZE <= len(data):
        magic,frm,to,typ,unk,psz,csum = struct.unpack_from('<IIIIIII', data, pos)
        if magic != HDR_MAGIC:
            # resync: scan for next header magic
            nxt = data.find(struct.pack('<I', HDR_MAGIC), pos+1)
            if nxt < 0: break
            print(f"  ! non-frame bytes {pos}..{nxt} skipped")
            pos=nxt; continue
        payload = data[pos+PREFIX_SIZE: pos+PREFIX_SIZE+psz]
        side = "CLIENT" if frm==FROM_CLIENT else ("SERVER" if frm==FROM_SERVER else f"{frm:08X}")
        ftype = FRAME_TYPES.get(typ, f"type{typ}")
        print(f"[{idx}] @0x{pos:04x} {ftype} from={side} payload={psz}B")

        if typ == 2 and len(payload) >= 6:
            pm,t1,t2 = struct.unpack_from('<HHH', payload, 0)
            if pm == pmagic:
                name = MSG_NAMES.get(t1, f"Unknown({t1})")
                print(f"      APP type={t1} ({name})  [t2={t2}]")
                if t1 == 170:
                    print(f"      170 fields: {decode_170(payload, 6)}")
            elif pm == 0x0062:
                print(f"      CHAT frame Type={t1} Id={t2}")
            else:
                print(f"      (payload magic 0x{pm:04X} — not {pmagic:04X})")
        print(hexdump(payload))
        print()

        pos += PREFIX_SIZE + psz
        idx += 1
        if args.max and idx >= args.max: break

    print(f"# decoded {idx} frames")

if __name__ == "__main__":
    main()
