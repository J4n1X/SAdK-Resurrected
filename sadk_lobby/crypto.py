"""
Login crypto for the SAdK lobby handshake (ported verbatim from the working
monolith — this flow is delicate and validated against the real client):

  * StartAuthenticateSession (201) carries the client's secp521r1 public key.
    We do ECDH, SHA-512 the shared point, XOR a random 32-byte secret with it,
    and reply AckAuthenticateSession (202) with our key + the XORed secret.
  * Credentials (203/204/206) arrive Twofish-CTR encrypted under that secret.
  * We reply SessionKey (207) with a Twofish-encrypted session key.
"""
import hashlib
import os
import struct

try:
    from cryptography.hazmat.primitives.asymmetric.ec import (
        SECP521R1, EllipticCurvePublicNumbers, generate_private_key, ECDH)
    from cryptography.hazmat.backends import default_backend
    ECDH_AVAILABLE = True
except ImportError:  # pragma: no cover
    ECDH_AVAILABLE = False

try:
    import twofish as _twofish_mod
    TWOFISH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TWOFISH_AVAILABLE = False


# ── DER helpers ───────────────────────────────────────────────────────────────
def _der_len(n):
    if n < 0x80:
        return bytes([n])
    if n < 0x100:
        return bytes([0x81, n])
    return bytes([0x82, n >> 8, n & 0xFF])


def _int_to_der(v):
    if v == 0:
        return b"\x02\x01\x00"
    nb = (v.bit_length() + 7) // 8
    b = v.to_bytes(nb, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return b"\x02" + _der_len(len(b)) + b


def _parse_ec_key(der):
    pos = 1
    if der[pos] & 0x80:
        pos += 1 + (der[pos] & 0x7F)
    else:
        pos += 1
    pos += 1 + 1 + der[pos + 1]   # BITSTRING
    pos += 1 + 1 + der[pos + 1]   # INTEGER 0x41
    assert der[pos] == 0x02; pos += 1
    xl = der[pos]; pos += 1
    x = int.from_bytes(der[pos:pos + xl], "big"); pos += xl
    assert der[pos] == 0x02; pos += 1
    yl = der[pos]; pos += 1
    y = int.from_bytes(der[pos:pos + yl], "big")
    return x, y


def _encode_keystream(x, y):
    inner = b"\x03\x02\x07\x00" + b"\x02\x01\x41" + _int_to_der(x) + _int_to_der(y)
    return b"\x30" + _der_len(len(inner)) + inner


def _encode_reply_cipher(ks, secret):
    oid = bytes([0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x03])
    o_ks = b"\x04" + _der_len(len(ks)) + ks
    o_sec = b"\x04" + _der_len(len(secret)) + secret
    inner = oid + o_ks + o_sec
    return b"\x30" + _der_len(len(inner)) + inner


def handle_login_key(key_bytes):
    """Process StartAuthenticateSession(201) key → (reply_cipher_for_202, shared_secret)."""
    if not ECDH_AVAILABLE:
        raise ImportError("pip install cryptography")
    x, y = _parse_ec_key(key_bytes)
    client_pub = EllipticCurvePublicNumbers(x=x, y=y, curve=SECP521R1()).public_key(default_backend())
    server_priv = generate_private_key(SECP521R1(), default_backend())
    server_pub = server_priv.public_key()
    agreement = server_priv.exchange(ECDH(), client_pub)
    if len(agreement) == 65:
        agreement = b"\x00" + agreement
    h = hashlib.sha512(agreement).digest()
    shared = os.urandom(32)
    xored = bytes(shared[i] ^ h[i] for i in range(32))
    pn = server_pub.public_numbers()
    ks = _encode_keystream(pn.x, pn.y)
    return _encode_reply_cipher(ks, xored), shared


# ── Twofish CTR ───────────────────────────────────────────────────────────────
def _twofish_ctr(key, iv, data):
    if not TWOFISH_AVAILABLE:
        raise ImportError("pip install twofish")
    tf = _twofish_mod.Twofish(key)
    counter = bytearray(iv)
    out = bytearray()
    pos = 0
    while pos < len(data):
        ks = bytearray(tf.encrypt(bytes(counter)))
        chunk = min(16, len(data) - pos)
        for i in range(chunk):
            out.append(ks[i] ^ data[pos + i])
        pos += chunk
        j = 0
        while j < len(counter):
            counter[j] = (counter[j] + 1) & 0xFF
            if counter[j]:
                break
            j += 1
    return bytes(out)


def decrypt_cipher(cipher, shared):
    return _twofish_ctr(shared, cipher[:16], cipher[16:])


def encrypt_session_key(sk, shared):
    iv = os.urandom(16)
    return iv + _twofish_ctr(shared, iv, sk)


# ── Token (213/214) plaintext + cipher (reversed s31 from tincat3 Authenticator) ───────────────
def build_token_plaintext(perm_id, name, nonce, cdkey_hash=b"", server_pw=b"", extra=0):
    """Authenticator token plaintext — reversed from tincat3 GenerateToken/DecryptToken
    (@0x1002c090 / 0x1002c430): `perm_id u32 | u8 len+name | u8 len+cdkeyHash | u32 |
    u8 len+serverPw | u8 len+nonce`. The 212 server nonce is carried INSIDE the encrypted
    token (the cryptographic challenge), NOT echoed in cleartext."""
    def _lp(b):
        b = b.encode("iso-8859-15") if isinstance(b, str) else bytes(b)
        return bytes([len(b) & 0xFF]) + b
    nb = name.encode("iso-8859-15") if isinstance(name, str) else bytes(name)
    return (struct.pack("<I", perm_id & 0xFFFFFFFF) + _lp(nb) + _lp(cdkey_hash)
            + struct.pack("<I", extra & 0xFFFFFFFF) + _lp(server_pw) + _lp(nonce))


def build_token_cipher(key, plaintext):
    """Token `cipher` MEMBLOCK = IV(16 random) || Twofish-CTR(key, IV, plaintext) — identical framing
    to encrypt_session_key (verified vs tincat3 GenerateToken). `key` = the 207 session key (or shared)."""
    return encrypt_session_key(plaintext, key)


# ── Login credential blob ─────────────────────────────────────────────────────
def decode_login_blob(blob, has_cdkey=False):
    r = {}
    pos = 0
    try:
        nl = blob[pos]; pos += 1
        r["username"] = blob[pos:pos + nl].decode("ascii", "replace"); pos += nl
        pl = blob[pos]; pos += 1
        pw = blob[pos:pos + pl]; pos += pl
        r["password_raw"] = pw.hex()
        r["password_sha512"] = hashlib.sha512(pw).hexdigest()
        if has_cdkey and pos + 3 <= len(blob):
            ksl = blob[pos]; pos += 1
            kp = blob[pos]; pos += 1
            kl = blob[pos]; pos += 1
            if ksl == 1 and kp == 1 and kl == 16 and pos + kl <= len(blob):
                r["cd_key"] = blob[pos:pos + kl].decode("ascii", "replace")
    except Exception as e:  # noqa: BLE001
        r["_err"] = str(e)
    return r
