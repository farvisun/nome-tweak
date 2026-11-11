#!/usr/bin/python3
"""Compile standard singular gettext PO catalogs without a build dependency."""
import ast
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parent.parent


def compile_po(source):
    messages = {}
    msgid = msgstr = ""
    mode = None
    def commit():
        if msgstr:
            messages[msgid] = msgstr
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            commit(); msgid = ast.literal_eval(line[6:]); msgstr = ""; mode = "id"
        elif line.startswith("msgstr "):
            msgstr = ast.literal_eval(line[7:]); mode = "str"
        elif line.startswith('"'):
            if mode == "id": msgid += ast.literal_eval(line)
            elif mode == "str": msgstr += ast.literal_eval(line)
        else:
            raise ValueError(f"Unsupported PO syntax in {source}: {line}")
    commit()
    items = sorted((k.encode("utf-8"), v.encode("utf-8")) for k, v in messages.items())
    n = len(items)
    originals = b""; translations = b""; otab = []; ttab = []
    offset = 28 + n * 16
    for key, val in items:
        otab.append((len(key), offset + len(originals))); originals += key + b"\0"
    toffset = offset + len(originals)
    for key, val in items:
        ttab.append((len(val), toffset + len(translations))); translations += val + b"\0"
    header = struct.pack("<7I", 0x950412de, 0, n, 28, 28 + n * 8, 0, 0)
    tables = b"".join(struct.pack("<2I", *row) for row in otab + ttab)
    output = ROOT / "desktop_studio/locale" / source.stem / "LC_MESSAGES/desktop-studio.mo"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(header + tables + originals + translations)
    print(f"{source.stem}: {n - 1} translated strings")


if __name__ == "__main__":
    for source in (ROOT / "po").glob("*.po"):
        compile_po(source)
