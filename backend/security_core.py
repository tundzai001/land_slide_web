import asyncio
import time
import re
import json
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
        self.whitelisted_ips = set(["127.0.0.1", "::1"])
        
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

    def add_event(self, event_type: str, ip: str, detail: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.event_log.appendleft(f"[{timestamp}] [{event_type}] {ip} - {detail}")
        
        # Fire off GeoIP resolver for Map
        if event_type in ["DDOS", "WAF", "NORMAL"]:
            async_add_threat_map(ip, event_type)

    def clean_old_records(self):
        now = time.time()
        for ip in list(self.ip_records.keys()):
            self.ip_records[ip] = [ts for ts in self.ip_records[ip] if now - ts < self.RATE_LIMIT_WINDOW]
            if not self.ip_records[ip]:
                del self.ip_records[ip]
                
        for ip in list(self.blocked_ips.keys()):
            if now > self.blocked_ips[ip]:
                del self.blocked_ips[ip]
                self.add_event("UNBAN", ip, "Ban duration expired.")

security_state = SecurityState()

# --- GeoIP Core ---
import urllib.request
import threading

def fetch_geoip_sync(ip: str, threat_type: str):
    if ip not in security_state.geoip_cache:
        try:
            # Handle localhost resolving roughly to Hanoi for demo
            if ip in ["127.0.0.1", "::1"] or ip.startswith("192.168.") or ip.startswith("10."):
                security_state.geoip_cache[ip] = (21.0285, 105.8542)
            else:
                url = f"http://ip-api.com/json/{ip}?fields=lat,lon"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode())
                    security_state.geoip_cache[ip] = (data.get("lat", 0.0), data.get("lon", 0.0))
        except Exception as e:
            security_state.geoip_cache[ip] = (0.0, 0.0) # Ocean / Unknown
            
    lat, lon = security_state.geoip_cache[ip]
    security_state.map_events.append({
        "ip": ip,
        "lat": lat,
        "lon": lon,
        "type": threat_type,
        "time": time.time()
    })

def async_add_threat_map(ip: str, threat_type: str):
    threading.Thread(target=fetch_geoip_sync, args=(ip, threat_type), daemon=True).start()

# --- WAF Rules ---
# Granular signatures
SQLI_PATTERN = re.compile(r"(?i)(\bunion\b\s+\bselect\b|\bselect\b\s+.*\s+\bfrom\b|\binsert\b\s+\binto\b|\bdrop\b\s+\btable\b|\bupdate\b\s+.*\s+\bset\b)")
XSS_PATTERN = re.compile(r"(?i)(<script.*?>.*?</script>|javascript:|onerror=|onload=)")
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

# --- Middleware ---
class AdvancedSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        security_state.total_requests += 1
        now = time.time()

        url_path = str(request.url.path)

        # Distinguish Pi vs Client Traffic
        if url_path.startswith("/api/data") or "/pi-" in url_path.lower():
            security_state.pi_requests += 1
        else:
            security_state.client_requests += 1
            if "/api/" in url_path and not url_path.endswith("/heartbeat") and client_ip not in security_state.whitelisted_ips:
                # Log normal traffic on map randomly or sparsely to see traffic flow (throttle it so map doesn't lag)
                if now % 2 < 0.5: # Simple throttle
                    async_add_threat_map(client_ip, "NORMAL")

        if client_ip in security_state.whitelisted_ips:
            return await call_next(request)

        # 0. Panic Mode
        if security_state.panic_mode:
            security_state.blocked_requests += 1
            return JSONResponse(status_code=503, content={"detail": "Service Unavailable. System is under lockdown."})

        # 1. Check if Blocked
        if client_ip in security_state.blocked_ips:
            if now > security_state.blocked_ips[client_ip]:
                del security_state.blocked_ips[client_ip] # Unban
                security_state.add_event("UNBAN", client_ip, "Ban duration expired.")
            else:
                security_state.blocked_requests += 1
                return JSONResponse(status_code=403, content={"detail": "IP address is banned by Security Core."})

        # 2. Rate Limiting (Token Bucket / Sliding Window Hybrid)
        if client_ip not in security_state.ip_records:
            security_state.ip_records[client_ip] = []
        
        # Prune old for this IP
        security_state.ip_records[client_ip] = [ts for ts in security_state.ip_records[client_ip] if now - ts < security_state.RATE_LIMIT_WINDOW]
        security_state.ip_records[client_ip].append(now)

        if len(security_state.ip_records[client_ip]) > security_state.RATE_LIMIT_MAX_REQUESTS:
            security_state.blocked_ips[client_ip] = now + security_state.BLOCK_DURATION
            logger.warning(f"[Anti-DDoS] Auto-banning IP {client_ip} for high traffic.")
            security_state.blocked_requests += 1
            security_state.add_event("DDOS", client_ip, f"Triggered rate limit > {security_state.RATE_LIMIT_MAX_REQUESTS} req/s")
            return JSONResponse(status_code=429, content={"detail": "Too many requests. You have been temporarily blocked."})

        # 3. WAF (Headers and URL only to avoid consuming body)
        full_url_str = str(request.url)
        headers_str = str(request.headers)
        
        # Check payload and headers for malicious strings
        threat_type_url = check_waf_granular(full_url_str)
        threat_type_hdr = check_waf_granular(headers_str)
        threat_type = threat_type_url or threat_type_hdr

        if threat_type:
            security_state.blocked_ips[client_ip] = now + security_state.BLOCK_DURATION
            logger.warning(f"[WAF] Malicious payload ({threat_type}) detected from {client_ip}. IP banned.")
            security_state.waf_blocks += 1
            if threat_type == "SQLI": security_state.sqli_blocks += 1
            elif threat_type == "XSS": security_state.xss_blocks += 1
            elif threat_type == "LFI": security_state.lfi_blocks += 1
            
            security_state.add_event("WAF", client_ip, f"Signature matched: {threat_type}")
            return JSONResponse(status_code=403, content={"detail": "Malicious payload detected and blocked."})

        # Process Request
        response = await call_next(request)
        return response

# --- IPC Server ---
async def handle_ipc_client(reader, writer):
    try:
        data = await reader.read(4096)
        message = data.decode().strip()
        if not message:
            return

        command_parts = message.split()
        cmd = command_parts[0].lower()
        args = command_parts[1:]

        response = {"status": "error", "message": "Unknown command"}

        security_state.clean_old_records()

        if cmd == "status":
            response = {
                "status": "ok",
                "data": {
                    "total_requests": getattr(security_state, 'total_requests', 0),
                    "pi_requests": getattr(security_state, 'pi_requests', 0),
                    "client_requests": getattr(security_state, 'client_requests', 0),
                    "blocked_requests": getattr(security_state, 'blocked_requests', 0),
                    "waf_blocks": getattr(security_state, 'waf_blocks', 0),
                    "sqli_blocks": getattr(security_state, 'sqli_blocks', 0),
                    "xss_blocks": getattr(security_state, 'xss_blocks', 0),
                    "lfi_blocks": getattr(security_state, 'lfi_blocks', 0),
                    "active_ips_count": len(security_state.ip_records),
                    "blocked_ips_count": len(security_state.blocked_ips),
                    "blocked_ips": list(security_state.blocked_ips.keys()),
                    "rate_limit": security_state.RATE_LIMIT_MAX_REQUESTS,
                    "panic_mode": security_state.panic_mode,
                    "events": list(security_state.event_log),
                    "map_events": list(security_state.map_events)
                }
            }
        elif cmd == "ban" and args:
            ip = args[0]
            security_state.blocked_ips[ip] = time.time() + (86400 * 365) # 1 year
            security_state.add_event("BAN", ip, "Manually banned via Admin CLI")
            response = {"status": "ok", "message": f"Banned IP: {ip}"}
        elif cmd == "unban" and args:
            ip = args[0]
            if ip in security_state.blocked_ips:
                del security_state.blocked_ips[ip]
                security_state.add_event("UNBAN", ip, "Manually unbanned via Admin CLI")
                response = {"status": "ok", "message": f"Unbanned IP: {ip}"}
            else:
                response = {"status": "error", "message": "IP not found in blocklist"}
        elif cmd == "set_limit" and args:
            try:
                limit = int(args[0])
                security_state.RATE_LIMIT_MAX_REQUESTS = limit
                security_state.add_event("CONFIG", "System", f"Rate limit changed to {limit}")
                response = {"status": "ok", "message": f"Rate limit set to {limit} req/10s"}
            except ValueError:
                response = {"status": "error", "message": "Invalid limit value"}
        elif cmd == "panic" and args:
            state_str = args[0].lower()
            if state_str in ["on", "true", "1"]:
                security_state.panic_mode = True
                security_state.add_event("ALERT", "System", "PANIC MODE ENABLED! ALL TRAFFIC DROPPED.")
                response = {"status": "ok", "message": "Panic Mode ENABLED"}
            else:
                security_state.panic_mode = False
                security_state.add_event("CONFIG", "System", "PANIC MODE DISABLED. Traffic resuming.")
                response = {"status": "ok", "message": "Panic Mode DISABLED"}

        writer.write((json.dumps(response) + "\n").encode())
        await writer.drain()
    except Exception as e:
        logger.error(f"IPC Error: {e}")
    finally:
        writer.close()

async def start_ipc_server():
    server = await asyncio.start_server(handle_ipc_client, '127.0.0.1', 9999)
    logger.info("Security IPC Server started on 127.0.0.1:9999")
    async with server:
        await server.serve_forever()
