import errno
import os
from pathlib import Path

from app.services.web_snapshots import SnapshotStore
from scripts.run_persistent_volume_disk_full import (
    DRILL_VERSION,
    PROTECTED_BODY,
    exercise_volume,
    loop_ext4_available,
    run_loop_ext4_drill,
)


def test_exercise_volume_protects_lineage_on_enospace(tmp_path: Path, monkeypatch) -> None:
    original = Path.write_bytes

    def write_bytes(self: Path, data: bytes) -> int:
        if len(data) > 1024 * 1024:
            raise OSError(errno.ENOSPC, "No space left on device")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    result = exercise_volume(tmp_path)

    store = SnapshotStore(tmp_path / "snapshots")
    assert result["status"] == "passed"
    assert result["medium"] == "persistent_volume"
    assert result["write_failed"] is True
    assert result["protected_snapshot_survived"] is True
    assert result["partial_tmp_cleaned"] is True
    assert result["db_consistent"] is True
    surviving = [store.get(item_id) for item_id in store.list_ids()]
    assert any(item is not None and item.body == PROTECTED_BODY for item in surviving)
    assert not any(path.name.startswith(".tmp-") for path in (tmp_path / "snapshots").iterdir())


def test_loop_ext4_drill_skips_without_claiming_tmpfs_pass() -> None:
    if loop_ext4_available():
        return
    result = run_loop_ext4_drill()
    assert result["drill_version"] == DRILL_VERSION
    assert result["status"] == "skipped"
    assert result["tmpfs_substituted"] is False
    assert result["medium"] == "ext4_loop"


def test_loop_ext4_is_not_available_on_windows() -> None:
    if os.name == "nt":
        assert loop_ext4_available() is False
