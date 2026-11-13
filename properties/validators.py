"""Reusable validation for the property domain."""

from django.core.validators import RegexValidator

phone_number_validator = RegexValidator(
    regex=r"^\+[1-9]\d{7,14}$",
    message="Use E.164 format, for example +919876543210.",
)
