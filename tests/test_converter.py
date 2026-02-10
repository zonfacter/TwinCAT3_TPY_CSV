from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.converter import ConvertOptions, HEADER_LINE_1, HEADER_LINES, TpyToCsvConverter


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


class ConverterTests(unittest.TestCase):
    def test_struct_recurse_emits_subitems(self) -> None:
        with TemporaryDirectory() as td:
            td_path = Path(td)
            tpy = td_path / "in.tpy"
            out = td_path / "out.csv"

            xml = """<?xml version="1.0" encoding="utf-8"?>
<Root>
  <DataTypes>
    <DataType>
      <Name>MYTYPE</Name>
      <BitSize>16</BitSize>
      <SubItem>
        <Name>a</Name>
        <Type>INT</Type>
        <BitSize>16</BitSize>
        <BitOffs>0</BitOffs>
      </SubItem>
    </DataType>
  </DataTypes>
  <Symbols>
    <Symbol>
      <Name>gVar</Name>
      <Type>MYTYPE</Type>
      <IGroup>123</IGroup>
      <IOffset>100</IOffset>
      <BitSize>16</BitSize>
      <Comment>hello</Comment>
    </Symbol>
  </Symbols>
</Root>
"""
            _write_text(tpy, xml)

            opt = ConvertOptions(recurse=True, recurse_array=True)
            conv = TpyToCsvConverter(opt)

            logs = []

            def log(s: str) -> None:
                logs.append(s)

            def cancel() -> bool:
                return False

            def progress(p: int) -> None:
                pass

            written = conv.convert_one(tpy, out, log=log, cancel_requested=cancel, progress=progress)
            self.assertEqual(len(written), 1)
            self.assertTrue(out.exists())

            lines = out.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(lines), HEADER_LINES + 2)
            self.assertEqual(lines[0], HEADER_LINE_1)
            self.assertEqual(lines[1], "2")  # top row + subitem row

    def test_chunking_splits_files(self) -> None:
        with TemporaryDirectory() as td:
            td_path = Path(td)
            tpy = td_path / "arr.tpy"
            out = td_path / "arr.csv"

            xml = """<?xml version="1.0" encoding="utf-8"?>
<Root>
  <DataTypes></DataTypes>
  <Symbols>
    <Symbol>
      <Name>a</Name>
      <Type>ARRAY [0..3] OF INT</Type>
      <IGroup>1</IGroup>
      <IOffset>0</IOffset>
      <BitSize>64</BitSize>
    </Symbol>
  </Symbols>
</Root>
"""
            _write_text(tpy, xml)

            # max_total_lines_per_file=5 => max_data_rows_per_file=3
            opt = ConvertOptions(max_total_lines_per_file=5, recurse=True, recurse_array=True)
            conv = TpyToCsvConverter(opt)

            def log(_: str) -> None:
                pass

            def cancel() -> bool:
                return False

            def progress(_: int) -> None:
                pass

            written = conv.convert_one(tpy, out, log=log, cancel_requested=cancel, progress=progress)
            self.assertEqual(len(written), 2)
            self.assertTrue((td_path / "arr.csv").exists())
            self.assertTrue((td_path / "arr_2.csv").exists())


if __name__ == "__main__":
    unittest.main()
