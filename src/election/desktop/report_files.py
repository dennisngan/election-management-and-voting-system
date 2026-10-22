"""Validated local destinations and atomic writes for authenticated report downloads."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QIODevice, QSaveFile, QUrl

from election.desktop.configuration import ResultHandler

type DownloadRequest = Callable[[str, ResultHandler, Callable[[str], None]], None]


def report_destination(filepath: str) -> str | None:
    url = QUrl(filepath)
    candidate = url.toLocalFile() if url.isLocalFile() else filepath
    return candidate if candidate and Path(candidate).is_absolute() else None


def save_report(data: dict[str, Any], destination: str, format: str) -> bool:
    raw, content_type = data.get("data"), data.get("content_type", "")
    expected = {"pdf": "application/pdf", "csv": "text/csv"}.get(format)
    actual = str(content_type).partition(";")[0].strip().lower()
    if expected is None or not isinstance(raw, bytes) or actual != expected:
        return False
    output = QSaveFile(destination)
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        return False
    if output.write(raw) != len(raw) or not output.commit():
        output.cancelWriting()
        return False
    return True
