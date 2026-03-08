import asyncio
import json
import threading
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox

IPC_HOST = '127.0.0.1'
IPC_PORT = 9999

class SecurityAdminGUI(ttk.Window):
    def __init__(self):
        super().__init__(themename="superhero", title="Advanced Web Security & Anti-DDoS", size=(800, 600))
        
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.start_asyncio_loop, daemon=True).start()

        self._build_ui()
        self._start_auto_refresh()

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
        # Top Header
        header_frame = ttk.Frame(self, padding=20)
        header_frame.pack(fill=X)
        ttk.Label(header_frame, text="Security Core Dashboard", font=("Helvetica", 24, "bold")).pack(side=LEFT)
        
        # Mian Content
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=BOTH, expand=YES)
        
        # Left Panel (Stats)
        left_panel = ttk.Frame(main_frame)
        left_panel.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))

        # Stats Cards
        card_frame = ttk.Frame(left_panel)
        card_frame.pack(fill=X, pady=10)

        self.lbl_total_req = self._create_stat_card(card_frame, "Total Requests", "0", 0, 0, bootstyle=PRIMARY)
        self.lbl_blocked_req = self._create_stat_card(card_frame, "Blocked Requests", "0", 0, 1, bootstyle=DANGER)
        self.lbl_waf_blocks = self._create_stat_card(card_frame, "WAF Blocks", "0", 1, 0, bootstyle=WARNING)
        self.lbl_active_ips = self._create_stat_card(card_frame, "Active IPs (Tracked)", "0", 1, 1, bootstyle=INFO)

        # Rate Limit Control
        limit_frame = ttk.LabelFrame(left_panel, text="Anti-DDoS Configuration", padding=15)
        limit_frame.pack(fill=X, pady=20)
        
        ttk.Label(limit_frame, text="Max Requests / Second:").pack(side=LEFT, padx=5)
        self.var_rate_limit = ttk.StringVar(value="10000")
        self.entry_limit = ttk.Entry(limit_frame, textvariable=self.var_rate_limit, width=15)
        self.entry_limit.pack(side=LEFT, padx=5)
        ttk.Button(limit_frame, text="Update Limit", style=SUCCESS, command=self.on_set_limit).pack(side=LEFT, padx=10)

        # Right Panel (Bans)
        right_panel = ttk.LabelFrame(main_frame, text="Blocklist Management", padding=15)
        right_panel.pack(side=RIGHT, fill=BOTH, expand=YES)

        # Actions
        action_frame = ttk.Frame(right_panel)
        action_frame.pack(fill=X, pady=(0, 10))
        
        self.var_ban_ip = ttk.StringVar()
        ttk.Entry(action_frame, textvariable=self.var_ban_ip, width=20).pack(side=LEFT, padx=5)
        ttk.Button(action_frame, text="Ban IP", style=DANGER, command=self.on_ban_ip).pack(side=LEFT, padx=5)
        ttk.Button(action_frame, text="Unban IP", style=SECONDARY, command=self.on_unban_ip).pack(side=LEFT, padx=5)

        # Blocked IPs List
        self.tree_blocked = ttk.Treeview(right_panel, columns=("ip"), show="headings", height=15)
        self.tree_blocked.heading("ip", text="Banned IP Address")
        self.tree_blocked.pack(fill=BOTH, expand=YES)
        
        # Status Bar
        self.status_var = ttk.StringVar(value="Initializing...")
        ttk.Label(self, textvariable=self.status_var, padding=5, bootstyle=SECONDARY).pack(side=BOTTOM, fill=X)


    def _create_stat_card(self, parent, title, value, row, col, bootstyle=PRIMARY):
        frame = ttk.Frame(parent, bootstyle=bootstyle)
        frame.grid(row=row, column=col, padx=5, pady=5, sticky=NSEW)
        parent.columnconfigure(col, weight=1)
        
        ttk.Label(frame, text=title, font=("Helvetica", 10)).pack(pady=(10, 0))
        val_lbl = ttk.Label(frame, text=value, font=("Helvetica", 24, "bold"))
        val_lbl.pack(pady=(0, 10))
        return val_lbl

    def _start_auto_refresh(self):
        self.refresh_dashboard()
        self.after(2000, self._start_auto_refresh)

    def refresh_dashboard(self):
        self.run_async(self._send_ipc_command("status"), self._update_ui_stats)

    def _update_ui_stats(self, response):
        if not response:
            self.status_var.set("Disconnected. Is server.py running?")
            return
            
        if response.get("status") == "ok":
            data = response.get("data", {})
            self.lbl_total_req.config(text=str(data.get("total_requests", 0)))
            self.lbl_blocked_req.config(text=str(data.get("blocked_requests", 0)))
            self.lbl_waf_blocks.config(text=str(data.get("waf_blocks", 0)))
            self.lbl_active_ips.config(text=str(data.get("active_ips_count", 0)))
            
            # Don't overwrite string var if user is typing, just placeholder for logic if needed
            # self.var_rate_limit.set(str(data.get("rate_limit", 10000)))
            
            # Update treeview
            for item in self.tree_blocked.get_children():
                self.tree_blocked.delete(item)
            for ip in data.get("blocked_ips", []):
                self.tree_blocked.insert("", END, values=(ip,))
                
            self.status_var.set("Connected and monitoring live traffic...")
        else:
            self.status_var.set(response.get("message", "Error fetching stats"))

    def on_set_limit(self):
        limit = self.var_rate_limit.get()
        if not limit.isdigit():
            messagebox.showerror("Error", "Limit must be a number")
            return
        
        self.run_async(self._send_ipc_command("set_limit", [limit]), self._show_result)

    def on_ban_ip(self):
        ip = self.var_ban_ip.get().strip()
        if ip:
            self.run_async(self._send_ipc_command("ban", [ip]), self._show_result)
            self.var_ban_ip.set("")

    def on_unban_ip(self):
        ip = self.var_ban_ip.get().strip()
        # Alternatively pull from treeview selection
        selection = self.tree_blocked.selection()
        if selection and not ip:
            ip = self.tree_blocked.item(selection[0])['values'][0]

        if ip:
            self.run_async(self._send_ipc_command("unban", [ip]), self._show_result)
            self.var_ban_ip.set("")

    def _show_result(self, response):
        if response:
            if response.get("status") == "ok":
                self.status_var.set(f"Success: {response.get('message')}")
                # Refresh immediately
                self.run_async(self._send_ipc_command("status"), self._update_ui_stats)
            else:
                messagebox.showerror("Error", response.get("message", "Unknown error"))
        else:
            messagebox.showerror("Error", "No response from server")

if __name__ == "__main__":
    app = SecurityAdminGUI()
    app.mainloop()
