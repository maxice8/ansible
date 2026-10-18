"""Capture restorable databases inside the single data root before a scheduled backup.

Systemd briefly pauses Pomerium/Syncthing around their directory copies. SQLite's
online backup API captures the other live databases without stopping applications.
This helper runs as the backup identity with read-only access to application state.
"""

import shutil
import sqlite3
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
        with (
            sqlite3.connect("file:" + str(source) + "?mode=ro", uri=True) as reader,
            sqlite3.connect(temporary) as writer,
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
