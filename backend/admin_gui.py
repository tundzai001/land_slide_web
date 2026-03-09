import asyncio
import json
import threading
import sys
import subprocess
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, scrolledtext
import logging
import os

logging.basicConfig(level=logging.DEBUG)

try:
    import tkintermapview
    HAS_MAPVIEW = True
    logging.info("tkintermapview for Threat Map loaded successfully.")
except ImportError:
    try:
        logging.info("tkintermapview for Threat Map not found, will attempt to install...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tkintermapview", "pillow"])
        logging.debug("tkintermapview installed successfully.")
        import tkintermapview
        HAS_MAPVIEW = True
        logging.info("tkintermapview loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to install tkintermapview: {e}")
        HAS_MAPVIEW = False

IPC_HOST = os.getenv("IPC_HOST", "127.0.0.1")
IPC_PORT = int(os.getenv("IPC_PORT", 9999))

class SIEMAdminGUI(ttk.Window):
    def __init__(self):
        logging.debug("Initializing SIEMAdminGUI...")
        super().__init__(themename="cyborg", title="SOC SIEM Dashboard - Absolute Defense", size=(1400, 900))
        
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.start_asyncio_loop, daemon=True).start()
        
        self.panic_active = False
        
        # Map variables
        self.img_map = None
        self.active_radars = {}
        self.processed_events = set()

        self._build_ui()
        logging.debug("UI built successfully, starting auto-refresh...")
        self._start_auto_refresh()
        logging.debug("SIEMAdminGUI initialization complete.")

    def start_asyncio_loop(self):
        asyncio.set_event_loop(self.loop)
        logging.debug("Asyncio event loop will start.")
        self.loop.run_forever()

    def run_async(self, coro, callback=None):
        def _thread_target():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            try:
                result = future.result(timeout=5)
                logging.info("Result received from async command.")
                if callback:
                    self.after(0, callback, result)
                    logging.debug("Callback scheduled.")
            except Exception as e:
                logging.error(f"Async Error: {e}")
                if callback:
                    self.after(0, callback, None)
                    logging.debug("Callback scheduled without result.")
        threading.Thread(target=_thread_target, daemon=True).start()
        logging.info("New thread started for async command.")

    async def _send_ipc_command(self, cmd, args=[]):
        try:
            reader, writer = await asyncio.open_connection(IPC_HOST, IPC_PORT)
            message = f"{cmd} {' '.join(args)}\n"
            logging.debug(f"Writing IPC command: {message.strip()}")
            writer.write(message.encode())
            await writer.drain()

            data = await reader.read(4096)
            writer.close()
            await writer.wait_closed()
            logging.info("IPC command sent and response received.")
            if not data:
                logging.warning("No data received from IPC command.")
                return None
            json_data = json.loads(data.decode().strip())
            logging.debug(f"Received IPC response: {json_data}")
            return json_data
        except ConnectionRefusedError:
            logging.error("Connection refused when trying to send IPC command.")
            return {"status": "error", "message": "Connection refused. Is security_core running?"}
        except Exception as e:
            logging.error(f"IPC Error: {e}")
            return {"status": "error", "message": f"IPC Error: {e}"}

    def _build_ui(self):
        logging.info("Building UI components...")
        # Header
        header_frame = ttk.Frame(self, padding=10)
        header_frame.pack(fill=X)
        logging.debug("Header frame is set.")
        ttk.Label(header_frame, text="🛡️ GLOBAL SECURITY OPERATIONS CENTER", font=("Consolas", 24, "bold"), bootstyle=SUCCESS).pack(side=LEFT)
        
        self.btn_panic = ttk.Button(header_frame, text="🚨 ENABLE PANIC MODE", style=DANGER, width=25, command=self.toggle_panic)
        self.btn_panic.pack(side=RIGHT, padx=10)
        logging.debug("Panic mode button is set.")
        
        # Main Content container
        main_content = ttk.PanedWindow(self, orient=VERTICAL)
        main_content.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        logging.debug("Main content pane is set.")
        
        # --- TOP ROW: METRICS ---
        metrics_frame = ttk.Frame(main_content)
        main_content.add(metrics_frame, weight=1)
        logging.debug("Metrics frame is set and added.")
        
        self.lbl_total_req = self._create_stat_card(metrics_frame, "Total Requests", "0", 0, 0, bootstyle=PRIMARY)
        self.lbl_pi_req = self._create_stat_card(metrics_frame, "Pi Traffic", "0", 0, 1, bootstyle=SUCCESS)
        self.lbl_client_req = self._create_stat_card(metrics_frame, "Client Traffic", "0", 0, 2, bootstyle=INFO)
        self.lbl_blocked_req = self._create_stat_card(metrics_frame, "DDoS Blocks", "0", 0, 3, bootstyle=WARNING)
        self.lbl_waf_sqli = self._create_stat_card(metrics_frame, "SQLi Blocks", "0", 0, 4, bootstyle=DANGER)
        self.lbl_waf_xss = self._create_stat_card(metrics_frame, "XSS Blocks", "0", 0, 5, bootstyle=DANGER)
        self.lbl_waf_lfi = self._create_stat_card(metrics_frame, "Path Traverse", "0", 0, 6, bootstyle=DANGER)
        self.lbl_active_ips = self._create_stat_card(metrics_frame, "Tracked IPs", "0", 0, 7, bootstyle=SECONDARY)

        logging.debug("All metric cards created.")

        # --- MIDDLE ROW: THREAT MAP & CONTROLS ---
        mid_frame = ttk.PanedWindow(main_content, orient=HORIZONTAL)
        main_content.add(mid_frame, weight=5)

        logging.debug("Middle frame for threat map and controls is set and added.")
        
        # 1. Threat Map Panel
        map_frame = ttk.LabelFrame(mid_frame, text="Live Threat Map (Geo-Radar)", padding=5)
        mid_frame.add(map_frame, weight=3) # Give map generous space
        logging.debug("Map frame is set and added.")
        
        if HAS_MAPVIEW:
            self.map_widget = tkintermapview.TkinterMapView(map_frame, corner_radius=0)
            self.map_widget.pack(fill=BOTH, expand=YES)
            try:
                self.map_widget.set_tile_server("https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", max_zoom=19)
                logging.debug("Map tile server initialized.")
            except:
                logging.warning("Failed to set custom tile server, using default.")
                pass
            self.map_widget.set_position(21.0285, 105.8542) # Hanoi center
            self.map_widget.set_zoom(2)
            self.map_markers = []
            logging.debug("Map widget set to initial position 21.0285 N, 105.8542 E with zoom level 2.")
        else:
            self.map_canvas = ttk.Canvas(map_frame, bg="#0e0e0e", highlightthickness=0)
            self.map_canvas.pack(fill=BOTH, expand=YES)
            self.map_canvas.create_text(400, 200, text="[SYS WARNING] tkintermapview not available.", fill="red")
            logging.warning("tkintermapview not available, showing warning on canvas.")
        
        # 2. Threat Feed & Controls
        right_panel = ttk.PanedWindow(mid_frame, orient=VERTICAL)
        mid_frame.add(right_panel, weight=2)
        logging.debug("Right panel for threat feed and controls is set and added.")

        # Threat Feed
        feed_frame = ttk.LabelFrame(right_panel, text="Live Threat Intelligence Feed", padding=10)
        right_panel.add(feed_frame, weight=2)
        self.txt_feed = scrolledtext.ScrolledText(feed_frame, font=("Consolas", 10), bg="#0f0f0f", fg="#00ff00", state="disabled")
        self.txt_feed.pack(fill=BOTH, expand=YES)
        logging.debug("Threat feed text area is set and added.")
        # Controls & Blocklist
        control_frame = ttk.Frame(right_panel)
        right_panel.add(control_frame, weight=1)
        logging.debug("Control frame is set and added.")

        # Config & Actions
        limit_frame = ttk.Frame(control_frame, padding=(0, 0, 0, 5))
        limit_frame.pack(fill=X)
        ttk.Label(limit_frame, text="Req/s:").pack(side=LEFT)
        self.var_rate_limit = ttk.StringVar(value="10000")
        ttk.Entry(limit_frame, textvariable=self.var_rate_limit, width=8).pack(side=LEFT, padx=3)
        ttk.Button(limit_frame, text="Apply", style=SUCCESS, command=self.on_set_limit).pack(side=LEFT, padx=3)
        logging.debug("Rate limit controls are set and added.")
        
        self.var_ban_ip = ttk.StringVar()
        ttk.Entry(limit_frame, textvariable=self.var_ban_ip, width=12).pack(side=LEFT, padx=(15, 3))
        ttk.Button(limit_frame, text="Ban", style=DANGER, command=self.on_ban_ip).pack(side=LEFT, padx=2)
        ttk.Button(limit_frame, text="Unban", style=SECONDARY, command=self.on_unban_ip).pack(side=LEFT, padx=2)
        logging.debug("IP ban controls are set and added.")

        # Blocklist Grid
        blocklist_frame = ttk.LabelFrame(control_frame, text="Active Blocklist", padding=5)
        blocklist_frame.pack(fill=BOTH, expand=YES, pady=(5,0))
        logging.debug("Blocklist frame is set and added.")
        
        self.tree_blocked = ttk.Treeview(blocklist_frame, columns=("ip"), show="headings", height=8)
        self.tree_blocked.heading("ip", text="Target IP")
        self.tree_blocked.pack(fill=BOTH, expand=YES)
        logging.debug("Blocked IPs treeview is set and added.")
        
        # Status Bar
        self.status_var = ttk.StringVar(value="System Initializing...")
        ttk.Label(self, textvariable=self.status_var, padding=5, font=("Consolas", 9)).pack(side=BOTTOM, fill=X)
        logging.info("Finished building UI components.")

    def _create_stat_card(self, parent, title, value, row, col, bootstyle=PRIMARY):
        frame = ttk.Frame(parent, bootstyle=bootstyle)
        frame.grid(row=row, column=col, padx=4, pady=5, sticky=NSEW)
        parent.columnconfigure(col, weight=1)
        
        ttk.Label(frame, text=title, font=("Consolas", 9)).pack(pady=(10, 0))
        val_lbl = ttk.Label(frame, text=value, font=("Consolas", 24, "bold"))
        val_lbl.pack(pady=(0, 10))
        logging.debug(f"Stat card created. Title: {title}, Initial Value: {value}")
        return val_lbl

    def _start_auto_refresh(self):
        self.refresh_dashboard()
        self.after(1000, self._start_auto_refresh) # 1s refresh for "pro" feel
        logging.debug("Auto-refresh scheduled every 1 second.")

    def refresh_dashboard(self):
        self.run_async(self._send_ipc_command("status"), self._update_ui_stats)
        logging.debug("Dashboard refreshed.")

    def _update_ui_stats(self, response):
        if not response:
            self.status_var.set("[SYS] DISCONNECTED - IPC Socket Unreachable")
            logging.warning("Failed to update UI stats: IPC socket unreachable.")
            return
            
        if response.get("status") == "ok":
            data = response.get("data", {})
            self.lbl_total_req.config(text=str(data.get("total_requests", 0)))
            self.lbl_pi_req.config(text=str(data.get("pi_requests", 0)))
            self.lbl_client_req.config(text=str(data.get("client_requests", 0)))
            self.lbl_blocked_req.config(text=str(data.get("blocked_requests", 0)))
            self.lbl_waf_sqli.config(text=str(data.get("sqli_blocks", 0)))
            self.lbl_waf_xss.config(text=str(data.get("xss_blocks", 0)))
            self.lbl_waf_lfi.config(text=str(data.get("lfi_blocks", 0)))
            self.lbl_active_ips.config(text=str(data.get("active_ips_count", 0)))
            logging.info("UI stats updated successfully with latest data.")
            
            # Sync Panic Mode UI
            server_panic = data.get("panic_mode", False)
            if server_panic != self.panic_active:
                self.panic_active = server_panic
                if self.panic_active:
                    self.btn_panic.config(text="🟢 DISABLE PANIC MODE")
                    self.status_var.set("[CRITICAL ALARM] PANIC MODE ACTIVE. TRAFFIC BLOCKED.")
                    logging.info("Panic mode activated.")
                else:
                    self.btn_panic.config(text="🚨 ENABLE PANIC MODE")
                    self.status_var.set("[SYS] ONLINE - Real-time Threat Monitoring Active")
                    logging.info("Panic mode is already activated before.")
            elif not self.panic_active:
                self.status_var.set("[SYS] ONLINE - Real-time Threat Monitoring Active")
                logging.info("Panic mode is deactivated.")
            
            # Update Treeview
            for item in self.tree_blocked.get_children():
                self.tree_blocked.delete(item)
                logging.debug("Cleared existing entries in blocked IPs treeview.")
            for ip in data.get("blocked_ips", []):
                self.tree_blocked.insert("", END, values=(ip,))
                logging.debug(f"Added blocked IP to treeview: {ip}")
                
            # Update Threat Feed
            events = data.get("events", [])
            self.txt_feed.config(state="normal")
            self.txt_feed.delete(1.0, END)
            for ev in events:
                self.txt_feed.insert(END, ev + "\n")
            self.txt_feed.config(state="disabled")
            
            # Update Threat Map Radars
            map_events = data.get("map_events", [])
            for event in map_events[-20:]:
                event_id = f"{event['ip']}_{event['time']}"
                if event_id not in self.processed_events:
                    self.processed_events.add(event_id)
                    lat = event.get("lat", 0.0)
                    lon = event.get("lon", 0.0)
                    threat_type = event.get("type", "NORMAL")
                    
                    # Ocean / Unresolved
                    if lat == 0.0 and lon == 0.0: continue
                    
                    if HAS_MAPVIEW and hasattr(self, 'map_widget'):
                        mrk = self.map_widget.set_marker(lat, lon, text=f"{event['ip']}\n({threat_type})")
                        self.map_markers.append(mrk)
                        if len(self.map_markers) > 30:
                            old = self.map_markers.pop(0)
                            old.delete()
                        
            # Prevent memory leak
            if len(self.processed_events) > 1000:
                self.processed_events.clear()
                
        else:
            self.status_var.set(f"[SYS ERROR] {response.get('message', 'Unknown Error')}")

    def toggle_panic(self):
        cmd_arg = "off" if self.panic_active else "on"
        self.run_async(self._send_ipc_command("panic", [cmd_arg]), self._show_result)
        logging.info(f"Panic mode toggle command sent: {cmd_arg}")

    def on_set_limit(self):
        limit = self.var_rate_limit.get()
        if not limit.isdigit():
            messagebox.showerror("Validation Error", "Rate limit must be numeric.")
            return
        self.run_async(self._send_ipc_command("set_limit", [limit]), self._show_result)
        logging.info(f"Rate limit set to: {limit}")

    def on_ban_ip(self):
        ip = self.var_ban_ip.get().strip()
        if ip:
            self.run_async(self._send_ipc_command("ban", [ip]), self._show_result)
            logging.info(f"IP banned: {ip}")
            self.var_ban_ip.set("")

    def on_unban_ip(self):
        ip = self.var_ban_ip.get().strip()
        selection = self.tree_blocked.selection()
        if selection and not ip:
            ip = self.tree_blocked.item(selection[0])['values'][0]

        if ip:
            self.run_async(self._send_ipc_command("unban", [ip]), self._show_result)
            logging.info(f"IP unbanned: {ip}")
            self.var_ban_ip.set("")

    def _show_result(self, response):
        if response and response.get("status") == "ok":
            logging.debug("Command executed successfully, refreshing dashboard.")
            self.refresh_dashboard()
        elif response:
            logging.error(f"Command failed: {response.get('message', 'Unknown error')}")
            messagebox.showerror("Command Failed", response.get("message", "Unknown error"))
        else:
            logging.error("No response received for command execution.")
            messagebox.showerror("IPC Error", "Server unreachable.")

if __name__ == "__main__":
    app = SIEMAdminGUI()
    app.mainloop()
