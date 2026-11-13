# PropertyPost architecture

PropertyPost is a Django server-rendered application for one category: Open Plot / Land
for Sale. The broker journey runs through login, dashboard, plot details, photos,
generation, advert review, preview, and publication. Django owns the state machine and
authorization checks. Every broker listing route filters by both listing ID and owner.

Public listing fields and private owner/negotiation fields are separate database models,
serializers, and Firestore document collections. Only the public allow-list feeds Gemini
and the versioned automation API. The automation API authenticates each request with a
timestamped HMAC, and callback receipts enforce request ID idempotency. Signed image URLs
expire and stream private media without granting public bucket access.

Pillow renders posters from a selected main photo and three layouts. Caption providers
are local deterministic or Gemini. A broker edits the caption before approval. Changing
plot details or photo order invalidates the generated advert. Published plots reject
changes through the broker forms.

The local adapter persists private objects under ignored `media/`; tests can use an
in-memory adapter. Production uses GCS with Application Default Credentials. Firestore
adapters hold public/private documents and job metadata. The current web workflow also
uses the Django ORM as its transactional source of truth, backed by PostgreSQL in
production. A production deployment must provision that database, GCS, Firestore, and
Firebase Authentication before serving traffic. Cloud service costs must fit the
₹2,000/month cap.

Gunicorn serves Django behind an HTTPS ingress. WhiteNoise serves collected, hashed
static files. `/health/` reports process liveness; `/ready/` checks database access.
Production secrets and database credentials come only from environment variables.
Application logs are JSON with level, logger, and fixed event names, omitting request
bodies, URLs, tokens, and private listing fields. Gunicorn access logs omit query strings.

The Docker image is built once and runs as a non-root user. Migrations must run as a
separate release step before traffic is switched. No Make.com or Facebook connector is
enabled.
