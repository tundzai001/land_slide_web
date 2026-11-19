import time
import re
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("security_core")

from collections import deque
import datetime

# --- Security State (In-Memory, Ultra-fast) ---
class SecurityState:
    def __init__(self):
        self.ip_records = {}  # { ip: [timestamp1, timestamp2, ...] }
        self.blocked_ips = {} # { ip: unban_time }
        self.whitelisted_ips = {"127.0.0.1", "::1"}
        
        # Threat Feed Logging (Max 100 entries)
        self.event_log = deque(maxlen=100)
        
        # Configuration
        self.RATE_LIMIT_WINDOW = 1  # seconds
        self.RATE_LIMIT_MAX_REQUESTS = 10000 # requests per second
        self.BLOCK_DURATION = 300 # seconds (5 mins)
        self.panic_mode = False # Absolute lockdown
        
        # Stats
        self.total_requests = 0
        self.pi_requests = 0
        self.client_requests = 0
        
        self.blocked_requests = 0
        self.waf_blocks = 0
        self.sqli_blocks = 0
        self.xss_blocks = 0
        self.lfi_blocks = 0
        
        # Threat Map State
        self.geoip_cache = {}
        self.map_events = deque(maxlen=200)

    def add_event(self, event_type: str, ip: str, detail: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.event_log.appendleft(f"[{timestamp}] [{event_type}] {ip} - {detail}")
        
        # Fire off GeoIP resolver for Map
        if event_type in ["DDOS", "WAF", "NORMAL"]:
            async_add_threat_map(ip, event_type)

    def clean_old_records(self):
        now = time.time()
        for ip in tuple(self.ip_records):
            self.ip_records[ip] = [ts for ts in self.ip_records[ip] if now - ts < self.RATE_LIMIT_WINDOW]
            if not self.ip_records[ip]:
                del self.ip_records[ip]
                
        for ip in tuple(self.blocked_ips):
            if now > self.blocked_ips[ip]:
                del self.blocked_ips[ip]
                self.add_event("UNBAN", ip, "Ban duration expired.")

security_state = SecurityState()

def async_add_threat_map(ip: str, threat_type: str):
    # IP geolocation requires a separately approved provider and privacy policy.
    security_state.map_events.append({
        "ip": ip, "lat": None, "lon": None, "type": threat_type, "time": time.time(),
    })

# --- WAF Rules ---
# Granular signatures
SQLI_PATTERN = re.compile(r"(?i)(\bunion\s+select\b|\bselect\b[^\r\n]+?\bfrom\b|\binsert\s+into\b|\bdrop\s+table\b|\bupdate\b[^\r\n]+?\bset\b)")
XSS_PATTERN = re.compile(r"(?i)(<script[^>]*>.*?</script>|javascript:|onerror=|onload=)")
LFI_PATTERN = re.compile(r"(?i)(\.\./\.\./|etc/passwd|win\.ini)")

def check_waf_granular(payload: str):
    """Returns classification of malicious payload, or None."""
    if SQLI_PATTERN.search(payload):
        return "SQLI"
    if XSS_PATTERN.search(payload):
        return "XSS"
    if LFI_PATTERN.search(payload):
        return "LFI"
    return None

# --- Middleware Helpers ---
def _track_request_metrics(client_ip: str, url_path: str, now: float) -> None:
    security_state.total_requests += 1
    if url_path.startswith("/api/data") or "/pi-" in url_path.lower():
        security_state.pi_requests += 1
        return

    security_state.client_requests += 1
    if "/api/" in url_path and not url_path.endswith("/heartbeat") and client_ip not in security_state.whitelisted_ips:
        if now % 2 < 0.5:
            async_add_threat_map(client_ip, "NORMAL")

def _check_ip_ban(client_ip: str, now: float) -> JSONResponse | None:
    if client_ip not in security_state.blocked_ips:
        return None
    if now > security_state.blocked_ips[client_ip]:
        del security_state.blocked_ips[client_ip]
        security_state.add_event("UNBAN", client_ip, "Ban duration expired.")
        return None
    security_state.blocked_requests += 1
    return JSONResponse(status_code=403, content={"detail": "IP address is banned by Security Core."})

def _check_rate_limit(client_ip: str, now: float) -> JSONResponse | None:
    if client_ip not in security_state.ip_records:
        security_state.ip_records[client_ip] = []
    
    records = [ts for ts in security_state.ip_records[client_ip] if now - ts < security_state.RATE_LIMIT_WINDOW]
    records.append(now)
    security_state.ip_records[client_ip] = records

    if len(records) > security_state.RATE_LIMIT_MAX_REQUESTS:
        security_state.blocked_ips[client_ip] = now + security_state.BLOCK_DURATION
        logger.warning(f"[Anti-DDoS] Auto-banning IP {client_ip} for high traffic.")
        security_state.blocked_requests += 1
        security_state.add_event("DDOS", client_ip, f"Triggered rate limit > {security_state.RATE_LIMIT_MAX_REQUESTS} req/s")
        return JSONResponse(status_code=429, content={"detail": "Too many requests. You have been temporarily blocked."})
    return None

def _record_waf_block(threat_type: str, client_ip: str, now: float) -> JSONResponse:
    security_state.blocked_ips[client_ip] = now + security_state.BLOCK_DURATION
    logger.warning(f"[WAF] Malicious payload ({threat_type}) detected from {client_ip}. IP banned.")
    security_state.waf_blocks += 1
    if threat_type == "SQLI":
        security_state.sqli_blocks += 1
    elif threat_type == "XSS":
        security_state.xss_blocks += 1
    elif threat_type == "LFI":
        security_state.lfi_blocks += 1
    security_state.add_event("WAF", client_ip, f"Signature matched: {threat_type}")
    return JSONResponse(status_code=403, content={"detail": "Malicious payload detected and blocked."})

def _check_waf_threat(client_ip: str, request: Request, now: float) -> JSONResponse | None:
    threat = check_waf_granular(str(request.url)) or check_waf_granular(str(request.headers))
    if threat:
        return _record_waf_block(threat, client_ip, now)
    return None

# --- Middleware ---
class AdvancedSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        _track_request_metrics(client_ip, str(request.url.path), now)

        if client_ip in security_state.whitelisted_ips:
            return await call_next(request)

        if security_state.panic_mode:
            security_state.blocked_requests += 1
            return JSONResponse(status_code=503, content={"detail": "Service Unavailable. System is under lockdown."})

        ban_resp = _check_ip_ban(client_ip, now)
        if ban_resp:
            return ban_resp

        rate_resp = _check_rate_limit(client_ip, now)
        if rate_resp:
            return rate_resp

        waf_resp = _check_waf_threat(client_ip, request, now)
        if waf_resp:
            return waf_resp

        return await call_next(request)

