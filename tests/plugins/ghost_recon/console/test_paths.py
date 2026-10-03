"""Path containment: only paths that resolve inside an allowed root are accepted."""
import os

import pytest

from plugins.ghost_recon.console.paths import resolve_within


def test_inside_outside_and_missing(tmp_path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    inside = root / "a" / "f.txt"
    inside.write_text("x", encoding="utf-8")
    outside = tmp_path / "other.txt"
    outside.write_text("y", encoding="utf-8")
    assert resolve_within(inside, [root]) == inside.resolve()
    assert resolve_within(root / "a" / ".." / ".." / "other.txt", [root]) is None
    assert resolve_within(outside, [root]) is None
    assert resolve_within(root / "missing.txt", [root]) is None
    assert resolve_within(inside, []) is None


@pytest.mark.platforms("posix")
def test_symlink_escaping_the_root_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("s", encoding="utf-8")
    os.symlink(secret, root / "link.txt")
    assert resolve_within(root / "link.txt", [root]) is None


@pytest.mark.platforms("windows")
def test_windows_containment_ignores_letter_case(tmp_path):
    root = tmp_path / "Root"
    root.mkdir()
    f = root / "Informe.md"
    f.write_text("x", encoding="utf-8")
    assert resolve_within(str(f).upper(), [root]) is not None
