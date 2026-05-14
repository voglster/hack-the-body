"""Entry point: connect to MQTT, register discovery, run state + preview loops."""
import logging
import signal
import sys
import threading
from typing import Optional

import paho.mqtt.client as mqtt

from . import actions
from .config import Settings
from .discovery import configs

log = logging.getLogger("htb-pi-agent")

_stop = threading.Event()


def _t(s: Settings, suffix: str) -> str:
    return f"{s.topic_prefix}/{suffix}"


def _on_connect(client: mqtt.Client, userdata: dict, _flags, reason_code, _props=None):
    s: Settings = userdata["settings"]
    if reason_code != 0:
        log.error("MQTT connect failed: %s", reason_code)
        return
    log.info("connected to %s:%s", s.mqtt_host, s.mqtt_port)

    actions.init_display(s)

    # Availability online
    client.publish(_t(s, "availability"), "online", qos=1, retain=True)

    # Discovery configs (retained so HA picks them up on restart)
    for topic, payload in configs(s):
        client.publish(topic, payload, qos=1, retain=True)

    # Subscribe to all command topics
    for sub in (
        "power/set", "brightness/set", "reload/press",
        "reboot/press", "url/set", "type/set",
    ):
        client.subscribe(_t(s, sub), qos=1)

    # Publish initial state
    _publish_state(client, s, force=True)


def _on_message(client: mqtt.Client, userdata: dict, msg: mqtt.MQTTMessage):
    s: Settings = userdata["settings"]
    topic = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace").strip()
    log.info("rx %s = %r", topic, payload[:80])
    try:
        if topic.endswith("/power/set"):
            actions.set_power(s, payload.lower() == "on")
        elif topic.endswith("/brightness/set"):
            try:
                actions.set_brightness(s, int(payload))
            except ValueError:
                log.warning("bad brightness payload: %r", payload)
        elif topic.endswith("/reload/press"):
            actions.reload_browser(s)
        elif topic.endswith("/reboot/press"):
            client.publish(_t(s, "availability"), "offline", qos=1, retain=True)
            actions.reboot(s)
        elif topic.endswith("/url/set"):
            ok = actions.navigate(s, payload)
            if ok:
                client.publish(_t(s, "url/state"), payload, qos=1, retain=True)
        elif topic.endswith("/type/set"):
            actions.type_text(s, payload)
        _publish_state(client, s, force=True)
    except Exception as e:
        log.exception("error handling %s: %s", topic, e)


_last_state: dict[str, Optional[object]] = {}


def _publish_state(client: mqtt.Client, s: Settings, *, force: bool = False) -> None:
    power = actions.get_power(s)
    brightness = actions.get_brightness(s)
    url = actions.get_url(s)

    updates = {
        "power/state": "on" if power else ("off" if power is False else None),
        "brightness/state": str(brightness) if brightness is not None else None,
        "url/state": url,
    }
    for suffix, val in updates.items():
        if val is None:
            continue
        if force or _last_state.get(suffix) != val:
            client.publish(_t(s, suffix), val, qos=1, retain=True)
            _last_state[suffix] = val


def _state_loop(client: mqtt.Client, s: Settings) -> None:
    while not _stop.is_set():
        try:
            _publish_state(client, s)
        except Exception as e:
            log.warning("state loop error: %s", e)
        _stop.wait(s.state_poll_seconds)


def _preview_loop(client: mqtt.Client, s: Settings) -> None:
    while not _stop.is_set():
        try:
            jpg = actions.screenshot_jpeg(s)
            if jpg is not None:
                client.publish(_t(s, "preview/image"), jpg, qos=0, retain=False)
        except Exception as e:
            log.warning("preview loop error: %s", e)
        _stop.wait(s.preview_seconds)


def _handle_signal(*_a):
    log.info("shutdown signal")
    _stop.set()


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    s = Settings()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"htb-pi-agent-{s.device_id}",
        userdata={"settings": s},
    )
    client.username_pw_set(s.mqtt_user, s.mqtt_password)
    client.will_set(_t(s, "availability"), "offline", qos=1, retain=True)
    client.on_connect = _on_connect
    client.on_message = _on_message

    while not _stop.is_set():
        try:
            client.connect(s.mqtt_host, s.mqtt_port, keepalive=s.mqtt_keepalive)
            break
        except Exception as e:
            log.warning("connect failed, retry in 5s: %s", e)
            _stop.wait(5)
    if _stop.is_set():
        sys.exit(0)

    client.loop_start()

    t_state = threading.Thread(target=_state_loop, args=(client, s), daemon=True)
    t_state.start()
    t_preview = threading.Thread(target=_preview_loop, args=(client, s), daemon=True)
    t_preview.start()

    _stop.wait()

    try:
        client.publish(_t(s, "availability"), "offline", qos=1, retain=True).wait_for_publish(2)
    except Exception:
        pass
    client.loop_stop()
    client.disconnect()
    log.info("clean shutdown")


if __name__ == "__main__":
    run()
