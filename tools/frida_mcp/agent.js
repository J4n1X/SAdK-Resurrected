// Frida agent loaded into SADK.exe by tools/frida_mcp/server.py.
// Exposes a small RPC surface: call a client function, read memory, hook functions and collect what
// they were called with. Addresses are the static Ghidra addresses (SADK.exe has no ASLR: base
// 0x400000, tincat3.dll 0x10000000 — CLAUDE.md), so the mapping's addresses can be used directly.

const events = [];
const hooks = {};
const MAX_EVENTS = 5000;

function push(ev) {
  ev.t = Date.now();
  events.push(ev);
  if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS);
}

function toPtr(v) {
  if (typeof v === 'string') return ptr(v);
  return ptr(v >>> 0);
}

// Argument spec: a number/hex string is passed as a 32-bit value; {"str": "text"} passes a pointer to a
// fresh NUL-terminated ANSI string; {"bytes": "hex"} passes a pointer to a fresh buffer.
const keep = [];   // keep allocations alive for the duration of a call
function arg(a) {
  if (a !== null && typeof a === 'object') {
    if ('str' in a) { const m = Memory.allocAnsiString(a.str); keep.push(m); return m; }
    if ('bytes' in a) {
      const hex = a.bytes.replace(/\s+/g, '');
      const m = Memory.alloc(Math.max(1, hex.length / 2));
      for (let i = 0; i < hex.length; i += 2) m.add(i / 2).writeU8(parseInt(hex.substr(i, 2), 16));
      keep.push(m);
      return m;
    }
  }
  return toPtr(a);
}

rpc.exports = {
  // Call a function. abi: 'cdecl' | 'stdcall' | 'thiscall' | 'fastcall'. For thiscall, the first arg is `this`.
  call(address, args, abi, retType) {
    const n = args.length;
    const f = new NativeFunction(toPtr(address), retType || 'uint32', Array(n).fill('pointer'),
                                 { abi: abi || 'cdecl', exceptions: 'propagate' });
    try {
      const r = f(...args.map(arg));
      return { ok: true, ret: (r && r.toString) ? r.toString() : String(r) };
    } catch (e) {
      return { ok: false, error: String(e), stack: e.stack || '' };
    } finally {
      keep.length = 0;
    }
  },

  read(address, length) {
    return toPtr(address).readByteArray(length);
  },

  readU32(address) { return toPtr(address).readU32(); },

  readCstring(address, max) { return toPtr(address).readCString(max || 256); },

  // Hook: record args (as hex u32), `this` (ECX) and the return value of every call.
  hook(address, nargs, name) {
    const key = String(address);
    if (hooks[key]) return 'already hooked';
    hooks[key] = Interceptor.attach(toPtr(address), {
      onEnter(a) {
        this.rec = { kind: 'call', name: name || key, addr: key, ecx: this.context.ecx.toString(),
                     args: Array.from({ length: nargs || 0 }, (_, i) => a[i].toString()),
                     tid: this.threadId };
      },
      onLeave(r) {
        this.rec.ret = r.toString();
        push(this.rec);
      }
    });
    return 'hooked ' + (name || key);
  },

  unhook(address) {
    const key = String(address);
    if (!hooks[key]) return 'not hooked';
    hooks[key].detach();
    delete hooks[key];
    return 'unhooked ' + key;
  },

  events(clear) {
    const out = events.slice();
    if (clear) events.length = 0;
    return out;
  },

  // Free-form JavaScript for anything the fixed calls do not cover. Returns the value of the last
  // expression (JSON-serialisable values only).
  evaluate(code) {
    try {
      return { ok: true, value: (0, eval)(code) };
    } catch (e) {
      return { ok: false, error: String(e), stack: e.stack || '' };
    }
  },

  modules() {
    return Process.enumerateModules().map(m => ({ name: m.name, base: m.base.toString(), size: m.size }));
  }
};

// Report every crash with its context instead of letting the game die silently.
Process.setExceptionHandler(details => {
  push({ kind: 'exception', type: details.type, address: details.address.toString(),
         memory: details.memory ? { op: details.memory.operation, address: details.memory.address.toString() } : null,
         context: { eip: details.context.eip.toString(), eax: details.context.eax.toString(),
                    ecx: details.context.ecx.toString(), edx: details.context.edx.toString(),
                    ebx: details.context.ebx.toString(), esp: details.context.esp.toString(),
                    ebp: details.context.ebp.toString(), esi: details.context.esi.toString(),
                    edi: details.context.edi.toString() },
         backtrace: Thread.backtrace(details.context, Backtracer.FUZZY).map(String).slice(0, 24) });
  return false;   // not handled: the game's own handling / crash continues
});
