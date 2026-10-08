// npcmodels: the NPC record's bdyprt nibble picks the npc_bodyparts.xml set (docs/BINARY_PATCHES.md, "NPC model
// sets"; docs/village-and-character-protocol.md §5.1).
//
// Lobby::CGfxObjAvatar::UpdateAppearance S 00508090 picks an NPC's model with AvatarBodyParts::AcquireVariant(set, 0,
// npcidx), but its NPC branch hard-codes the set to 0 (`XOR EBX,EBX`), so the female, MacDoyleJr and MacGabhan sets
// are never shown. The record's bdyprt nibble reaches the NPCProxy (+0x48, NPCProxy::ReadFromMessage S 0047b5c0) and
// is otherwise unused for NPCs; this patch makes it the set number. bdyprt 0 (every record NPC so far) behaves as
// before.
//
// At 005081db, after `CALL ActorProxy::AsType2` (EAX = the NPCProxy):
//   MOV EDX,[EAX] / MOV ECX,EAX / MOV EAX,[EDX+0x1C] / XOR EBX,EBX / CALL EAX / MOV EBP,EAX
// becomes
//   MOVZX EBX,BYTE [EAX+0x48] / MOV EDX,[EAX] / MOV ECX,EAX / CALL [EDX+0x1C] / MOV EBP,EAX
// EBX is the set, EBP the NPC index (the proxy's vtbl+0x1c, unchanged). There is no room for a bounds check: the
// server must only send a set that exists (0-3 in the shipped file) and an index below that set's size.
#include <sadkmod/sadkmod.hpp>

bool npcmodels_start()
{
    bool ok = sadk::patch(0x005081db, {0x8B, 0x10, 0x8B, 0xC8, 0x8B, 0x42, 0x1C, 0x33, 0xDB, 0xFF, 0xD0, 0x8B, 0xE8},
                          {0x0F, 0xB6, 0x58, 0x48, 0x8B, 0x10, 0x8B, 0xC8, 0xFF, 0x52, 0x1C, 0x8B, 0xE8},
                          "NPC model set from bdyprt");
    sadk::log("%s", ok ? "bdyprt selects the npc_bodyparts.xml set" : "patch NOT active");
    return ok;
}

SADKMOD_MAIN(npcmodels_start, 1, SADKMOD_LOBBY)
