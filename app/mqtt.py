import asyncio
import json
import time
from .config import BROKER_URL, BROKER_TOPIC, parse_mqtt_url
from .db import apply_change
from .ws import broadcast
import app.db as db

import aiomqtt as mqtt

Client = mqtt.Client


async def mqtt_consumer():
    cfg = parse_mqtt_url(BROKER_URL)
    while True:
        try:
            async with Client(cfg["host"], cfg["port"]) as client:
                await client.subscribe(f"{BROKER_TOPIC}/+/+")
                print("MQTT connected to", BROKER_URL, "subscribed to", f"{BROKER_TOPIC}/+/+")

                async for message in client.messages:
                    topic = message.topic
                    ts = int(time.time())

                    topicString = topic.value
                    parts = topicString.split("/")
                    print("new message", topicString)

                    if len(parts) < 4:
                        continue

                    pin = parts[-2]
                    action = parts[-1]

                    try:
                        payload = json.loads(message.payload.decode("utf-8"))
                    except Exception:
                        continue

                    if action == "toggle":
                        enabled = bool(payload.get("enabled", True))
                        uuid = payload.get("uuid", "")
                        user = db.get_user_by_device_pin(pin)
                        if user is None:
                            continue

                        if user["rfid_uid"] != uuid:
                            await broadcast(
                                {
                                    "topic": topic.value,
                                    "pin": pin,
                                    "enabled": False,
                                    "not_authorized": True,
                                    "uuid": uuid,
                                    "ts": ts,
                                }
                            )
                            continue

                        print(f"PIN {pin} -> ENABLED {enabled}")
                        db.set_user_pins_enabled(pin=pin, enabled=enabled)
                        await broadcast(
                            {
                                "topic": topic.value,
                                "pin": pin,
                                "enabled": enabled,
                                "uuid": uuid,
                                "ts": ts,
                            }
                        )
                        continue

                    if action == "count":
                        try:
                            change = int(payload.get("change", 0))
                        except Exception:
                            continue

                        if change not in (-1, 1):
                            continue

                        pin_info = db.get_pin_by_id(pin)
                        if pin_info is None or not pin_info["enabled"]:
                            continue

                        print(f"PIN {pin} -> CHANGE {change}")
                        new_count = apply_change(pin=pin, change=change, ts=ts)
                        await broadcast(
                            {
                                "topic": topic.value,
                                "pin": pin,
                                "change": change,
                                "new_count": new_count,
                                "ts": ts,
                            }
                        )
        except Exception as e:
            print("MQTT error:", e)
            await asyncio.sleep(3)


async def publish_reset(device_id: str):
    cfg = parse_mqtt_url(BROKER_URL)
    topic = f"{BROKER_TOPIC}/{device_id}/reset"
    payload = json.dumps({"reset": True})
    print("MQTT publish reset to", topic)
    async with Client(cfg["host"], cfg["port"]) as client:
        await client.publish(topic, payload)
