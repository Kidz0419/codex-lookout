"""Reject private build-machine paths in release bytes and frozen code metadata."""
import marshal
import sys
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

app = Path(sys.argv[1])
root = Path(__file__).resolve().parents[1]
prefixes = tuple(str(path) + "/" for path in (root, Path.home()))
encoded = tuple(prefix.encode() for prefix in prefixes)
raw_matches = sum(any(prefix in path.read_bytes() for prefix in encoded)
                  for path in app.rglob("*") if path.is_file() and not path.is_symlink())
archive = CArchiveReader(app / "Contents/Resources/backend/pulse-backend")
modules = archive.open_embedded_archive("PYZ.pyz")
checked = 0
private_filenames = 0


def visit(value):
    global checked, private_filenames
    if isinstance(value, types.CodeType):
        checked += 1
        private_filenames += any(prefix in value.co_filename for prefix in prefixes)
        for item in value.co_consts:
            visit(item)


for name in modules.toc:
    visit(modules.extract(name))
for name, metadata in archive.toc.items():
    if metadata[-1] in ("s", "m", "M"):
        visit(marshal.loads(archive.extract(name)))
if raw_matches or private_filenames:
    raise SystemExit(f"Private build paths found: {raw_matches} files, {private_filenames} code filenames")
print(f"PASS: no private build paths in release files or {checked} frozen code objects")
