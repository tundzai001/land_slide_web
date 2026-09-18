"""Device administration routes composed by responsibility."""

from fastapi import APIRouter

from .gnss_origin import reset_gnss_origin, router as gnss_origin_router
from .licensing import (
    ProvisionDeviceRequest,
    generate_customer_license_base,
    generate_license_for_device,
    generate_pi_license_base,
    get_license_code_from_string,
    get_pending_devices,
    provision_device,
    router as licensing_router,
)

router = APIRouter()
router.include_router(licensing_router)
router.include_router(gnss_origin_router)
