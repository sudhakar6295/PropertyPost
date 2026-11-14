# Automation API v1

The broker's **Create posting** button sends a small generation event to the configured
Make.com webhook. It contains the listing UUID, a request UUID, selected template, and
PropertyPost API URLs, but no property fields, photos, or private details. Make fetches the
listing separately from the signed automation-input endpoint.

Set `MAKE_WEBHOOK_URL` from Secret Manager secret `propertypost-make-webhook-url`. Set
`AUTOMATION_HMAC_SECRET` to the same independent secret in PropertyPost and Make's secure
connection so Make can sign input and callback requests. Without it, the API returns 401.

Every request sends `X-PropertyPost-Timestamp` (Unix seconds) and
`X-PropertyPost-Signature` (lowercase hex HMAC-SHA256). Sign the exact bytes:

```text
METHOD\nPATH\nTIMESTAMP\nRAW_BODY
```

For GET, `RAW_BODY` is empty. Timestamps more than five minutes from server time are
rejected. Keep the secret in a credential manager and never place it in a URL or log.
Callbacks use a UUID `request_id`. Repeating the same ID and exact body returns the
stored response; reusing an ID with different content returns 409. Each listing and
callback type has its own request ID namespace.

## GET `/api/v1/listings/{id}/automation-input/`

Successful response (200):

```json
{
  "id": "2ed678c5-8b94-41d3-a803-2ffddb0cb485",
  "status": "generating",
  "public_details": {
    "title": "East-facing plot",
    "location": "Shamshabad, Hyderabad",
    "landmark": "Near ORR Exit 15",
    "area": "267.00",
    "area_unit": "sq_yd",
    "total_price": 4800000,
    "price_per_unit": "17977.53",
    "facing": "east",
    "road_width_ft": "30.00",
    "approval_type": "hmda",
    "contact_number": "+919876543210",
    "language": "te"
  },
  "images": [
    {
      "url": "https://propertypost.example.com/api/v1/listings/2ed678c5-8b94-41d3-a803-2ffddb0cb485/images/1/?expires=1790000000&signature=example",
      "is_main": true,
      "sort_order": 0,
      "content_type": "image/png"
    }
  ]
}
```

Image URLs expire after five minutes. They stream private objects through PropertyPost
and contain no storage credentials. The endpoint returns data only while a broker-triggered
generation request is pending. The URL
above illustrates the shape; its example signature is not valid.

The website sends this event to Make when the broker creates a posting:

```json
{
  "event": "propertypost.generation.requested",
  "request_id": "ac1736c9-4d43-479a-b9bb-fbb7bf5595a1",
  "listing_id": "2ed678c5-8b94-41d3-a803-2ffddb0cb485",
  "template": "classic",
  "automation_input_url": "https://propertypost.example.com/api/v1/listings/2ed678c5-8b94-41d3-a803-2ffddb0cb485/automation-input/",
  "generation_result_url": "https://propertypost.example.com/api/v1/listings/2ed678c5-8b94-41d3-a803-2ffddb0cb485/generation-result/"
}
```

Use the same `request_id` in the generation callback. PropertyPost sets the listing to
`generating` before calling Make; repeated clicks while that request is pending do not
send another event. A successful callback moves it to `review` for broker editing and
approval. This event requests generation only; it does not publish to Facebook.

## POST `/api/v1/listings/{id}/generation-result/`

The listing must be `generating`. A successful callback moves it to `review` for broker
editing and approval.

```json
{
  "request_id": "ac1736c9-4d43-479a-b9bb-fbb7bf5595a1",
  "status": "succeeded",
  "headline": "A plot near ORR",
  "caption": "267 square yards in Shamshabad. Call for details.",
  "hashtags": ["#OpenPlot", "#LandForSale"],
  "poster_path": "posters/1/2ed678c5-8b94-41d3-a803-2ffddb0cb485/poster.png"
}
```

Response: `{"request_id":"ac1736c9-4d43-479a-b9bb-fbb7bf5595a1","status":"review"}`.
The poster path must belong to the same broker and listing. Media bytes are never sent
in a callback.

## POST `/api/v1/listings/{id}/publication-result/`

The listing must be `publishing`. A successful callback marks it `published`.

```json
{
  "request_id": "90327731-cb39-4468-a926-5a7c431ac504",
  "status": "succeeded",
  "external_post_id": "remote-post-42"
}
```

Response: `{"request_id":"90327731-cb39-4468-a926-5a7c431ac504","status":"published","external_post_id":"remote-post-42"}`.
No external publisher is called by this API.

For either callback, a failed result uses `{"request_id":"...","status":"failed",
"error":"Short reason"}` while the listing is awaiting that result. It moves the
listing to `failed`; the error is not echoed into the public response.
