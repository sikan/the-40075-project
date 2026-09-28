"""Read-only Concept2 client with a reusable, verified HTTPS connection."""

import gzip
import http.client
import json
import ssl
import time
from urllib.parse import urlencode


class APIError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Concept2:
    HOST = "log.concept2.com"
    ROOT = "/api/users/me"

    def __init__(self, token, timeout=30):
        if not token or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("The Concept2 token is empty or contains invalid characters.")
        self.token = token
        self.timeout = timeout
        self.connection = None
        self.context = ssl.create_default_context()
        self.context.set_alpn_protocols(["http/1.1"])

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def get(self, path, params=None):
        parts = path.split("/")
        supported = (
            path in ("", "/results") or
            (len(parts) == 3 and parts[:2] == ["", "results"] and parts[2].isdigit()) or
            (len(parts) == 4 and parts[:2] == ["", "results"] and
             parts[2].isdigit() and parts[3] == "strokes")
        )
        if not supported:
            raise ValueError("Unsupported API path.")
        target = self.ROOT + path
        if params:
            target += "?" + urlencode(params)
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.c2logbook.v1+json",
            "Accept-Encoding": "gzip",
            "User-Agent": "the-40075-project/0.1",
        }
        for attempt in range(4):
            try:
                if self.connection is None:
                    self.connection = http.client.HTTPSConnection(
                        self.HOST, timeout=self.timeout, context=self.context)
                self.connection.request("GET", target, headers=headers)
                response = self.connection.getresponse()
                status = response.status
                retry = response.getheader("Retry-After", "")
                encoding = response.getheader("Content-Encoding", "").lower()
                body = response.read()
                response.close()
                if status != 200:
                    # No redirects are followed; credentials stay on this host.
                    if status in (429, 500, 502, 503, 504) and attempt < 3:
                        self.close()
                        delay = min(30, max(2 ** attempt, int(retry) if retry.isdigit() else 0))
                        time.sleep(delay)
                        continue
                    message = "Concept2 returned HTTP {}.".format(status)
                    if status in (401, 403):
                        message += " Check the token and its read permissions."
                    raise APIError(message, status)
                if encoding == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body)
            except (http.client.HTTPException, OSError, EOFError):
                self.close()
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise APIError("Could not reach Concept2; no sync checkpoint was advanced.") from None
            except (ValueError, UnicodeError):
                raise APIError("Concept2 returned an invalid JSON response.") from None
