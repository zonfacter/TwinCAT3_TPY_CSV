from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence

from PySide6 import QtCore, QtWidgets

from .config import AppConfig, load_config, normalize_existing_paths, save_config
from .converter import ConvertOptions
from .logging_utils import setup_logging
from .worker import BatchJob, ConversionWorker


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TPY → CSV (SPS Analyzer)")

        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[ConversionWorker] = None

        # Logging (file)
        self._app_dir = Path.cwd()  # overwritten after config load if needed
        self._logger = logging.getLogger("tpy_csv_gui")

        self._cfg = self._load_cfg()
        self._build_ui()
        self._apply_cfg_to_ui()

    def _load_cfg(self) -> AppConfig:
        cfg = load_config()
        cfg.input_files = normalize_existing_paths(cfg.input_files)
        return cfg

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)

        layout = QtWidgets.QVBoxLayout(central)

        # Files group
        files_group = QtWidgets.QGroupBox("Batch: Eingabedateien (.tpy)")
        files_layout = QtWidgets.QVBoxLayout(files_group)

        self.files_list = QtWidgets.QListWidget()
        self.files_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        files_layout.addWidget(self.files_list)

        files_btn_row = QtWidgets.QHBoxLayout()
        self.btn_add_files = QtWidgets.QPushButton("Dateien hinzufügen…")
        self.btn_remove_files = QtWidgets.QPushButton("Auswahl entfernen")
        self.btn_clear_files = QtWidgets.QPushButton("Liste leeren")
        files_btn_row.addWidget(self.btn_add_files)
        files_btn_row.addWidget(self.btn_remove_files)
        files_btn_row.addWidget(self.btn_clear_files)
        files_btn_row.addStretch(1)
        files_layout.addLayout(files_btn_row)

        layout.addWidget(files_group)

        # Output group
        out_group = QtWidgets.QGroupBox("Ausgabe")
        out_layout = QtWidgets.QGridLayout(out_group)

        self.out_dir_edit = QtWidgets.QLineEdit()
        self.btn_browse_out_dir = QtWidgets.QPushButton("Ordner wählen…")
        out_layout.addWidget(QtWidgets.QLabel("Output-Ordner:"), 0, 0)
        out_layout.addWidget(self.out_dir_edit, 0, 1)
        out_layout.addWidget(self.btn_browse_out_dir, 0, 2)

        self.only_edit = QtWidgets.QLineEdit()
        self.btn_browse_only = QtWidgets.QPushButton("…")
        out_layout.addWidget(QtWidgets.QLabel("Whitelist (optional):"), 1, 0)
        out_layout.addWidget(self.only_edit, 1, 1)
        out_layout.addWidget(self.btn_browse_only, 1, 2)

        self.skip_edit = QtWidgets.QLineEdit()
        self.btn_browse_skip = QtWidgets.QPushButton("…")
        out_layout.addWidget(QtWidgets.QLabel("Blacklist (optional):"), 2, 0)
        out_layout.addWidget(self.skip_edit, 2, 1)
        out_layout.addWidget(self.btn_browse_skip, 2, 2)

        layout.addWidget(out_group)

        # Options group
        opt_group = QtWidgets.QGroupBox("Optionen")
        opt_layout = QtWidgets.QVBoxLayout(opt_group)
        self.chk_recurse = QtWidgets.QCheckBox("UDT/STRUCT rekursiv entfalten")
        self.chk_recurse_array = QtWidgets.QCheckBox("Array-UDTs rekursiv entfalten")
        opt_layout.addWidget(self.chk_recurse)
        opt_layout.addWidget(self.chk_recurse_array)
        layout.addWidget(opt_group)

        # Run group
        run_row = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_cancel = QtWidgets.QPushButton("Abbrechen")
        self.btn_cancel.setEnabled(False)
        run_row.addWidget(self.btn_start)
        run_row.addWidget(self.btn_cancel)
        run_row.addStretch(1)
        layout.addLayout(run_row)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QtWidgets.QLabel("Bereit.")
        layout.addWidget(self.status_label)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view, stretch=1)

        # Connections
        self.btn_add_files.clicked.connect(self._on_add_files)
        self.btn_remove_files.clicked.connect(self._on_remove_selected)
        self.btn_clear_files.clicked.connect(self._on_clear_list)
        self.btn_browse_out_dir.clicked.connect(self._on_browse_out_dir)
        self.btn_browse_only.clicked.connect(self._on_browse_only)
        self.btn_browse_skip.clicked.connect(self._on_browse_skip)

        self.chk_recurse.stateChanged.connect(self._on_recurse_changed)

        self.btn_start.clicked.connect(self._on_start)
        self.btn_cancel.clicked.connect(self._on_cancel)

        self._on_recurse_changed()

    def _apply_cfg_to_ui(self) -> None:
        self.out_dir_edit.setText(self._cfg.output_dir)
        self.only_edit.setText(self._cfg.only_file)
        self.skip_edit.setText(self._cfg.skip_file)
        self.chk_recurse.setChecked(self._cfg.recurse)
        self.chk_recurse_array.setChecked(self._cfg.recurse_array)

        for p in self._cfg.input_files:
            self.files_list.addItem(p)

        # Setup logging file path based on config dir
        # (we keep it simple; file will be in config folder)
        from .config import get_app_dir

        log_file = get_app_dir() / "app.log"
        self._logger = setup_logging(log_file)
        self._append_log(f"Log-Datei: {log_file}")

    def _gather_inputs(self) -> List[Path]:
        paths: List[Path] = []
        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            if item:
                paths.append(Path(item.text()))
        return paths

    def _append_log(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)
        try:
            self._logger.info(msg)
        except Exception:
            pass

    def _save_cfg_from_ui(self) -> None:
        self._cfg.output_dir = self.out_dir_edit.text().strip()
        self._cfg.only_file = self.only_edit.text().strip()
        self._cfg.skip_file = self.skip_edit.text().strip()
        self._cfg.recurse = self.chk_recurse.isChecked()
        self._cfg.recurse_array = self.chk_recurse_array.isChecked()
        self._cfg.input_files = [str(p) for p in self._gather_inputs()]
        save_config(self._cfg)

    @QtCore.Slot()
    def _on_recurse_changed(self) -> None:
        if not self.chk_recurse.isChecked():
            self.chk_recurse_array.setChecked(False)
            self.chk_recurse_array.setEnabled(False)
        else:
            self.chk_recurse_array.setEnabled(True)

    @QtCore.Slot()
    def _on_add_files(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "TPY-Dateien auswählen",
            "",
            "TPY Dateien (*.tpy);;Alle Dateien (*.*)",
        )
        if not files:
            return
        existing = set(self._gather_inputs())
        for f in files:
            p = Path(f)
            if p not in existing:
                self.files_list.addItem(str(p))

        self._save_cfg_from_ui()

    @QtCore.Slot()
    def _on_remove_selected(self) -> None:
        for item in self.files_list.selectedItems():
            row = self.files_list.row(item)
            self.files_list.takeItem(row)
        self._save_cfg_from_ui()

    @QtCore.Slot()
    def _on_clear_list(self) -> None:
        self.files_list.clear()
        self._save_cfg_from_ui()

    @QtCore.Slot()
    def _on_browse_out_dir(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Output-Ordner wählen", self.out_dir_edit.text().strip())
        if d:
            self.out_dir_edit.setText(d)
            self._save_cfg_from_ui()

    @QtCore.Slot()
    def _on_browse_only(self) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Whitelist-Datei auswählen",
            self.only_edit.text().strip(),
            "Text Dateien (*.txt);;Alle Dateien (*.*)",
        )
        if f:
            self.only_edit.setText(f)
            self._save_cfg_from_ui()

    @QtCore.Slot()
    def _on_browse_skip(self) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Blacklist-Datei auswählen",
            self.skip_edit.text().strip(),
            "Text Dateien (*.txt);;Alle Dateien (*.*)",
        )
        if f:
            self.skip_edit.setText(f)
            self._save_cfg_from_ui()

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.btn_add_files.setEnabled(not running)
        self.btn_remove_files.setEnabled(not running)
        self.btn_clear_files.setEnabled(not running)
        self.btn_browse_out_dir.setEnabled(not running)
        self.btn_browse_only.setEnabled(not running)
        self.btn_browse_skip.setEnabled(not running)
        self.chk_recurse.setEnabled(not running)
        self.chk_recurse_array.setEnabled(not running and self.chk_recurse.isChecked())

    @QtCore.Slot()
    def _on_start(self) -> None:
        input_files = self._gather_inputs()
        if not input_files:
            QtWidgets.QMessageBox.warning(self, "Fehlende Eingabe", "Bitte mindestens eine .tpy Datei hinzufügen.")
            return

        out_dir = Path(self.out_dir_edit.text().strip())
        if not str(out_dir):
            QtWidgets.QMessageBox.warning(self, "Fehlende Ausgabe", "Bitte einen Output-Ordner wählen.")
            return

        if not out_dir.exists():
            res = QtWidgets.QMessageBox.question(
                self,
                "Ordner existiert nicht",
                f"Der Output-Ordner existiert nicht:\n{out_dir}\n\nSoll er erstellt werden?",
            )
            if res != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(self, "Fehler", f"Output-Ordner konnte nicht erstellt werden:\n{exc}")
                return

        options = ConvertOptions(
            recurse=self.chk_recurse.isChecked(),
            recurse_array=self.chk_recurse_array.isChecked(),
            only_file=self.only_edit.text().strip() or None,
            skip_file=self.skip_edit.text().strip() or None,
        )

        self._save_cfg_from_ui()

        self.progress.setValue(0)
        self.log_view.clear()
        self._append_log("Batch gestartet.")
        self.status_label.setText("Läuft…")
        self._set_running(True)

        job = BatchJob(
            input_files=input_files,
            output_dir=out_dir,
            options=options,
        )

        self._thread = QtCore.QThread(self)
        self._worker = ConversionWorker(job)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)

        self._worker.log_line.connect(self._append_log)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.file_started.connect(lambda p: self.status_label.setText(f"Verarbeite: {p}"))
        self._worker.file_finished.connect(lambda p: self.status_label.setText(f"Fertig: {p}"))

        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)

        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.finished.connect(self._cleanup_thread)

        self._thread.start()

    @QtCore.Slot()
    def _on_cancel(self) -> None:
        if self._worker:
            self._append_log("Abbruch angefordert…")
            self._worker.request_cancel()

    @QtCore.Slot()
    def _on_worker_finished(self) -> None:
        self._append_log("Batch fertig.")
        self.status_label.setText("Fertig.")
        self.progress.setValue(100)
        self._set_running(False)

    @QtCore.Slot(str)
    def _on_worker_failed(self, msg: str) -> None:
        self._append_log(f"Fehler: {msg}")
        self.status_label.setText("Fehler.")
        self._set_running(False)
        QtWidgets.QMessageBox.critical(self, "Konvertierung fehlgeschlagen", msg)

    @QtCore.Slot()
    def _cleanup_thread(self) -> None:
        self._worker = None
        if self._thread:
            self._thread.deleteLater()
        self._thread = None

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self._save_cfg_from_ui()
        except Exception:
            pass
        super().closeEvent(event)


def run_app(argv: Sequence[str]) -> int:
    app = QtWidgets.QApplication(list(argv))
    w = MainWindow()
    w.resize(980, 720)
    w.show()
    return app.exec()
