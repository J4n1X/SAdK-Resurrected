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

[TODO] npcidx/bdyprt semantics (model variants?), colour-nibble palette, `act` id
space (emote-id hypothesis: 0 laugh · 1 dance · 2 applaus · 3 crying · 4 bow ·
5 monkey), rot_deg facing convention — all validated by eyeball only.
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

#: [HYPOTHESIS] act ids = the chat emote id space (see docs; consumer not yet reversed).
ACT_LAUGH, ACT_DANCE, ACT_APPLAUS, ACT_CRYING, ACT_BOW, ACT_MONKEY = range(6)


@dataclass
class Npc:
    perm_id: int
    name: str
    #: Record NPCs (1004): npctyp 1/2. Walkers (1001 avatars): npctyp None.
    npctyp: int = None
    #: 1004: FOUR 4-bit nibbles (hrclr, sknclr, shrtclr, trsrclr).
    #: 1001 walkers: up to eight 8-bit bytes (hrclr..addColor4).
    colours: tuple = ()
    npcidx: int = 0
    bdyprt: int = 0
    #: Up to 3 (act_id, chat_line) pairs — record NPCs only.
    actions: tuple = ()
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

    return [
        # ── Record NPCs (1004) — the real thing: labelled, model-varied, interactive.
        Npc(NPC_ID_BASE + 1, "Händler Hinnerk", npctyp=NPCTYP_SETTLER,
            anchor=at(3.5, 2.0), rot_deg=225.0, colours=(2, 1, 3, 1),
            npcidx=1, bdyprt=1,
            actions=((ACT_BOW, "Willkommen, Siedler! Schaut Euch ruhig um."),
                     (ACT_LAUGH, "Feinste Waren, direkt vom Schiff!"))),
        Npc(NPC_ID_BASE + 2, "Magd Mathilde", npctyp=NPCTYP_SETTLER,
            anchor=at(-4.0, 3.0), rot_deg=135.0, colours=(1, 0, 4, 2),
            npcidx=2, bdyprt=2,
            actions=((ACT_DANCE, "Ein Tänzchen gefällig?"),)),
        Npc(NPC_ID_BASE + 3, "Alter Anselm", npctyp=NPCTYP_SETTLER,
            anchor=at(0.5, -4.5), rot_deg=0.0, colours=(0, 2, 1, 3),
            npcidx=3, bdyprt=0,
            actions=((ACT_APPLAUS, "Damals, zu meiner Zeit..."),)),
        Npc(NPC_ID_BASE + 6, "Briefkasten", npctyp=NPCTYP_LETTERBOX,
            anchor=at(6.5, -2.0), rot_deg=90.0),
        # ── Walkers (1001 avatars) — ambient motion via the waypoint ring.
        Npc(NPC_ID_BASE + 4, "Wächter Wilhelm", colours=(3, 1, 2, 0),
            anchor=at(6.0, 6.0), path=loop((6, 6), (6, -6), (-6, -6), (-6, 6)),
            speed=1.0),
        Npc(NPC_ID_BASE + 5, "Bote Balduin", colours=(4, 0, 5, 1), running=True,
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
