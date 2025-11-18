import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Form, status, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from app.auth import authenticate_user, register_user, issue_token, verify_token
from app.config import JWT_EXP_SECONDS
import time

from app.db import (
    apply_change,
    get_current_count,
    get_logs,
    init_db,
    link_pin_to_user,
    list_user_pins,
    set_user_rfid,
    set_device_mode,
)
from app.mqtt import mqtt_consumer, publish_reset
from app.ws import router as ws_router, broadcast
from app.mqtt import mqtt_consumer
from app.ws import router as ws_router, broadcast

import uvicorn

TOKEN_COOKIE = "token"

def set_auth_cookie(response: Response, token: str) -> Response:
    response.set_cookie(
        TOKEN_COOKIE,
        token,
        max_age=JWT_EXP_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


def clear_auth_cookie(response: Response) -> Response:
    response.delete_cookie(TOKEN_COOKIE, path="/")
    return response


def extract_token(request: Request) -> Optional[str]:
    return request.cookies.get(TOKEN_COOKIE)


def decode_user_id(token: Optional[str]) -> Optional[int]:
    if not token:
        return None
    try:
        payload = verify_token(token)
    except Exception:
        return None
    sub = payload.get("sub")
    try:
        return int(sub)
    except (TypeError, ValueError):
        return None


def has_valid_session(request: Request) -> bool:
    return decode_user_id(extract_token(request)) is not None

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(mqtt_consumer())
    app.state.mqtt_task = task
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except Exception:
                pass


app = FastAPI(lifespan=lifespan)
app.include_router(ws_router)
app.mount("/public", StaticFiles(directory="public"), name="public")


@app.get("/")
def root(request: Request):
    if has_valid_session(request):
        return FileResponse("public/dashboard.html")
    response = FileResponse("public/login.html")
    if TOKEN_COOKIE in request.cookies:
        response = clear_auth_cookie(response)
    return response


def auth_user_id(request: Request) -> int:
    uid = decode_user_id(extract_token(request))
    if uid is not None:
        return uid
    raise HTTPException(status_code=401, detail="Missing or invalid token")


def login_success_response(user_id: int, username: str) -> RedirectResponse:
    token = issue_token(user_id, username)
    return set_auth_cookie(
        RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER),
        token,
    )


def redirect_with_error(path: str, code: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{path}?err={code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    return clear_auth_cookie(response)


@app.post("/register")
async def register_form(username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    password = password.strip()
    if not username or not password:
        return redirect_with_error("/register", "1")
    import sqlite3

    try:
        user_id = register_user(username, password)
    except sqlite3.IntegrityError:
        return redirect_with_error("/register", "2")
    return login_success_response(user_id, username)


@app.post("/login")
async def login_form(username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    password = password.strip()
    user = authenticate_user(username, password)
    if not user:
        return redirect_with_error("/login", "1")
    return login_success_response(int(user["id"]), user["username"])


@app.post("/api/auth/logout")
async def api_logout():
    return clear_auth_cookie(JSONResponse({"ok": True}))


@app.get("/api/me")
async def api_me(request: Request):
    uid = auth_user_id(request)
    return {"user_id": uid, "pins": list_user_pins(uid)}


@app.get("/api/devices")
async def api_devices(request: Request):
    uid = auth_user_id(request)
    return list_user_pins(uid)


@app.post("/api/devices")
async def api_add_device(request: Request, body: dict):
    uid = auth_user_id(request)
    pin = str(body.get("pin", "")).strip()
    if not pin:
        raise HTTPException(status_code=400, detail="pin required")
    link_pin_to_user(uid, pin)
    return {"ok": True}


@app.post("/api/removeDevice/{device_id}")
async def api_remove_device(device_id: str, request: Request):
    uid = auth_user_id(request)
    from app.db import is_pin_owned_by_user

    if not is_pin_owned_by_user(uid, device_id):
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        await publish_reset(device_id)
    except Exception:
        raise HTTPException(status_code=500, detail="mqtt error")

    return {"ok": True}


@app.post("/api/rfid")
async def api_set_rfid(request: Request, body: dict):
    uid = auth_user_id(request)
    rfid_uid = str(body.get("rfid_uid", "")).strip()
    if not rfid_uid:
        raise HTTPException(status_code=400, detail="rfid_uid required")
    set_user_rfid(uid, rfid_uid)
    return {"ok": True, "rfid_uid": rfid_uid}

@app.post("/api/devices/{pin}/mode")
async def api_set_device_mode(pin: str, request: Request, body: dict):
    uid = auth_user_id(request)
    from app.db import is_pin_owned_by_user

    if not is_pin_owned_by_user(uid, pin):
        raise HTTPException(status_code=403, detail="forbidden")

    mode = body.get("mode") if isinstance(body, dict) else None
    try:
        updated_mode = set_device_mode(pin, str(mode))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"pin": pin, "mode": updated_mode}


@app.post("/api/devices/{pin}/change")
async def api_change_device(pin: str, request: Request, body: dict):
    uid = auth_user_id(request)
    from app.db import is_pin_owned_by_user

    if not is_pin_owned_by_user(uid, pin):
        raise HTTPException(status_code=403, detail="forbidden")

    change = None
    if isinstance(body, dict):
        if "change" in body:
            try:
                change = int(body.get("change"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="invalid change")
        elif "direction" in body:
            direction = str(body.get("direction", ""))
            if direction.lower() == "increment":
                change = 1
            elif direction.lower() == "decrement":
                change = -1

    if change not in (-1, 1):
        raise HTTPException(status_code=400, detail="change must be -1 or 1")

    ts = int(time.time())
    new_count = apply_change(pin=pin, change=change, ts=ts)
    await broadcast(
        {
            "pin": pin,
            "change": change,
            "new_count": new_count,
            "ts": ts,
        }
    )
    return {"pin": pin, "change": change, "new_count": new_count, "ts": ts}


@app.get("/api/devices/{pin}")
def api_device(pin: str, request: Request):
    uid = auth_user_id(request)
    from app.db import is_pin_owned_by_user

    if not is_pin_owned_by_user(uid, pin):
        raise HTTPException(status_code=403, detail="forbidden")
    count = get_current_count(pin)
    return {"pin": pin, "current_count": count}


@app.get("/api/logs/{pin}")
def api_logs(pin: str, request: Request, limit: int = 50):
    uid = auth_user_id(request)
    from app.db import is_pin_owned_by_user

    if not is_pin_owned_by_user(uid, pin):
        raise HTTPException(status_code=403, detail="forbidden")
    return get_logs(pin, limit=limit)


@app.get("/login")
def page_login(request: Request):
    if has_valid_session(request):
        return RedirectResponse("/dashboard")
    response = FileResponse("public/login.html")
    if TOKEN_COOKIE in request.cookies:
        response = clear_auth_cookie(response)
    return response


@app.get("/register")
def page_register(request: Request):
    if has_valid_session(request):
        return RedirectResponse("/dashboard")
    response = FileResponse("public/register.html")
    if TOKEN_COOKIE in request.cookies:
        response = clear_auth_cookie(response)
    return response


@app.get("/dashboard")
def page_dashboard(request: Request):
    if has_valid_session(request):
        return FileResponse("public/dashboard.html")
    response = RedirectResponse("/login")
    if TOKEN_COOKIE in request.cookies:
        response = clear_auth_cookie(response)
    return response


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)
