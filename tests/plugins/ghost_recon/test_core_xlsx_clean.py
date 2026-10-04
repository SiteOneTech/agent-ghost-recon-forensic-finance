"""The XLSX cleaner strips the control characters openpyxl refuses to write, without needing openpyxl."""
from plugins.ghost_recon.core.reports.xlsx import _clean


def test_clean_strips_control_characters_but_keeps_tab_and_newline():
    assert _clean("a\x01b\x0bc\td\ne") == "abc\td\ne"


def test_clean_passes_non_strings_through():
    assert _clean(-1500.0) == -1500.0 and _clean(None) is None and _clean(7) == 7
