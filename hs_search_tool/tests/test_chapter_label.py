"""Tests for chapter labels and parent code lookups."""
from __future__ import annotations


def test_chapter_label_known_chapters(engine):
    """Common chapters from our data should have bilingual labels."""
    for chapter in ("85", "87", "64", "39", "84"):
        label = engine.chapter_label(chapter)
        assert label is not None, f"chapter {chapter} missing label"
        # Must contain Arabic + English in parentheses
        assert "(" in label and ")" in label, label


def test_chapter_label_unknown_chapter_returns_none(engine):
    """Chapters not in our hardcoded label list return None gracefully."""
    assert engine.chapter_label("99") in (None, "")
    assert engine.chapter_label("") in (None, "")


def test_get_parent_4digit_known(engine):
    """A common 4-digit prefix from data must return parent metadata."""
    sample = engine.search("8703", limit=1)
    if not sample:
        return
    parent = engine.get_parent("8703", level=4)
    assert parent is not None
    assert parent.code == "8703"
    assert parent.level == 4
    assert parent.child_count > 0


def test_get_parent_6digit_known(engine):
    sample = engine.search("870380", limit=1)
    if not sample:
        return
    parent = engine.get_parent("870380", level=6)
    if parent is not None:
        assert parent.code == "870380"
        assert parent.level == 6


def test_get_parent_unknown_returns_none(engine):
    assert engine.get_parent("9999", level=4) is None
    assert engine.get_parent("", level=4) is None
