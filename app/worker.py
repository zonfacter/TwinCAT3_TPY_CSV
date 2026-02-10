from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore

from .converter import ConvertOptions, TpyToCsvConverter
from .exceptions import ConversionError


@dataclass(frozen=True)
class BatchJob:
    input_files: List[Path]
    output_dir: Path
    options: ConvertOptions


class ConversionWorker(QtCore.QObject):
    log_line = QtCore.Signal(str)
    progress = QtCore.Signal(int)          # 0..100 overall
    file_started = QtCore.Signal(str)      # input path
    file_finished = QtCore.Signal(str)     # input path
    finished = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, job: BatchJob) -> None:
        super().__init__()
        self._job = job
        self._stop_event = threading.Event()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            total_files = max(1, len(self._job.input_files))
            for idx, input_file in enumerate(self._job.input_files):
                if self._stop_event.is_set():
                    raise ConversionError("Abgebrochen")

                self.file_started.emit(str(input_file))
                self.log_line.emit(f"Starte: {input_file}")

                output_base = self._job.output_dir / f"{input_file.stem}.csv"
                converter = TpyToCsvConverter(self._job.options)

                base_progress = int(idx * 100 / total_files)
                span = int(100 / total_files) if total_files else 100

                def log(msg: str) -> None:
                    self.log_line.emit(msg)

                def cancel_requested() -> bool:
                    return self._stop_event.is_set()

                def file_progress(pct: int) -> None:
                    overall = min(100, base_progress + int(span * pct / 100))
                    self.progress.emit(overall)

                out_files = converter.convert_one(
                    input_file=input_file,
                    output_base_csv=output_base,
                    log=log,
                    cancel_requested=cancel_requested,
                    progress=file_progress,
                )

                self.log_line.emit(f"Fertig: {input_file} -> {len(out_files)} Datei(en)")
                self.file_finished.emit(str(input_file))
                self.progress.emit(min(100, int((idx + 1) * 100 / total_files)))

            self.finished.emit()
        except ConversionError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # last resort
            self.failed.emit(f"Unerwarteter Fehler: {exc}")

    def request_cancel(self) -> None:
        self._stop_event.set()
