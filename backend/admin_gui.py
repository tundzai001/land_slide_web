import asyncio
import json
import threading
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, scrolledtext

IPC_HOST = '127.0.0.1'
IPC_PORT = 9999

class SIEMAdminGUI(ttk.Window):
    def __init__(self):
        super().__init__(themename="cyborg", title="SOC SIEM Dashboard - Absolute Defense", size=(1400, 900))
        
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.start_asyncio_loop, daemon=True).start()
        
        self.panic_active = False
        
        # Map variables
        self.img_map = None
        self.active_radars = {}
        self.processed_events = set()

        self._build_ui()
        self._start_auto_refresh()
        self.after(50, self._animate_radar)

    def start_asyncio_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_async(self, coro, callback=None):
        def _thread_target():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            try:
                result = future.result(timeout=5)
                if callback:
                    self.after(0, callback, result)
            except Exception as e:
                print(f"Async Error: {e}")
                if callback:
                    self.after(0, callback, None)
        threading.Thread(target=_thread_target, daemon=True).start()

    async def _send_ipc_command(self, cmd, args=[]):
        try:
            reader, writer = await asyncio.open_connection(IPC_HOST, IPC_PORT)
            message = f"{cmd} {' '.join(args)}\n"
            writer.write(message.encode())
            await writer.drain()

            data = await reader.read(4096)
            writer.close()
            await writer.wait_closed()
            
            if not data:
                return None
            return json.loads(data.decode().strip())
        except ConnectionRefusedError:
            return {"status": "error", "message": "Connection refused. Is security_core running?"}
        except Exception as e:
            return {"status": "error", "message": f"IPC Error: {e}"}

    def _build_ui(self):
        # Header
        header_frame = ttk.Frame(self, padding=10)
        header_frame.pack(fill=X)
        ttk.Label(header_frame, text="🛡️ GLOBAL SECURITY OPERATIONS CENTER", font=("Consolas", 24, "bold"), bootstyle=SUCCESS).pack(side=LEFT)
        
        self.btn_panic = ttk.Button(header_frame, text="🚨 ENABLE PANIC MODE", style=DANGER, width=25, command=self.toggle_panic)
        self.btn_panic.pack(side=RIGHT, padx=10)
        
        # Main Content container
        main_content = ttk.PanedWindow(self, orient=VERTICAL)
        main_content.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # --- TOP ROW: METRICS ---
        metrics_frame = ttk.Frame(main_content)
        main_content.add(metrics_frame, weight=1)
        
        self.lbl_total_req = self._create_stat_card(metrics_frame, "Total Requests", "0", 0, 0, bootstyle=PRIMARY)
        self.lbl_pi_req = self._create_stat_card(metrics_frame, "Pi Traffic", "0", 0, 1, bootstyle=SUCCESS)
        self.lbl_client_req = self._create_stat_card(metrics_frame, "Client Traffic", "0", 0, 2, bootstyle=INFO)
        self.lbl_blocked_req = self._create_stat_card(metrics_frame, "DDoS Blocks", "0", 0, 3, bootstyle=WARNING)
        self.lbl_waf_sqli = self._create_stat_card(metrics_frame, "SQLi Blocks", "0", 0, 4, bootstyle=DANGER)
        self.lbl_waf_xss = self._create_stat_card(metrics_frame, "XSS Blocks", "0", 0, 5, bootstyle=DANGER)
        self.lbl_waf_lfi = self._create_stat_card(metrics_frame, "Path Traverse", "0", 0, 6, bootstyle=DANGER)
        self.lbl_active_ips = self._create_stat_card(metrics_frame, "Tracked IPs", "0", 0, 7, bootstyle=SECONDARY)

        # --- MIDDLE ROW: THREAT MAP & CONTROLS ---
        mid_frame = ttk.PanedWindow(main_content, orient=HORIZONTAL)
        main_content.add(mid_frame, weight=5)
        
        # 1. Threat Map Panel
        map_frame = ttk.LabelFrame(mid_frame, text="Live Threat Map (Geo-Radar)", padding=5)
        mid_frame.add(map_frame, weight=3) # Give map generous space
        
        self.map_canvas = ttk.Canvas(map_frame, bg="#0e0e0e", highlightthickness=0)
        self.map_canvas.pack(fill=BOTH, expand=YES)
        threading.Thread(target=self._load_map_bg_thread, daemon=True).start()
        
        # 2. Threat Feed & Controls
        right_panel = ttk.PanedWindow(mid_frame, orient=VERTICAL)
        mid_frame.add(right_panel, weight=2)
        
        # Threat Feed
        feed_frame = ttk.LabelFrame(right_panel, text="Live Threat Intelligence Feed", padding=10)
        right_panel.add(feed_frame, weight=2)
        self.txt_feed = scrolledtext.ScrolledText(feed_frame, font=("Consolas", 10), bg="#0f0f0f", fg="#00ff00", state="disabled")
        self.txt_feed.pack(fill=BOTH, expand=YES)
        
        # Controls & Blocklist
        control_frame = ttk.Frame(right_panel)
        right_panel.add(control_frame, weight=1)
        
        # Config & Actions
        limit_frame = ttk.Frame(control_frame, padding=(0, 0, 0, 5))
        limit_frame.pack(fill=X)
        ttk.Label(limit_frame, text="Req/s:").pack(side=LEFT)
        self.var_rate_limit = ttk.StringVar(value="10000")
        ttk.Entry(limit_frame, textvariable=self.var_rate_limit, width=8).pack(side=LEFT, padx=3)
        ttk.Button(limit_frame, text="Apply", style=SUCCESS, command=self.on_set_limit).pack(side=LEFT, padx=3)
        
        self.var_ban_ip = ttk.StringVar()
        ttk.Entry(limit_frame, textvariable=self.var_ban_ip, width=12).pack(side=LEFT, padx=(15, 3))
        ttk.Button(limit_frame, text="Ban", style=DANGER, command=self.on_ban_ip).pack(side=LEFT, padx=2)
        ttk.Button(limit_frame, text="Unban", style=SECONDARY, command=self.on_unban_ip).pack(side=LEFT, padx=2)

        # Blocklist Grid
        blocklist_frame = ttk.LabelFrame(control_frame, text="Active Blocklist", padding=5)
        blocklist_frame.pack(fill=BOTH, expand=YES, pady=(5,0))
        
        self.tree_blocked = ttk.Treeview(blocklist_frame, columns=("ip"), show="headings", height=8)
        self.tree_blocked.heading("ip", text="Target IP")
        self.tree_blocked.pack(fill=BOTH, expand=YES)
        
        # Status Bar
        self.status_var = ttk.StringVar(value="System Initializing...")
        ttk.Label(self, textvariable=self.status_var, padding=5, font=("Consolas", 9)).pack(side=BOTTOM, fill=X)

    def _load_map_bg_thread(self):
        import os, urllib.request
        try:
            if not os.path.exists("world_map_dark.png"):
                req = urllib.request.Request('https://upload.wikimedia.org/wikipedia/commons/thumb/e/e4/World_map_blank_black.png/1024px-World_map_blank_black.png', headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp, open('world_map_dark.png', 'wb') as f:
                    f.write(resp.read())
            self.after(0, self._render_map_bg)
        except Exception as e:
            print("Threat Map image fetch failed:", e)

    def _render_map_bg(self):
        # We place the top-left at X=50, Y=20 to center the 1024x516 map nicely
        self.map_offset_x = 50
        self.map_offset_y = 20
        self.img_map = ttk.PhotoImage(file="world_map_dark.png")
        self.map_canvas.create_image(self.map_offset_x, self.map_offset_y, image=self.img_map, anchor=NW, tags="bg")

    def _animate_radar(self):
        to_del = []
        for pid, data in list(self.active_radars.items()):
            data["radius"] += 1.5
            cv_id = data["cv_id"]
            x, y, r = data["x"], data["y"], data["radius"]
            
            # Simple scaling out
            self.map_canvas.coords(cv_id, x-r, y-r, x+r, y+r)
            
            if r > 40:
                self.map_canvas.delete(cv_id)
                to_del.append(pid)
                
        for pid in to_del:
            del self.active_radars[pid]
            
        self.after(40, self._animate_radar)

        frame = ttk.Frame(parent, bootstyle=bootstyle)
        frame.grid(row=row, column=col, padx=4, pady=5, sticky=NSEW)
        parent.columnconfigure(col, weight=1)
        
        ttk.Label(frame, text=title, font=("Consolas", 9)).pack(pady=(10, 0))
        val_lbl = ttk.Label(frame, text=value, font=("Consolas", 24, "bold"))
        val_lbl.pack(pady=(0, 10))
        return val_lbl

    def _start_auto_refresh(self):
        self.refresh_dashboard()
        self.after(1000, self._start_auto_refresh) # 1s refresh for "pro" feel

    def refresh_dashboard(self):
        self.run_async(self._send_ipc_command("status"), self._update_ui_stats)

    def _update_ui_stats(self, response):
        if not response:
            self.status_var.set("[SYS] DISCONNECTED - IPC Socket Unreachable")
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
            
            # Sync Panic Mode UI
            server_panic = data.get("panic_mode", False)
            if server_panic != self.panic_active:
                self.panic_active = server_panic
                if self.panic_active:
                    self.btn_panic.config(text="🟢 DISABLE PANIC MODE")
                    self.status_var.set("[CRITICAL ALARM] PANIC MODE ACTIVE. TRAFFIC BLOCKED.")
                else:
                    self.btn_panic.config(text="🚨 ENABLE PANIC MODE")
                    self.status_var.set("[SYS] ONLINE - Real-time Threat Monitoring Active")
            elif not self.panic_active:
                self.status_var.set("[SYS] ONLINE - Real-time Threat Monitoring Active")
            
            # Update Treeview
            for item in self.tree_blocked.get_children():
                self.tree_blocked.delete(item)
            for ip in data.get("blocked_ips", []):
                self.tree_blocked.insert("", END, values=(ip,))
                
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
                    
                    if hasattr(self, 'map_offset_x'):
                        # Equirectangular projection mapping to 1024x516 World Map
                        x = self.map_offset_x + (lon + 180) * (1024 / 360)
                        y = self.map_offset_y + (90 - lat) * (516 / 180)
                        
                        color = "#00ff00" if threat_type == "NORMAL" else "#ff0000"
                        if threat_type == "DDOS": color = "#ffaa00"
                        
                        cv_id = self.map_canvas.create_oval(x-2, y-2, x+2, y+2, outline=color, width=2)
                        # Add a persistent tiny dot
                        self.map_canvas.create_oval(x-1, y-1, x+1, y+1, fill=color, outline=color)
                        
                        self.active_radars[event_id] = {"x": x, "y": y, "radius": 2, "color": color, "cv_id": cv_id}
                        
            # Prevent memory leak
            if len(self.processed_events) > 1000:
                self.processed_events.clear()
                
        else:
            self.status_var.set(f"[SYS ERROR] {response.get('message', 'Unknown Error')}")

    def toggle_panic(self):
        cmd_arg = "off" if self.panic_active else "on"
        self.run_async(self._send_ipc_command("panic", [cmd_arg]), self._show_result)

    def on_set_limit(self):
        limit = self.var_rate_limit.get()
        if not limit.isdigit():
            messagebox.showerror("Validation Error", "Rate limit must be numeric.")
            return
        self.run_async(self._send_ipc_command("set_limit", [limit]), self._show_result)

    def on_ban_ip(self):
        ip = self.var_ban_ip.get().strip()
        if ip:
            self.run_async(self._send_ipc_command("ban", [ip]), self._show_result)
            self.var_ban_ip.set("")

    def on_unban_ip(self):
        ip = self.var_ban_ip.get().strip()
        selection = self.tree_blocked.selection()
        if selection and not ip:
            ip = self.tree_blocked.item(selection[0])['values'][0]

        if ip:
            self.run_async(self._send_ipc_command("unban", [ip]), self._show_result)
            self.var_ban_ip.set("")

    def _show_result(self, response):
        if response and response.get("status") == "ok":
            self.refresh_dashboard()
        elif response:
            messagebox.showerror("Command Failed", response.get("message", "Unknown error"))
        else:
            messagebox.showerror("IPC Error", "Server unreachable.")

if __name__ == "__main__":
    app = SIEMAdminGUI()
    app.mainloop()
