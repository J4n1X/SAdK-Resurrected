"""
Village NPCs — server-driven, so the lobby world feels alive.

Two mechanisms, both the client's own (nothing invented):

1. **Record NPCs — PlayerCreate(1004), the real NPC system.** The record carries
   `npcdesc` (the label), a static location, 4-bit colour nibbles, `npcidx`/`bdyprt`
   (model selection), `npctyp` (1 = "settler" template person, 2 = "letterbox") and up
   to 3 (act, actChat) action slots. The consumer (`FUN_005031a0`, subscribed on
   villageConn+0x38 → `FUN_004f6ea0`) builds the visible object from the template the
   moment the record arrives — one message, no refresh stream. [HYPOTHESIS] record
   objects are not waypoint-ring driven, so they persist without location refreshes
   (the letterbox certainly does not jog in place); falsified if they vanish after 3 s.

2. **Walkers — EntityCreate(1001) avatars**, byte-identical to remote players: styled
   body, kept alive and MOVED by the 1 Hz waypoint refresh. Purely ambient motion; no
   interactivity is possible on this path.

IDs live at NPC_ID_BASE and up — far above the sequential player perm_ids handed out
from 1 (players.py) — so they can never collide with a real player.

Appearance + interaction, all [PROVEN 2026-08-02] against `AvatarVisual_RefreshStyleModel
@0x00508090` and the LobbyAction table in `FUN_004325b0`:
  * object type lives at proxy+8 — **1 = AvatarProxy (player), 2 = NPCProxy (record)** — and
    routes the model lookup: type 2 takes the model index straight from **npcidx** (vtbl+0x1c
    → +0xc0); type 1 computes bodypart + (tribe−1)×3 from the **trbgndr** nibbles instead.
  * colours land in proxy+0x49..+0x4c (+0x4d..+0x50 for avatars) and tint the chosen model.
  * **act = a LobbyAction id, not an emote** (see the ACT_* constants) — this is why every v2
    NPC opened the minigame dialog.

[TODO] npcidx→appearance and the colour palette are only knowable by eyeball (or from the
encrypted game data); whether `actChat` is a button label or a spoken line is unresolved —
the button-fill path bottoms out in unreliable decompilation and was NOT guessed at.
"""
import math
import threading
from dataclasses import dataclass, field

#: Synthetic avatar-id floor. Player perm_ids are handed out sequentially from 1
#: (players.py `_next_perm`); one million leaves six orders of magnitude of headroom.
NPC_ID_BASE = 1_000_000

#: Outdoor square values: zone 0 is the village square; ghost-zone 15 is the neutral
#: "no ghost zone" sentinel (1001 walkers only — the 1004 location block has no
#: ghost-zone field at all).
SQUARE_ZONE = 0
NO_GHOST_ZONE = 15

#: `npctyp` values with a visual in FUN_004f6ea0. Anything else renders nothing.
NPCTYP_SETTLER = 1
NPCTYP_LETTERBOX = 2

# ── `act` = the LobbyAction enum [PROVEN 2026-08-02, FUN_004325b0] ────────────
# ⛔ The old "act ids are chat emotes (0 laugh, 1 dance, ...)" reading was WRONG, and the live
# test named it: EVERY NPC opened the minigame matchmaking dialog, because the emote ids we sent
# (4 = "bow", 2 = "applaus") both fall in the 2..6 band that maps to MinigameMatchmaking.
#
# `FUN_004325b0(screen, slot, actionId)` sets one of the three village-screen action buttons
# (+0x3560/+0x3564/+0x3568) to a named LobbyAction — the string table IS the enum:
#     0, 19 → LobbyAction_None            (button hidden)
#     1     → LobbyAction_HairColor
#     2..6  → LobbyAction_MinigameMatchmaking
#     7     → LobbyAction_Mailbox
#     8, 18 → LobbyAction_HostGame
#     9     → LobbyAction_ListGames
#     10    → LobbyAction_HoF             (hall of fame)
#     11    → LobbyAction_OpenShop
#     else  → LobbyAction_None
#: Probe stock for the shop: (ItemID, Buy, Sell). [TODO] ItemIDs are game-data ids from the
#: encrypted item tables and are NOT derivable from the binary, so this is a deliberate low-id
#: sweep — whichever ids come back as real wares identify themselves, and unknown ids should show
#: as blanks. Prices are arbitrary until the id space is known.
SHOP_STOCK = tuple((item_id, 100 * item_id, 50 * item_id) for item_id in range(1, 9))

ACT_NONE = 0
ACT_HAIRCOLOR = 1
ACT_MINIGAME = 2
ACT_MAILBOX = 7
ACT_HOST_GAME = 8
ACT_LIST_GAMES = 9
ACT_HALL_OF_FAME = 10
ACT_OPEN_SHOP = 11
#: The tailor. DispatchSlotAction (S 00434230) has NO case for code 1 (HairColor only labels the
#: button, S 004325b0), so a code-1 button does nothing — live-confirmed 2026-10-07. Code 17 checks
#: gold >= 50, asks !TAYLOR_QUESTION and opens the tailor; its button gets the generic template but
#: is enabled. [known]
ACT_TAILOR = 17


@dataclass
class Npc:
    perm_id: int
    name: str
    #: Record NPCs (1004): npctyp 1/2. Walkers (1001 avatars): npctyp None.
    npctyp: int = None
    #: Colour slots, landing in proxy bytes +0x49..+0x4c (hrclr, sknclr, shrtclr, trsrclr) and,
    #: for 1001 avatars only, +0x4d..+0x50 (addColor1..4). `AvatarVisual_RefreshStyleModel
    #: @0x00508090` feeds all eight to the model tinting call. [PROVEN offsets; [TODO] palette
    #: semantics — which index is which colour is only knowable by eyeball or from game data.]
    #: 1004 writes these as 4-bit NIBBLES (0..15); the 1001 style block writes full bytes.
    colours: tuple = ()
    #: ⭐ THE model selector for record NPCs [PROVEN]: NPCProxy vtbl+0x1c (`FUN_006ab260`)
    #: returns +0xc0 = npcidx, and `AvatarVisual_RefreshStyleModel` uses it as the model index
    #: for type-2 (NPC) objects, skipping the avatar tribe/gender/bodypart math entirely.
    #: 4 bits on the wire ⇒ 0..15 is the whole space. [TODO] which index looks like what.
    npcidx: int = 0
    #: ⚠️ Written to proxy+0x48, which for AVATARS is the tribe/gender/bodypart byte — but the
    #: NPC branch of the style refresh never reads it. Kept because the wire field exists;
    #: it does NOT affect a record NPC's appearance. [PROVEN 2026-08-02]
    bdyprt: int = 0
    #: Up to 3 (act_id, act_text) pairs — record NPCs only. `act_id` is a LobbyAction (see the
    #: ACT_* constants); it decides which dialog the NPC's button opens.
    #: [TODO] whether `actChat` is the BUTTON LABEL or a spoken line is unresolved — the
    #: button-fill path (`FUN_00433f60`) reads at the limit of reliable static analysis, so it
    #: was left unreversed rather than guessed. Keep the strings short and label-like until a
    #: live look settles it.
    actions: tuple = ()
    #: Shop NPCs only: (shop_id, shop_name, sell_mod, ((item_id, buy, sell), ...)). When set, the
    #: server pushes a ShopInventoryData(0xE11) bound to this NPC's id at world entry — clicking
    #: the NPC sends nothing, so the wares must already be there.
    shop: tuple = None
    #: 1001 walkers only — the `trbgndr` byte. ⭐ PACKING RESOLVED [PROVEN 2026-08-02]:
    #: HIGH nibble = body part (`+0x48 >> 4`, `FUN_0046b5c0`, must be < 3 or the model math
    #: clamps), LOW nibble = gender (`+0x48 & 0xF`, `FUN_0046b5d0`, used as a boolean).
    #: Avatar model index = bodypart + (tribe − 1) × 3, tribe from vtbl+0x18 clamped to 1..5.
    #: 0 means body part 0 / gender 0 for everyone — which is exactly why the walkers all wore
    #: the same default look.
    tribe_gender: int = 0
    anchor: tuple = (0.0, 0.0, 0.0)
    rot_deg: float = 0.0
    #: Walkers only: looped patrol path of absolute (x, z) waypoints, `speed` units/s.
    path: tuple = ()
    speed: float = 0.0
    running: bool = False
    _seg: int = field(default=0, repr=False)
    _dist: float = field(default=0.0, repr=False)
    _pos: tuple = field(default=None, repr=False)

    def __post_init__(self):
        if self._pos is None:
            self._pos = self.anchor

    @property
    def is_record(self):
        return self.npctyp is not None

    def record_kwargs(self):
        """Kwargs for `village.send_player_create` (1004) — record NPCs only."""
        return {"pos": self.anchor, "rot_deg": self.rot_deg, "zone": SQUARE_ZONE,
                "colours": self.colours, "npcidx": self.npcidx, "bdyprt": self.bdyprt,
                "npctyp": self.npctyp, "actions": self.actions}

    def style(self):
        """AvatarStyle dict for `village.entity_create_body` (1001) — walkers only."""
        return {"name": self.name, "tribe_gender": self.tribe_gender,
                "colours": self.colours}

    def pose(self):
        """Location kwargs for `village.send_entity_create` — walkers only."""
        return {"pos": self._pos, "rot_deg": self.rot_deg,
                "zone": SQUARE_ZONE, "ghost_zone": NO_GHOST_ZONE,
                "running": self.running}

    def advance(self, dt):
        """Move a walker `dt` seconds along its loop; no-op for everything else."""
        if not self.path or self.speed <= 0.0:
            return
        remaining = self.speed * dt
        y = self.anchor[1]
        while remaining > 0.0:
            ax, az = self.path[self._seg]
            bx, bz = self.path[(self._seg + 1) % len(self.path)]
            seg_len = math.hypot(bx - ax, bz - az)
            if seg_len <= 1e-6:
                self._seg = (self._seg + 1) % len(self.path)
                self._dist = 0.0
                continue
            if self._dist + remaining < seg_len:
                self._dist += remaining
                remaining = 0.0
            else:
                remaining -= seg_len - self._dist
                self._seg = (self._seg + 1) % len(self.path)
                self._dist = 0.0
                continue
            frac = self._dist / seg_len
            self._pos = (ax + (bx - ax) * frac, y, az + (bz - az) * frac)
            # Face the direction of travel. [TODO] 0-degree convention unverified;
            # wrong mapping is purely cosmetic (a sideways-walking settler).
            self.rot_deg = math.degrees(math.atan2(bx - ax, bz - az)) % 360.0


_lock = threading.Lock()


def make_village_npcs(center):
    """The default ambient cast, placed around the village spawn square.

    `center` is dispatch.VILLAGE_SPAWN_POINT — the one spot whose ground height
    (y=2.71) is [PROVEN] (TTD `avatar_spawn_diag.run`). Everything stays within a few
    units of it so nobody stands inside unknown terrain."""
    cx, cy, cz = center

    def at(dx, dz):
        return (cx + dx, cy, cz + dz)

    def loop(*offsets):
        return tuple((cx + dx, cz + dz) for dx, dz in offsets)

    # ⭐ Each record NPC gets a DISTINCT npcidx (the model selector) and an action that matches
    # its role, so one look in-world reads out the npcidx→appearance table: whichever settler
    # looks wrong is named, and its index is right here.
    return [
        # ── Record NPCs (1004) — labelled, model-varied, each opening a real lobby dialog.
        Npc(NPC_ID_BASE + 1, "Händler Hinnerk", npctyp=NPCTYP_SETTLER,
            anchor=at(3.5, 2.0), rot_deg=225.0, colours=(2, 1, 3, 1), npcidx=1,
            actions=((ACT_OPEN_SHOP, "Zum Laden"),),
            shop=(1, "Hinnerks Krämerladen", 1.0, SHOP_STOCK)),
        Npc(NPC_ID_BASE + 2, "Magd Mathilde", npctyp=NPCTYP_SETTLER,
            anchor=at(-4.0, 3.0), rot_deg=135.0, colours=(1, 0, 4, 2), npcidx=2,
            actions=((ACT_TAILOR, "Neue Frisur"),)),
        Npc(NPC_ID_BASE + 3, "Alter Anselm", npctyp=NPCTYP_SETTLER,
            anchor=at(0.5, -4.5), rot_deg=0.0, colours=(0, 2, 1, 3), npcidx=3,
            actions=((ACT_HALL_OF_FAME, "Ruhmeshalle"),)),
        Npc(NPC_ID_BASE + 7, "Herold Hartmut", npctyp=NPCTYP_SETTLER,
            anchor=at(-2.0, -2.5), rot_deg=45.0, colours=(3, 1, 5, 4), npcidx=4,
            actions=((ACT_LIST_GAMES, "Partien ansehen"),
                     (ACT_HOST_GAME, "Partie eröffnen"))),
        Npc(NPC_ID_BASE + 8, "Spielmeister Silas", npctyp=NPCTYP_SETTLER,
            anchor=at(4.5, -3.5), rot_deg=300.0, colours=(5, 2, 0, 2), npcidx=5,
            actions=((ACT_MINIGAME, "Minispiel"),)),
        Npc(NPC_ID_BASE + 6, "Briefkasten", npctyp=NPCTYP_LETTERBOX,
            anchor=at(6.5, -2.0), rot_deg=90.0,
            actions=((ACT_MAILBOX, "Post"),)),
        # ── Walkers (1001 avatars) — ambient motion via the waypoint ring.
        #    trbgndr now VARIES (high nibble = body part 0..2, low = gender): 0x00 left both
        #    walkers on model index (tribe−1)×3, i.e. the identical default look.
        Npc(NPC_ID_BASE + 4, "Wächter Wilhelm", tribe_gender=0x10,
            colours=(3, 1, 2, 0, 1, 2, 3, 4),
            anchor=at(6.0, 6.0), path=loop((6, 6), (6, -6), (-6, -6), (-6, 6)),
            speed=1.0),
        Npc(NPC_ID_BASE + 5, "Bote Balduin", tribe_gender=0x21, running=True,
            colours=(4, 0, 5, 1, 2, 3, 4, 5),
            anchor=at(-8.0, 0.0), path=loop((-8, 0), (0, 8), (8, 0), (0, -8)),
            speed=2.2),
    ]


def record_npcs(npc_list):
    return [n for n in npc_list if n.is_record]


def walker_npcs(npc_list):
    return [n for n in npc_list if not n.is_record]


def advance_all(npc_list, dt):
    """Advance every walker one ticker step. Called only from the location ticker."""
    with _lock:
        for npc in npc_list:
            npc.advance(dt)
