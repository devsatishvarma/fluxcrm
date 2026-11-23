"""Gunicorn access logger that redacts password-reset token paths."""

from gunicorn.glogging import Logger


class RedactingLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        path = environ.get("PATH_INFO", "")
        if "/password-reset/" in path and path.count("/") >= 4:
            environ = dict(environ)
            environ["PATH_INFO"] = "/password-reset/<redacted>/"
            raw = environ.get("RAW_URI", "")
            if "/password-reset/" in raw:
                environ["RAW_URI"] = "/password-reset/<redacted>/"
            request_uri = environ.get("REQUEST_URI", "")
            if "/password-reset/" in request_uri:
                environ["REQUEST_URI"] = "/password-reset/<redacted>/"
        return super().atoms(resp, req, environ, request_time)
