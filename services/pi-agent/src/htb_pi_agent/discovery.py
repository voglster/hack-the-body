"""MQTT Discovery configs. Published once on connect (retained) so HA auto-creates entities."""
import json
from typing import Iterable

from .config import Settings


def _device(s: Settings) -> dict:
    return {
        "identifiers": [s.device_id],
        "name": s.device_name,
        "model": "Raspberry Pi 4 kiosk",
        "manufacturer": "voglster/hack-the-body",
    }


def _availability(s: Settings) -> dict:
    return {
        "availability_topic": f"{s.topic_prefix}/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def configs(s: Settings) -> Iterable[tuple[str, str]]:
    """Yield (topic, payload_json) pairs to publish (retain=True)."""
    base = s.topic_prefix
    disc = s.discovery_prefix
    dev = _device(s)
    av = _availability(s)
    obj_prefix = s.device_id

    # Switch — monitor power
    yield (
        f"{disc}/switch/{obj_prefix}/monitor/config",
        json.dumps({
            "name": "Monitor",
            "unique_id": f"{obj_prefix}_monitor",
            "command_topic": f"{base}/power/set",
            "state_topic": f"{base}/power/state",
            "payload_on": "on",
            "payload_off": "off",
            "state_on": "on",
            "state_off": "off",
            "icon": "mdi:monitor",
            "device": dev,
            **av,
        }),
    )

    # Number — brightness
    yield (
        f"{disc}/number/{obj_prefix}/brightness/config",
        json.dumps({
            "name": "Brightness",
            "unique_id": f"{obj_prefix}_brightness",
            "command_topic": f"{base}/brightness/set",
            "state_topic": f"{base}/brightness/state",
            "min": 0,
            "max": 100,
            "step": 5,
            "mode": "slider",
            "icon": "mdi:brightness-6",
            "device": dev,
            **av,
        }),
    )

    # Button — reload browser
    yield (
        f"{disc}/button/{obj_prefix}/reload/config",
        json.dumps({
            "name": "Reload browser",
            "unique_id": f"{obj_prefix}_reload",
            "command_topic": f"{base}/reload/press",
            "payload_press": "press",
            "icon": "mdi:refresh",
            "device": dev,
            **av,
        }),
    )

    # Button — reboot Pi
    yield (
        f"{disc}/button/{obj_prefix}/reboot/config",
        json.dumps({
            "name": "Reboot Pi",
            "unique_id": f"{obj_prefix}_reboot",
            "command_topic": f"{base}/reboot/press",
            "payload_press": "press",
            "icon": "mdi:restart",
            "device": dev,
            **av,
        }),
    )

    # Text — current URL (can be set to navigate)
    yield (
        f"{disc}/text/{obj_prefix}/url/config",
        json.dumps({
            "name": "URL",
            "unique_id": f"{obj_prefix}_url",
            "command_topic": f"{base}/url/set",
            "state_topic": f"{base}/url/state",
            "icon": "mdi:web",
            "device": dev,
            **av,
        }),
    )

    # Text — type into focused window
    yield (
        f"{disc}/text/{obj_prefix}/type/config",
        json.dumps({
            "name": "Type text",
            "unique_id": f"{obj_prefix}_type",
            "command_topic": f"{base}/type/set",
            "icon": "mdi:keyboard",
            "device": dev,
            **av,
        }),
    )

    # Camera — preview screenshot
    yield (
        f"{disc}/camera/{obj_prefix}/preview/config",
        json.dumps({
            "name": "Preview",
            "unique_id": f"{obj_prefix}_preview",
            "topic": f"{base}/preview/image",
            "icon": "mdi:image",
            "device": dev,
            **av,
        }),
    )
