"""
Generic message codec driven by the msgdefs.ini registry.

encode_body(type, values)  -> bytes      (body only; no Magic/Type prefix)
decode_body(type, data)    -> dict        {field_name: value}

The body excludes the leading ``type`` discriminator (that lives in the
app-payload prefix). Use tincat.app_payload() to add the prefix when sending.
"""
import struct

from . import msgdefs
from .msgdefs import KIND_SCALAR, KIND_BOOL, KIND_STRING, KIND_BLOB
from .tincat import BinaryReader, BinaryWriter


def _resolve(type_or_def):
    if isinstance(type_or_def, msgdefs.MessageDef):
        return type_or_def
    md = msgdefs.get(type_or_def)
    if md is None:
        raise KeyError(f"No msgdef for type {type_or_def}")
    return md


def encode_body(type_or_def, values=None) -> bytes:
    md = _resolve(type_or_def)
    values = values or {}
    w = BinaryWriter()
    for f in md.body_fields:
        v = values.get(f.name)
        if f.kind == KIND_SCALAR:
            w.raw(struct.pack(f.fmt, int(v) if v is not None else 0))
        elif f.kind == KIND_BOOL:
            w.boolean(bool(v))
        elif f.kind == KIND_STRING:
            w.string(v)            # None -> 4-byte 0; "" -> len 1 + NUL
        elif f.kind == KIND_BLOB:
            w.blob(v)
    return w.getvalue()


def decode_body(type_or_def, data, pos=0) -> dict:
    md = _resolve(type_or_def)
    r = BinaryReader(data, pos)
    out = {}
    for f in md.body_fields:
        try:
            if f.kind == KIND_SCALAR:
                out[f.name] = struct.unpack_from(f.fmt, r._d, r._p)[0]
                r._p += struct.calcsize(f.fmt)
            elif f.kind == KIND_BOOL:
                out[f.name] = r.boolean()
            elif f.kind == KIND_STRING:
                out[f.name] = r.string()
            elif f.kind == KIND_BLOB:
                out[f.name] = r.blob()
        except (struct.error, IndexError) as e:
            out["_decode_err"] = f"{f.name}: {e}"
            break
    return out
