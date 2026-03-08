import asyncio
import time
import re
import json
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("security_core")

# --- Security State (In-Memory, Ultra-fast) ---
class SecurityState:
    def __init__(self):
        self.ip_records = {}  # { ip: [timestamp1, timestamp2, ...] }
        self.blocked_ips = {} # { ip: unban_time }
        self.whitelisted_ips = set(["127.0.0.1", "::1"])
        
        # Configuration
        self.RATE_LIMIT_WINDOW = 1  # seconds
        self.RATE_LIMIT_MAX_REQUESTS = 10000 # requests per second
        self.BLOCK_DURATION = 300 # seconds (5 mins)
        
        # Stats
        self.total_requests = 0
        self.blocked_requests = 0
        self.waf_blocks = 0

    def clean_old_records(self):
        now = time.time()
        for ip in list(self.ip_records.keys()):
            self.ip_records[ip] = [ts for ts in self.ip_records[ip] if now - ts < self.RATE_LIMIT_WINDOW]
            if not self.ip_records[ip]:
                del self.ip_records[ip]
                
        for ip in list(self.blocked_ips.keys()):
            if now > self.blocked_ips[ip]:
                del self.blocked_ips[ip]

security_state = SecurityState()

# --- WAF Rules ---
# Basic SQLi, XSS, and Traversal signatures
WAF_PATTERNS = [
    re.compile(r"(?i)(union\s+select|select\s+.*\s+from|insert\s+into|drop\s+table|update\s+.*\s+set)"),
    re.compile(r"(?i)(<script.*?>.*?</script>|javascript:|onerror=|onload=)"),
    re.compile(r"(?i)(\.\./\.\./|etc/passwd|win\.ini)")
]

def check_waf(payload: str) -> bool:
    """Returns True if malicious."""
    for pattern in WAF_PATTERNS:
        if pattern.search(payload):
            return True
    return False

# --- Middleware ---
class AdvancedSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        security_state.total_requests += 1
        now = time.time()

        if client_ip in security_state.whitelisted_ips:
            return await call_next(request)

        # 1. Check if Blocked
        if client_ip in security_state.blocked_ips:
            if now > security_state.blocked_ips[client_ip]:
                del security_state.blocked_ips[client_ip] # Unban
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
            return JSONResponse(status_code=429, content={"detail": "Too many requests. You have been temporarily blocked."})

        # 3. WAF (Headers and URL only to avoid consuming body)
        url_path = str(request.url)
        headers_str = str(request.headers)
        
        # Check payload and headers for malicious strings
        if check_waf(url_path) or check_waf(headers_str):
            security_state.blocked_ips[client_ip] = now + security_state.BLOCK_DURATION
            logger.warning(f"[WAF] Malicious payload detected from {client_ip}. IP banned.")
            security_state.waf_blocks += 1
            return JSONResponse(status_code=403, content={"detail": "Malicious payload detected and blocked."})

        # Process Request
        response = await call_next(request)
        return response

# --- IPC Server ---
async def handle_ipc_client(reader, writer):
    try:
        data = await reader.read(1024)
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
                    "blocked_requests": getattr(security_state, 'blocked_requests', 0),
                    "waf_blocks": getattr(security_state, 'waf_blocks', 0),
                    "active_ips_count": len(security_state.ip_records),
                    "blocked_ips_count": len(security_state.blocked_ips),
                    "blocked_ips": list(security_state.blocked_ips.keys()),
                    "rate_limit": security_state.RATE_LIMIT_MAX_REQUESTS
                }
            }
        elif cmd == "ban" and args:
            ip = args[0]
            security_state.blocked_ips[ip] = time.time() + (86400 * 365) # 1 year
            response = {"status": "ok", "message": f"Banned IP: {ip}"}
        elif cmd == "unban" and args:
            ip = args[0]
            if ip in security_state.blocked_ips:
                del security_state.blocked_ips[ip]
                response = {"status": "ok", "message": f"Unbanned IP: {ip}"}
            else:
                response = {"status": "error", "message": "IP not found in blocklist"}
        elif cmd == "set_limit" and args:
            try:
                limit = int(args[0])
                security_state.RATE_LIMIT_MAX_REQUESTS = limit
                response = {"status": "ok", "message": f"Rate limit set to {limit} req/10s"}
            except ValueError:
                response = {"status": "error", "message": "Invalid limit value"}

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
