from custom_components.s60_rowenta.diagnostics import REDACTED, redact


def test_redact():
    out = redact(
        {
            "name": "Casa de Ana",
            "features": [{"name": "power", "value": "NORMAL"}],
            "wifiSsid": "x",
            "ip": "192.168.1.2",
            "note": "ana@example.com 192.168.1.2 aa:bb:cc:dd:ee:ff",
            "robot-1": {"battery": 80},
        },
        ("robot-1",),
    )
    assert out["name"] == out["wifiSsid"] == out["ip"] == REDACTED
    assert out["features"][0] == {"name": "power", "value": "NORMAL"}
    assert out["note"] == f"{REDACTED} {REDACTED} {REDACTED}"
    assert out[REDACTED] == {"battery": 80}
