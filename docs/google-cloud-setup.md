# Google Cloud setup

The `DATA_ADAPTER` setting selects local file/object adapters in development and Google
adapters in production. Set `GOOGLE_CLOUD_PROJECT`, `FIRESTORE_DATABASE` (usually
`(default)`), and `GCS_PRIVATE_BUCKET` through the environment. Set the existing Firebase
and Django production variables shown in `.env.example` as well.

For local access to Google services, run `gcloud auth application-default login` with a
developer identity that has only the needed Firestore and bucket permissions. Do not
download a service account key or set `GOOGLE_APPLICATION_CREDENTIALS` to a key file.
For Cloud Run, attach a dedicated runtime service account to the service. Grant it
Firestore read/write access and object create/read permissions on the private bucket;
keep bucket public access prevention enabled and uniform bucket-level access on.

Collections are `users`, `sites`, `listings`, `listing_private`, `generation_jobs`, and
`publication_jobs`. The public listing document contains public details, owner ID,
workflow status, and photo path/metadata. `listing_private` holds restricted owner and
negotiation details. Jobs should carry listing ID, owner ID, status, timestamps, and
output object paths, never raw media bytes. The document store accepts only these
collections and one-segment document IDs.

Originals use `originals/{broker_id}/{listing_id}/{random_id}.{extension}`. Future
posters use `posters/{broker_id}/{listing_id}/{random_id}.png`. GCS objects remain
private; authenticated broker requests stream originals from the server. Firestore
documents contain object paths and metadata only. Development private objects persist
under ignored `media/`; isolated tests may use an in-memory adapter.

Cloud integration is configured but has not been deployed or connected to a live
project. Before deployment, budget Firestore operations, GCS storage and egress, Cloud
Run, and Firebase against the ₹2,000/month cap. Set billing alerts and quotas to avoid
unexpected costs.
