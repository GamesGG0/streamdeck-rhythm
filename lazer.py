"""Finds charts in osu!lazer's library by reading its database (client.realm), read-only."""

import os
import struct

LAZER_DIR = os.path.join(os.environ.get("APPDATA", ""), "osu")
CLUSTER_SIZE = 256


def data_dir():
    # storage.ini points elsewhere if the user moved lazer's data folder
    ini = os.path.join(LAZER_DIR, "storage.ini")
    if os.path.exists(ini):
        with open(ini, encoding="utf-8") as f:
            for line in f:
                key, sep, value = line.partition("=")
                if sep and key.strip() == "FullPath" and value.strip():
                    return value.strip()
    return LAZER_DIR


def stored_file(root, hash_):
    return os.path.join(root, "files", hash_[0], hash_[:2], hash_)


class Realm:
    """Just enough of the Realm file format to read string, link and list columns."""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        if self.data[16:20] != b"T-DB":
            raise ValueError("not a Realm file")
        top_refs = struct.unpack_from("<QQ", self.data, 0)
        top = self.ints(top_refs[self.data[23] & 1])
        self.tables = dict(zip(self.strings(top[0]), self.ints(top[1])))

    def header(self, ref):
        h = self.data[ref:ref + 8]
        if h[:4] != b"AAAA":
            raise ValueError(f"bad node at {ref}")
        flags = h[4]
        return flags & 0x80, flags & 0x40, flags & 0x20, (1 << (flags & 7)) >> 1, int.from_bytes(h[5:8], "big")

    def ints(self, ref):
        _, _, _, width, size = self.header(ref)
        start = ref + 8
        if width == 0:
            return [0] * size
        if width < 8:
            mask = (1 << width) - 1
            return [(self.data[start + i * width // 8] >> (i * width % 8)) & mask for i in range(size)]
        step = width // 8
        return [int.from_bytes(self.data[start + i * step:start + (i + 1) * step], "little", signed=True) for i in range(size)]

    def strings(self, ref):
        _, has_refs, big, width, size = self.header(ref)
        if not has_refs:
            out = []
            for i in range(size):
                chunk = self.data[ref + 8 + i * width:ref + 8 + (i + 1) * width]
                out.append(None if not width or chunk[-1] == width else chunk[:width - 1 - chunk[-1]].decode("utf-8", "replace"))
            return out
        if big:
            return [self.blob(r) if r else None for r in self.ints(ref)]
        parts = self.ints(ref)
        ends = self.ints(parts[0])
        blob_start = parts[1] + 8
        nulls = self.ints(parts[2]) if len(parts) > 2 and parts[2] else [0] * len(ends)
        out, begin = [], 0
        for end, null in zip(ends, nulls):
            out.append(None if null else self.data[blob_start + begin:blob_start + end - 1].decode("utf-8", "replace"))
            begin = end
        return out

    def blob(self, ref):
        size = self.header(ref)[4]
        return self.data[ref + 8:ref + 8 + size - 1].decode("utf-8", "replace")

    def leaves(self, ref, offset=0):
        inner = self.header(ref)[0]
        slots = self.ints(ref)
        if inner:
            children = slots[3:]
            offsets = self.ints(slots[0]) if slots[0] else [i * CLUSTER_SIZE for i in range(len(children))]
            for child_offset, child in zip(offsets, children):
                yield from self.leaves(child, offset + child_offset)
        else:
            keys = range(slots[0] >> 1) if slots[0] & 1 else self.ints(slots[0])
            yield offset, keys, slots[1:]

    def column(self, table, name, kind):
        """Maps each object key to its value in one column."""
        table_top = self.ints(self.tables[table])
        spec = self.ints(table_top[0])
        index = self.strings(spec[1]).index(name)
        leaf = self.ints(spec[5])[index] & 0xFFFF
        read = self.strings if kind == "str" else self.ints
        values = {}
        for offset, keys, columns in self.leaves(table_top[2]):
            values.update(zip((offset + k for k in keys), read(columns[leaf])))
        return values

    def list_items(self, ref):
        if not ref:
            return []
        slots = self.ints(ref)
        if self.header(ref)[0]:
            return [item for child in slots[1:-1] for item in self.list_items(child)]
        return slots


def beatmap_sets():
    """Yields one dict per beatmap set, mapping each lowercase filename to its stored path."""
    root = data_dir()
    realm = Realm(os.path.join(root, "client.realm"))
    hashes = realm.column("class_File", "Hash", "str")
    names = realm.column("class_RealmNamedFileUsage", "Filename", "str")
    links = realm.column("class_RealmNamedFileUsage", "File", "int")
    deleted = realm.column("class_BeatmapSet", "DeletePending", "int")
    for set_key, files_ref in realm.column("class_BeatmapSet", "Files", "int").items():
        if deleted.get(set_key):
            continue
        files = {}
        for usage in realm.list_items(files_ref):
            # Single links are stored as key + 1 so that 0 can mean "none"
            if links.get(usage):
                files[names[usage].lower()] = stored_file(root, hashes[links[usage] - 1])
        yield files
