# backend/app/models/pi_device.py
from sqlalchemy import Column, Integer, String, BigInteger, JSON, Boolean
from .config import BaseConfig  # shares metadata with config DB → auto-created with create_all


class PiDevice(BaseConfig):
    """
    Bảng lưu các thiết bị Raspberry Pi (độc lập với Device/sensor).
    Vòng đời: pending → activated → assigned
    Lock: thiết bị bị khóa sẽ không được phép hoạt động
    """
    __tablename__ = "pi_devices"

    id            = Column(Integer, primary_key=True, index=True)
    serial        = Column(String(100), unique=True, index=True, nullable=False)  # device_code từ Pi
    name          = Column(String(255), nullable=False)
    device_type   = Column(String(20), default="pi")         # pi | win | etc...
    status        = Column(String(20), default="pending")    # pending | activating | activated | assigned
    is_locked     = Column(Boolean, default=False)           # True = thiết bị bị khóa
    station_id    = Column(Integer, nullable=True)           # FK mềm (không ràng buộc DB để tránh vấn đề khi trạm bị xóa)
    pi_center_id  = Column(Integer, nullable=True)           # FK mềm: pi_point links to pi_center PiDevice.id
    license_key   = Column(String(255), nullable=True)       # Key backend đã tạo
    last_seen     = Column(BigInteger, default=0)
    registered_at = Column(BigInteger, nullable=False)
    mqtt_topic    = Column(String(255), nullable=True)       # MQTT topic cho pi_point (light/siren control)
    extra_config  = Column(JSON, default={})                 # MQTT info, firmware, v.v.

