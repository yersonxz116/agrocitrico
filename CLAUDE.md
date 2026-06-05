# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Setup
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Run dev server (localhost:5000, debug mode)
python app.py

# Database migrations
flask db upgrade              # Apply all migrations
flask db migrate -m "desc"    # Generate migration after model changes
flask db current              # Show current revision

# Verify syntax
python -m py_compile app.py

# List all routes
flask routes
```

Required: MySQL database `agrocitrico` and `.env` file with `FERNET_KEY`, `MYSQL_*` vars, and `SECRET_KEY`.

## Architecture

**Monolithic Flask app** — all models, routes, middleware, and helpers live in `app.py`. No blueprints, no separate modules.

### Key Architectural Decisions

- **Session-based auth** with `auth_middleware()` running `@app.before_request`. Routes are classified into endpoint groups (GUEST, MFA, SETUP, PROTECTED) that control redirect logic.
- **MFA is optional** — users are offered setup on first login but can skip it. Three auth methods: password+TOTP, password+backup-code, or PEM file (no password).
- **Fernet encryption at rest** — sensitive DB fields (TOTP secret, PEM public key) prefixed with `enc::` to identify encrypted values.
- **AI assistant** uses GPT4All with a local `.gguf` model, lazy-loaded with thread lock on first `/ia/chat` request.
- **No frontend framework** — vanilla JS + Jinja2 templates. Each page has its own CSS/JS file in `static/css/` and `static/js/`.

### Database (MySQL via Flask-SQLAlchemy)

Four tables: `users`, `backup_codes`, `actividades`, `cosechas`. Managed via Flask-Migrate/Alembic in `migrations/versions/`.

### Template/Static Convention

- Templates: `templates/<page>.html` (Jinja2)
- Styles: `static/css/<page>.css` (page-specific) or `static/index.css` (homepage)
- Scripts: `static/js/<page>.js` (page-specific) or `static/index.js` (homepage)

## Coding Conventions

- Python: 4-space indent, short route handlers
- Route function names match page purpose (e.g., `register()` for `/register`)
- Spanish used for: route names (`/actividades`, `/cosechas`), model fields, commit messages, UI text
- HTML class names follow existing Spanish vocabulary
- Commits: short Spanish subjects, imperative mood, optional `Feat:`/`fix:`/`refactor:` prefix
