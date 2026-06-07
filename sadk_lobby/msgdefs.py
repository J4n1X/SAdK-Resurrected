"""
Loader for the game's own message-definition file (msgdefs.ini).

msgdefs.ini ships in the game's bin/ directory and is the AUTHORITATIVE schema
that tincat3.dll uses to (de)serialize every NETMSG. We bundle a copy under
sadk_lobby/data/ and parse it here into an ordered registry so the codec can
encode/decode any of the ~150 message types generically.

File format (one section per type):

    # FriendlyName
    [NETMSG_TYPE_<n>]
    field_name="TYPE [arg]"
    ...

The leading ``type="UNSHORT"`` field of every message is the type discriminator;
on the wire it lives in the app-payload prefix (Magic+Type1+Type2), NOT the body,
so the codec skips any field literally named ``type``.
"""
import re

from . import config

# ── Field type tokens → wire kind ─────────────────────────────────────────────
SCALAR_FORMATS = {
    "UNBYTE": "B", "SIBYTE": "b",
    "UNSHORT": "H", "SISHORT": "h",
    "UNLONG": "I", "SILONG": "i",
}
KIND_SCALAR, KIND_BOOL, KIND_STRING, KIND_BLOB = "scalar", "bool", "string", "blob"


class Field:
    __slots__ = ("name", "token", "kind", "fmt", "arg")

    def __init__(self, name, token, arg=None):
        self.name = name
        self.token = token
        self.arg = arg
        if token in SCALAR_FORMATS:
            self.kind = KIND_SCALAR
            self.fmt = "<" + SCALAR_FORMATS[token]
        elif token == "LBOOL":
            self.kind = KIND_BOOL
            self.fmt = None
        elif token == "STRING":
            self.kind = KIND_STRING
            self.fmt = None
        elif token == "MEMBLOCK":
            self.kind = KIND_BLOB
            self.fmt = None
        else:
            raise ValueError(f"Unknown field token {token!r} for field {name!r}")

    def __repr__(self):
        return f"Field({self.name!r}, {self.token}{'' if self.arg is None else ' ' + str(self.arg)})"


class MessageDef:
    __slots__ = ("type_num", "name", "fields", "body_fields")

    def __init__(self, type_num, name, fields):
        self.type_num = type_num
        self.name = name
        self.fields = fields                      # all fields, in order
        # body fields = everything except the leading 'type' discriminator
        self.body_fields = [f for f in fields if f.name != "type"]

    def field_names(self):
        return [f.name for f in self.body_fields]

    def __repr__(self):
        return f"MessageDef({self.type_num}, {self.name!r}, {len(self.body_fields)} body fields)"


_SECTION_RE = re.compile(r"^\[NETMSG_TYPE_(\d+)\]\s*$")
_FIELD_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"([^"]*)"\s*$')
_COMMENT_RE = re.compile(r"^\s*#\s*(.*?)\s*$")


def _parse_field_value(name, value):
    parts = value.split()
    token = parts[0].upper()
    arg = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
    return Field(name, token, arg)


def load(path=None):
    """Parse msgdefs.ini → (registry: {type_num: MessageDef}, name_to_type: {name: type_num})."""
    path = path or config.MSGDEFS_PATH
    registry = {}
    name_to_type = {}
    pending_name = None
    cur = None        # (type_num, name, [fields])

    def _flush():
        if cur is not None:
            tn, nm, flds = cur
            md = MessageDef(tn, nm, flds)
            registry[tn] = md
            name_to_type[nm] = tn

    with open(path, "r", encoding="iso-8859-15") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            sec = _SECTION_RE.match(line)
            if sec:
                _flush()
                tn = int(sec.group(1))
                cur = (tn, pending_name or f"Type{tn}", [])
                pending_name = None
                continue
            fld = _FIELD_RE.match(line)
            if fld and cur is not None:
                cur[2].append(_parse_field_value(fld.group(1), fld.group(2)))
                continue
            cm = _COMMENT_RE.match(line)
            if cm:
                pending_name = cm.group(1)          # remember for the next section
                continue
            # blank / unrecognized line: clears a dangling comment only if no section yet
            if not line.strip():
                continue
    _flush()
    return registry, name_to_type


# Module-level registry, loaded from the bundled schema on import.
REGISTRY, NAME_TO_TYPE = load()
TYPE_TO_NAME = {tn: md.name for tn, md in REGISTRY.items()}


def get(type_num):
    return REGISTRY.get(type_num)


def name_of(type_num):
    md = REGISTRY.get(type_num)
    return md.name if md else f"Unknown({type_num})"
