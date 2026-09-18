import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading, queue, time, json, os
from datetime import datetime
from token_manager import get_valid_token

# ================================================================
# ---------------- Device Type Mapping --------------------------
# ================================================================
DEVICE_MAPPING = {
    "Axioma ssl":  {"Device model ID": "AXIO/QALW1A.1.0.2b_ETSI",  "Connection IDs": "78446"},
    "Powogaz ssl": {"Device model ID": "LORA/GenericB.1.0.2c_ETSI", "Connection IDs": "78441"},
    "Addra ssl":   {"Device model ID": "LORA/GenericA.1.0.2c_ETSI", "Connection IDs": "78444"},
}

DOMAINS = [
    "Elassona", "Katerini", "Kerkira", "Kozani",
    "Larisa", "Livadia", "Mandra", "Metsovo",
    "Oinousses", "Prespes", "Spetses", "Thiva",
    "Trikala", "Preveza", "Kalamata", "Preveza"
]

API_ROOT = "https://thingparkenterprise.eu.actility.com/thingpark/dx/core/latest/api/"
DEVICES_URL = API_ROOT + "devices/"

BG = "#f5f5f5"
PANEL_BG = "#ffffff"
BORDER = "#d0d0d0"
TEXT_DARK = "#1a1a1a"
TEXT_MID = "#666666"
TEXT_LIGHT = "#999999"
ACCENT = "#3a3a3a"
LOG_BG = "#1c1c1c"
LOG_FG = "#d4d4d4"
LOG_OK = "#6dbf67"
LOG_ERR = "#c0392b"
LOG_WARN = "#b8860b"
LOG_INFO = "#7a9cbf"

FONT_UI = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_HEAD = ("Segoe UI", 12, "bold")
FONT_MONO = ("Consolas", 8)

STATUS_LOG_COLORS = {
    "Created": LOG_OK, "Updated": LOG_OK, "Deleted": LOG_ERR,
    "Successful": LOG_OK, "Failed": LOG_ERR, "Exists": LOG_WARN,
    "Found": LOG_INFO, "NotFound": TEXT_MID,
}

def normalize_dev_eui(raw_eui):
    if not raw_eui:
        return None, None
    s = str(raw_eui).strip().replace("-", "").replace(":", "").replace(" ", "")
    if s.lower().startswith("e") and len(s) == 17:
        s = s[1:]
    return f"e{s.upper()}", s.upper()

def extract_error(response):
    try:
        text = response.text.strip()
        try:
            data = response.json()
            return f"Pre-check error (status {response.status_code}): {json.dumps(data, ensure_ascii=False)}"
        except json.JSONDecodeError:
            return f"Pre-check error (status {response.status_code}): {text}"
    except Exception as e:
        return f"Error extracting message: {str(e)}"

def safe_request(session, method, url, headers=None, payload=None, retries=3):
    for attempt in range(retries):
        try:
            if method == "GET": r = session.get(url, headers=headers, timeout=20)
            elif method == "POST": r = session.post(url, headers=headers, json=payload, timeout=30)
            elif method == "DELETE": r = session.delete(url, headers=headers, timeout=25)
            elif method == "PUT": r = session.put(url, headers=headers, json=payload, timeout=30)
            else: return None
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            return r
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None

def check_device(session, headers, device_ref):
    try:
        r = safe_request(session, "GET", DEVICES_URL + device_ref, headers=headers)
        if r is None: return {"exists": False, "raw": "No response"}
        if r.status_code == 200: return {"exists": True, "raw": r.text, "data": r.json()}
        if r.status_code == 404: return {"exists": False, "raw": r.text}
        return {"exists": False, "raw": r.text}
    except Exception as e:
        return {"exists": False, "raw": str(e)}

def worker_create(row, headers, mapping, domain, session):
    meter = row.get("Meter No.", "")
    raw_dev = row.get("Dev EUI (OTAA)", "") or row.get("DevEUI", "")
    dev_ref, dev_eui = normalize_dev_eui(raw_dev)
    timestamp = datetime.now().isoformat()
    if not dev_ref:
        return {"Meter No.": meter, "DevEUI": raw_dev, "Status": "Failed", "Message": "Invalid DevEUI", "Timestamp": timestamp}
    exists = check_device(session, headers, dev_ref)
    if exists.get("exists"):
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Exists", "Message": "Already exists", "Timestamp": timestamp}
    def is_valid_number(x):
        try:
            val = float(x)
            return val == val and val not in (float("inf"), float("-inf"))
        except: return False
    raw_lat, raw_long = row.get("lat", None), row.get("long", None)
    payload = {
        "name": meter, "EUI": dev_eui, "activationType": "OTAA",
        "deviceProfileId": mapping["Device model ID"], "processingStrategyId": "ROUTE",
        "applicationEUI": row.get("App EUI (OTAA)", ""),
        "applicationKey": row.get("Lora App Key (OTAA)", ""),
        "connectivityPlanName": row.get("connectivityPlanName", "Basic Unicast"),
        "routeRefs": [mapping["Connection IDs"]],
        "domains": [{"name": domain, "group": {"name": "Projects"}}],
    }
    if is_valid_number(raw_lat) and is_valid_number(raw_long):
        lat, lng = float(raw_lat), float(raw_long)
        payload["geoLatitude"], payload["geoLongitude"] = lat, lng
        payload["location"] = {"locationType": "MANUAL", "latitude": lat, "longitude": lng}
    try:
        r = session.post(DEVICES_URL, headers=headers, json=payload, timeout=60)
    except Exception as e:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": f"Request exception: {e}", "Timestamp": timestamp}
    if r is None:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": "No response from server", "Timestamp": timestamp}
    if r.status_code in (200, 201):
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Created", "Message": f"HTTP {r.status_code}", "Timestamp": timestamp}
    return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": f"Pre-check error (status {r.status_code}): {r.text}", "Timestamp": timestamp}

def worker_get(row, headers, session):
    raw_dev = row.get("Dev EUI (OTAA)", "") or row.get("DevEUI", "")
    dev_ref, _ = normalize_dev_eui(raw_dev)
    meter, timestamp = row.get("Meter No.", ""), datetime.now().isoformat()
    if not dev_ref:
        return {"Meter No.": meter, "DevEUI": raw_dev, "Status": "Failed", "Message": "Invalid DevEUI", "Timestamp": timestamp}
    r = safe_request(session, "GET", DEVICES_URL + dev_ref, headers=headers)
    if r is None:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": "No response", "Timestamp": timestamp}
    if r.status_code == 404:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "NotFound", "Message": "Device not found", "Timestamp": timestamp}
    if r.status_code == 200:
        try: data = r.json()
        except: data = {}
        result = {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Found", "Timestamp": timestamp}
        def flatten(obj, prefix=""):
            if isinstance(obj, dict):
                for k, v in obj.items(): flatten(v, f"{prefix}{k}.")
            elif isinstance(obj, list):
                for i, v in enumerate(obj): flatten(v, f"{prefix}{i}.")
            else: result[prefix.rstrip(".")] = obj
        flatten(data)
        return result
    return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": extract_error(r), "Timestamp": timestamp}

def worker_delete(row, headers, session):
    raw_dev = row.get("Dev EUI (OTAA)", "") or row.get("DevEUI", "")
    dev_ref, _ = normalize_dev_eui(raw_dev)
    meter, timestamp = row.get("Meter No.", ""), datetime.now().isoformat()
    if not dev_ref:
        return {"Meter No.": meter, "DevEUI": raw_dev, "Status": "Failed", "Message": "Invalid DevEUI", "Timestamp": timestamp}
    exists = check_device(session, headers, dev_ref)
    if not exists.get("exists"):
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "NotFound", "Message": "Not found", "Timestamp": timestamp}
    time.sleep(0.3)
    r = safe_request(session, "DELETE", DEVICES_URL + dev_ref, headers=headers)
    if r is None:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": "No response", "Timestamp": timestamp}
    if r.status_code in (200, 204):
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Successful", "Message": f"HTTP {r.status_code}", "Timestamp": timestamp}
    return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": extract_error(r), "Timestamp": timestamp}

def worker_update(row, headers, session, ref_conn_id):
    raw_dev = row.get("Dev EUI (OTAA)", "") or row.get("DevEUI", "")
    dev_ref, dev_eui = normalize_dev_eui(raw_dev)
    meter, timestamp = row.get("Meter No.", ""), datetime.now().isoformat()
    if not dev_ref:
        return {"Meter No.": meter, "DevEUI": raw_dev, "Status": "Failed", "Message": "Invalid DevEUI", "Timestamp": timestamp}
    exists = check_device(session, headers, dev_ref)
    if not exists.get("exists"):
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "NotFound", "Message": "Device not found", "Timestamp": timestamp}
    payload = {"ref": ref_conn_id, "EUI": dev_eui, "domains": [{"name": "Elassona", "group": {"name": "Projects"}}]}
    r = safe_request(session, "PUT", DEVICES_URL + dev_ref, headers=headers, payload=payload)
    if r is None:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": "No response", "Timestamp": timestamp}
    if r.status_code == 200:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Updated", "Message": f"ref={ref_conn_id} (HTTP 200)", "Timestamp": timestamp}
    return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": extract_error(r), "Timestamp": timestamp}

RESET_CONNECTIVITY_PLAN = "reset"
TARGET_CONNECTIVITY_PLAN = "actility-tpe-cs/tpe-cp"

def worker_restart(row, headers, session, ref_conn_id):
    raw_dev = row.get("Dev EUI (OTAA)", "") or row.get("DevEUI", "")
    dev_ref, dev_eui = normalize_dev_eui(raw_dev)
    meter, timestamp = row.get("Meter No.", ""), datetime.now().isoformat()
    if not dev_ref:
        return {"Meter No.": meter, "DevEUI": raw_dev, "Status": "Failed", "Message": "Invalid DevEUI", "Timestamp": timestamp, "Phase": "Reset"}
    exists = check_device(session, headers, dev_ref)
    if not exists.get("exists"):
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "NotFound", "Message": "Device not found", "Timestamp": timestamp, "Phase": "Reset"}
    reset_payload = {"ref": ref_conn_id, "EUI": dev_eui, "connectivityPlanId": RESET_CONNECTIVITY_PLAN}
    reset_response = safe_request(session, "PUT", DEVICES_URL + dev_ref, headers=headers, payload=reset_payload)
    if reset_response is None:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": "No response during connectivity plan reset", "Timestamp": timestamp, "Phase": "Reset"}
    if reset_response.status_code != 200:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": f"Reset failed: {extract_error(reset_response)}", "Timestamp": timestamp, "Phase": "Reset"}
    target_payload = {"ref": ref_conn_id, "EUI": dev_eui, "connectivityPlanId": TARGET_CONNECTIVITY_PLAN}
    target_response = safe_request(session, "PUT", DEVICES_URL + dev_ref, headers=headers, payload=target_payload)
    if target_response is None:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": "Reset succeeded, but no response while restoring connectivity plan", "Timestamp": timestamp, "Phase": "Restore"}
    if target_response.status_code == 200:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Successful", "Message": f"Restart completed: reset -> {RESET_CONNECTIVITY_PLAN}, restore -> {TARGET_CONNECTIVITY_PLAN} (HTTP 200)", "Timestamp": timestamp, "Phase": "Restore"}
    return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": f"Reset succeeded, but restore failed: {extract_error(target_response)}", "Timestamp": timestamp, "Phase": "Restore"}

def worker_update_domain(row, headers, session, ref_conn_id, domain):
    raw_dev = row.get("Dev EUI (OTAA)", "") or row.get("DevEUI", "")
    dev_ref, dev_eui = normalize_dev_eui(raw_dev)
    meter, timestamp = row.get("Meter No.", ""), datetime.now().isoformat()
    if not dev_ref:
        return {"Meter No.": meter, "DevEUI": raw_dev, "Status": "Failed", "Message": "Invalid DevEUI", "Timestamp": timestamp}
    exists = check_device(session, headers, dev_ref)
    if not exists.get("exists"):
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "NotFound", "Message": "Device not found", "Timestamp": timestamp}
    payload = {"ref": ref_conn_id, "EUI": dev_eui, "domains": [{"name": domain, "group": {"name": "Projects"}}]}
    response = safe_request(session, "PUT", DEVICES_URL + dev_ref, headers=headers, payload=payload)
    if response is None:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": "No response", "Timestamp": timestamp}
    if response.status_code == 200:
        return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Updated", "Message": f"domain={domain} (HTTP 200)", "Timestamp": timestamp}
    return {"Meter No.": meter, "DevEUI": dev_ref, "Status": "Failed", "Message": extract_error(response), "Timestamp": timestamp}

SIDEBAR_BG = "#242424"
SIDEBAR_ACTIVE = "#4a4a4a"
SIDEBAR_TEXT = "#f2f2f2"
SIDEBAR_MUTED = "#a8a8a8"
CONTENT_BG = "#ffffff"
CONTENT_BORDER = "#d0d0d0"

def make_button(parent, text, command, width=None, height=None):
    kwargs = {"text": text, "command": command, "bg": ACCENT, "fg": "white", "font": FONT_BOLD,
              "relief": "flat", "bd": 0, "activebackground": "#555555", "activeforeground": "white",
              "cursor": "hand2", "padx": 12, "pady": 6}
    if width is not None: kwargs["width"] = width
    if height is not None: kwargs["height"] = height
    return tk.Button(parent, **kwargs)

class ProgressPanel:
    def __init__(self, parent):
        self.parent = parent
        self.total = self.completed = self.ok = self.fail = self.warn = self.nf = 0
        self.frame = tk.LabelFrame(parent, text="  Batch progress  ", font=FONT_UI, bg=CONTENT_BG,
                                   fg=TEXT_MID, bd=1, relief="groove", padx=10, pady=8)
        self.counter_text = tk.StringVar(value="Successful  0     Failed  0     Not found  0     Other  0")
        tk.Label(self.frame, textvariable=self.counter_text, font=FONT_UI, bg=CONTENT_BG,
                 fg=TEXT_MID, anchor="w").pack(fill="x", pady=(0, 7))
        style = ttk.Style()
        try: style.configure("Actility.Horizontal.TProgressbar", troughcolor="#dddddd", background="#3a3a3a", thickness=10)
        except tk.TclError: pass
        self.progress_value = tk.DoubleVar(value=0)
        ttk.Progressbar(self.frame, variable=self.progress_value, maximum=100,
                        style="Actility.Horizontal.TProgressbar").pack(fill="x")
        self.progress_text = tk.StringVar(value="0 / 0")
        tk.Label(self.frame, textvariable=self.progress_text, font=("Segoe UI", 8), bg=CONTENT_BG,
                 fg=TEXT_LIGHT, anchor="w").pack(fill="x", pady=(3, 0))

    def reset(self, total):
        self.total, self.completed = total, 0
        self.ok = self.fail = self.warn = self.nf = 0
        self.progress_value.set(0); self.progress_text.set(f"0 / {total}")
        self.counter_text.set("Successful  0     Failed  0     Not found  0     Other  0")

    def add(self, item):
        self.completed += 1
        status = item.get("Status", "")
        if status in ("Created", "Updated", "Found", "Successful"): self.ok += 1
        elif status == "Exists": self.warn += 1
        elif status == "NotFound": self.nf += 1
        else: self.fail += 1
        pct = int(self.completed / self.total * 100) if self.total else 100
        self.progress_value.set(pct); self.progress_text.set(f"{self.completed} / {self.total}  ({pct}%)")
        self.counter_text.set(f"Successful  {self.ok}     Failed  {self.fail}     Not found  {self.nf}     Other  {self.warn}")

class OperationPage:
    TITLES = {
        "create": ("Create OTAA Devices", "Create OTAA devices from an Excel file."),
        "get": ("Get Devices", "Get devices from ThingPark Enterprise."),
        "delete": ("Delete Devices", "Delete devices from ThingPark Enterprise."),
        "update": ("Update Connectivity", "Update device connectivity configuration."),
        "domain": ("Update Domain", "Assign devices to a ThingPark Enterprise domain."),
        "restart": ("Restart", "Reset and restore the connectivity plan for devices."),
    }
    def __init__(self, app, operation):
        self.app, self.operation = app, operation
        self.title, self.subtitle = self.TITLES[operation]
        self.file_path = tk.StringVar()
        self.domain = tk.StringVar(value=DOMAINS[0])
        self.device_type = tk.StringVar(value=list(DEVICE_MAPPING.keys())[0])
        self.connection_label = tk.StringVar(value=self.connection_labels()[0])
        self.threads = tk.IntVar(value=30)
        self.container = tk.Frame(app.content, bg=CONTENT_BG)
        self.container.pack(fill="both", expand=True)
        self.build()

    def connection_labels(self):
        return [f"{name}  →  {cfg['Connection IDs']}" for name, cfg in DEVICE_MAPPING.items()]

    def selected_connection_id(self):
        label = self.connection_label.get()
        for name, cfg in DEVICE_MAPPING.items():
            if label == f"{name}  →  {cfg['Connection IDs']}": return cfg["Connection IDs"]
        return list(DEVICE_MAPPING.values())[0]["Connection IDs"]

    def section(self, title, parent=None):
        if parent is None: parent = self.container
        return tk.LabelFrame(parent, text=f"  {title}  ", font=FONT_UI, bg=CONTENT_BG,
                             fg=TEXT_MID, bd=1, relief="groove", padx=8, pady=7)

    def build(self):
        tk.Label(self.container, text=self.title, font=("Segoe UI", 16, "bold"), bg=CONTENT_BG,
                 fg=TEXT_DARK, anchor="w").pack(fill="x", padx=28, pady=(18, 1))
        tk.Label(self.container, text=self.subtitle, font=("Segoe UI", 9), bg=CONTENT_BG,
                 fg=TEXT_LIGHT, anchor="w").pack(fill="x", padx=28, pady=(0, 12))
        form = tk.Frame(self.container, bg=CONTENT_BG)
        form.pack(fill="both", expand=True, padx=28)
        file_frame = self.section("Excel file", form)
        file_frame.pack(fill="x", pady=(0, 7))
        tk.Entry(file_frame, textvariable=self.file_path, font=FONT_UI, bg=PANEL_BG,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, padx=(0, 7))
        make_button(file_frame, "Browse...", self.browse_file, width=10).pack(side="left")
        options = tk.Frame(form, bg=CONTENT_BG); options.pack(fill="x")
        if self.operation == "create":
            self.combo_box(options, "Domain", self.domain, DOMAINS, 22).pack(side="left", fill="x", expand=True, padx=(0, 7))
            self.combo_box(options, "Device type", self.device_type, list(DEVICE_MAPPING.keys()), 19).pack(side="left", fill="x", expand=True, padx=(0, 7))
        elif self.operation in ("update", "domain", "restart"):
            self.combo_box(options, "Ref (Connection ID)", self.connection_label, self.connection_labels(), 31).pack(side="left", fill="x", expand=True, padx=(0, 7))
            if self.operation == "domain":
                self.combo_box(options, "Domain", self.domain, DOMAINS, 18).pack(side="left", fill="x", expand=True, padx=(0, 7))
        self.threads_box(options).pack(side="left")
        button_text = {
            "create": "Run — Create OTAA Devices", "get": "Run — Get Devices",
            "delete": "Run — Delete Devices", "update": "Run — Update Connectivity",
            "domain": "Run — Update Domain", "restart": "Run — Restart",
        }[self.operation]
        self.run_button = make_button(form, button_text, self.run, width=26)
        self.run_button.pack(anchor="w", pady=(10, 10))
        self.progress_panel = ProgressPanel(form)
        self.progress_panel.frame.pack(fill="x", pady=(0, 7))
        log_frame = tk.LabelFrame(form, text="  Activity log  ", font=FONT_UI, bg=CONTENT_BG,
                                  fg=TEXT_MID, bd=1, relief="groove", padx=7, pady=5)
        log_frame.pack(fill="both", expand=True, pady=(0, 5))
        self.log = tk.Text(log_frame, font=FONT_MONO, bg=LOG_BG, fg=LOG_FG,
                           relief="flat", state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y"); self.log.pack(fill="both", expand=True)
        for status, color in STATUS_LOG_COLORS.items():
            self.log.tag_config(status, foreground=color, font=("Consolas", 8, "bold"))
        self.status_text = tk.StringVar(value="Ready")
        tk.Label(self.container, textvariable=self.status_text, font=("Segoe UI", 8), bg=CONTENT_BG,
                 fg=TEXT_LIGHT, anchor="w").pack(fill="x", padx=28, pady=(0, 7))

    def combo_box(self, parent, label, variable, values, width):
        frame = self.section(label, parent)
        ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=width).pack(anchor="w")
        return frame

    def threads_box(self, parent):
        frame = self.section("Threads", parent)
        tk.Entry(frame, textvariable=self.threads, font=FONT_UI, width=6, bg=PANEL_BG,
                 relief="solid", bd=1).pack(anchor="w")
        return frame

    def browse_file(self):
        selected = filedialog.askopenfilename(parent=self.app.root, title="Select Excel file",
                                              filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")])
        if selected:
            self.file_path.set(selected); self.status_text.set(f"Selected: {os.path.basename(selected)}")

    def log_item(self, item):
        status, dev_eui, message, phase = item.get("Status", ""), item.get("DevEUI", ""), item.get("Message", ""), item.get("Phase", "")
        prefix = f"[{status}]" + (f" [{phase}]" if phase else "")
        self.log.configure(state="normal"); self.log.insert("end", prefix, status)
        self.log.insert("end", f"  {dev_eui}  —  {message}\n"); self.log.see("end"); self.log.configure(state="disabled")

    def reset_run_state(self, total):
        self.app.total_tasks, self.app.completed_tasks = total, 0
        self.app.results, self.app.result_queue = [], queue.Queue()
        self.progress_panel.reset(total)
        self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")

    def load_dataframe(self):
        if not self.file_path.get():
            messagebox.showerror("Error", "No Excel file selected.", parent=self.app.root); return None
        try: df = pd.read_excel(self.file_path.get(), dtype=str, keep_default_na=False)
        except Exception as exc:
            messagebox.showerror("Excel error", f"Failed to read Excel file:\n{exc}", parent=self.app.root); return None
        if df.empty:
            messagebox.showerror("Error", "The selected Excel file contains no rows.", parent=self.app.root); return None
        return df

    def run(self):
        if self.app.is_running: return
        df = self.load_dataframe()
        if df is None: return
        if self.operation == "delete" and not messagebox.askyesno("Confirm Delete", "Are you sure you want to delete the selected devices?", parent=self.app.root): return
        if self.operation == "restart" and not messagebox.askyesno("Confirm Restart", "Restart the selected devices?\n\nThe connectivity plan will be reset and then restored.", parent=self.app.root): return
        try: threads = max(1, int(self.threads.get()))
        except (TypeError, ValueError):
            messagebox.showerror("Error", "Threads must be a positive integer.", parent=self.app.root); return
        self.reset_run_state(len(df)); self.app.is_running = True; self.run_button.configure(state="disabled")
        headers = {"accept": "application/json", "Authorization": f"Bearer {self.app.token}", "Content-Type": "application/json"}
        out_dir = os.path.dirname(self.file_path.get()); stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = ".xlsx" if self.operation == "get" else ".csv"
        self.app.output_path = os.path.join(out_dir, f"{self.operation}_results_{stamp}{extension}")
        self.status_text.set("Running...")
        rows = [row for _, row in df.iterrows()]
        connection_id, domain, device_type = self.selected_connection_id(), self.domain.get(), self.device_type.get()

        def run_batch():
            try:
                with ThreadPoolExecutor(max_workers=threads, thread_name_prefix="actility") as executor:
                    futures = []
                    for row in rows:
                        if self.operation == "create": future = executor.submit(worker_create, row, headers, DEVICE_MAPPING[device_type], domain, self.app.session)
                        elif self.operation == "get": future = executor.submit(worker_get, row, headers, self.app.session)
                        elif self.operation == "delete": future = executor.submit(worker_delete, row, headers, self.app.session)
                        elif self.operation == "update": future = executor.submit(worker_update, row, headers, self.app.session, connection_id)
                        elif self.operation == "domain": future = executor.submit(worker_update_domain, row, headers, self.app.session, connection_id, domain)
                        elif self.operation == "restart": future = executor.submit(worker_restart, row, headers, self.app.session, connection_id)
                        else: continue
                        futures.append(future)
                    for future in as_completed(futures):
                        try: result = future.result()
                        except Exception as exc:
                            result = {"Meter No.": "", "DevEUI": "", "Status": "Failed", "Message": f"Unexpected worker error: {exc}", "Timestamp": datetime.now().isoformat()}
                        self.app.result_queue.put(result)
            except Exception as exc:
                self.app.result_queue.put({"Meter No.": "", "DevEUI": "", "Status": "Failed", "Message": f"Batch error: {exc}", "Timestamp": datetime.now().isoformat()})
        threading.Thread(target=run_batch, daemon=True, name=f"actility-{self.operation}").start()
        self.app.poll_queue(self)

    def finish(self):
        try:
            df_out = pd.DataFrame(self.app.results)
            if self.operation == "get": df_out.to_excel(self.app.output_path, index=False, engine="openpyxl")
            else: df_out.to_csv(self.app.output_path, index=False, encoding="utf-8")
        except Exception as exc:
            self.app.is_running = False; self.run_button.configure(state="normal")
            messagebox.showerror("Save failed", f"Failed to save output file:\n{exc}", parent=self.app.root); return
        self.app.is_running = False; self.run_button.configure(state="normal")
        self.status_text.set(f"Completed — saved to {os.path.basename(self.app.output_path)}")
        messagebox.showinfo("Completed", f"Total     : {self.app.total_tasks}\nSuccessful: {self.progress_panel.ok}\nFailed    : {self.progress_panel.fail}\nNot found : {self.progress_panel.nf}\n\nSaved to: {os.path.basename(self.app.output_path)}", parent=self.app.root)

class DeviceManagerApp:
    OPERATIONS = (
        ("create", "Create OTAA Devices"), ("get", "Get Devices"), ("delete", "Delete Devices"),
        ("update", "Update Connectivity"), ("domain", "Update Domain"), ("restart", "Restart"),
    )
    def __init__(self, root):
        self.root = root; self.root.title("Actility Device Manager"); self.root.geometry("1100x720")
        self.root.minsize(900, 620); self.root.configure(bg=CONTENT_BG)
        self.is_running = False; self.token = get_valid_token(); self.session = requests.Session()
        self.content = None; self.nav_buttons = {}; self.current_page = None
        self.total_tasks = self.completed_tasks = 0; self.results = []; self.result_queue = queue.Queue(); self.output_path = None
        if not self.token:
            messagebox.showerror("Error", "Failed to obtain access token.", parent=root); root.destroy(); return
        self.build_shell(); self.show_operation("create")

    def build_shell(self):
        sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=216); sidebar.pack(side="left", fill="y"); sidebar.pack_propagate(False)
        tk.Label(sidebar, text="ACTILITY", font=("Segoe UI", 17, "bold"), bg=SIDEBAR_BG, fg=SIDEBAR_TEXT, anchor="w").pack(fill="x", padx=12, pady=(18, 1))
        tk.Label(sidebar, text="ThingPark Enterprise", font=("Segoe UI", 8), bg=SIDEBAR_BG, fg=SIDEBAR_MUTED, anchor="w").pack(fill="x", padx=12, pady=(0, 28))
        for operation, label in self.OPERATIONS:
            button = tk.Button(sidebar, text=label, command=lambda op=operation: self.show_operation(op),
                               bg=SIDEBAR_BG, fg=SIDEBAR_TEXT, font=FONT_UI, anchor="w", relief="flat", bd=0,
                               padx=12, pady=8, activebackground=SIDEBAR_ACTIVE, activeforeground="white", cursor="hand2")
            button.pack(fill="x"); self.nav_buttons[operation] = button
        footer = tk.Frame(sidebar, bg=SIDEBAR_BG); footer.pack(side="bottom", fill="x", padx=12, pady=12)
        tk.Label(footer, text="Token managed by token_manager", font=("Segoe UI", 7), bg=SIDEBAR_BG, fg=SIDEBAR_MUTED, anchor="w").pack(fill="x")
        self.content = tk.Frame(self.root, bg=CONTENT_BG); self.content.pack(side="left", fill="both", expand=True)

    def show_operation(self, operation):
        if self.is_running:
            messagebox.showwarning("Operation running", "Please wait for the current operation to finish.", parent=self.root); return
        for op, button in self.nav_buttons.items(): button.configure(bg=SIDEBAR_ACTIVE if op == operation else SIDEBAR_BG)
        for widget in self.content.winfo_children(): widget.destroy()
        self.current_page = OperationPage(self, operation)

    def poll_queue(self, page):
        while True:
            try: item = self.result_queue.get_nowait()
            except queue.Empty: break
            self.results.append(item); self.completed_tasks += 1; page.log_item(item); page.progress_panel.add(item)
        if self.completed_tasks >= self.total_tasks and self.total_tasks > 0: page.finish(); return
        if self.is_running: self.root.after(150, lambda: self.poll_queue(page))

if __name__ == "__main__":
    root = tk.Tk()
    DeviceManagerApp(root)
    root.mainloop()
