from app.features.stations.topics import duplicate_mqtt_topics, normalize_mqtt_topic


def test_normalize_mqtt_topic_trims_outer_whitespace():
    assert normalize_mqtt_topic("  device/station/gnss  ") == "device/station/gnss"


def test_duplicate_mqtt_topics_is_exact_and_case_sensitive():
    assert duplicate_mqtt_topics([
        "device/station/gnss",
        " device/station/gnss ",
        "DEVICE/STATION/GNSS",
        "",
    ]) == ["device/station/gnss"]
