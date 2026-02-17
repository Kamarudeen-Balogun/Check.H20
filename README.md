# Water Quality Compliance Suite

Small Flask app to analyse water quality test results and generate a downloadable PDF report.

Key points
- PDFs are generated in-memory and streamed to the user (no server-side storage).
- Database of standards is `database.json` (local file); the app hides DB version in production.

Quick start (local)

1. Create and activate a Python venv, then install deps:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run locally:

```powershell
python app.py
```

3. Open http://127.0.0.1:5000 and use the UI. To test from a phone on the same network, run on your machine and visit `http://<your-pc-ip>:5000`.

Quick import check

```powershell
python -c "import app, logic; print('imports ok')"
```

Docker (recommended for parity with Render)

Build and run locally:

```bash
docker build -t water-app .
docker run -p 5000:5000 water-app
```



