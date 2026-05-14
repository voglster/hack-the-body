import json

from htb_pi_agent.config import Settings
from htb_pi_agent.discovery import configs


def _settings() -> Settings:
    return Settings(
        mqtt_password="x",
        device_id="jims_office_kiosk",
        device_name="Jims Office Kiosk",
        topic_prefix="office/jims-kiosk",
        discovery_prefix="homeassistant",
    )


def test_emits_one_config_per_entity():
    pairs = list(configs(_settings()))
    components = sorted(p[0].split("/")[1] for p in pairs)
    assert components == ["button", "button", "camera", "number", "switch", "text", "text"]


def test_topics_and_availability_consistent():
    s = _settings()
    for topic, payload in configs(s):
        data = json.loads(payload)
        assert data["availability_topic"] == f"{s.topic_prefix}/availability"
        assert data["device"]["identifiers"] == [s.device_id]
        assert topic.startswith(s.discovery_prefix + "/")
        assert s.device_id in topic


def test_switch_uses_expected_command_state_topics():
    s = _settings()
    monitor = next(
        json.loads(payload) for topic, payload in configs(s) if "monitor/config" in topic
    )
    assert monitor["command_topic"] == "office/jims-kiosk/power/set"
    assert monitor["state_topic"] == "office/jims-kiosk/power/state"
    assert monitor["payload_on"] == "on"
    assert monitor["payload_off"] == "off"


def test_camera_uses_raw_image_topic_no_b64_encoding():
    s = _settings()
    cam = next(
        json.loads(payload) for topic, payload in configs(s) if "preview/config" in topic
    )
    assert cam["topic"] == "office/jims-kiosk/preview/image"
    # HA defaults to raw bytes when image_encoding is absent; we publish raw JPEG.
    assert "image_encoding" not in cam


def test_brightness_number_bounds():
    s = _settings()
    br = next(
        json.loads(payload) for topic, payload in configs(s) if "brightness/config" in topic
    )
    assert br["min"] == 0
    assert br["max"] == 100
