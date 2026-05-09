import json
import os
from unittest.mock import patch

import pytest

from ui.feedback import FeedbackDialog, FEEDBACK_CATEGORIES


def test_dialog_title(qtbot):
    dlg = FeedbackDialog()
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "피드백 보내기"


def test_category_options(qtbot):
    dlg = FeedbackDialog()
    qtbot.addWidget(dlg)
    assert dlg.cb_category.count() == len(FEEDBACK_CATEGORIES)
    for i, cat in enumerate(FEEDBACK_CATEGORIES):
        assert dlg.cb_category.itemText(i) == cat


def test_empty_message_shows_warning(qtbot):
    dlg = FeedbackDialog()
    qtbot.addWidget(dlg)
    with patch("ui.feedback.QMessageBox.warning") as mock_warn:
        dlg._submit()
        mock_warn.assert_called_once()


def test_empty_message_does_not_save(qtbot, tmp_path):
    feedback_file = str(tmp_path / "feedback.json")
    dlg = FeedbackDialog(feedback_file=feedback_file)
    qtbot.addWidget(dlg)
    with patch("ui.feedback.QMessageBox.warning"):
        dlg._submit()
    assert not os.path.exists(feedback_file)


def test_submit_saves_entry(qtbot, tmp_path):
    feedback_file = str(tmp_path / "feedback.json")
    dlg = FeedbackDialog(feedback_file=feedback_file)
    qtbot.addWidget(dlg)
    dlg.text_message.setPlainText("테스트 피드백")
    dlg.cb_category.setCurrentIndex(0)

    with patch("ui.feedback.QMessageBox.information"):
        dlg._submit()

    assert os.path.exists(feedback_file)
    with open(feedback_file, "r", encoding="utf-8") as f:
        entries = json.load(f)
    assert len(entries) == 1
    assert entries[0]["message"] == "테스트 피드백"
    assert entries[0]["category"] == FEEDBACK_CATEGORIES[0]
    assert "timestamp" in entries[0]


def test_submit_appends_to_existing_file(qtbot, tmp_path):
    feedback_file = str(tmp_path / "feedback.json")
    existing = [{"timestamp": "2026-01-01T00:00:00", "category": "기타", "message": "기존 항목"}]
    with open(feedback_file, "w", encoding="utf-8") as f:
        json.dump(existing, f)

    dlg = FeedbackDialog(feedback_file=feedback_file)
    qtbot.addWidget(dlg)
    dlg.text_message.setPlainText("새 피드백")
    dlg.cb_category.setCurrentIndex(1)

    with patch("ui.feedback.QMessageBox.information"):
        dlg._submit()

    with open(feedback_file, "r", encoding="utf-8") as f:
        entries = json.load(f)
    assert len(entries) == 2
    assert entries[0]["message"] == "기존 항목"
    assert entries[1]["message"] == "새 피드백"
    assert entries[1]["category"] == FEEDBACK_CATEGORIES[1]


def test_submit_handles_corrupted_file(qtbot, tmp_path):
    feedback_file = str(tmp_path / "feedback.json")
    with open(feedback_file, "w") as f:
        f.write("not valid json{{{")

    dlg = FeedbackDialog(feedback_file=feedback_file)
    qtbot.addWidget(dlg)
    dlg.text_message.setPlainText("복구 테스트")

    with patch("ui.feedback.QMessageBox.information"):
        dlg._submit()

    with open(feedback_file, "r", encoding="utf-8") as f:
        entries = json.load(f)
    assert len(entries) == 1
    assert entries[0]["message"] == "복구 테스트"


def test_whitespace_only_message_shows_warning(qtbot):
    dlg = FeedbackDialog()
    qtbot.addWidget(dlg)
    dlg.text_message.setPlainText("   \n  ")
    with patch("ui.feedback.QMessageBox.warning") as mock_warn:
        dlg._submit()
        mock_warn.assert_called_once()
