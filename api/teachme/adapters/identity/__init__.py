from __future__ import annotations


class IdentityUnavailable(Exception):
    """No OIDC token to present. Raised by an identity provider that was asked for one and has
    none: the request carried no token header, or the token file is missing or empty. It is a
    configuration or platform fault, never a caller's, so it is not mapped to a status code."""
