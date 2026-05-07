# BugBoard

BugBoard is a simple Flask issue tracker SaaS MVP. It supports user accounts, projects, issue creation, priorities, statuses, search, and filters.

Live demo: https://bugboard-no3e.onrender.com

## Features

- Register and log in
- Create projects
- Add issues to each project
- Edit and delete issues
- Track status: Open, In Progress, Done
- Track priority: High, Medium, Low
- Dashboard with issue counts
- Search and filter issues
- SQLite database for local development

## Run Locally

1. Open a terminal in this folder:

   ```powershell
   cd C:\bugboard
   ```

2. Create a virtual environment:

   ```powershell
   python -m venv .venv
   ```

3. Activate it:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

4. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

5. Start the app:

   ```powershell
   python run_dev.py
   ```

6. Open:

   ```text
   http://127.0.0.1:5001
   ```

The SQLite database is created automatically in `instance/bugboard.sqlite`.

## Render Notes

For a simple Render deployment, use:

```text
gunicorn app:app
```

Set these environment variables in Render:

```text
SECRET_KEY=use-a-long-random-value
DATABASE_URL=your-render-postgres-internal-database-url
```

BugBoard uses SQLite locally. If `DATABASE_URL` is present, it connects to Postgres instead.
