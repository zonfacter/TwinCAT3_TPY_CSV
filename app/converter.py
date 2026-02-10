from __future__ import annotations

import csv
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Pattern, Sequence, Tuple

from .exceptions import ConversionError


ARRAY_RE = re.compile(r"^(?:.*)?\s*ARRAY\s*\[(\d+)\s*\.\.\s*(\d+)\]\s*OF\s*(.+)$", re.IGNORECASE)
STRING_RE = re.compile(r"^(W?STRING)\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)

PRIM_BITS: Dict[str, int] = {
    "BOOL": 8,
    "BYTE": 8,
    "SINT": 8,
    "USINT": 8,
    "WORD": 16,
    "INT": 16,
    "UINT": 16,
    "DWORD": 32,
    "DINT": 32,
    "UDINT": 32,
    "REAL": 32,
    "LWORD": 64,
    "LINT": 64,
    "ULINT": 64,
    "LREAL": 64,
}

SPECIAL_BITS: Dict[str, int] = {
    "TIME": 32,
    "DATE_AND_TIME": 32,
    "DATE": 16,
    "TIME_OF_DAY": 32,
    "TOD": 32,
    "DT": 32,
    "LTIME": 64,
    "LDATE": 32,
}

HEADER_LINE_1 = "Beckhoff TwinCat V2-PLC-Symbolfile"
HEADER_LINES = 2
DEFAULT_MAX_TOTAL_LINES_PER_FILE = 1_670_000
DEFAULT_ENCODING = "utf-8"


Row = List[object]
LogFn = Callable[[str], None]
CancelFn = Callable[[], bool]
ProgressFn = Callable[[int], None]


@dataclass(frozen=True)
class ConvertOptions:
    recurse: bool = True
    recurse_array: bool = True
    only_file: Optional[str] = None
    skip_file: Optional[str] = None
    max_total_lines_per_file: int = DEFAULT_MAX_TOTAL_LINES_PER_FILE
    encoding: str = DEFAULT_ENCODING


def _text(e: ET.Element, tag: str, default: str = "") -> str:
    n = e.find(tag)
    return n.text if n is not None and n.text is not None else default


def _limit_comment(s: str) -> str:
    return (s or "")[:200].replace("\n", " ").replace("\r", " ")


def _qualify(parent: str, child: str) -> str:
    child = child or ""
    parent = parent or ""
    if not parent:
        return child
    if child.startswith(parent + "."):
        return child
    return f"{parent}.{child}" if child else parent


def _part_filename(base_path: Path, part_index: int) -> Path:
    if part_index == 0:
        return base_path
    return base_path.with_name(f"{base_path.stem}_{part_index + 1}{base_path.suffix}")


def _load_regex_file(path: Optional[str], encoding: str, log: LogFn) -> List[Pattern[str]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        log(f"Warnung: Regex-Datei nicht gefunden: {p}. Ignoriere.")
        return []

    patterns: List[Pattern[str]] = []
    for line in p.read_text(encoding=encoding).splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";") or s.startswith("//"):
            continue
        try:
            patterns.append(re.compile(s))
        except re.error as exc:
            log(f"Warnung: ungültiges Regex in {p}: {s!r} -> {exc}")
    return patterns


def _matches_any(name: str, patterns: Sequence[Pattern[str]]) -> bool:
    for pat in patterns:
        if pat.search(name):
            return True
    return False


def _allowed_udt(name: Optional[str], only_pats: Sequence[Pattern[str]], skip_pats: Sequence[Pattern[str]]) -> bool:
    if not name:
        return False
    if only_pats and not _matches_any(name, only_pats):
        return False
    if skip_pats and _matches_any(name, skip_pats):
        return False
    return True


class _CsvPartWriter:
    """
    Writes CSV rows into a temporary file while counting them,
    then finalizes to the target path with the required two header lines:
      line1: fixed header
      line2: record count (number only)
    """

    def __init__(self, encoding: str) -> None:
        self._encoding = encoding
        self._tmp_file = None
        self._tmp_path: Optional[Path] = None
        self._writer: Optional[csv.writer] = None
        self.record_count: int = 0

    def open(self, tmp_dir: Path) -> None:
        self.close()

        tmp_dir.mkdir(parents=True, exist_ok=True)
        f = tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding=self._encoding,
            delete=False,
            prefix="tpycsv_",
            suffix=".tmp",
            dir=str(tmp_dir),
        )
        self._tmp_file = f
        self._tmp_path = Path(f.name)
        self._writer = csv.writer(f, delimiter=";", lineterminator="\n")
        self.record_count = 0

    def write_row(self, row: Row) -> None:
        if not self._writer:
            raise ConversionError("Internal error: CSV writer is not open.")
        self._writer.writerow(row)
        self.record_count += 1

    def finalize_to(self, out_path: Path) -> None:
        if not self._tmp_file or not self._tmp_path:
            raise ConversionError("Internal error: cannot finalize; temp file missing.")

        self._tmp_file.flush()
        self._tmp_file.close()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding=self._encoding, newline="") as out_f:
            out_f.write(HEADER_LINE_1 + "\n")
            out_f.write(str(self.record_count) + "\n")
            with self._tmp_path.open("r", encoding=self._encoding, newline="") as in_f:
                # Copy raw CSV rows
                for chunk in iter(lambda: in_f.read(1024 * 1024), ""):
                    if not chunk:
                        break
                    out_f.write(chunk)

        try:
            self._tmp_path.unlink(missing_ok=True)
        except OSError:
            # Non-fatal
            pass

        self._tmp_file = None
        self._tmp_path = None
        self._writer = None

    def close(self) -> None:
        if self._tmp_file:
            try:
                self._tmp_file.close()
            except OSError:
                pass
        self._tmp_file = None
        self._writer = None
        if self._tmp_path:
            try:
                self._tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._tmp_path = None


class TpyToCsvConverter:
    def __init__(self, options: ConvertOptions) -> None:
        self._opt = options

        if self._opt.max_total_lines_per_file < HEADER_LINES + 1:
            raise ConversionError("max_total_lines_per_file ist zu klein.")

        self._max_data_rows_per_file = self._opt.max_total_lines_per_file - HEADER_LINES

    def convert_one(
        self,
        input_file: Path,
        output_base_csv: Path,
        *,
        log: LogFn,
        cancel_requested: CancelFn,
        progress: ProgressFn,
    ) -> List[Path]:
        """
        Converts one .tpy XML into one or more CSV parts.
        Returns list of written output file paths.
        """
        if not input_file.exists():
            raise ConversionError(f"Eingabedatei existiert nicht: {input_file}")

        only_pats = _load_regex_file(self._opt.only_file, self._opt.encoding, log)
        skip_pats = _load_regex_file(self._opt.skip_file, self._opt.encoding, log)

        try:
            tree = ET.parse(str(input_file))
        except (ET.ParseError, OSError) as exc:
            raise ConversionError(f"XML konnte nicht gelesen werden: {exc}") from exc

        root = tree.getroot()

        # DataType maps
        datatype_by_name: Dict[str, ET.Element] = {}
        datatype_bits: Dict[str, int] = {}

        for dt in root.findall(".//DataTypes/DataType"):
            dt_name = _text(dt, "Name")
            if not dt_name:
                continue
            datatype_by_name[dt_name] = dt
            bs = _text(dt, "BitSize", "")
            try:
                datatype_bits[dt_name] = int(bs) if bs else 0
            except ValueError:
                datatype_bits[dt_name] = 0

        def get_type_bits(type_name: str, symbol_bitsize: Optional[int] = None, array_count: Optional[int] = None) -> int:
            if not type_name:
                return 8
            base = type_name.strip()

            b = PRIM_BITS.get(base.upper())
            if b is not None:
                return b

            m = STRING_RE.match(base)
            if m:
                n = int(m.group(2))
                bytes_per_char = 2 if m.group(1).upper().startswith("W") else 1
                return (n + 1) * bytes_per_char * 8

            b = SPECIAL_BITS.get(base.upper())
            if b is not None:
                return b

            b = datatype_bits.get(base)
            if b:
                return b

            if symbol_bitsize and array_count:
                return max(8, (symbol_bitsize // array_count))

            return 8

        def allowed_udt(name: str) -> bool:
            return _allowed_udt(name, only_pats, skip_pats)

        def expand_struct_recursive(
            writer: _CsvPartWriter,
            out_paths: List[Path],
            part_index_ref: List[int],
            rows_in_part_ref: List[int],
            parent_name: str,
            parent_base_addr: int,
            parent_abs_bitoffs: int,
            igroup: str,
            dtype_name: str,
            allow_recurse: bool,
        ) -> None:
            dt = datatype_by_name.get(dtype_name)
            if dt is None:
                return

            for si in dt.findall("SubItem"):
                if cancel_requested():
                    raise ConversionError("Abgebrochen")

                si_name = _text(si, "Name")
                si_type = _text(si, "Type")
                si_bits = int(_text(si, "BitSize", "0") or 0)
                si_boffs = int(_text(si, "BitOffs", "0") or 0)

                default_v = ""
                de = si.find("Default/Value")
                if de is not None and de.text:
                    default_v = de.text

                abs_bitoffs = parent_abs_bitoffs + si_boffs
                actual_addr = parent_base_addr + (abs_bitoffs // 8)
                qual_name = _qualify(parent_name, si_name)

                _emit_row_with_chunking(
                    writer=writer,
                    out_paths=out_paths,
                    part_index_ref=part_index_ref,
                    rows_in_part_ref=rows_in_part_ref,
                    output_base_csv=output_base_csv,
                    tmp_dir=output_base_csv.parent,
                    row=[igroup, actual_addr, qual_name, "", si_type, si_bits, abs_bitoffs, default_v, actual_addr],
                    log=log,
                )

                if allow_recurse and (si_type in datatype_by_name) and allowed_udt(si_type):
                    expand_struct_recursive(
                        writer,
                        out_paths,
                        part_index_ref,
                        rows_in_part_ref,
                        qual_name,
                        parent_base_addr,
                        abs_bitoffs,
                        igroup,
                        si_type,
                        allow_recurse,
                    )

        def _emit_row_with_chunking(
            *,
            writer: _CsvPartWriter,
            out_paths: List[Path],
            part_index_ref: List[int],
            rows_in_part_ref: List[int],
            output_base_csv: Path,
            tmp_dir: Path,
            row: Row,
            log: LogFn,
        ) -> None:
            if rows_in_part_ref[0] >= self._max_data_rows_per_file:
                out_path = _part_filename(output_base_csv, part_index_ref[0])
                writer.finalize_to(out_path)
                out_paths.append(out_path)
                log(
                    f"geschrieben: {out_path} (Datensätze: {writer.record_count}, "
                    f"Gesamtzeilen: {writer.record_count + HEADER_LINES})"
                )
                part_index_ref[0] += 1
                rows_in_part_ref[0] = 0
                writer.open(tmp_dir=tmp_dir)

            writer.write_row(row)
            rows_in_part_ref[0] += 1

        # Prepare writer
        writer = _CsvPartWriter(encoding=self._opt.encoding)
        out_paths: List[Path] = []
        part_index_ref = [0]
        rows_in_part_ref = [0]
        writer.open(tmp_dir=output_base_csv.parent)

        # Iterate symbols
        symbols = root.findall(".//Symbol")
        total_symbols = max(1, len(symbols))
        processed_symbols = 0

        for sym in symbols:
            if cancel_requested():
                raise ConversionError("Abgebrochen")

            name = _text(sym, "Name")
            type_ = _text(sym, "Type")
            igroup = _text(sym, "IGroup")
            ioffset = int(_text(sym, "IOffset", "0") or 0)
            bitsize = int(_text(sym, "BitSize", "0") or 0)
            comment = _limit_comment(_text(sym, "Comment", ""))

            # Top row
            _emit_row_with_chunking(
                writer=writer,
                out_paths=out_paths,
                part_index_ref=part_index_ref,
                rows_in_part_ref=rows_in_part_ref,
                output_base_csv=output_base_csv,
                tmp_dir=output_base_csv.parent,
                row=[igroup, ioffset, name, comment, type_, bitsize, "", "", ioffset],
                log=log,
            )

            # ARRAY?
            m = ARRAY_RE.match(type_ or "")
            if m:
                start = int(m.group(1))
                end = int(m.group(2))
                elem_type = m.group(3).strip()
                count = end - start + 1 if end >= start else 0
                if count > 0:
                    per_bits = get_type_bits(elem_type, symbol_bitsize=bitsize, array_count=count)
                    base_addr = ioffset
                    for idx in range(start, end + 1):
                        if cancel_requested():
                            raise ConversionError("Abgebrochen")

                        elem_boffs = (idx - start) * per_bits
                        actual_addr = base_addr + (elem_boffs // 8)
                        item_name = f"{name}[{idx}]"
                        _emit_row_with_chunking(
                            writer=writer,
                            out_paths=out_paths,
                            part_index_ref=part_index_ref,
                            rows_in_part_ref=rows_in_part_ref,
                            output_base_csv=output_base_csv,
                            tmp_dir=output_base_csv.parent,
                            row=[igroup, actual_addr, item_name, "", elem_type, per_bits, elem_boffs, "", actual_addr],
                            log=log,
                        )

                        if self._opt.recurse_array and (elem_type in datatype_by_name) and allowed_udt(elem_type):
                            expand_struct_recursive(
                                writer,
                                out_paths,
                                part_index_ref,
                                rows_in_part_ref,
                                item_name,
                                base_addr,
                                elem_boffs,
                                igroup,
                                elem_type,
                                allow_recurse=True,
                            )

                processed_symbols += 1
                progress(int(processed_symbols * 100 / total_symbols))
                continue

            # STRUCT/UDT
            if type_ in datatype_by_name:
                if self._opt.recurse and allowed_udt(type_):
                    expand_struct_recursive(
                        writer,
                        out_paths,
                        part_index_ref,
                        rows_in_part_ref,
                        name,
                        ioffset,
                        0,
                        igroup,
                        type_,
                        allow_recurse=True,
                    )
                else:
                    dt = datatype_by_name[type_]
                    base_addr = ioffset
                    for si in dt.findall("SubItem"):
                        if cancel_requested():
                            raise ConversionError("Abgebrochen")

                        si_name = _text(si, "Name")
                        si_type = _text(si, "Type")
                        si_bits = int(_text(si, "BitSize", "0") or 0)
                        si_boffs = int(_text(si, "BitOffs", "0") or 0)

                        default_v = ""
                        de = si.find("Default/Value")
                        if de is not None and de.text:
                            default_v = de.text

                        abs_bitoffs = si_boffs
                        actual_addr = base_addr + (abs_bitoffs // 8)
                        qual_name = _qualify(name, si_name)

                        _emit_row_with_chunking(
                            writer=writer,
                            out_paths=out_paths,
                            part_index_ref=part_index_ref,
                            rows_in_part_ref=rows_in_part_ref,
                            output_base_csv=output_base_csv,
                            tmp_dir=output_base_csv.parent,
                            row=[igroup, actual_addr, qual_name, "", si_type, si_bits, abs_bitoffs, default_v, actual_addr],
                            log=log,
                        )

            processed_symbols += 1
            progress(int(processed_symbols * 100 / total_symbols))

        # Finalize last part if it has any rows
        if writer.record_count > 0:
            out_path = _part_filename(output_base_csv, part_index_ref[0])
            writer.finalize_to(out_path)
            out_paths.append(out_path)
            log(
                f"geschrieben: {out_path} (Datensätze: {writer.record_count}, "
                f"Gesamtzeilen: {writer.record_count + HEADER_LINES})"
            )

        writer.close()
        return out_paths
