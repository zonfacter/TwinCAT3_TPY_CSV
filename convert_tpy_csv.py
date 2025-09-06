
import xml.etree.ElementTree as ET
import csv
import re
import sys
from pathlib import Path

# ---------- Konfiguration ----------
input_file = sys.argv[1] if len(sys.argv) > 1 else '/mnt/data/Plc.tpy'
output_file = sys.argv[2] if len(sys.argv) > 2 else '/mnt/data/output.csv'

# Maximale Zeilen pro Datei (inkl. der 2 Headerzeilen)
MAX_TOTAL_LINES_PER_FILE = 1_670_000
HEADER_LINES = 2
MAX_DATA_ROWS_PER_FILE = MAX_TOTAL_LINES_PER_FILE - HEADER_LINES  # = 1_669_998

# ---------- Typ-/Regex-Hilfen ----------
ARRAY_RE = re.compile(r'^(?:.*)?\s*ARRAY\s*\[(\d+)\s*\.\.\s*(\d+)\]\s*OF\s*(.+)$', re.IGNORECASE)
STRING_RE = re.compile(r'^(W?STRING)\s*\(\s*(\d+)\s*\)$', re.IGNORECASE)

# Grobe primitive Typgrößen (Bit); BOOL in Arrays byte-aligned = 8 Bit
PRIM_BITS = {
    'BOOL': 8, 'BYTE': 8, 'SINT': 8, 'USINT': 8,
    'WORD': 16, 'INT': 16, 'UINT': 16,
    'DWORD': 32, 'DINT': 32, 'UDINT': 32, 'REAL': 32,
    'LWORD': 64, 'LINT': 64, 'ULINT': 64, 'LREAL': 64,
}

# Zeit-/Datumstypen (TwinCAT)
SPECIAL_BITS = {
    'TIME': 32,
    'DATE_AND_TIME': 32,
    'DATE': 16,
    'TIME_OF_DAY': 32,
    'TOD': 32,
    'DT': 32,
    'LTIME': 64,
    'LDATE': 32,
}

def text(e, tag, default=''):
    n = e.find(tag)
    return n.text if n is not None and n.text is not None else default

def limit_comment(s):
    return (s or '')[:200].replace('\n',' ').replace('\r',' ')

def part_filename(base_path: str, part_index: int) -> str:
    p = Path(base_path)
    if part_index == 0:
        return str(p)
    return str(p.with_name(f"{p.stem}_{part_index+1}{p.suffix}"))

def write_chunk(filepath: str, data_rows):
    record_count = len(data_rows)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        f.write('Beckhoff TwinCat V2-PLC-Symbolfile\n')
        f.write(str(record_count) + '\n')
        w = csv.writer(f, delimiter=';', lineterminator='\n')
        w.writerows(data_rows)
    print(f"geschrieben: {filepath}  (Datensätze: {record_count}, Gesamtzeilen: {record_count + HEADER_LINES})")

# ---------- XML laden ----------
tree = ET.parse(input_file)
root = tree.getroot()

# DataType-Map
datatype_by_name = {}
datatype_bits = {}
for dt in root.findall('.//DataTypes/DataType'):
    dt_name = text(dt, 'Name')
    if dt_name:
        datatype_by_name[dt_name] = dt
        bs = text(dt, 'BitSize', '')
        try:
            datatype_bits[dt_name] = int(bs) if bs else 0
        except ValueError:
            datatype_bits[dt_name] = 0

def get_type_bits(type_name: str, symbol_bitsize: int | None = None, array_count: int | None = None) -> int:
    if not type_name:
        return 8
    base = type_name.strip()

    b = PRIM_BITS.get(base.upper())
    if b is not None:
        return b

    m = STRING_RE.match(base)
    if m:
        n = int(m.group(2))
        bytes_per_char = 2 if m.group(1).upper().startswith('W') else 1
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

def qualify(parent: str, child: str) -> str:
    child = child or ''
    parent = parent or ''
    if not parent:
        return child
    # Wenn child bereits mit parent. beginnt → ok
    if child.startswith(parent + "."):
        return child
    # Wenn child scheinbar schon voll qualifiziert ist (enthält einen Punkt), prüfen wir auf Duplikat
    # Trotzdem qualifizieren, um immer konsistent Parent.SubItem zu liefern
    return f"{parent}.{child}" if child else parent

# ---------- CSV sammeln ----------
rows = []
rows.append(['IGroup','IOffset','Name','Comment','Type','BitSize','BitOffs','DefaultValue','ActualAddress'])

for sym in root.findall('.//Symbol'):
    name     = text(sym, 'Name')
    type_    = text(sym, 'Type')
    igroup   = text(sym, 'IGroup')
    ioffset  = int(text(sym, 'IOffset', '0') or 0)
    bitsize  = int(text(sym, 'BitSize', '0') or 0)
    comment  = limit_comment(text(sym, 'Comment', ''))

    # Top-Zeile
    rows.append([igroup, ioffset, name, comment, type_, bitsize, '', '', ioffset])

    # ARRAY?
    m = ARRAY_RE.match(type_)
    if m:
        start = int(m.group(1)); end = int(m.group(2))
        elem_type = m.group(3).strip()
        count = end - start + 1 if end >= start else 0
        if count > 0:
            per_bits = get_type_bits(elem_type, symbol_bitsize=bitsize, array_count=count)
            base_addr = ioffset
            for idx in range(start, end + 1):
                elem_boffs  = (idx - start) * per_bits
                actual_addr = base_addr + (elem_boffs // 8)
                item_name = f"{name}[{idx}]"
                rows.append([igroup, actual_addr, item_name, '', elem_type, per_bits, elem_boffs, '', actual_addr])
        continue

    # STRUCT/UDT (SubItems)
    dt = datatype_by_name.get(type_)
    if dt is not None:
        base_addr = ioffset
        for si in dt.findall('SubItem'):
            si_name   = text(si, 'Name')
            si_type   = text(si, 'Type')
            si_bits   = int(text(si, 'BitSize', '0') or 0)
            si_boffs  = int(text(si, 'BitOffs', '0') or 0)

            # Default
            default_v = ''
            de = si.find('Default/Value')
            if de is not None and de.text:
                default_v = de.text

            actual_addr = base_addr + (si_boffs // 8)

            # SubItem-Namen IMMER mit Parent qualifizieren
            qual_name = qualify(name, si_name)

            rows.append([igroup, actual_addr, qual_name, '', si_type, si_bits, si_boffs, default_v, actual_addr])

# ---------- Schreiben mit Chunking ----------
data_rows = rows[1:]
total = len(data_rows)

def write_chunk_file(path, chunk_rows):
    record_count = len(chunk_rows)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        f.write('Beckhoff TwinCat V2-PLC-Symbolfile\n')
        f.write(str(record_count) + '\n')
        w = csv.writer(f, delimiter=';', lineterminator='\n')
        w.writerows(chunk_rows)
    print(f"geschrieben: {path}  (Datensätze: {record_count}, Gesamtzeilen: {record_count + HEADER_LINES})")

if total <= MAX_DATA_ROWS_PER_FILE:
    write_chunk_file(part_filename(output_file, 0), data_rows)
else:
    part = 0
    start = 0
    while start < total:
        end = min(start + MAX_DATA_ROWS_PER_FILE, total)
        chunk = data_rows[start:end]
        write_chunk_file(part_filename(output_file, part), chunk)
        part += 1
        start = end

print("Fertig.")
