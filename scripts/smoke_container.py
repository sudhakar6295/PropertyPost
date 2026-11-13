"""Run a disposable end-to-end broker journey against a local container."""

import re
import sys
from http.cookiejar import CookieJar
from io import BytesIO
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

from PIL import Image


def main(base_url: str, username: str, password: str) -> None:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(path):
        with opener.open(urljoin(base_url, path)) as response:
            return response.geturl(), response.read().decode()

    def csrf(html):
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        assert match, "CSRF token missing"
        return match.group(1)

    def post(path, fields, image=None):
        if image is None:
            data = urlencode(fields).encode()
            content_type = "application/x-www-form-urlencoded"
        else:
            boundary = "propertypost-smoke-boundary"
            parts = []
            for key, value in fields.items():
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                    f"{value}\r\n".encode()
                )
            parts.extend(
                [
                    f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                    'filename="plot.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),
                    image,
                    f"\r\n--{boundary}--\r\n".encode(),
                ]
            )
            data = b"".join(parts)
            content_type = f"multipart/form-data; boundary={boundary}"
        request = Request(
            urljoin(base_url, path),
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with opener.open(request) as response:
            return response.geturl(), response.read().decode()

    _, login = get("/login/")
    _, dashboard = post(
        "/login/", {"csrfmiddlewaretoken": csrf(login), "username": username, "password": password}
    )
    assert "My plots" in dashboard
    _, add = get("/plots/add/")
    photo_url, photos = post(
        "/plots/add/",
        {
            "csrfmiddlewaretoken": csrf(add),
            "public-title": "Container smoke plot",
            "public-location": "Hyderabad",
            "public-landmark": "Near ORR",
            "public-area": "267",
            "public-area_unit": "sq_yd",
            "public-total_price": "4800000",
            "public-price_per_unit": "",
            "public-facing": "east",
            "public-road_width_ft": "30",
            "public-approval_type": "hmda",
            "public-contact_number": "+919876543210",
            "public-language": "te",
            "private-owner_name": "Private smoke owner",
            "private-owner_phone": "+919800000000",
            "private-internal_notes": "Never publish this",
            "private-negotiable_amount": "4500000",
        },
    )
    assert "Upload photos" in photos, photos[:400]
    image = BytesIO()
    Image.new("RGB", (100, 80), "green").save(image, "PNG")
    _, photos = post(
        photo_url, {"csrfmiddlewaretoken": csrf(photos), "caption": "Road view"}, image.getvalue()
    )
    assert "Main photo" in photos, photos[:400]
    generate_path = photo_url.replace("/photos/", "/generate/")
    _, generate = get(generate_path)
    review_url, review = post(
        generate_path, {"csrfmiddlewaretoken": csrf(generate), "template": "classic"}
    )
    assert "Review your advert" in review, review[:400]
    preview_url, preview = post(
        review_url,
        {
            "csrfmiddlewaretoken": csrf(review),
            "headline": "Edited smoke advert",
            "caption": "Plot near ORR. Call for details.",
            "hashtags_text": "#OpenPlot",
        },
    )
    assert "Edited smoke advert" in preview
    assert "Private smoke owner" not in preview
    publish_path = preview_url.replace("/preview/", "/publish/")
    _, published = post(publish_path, {"csrfmiddlewaretoken": csrf(preview)})
    assert "Your advert is published" in published
    print("container broker journey passed")


if __name__ == "__main__":
    main(*sys.argv[1:4])
