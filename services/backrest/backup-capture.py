"""Capture restorable databases inside the single data root before a scheduled backup.

Systemd pauses database writers while this helper copies their state. SQLite
recovers private database copies without write access to application state.
This helper runs as the backup identity with read-only access to application state.
"""

import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path("/var/lib/data")
DEST = ROOT / "backup-capture"


def main():
    DEST.mkdir(mode=0o700, exist_ok=True)
    for name, relative in {
        "forgejo": "forgejo/data/gitea.db",
        "pocket-id": "pocket-id/pocket-id.db",
        "pingvin-share": "pingvin-share/data/pingvin-share.db",
    }.items():
        source = ROOT / relative
        assert source.is_file() and not source.is_symlink(), source
        assert source.resolve().is_relative_to(ROOT / relative.split("/")[0])
        temporary = DEST / (name + ".sqlite.new")
        temporary.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(dir=DEST) as directory:
            database = Path(directory) / source.name
            shutil.copyfile(source, database)
            # Keep committed WAL data. SQLite creates a new shared-memory index.
            wal = source.with_name(source.name + "-wal")
            if wal.exists():
                assert wal.is_file() and not wal.is_symlink(), wal
                shutil.copyfile(wal, database.with_name(database.name + "-wal"))
            with (
                closing(sqlite3.connect(database)) as reader,
                closing(sqlite3.connect(temporary)) as writer,
            ):
                reader.backup(writer)
                assert writer.execute("pragma quick_check").fetchone() == ("ok",)
        temporary.chmod(0o600)
        temporary.replace(DEST / (name + ".sqlite"))
    for name, relative in {
        "pomerium": "pomerium/databroker",
        "syncthing": "syncthing/config",
    }.items():
        source = ROOT / relative
        assert source.is_dir() and not source.is_symlink()
        assert all(not p.is_symlink() for p in source.rglob("*"))
        temporary = DEST / (name + ".new")
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(source, temporary)
        old = DEST / (name + ".old")
        if old.exists():
            shutil.rmtree(old)
        target = DEST / name
        if target.exists():
            target.rename(old)
        temporary.rename(target)
        if old.exists():
            shutil.rmtree(old)


if __name__ == "__main__":
    main()
