from .db import create_user, get_user_by_username
from .config import JWT_SECRET, JWT_EXP_SECONDS
from .jwt import encode_jwt, decode_jwt

def register_user(username: str, password: str) -> int:
    return create_user(username=username, password=password)

def authenticate_user(username: str, password: str):
    user = get_user_by_username(username)
    if not user:
        return None
    if user.get("password") != password:
        return None
    return user

def issue_token(user_id: int, username: str) -> str:
    return encode_jwt({"sub": user_id, "username": username}, JWT_SECRET, JWT_EXP_SECONDS)

def verify_token(token: str):
    return decode_jwt(token, JWT_SECRET)
