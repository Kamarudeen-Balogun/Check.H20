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

The container uses `gunicorn` to serve `app:app` on port 5000.

Deploying to Render

This project includes a `Dockerfile` and a simple GitHub Actions file to validate imports.

Steps (high level):
1. Push your repo to GitHub.
2. Create a Render account and create a new Web Service.
   - Choose "Docker" (Render will use the `Dockerfile`).
   - Connect the repo and select the branch (e.g., `main`).
   - Set the start command if needed: `gunicorn -w 4 -b 0.0.0.0:5000 app:app`.
3. Enable auto-deploy from GitHub so every push to `main` deploys automatically.
4. Use a separate branch (e.g., `staging`) for preview deployments and testing before merging to `main`.

Short domain & DNS

- Render provides a service subdomain like `your-service.onrender.com` by default (short and memorable enough). For a truly short custom domain, map your domain through Render and use Cloudflare for DNS + WAF.

Security & availability notes

- Place Cloudflare in front of the Render app for free CDN, DDoS protection and basic WAF/rate-limiting.
- Always run with `debug=False` in production and serve with `gunicorn`.
- The app writes no PDFs to disk, but `database.json` is read from the filesystem. If you deploy to an ephemeral container and need persistent DB edits, store DB in S3 or a managed DB.

CI / Local testing workflow

- Use `staging` branch + Render preview apps to test changes before merging to `main`.
- Locally, test with the same Docker image (`docker build`) and run the container to ensure parity.

If you want, I can:
- Add example GitHub Actions to deploy to Render automatically (requires Render API key),
- Add S3-based storage for the standards DB, or
- Configure a Cloudflare+Render short domain guide.

