# PropertyPost architecture

PropertyPost is a Django application for Open Plot / Land for Sale. Django ORM is the source of truth, and all local and production relational data uses MySQL 8. Public listing fields and private owner/negotiation details are stored in separate models and serializers. Broker reads and writes are filtered by the authenticated owner.

Local development runs MySQL in Docker Compose on an isolated named volume. Production connects to a separately provisioned Hostinger MySQL database over TLS. Production database credentials are Secret Manager values injected into Cloud Run. Local `.env` values never enter the image or Git. The container does not run migrations at startup; migrations are an explicit release step.

Django username/password authentication and Django sessions are used in local and production environments, with user accounts stored in the configured MySQL database. Photos and generated posters are private: local development uses files under ignored `media/`, while production uses private Google Cloud Storage through Application Default Credentials or the Cloud Run service account.

An optional broker-owned Meta integration treats each Django broker user as an isolated tenant. Social Page access tokens are encrypted in MySQL with an independent environment-provided key. Brokers select only their own connected Pages for direct Facebook/Instagram publication; a `SocialPublicationAttempt` stores each target, advert version and outcome. This path is feature-gated and leaves the existing Make publication path in place until Meta setup is complete. See [broker-owned social publishing](social-multitenancy.md).

Pillow creates posters in three templates and keeps the generated PNG in private object storage. Gemini receives only allow-listed public listing fields and returns validated JSON. Brokers can edit the result before approval. Versioned Make callbacks use timestamped HMAC signatures, request correlation, and idempotency receipts. Publication begins only after broker approval: the existing Make path uses a signed callback, while the opt-in broker-owned Meta path stores a separate outcome for each chosen Page and platform.

Gunicorn serves Django behind HTTPS. WhiteNoise serves hashed static assets. `/health/` reports process liveness; `/ready/` checks database connectivity. JSON logs omit request bodies, private listing values and tokens. Cloud Run uses minimum instances zero and conservative resource limits; production deployment holds candidate revisions at zero traffic until health/readiness checks pass.

## Data and external services

- Database: local MySQL 8; production Hostinger MySQL. No SQLite, PostgreSQL, Cloud SQL or Firestore runtime.
- Photo/poster objects: local filesystem for development; private Cloud Storage in production.
- Login: Django password authentication and database-backed Django sessions in both environments.
- Runtime: Docker image on Cloud Run; GitHub Actions deploys using GitHub OIDC, with no service-account JSON key.
- Migrations: explicit `manage.py migrate` operation, never an automatic container startup task.
- Cost: retain minimum Cloud Run instances at zero and keep total cloud infrastructure below ₹2,000/month. Hostinger database plan and usage are billed separately and must fit the same budget.
