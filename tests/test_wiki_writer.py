"""The wiki writer: target guard, atomic build, owned-files-only updates, permissions."""

from __future__ import annotations

import json
import os
import stat
import unicodedata
from pathlib import Path

import pytest

from bilinc.wiki import writer
from bilinc.wiki.manifest import MANIFEST_NAME, TMP_NAME, build_manifest, dumps_manifest
from bilinc.wiki.writer import (
    WikiExportError,
    WikiRefused,
    inspect_target,
    write_tree,
)

BASE_URL = "https://bilinc.space"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX permissions and symlinks")


def _case_insensitive_fs(path: Path) -> bool:
    probe = path / "CaseProbe"
    probe.write_text("")
    try:
        return (path / "caseprobe").exists()
    finally:
        probe.unlink()


@pytest.fixture()
def case_sensitive_fs(tmp_path):
    """These tests build case twins on disk, which only a case-sensitive folder can hold."""
    if _case_insensitive_fs(tmp_path):
        pytest.skip("needs a case-sensitive file system (CI runs on Linux)")


def manifest_for(complete, files):
    return build_manifest(
        version="2.7.0",
        base_url=BASE_URL,
        prefix=None,
        history=5,
        exported_at="2026-11-09T00:00:00Z",
        complete=complete,
        files=files,
        keys={},
    )


def read_manifest_json(target: Path) -> dict:
    return json.loads((target / MANIFEST_NAME).read_text(encoding="utf-8"))


def tree(root: Path) -> dict[str, tuple[bytes | None, int]]:
    """Every entry under root (symlinks not followed): content for files, mode bits."""
    out: dict[str, tuple[bytes | None, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            info = path.lstat()
            rel = path.relative_to(root).as_posix()
            if stat.S_ISREG(info.st_mode):
                out[rel] = (path.read_bytes(), stat.S_IMODE(info.st_mode))
            elif stat.S_ISLNK(info.st_mode):
                out[rel] = (os.readlink(path).encode(), -1)
            else:
                out[rel] = (None, stat.S_IMODE(info.st_mode))
    return out


FILES = {
    "AGENTS.md": "agents\n",
    "index.md": "index\n",
    "a/_index.md": "a index\n",
    "a/b.md": "page b\n",
    "c.md": "page c\n",
}


def first_run(target: Path, files=FILES) -> None:
    write_tree(target, files, previous=None, manifest_for=manifest_for)


# --- inspect_target --------------------------------------------------------------


def test_missing_dir_is_fine_when_parent_exists(tmp_path):
    assert inspect_target(tmp_path / "new", base_url=BASE_URL, prefix=None) is None


def test_missing_parent_is_refused(tmp_path):
    with pytest.raises(WikiRefused, match="does not exist"):
        inspect_target(tmp_path / "no" / "such" / "new", base_url=BASE_URL, prefix=None)


def test_empty_dir_is_fine(tmp_path):
    assert inspect_target(tmp_path, base_url=BASE_URL, prefix=None) is None


def test_obsidian_only_dir_counts_as_empty(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text("{}")
    (tmp_path / ".trash").mkdir()
    (tmp_path / ".DS_Store").write_bytes(b"\0")

    assert inspect_target(tmp_path, base_url=BASE_URL, prefix=None) is None


def test_non_empty_without_marker_is_refused(tmp_path):
    (tmp_path / "notes.md").write_text("mine")

    with pytest.raises(WikiRefused, match="not a Bilinc wiki folder"):
        inspect_target(tmp_path, base_url=BASE_URL, prefix=None)


def test_stale_tmp_without_marker_is_refused_and_named(tmp_path):
    (tmp_path / TMP_NAME).mkdir()

    with pytest.raises(WikiRefused, match=r"\.bilinc-wiki\.tmp"):
        inspect_target(tmp_path, base_url=BASE_URL, prefix=None)


def test_target_symlink_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    with pytest.raises(WikiRefused, match="symbolic link"):
        inspect_target(link, base_url=BASE_URL, prefix=None)


def test_target_that_is_a_file_is_refused(tmp_path):
    target = tmp_path / "file"
    target.write_text("x")

    with pytest.raises(WikiRefused, match="not a folder"):
        inspect_target(target, base_url=BASE_URL, prefix=None)


def test_valid_manifest_is_returned(tmp_path):
    first_run(tmp_path)

    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    assert previous is not None and previous["files"] == sorted(FILES)


@pytest.mark.parametrize(
    "base_url,prefix,named",
    [("https://other.example", None, "https://other.example"), (BASE_URL, "team:", "team:")],
)
def test_prefix_or_base_url_change_is_refused(tmp_path, base_url, prefix, named):
    first_run(tmp_path)

    with pytest.raises(WikiRefused) as caught:
        inspect_target(tmp_path, base_url=base_url, prefix=prefix)

    assert named in str(caught.value)


def test_corrupt_manifest_is_refused(tmp_path):
    (tmp_path / MANIFEST_NAME).write_text("{")

    with pytest.raises(WikiRefused):
        inspect_target(tmp_path, base_url=BASE_URL, prefix=None)


# --- write_tree ------------------------------------------------------------------


def test_first_write_creates_files_manifest_and_permissions(tmp_path):
    target = tmp_path / "wiki"

    result = write_tree(target, FILES, previous=None, manifest_for=manifest_for)

    assert result.written == len(FILES)
    for rel, text in FILES.items():
        path = target / rel
        assert path.read_text(encoding="utf-8") == text
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert stat.S_IMODE((target / "a").stat().st_mode) == 0o700
    manifest = read_manifest_json(target)
    assert manifest["complete"] is True and manifest["files"] == sorted(FILES)
    assert stat.S_IMODE((target / MANIFEST_NAME).stat().st_mode) == 0o600
    assert not (target / TMP_NAME).exists()


def test_rewrite_removes_stale_files_and_keeps_user_files(tmp_path):
    first_run(tmp_path)
    (tmp_path / "notes.md").write_text("mine")
    (tmp_path / "a" / "mine.md").write_text("also mine")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text("{}")
    user_before = {rel: v for rel, v in tree(tmp_path).items() if rel in {"notes.md", "a/mine.md", ".obsidian/app.json"}}
    new_files = {"AGENTS.md": "agents 2\n", "index.md": "index 2\n", "d/e.md": "page e\n", "d/_index.md": "d\n"}
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    result = write_tree(tmp_path, new_files, previous=previous, manifest_for=manifest_for)

    assert sorted(result.removed) == ["a/_index.md", "a/b.md", "c.md"]
    after = tree(tmp_path)
    for rel, value in user_before.items():
        assert after[rel] == value
    assert not (tmp_path / "c.md").exists()
    assert (tmp_path / "a").is_dir()  # still holds the user's file
    assert (tmp_path / "d" / "e.md").read_text() == "page e\n"
    assert read_manifest_json(tmp_path)["files"] == sorted(new_files)


def test_emptied_folders_are_removed(tmp_path):
    first_run(tmp_path)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    write_tree(tmp_path, {"index.md": "i\n", "AGENTS.md": "a\n"}, previous=previous, manifest_for=manifest_for)

    assert not (tmp_path / "a").exists()


def test_world_readable_files_are_tightened(tmp_path):
    first_run(tmp_path)
    os.chmod(tmp_path / "c.md", 0o644)
    os.chmod(tmp_path / "a", 0o755)
    os.chmod(tmp_path, 0o755)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    write_tree(tmp_path, FILES, previous=previous, manifest_for=manifest_for)

    assert stat.S_IMODE((tmp_path / "c.md").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "a").stat().st_mode) == 0o700
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


@pytest.mark.parametrize("kind", ["file", "dir", "symlink"])
def test_user_entry_at_a_needed_path_is_refused_before_moving(tmp_path, kind):
    first_run(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.write_text("outside")
    needed = tmp_path / "new.md"
    if kind == "file":
        needed.write_text("mine")
    elif kind == "dir":
        needed.mkdir()
    else:
        needed.symlink_to(outside)
    before = tree(tmp_path)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    with pytest.raises(WikiRefused, match="new.md"):
        write_tree(tmp_path, {**FILES, "new.md": "page\n"}, previous=previous, manifest_for=manifest_for)

    assert tree(tmp_path) == before
    assert outside.read_text() == "outside"


def test_owned_page_that_became_a_directory_is_refused(tmp_path):
    first_run(tmp_path)
    (tmp_path / "c.md").unlink()
    (tmp_path / "c.md").mkdir()
    before = tree(tmp_path)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    with pytest.raises(WikiRefused, match="c.md"):
        write_tree(tmp_path, FILES, previous=previous, manifest_for=manifest_for)

    assert tree(tmp_path) == before


@pytest.mark.parametrize("kind", ["symlink", "file"])
def test_needed_folder_that_is_not_a_real_folder_is_refused(tmp_path, kind):
    first_run(tmp_path)
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    elsewhere.mkdir()
    for rel in ("a/b.md", "a/_index.md"):
        (tmp_path / rel).unlink()
    (tmp_path / "a").rmdir()
    if kind == "symlink":
        (tmp_path / "a").symlink_to(elsewhere)
    else:
        (tmp_path / "a").write_text("mine")
    before = tree(tmp_path)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    with pytest.raises(WikiRefused, match="a"):
        write_tree(tmp_path, FILES, previous=previous, manifest_for=manifest_for)

    assert tree(tmp_path) == before
    assert list(elsewhere.iterdir()) == []


def test_owned_page_replaced_by_a_symlink_is_replaced_not_followed(tmp_path):
    first_run(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("outside")
    (tmp_path / "c.md").unlink()
    (tmp_path / "c.md").symlink_to(outside)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    write_tree(tmp_path, FILES, previous=previous, manifest_for=manifest_for)

    assert outside.read_text() == "outside"
    assert not (tmp_path / "c.md").is_symlink()
    assert (tmp_path / "c.md").read_text() == "page c\n"


def test_stale_delete_never_follows_a_symlinked_parent(tmp_path):
    first_run(tmp_path)
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    elsewhere.mkdir()
    (elsewhere / "b.md").write_text("not ours")
    for rel in ("a/b.md", "a/_index.md"):
        (tmp_path / rel).unlink()
    (tmp_path / "a").rmdir()
    (tmp_path / "a").symlink_to(elsewhere)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    new_files = {rel: text for rel, text in FILES.items() if not rel.startswith("a/")}

    result = write_tree(tmp_path, new_files, previous=previous, manifest_for=manifest_for)

    assert (elsewhere / "b.md").read_text() == "not ours"
    assert sorted(result.skipped) == ["a/_index.md", "a/b.md"]
    assert (tmp_path / "a").is_symlink()


def test_stale_owned_entry_that_became_a_directory_is_skipped(tmp_path):
    first_run(tmp_path)
    (tmp_path / "c.md").unlink()
    (tmp_path / "c.md").mkdir()
    (tmp_path / "c.md" / "keep").write_text("mine")
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    new_files = {rel: text for rel, text in FILES.items() if rel != "c.md"}

    result = write_tree(tmp_path, new_files, previous=previous, manifest_for=manifest_for)

    assert result.skipped == ["c.md"]
    assert (tmp_path / "c.md" / "keep").read_text() == "mine"


def test_tmp_symlink_is_refused(tmp_path):
    first_run(tmp_path)
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep").write_text("keep")
    (tmp_path / TMP_NAME).symlink_to(elsewhere)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    with pytest.raises(WikiRefused, match=r"\.bilinc-wiki\.tmp"):
        write_tree(tmp_path, FILES, previous=previous, manifest_for=manifest_for)

    assert (elsewhere / "keep").read_text() == "keep"


def test_stale_tmp_from_a_crashed_run_is_replaced(tmp_path):
    first_run(tmp_path)
    (tmp_path / TMP_NAME).mkdir()
    (tmp_path / TMP_NAME / "junk.md").write_text("junk")
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    write_tree(tmp_path, FILES, previous=previous, manifest_for=manifest_for)

    assert not (tmp_path / TMP_NAME).exists()


def test_build_error_leaves_the_previous_wiki_intact(tmp_path, monkeypatch):
    first_run(tmp_path)
    before = tree(tmp_path)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    real_open = os.open
    calls = {"n": 0}

    def failing_open(path, flags, mode=0o777, *args, **kwargs):
        if TMP_NAME in str(path) and flags & os.O_CREAT:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError(28, "No space left on device")
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(writer.os, "open", failing_open)

    with pytest.raises(WikiExportError, match="No space left"):
        write_tree(tmp_path, {**FILES, "c.md": "changed\n"}, previous=previous, manifest_for=manifest_for)

    assert tree(tmp_path) == before


def test_build_error_on_a_first_run_leaves_no_folder(tmp_path, monkeypatch):
    target = tmp_path / "wiki"
    real_open = os.open

    def failing_open(path, flags, mode=0o777, *args, **kwargs):
        if TMP_NAME in str(path) and flags & os.O_CREAT:
            raise OSError(13, "Permission denied")
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(writer.os, "open", failing_open)

    with pytest.raises(WikiExportError):
        write_tree(target, FILES, previous=None, manifest_for=manifest_for)

    assert not target.exists()


def test_crash_mid_move_then_rerun_recovers(tmp_path, monkeypatch):
    first_run(tmp_path)
    (tmp_path / "notes.md").write_text("mine")
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    new_files = {"AGENTS.md": "a2\n", "index.md": "i2\n", "x/_index.md": "x\n", "x/y.md": "y\n", "z.md": "z\n"}
    real_replace = os.replace
    calls = {"n": 0}

    def failing_replace(src, dst, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(5, "Input/output error")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(writer.os, "replace", failing_replace)

    with pytest.raises(WikiExportError):
        write_tree(tmp_path, new_files, previous=previous, manifest_for=manifest_for)

    manifest = read_manifest_json(tmp_path)
    assert manifest["complete"] is False
    on_disk = {
        rel
        for rel, (content, mode) in tree(tmp_path).items()
        if content is not None and not rel.startswith(".") and rel != "notes.md"
    }
    assert on_disk <= set(manifest["files"])
    assert (tmp_path / "notes.md").read_text() == "mine"

    monkeypatch.setattr(writer.os, "replace", real_replace)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    write_tree(tmp_path, new_files, previous=previous, manifest_for=manifest_for)

    manifest = read_manifest_json(tmp_path)
    assert manifest["complete"] is True
    files_now = {
        rel for rel, (content, mode) in tree(tmp_path).items() if content is not None and not rel.startswith(".")
    }
    assert files_now == set(new_files) | {"notes.md"}


def test_manifest_written_last(tmp_path, monkeypatch):
    first_run(tmp_path)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    order = []
    real_replace = os.replace

    def recording_replace(src, dst, *args, **kwargs):
        order.append(Path(dst).name)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(writer.os, "replace", recording_replace)

    write_tree(tmp_path, FILES, previous=previous, manifest_for=manifest_for)

    assert order[0] == MANIFEST_NAME and order[-1] == MANIFEST_NAME
    assert order.count(MANIFEST_NAME) == 2


def test_rejects_unsafe_file_paths(tmp_path):
    with pytest.raises(ValueError):
        write_tree(tmp_path, {"../escape.md": "x"}, previous=None, manifest_for=manifest_for)
    assert not (tmp_path.parent / "escape.md").exists()


def test_dumps_manifest_round_trip_is_what_is_written(tmp_path):
    first_run(tmp_path)

    text = (tmp_path / MANIFEST_NAME).read_text(encoding="utf-8")

    assert text == dumps_manifest(manifest_for(True, sorted(FILES)))


def test_lone_surrogates_in_content_do_not_stop_the_write(tmp_path):
    write_tree(tmp_path, {"index.md": "bad \ud800 text\n"}, previous=None, manifest_for=manifest_for)

    assert (tmp_path / "index.md").read_bytes() == b"bad ? text\n"


def test_unreadable_target_is_a_clean_error(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(writer.os, "listdir", denied)

    with pytest.raises(WikiExportError, match="Permission denied"):
        inspect_target(tmp_path, base_url=BASE_URL, prefix=None)


def test_target_that_cannot_be_created_is_a_clean_error(tmp_path):
    parent = tmp_path / "locked"
    parent.mkdir()
    os.chmod(parent, 0o500)
    try:
        if os.access(parent, os.W_OK):
            pytest.skip("running with permissions that ignore the mode")
        with pytest.raises(WikiExportError, match="Permission denied"):
            write_tree(parent / "wiki", FILES, previous=None, manifest_for=manifest_for)
    finally:
        os.chmod(parent, 0o700)


def test_final_chmod_failure_is_a_clean_error(tmp_path, monkeypatch):
    real_chmod = os.chmod

    def failing_chmod(path, mode, *args, **kwargs):
        if Path(path) == tmp_path:
            raise PermissionError(1, "Operation not permitted", str(path))
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(writer.os, "chmod", failing_chmod)

    with pytest.raises(WikiExportError, match="not permitted"):
        write_tree(tmp_path, FILES, previous=None, manifest_for=manifest_for)


def test_case_only_rename_on_a_case_insensitive_folder_is_not_refused(tmp_path, case_sensitive_fs):
    # A hard link stands in for a case-insensitive file system: "foo.md" and the
    # owned "Foo.md" are the same directory entry.
    first_run(tmp_path, {**FILES, "Foo.md": "old\n"})
    os.link(tmp_path / "Foo.md", tmp_path / "foo.md")
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    result = write_tree(tmp_path, {**FILES, "foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)

    assert (tmp_path / "foo.md").read_text() == "new\n"
    assert "Foo.md" not in result.removed and "Foo.md" not in result.skipped
    assert read_manifest_json(tmp_path)["files"] == sorted({**FILES, "foo.md": ""})


def test_case_twin_that_is_a_different_file_is_still_refused(tmp_path, case_sensitive_fs):
    first_run(tmp_path, {**FILES, "Foo.md": "old\n"})
    (tmp_path / "foo.md").write_text("the user's own file")
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    with pytest.raises(WikiRefused, match="foo.md"):
        write_tree(tmp_path, {**FILES, "foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)

    assert (tmp_path / "foo.md").read_text() == "the user's own file"


@pytest.fixture()
def case_insensitive(monkeypatch):
    """Make the writer see the folder like macOS/Windows: names match case-insensitively.

    Like APFS and HFS+, names also match across NFC/NFD, and replacing or
    renaming onto an existing entry keeps that entry's spelling. ``listdir``
    is the real one, so it shows the spelling on disk.
    """
    real_lstat, real_unlink, real_replace, real_rename = os.lstat, os.unlink, os.replace, os.rename

    def fold(name):
        return unicodedata.normalize("NFC", name).casefold()

    def existing(path):
        path = Path(path)
        if path.parent.is_dir():
            for name in os.listdir(path.parent):
                if fold(name) == fold(path.name):
                    return path.parent / name
        return path

    class CaseInsensitiveOs:
        def __getattr__(self, name):
            return getattr(os, name)

        def lstat(self, path, *args, **kwargs):
            return real_lstat(existing(path), *args, **kwargs)

        def unlink(self, path, *args, **kwargs):
            return real_unlink(existing(path), *args, **kwargs)

        def replace(self, src, dst, *args, **kwargs):
            return real_replace(src, existing(dst), *args, **kwargs)

        def rename(self, src, dst, *args, **kwargs):
            return real_rename(existing(src), existing(dst), *args, **kwargs)

    monkeypatch.setattr(writer, "os", CaseInsensitiveOs())


def test_rerun_after_an_interrupted_case_rename_keeps_the_new_page(tmp_path, case_insensitive):
    (tmp_path / "Foo.md").write_text("old\n")
    # The interim manifest of a run interrupted mid-rename owns both spellings.
    interrupted = manifest_for(False, ["Foo.md", "foo.md"])

    result = write_tree(tmp_path, {"foo.md": "new\n"}, previous=interrupted, manifest_for=manifest_for)

    pages = [name for name in os.listdir(tmp_path) if name.endswith(".md")]
    assert len(pages) == 1 and (tmp_path / pages[0]).read_text() == "new\n"
    assert result.removed == []


def test_case_rename_on_a_case_insensitive_folder_keeps_the_new_page(tmp_path, case_insensitive):
    first_run(tmp_path, {"Foo.md": "old\n"})
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    result = write_tree(tmp_path, {"foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)

    pages = [name for name in os.listdir(tmp_path) if name.endswith(".md")]
    assert len(pages) == 1 and (tmp_path / pages[0]).read_text() == "new\n"
    assert result.removed == []


def test_case_rename_leaves_the_manifest_spelling_on_disk(tmp_path, case_insensitive):
    first_run(tmp_path, {"Foo.md": "old\n"})
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    write_tree(tmp_path, {"foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)

    assert [n for n in os.listdir(tmp_path) if n.endswith(".md")] == ["foo.md"]
    assert (tmp_path / "foo.md").read_text() == "new\n"
    assert not (tmp_path / TMP_NAME).exists()


def test_existing_2_7_0_state_is_repaired(tmp_path, case_insensitive):
    # The 2.7.0 writer left "Foo.md" on disk while its manifest says "foo.md".
    (tmp_path / "Foo.md").write_text("stale\n")
    owned = manifest_for(True, ["foo.md"])

    write_tree(tmp_path, {"foo.md": "new\n"}, previous=owned, manifest_for=manifest_for)

    assert [n for n in os.listdir(tmp_path) if n.endswith(".md")] == ["foo.md"]
    assert (tmp_path / "foo.md").read_text() == "new\n"


def test_a_users_case_twin_is_still_refused(tmp_path, case_insensitive):
    first_run(tmp_path, {"bar.md": "x\n"})
    (tmp_path / "Foo.md").write_text("the user's file")
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    with pytest.raises(WikiRefused):
        write_tree(tmp_path, {"bar.md": "x\n", "foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)

    assert (tmp_path / "Foo.md").read_text() == "the user's file"
    assert sorted(n for n in os.listdir(tmp_path) if n.endswith(".md")) == ["Foo.md", "bar.md"]


def test_parked_copy_never_lands_on_a_page_path(tmp_path, case_insensitive):
    first_run(tmp_path, {"Foo.md": "old\n", "old/1.md": "page\n"})
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    write_tree(tmp_path, {"foo.md": "new\n", "old/1.md": "page\n"}, previous=previous, manifest_for=manifest_for)

    assert (tmp_path / "old" / "1.md").read_text() == "page\n" and (tmp_path / "foo.md").read_text() == "new\n"
    assert os.listdir(tmp_path / "old") == ["1.md"]


def test_crash_after_parking_keeps_the_old_copy_inside_the_temp_folder(tmp_path, case_insensitive, monkeypatch):
    first_run(tmp_path, {"Foo.md": "old\n", "bar.md": "bar\n"})
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    new_files = {"foo.md": "new\n", "bar.md": "bar\n"}
    emulated_replace = writer.os.replace
    failed = []

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst).name == "foo.md" and not failed:
            failed.append(dst)
            raise OSError(5, "Input/output error")
        return emulated_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(writer.os, "replace", failing_replace)

    with pytest.raises(WikiExportError):
        write_tree(tmp_path, new_files, previous=previous, manifest_for=manifest_for)

    assert failed
    old_copies = [rel for rel, (content, _) in tree(tmp_path).items() if content == b"old\n"]
    assert old_copies and all(rel.startswith(f"{TMP_NAME}/.old/") for rel in old_copies)
    assert not any(n.casefold() == "foo.md" for n in os.listdir(tmp_path))
    manifest = read_manifest_json(tmp_path)
    assert manifest["complete"] is False and "foo.md" in manifest["files"]

    # The next run clears the leftover temp folder and regenerates the page.
    monkeypatch.setattr(writer.os, "replace", emulated_replace)
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)
    write_tree(tmp_path, new_files, previous=previous, manifest_for=manifest_for)

    assert sorted(n for n in os.listdir(tmp_path) if n.endswith(".md")) == ["bar.md", "foo.md"]
    assert (tmp_path / "foo.md").read_text() == "new\n"
    assert not (tmp_path / TMP_NAME).exists()
    manifest = read_manifest_json(tmp_path)
    assert manifest["complete"] is True and manifest["files"] == ["bar.md", "foo.md"]


def test_nfd_spelling_is_not_churned(tmp_path, case_insensitive, monkeypatch):
    # HFS+ stores names in NFD; the manifest key is NFC. Same name, no rename.
    nfc = unicodedata.normalize("NFC", "caf\u00e9.md")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    (tmp_path / nfd).write_text("old\n")
    renames = []
    monkeypatch.setattr(writer.os, "rename", lambda *args, **kwargs: renames.append(args))

    write_tree(tmp_path, {nfc: "new\n"}, previous=manifest_for(True, [nfc]), manifest_for=manifest_for)

    assert renames == []
    assert [n for n in os.listdir(tmp_path) if n.endswith(".md")] == [nfd]
    assert (tmp_path / nfd).read_text() == "new\n"


def test_case_rename_on_a_case_sensitive_folder_removes_the_old_spelling(tmp_path, case_sensitive_fs):
    first_run(tmp_path, {"Foo.md": "old\n"})
    previous = inspect_target(tmp_path, base_url=BASE_URL, prefix=None)

    result = write_tree(tmp_path, {"foo.md": "new\n"}, previous=previous, manifest_for=manifest_for)

    assert result.removed == ["Foo.md"]
    assert sorted(name for name in os.listdir(tmp_path) if name.endswith(".md")) == ["foo.md"]


def test_refused_leftover_temp_folder_is_left_in_place(tmp_path):
    # A temp folder that appears after inspect_target (or that a previous,
    # interrupted run left behind) is refused, and the refusal must not delete it.
    target = tmp_path / "wiki"
    target.mkdir()
    leftover = target / TMP_NAME
    leftover.mkdir()
    (leftover / "keep.md").write_text("not ours to delete")

    with pytest.raises(WikiRefused, match=r"interrupted export"):
        write_tree(target, {"a.md": "page a\n"}, previous=None, manifest_for=manifest_for)

    assert (leftover / "keep.md").read_text() == "not ours to delete"
    assert not (target / "a.md").exists()
    assert not (target / MANIFEST_NAME).exists()
