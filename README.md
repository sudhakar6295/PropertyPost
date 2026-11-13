# PropertyPost

PropertyPost is a privacy-conscious property listing platform built with Python 3.12,
Django, server-rendered Bootstrap 5 templates, `uv`, Ruff, and pytest.

The current domain intentionally supports one category: **Open Plot / Land for Sale**.
Public listing details and private owner/negotiation details use separate tables,
serializers, repository contracts, and Firestore documents. See
[`docs/firestore-data-model.md`](docs/firestore-data-model.md) for the document schema and
access-boundary design.

## Local development

```powershell
uv sync --dev
uv run manage.py migrate
uv run manage.py runserver
```

Then open <http://127.0.0.1:8000/>.

Production build and checks use the same lockfile:

```powershell
uv sync --frozen --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run manage.py check --deploy --settings propertypost.settings.production
docker build -t propertypost:local .
```

Production requires `DATABASE_URL`, Django/Firebase secrets, the automation HMAC secret,
and Google Cloud configuration from `.env.example`. Run `uv run manage.py migrate
--settings propertypost.settings.production` as a separate release step. The image
starts Gunicorn on port 8080; `/health/` and `/ready/` are container probes. For a
local container smoke test, set `DJANGO_SETTINGS_MODULE=propertypost.settings.development`
and use a persistent SQLite volume for the local adapter. Do not use development
settings in a public deployment. See [`docs/architecture.md`](docs/architecture.md).

Create a local broker account with `uv run manage.py createsuperuser`, then sign in at
`/login/`. The broker journey goes through My plots, Add a plot, Upload photos, Review
details, Advert preview, and Published result. Photos are stored in ignored local `media/`.
Each broker route filters by the signed-in owner, including uploads and publication.
Cloud configuration and private storage setup are in
[`docs/google-cloud-setup.md`](docs/google-cloud-setup.md).
The approved, repeatable Google Cloud provisioning and GitHub OIDC setup are in
[`docs/google-cloud-provisioning.md`](docs/google-cloud-provisioning.md).
Poster layouts, caption providers, and the approval flow are described in
[`docs/advert-generation.md`](docs/advert-generation.md).
The versioned, signed automation API contract is in
[`docs/automation-api.md`](docs/automation-api.md).

Local development uses Django password authentication. Production settings require Firebase
project configuration and use Firebase email/password sign-in, verified ID tokens, and
revocation-checked server session cookies. Firebase credentials come from the runtime
environment; cloud deployment and provider configuration are separate later steps.

## Quality checks

The [manual CI workflow](.github/workflows/ci.yml) runs only when started from the
GitHub Actions tab. It verifies `uv.lock`, installs dependencies with uv, runs Ruff and
the full test suite, builds the production Docker image, and scans Git history for
secrets. It does not deploy.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run manage.py check
```

Configuration defaults to safe local-development settings. Production requires
`DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`; see `.env.example` for the complete list.

Public listing content and private owner/contact information are deliberately stored in
separate models and database tables. Private data must never be exposed by public views,
templates, serializers, logs, or integrations.
