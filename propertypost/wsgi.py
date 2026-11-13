"""WSGI config for PropertyPost."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "propertypost.settings.production")

application = get_wsgi_application()
