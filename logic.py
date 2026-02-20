# logic.py
import json
import math
import os
import datetime
from fpdf import FPDF
from functools import lru_cache

DB_FILE = "database.json"

# ─────────────────────────────────────────────────────────────────────────────
# UNICODE → LATIN-1 SAFE SUBSTITUTION MAP
# Covers the most common characters that crash fpdf's Latin-1 encoder.
# ─────────────────────────────────────────────────────────────────────────────
_UNICODE_MAP = {
    '\u2014': '--',    # em dash            —
    '\u2013': '-',     # en dash            –
    '\u2018': "'",     # left single quote  '
    '\u2019': "'",     # right single quote '  (also apostrophe)
    '\u201C': '"',     # left double quote  "
    '\u201D': '"',     # right double quote "
    '\u2026': '...',   # ellipsis           …
    '\u00B0': ' deg',  # degree sign        °
    '\u00B5': 'u',     # micro sign         µ  (in µS/cm)
    '\u2265': '>=',    # greater or equal   ≥
    '\u2264': '<=',    # less or equal      ≤
    '\u00D7': 'x',     # multiplication     ×
    '\u00B1': '+/-',   # plus-minus         ±
    '\u00AE': '(R)',   # registered         ®
    '\u2122': '(TM)',  # trademark          ™
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_data():
    """
    Load and cache the parameters list from database.json.
    Supports both the old flat-list format and the new
    {"_metadata": ..., "parameters": [...]} format.
    Call load_data.cache_clear() if you hot-reload the DB at runtime.
    """
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        if isinstance(payload, list):
            return payload
        return payload.get("parameters", [])
    except FileNotFoundError:
        return []


def get_db_version():
    """Return a human-readable DB version + date string for display in reports."""
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        meta = payload.get("_metadata", {})
        version     = meta.get("db_version")
        last_update = meta.get("last_updated")
        # Only return version info if both fields exist
        if version and last_update:
            return f"v{version} (updated {last_update})"
        return ""
    except Exception:
        return ""


def get_parameter_names():
    """Return a sorted list of parameter names for UI dropdowns."""
    return sorted([item["name"] for item in load_data()])


def sanitize(text):
    """
    Safely encode text for fpdf, which uses Latin-1 internally.

    Strategy (in order):
      1. Replace known problematic Unicode characters with ASCII equivalents
         using _UNICODE_MAP — prevents the most common encoder crashes.
      2. Encode to Latin-1 with 'replace' so any remaining unknown characters
         appear as '?' in the PDF instead of crashing the generator.
    """
    if isinstance(text, (int, float)):
        return str(text)

    text = str(text)

    # Step 1: targeted safe substitutions
    for char, replacement in _UNICODE_MAP.items():
        text = text.replace(char, replacement)

    # Step 2: catch-all — any still-unhandled non-Latin-1 chars become '?'
    return text.encode('latin-1', 'replace').decode('latin-1')


def safe_output_path(directory, filename):
    """
    Return an absolute path for a PDF output file.
    Creates the output directory if it does not exist.
    Using abspath ensures send_file() in Flask always gets a valid path
    regardless of process working directory.
    """
    os.makedirs(directory, exist_ok=True)
    return os.path.abspath(os.path.join(directory, filename))


# ─────────────────────────────────────────────────────────────────────────────
# INPUT VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_batch(batch_data):
    """
    Validate a list of {"name": str, "value": any} dicts before analysis.

    Checks performed per entry:
      1. Value is present and non-empty.
      2. Value is coercible to float.
      3. Value is a finite real number (not NaN or Inf).
      4. Value falls within the physical min/max bounds defined in the DB.

    Returns:
        errors  (list[str]): Human-readable messages. Empty list = all clear.
        cleaned (list[dict]): Valid entries with value coerced to float.
    """
    db        = load_data()
    param_map = {item["name"]: item for item in db}
    errors    = []
    cleaned   = []

    for item in batch_data:
        name = item.get("name", "Unknown Parameter")
        raw  = item.get("value")

        # 1. Presence check
        if raw is None or str(raw).strip() == "":
            errors.append(f"'{name}': No value entered.")
            continue

        # 2. Numeric type check
        try:
            value = float(raw)
        except (ValueError, TypeError):
            errors.append(f"'{name}': '{raw}' is not a valid number.")
            continue

        # 3. Finite number check
        if math.isnan(value) or math.isinf(value):
            errors.append(f"'{name}': Value must be a finite real number.")
            continue

        # 4. Physical bounds check (sourced from DB)
        # Keep parameter object for context (units etc.) but do not
        # reject values that fall outside the DB's physical_min/physical_max.
        # This change allows analysis to run for any numeric input while
        # preserving other validation (presence, numeric, finite).
        param_obj = param_map.get(name)
        cleaned.append({"name": name, "value": value})

    return errors, cleaned


# ─────────────────────────────────────────────────────────────────────────────
# PURE ANALYSIS ENGINE  (no UI or PDF concerns here)
# ─────────────────────────────────────────────────────────────────────────────

def run_analysis(batch_data):
    """
    Core compliance engine. Accepts validated batch data, returns structured results.
    Does NOT touch the UI or PDF — those are separate concerns.

    Returns:
        results  (list[dict]): One dict per parameter with full compliance detail.
        warnings (list[str]): Parameters skipped because they weren't found in the DB.
    """
    db       = load_data()
    results  = []
    warnings = []

    for item in batch_data:
        p_name = item['name']

        # Defensive float cast (validation should have caught bad values upstream)
        try:
            val = float(item['value'])
        except (ValueError, TypeError):
            warnings.append(f"'{p_name}': Could not parse value -- skipped.")
            continue

        param_obj = next((x for x in db if x["name"] == p_name), None)

        # Warn on unknown parameters rather than silently skipping
        if not param_obj:
            warnings.append(
                f"'{p_name}': Not found in standards database -- skipped. "
                f"Check spelling or update database.json."
            )
            continue

        standards_results = []

        for std in param_obj['standards']:
            authority     = std['authority']
            standard_date = std.get('standard_date', 'date unknown')
            limit_max     = std.get('max_limit')
            limit_min     = std.get('min_limit')

            is_unsafe     = False
            violation_txt = ""

            if limit_max is not None and val > limit_max:
                is_unsafe     = True
                violation_txt = f"> {limit_max}"

            # FIX: use `is not None` — catches limit_min == 0 correctly
            if limit_min is not None and val < limit_min:
                is_unsafe     = True
                violation_txt = f"< {limit_min}"

            # Build limit display string — FIX: plain hyphen avoids em/en-dash encoding crash
            if limit_min is not None and limit_max is not None:
                limit_str = f"{limit_min} - {limit_max}"
            elif limit_max is not None:
                limit_str = f"Max {limit_max}"
            elif limit_min is not None:
                limit_str = f"Min {limit_min}"
            else:
                limit_str = "No numeric limit"

            if is_unsafe:
                entry = {
                    "authority":     authority,
                    "standard_date": standard_date,
                    "status":        "FAIL",
                    "limit":         limit_str,
                    "violation":     violation_txt,
                    "consequence":   std['consequence'],
                    "solution":      std['solution'],
                    "color":         (200, 0, 0),
                    "symbol":        "7",
                }
            elif limit_max is None and limit_min is None:
                entry = {
                    "authority":     authority,
                    "standard_date": standard_date,
                    "status":        "INFO",
                    "limit":         limit_str,
                    "color":         (0, 0, 200),
                    "symbol":        "s",
                }
            else:
                entry = {
                    "authority":     authority,
                    "standard_date": standard_date,
                    "status":        "PASS",
                    "limit":         limit_str,
                    "color":         (0, 150, 0),
                    "symbol":        "3",
                }

            standards_results.append(entry)

        results.append({
            "parameter": p_name,
            "value":     val,
            "unit":      param_obj['unit'],
            "standards": standards_results,
        })

    return results, warnings


# ─────────────────────────────────────────────────────────────────────────────
# GUI TEXT RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def build_gui_output(results, warnings):
    """
    Convert structured analysis results into a flat list of (tag, text) tuples
    for the frontend/UI to render with appropriate styling.
    """
    gui = []
    gui.append(("HEADER", "COMPREHENSIVE ANALYSIS REPORT"))
    gui.append(("NORMAL", f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    gui.append(("NORMAL", f"Standards database: {get_db_version()}"))
    gui.append(("NORMAL", "=" * 60))

    for w in warnings:
        gui.append(("WARNING", f"WARNING: {w}"))

    for res in results:
        gui.append(("SUBHEADER", f">> {res['parameter']}  ({res['value']} {res['unit']})"))

        for std in res['standards']:
            date_label = f" [standard dated {std['standard_date']}]"
            if std['status'] == "FAIL":
                gui.append(("FAIL",   f"   FAIL  [{std['authority']}{date_label}]  {std['violation']}  (Limit: {std['limit']})"))
                gui.append(("NORMAL", f"         Consequence: {std['consequence']}"))
                gui.append(("NORMAL", f"         Solution:    {std['solution']}"))
            elif std['status'] == "INFO":
                gui.append(("INFO",   f"   INFO  [{std['authority']}{date_label}]  {std['limit']}"))
            else:
                gui.append(("PASS",   f"   PASS  [{std['authority']}{date_label}]  (Limit: {std['limit']})"))

        gui.append(("NORMAL", "-" * 40))

    return gui


# ─────────────────────────────────────────────────────────────────────────────
# PDF RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def save_comprehensive_pdf(results, warnings, output_dir="reports"):
    """
    Render structured analysis results to a professional PDF report.

    All text is passed through sanitize() before being written to PDF,
    which handles Unicode characters that fpdf's Latin-1 engine cannot encode.

    Returns:
        filepath (str): Absolute path to the generated PDF file.
    """
    pdf = FPDF()
    pdf.add_page()

    # ── Title block ───────────────────────────────────────────────────────────
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Comprehensive Water Quality Report", ln=True, align='C')

    pdf.set_font("Arial", 'I', 9)
    pdf.cell(0, 6, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True, align='C')
    pdf.cell(0, 6, sanitize(f"Standards database: {get_db_version()}"), ln=True, align='C')
    pdf.ln(6)

    # ── Warnings block ────────────────────────────────────────────────────────
    if warnings:
        pdf.set_font("Arial", 'B', 11)
        pdf.set_text_color(180, 100, 0)
        pdf.cell(0, 8, "NOTICES:", ln=True)
        pdf.set_font("Arial", '', 9)
        for w in warnings:
            pdf.multi_cell(0, 5, sanitize(f"  - {w}"))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    # ── Summary table ─────────────────────────────────────────────────────────
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. SUMMARY OF RESULTS", ln=True)

    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(65, 8, "Parameter",       1, 0, 'L', True)
    pdf.cell(40, 8, "Value",           1, 0, 'C', True)
    pdf.cell(85, 8, "Overall Status",  1, 1, 'L', True)

    pdf.set_font("Arial", '', 10)
    for res in results:
        overall = "UNSAFE" if any(s['status'] == "FAIL" for s in res['standards']) else "SAFE"
        label   = f"{res['value']} {res['unit']}"

        pdf.cell(65, 8, sanitize(res['parameter']), 1)
        pdf.cell(40, 8, sanitize(label), 1, 0, 'C')

        if overall == "UNSAFE":
            pdf.set_text_color(200, 0, 0)
            pdf.cell(85, 8, "FLAGGED -- see details below", 1, 1)
        else:
            pdf.set_text_color(0, 150, 0)
            pdf.cell(85, 8, "PASSED ALL STANDARDS", 1, 1)
        pdf.set_text_color(0, 0, 0)

    pdf.ln(8)

    # ── Detailed breakdown ────────────────────────────────────────────────────
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. DETAILED ANALYSIS & SOLUTIONS", ln=True)

    for res in results:
        pdf.set_font("Arial", 'B', 11)
        pdf.set_text_color(200, 150, 0)
        pdf.cell(0, 8, sanitize(f"  {res['parameter']}  (Result: {res['value']} {res['unit']})"), ln=True)
        pdf.set_text_color(0, 0, 0)

        for std in res['standards']:
            r, g, b = std['color']

            # Authority line with standard date
            pdf.set_text_color(r, g, b)
            pdf.set_font("Arial", 'B', 10)
            status_line = sanitize(
                f"    [{std['authority']}]  {std['status']}  --  Limit: {std['limit']}"
                f"  (Standard dated: {std['standard_date']})"
            )
            if std['status'] == "FAIL":
                status_line = sanitize(status_line + f"  Violation: {std['violation']}")
            pdf.cell(0, 6, status_line, ln=True)

            # Consequence and solution for failures
            pdf.set_text_color(50, 50, 50)
            pdf.set_font("Arial", '', 10)
            if std['status'] == "FAIL":
                pdf.multi_cell(0, 5, sanitize(f"        Risk:     {std['consequence']}"))
                pdf.multi_cell(0, 5, sanitize(f"        Solution: {std['solution']}"))
                pdf.ln(2)

        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(120, 120, 120)
    # Use multi_cell so long footer text wraps instead of being clipped.
    footer_text = sanitize(
        "Report generated by Water Quality Compliance Suite  |  "
        "Standards: WHO GDWQ 4th Ed. (2022) & NIS 554:2015 (SON)  |  "
        "Always verify against the latest published standards."
    )
    pdf.multi_cell(0, 5, footer_text, align='C')

    # ── Save with full timestamp to prevent filename collisions ───────────────
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename  = f"Analysis_Report_{timestamp}.pdf"
    filepath  = safe_output_path(output_dir, filename)
    pdf.output(filepath)
    return filepath


def generate_comprehensive_pdf_bytes(results, warnings):
    """Render structured analysis results and return PDF bytes (no disk writes).

    This function mirrors save_comprehensive_pdf but returns the PDF
    as bytes so the calling code can stream it directly to the user
    without persisting it on the server.
    """
    pdf = FPDF()
    pdf.add_page()

    # ── Title block ───────────────────────────────────────────────────────────
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Comprehensive Water Quality Report", ln=True, align='C')

    pdf.set_font("Arial", 'I', 9)
    pdf.cell(0, 6, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True, align='C')
    pdf.cell(0, 6, sanitize(f"Standards database: {get_db_version()}"), ln=True, align='C')
    pdf.ln(6)

    # ── Warnings block ────────────────────────────────────────────────────────
    if warnings:
        pdf.set_font("Arial", 'B', 11)
        pdf.set_text_color(180, 100, 0)
        pdf.cell(0, 8, "NOTICES:", ln=True)
        pdf.set_font("Arial", '', 9)
        for w in warnings:
            pdf.multi_cell(0, 5, sanitize(f"  - {w}"))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    # ── Summary table ─────────────────────────────────────────────────────────
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. SUMMARY OF RESULTS", ln=True)

    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(65, 8, "Parameter",       1, 0, 'L', True)
    pdf.cell(40, 8, "Value",           1, 0, 'C', True)
    pdf.cell(85, 8, "Overall Status",  1, 1, 'L', True)

    pdf.set_font("Arial", '', 10)
    for res in results:
        overall = "UNSAFE" if any(s['status'] == "FAIL" for s in res['standards']) else "SAFE"
        label   = f"{res['value']} {res['unit']}"

        pdf.cell(65, 8, sanitize(res['parameter']), 1)
        pdf.cell(40, 8, sanitize(label), 1, 0, 'C')

        if overall == "UNSAFE":
            pdf.set_text_color(200, 0, 0)
            pdf.cell(85, 8, "FLAGGED -- see details below", 1, 1)
        else:
            pdf.set_text_color(0, 150, 0)
            pdf.cell(85, 8, "PASSED ALL STANDARDS", 1, 1)
        pdf.set_text_color(0, 0, 0)

    pdf.ln(8)

    # ── Detailed breakdown ────────────────────────────────────────────────────
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. DETAILED ANALYSIS & SOLUTIONS", ln=True)

    for res in results:
        pdf.set_font("Arial", 'B', 11)
        pdf.set_text_color(200, 150, 0)
        pdf.cell(0, 8, sanitize(f"  {res['parameter']}  (Result: {res['value']} {res['unit']})"), ln=True)
        pdf.set_text_color(0, 0, 0)

        for std in res['standards']:
            r, g, b = std['color']

            # Authority line with standard date
            pdf.set_text_color(r, g, b)
            pdf.set_font("Arial", 'B', 10)
            status_line = sanitize(
                f"    [{std['authority']}]  {std['status']}  --  Limit: {std['limit']}"
                f"  (Standard dated: {std['standard_date']})"
            )
            if std['status'] == "FAIL":
                status_line = sanitize(status_line + f"  Violation: {std['violation']}")
            pdf.cell(0, 6, status_line, ln=True)

            # Consequence and solution for failures
            pdf.set_text_color(50, 50, 50)
            pdf.set_font("Arial", '', 10)
            if std['status'] == "FAIL":
                pdf.multi_cell(0, 5, sanitize(f"        Risk:     {std['consequence']}"))
                pdf.multi_cell(0, 5, sanitize(f"        Solution: {std['solution']}"))
                pdf.ln(2)

        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(120, 120, 120)
    footer_text = sanitize(
        "Report generated by Water Quality Compliance Suite  |  "
        "Standards: WHO GDWQ 4th Ed. (2022) & NIS 554:2015 (SON)  |  "
        "Always verify against the latest published standards."
    )
    pdf.multi_cell(0, 5, footer_text, align='C')

    # Return PDF bytes instead of writing to disk
    raw = pdf.output(dest='S')
    # FPDF returns a str for 'S' output — encode to latin-1 to preserve characters
    if isinstance(raw, str):
        raw = raw.encode('latin-1')
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT  (called by app.py)
# ─────────────────────────────────────────────────────────────────────────────

def analyze_batch(batch_data, output_dir="reports"):
    """
    Main entry point for app.py.

    Workflow:
      1. Validate inputs         -- returns errors immediately if any are invalid.
      2. Run pure analysis       -- structured results + skip warnings.
      3. Build GUI text output   -- list of (tag, text) tuples for the UI.

    Returns:
        gui_text    (list): (tag, text) tuples for the UI to render.
        pdf_results (list): Structured result dicts for save_comprehensive_pdf().
        val_errors  (list): Validation error strings. Empty = all inputs valid.
        warnings    (list): Skipped-parameter notices.
    """
    val_errors, cleaned = validate_batch(batch_data)

    if val_errors:
        return [], [], val_errors, []

    results, warnings = run_analysis(cleaned)
    gui_text          = build_gui_output(results, warnings)

    return gui_text, results, [], warnings
