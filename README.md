# ClassConnect

ClassConnect is a Flask-based classroom management app for teachers and students. It supports class registration, notes, assignments, groups, attendance, progress tracking, event announcements, notifications, and optional Gmail email alerts.

## Features

- Teacher and student registration/login
- Automatic class code generation for teachers
- Student enrollment using class codes
- Notes and assignment posting
- Student assignment submissions
- Random and specific student groups
- Group topic assignments and submissions
- Attendance marking and attendance history
- Teacher and student progress dashboards
- Event and holiday announcements
- In-app notifications
- Optional Gmail app-password email notifications
- Background overdue-assignment checks

## Project Structure

```text
classroom_v2/
  app.py              Flask application and routes
  email_utils.py      Gmail email helpers
  schema.sql          SQLite database schema
  requirements.txt    Python dependencies
  classroom.db        Local SQLite database
  templates/          HTML templates
```

## Requirements

- Python 3.10 or newer
- Flask
- APScheduler

Install dependencies:

```bash
cd classroom_v2
pip install -r requirements.txt
```

## Run Locally

From the repository root:

```bash
python classroom_v2/app.py
```

Or from inside the app folder:

```bash
cd classroom_v2
python app.py
```

The app starts in Flask debug mode. Open the local URL printed in the terminal, usually:

```text
http://127.0.0.1:5000
```

## Database

The app uses SQLite. If `classroom_v2/classroom.db` does not exist, the app initializes it from `classroom_v2/schema.sql`.

## Email Setup

Teachers can configure Gmail from the in-app settings page. Use a Gmail app password, not the normal account password.

## Notes

- The app stores data locally in `classroom_v2/classroom.db`.
- Generated Python cache files in `__pycache__/` should not be committed.
- Do not commit real credentials or personal app passwords.
