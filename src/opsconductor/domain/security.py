"""Credential hashing for API key authentication."""

import hashlib


def hash_api_key(value: str) -> str:
    """Return the hexadecimal SHA-256 digest used to store and look up a key.

    The digest is deterministic and unsalted so authentication can find a user
    with a single equality lookup on the unique ``api_key_hash`` column. API
    keys are high-entropy secrets, which is why a fast unsalted hash is
    acceptable for this purpose.

    Args:
        value: Raw API key presented by the caller, with no normalization.

    Returns:
        A 64-character lowercase hexadecimal digest, matching the
        ``String(64)`` column used to persist it.

    Warning:
        Never store or log the raw key, and never reuse this function for
        user-chosen passwords; unsalted SHA-256 is not a password hash.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
