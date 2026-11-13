"""Revalidate Firebase broker sessions on each production request."""

from django.conf import settings
from django.contrib.auth import logout


class FirebaseSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.AUTH_ADAPTER == "firebase" and request.user.is_authenticated:
            cookie = request.COOKIES.get("firebase_session")
            valid = False
            if cookie:
                from firebase_admin import auth, get_app, initialize_app

                try:
                    get_app()
                except ValueError:
                    initialize_app(options={"projectId": settings.FIREBASE_PROJECT_ID})
                try:
                    claims = auth.verify_session_cookie(cookie, check_revoked=True)
                    valid = request.user.username == f"firebase:{claims['uid']}"
                except (ValueError, auth.InvalidSessionCookieError, auth.RevokedSessionCookieError):
                    pass
            if not valid:
                logout(request)
        return self.get_response(request)
