# PropertyPost

PropertyPost is a privacy-conscious property listing platform built with Python 3.12,
Django, server-rendered Bootstrap 5 templates, `uv`, Ruff, and pytest.

The current domain intentionally supports one category: **Open Plot / Land for Sale**.
Public listing details and private owner/negotiation details use separate tables,
serializers and repository contracts. Public advert details and private owner/negotiation
details use distinct database models and serializers.

## Local development

Copy `.env.example` to `.env`, replace both local-only database password placeholders,
then start the local MySQL 8 database and Django app:

```powershell
Copy-Item .env.example .env
docker compose up --build -d mysql
docker compose run --rm app uv run --no-sync manage.py migrate
docker compose up --build -d app
docker compose run --rm app uv run --no-sync manage.py createsuperuser
```

Then open <http://127.0.0.1:8000/>.

Production build and checks use the same lockfile:

```powershell
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run --env-file .env manage.py check --deploy --settings propertypost.settings.production
docker build -t propertypost:local .
```

Production uses the separate Hostinger MySQL database configured by `MYSQL_HOST`,
`MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD`. Store production values
in Google Secret Manager and attach them to Cloud Run; never add them to GitHub or this
repository. Set `MYSQL_SSL_ENABLED=true` and supply `MYSQL_SSL_CA` when Hostinger provides
a custom CA certificate. Local credentials are loaded from the ignored `.env`; local and
production databases are entirely separate. `/health/` and `/ready/` are container probes.
See [`docs/architecture.md`](docs/architecture.md).

Migrations are explicit. Never run them automatically in the image entrypoint. In local
development, `docker compose run --rm app uv run --no-sync manage.py migrate` applies
them to the persistent named MySQL volume. Create a broker account with the
`createsuperuser` command above. Stop services while keeping the database by running
`docker compose down`; **do not** add `--volumes`/`-v` unless you intentionally want to
erase local database data.

The test runner needs permission to create and drop Django's temporary test database.
For local PowerShell tests, use the MySQL root credential already stored in ignored `.env`
for this test process only; the running app continues to use the limited `propertypost`
database user:

```powershell
$localEnv = Get-Content .env
$rootEntry = $localEnv | Where-Object { $_.StartsWith('MYSQL_ROOT_PASSWORD=') } | Select-Object -First 1
$env:MYSQL_USER = 'root'
$env:MYSQL_PASSWORD = $rootEntry.Substring('MYSQL_ROOT_PASSWORD='.Length)
$env:MYSQL_HOST = '127.0.0.1'
$env:MYSQL_SSL_ENABLED = 'false'
$env:DJANGO_SETTINGS_MODULE = 'propertypost.settings.development'
uv run --env-file .env pytest
```

Create a local broker account using the `docker compose run ... createsuperuser` command
above, then sign in at `/login/`. The broker journey goes through My plots, Add a plot, Upload photos, Review
details, Advert preview, and Published result. Photos are stored in ignored local `media/`.
Each broker route filters by the signed-in owner, including uploads and publication.
Google Cloud Storage, Secret Manager, and GitHub OIDC setup are in
[`docs/google-cloud-setup.md`](docs/google-cloud-setup.md).
Poster layouts, caption providers, and the approval flow are described in
[`docs/advert-generation.md`](docs/advert-generation.md).
The MySQL schema boundary is in [`docs/data-model.md`](docs/data-model.md), and the
versioned, signed automation API contract is in
[`docs/automation-api.md`](docs/automation-api.md).

Local development uses Django password authentication. Production settings use Firebase
email/password sign-in, verified ID tokens, and revocation-checked server session cookies.
Firebase credentials come from the runtime environment.

## Quality checks

The [CI workflow](.github/workflows/ci.yml) runs for pushes to `main` and on manual
dispatch. It verifies `uv.lock`, installs dependencies with uv, runs Ruff and the full
test suite, builds the production Docker image, and scans Git history for secrets. A
successful push run can trigger the separate production deployment workflow.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run manage.py check
```

Configuration defaults to safe local-development settings. Production requires
`DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`; see `.env.example` for the complete list.

Public listing content and private owner/contact information are deliberately stored in
separate models and database tables. Hostinger MySQL is the production database; local
MySQL 8 runs in Docker Compose with a persistent named volume. No PostgreSQL, Cloud SQL,
Firestore or SQLite runtime configuration is used. Private data must never be exposed by
public views, templates, serializers, logs, or integrations.
