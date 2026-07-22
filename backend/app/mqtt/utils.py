"""Small payload-normalization helpers shared by MQTT components."""


def clean_null_bytes(data):
    if isinstance(data, str):
        return data.replace("\x00", "")
    if isinstance(data, dict):
        return {key: clean_null_bytes(value) for key, value in data.items()}
    if isinstance(data, list):
        return [clean_null_bytes(item) for item in data]
    return data
