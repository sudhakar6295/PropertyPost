# PropertyPost architecture

PropertyPost is a Django application for Open Plot / Land for Sale. Django ORM is the source of truth, and all local and production relational data uses MySQL 8. Public listing fields and private owner/negotiation details are stored in separate models and serializers. Broker reads and writes are filtered by the authenticated owner.

Local development runs MySQL in Docker Compose on an isolated named volume. Production connects to a separately provisioned Hostinger MySQL database over TLS. Production database credentials are Secret Manager values injected into Cloud Run. Local `.env` values never enter the image or Git. The container does not run migrations at startup; migrations are an explicit release step.

Django username/password authentication and Django sessions are used in local and production environments, with user accounts stored in the configured MySQL database. Photos and generated posters are private: local development uses files under ignored `media/`, while production uses private Google Cloud Storage through Application Default Credentials or the Cloud Run service account.

Pillow creates posters in three templates. Caption generation uses the deterministic local provider or Gemini, which receives only approved public fields. Brokers can edit the result before approval. Versioned automation callbacks use timestamped HMAC signatures and idempotency receipts; Make.com and Facebook are not connected.

Gunicorn serves Django behind HTTPS. WhiteNoise serves hashed static assets. `/health/` reports process liveness; `/ready/` checks database connectivity. JSON logs omit request bodies, private listing values and tokens. Cloud Run uses minimum instances zero and conservative resource limits; production deployment holds candidate revisions at zero traffic until health/readiness checks pass.

## Data and external services

- Database: local MySQL 8; production Hostinger MySQL. No SQLite, PostgreSQL, Cloud SQL or Firestore runtime.
- Photo/poster objects: local filesystem for development; private Cloud Storage in production.
- Login: Django password authentication and database-backed Django sessions in both environments.
- Runtime: Docker image on Cloud Run; GitHub Actions deploys using GitHub OIDC, with no service-account JSON key.
- Migrations: explicit `manage.py migrate` operation, never an automatic container startup task.
- Cost: retain minimum Cloud Run instances at zero and keep total cloud infrastructure below ₹2,000/month. Hostinger database plan and usage are billed separately and must fit the same budget.
