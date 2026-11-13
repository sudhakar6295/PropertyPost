"""Deterministic Pillow advert posters."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps

TEMPLATES = ("classic", "minimal", "bold")
PALETTES = {
    "classic": ("#102A43", "#FFFFFF", "#D6A85B"),
    "minimal": ("#F5F3EE", "#17252D", "#30776C"),
    "bold": ("#17283C", "#FFFFFF", "#E9B85C"),
}


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def render_poster(photo_bytes: bytes, details: dict, template: str, logo_bytes=None) -> bytes:
    if template not in TEMPLATES:
        raise ValueError("Unknown poster template")
    from .captions import approved_public_details

    details = approved_public_details(details)
    with Image.open(BytesIO(photo_bytes)) as original:
        image = ImageOps.fit(original.convert("RGB"), (1200, 850), method=Image.Resampling.LANCZOS)
    background, foreground, accent = PALETTES[template]
    poster = Image.new("RGB", (1200, 1200), background)
    if template == "minimal":
        poster.paste(image, (0, 0))
    elif template == "bold":
        poster.paste(image, (0, 160))
    else:
        poster.paste(image, (0, 0))
    draw = ImageDraw.Draw(poster)
    if template == "minimal":
        draw.rectangle((0, 850, 1200, 1200), fill=background)
        text_y = 884
    elif template == "bold":
        draw.rectangle((0, 0, 1200, 160), fill=background)
        draw.rectangle((0, 1010, 1200, 1200), fill=background)
        draw.text((52, 50), "OPEN PLOT / LAND FOR SALE", font=_font(42), fill=accent)
        text_y = 1030
    else:
        draw.rectangle((0, 850, 1200, 1200), fill=background)
        text_y = 885
    location = str(details["location"])
    area = f"{details['area']} {details['area_unit']}"
    price = f"INR {details['total_price']:,}"
    contact = f"Call {details['contact_number']}"
    if template == "bold":
        lines = [(location, 39), (f"{area}  |  {price}", 33), (contact, 28)]
        step = 53
    else:
        lines = [(location, 48), (f"{area}  |  {price}", 37), (contact, 31)]
        step = 85
    for index, (label, size) in enumerate(lines):
        draw.text((54, text_y + index * step), label[:52], font=_font(size), fill=foreground)
    if logo_bytes:
        with Image.open(BytesIO(logo_bytes)) as source:
            logo = source.convert("RGBA")
            logo.thumbnail((210, 110))
            poster.paste(logo, (1200 - logo.width - 35, text_y), logo)
    output = BytesIO()
    poster.save(output, format="PNG", optimize=True)
    return output.getvalue()
