"""
Global game-server registry.

A process-global, thread-safe store for hosted games (AddGameServer 168), keyed by a
globally-unique server_id and tagging each game with the owning connection id, so a game
hosted by client A is:
  * listed cross-client (any client's 166/171 sees every hosted game),
  * resolved by RequestConnectionData(221) regardless of which client owns it,
  * cleaned up when the owning connection drops.
"""
import threading


class GameRegistry:
    def __init__(self, first_id=100):
        self._lock = threading.Lock()
        self._games = {}            # server_id -> info dict (carries "_owner" conn id)
        self._next_id = first_id

    def add(self, owner_conn_id, info):
        """Register a hosted game; returns the assigned globally-unique server_id."""
        with self._lock:
            sid = self._next_id
            self._next_id += 1
            rec = dict(info)
            rec["id"] = sid
            rec["_owner"] = owner_conn_id
            self._games[sid] = rec
            return sid

    def remove(self, owner_conn_id, sid):
        """Remove a game iff it is owned by this connection. Returns True if removed."""
        with self._lock:
            rec = self._games.get(sid)
            if rec is not None and rec.get("_owner") == owner_conn_id:
                del self._games[sid]
                return True
            return False

    def get(self, sid):
        """A copy of the game record, or None."""
        with self._lock:
            rec = self._games.get(sid)
            return dict(rec) if rec else None

    def get_owned(self, owner_conn_id):
        """A copy of the (first) game hosted by this connection, or None.
        A connection hosts at most one game (the ChangeGameServer model)."""
        with self._lock:
            for rec in self._games.values():
                if rec.get("_owner") == owner_conn_id:
                    return dict(rec)
            return None

    def update_owned(self, owner_conn_id, changes):
        """Apply `changes` to the (first) game owned by this connection — the model
        ChangeGameServer(177) follows (a connection hosts one game). Returns the
        updated copy or None."""
        with self._lock:
            for rec in self._games.values():
                if rec.get("_owner") == owner_conn_id:
                    rec.update(changes)
                    return dict(rec)
            return None

    def list_by_type(self, server_type):
        """Copies of all games matching server_type (0 == any), in insertion order."""
        with self._lock:
            return [dict(r) for r in self._games.values()
                    if server_type == 0 or r.get("server_type") == server_type]

    def remove_owner(self, owner_conn_id):
        """Drop every game owned by a (now-disconnected) connection. Returns the ids."""
        with self._lock:
            dead = [s for s, r in self._games.items()
                    if r.get("_owner") == owner_conn_id]
            for s in dead:
                del self._games[s]
            return dead

    def clear(self):
        with self._lock:
            self._games.clear()


# Process-global singleton shared by every connection.
games = GameRegistry()
