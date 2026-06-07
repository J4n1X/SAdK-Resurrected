"""
Golden tests: prove the msgdefs-driven codec reproduces the hard-won, working
legacy serialization byte-for-byte (so the refactor cannot silently regress the
wire format), plus a decode round-trip.

Run directly:   python tests/test_codec_golden.py
Or with pytest: pytest tests/test_codec_golden.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import codec, msgdefs  # noqa: E402

# The village ServerType=4 entry that currently gets us INTO the list (s12/s13).
VILLAGE_SRV = {
    "id": 1, "owner_id": 1,
    "name": "world1", "description": "SaDK Revival Lobby World",
    "ip": "127.0.0.1", "port": 5479,
    "max_players": 20, "cur_players": 1, "ai_players": 0,
    "lobby_id": 1000, "version": "", "server_type": 4, "server_subtype": 2,
    "level": 0, "game_mode": 0, "hardcore": False,
    "map": "world1", "running": True, "data": None,
}
TICKET = 0x12345678


def _srv_to_170_values(srv, ticket):
    """Map a legacy server dict onto canonical msgdefs(170) field names."""
    return {
        "server_id": srv["id"],
        "name": srv["name"],
        "owner_id": srv["owner_id"],
        "description": srv.get("description", ""),
        "ip": srv["ip"],
        "port": srv["port"],
        "password_required": False,
        "server_type": srv.get("server_type", 5),
        "server_subtype": srv.get("server_subtype", 0),
        "version": srv.get("version", ""),
        "max_players": srv.get("max_players", 2),
        "cur_players": srv.get("cur_players", 1),
        "max_spectators": 0,
        "cur_spectators": 0,
        "ai_players": srv.get("ai_players", 0),
        "room_id": srv.get("lobby_id", 9212),
        "level": srv.get("level", 0),
        "game_mode": srv.get("game_mode", 0),
        "hardcore": bool(srv.get("hardcore")),
        "map": srv.get("map", ""),
        "running": bool(srv.get("running")),
        "locked_config": False,
        "data": srv.get("data"),
        "ticket_id": ticket,
    }


def _legacy_170(srv, ticket):
    """Call the legacy monolith's _make_server_payload_old unbound (self unused)."""
    import legacy_tincat_server as legacy
    return legacy.Conn._make_server_payload_old(None, srv, ticket)


def test_registry_loaded():
    assert msgdefs.get(170) is not None
    assert msgdefs.name_of(170) == "GameServerData"
    assert msgdefs.name_of(171) == "RegObserverServerList"
    assert msgdefs.name_of(189) == "AssignServer"
    # spot-check a few field names/order on 170
    names = msgdefs.get(170).field_names()
    assert names[0] == "server_id"
    assert names[-1] == "ticket_id"
    assert "room_id" in names and "server_subtype" in names


def test_170_matches_legacy_byte_for_byte():
    values = _srv_to_170_values(VILLAGE_SRV, TICKET)
    new = codec.encode_body(170, values)
    legacy = _legacy_170(VILLAGE_SRV, TICKET)
    assert new == legacy, (
        f"codec/legacy mismatch\n  new   ({len(new)}B): {new.hex()}\n"
        f"  legacy({len(legacy)}B): {legacy.hex()}"
    )


def test_170_decode_roundtrip():
    values = _srv_to_170_values(VILLAGE_SRV, TICKET)
    body = codec.encode_body(170, values)
    back = codec.decode_body(170, body)
    assert "_decode_err" not in back, back.get("_decode_err")
    assert back["server_id"] == 1
    assert back["server_type"] == 4
    assert back["server_subtype"] == 2
    assert back["room_id"] == 1000
    assert back["name"] == "world1"
    assert back["map"] == "world1"
    assert back["cur_players"] == 1 and back["max_players"] == 20
    assert back["ticket_id"] == TICKET


def _run():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {e}")
    print()
    if failures:
        print(f"{failures} test(s) FAILED")
        return 1
    print("All golden tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
