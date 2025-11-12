import base64
import json
import hmac
import hashlib
import time

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def encode_jwt(payload: dict, secret: str, exp_seconds: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}

    now = int(time.time())
    body = dict(payload)

    body.setdefault("iat", now)
    body.setdefault("exp", now + int(exp_seconds))

    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    token = f"{header_b64}.{payload_b64}.{_b64encode(signature)}"

    return token


def decode_jwt(token: str, secret: str) -> dict:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise ValueError("Invalid token format")
    
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual_sig = _b64decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid signature")
    
    payload = json.loads(_b64decode(payload_b64))
    exp = int(payload.get("exp", 0))

    if exp and exp < time.time():
        raise ValueError("Token expired")
    return payload
