# Firestore data model: Open Plot / Land for Sale

Firestore is an optional persistence adapter, not a domain dependency. Application code uses
the `PublicOpenPlotRepository` and `PrivateOpenPlotRepository` protocols. The current Django
ORM and future Firestore adapters implement the same contracts.

Allowed workflow statuses are `draft`, `ready`, `generating`, `review`, `approved`,
`publishing`, `published`, and `failed`.

## Public document

Path: `open_plot_public/{public_id}`

```json
{
  "schema_version": 1,
  "category": "open_plot_land_for_sale",
  "status": "published",
  "public_details": {
    "title": "East-facing residential plot",
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
  }
}
```

Only this collection may be used by public pages. Query published listings with
`status == "published"`. Decimal measurements are strings to avoid binary floating-point
rounding; INR amounts are integer rupees.

## Private document

Path: `open_plot_private/{public_id}`

```json
{
  "schema_version": 1,
  "category": "open_plot_land_for_sale",
  "private_details": {
    "owner_name": "Restricted",
    "owner_phone": "+919800000000",
    "internal_notes": "Restricted",
    "negotiable_amount": 4500000
  }
}
```

The document ID links the two documents without copying private content into the public
document. Firestore Security Rules must deny all client reads and writes to
`open_plot_private`; only a trusted server identity may access it. The public collection must
allow reads only when `status == "published"`. Create/update operations should be server-only
until an authenticated authoring workflow is implemented.

The Google Cloud SDK adapter is available through Application Default Credentials.
Production deployment and live cloud verification are separate release steps.
