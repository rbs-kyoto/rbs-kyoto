import base64
import json
import os

from django.conf import settings
from pywebpush import WebPushException, webpush
from py_vapid import Vapid, VapidException
from cryptography.hazmat.primitives import serialization

from .models import NotificationHistory


class PushConfigurationError(Exception):
    pass


def _load_vapid_private_key():
    private_key = settings.WEBPUSH_VAPID_PRIVATE_KEY.strip()
    if not private_key:
        raise PushConfigurationError("WEBPUSH_VAPID_PRIVATE_KEY is not configured.")

    try:
        if os.path.isfile(private_key):
            vapid_key = Vapid.from_file(private_key)
        elif private_key.startswith("-----BEGIN"):
            vapid_key = Vapid.from_pem(private_key.encode("utf-8"))
        elif "/" in private_key or "\\" in private_key:
            raise PushConfigurationError(
                "The configured VAPID private-key file does not exist."
            )
        else:
            vapid_key = Vapid.from_string(private_key)
    except PushConfigurationError:
        raise
    except (ValueError, TypeError, OSError, VapidException) as error:
        raise PushConfigurationError(
            "The configured VAPID private key is invalid."
        ) from error

    public_key_bytes = vapid_key.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    derived_public_key = (
        base64.urlsafe_b64encode(public_key_bytes).decode("ascii").rstrip("=")
    )
    configured_public_key = settings.WEBPUSH_VAPID_PUBLIC_KEY.rstrip("=")
    if derived_public_key != configured_public_key:
        raise PushConfigurationError(
            "The configured VAPID public and private keys do not match."
        )
    return vapid_key


def send_web_push(subscription, payload):
    if not all(
        (
            settings.WEBPUSH_VAPID_PUBLIC_KEY,
            settings.WEBPUSH_VAPID_PRIVATE_KEY,
            settings.WEBPUSH_VAPID_SUBJECT,
        )
    ):
        raise PushConfigurationError("Web Push VAPID settings are incomplete.")
    vapid_key = _load_vapid_private_key()

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                },
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid_key,
            vapid_claims={"sub": settings.WEBPUSH_VAPID_SUBJECT},
        )
    except WebPushException as error:
        status_code = error.response.status_code if error.response is not None else None
        if status_code in {404, 410}:
            subscription.delete()
            return False
        raise
    return True


def record_notification(user_id, kind, payload):
    """Save a notification that was delivered to the user's history."""
    return NotificationHistory.objects.create(
        user_id=user_id,
        kind=kind,
        title=str(payload.get("title", ""))[:200],
        body=str(payload.get("body", ""))[:500],
        url=str(payload.get("url", ""))[:500],
    )
