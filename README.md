# FinTel

AI-powered IPO research dashboard and agents.

## Running Locally

1. Create and activate a Python virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Initialize database:
   ```powershell
   python -c "from utils.db import init_database; init_database()"
   ```

3. Start dashboard:
   ```powershell
   streamlit run dashboard/app.py
   ```

4. (Optional) Run scheduler manually:
   ```powershell
   python -m agents.scheduler
   ```

### Docker

Build the image:
```powershell
docker build -t fintel:latest .
```

Run scheduler container:
```powershell
docker run -d --name fintel-scheduler -v fintel_data:/home/fintel/app/fintel.db fintel:latest
```

Run dashboard container:
```powershell
docker run -d --name fintel-dashboard -p 8501:8501 -v fintel_data:/home/fintel/app/fintel.db fintel:latest streamlit run dashboard/app.py
```

### Testing & CI

Tests are located in `tests/`. Run them with:
```powershell
pytest -q
```

A GitHub Actions workflow (`.github/workflows/ci.yml`) will automatically run tests and build the Docker image on push or PR.
