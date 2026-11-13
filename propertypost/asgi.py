"""ASGI config for PropertyPost."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "propertypost.settings.production")

application = get_asgi_application()
