
import xml.etree.ElementTree as ET
import csv
import re
import sys
from pathlib import Path

# ---------- CLI / Konfiguration ----------
# Syntax:
#   python convert_tpy_csv.py [--no-recurse] [--no-array-recurse] [--only <file>] [--skip <file>] <Eingabe.tpy> <Ausgabe.csv>
args = sys.argv[1:]
RECURSE = True              # rekursive Entfaltung von UDTs (STRUCT/FB) aus Top-Symbolen
RECURSE_ARRAY = True        # rekursive Entfaltung in ARRAY-Elementen, wenn Elementtyp UDT ist
ONLY_FILE = None            # Pfad zu Whitelist-Datei (Regex je Zeile)
SKIP_FILE = None            # Pfad zu Blacklist-Datei (Regex je Zeile)
paths = []

i = 0
while i < len(args):
    a = args[i]
    if a == '--no-recurse':
        RECURSE = False
        RECURSE_ARRAY = False
        i += 1
    elif a == '--no-array-recurse':
        RECURSE_ARRAY = False
        i += 1
    elif a == '--only' and i+1 < len(args):
        ONLY_FILE = args[i+1]; i += 2
    elif a == '--skip' and i+1 < len(args):
        SKIP_FILE = args[i+1]; i += 2
    else:
        paths.append(a); i += 1

input_file = paths[0] if len(paths) > 0 else '/mnt/data/Plc.tpy'
output_file = paths[1] if len(paths) > 1 else '/mnt/data/output.csv'

# Maximale Zeilen pro Datei (inkl. 2 Headerzeilen)
MAX_TOTAL_LINES_PER_FILE = 1_670_000
HEADER_LINES = 2
MAX_DATA_ROWS_PER_FILE = MAX_TOTAL_LINES_PER_FILE - HEADER_LINES  # = 1_669_998

# ---------- Typ-/Regex-Hilfen ----------
ARRAY_RE = re.compile(r'^(?:.*)?\s*ARRAY\s*\[(\d+)\s*\.\.\s*(\d+)\]\s*OF\s*(.+)$', re.IGNORECASE)
STRING_RE = re.compile(r'^(W?STRING)\s*\(\s*(\d+)\s*\)$', re.IGNORECASE)

# Primitive Typgrößen (Bit); BOOL in Arrays byte-aligned = 8 Bit
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

# ---------- Whitelist/Blacklist laden ----------
def load_regex_file(path):
    pats = []
    if not path:
        return pats
    p = Path(path)
    if not p.exists():
        print(f"Warnung: Datei nicht gefunden: {path}. Ignoriere.", file=sys.stderr)
        return pats
    for line in p.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#') or s.startswith(';') or s.startswith('//'):
            continue
        try:
            pats.append(re.compile(s))
        except re.error as ex:
            print(f"Warnung: ungültiges Regex in {path}: {s!r} -> {ex}", file=sys.stderr)
    return pats

ONLY_PATS = load_regex_file(ONLY_FILE)
SKIP_PATS = load_regex_file(SKIP_FILE)

def matches_any(name: str, patterns) -> bool:
    for pat in patterns:
        if pat.search(name):
            return True
    return False

def allowed_udt(name: str) -> bool:
    """Whitelist/Blacklist-Regeln anwenden.
       - Wenn ONLY_PATS vorhanden: nur UDTs zulassen, die irgendeinem ONLY-Pattern entsprechen.
       - Danach ggf. via SKIP_PATS ausschließen.
    """
    if name is None:
        return False
    if ONLY_PATS:
        if not matches_any(name, ONLY_PATS):
            return False
    if SKIP_PATS and matches_any(name, SKIP_PATS):
        return False
    return True

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
    if child.startswith(parent + "."):
        return child
    return f"{parent}.{child}" if child else parent

# ---------- CSV sammeln ----------
rows = []
rows.append(['IGroup','IOffset','Name','Comment','Type','BitSize','BitOffs','DefaultValue','ActualAddress'])

def emit_row(igroup, io, name, comment, typ, bits, bitoffs, default, actual):
    rows.append([igroup, io, name, comment, typ, bits, bitoffs, default, actual])

def expand_struct_recursive(parent_name: str, parent_base_addr: int, parent_abs_bitoffs: int, igroup: str, dtype_name: str, allow_recurse: bool):
    """Entfaltet SubItems von dtype_name. Absolute BitOffs = parent_abs_bitoffs + si_boffs.
       allow_recurse steuert, ob weitere Verschachtelungen erlaubt sind (Top vs. Array)."""
    dt = datatype_by_name.get(dtype_name)
    if dt is None:
        return
    for si in dt.findall('SubItem'):
        si_name  = text(si, 'Name')
        si_type  = text(si, 'Type')
        si_bits  = int(text(si, 'BitSize', '0') or 0)
        si_boffs = int(text(si, 'BitOffs', '0') or 0)  # relativ zum dtype

        default_v = ''
        de = si.find('Default/Value')
        if de is not None and de.text:
            default_v = de.text

        abs_bitoffs = parent_abs_bitoffs + si_boffs
        actual_addr = parent_base_addr + (abs_bitoffs // 8)
        qual_name   = qualify(parent_name, si_name)

        # Für STRUCT/UDT-SubItems: IOffset == ActualAddress
        emit_row(igroup, actual_addr, qual_name, '', si_type, si_bits, abs_bitoffs, default_v, actual_addr)

        # Rekursiv weiter, wenn erlaubt und der SubItem-Typ wiederum ein DataType ist
        if allow_recurse and (si_type in datatype_by_name) and allowed_udt(si_type):
            expand_struct_recursive(qual_name, parent_base_addr, abs_bitoffs, igroup, si_type, allow_recurse)

for sym in root.findall('.//Symbol'):
    name     = text(sym, 'Name')
    type_    = text(sym, 'Type')
    igroup   = text(sym, 'IGroup')
    ioffset  = int(text(sym, 'IOffset', '0') or 0)
    bitsize  = int(text(sym, 'BitSize', '0') or 0)
    comment  = limit_comment(text(sym, 'Comment', ''))

    # Top-Zeile
    emit_row(igroup, ioffset, name, comment, type_, bitsize, '', '', ioffset)

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
                emit_row(igroup, actual_addr, item_name, '', elem_type, per_bits, elem_boffs, '', actual_addr)

                # Rekursive Entfaltung für ARRAY-UDTs (falls Elementtyp ein DataType ist)
                if RECURSE_ARRAY and (elem_type in datatype_by_name) and allowed_udt(elem_type):
                    expand_struct_recursive(item_name, base_addr, elem_boffs, igroup, elem_type, allow_recurse=True)
        continue

    # STRUCT/UDT (SubItems) – inkl. Rekursion in verschachtelte UDTs
    if type_ in datatype_by_name:
        if RECURSE and allowed_udt(type_):
            expand_struct_recursive(name, ioffset, 0, igroup, type_, allow_recurse=True)
        else:
            # Nur die erste Ebene ohne Rekursion (oder wenn gefiltert)
            dt = datatype_by_name[type_]
            base_addr = ioffset
            for si in dt.findall('SubItem'):
                si_name  = text(si, 'Name')
                si_type  = text(si, 'Type')
                si_bits  = int(text(si, 'BitSize', '0') or 0)
                si_boffs = int(text(si, 'BitOffs', '0') or 0)
                default_v = ''
                de = si.find('Default/Value')
                if de is not None and de.text:
                    default_v = de.text
                abs_bitoffs = si_boffs
                actual_addr = base_addr + (abs_bitoffs // 8)
                qual_name   = qualify(name, si_name)
                emit_row(igroup, actual_addr, qual_name, '', si_type, si_bits, abs_bitoffs, default_v, actual_addr)

# ---------- Schreiben mit Chunking ----------
data_rows = rows[1:]
total = len(data_rows)

if total <= MAX_DATA_ROWS_PER_FILE:
    write_chunk(part_filename(output_file, 0), data_rows)
else:
    part = 0
    start = 0
    while start < total:
        end = min(start + MAX_DATA_ROWS_PER_FILE, total)
        chunk = data_rows[start:end]
        write_chunk(part_filename(output_file, part), chunk)
        part += 1
        start = end

print("Fertig. RECURSE =", RECURSE, "| RECURSE_ARRAY =", RECURSE_ARRAY,
      "| ONLY_FILE =", ONLY_FILE, "| SKIP_FILE =", SKIP_FILE)
