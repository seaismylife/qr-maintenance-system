# QR Code-Enabled Equipment Repair and Maintenance Management System

Full-stack laboratory equipment and maintenance tracking portal built with Python (Flask) and MySQL. Supports role-based access for Administrator, Custodian, Technician, and Faculty, QR code scanning, repair requests workflow, activity logging, and reporting.

## Features

- Role-based access control (Admin, Custodian, Technician, Faculty)
- QR code generation and mobile camera scanning
- Maintenance ticketing from submission to verification and resolution
- Technician assignment, repair tracking, and duration logs
- Logbook and analytical summary reports
- Health check monitoring endpoint (`/health`)

## Requirements

- Python 3.10+
- MySQL Community Server or MariaDB (e.g. XAMPP)

## Local Setup

1. Configure environment:
   Copy `.env.example` to `.env` and verify database settings.

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Initialize database and default accounts:
   ```bash
   python init_db.py --seed
   ```

4. Start the server:
   ```bash
   start.bat
   ```
   Or:
   ```bash
   python wsgi.py
   ```
   Open `http://localhost:5000` in your browser.

## Cloud Deployment (Render + TiDB Cloud Serverless)

### Step 1: Set Up TiDB Cloud (Free Serverless MySQL)
1. Sign up or log in to [TiDB Cloud](https://tidbcloud.com/).
2. Click **Create Cluster** and select **TiDB Serverless** (Free plan).
3. Choose your preferred cloud region (e.g. AWS Singapore or US East).
4. In the cluster dashboard, click **Connect**:
   - Generate your root password and save it securely.
   - Note your connection details:
     - **Host**: e.g. `gateway01.<region>.prod.aws.tidbcloud.com`
     - **Port**: `4000`
     - **User**: e.g. `<prefix>.root`
     - **Password**: `<your-password>`
     - **Database**: `test` (or `qr_maintenance_db`)
   - Alternatively, copy the full connection string:
     `mysql://<prefix>.root:<password>@gateway01.<region>.prod.aws.tidbcloud.com:4000/test`

### Step 2: Deploy to Render (render.com)

#### Option A: One-Click Blueprint (Recommended)
1. Push your latest code to GitHub.
2. In [Render Dashboard](https://dashboard.render.com/), click **New +** -> **Blueprint**.
3. Select this GitHub repository. Render reads [`render.yaml`](file:///c:/xampp/htdocs/Capstone%20Project/render.yaml) automatically.
4. Fill in the prompted environment variables (`MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`, `MYSQL_PORT`) or provide `DATABASE_URL`.
5. Click **Apply**.

#### Option B: Manual Web Service
1. In Render Dashboard, click **New +** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure the following fields:
   - **Language**: `Python`
   - **Branch**: `main`
   - **Region**: Same or nearest region to your TiDB cluster
   - **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt`
   - **Start Command**: `python init_db.py --seed && gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --worker-class gthread --keep-alive 5`
   - **Health Check Path**: `/health`
4. Under **Environment Variables**, add:
   - `FLASK_ENV`: `production`
   - `FLASK_DEBUG`: `0`
   - `SECRET_KEY`: *(click Generate or enter a random 32-character string)*
   - `BEHIND_PROXY`: `1`
   - `PROXY_FIX_NUM_PROXIES`: `1`
   - `MYSQL_SSL_DISABLED`: `0`
   - **Either** paste your single connection string:
     - `DATABASE_URL`: `mysql://<prefix>.root:<password>@gateway01.<region>.prod.aws.tidbcloud.com:4000/test?sslmode=verify-full`
   - **Or** set individual parameters:
     - `MYSQL_HOST`: `gateway01.<region>.prod.aws.tidbcloud.com`
     - `MYSQL_PORT`: `4000`
     - `MYSQL_USER`: `<prefix>.root`
     - `MYSQL_PASSWORD`: `<your-tidb-password>`
     - `MYSQL_DB`: `test` (or `qr_maintenance_db`)
   - `PUBLIC_BASE_URL`: `https://your-service-name.onrender.com` *(after deployment)*
5. Click **Create Web Service**. Render will build the environment, run `init_db.py --seed` to create tables and seed default users, and start Gunicorn.


## Default Accounts

| Role | Email | Password |
|---|---|---|
| Administrator | admin@school.edu | admin123 |
| Custodian | custodian@school.edu | custodian123 |
| Technician | technician@school.edu | technician123 |
| Faculty | faculty@school.edu | faculty123 |

## Health Check

`GET /health` returns JSON status:
```json
{
  "status": "healthy",
  "database": "connected",
  "environment": "production",
  "version": "1.0.0"
}
```
