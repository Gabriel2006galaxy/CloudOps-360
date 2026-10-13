# Non-secret defaults for the `flask` command (committed on purpose).
# Without this, a fresh clone with no .env would make `flask` pick wsgi.py,
# which is the production entry point and refuses to start without secrets.
# Real environment variables and .env always take precedence.
FLASK_APP=run.py
FLASK_ENV=development
