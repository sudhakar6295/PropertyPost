# Advert generation

The broker selects a main photograph and one of three Pillow layouts: classic, minimal,
or bold. Pillow crops the photograph and draws the location, area, price, contact number,
and optional logo. The generated PNG stays in private object storage.

The Make generation scenario uses Google Gemini for caption text. Use the lowest-cost
stable text option, `gemini-2.5-flash-lite`, with structured JSON output. It receives only
the twelve allow-listed public fields fetched from the signed automation-input endpoint.
PropertyPost validates `headline`, `caption`, and `hashtags`, then creates the poster from
the selected main photo with Pillow. Private owner and negotiation fields are never sent.

The Gemini Developer API pricing page currently lists Flash-Lite at $0.10 per million
input text tokens and $0.40 per million output tokens, and lists a free tier. For example,
1,000 captions averaging 1,000 input tokens and 300 output tokens would be about $0.22 at
those paid rates before any free-tier allowance. Prices and quotas can change; verify them
at [Google's Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). This cost
is separate from Cloud Run and storage billing.

Generation moves a listing through `generating` and `review`; a failure marks it `failed`.
The broker can edit and approve the result before the status becomes `approved`. Only the
broker's Publish action asks Make to post to the selected Facebook Page. PropertyPost shows
`published` only after the signed Make callback confirms Facebook's post ID.
