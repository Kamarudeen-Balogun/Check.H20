# app.py
import os
import json
import datetime
from flask import Flask, render_template, request, jsonify, send_file
import io
from logic import analyze_batch, generate_comprehensive_pdf_bytes, get_parameter_names, get_db_version, load_data

app = Flask(__name__)


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the single-page frontend."""
    return render_template("index.html")


@app.route("/api/parameters", methods=["GET"])
def api_parameters():
    """Return all parameter names + units for the frontend selector."""
    data = load_data()
    params = [{"name": p["name"], "unit": p["unit"]} for p in data]
    # Only include the DB version when running locally (debug) or when
    # the request originates from localhost. This hides internal metadata
    # once the app is hosted publicly while still showing it during local dev.
    payload = {"parameters": params}

    show_version = False
    # Prefer explicit debug flag
    if app.debug:
        show_version = True
    else:
        # Check request origin — allow 127.0.0.1, ::1 or host starting with 'localhost'
        remote = (request.remote_addr or "")
        host   = (request.host or "")
        if remote.startswith("127.") or remote == "::1" or host.startswith("localhost"):
            show_version = True

    if show_version:
        payload["db_version"] = get_db_version()

    return jsonify(payload)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """
    Accept a JSON batch of {name, value} pairs.
    Validate, analyse, return structured JSON for the frontend.

    Expected body:
    { "batch": [{"name": "pH Level", "value": 7.2}, ...] }
    """
    body = request.get_json(silent=True)

    if not body or "batch" not in body:
        return jsonify({"error": "Request must include a 'batch' array."}), 400

    batch_data = body["batch"]
    if not isinstance(batch_data, list) or len(batch_data) == 0:
        return jsonify({"error": "Batch must be a non-empty array."}), 400

    try:
        gui_text, pdf_results, val_errors, warnings = analyze_batch(batch_data)
    except Exception as e:
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500

    if val_errors:
        return jsonify({"validation_errors": val_errors}), 422

    # Build clean JSON for frontend
    response_results = []
    for res in pdf_results:
        overall = "FAIL" if any(s["status"] == "FAIL" for s in res["standards"]) else "PASS"
        response_results.append({
            "parameter": res["parameter"],
            "value":     res["value"],
            "unit":      res["unit"],
            "status":    overall,
            "standards": [
                {
                    "authority":   s["authority"],
                    "status":      s["status"],
                    "limit":       s["limit"],
                    "violation":   s.get("violation", ""),
                    "consequence": s.get("consequence", ""),
                    "solution":    s.get("solution", ""),
                }
                for s in res["standards"]
            ]
        })

    return jsonify({
        "results":  response_results,
        "warnings": warnings,
    })


@app.route("/api/report", methods=["POST"])
def api_report():
    """
    Generate a PDF from the submitted batch and return it as a download.
    Uses the same body as /api/analyze.

    FIX: os.path.abspath() ensures send_file always gets a valid absolute path
    regardless of the process working directory.
    """
    body = request.get_json(silent=True)

    if not body or "batch" not in body:
        return jsonify({"error": "Request must include a 'batch' array."}), 400

    try:
        _, pdf_results, val_errors, warnings = analyze_batch(body["batch"])

        if val_errors:
            return jsonify({"validation_errors": val_errors}), 422

        # Generate PDF bytes in-memory and stream to the client without saving
        pdf_bytes = generate_comprehensive_pdf_bytes(pdf_results, warnings)
        if not pdf_bytes:
            return jsonify({"error": "PDF generation failed."}), 500

        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        filename = f"Analysis_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf"
        )

    except Exception as e:
        # Return a proper JSON error instead of crashing silently
        # (a silent crash is what caused the "Could not reach server" error)
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
