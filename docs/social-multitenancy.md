# Broker-owned Facebook and Instagram publishing

## Scope and tenant boundary

Each Django broker user is an isolated tenant in this release. Existing listings remain owned by their `broker` user; no existing listing or account is reassigned. A broker can connect Facebook Pages they manage and the Instagram professional accounts linked to those Pages. The broker must choose a connected Page and approve an advert before posting. Team accounts with multiple staff under one tenant are a separate future change.

The application still uses Django login, MySQL, private Cloud Storage, and Make.com for advert generation. The opt-in Meta publishing path calls Meta from PropertyPost so a shared Make scenario never receives a broker's Page access token. When `META_MULTI_TENANT_ENABLED=false`, the existing Make publication path remains active.

## Connection and publication design

1. The signed-in broker starts the Facebook OAuth authorization-code flow. PropertyPost stores a random, expiring, single-use state in the broker's session and uses a fixed configured callback URL.
2. After verifying state, PropertyPost exchanges the code server-side, discovers granted Pages and linked Instagram professional accounts, and encrypts each Page token before saving it in a broker-owned `SocialAccountConnection`. The app never renders the token.
3. An approved advert can be sent to a chosen connected Page. Facebook receives a Page photo post; a linked Instagram professional account receives a media container followed by media publication. Meta fetches a short-lived signed JPEG rendition of the approved poster; the original PNG and Cloud Storage object remain private.
4. `SocialPublicationAttempt` records one platform, target Page, advert version, request ID, status and external post ID. The uniqueness constraint blocks duplicate sends of the same advert version to the same Page/platform. Successful results are saved independently, so a Facebook success remains visible if Instagram fails. If Instagram is still processing, the container ID is saved and a later retry resumes that same container. An uncertain network outcome cannot be retried automatically. A stale attempt is marked uncertain when the broker next opens the app, so an interrupted worker does not leave a permanently pending post.
5. Every listing, connection and result query is scoped to the logged-in broker. OAuth state is bound to that broker's session. No social token or owner/private listing detail is included in Make events, templates, logs or public API serialization.

## Meta prerequisites and rollout

Meta's [Page photo publishing reference](https://developers.facebook.com/docs/graph-api/reference/page/photos/) documents a Page access token and `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts` permissions. Meta's [Instagram publishing guide](https://developers.facebook.com/documentation/instagram-platform/content-publishing) requires JPEG and `instagram_basic` plus `instagram_content_publish` for a linked professional account; personal Instagram accounts are outside this first connection flow. Meta's [App Review guide](https://developers.facebook.com/docs/resp-plat-initiatives/app-review/introduction) says unapproved permissions are limited to app-role users. Test with app-role users first, then complete Meta review for other brokers.

Before enabling the feature, register the exact HTTPS `/accounts/social/meta/callback/` redirect URI in the Meta app. Provide `META_APP_ID`, `META_APP_SECRET`, `META_REDIRECT_URI`, `META_TOKEN_ENCRYPTION_KEY`, and a supported `META_GRAPH_VERSION` through the runtime environment. Store the app secret and an independent Fernet encryption key in Google Secret Manager; do not commit or paste their values. Keep the old encryption key available until all saved Page tokens have been re-encrypted or disconnected. Set `META_MULTI_TENANT_ENABLED=true` only after the Meta app, permissions, Cloud Run secret access, migration, and live test are ready. The database migration is an explicit release step, never a container-start action.

No new cloud resource is created by this code. The eventual rollout needs two additional Secret Manager values. Google's [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing) lists six free active versions per account, then about US$0.06 per additional active version per month, plus access operations above the free allowance. Existing [Cloud Run request-based billing](https://cloud.google.com/run/pricing) and outbound traffic remain usage-based; retain minimum instances zero and the current maximum-instance limit. Check the complete bill, including the Hostinger database, against the ₹2,000 monthly project budget before enabling new brokers.

## Safety checks before launch

- Run migrations and the full MySQL-backed test suite in the release process.
- Verify two brokers cannot list, disconnect, select, or publish through each other's social connection or listing.
- Verify Page and Instagram account selection, an expired token, duplicate click, partial success, and uncertain response with Meta test accounts.
- Check that a signed poster URL is reachable by Meta for long enough to fetch the image, while the original object remains private.
- Confirm Meta app permissions and redirect URI in the live app, and verify no token appears in HTML, logs, Make payloads, or the database in plaintext.
- Enable the flag only after these checks; keep the existing Make path until then.
