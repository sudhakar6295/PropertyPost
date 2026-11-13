# Advert generation

The broker selects a main photograph and one of three Pillow layouts: classic, minimal,
or bold. Pillow crops the photo to a fixed canvas and draws location, area, INR price,
contact number, and an optional logo. The PNG is stored in the configured private object
store at a `posters/` path. The database keeps only the path and editable text.

`CAPTION_ADAPTER=local` generates deterministic text with no external request. To opt in
to Gemini, set `CAPTION_ADAPTER=gemini`, `GEMINI_API_KEY`, and `GEMINI_MODEL` through the
environment. Only the twelve approved public detail fields are included in the request.
The provider requests structured JSON with `headline`, `caption`, and `hashtags` and
validates the response before saving it. No private owner or negotiation fields are sent.

Generation moves the listing through `generating` and `review`; a failure marks it
`failed`. The broker edits and approves the text before the status becomes `approved`.
Publishing still requires approval. Gemini use may incur charges, so monitor it against
the ₹2,000/month infrastructure budget.
