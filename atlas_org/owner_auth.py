"""Owner signatures for governance events (audit v5.39 F1).

Every event whose actor is ``owner`` must carry ``owner_sig``: an
HMAC-SHA256, under the owner's secret key, of the event's canonical body
(without ``hash`` and ``owner_sig``, so it binds ``seq`` and ``prev_hash``:
a signature cannot be moved to another position or another log).

The key lives only on the owner's machine, outside the repository (see
``tools/atlas_org_cli.py owner-init``). An agent without it cannot produce a
valid owner event. Verification needs the key too: where it is absent the
event is accepted structurally and reported as unverified (``None``), never
as verified. Pure (L1): the caller supplies the key bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

SIG_FIELD = "owner_sig"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class OwnerSignatureError(ValueError):
    pass


def signing_body(event: dict[str, Any]) -> bytes:
    body = {k: v for k, v in event.items() if k not in ("hash", SIG_FIELD)}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(key: bytes, event: dict[str, Any]) -> str:
    if not key or len(key) < 32:
        raise OwnerSignatureError("owner key missing or shorter than 32 bytes")
    return hmac.new(key, signing_body(event), hashlib.sha256).hexdigest()


def check(event: dict[str, Any], owner_key: bytes | None) -> bool | None:
    """True = verified, None = signed but unverifiable here (no key); raises when invalid."""

    sig = event.get(SIG_FIELD)
    if not isinstance(sig, str) or not _HEX64.match(sig):
        raise OwnerSignatureError(f"seq {event.get('seq')}: owner event without a valid owner signature")
    if owner_key is None:
        return None
    if not hmac.compare_digest(sig, sign(owner_key, event)):
        raise OwnerSignatureError(f"seq {event.get('seq')}: owner signature does not verify")
    return True
