# convert\_tpy\_csv – README

Konvertiert eine **Beckhoff TwinCAT .tpy** in eine CSV im Format des **SPS‑Analyzer 6** (TwinCAT‑Modul), inkl. Entfaltung von **ARRAYs** und **STRUCT/UDT‑SubItems**.

---

## TL;DR

```bash
python convert_tpy_csv.py [--no-recurse] <Eingabe.tpy> <Ausgabe.csv>
```

* **Header** wie vom SPS‑Analyzer erwartet:

  1. `Beckhoff TwinCat V2-PLC-Symbolfile`
  2. Anzahl der Datensätze
  3. Ab Zeile 3: Datensätze (Semikolon‑separiert)
* **Großdateien** werden automatisch in Teile gesplittet (max. **1 670 000 Gesamtzeilen** je Datei, inkl. Header).
* **Rekursive Entfaltung** von verschachtelten UDTs/FBs ist **standardmäßig aktiv** (siehe unten). Mit `--no-recurse` kann sie deaktiviert werden.
* **Header** wie vom SPS‑Analyzer erwartet:

  1. `Beckhoff TwinCat V2-PLC-Symbolfile`
  2. Anzahl der Datensätze
  3. Ab Zeile 3: Datensätze (Semikolon‑separiert)
* **Großdateien** werden automatisch in Teile gesplittet (max. **1 670 000 Gesamtzeilen** je Datei, inkl. Header).

---

## Voraussetzungen

* **Python ≥ 3.10** (wegen `int | None` Type‑Hints). Getestet mit **3.13**.
* Keine externen Abhängigkeiten. Nur Python‑Standardbibliothek (`xml.etree.ElementTree`, `csv`, `re`, `pathlib`, `sys`).

---

## Aufruf / Parameter

```bash
python convert_tpy_csv.py [--no-recurse] <Eingabe.tpy> <Ausgabe.csv>
```

**Optionales Flag:**

* `--no-recurse` → schaltet die rekursive Entfaltung verschachtelter UDTs/Funktionsbausteine aus.

**Beispiele (Windows CMD):**

```bat
REM absolut
python convert_tpy_csv.py C:\Projekte\TwinCAT\Plc.tpy C:\Export\output.csv

REM relativ (aus C:\Projekte)
python convert_tpy_csv.py TwinCAT\Plc.tpy Export\output.csv

REM ohne Rekursion
python convert_tpy_csv.py --no-recurse TwinCAT\Plc.tpy Export\output.csv
```

> Achtung: `\tpy\Plc.tpy` (führender Backslash) wird als UNC‑Pfad interpretiert und führt zu *FileNotFoundError*. Entweder **relativ ohne führenden Backslash** oder **absolut** angeben.

**Standardwerte (nur als Fallback in dev/test):**

* Eingabe: `/mnt/data/Plc.tpy`
* Ausgabe: `/mnt/data/output.csv`

---

## Ausgabeformat (CSV)

**Spaltenreihenfolge:**

```
IGroup; IOffset; Name; Comment; Type; BitSize; BitOffs; DefaultValue; ActualAddress
```

**Header:**

```
Beckhoff TwinCat V2-PLC-Symbolfile
<Anzahl_Datensätze>
<Datensätze …>
```

### Semantik der Spalten

* **IGroup**: wie in der .tpy
* **IOffset**:

  * **ARRAY‑Elemente:** = **ActualAddress** des Elements
  * **STRUCT/UDT‑SubItems:** = **ActualAddress** des SubItems
  * **Top‑Symbolzeilen:** = Basisadresse des Symbols
* **Name**:

  * **Top‑Symbol:** Original‑Name aus .tpy
  * **ARRAY‑Element:** `Name[index]`
  * **STRUCT/UDT‑SubItem:** **qualifizierter Name** `Parent.SubItem` (z. B. `prgMain.tonTempDaten2.IN`)
* **Comment**: gekürzt auf 200 Zeichen, ohne Zeilenumbrüche
* **Type**: Datentyp (inkl. `ARRAY [...] OF …`)
* **BitSize**: Bitgröße des Elements (s. Auflösung unten)
* **BitOffs**: Bit‑Offset **relativ zur Basis** (ARRAY‑Basis bzw. STRUCT‑Parent)
* **DefaultValue**: falls im `<Default><Value>` vorhanden
* **ActualAddress**: `Basisadresse + (BitOffs // 8)`

---

## Entfaltungs‑/Adressierungsregeln

### Rekursive Entfaltung (Standard: EIN)

* **Was:** SubItems, deren **Type** wiederum ein `<DataType>` ist (UDT/FB, z. B. `Tc2_Standard.R_TRIG`, `Tc2_Standard.TON`, `Tc2_MC2.*`, `TC3_UniLib.*`), werden **weiter entfaltet**.
* **Name:** bei jedem Schritt vollständig qualifiziert (`Parent.SubItem[.SubSubItem…]`).
* **Offset/Adresse:** absolute `BitOffs` wird kumuliert (Summe der relativen Offsets); `ActualAddress = Basis + (BitOffs // 8)`; `IOffset = ActualAddress`.
* **Deaktivieren:** per Flag `--no-recurse`.

### Top‑Symbol

```
IGroup; IOffset=basis; Name; …; BitOffs=""; ActualAddress=basis
```

### ARRAY

* **Basisadresse** = `IOffset` aus Top‑Symbol
* **Element‑Name** = `Name[index]`
* **BitOffs (Element)** = `(index - start) * per_element_bits`
* **ActualAddress (Element)** = `Basis + (BitOffs // 8)`
* **IOffset (Element)** = **ActualAddress (Element)**

### STRUCT / UDT (SubItems)

* **Basisadresse** = `IOffset` aus Top‑Symbol
* **SubItem‑Name** = `Parent.SubItem`
* **ActualAddress (SubItem)** = `Basis + (BitOffs // 8)`
* **IOffset (SubItem)** = **ActualAddress (SubItem)**

---

## Größenauflösung (BitSize je Element)

Reihenfolge der Ermittlung (erste zutreffende Regel gewinnt):

1. **Primitive** (`PRIM_BITS`): `BOOL, BYTE, SINT, USINT, WORD, INT, UINT, DWORD, DINT, UDINT, REAL, LWORD, LINT, ULINT, LREAL`
2. **STRING/WSTRING**: `STRING(n)` → `(n+1) * 8` Bit; `WSTRING(n)` → `(n+1) * 16` Bit
3. **Zeit/Datum** (`SPECIAL_BITS`): z. B. `TIME: 32`, `DATE_AND_TIME: 32`, `LTIME: 64`, …
4. **UDT/Funktionsbausteine aus `<DataTypes>`**: nutzt `<BitSize>` des passenden `<DataType>`
5. **Fallback**: `symbol_bitsize / element_count`, mindestens **8 Bit**

Damit werden u. a. korrekt behandelt:

* **Tc2\_Standard**: `TON`, `R_TRIG` (über `<DataTypes>`)
* **Tc2\_MC2.\*:** `ST_McOutputs`, `AXIS_REF`, `MC_ReadParameter`, `MC_MoveAbsolute/Velocity/Modulo`, …
* **TC3\_UniLib.\*:** `ST_UniBaustein`, `ST_NcAchsen`, `FB_UniWkzgAnstg`, …

---

## Multi‑File‑Output (Chunking)

* Max. **1 670 000 Gesamtzeilen pro Datei** (inkl. 2 Headerzeilen) → **1 669 998 Datensätze** je Datei.
* Erste Datei heißt wie angegeben (z. B. `output.csv`).
* Folge‑Dateien: `output_2.csv`, `output_3.csv`, … (Zeile 2 enthält dort jeweils die **Teil‑Anzahl** der Datensätze).

**Konstanten im Script:**

```python
MAX_TOTAL_LINES_PER_FILE = 1_670_000
HEADER_LINES = 2
```

---

## Beispiele

### ARRAY (BOOL)

```
61472;51520300;.arrTwinSafeGroupOtherError;;ARRAY [1..5] OF BOOL;40;;;51520300
61472;51520300;.arrTwinSafeGroupOtherError[1];;BOOL;8;0;;51520300
61472;51520301;.arrTwinSafeGroupOtherError[2];;BOOL;8;8;;51520301
61472;51520302;.arrTwinSafeGroupOtherError[3];;BOOL;8;16;;51520302
61472;51520303;.arrTwinSafeGroupOtherError[4];;BOOL;8;24;;51520303
61472;51520304;.arrTwinSafeGroupOtherError[5];;BOOL;8;32;;51520304
```

### STRUCT/UDT – qualifizierte SubItems (`Tc2_Standard.TON`)

```
16448;777600;prgMain.tonTempDaten2;;Tc2_Standard.TON;256;;;777600
16448;777608;prgMain.tonTempDaten2.IN;;BOOL;8;64;;777608
16448;777612;prgMain.tonTempDaten2.PT;;TIME;32;96;;777612
16448;777616;prgMain.tonTempDaten2.Q;;BOOL;8;128;;777616
16448;777620;prgMain.tonTempDaten2.ET;;TIME;32;160;;777620
16448;777624;prgMain.tonTempDaten2.M;;BOOL;8;192;;777624
16448;777628;prgMain.tonTempDaten2.StartTime;;TIME;32;224;;777628
```

---

## Fehlerbehebung

* **FileNotFoundError**: In Windows kein führender Backslash (UNC). Pfad absolut oder relativ angeben, z. B. `tpy\Plc.tpy` statt `\tpy\Plc.tpy`.
* **Falsche IOffset‑Werte**: Prüfe, ob der Fall **ARRAY** (Element → `IOffset=ActualAddress`) oder **STRUCT** (SubItem → `IOffset=ActualAddress`) ist. Top‑Symbolzeilen behalten die Basisadresse.
* **Sondertypen fehlen**: Ergänze bei Bedarf `PRIM_BITS`/`SPECIAL_BITS`. UDTs werden i. d. R. über `<DataTypes>` automatisch erkannt.
* **Excel‑Kompatibilität**: Standard‑Encoding ist `UTF‑8`. Falls nötig, Ausgabe auf `cp1252` ändern.

---

## Anpassungspunkte im Code

* **Typgrößen**: `PRIM_BITS`, `SPECIAL_BITS`
* **Chunk‑Größe**: `MAX_TOTAL_LINES_PER_FILE`, `HEADER_LINES`
* **Kommentar‑Länge**: in `limit_comment()`

---

## Lizenz / Autor

Interner Projekt‑Helper; keine externe Lizenzangabe erforderlich. Änderungen nach Bedarf.
