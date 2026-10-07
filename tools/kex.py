"""
Parser for the game's .KEX files ("KScene" binary scenes: meshes, skeletons, animations), field for field
after the client's own loader (read through Ghidra, mapping cache of sadk_noav.exe):

  KSceneInternal::KFile::Load        S 0072b820  str name; vec3 axisX, axisY, axisZ, origin; f32 unitScale;
                                                 u8 meshCount + meshes; u8 skeletonCount + skeletons;
                                                 u8 animationCount + animations
  KScene_ReadLenPrefixedString       S 0072df40  u32 length + bytes (no NUL)
  KSceneInternal::KMesh::Load        S 0072c880  str name, str name2; u32 numIndices, numVertices, numStreams,
                                                 numBoneNames, numMaterials; u32 indices[numIndices];
                                                 per stream {u8 type, u32 byteSize, bytes};
                                                 str boneNames[numBoneNames]; materials[numMaterials]
  KSceneInternal::KMaterialDesc::Load S 007303a0 str name, str name2; u32 a, u32 b; u32 count;
                                                 count x {str, str} (usage, texture file)
  KSceneInternal::KSkeleton::Load    S 0072d290  str name, str name2; u32 boneCount; per bone {str name,
                                                 KBoneKey, f32 matrix[16], i32 parentIndex}
  KBoneKey_Read                      S 0072f1d0  u32 flags; bit0 vec3 position; bit1 quat rotation (x,y,z,w);
                                                 bit2 mat3 scale
  KSceneInternal::KAnimation::Load   S 0072dcf0  str name, str name2; f32 length; i32 trackCount; i32 keyCount;
                                                 per track {str boneName; u8 hasPos -> keyCount x vec3;
                                                 u8 hasRot -> keyCount x quat; u8 hasScale -> keyCount x mat3}

Stated reason (HARNESS.md §3): offline conversion of game files; no MCP reads or splits them in bulk.

Usage:  python3 tools/kex.py info <file.KEX>
        python3 tools/kex.py check <dir>            parse every .KEX, report any that do not end exactly
        python3 tools/kex.py split <dir> <out dir>  one folder per KEX: scene.json + one file per part
"""
import json
import os
import struct
import sys


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise ValueError(f"read of {n} bytes past the end at {self.pos}")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def u8(self):
        return self.take(1)[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def f32s(self, n):
        return list(struct.unpack(f"<{n}f", self.take(4 * n)))

    def string(self):
        n = self.i32()
        return self.take(n).decode("latin-1") if n > 0 else ""


def read_bone_key(r):
    flags = r.u32()
    key = {"flags": flags}
    if flags & 1:
        key["position"] = r.f32s(3)
    if flags & 2:
        key["rotation"] = r.f32s(4)
    if flags & 4:
        key["scale"] = r.f32s(9)
    return key


def read_material(r):
    m = {"name": r.string(), "name2": r.string(), "a": r.u32(), "b": r.u32()}
    m["textures"] = [[r.string(), r.string()] for _ in range(r.u32())]
    return m


def read_mesh(r):
    m = {"name": r.string(), "name2": r.string()}
    num_indices, num_vertices, num_streams, num_bones, num_materials = (r.u32() for _ in range(5))
    m["numVertices"] = num_vertices
    m["indices"] = r.take(4 * num_indices)
    streams = []
    for _ in range(num_streams):
        stype = r.u8()
        size = r.u32()
        streams.append({"type": stype, "data": r.take(size)})
    m["streams"] = streams
    m["boneNames"] = [r.string() for _ in range(num_bones)]
    m["materials"] = [read_material(r) for _ in range(num_materials)]
    return m


def read_skeleton(r):
    s = {"name": r.string(), "name2": r.string(), "bones": []}
    for _ in range(r.u32()):
        s["bones"].append({"name": r.string(), "key": read_bone_key(r), "matrix": r.f32s(16), "parent": r.i32()})
    return s


def read_animation(r):
    a = {"name": r.string(), "name2": r.string(), "length": r.f32s(1)[0]}
    tracks, keys = r.i32(), r.i32()
    a["keyCount"] = keys
    a["tracks"] = []
    for _ in range(max(tracks, 0)):
        t = {"bone": r.string()}
        if r.u8() == 1:
            t["positions"] = r.take(12 * keys)
        if r.u8() == 1:
            t["rotations"] = r.take(16 * keys)
        if r.u8() == 1:
            t["scales"] = r.take(36 * keys)
        a["tracks"].append(t)
    return a


def parse(data):
    r = Reader(data)
    scene = {"name": r.string(), "axisX": r.f32s(3), "axisY": r.f32s(3), "axisZ": r.f32s(3),
             "origin": r.f32s(3), "unitScale": r.f32s(1)[0]}
    scene["meshes"] = [read_mesh(r) for _ in range(r.u8())]
    scene["skeletons"] = [read_skeleton(r) for _ in range(r.u8())]
    scene["animations"] = [read_animation(r) for _ in range(r.u8())]
    scene["_trailing"] = len(data) - r.pos
    return scene


def summary(scene):
    """JSON-friendly description (bulk arrays replaced by sizes)."""
    out = {k: scene[k] for k in ("name", "axisX", "axisY", "axisZ", "origin", "unitScale")}
    out["meshes"] = [{"name": m["name"], "name2": m["name2"], "numVertices": m["numVertices"],
                      "numIndices": len(m["indices"]) // 4,
                      "streams": [{"type": s["type"], "bytes": len(s["data"]),
                                   "bytesPerVertex": len(s["data"]) / m["numVertices"] if m["numVertices"] else None}
                                  for s in m["streams"]],
                      "boneNames": m["boneNames"], "materials": m["materials"]} for m in scene["meshes"]]
    out["skeletons"] = scene["skeletons"]
    out["animations"] = [{"name": a["name"], "name2": a["name2"], "length": a["length"], "keyCount": a["keyCount"],
                          "tracks": [{"bone": t["bone"], "position": "positions" in t, "rotation": "rotations" in t,
                                      "scale": "scales" in t} for t in a["tracks"]]} for a in scene["animations"]]
    return out


def kex_files(root):
    for d, _, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith(".kex"):
                yield os.path.join(d, f)


def main(argv):
    if len(argv) == 2 and argv[0] == "info":
        print(json.dumps(summary(parse(open(argv[1], "rb").read())), indent=1))
        return 0
    if len(argv) == 2 and argv[0] == "check":
        ok = bad = 0
        for p in kex_files(argv[1]):
            try:
                s = parse(open(p, "rb").read())
                if s["_trailing"]:
                    raise ValueError(f"{s['_trailing']} bytes left over")
                ok += 1
            except ValueError as e:
                bad += 1
                print(f"BAD {os.path.relpath(p, argv[1])}: {e}")
        print(f"{ok} parsed exactly, {bad} failed")
        return 0 if not bad else 1
    if len(argv) == 3 and argv[0] == "split":
        n = 0
        for p in kex_files(argv[1]):
            scene = parse(open(p, "rb").read())
            out = os.path.join(argv[2], os.path.relpath(p, argv[1]))
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "scene.json"), "w") as fh:
                json.dump(summary(scene), fh, indent=1)
            for i, m in enumerate(scene["meshes"]):
                with open(os.path.join(out, f"mesh{i}.indices.u32"), "wb") as fh:
                    fh.write(m["indices"])
                for j, s in enumerate(m["streams"]):
                    with open(os.path.join(out, f"mesh{i}.stream{j}.type{s['type']}.bin"), "wb") as fh:
                        fh.write(s["data"])
            for i, a in enumerate(scene["animations"]):
                for j, t in enumerate(a["tracks"]):
                    for part in ("positions", "rotations", "scales"):
                        if part in t:
                            with open(os.path.join(out, f"anim{i}.track{j}.{part}.f32"), "wb") as fh:
                                fh.write(t[part])
            n += 1
        print(f"split {n} KEX files into {argv[2]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
