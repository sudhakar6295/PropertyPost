import json
from io import BytesIO

import pytest
from PIL import Image

from properties.captions import (
    GeminiCaptionProvider,
    LocalCaptionProvider,
    validate_caption,
    validate_generated_caption,
)
from properties.posters import TEMPLATES, render_poster
from properties.serializers import serialize_public_details
from properties.tests.test_serialization import make_public_plot


def photo_bytes():
    output = BytesIO()
    Image.new("RGB", (180, 100), "green").save(output, "PNG")
    return output.getvalue()


@pytest.mark.parametrize("template", TEMPLATES)
def test_pillow_poster_has_expected_size_and_distinct_layout(template):
    output = render_poster(photo_bytes(), serialize_public_details(make_public_plot()), template)
    with Image.open(BytesIO(output)) as poster:
        assert poster.size == (1200, 1200)
        assert poster.format == "PNG"


def test_caption_provider_input_excludes_private_data():
    public = serialize_public_details(make_public_plot())
    seen = []
    provider = GeminiCaptionProvider(
        "test-key",
        "test-model",
        transport=lambda payload: (
            seen.append(payload)
            or {
                "output_text": json.dumps(
                    {"headline": "A plot", "caption": "A good plot", "hashtags": ["#Land"]}
                )
            }
        ),
    )
    assert provider.generate(public).headline == "A plot"
    serialized = json.dumps(seen)
    assert "owner_name" not in serialized
    assert "negotiable_amount" not in serialized
    assert "internal_notes" not in serialized
    with pytest.raises(ValueError):
        provider.generate({**public, "owner_phone": "+919800000000"})


def test_caption_validation_rejects_bad_structure():
    for value in (
        {"headline": "Hi", "caption": "Body"},
        {"headline": "Hi", "caption": "Body", "hashtags": ["bad"]},
    ):
        with pytest.raises(ValueError):
            validate_caption(value)
    assert LocalCaptionProvider().generate(serialize_public_details(make_public_plot())).hashtags


def test_caption_validation_accepts_hindi_hashtags_with_vowel_marks():
    value = {
        "headline": "भूमि बिक्री हेतु",
        "caption": "विवरण के लिए संपर्क करें।",
        "hashtags": ["#भूमि", "#संपत्तिबिक्री"],
    }
    assert validate_caption(value).hashtags == ("#भूमि", "#संपत्तिबिक्री")
    for bad_tag in ("#", "#_भूमि", "#भूमि बिक्री", "#भूमि!"):
        with pytest.raises(ValueError):
            validate_caption({**value, "hashtags": [bad_tag]})


def test_generated_caption_keeps_valid_tags_when_model_returns_a_tag_with_spaces():
    value = {
        "headline": "भूमि बिक्री हेतु",
        "caption": "विवरण के लिए संपर्क करें।",
        "hashtags": ["#भूमि", "#Sample 1", "#LandForSale"],
    }
    assert validate_generated_caption(value).hashtags == ("#भूमि", "#LandForSale")
    with pytest.raises(ValueError):
        validate_caption(value)
