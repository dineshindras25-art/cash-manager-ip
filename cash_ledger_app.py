"""
Cash Ledger — Cash In / Out Monitor (Python Desktop Edition)
--------------------------------------------------------------
A modern desktop app (CustomTkinter) that reads/writes the SAME Firebase
Realtime Database used by the web version, so both stay in sync.

Setup:
    pip install customtkinter requests

Run:
    python cash_ledger_app.py
"""

import threading
import csv
import uuid
from datetime import datetime, date

import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

# ============================================================
#  CONFIG — same Firebase project as the web app
# ============================================================
DB_URL = "https://cash-manager-ip-default-rtdb.asia-southeast1.firebasedatabase.app"
POLL_INTERVAL_MS = 6000

DEFAULT_CATEGORIES = [
    "Sales Collection", "Customer Payment", "Supplier Payment",
    "Transport / Freight", "Office Expense", "Bank Withdrawal",
    "Bank Deposit", "Other",
]

# ============================================================
#  COLOR PALETTE — mirrors the web app's ledger-tape design
# ============================================================
C = {
    "bg":        "#1c2321",
    "panel":     "#232b27",
    "panel2":    "#2b342f",
    "line":      "#3a453e",
    "brass":     "#c9a227",
    "brass_soft":"#e3c766",
    "in":        "#4f9d6e",
    "out":       "#c1502e",
    "muted":     "#9aa79e",
    "white":     "#f5f6f1",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

FONT_MONO = ("Consolas", 12)
FONT_MONO_BOLD = ("Consolas", 13, "bold")
FONT_LABEL = ("Consolas", 10)
FONT_TITLE = ("Georgia", 14, "bold")


def fmt_money(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        n = 0
    return f"₹{n:,.2f}"


# ============================================================
#  FIREBASE REST CLIENT
# ============================================================
class FirebaseClient:
    """Thin wrapper around the Firebase Realtime Database REST API."""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def _url(self, path):
        return f"{self.base_url}/{path}.json"

    def get(self, path):
        r = requests.get(self._url(path), timeout=10)
        r.raise_for_status()
        return r.json()

    def set(self, path, value):
        r = requests.put(self._url(path), json=value, timeout=10)
        r.raise_for_status()
        return r.json()

    def push(self, path, value):
        r = requests.post(self._url(path), json=value, timeout=10)
        r.raise_for_status()
        return r.json().get("name")

    def update(self, path, value):
        r = requests.patch(self._url(path), json=value, timeout=10)
        r.raise_for_status()
        return r.json()

    def delete(self, path):
        r = requests.delete(self._url(path), timeout=10)
        r.raise_for_status()


# ============================================================
#  CATEGORY MANAGER (modal window)
# ============================================================
class CategoryManagerWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Manage Categories")
        self.geometry("420x520")
        self.configure(fg_color=C["panel"])
        self.transient(app)
        self.grab_set()

        ctk.CTkLabel(self, text="MANAGE CATEGORIES", font=FONT_TITLE,
                     text_color=C["brass_soft"]).pack(anchor="w", padx=20, pady=(18, 10))

        add_row = ctk.CTkFrame(self, fg_color="transparent")
        add_row.pack(fill="x", padx=20)
        self.new_cat_entry = ctk.CTkEntry(add_row, placeholder_text="e.g. Loading Charges",
                                           fg_color=C["panel2"], border_color=C["line"])
        self.new_cat_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(add_row, text="Add", width=70, fg_color=C["brass"],
                      text_color="#241c04", hover_color=C["brass_soft"],
                      command=self.add_category).pack(side="left")

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=C["bg"])
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(
            self,
            text="Renaming updates every past entry using it.\nDeleting only removes it from the picker.",
            font=FONT_LABEL, text_color=C["muted"], justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 16))

        self.render_list()

    def render_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        cats = self.app.categories
        if not cats:
            ctk.CTkLabel(self.list_frame, text="No categories yet. Add one above.",
                         text_color=C["muted"], font=FONT_LABEL).pack(pady=10)
            return

        for cat in cats:
            row = ctk.CTkFrame(self.list_frame, fg_color=C["panel2"])
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=cat["name"], font=FONT_MONO,
                         text_color=C["white"]).pack(side="left", padx=10, pady=8)
            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=6)
            ctk.CTkButton(btns, text="Edit", width=54, height=26, font=FONT_LABEL,
                          fg_color="transparent", border_width=1, border_color=C["line"],
                          text_color=C["muted"], hover_color=C["panel"],
                          command=lambda c=cat: self.start_edit(c)).pack(side="left", padx=3)
            ctk.CTkButton(btns, text="Delete", width=60, height=26, font=FONT_LABEL,
                          fg_color="transparent", border_width=1, border_color=C["line"],
                          text_color=C["out"], hover_color=C["panel"],
                          command=lambda c=cat: self.delete_category(c)).pack(side="left")

    def add_category(self):
        name = self.new_cat_entry.get().strip()
        if not name:
            return
        if any(c["name"].lower() == name.lower() for c in self.app.categories):
            messagebox.showwarning("Duplicate", "This category already exists.")
            return
        self.new_cat_entry.delete(0, "end")
        self.app.run_bg(lambda: self.app.client.push("categories", {"name": name}),
                         on_done=lambda _: self.app.refresh_data_async())

    def start_edit(self, cat):
        win = ctk.CTkToplevel(self)
        win.title("Rename Category")
        win.geometry("320x150")
        win.configure(fg_color=C["panel"])
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text=f"Rename '{cat['name']}'", font=FONT_MONO_BOLD,
                     text_color=C["brass_soft"]).pack(pady=(18, 8))
        entry = ctk.CTkEntry(win, fg_color=C["panel2"], border_color=C["line"])
        entry.insert(0, cat["name"])
        entry.pack(padx=20, fill="x")
        entry.focus_set()
        entry.select_range(0, "end")

        def save():
            new_name = entry.get().strip()
            if not new_name or new_name == cat["name"]:
                win.destroy()
                return
            if any(c["id"] != cat["id"] and c["name"].lower() == new_name.lower()
                   for c in self.app.categories):
                messagebox.showwarning("Duplicate", "A category with this name already exists.")
                return
            win.destroy()
            self.app.rename_category(cat, new_name)

        ctk.CTkButton(win, text="Save", fg_color=C["brass"], text_color="#241c04",
                      hover_color=C["brass_soft"], command=save).pack(pady=16)

    def delete_category(self, cat):
        in_use = sum(1 for e in self.app.entries if e.get("category") == cat["name"])
        msg = (f"'{cat['name']}' is used in {in_use} transaction(s). "
               f"Remove it from the category list? Existing entries keep their label."
               if in_use else f"Delete category '{cat['name']}'?")
        if not messagebox.askyesno("Delete Category", msg):
            return
        self.app.run_bg(lambda: self.app.client.delete(f"categories/{cat['id']}"),
                         on_done=lambda _: self.app.refresh_data_async())


# ============================================================
#  MAIN APPLICATION
# ============================================================
class CashLedgerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Cash Ledger — Cash In / Out Monitor")
        self.geometry("1280x780")
        self.configure(fg_color=C["bg"])

        self.client = FirebaseClient(DB_URL)
        self.entries = []
        self.categories = []
        self.opening = 0.0
        self.current_type = "in"
        self.editing_id = None
        self.category_window = None
        self._seed_tried = False
        self.last_report_rows = []

        self._build_style()
        self._build_header()
        self._build_body()

        self.refresh_data_async()
        self.after(POLL_INTERVAL_MS, self._poll_loop)

    # -------------------- background helper --------------------
    def run_bg(self, fn, on_done=None, on_error=None):
        def target():
            try:
                result = fn()
                if on_done:
                    self.after(0, lambda: on_done(result))
            except Exception as e:
                if on_error:
                    self.after(0, lambda: on_error(e))
                else:
                    self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=target, daemon=True).start()

    def _poll_loop(self):
        self.refresh_data_async()
        self.after(POLL_INTERVAL_MS, self._poll_loop)

    # -------------------- style --------------------
    def _build_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=C["panel2"], fieldbackground=C["panel2"],
                         foreground=C["white"], rowheight=28, borderwidth=0, font=FONT_MONO)
        style.configure("Treeview.Heading", background=C["panel"], foreground=C["brass_soft"],
                         relief="flat", font=FONT_LABEL)
        style.map("Treeview", background=[("selected", C["brass"])],
                  foreground=[("selected", "#241c04")])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # -------------------- header --------------------
    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=10)
        header.pack(fill="x", padx=20, pady=(18, 10))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=20, pady=(14, 6))
        ctk.CTkLabel(title_row, text="LEDGER — CASH IN / OUT MONITOR", font=FONT_TITLE,
                     text_color=C["brass_soft"]).pack(side="left")
        self.sync_label = ctk.CTkLabel(title_row, text="● Connecting…", font=FONT_LABEL,
                                        text_color=C["muted"])
        self.sync_label.pack(side="right")

        cards = ctk.CTkFrame(header, fg_color="transparent")
        cards.pack(fill="x", padx=20, pady=(0, 16))
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1)

        self.card_opening = self._make_card(cards, "Opening Balance", C["muted"], 0)
        self.card_in = self._make_card(cards, "Total Cash In", C["in"], 1)
        self.card_out = self._make_card(cards, "Total Cash Out", C["out"], 2)
        self.card_net = self._make_card(cards, "Current Balance", C["brass_soft"], 3)

    def _make_card(self, parent, label, color, col):
        cell = ctk.CTkFrame(parent, fg_color=C["bg"], corner_radius=6,
                             border_width=1, border_color=C["line"])
        cell.grid(row=0, column=col, sticky="ew", padx=6)
        ctk.CTkLabel(cell, text=label.upper(), font=FONT_LABEL,
                     text_color=C["muted"]).pack(anchor="w", padx=12, pady=(10, 0))
        value = ctk.CTkLabel(cell, text="₹0.00", font=("Consolas", 18, "bold"),
                              text_color=color)
        value.pack(anchor="w", padx=12, pady=(0, 10))
        return value

    def set_sync_status(self, ok):
        if ok:
            self.sync_label.configure(text="● Live", text_color=C["in"])
        else:
            self.sync_label.configure(text="● Offline", text_color=C["out"])

    # -------------------- body / tabs --------------------
    def _build_body(self):
        self.tabs = ctk.CTkTabview(self, fg_color=C["panel"], segmented_button_fg_color=C["panel2"],
                                    segmented_button_selected_color=C["brass"],
                                    segmented_button_selected_hover_color=C["brass_soft"],
                                    text_color=C["white"])
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.tabs.add("Ledger")
        self.tabs.add("Report")
        self._build_ledger_tab(self.tabs.tab("Ledger"))
        self._build_report_tab(self.tabs.tab("Report"))

    # ---------- Ledger tab ----------
    def _build_ledger_tab(self, parent):
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        # ---- left: entry form ----
        form = ctk.CTkFrame(parent, fg_color=C["panel2"], corner_radius=10, width=320)
        form.grid(row=0, column=0, sticky="ns", padx=(0, 14), pady=4)
        form.grid_propagate(False)

        ctk.CTkLabel(form, text="NEW ENTRY", font=FONT_TITLE,
                     text_color=C["brass_soft"]).pack(anchor="w", padx=18, pady=(16, 12))

        toggle = ctk.CTkFrame(form, fg_color="transparent")
        toggle.pack(fill="x", padx=18)
        self.btn_type_in = ctk.CTkButton(toggle, text="▲ Cash In", command=lambda: self.set_type("in"))
        self.btn_type_out = ctk.CTkButton(toggle, text="▼ Cash Out", command=lambda: self.set_type("out"))
        self.btn_type_in.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_type_out.pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.f_date = self._form_field(form, "Date (YYYY-MM-DD)")
        self.f_date.insert(0, date.today().isoformat())

        self.f_amount = self._form_field(form, "Amount (₹)")

        ctk.CTkLabel(form, text="CATEGORY", font=FONT_LABEL, text_color=C["muted"]).pack(
            anchor="w", padx=18, pady=(12, 4))
        cat_row = ctk.CTkFrame(form, fg_color="transparent")
        cat_row.pack(fill="x", padx=18)
        self.f_category = ctk.CTkOptionMenu(cat_row, values=["Loading…"], fg_color=C["panel"],
                                             button_color=C["panel"], button_hover_color=C["line"])
        self.f_category.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(form, text="⚙ Manage categories", font=FONT_LABEL, fg_color="transparent",
                      text_color=C["brass_soft"], hover_color=C["panel"], height=22,
                      command=self.open_category_manager).pack(anchor="w", padx=18, pady=(4, 0))

        self.f_party = self._form_field(form, "Party / Customer Name")
        self.f_note = self._form_field(form, "Note")

        self.editing_flag = ctk.CTkLabel(form, text="✎ Editing existing entry", font=FONT_LABEL,
                                          text_color=C["brass_soft"])

        self.btn_add = ctk.CTkButton(form, text="ADD TO LEDGER", fg_color=C["brass"],
                                      text_color="#241c04", hover_color=C["brass_soft"],
                                      command=self.submit_entry)
        self.btn_add.pack(fill="x", padx=18, pady=(16, 6))
        self.btn_cancel = ctk.CTkButton(form, text="Cancel edit", fg_color="transparent",
                                         border_width=1, border_color=C["line"], text_color=C["muted"],
                                         hover_color=C["panel"], command=self.reset_form)

        ctk.CTkLabel(form, text="Entries sync in real time via Firebase.", font=FONT_LABEL,
                     text_color=C["muted"], wraplength=280, justify="left").pack(
            anchor="w", padx=18, pady=(4, 16))

        open_row = ctk.CTkFrame(form, fg_color="transparent")
        open_row.pack(fill="x", padx=18, pady=(0, 18))
        self.f_opening = ctk.CTkEntry(open_row, placeholder_text="Opening balance",
                                       fg_color=C["panel"], border_color=C["line"])
        self.f_opening.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(open_row, text="Set", width=54, fg_color="transparent", border_width=1,
                      border_color=C["line"], text_color=C["white"], hover_color=C["panel"],
                      command=self.set_opening).pack(side="left")

        self.set_type("in")

        # ---- right: filters + ledger table ----
        right = ctk.CTkFrame(parent, fg_color=C["panel2"], corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", pady=4)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="TRANSACTION LEDGER", font=FONT_TITLE,
                     text_color=C["brass_soft"]).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))

        filters = ctk.CTkFrame(right, fg_color="transparent")
        filters.grid(row=0, column=0, sticky="e", padx=18, pady=(16, 6))
        self.search_box = ctk.CTkEntry(filters, placeholder_text="Search party or note…", width=200,
                                        fg_color=C["panel"], border_color=C["line"])
        self.search_box.pack(side="left", padx=4)
        self.search_box.bind("<KeyRelease>", lambda e: self.render_ledger())
        self.filter_type = ctk.CTkOptionMenu(filters, values=["All types", "Cash In only", "Cash Out only"],
                                              width=130, fg_color=C["panel"], button_color=C["panel"],
                                              button_hover_color=C["line"], command=lambda _: self.render_ledger())
        self.filter_type.pack(side="left", padx=4)
        self.filter_category = ctk.CTkOptionMenu(filters, values=["All categories"], width=150,
                                                   fg_color=C["panel"], button_color=C["panel"],
                                                   button_hover_color=C["line"],
                                                   command=lambda _: self.render_ledger())
        self.filter_category.pack(side="left", padx=4)

        table_frame = ctk.CTkFrame(right, fg_color="transparent")
        table_frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=6)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        cols = ("date", "party", "category", "note", "in", "out", "balance")
        headings = ["Date", "Party", "Category", "Note", "In", "Out", "Balance"]
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        for c, h in zip(cols, headings):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=100 if c not in ("note", "party") else 140, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        footer = ctk.CTkFrame(right, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 16))
        ctk.CTkButton(footer, text="Edit Selected", width=110, fg_color="transparent", border_width=1,
                      border_color=C["line"], text_color=C["white"], hover_color=C["panel"],
                      command=self.edit_selected).pack(side="left", padx=(0, 6))
        ctk.CTkButton(footer, text="Delete Selected", width=120, fg_color="transparent", border_width=1,
                      border_color=C["out"], text_color=C["out"], hover_color=C["panel"],
                      command=self.delete_selected).pack(side="left", padx=(0, 6))
        self.count_label = ctk.CTkLabel(footer, text="0 entries", font=FONT_LABEL, text_color=C["muted"])
        self.count_label.pack(side="left", padx=12)
        ctk.CTkButton(footer, text="Export CSV", fg_color="transparent", border_width=1,
                      border_color=C["in"], text_color=C["in"], hover_color=C["panel"],
                      command=self.export_ledger_csv).pack(side="right")

    def _form_field(self, parent, label):
        ctk.CTkLabel(parent, text=label.upper(), font=FONT_LABEL, text_color=C["muted"]).pack(
            anchor="w", padx=18, pady=(12, 4))
        entry = ctk.CTkEntry(parent, fg_color=C["panel"], border_color=C["line"])
        entry.pack(fill="x", padx=18)
        return entry

    # ---------- Report tab ----------
    def _build_report_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))

        self.r_from = ctk.CTkEntry(controls, placeholder_text="From (YYYY-MM-DD)", width=150,
                                    fg_color=C["panel2"], border_color=C["line"])
        self.r_from.pack(side="left", padx=4)
        self.r_to = ctk.CTkEntry(controls, placeholder_text="To (YYYY-MM-DD)", width=150,
                                  fg_color=C["panel2"], border_color=C["line"])
        self.r_to.pack(side="left", padx=4)
        self.r_type = ctk.CTkOptionMenu(controls, values=["All types", "Cash In only", "Cash Out only"],
                                         width=130, fg_color=C["panel2"], button_color=C["panel2"],
                                         button_hover_color=C["line"])
        self.r_type.pack(side="left", padx=4)
        self.r_category = ctk.CTkOptionMenu(controls, values=["All categories"], width=150,
                                             fg_color=C["panel2"], button_color=C["panel2"],
                                             button_hover_color=C["line"])
        self.r_category.pack(side="left", padx=4)

        ctk.CTkButton(controls, text="Generate Report", fg_color=C["brass"], text_color="#241c04",
                      hover_color=C["brass_soft"], command=self.generate_report).pack(side="left", padx=6)
        ctk.CTkButton(controls, text="Reset", fg_color="transparent", border_width=1, border_color=C["line"],
                      text_color=C["muted"], hover_color=C["panel"],
                      command=self.reset_report).pack(side="left", padx=4)
        ctk.CTkButton(controls, text="Export CSV", fg_color="transparent", border_width=1,
                      border_color=C["in"], text_color=C["in"], hover_color=C["panel"],
                      command=self.export_report_csv).pack(side="left", padx=4)

        self.report_summary_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.report_summary_frame.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))

        table_frame = ctk.CTkFrame(parent, fg_color=C["panel2"], corner_radius=10)
        table_frame.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        cols = ("date", "party", "category", "note", "in", "out", "balance")
        headings = ["Date", "Party", "Category", "Note", "In", "Out", "Balance"]
        self.report_tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        for c, h in zip(cols, headings):
            self.report_tree.heading(c, text=h)
            self.report_tree.column(c, width=100 if c not in ("note", "party") else 140, anchor="w")
        self.report_tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.report_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.report_tree.configure(yscrollcommand=vsb.set)

    # ============================================================
    #  DATA REFRESH
    # ============================================================
    def refresh_data_async(self):
        self.run_bg(self._fetch_all, on_done=self._apply_data, on_error=self._on_fetch_error)

    def _fetch_all(self):
        entries_raw = self.client.get("entries") or {}
        opening = self.client.get("meta/opening") or 0
        categories_raw = self.client.get("categories") or {}
        return entries_raw, opening, categories_raw

    def _on_fetch_error(self, err):
        self.set_sync_status(False)
        print("Fetch failed:", err)

    def _apply_data(self, result):
        entries_raw, opening, categories_raw = result
        self.set_sync_status(True)
        self.entries = [{"id": k, **v} for k, v in (entries_raw or {}).items()]
        self.opening = opening or 0
        self.categories = sorted(
            [{"id": k, "name": v.get("name", "")} for k, v in (categories_raw or {}).items()],
            key=lambda c: c["name"]
        )
        if not self.categories and not self._seed_tried:
            self._seed_tried = True
            self.run_bg(self._seed_categories, on_done=lambda _: self.refresh_data_async())
            return

        self._update_category_widgets()
        self.render_ledger()
        if self.category_window is not None and self.category_window.winfo_exists():
            self.category_window.render_list()

    def _seed_categories(self):
        updates = {}
        for name in DEFAULT_CATEGORIES:
            key = str(uuid.uuid4())
            updates[key] = {"name": name}
        self.client.update("categories", updates)

    def _update_category_widgets(self):
        names = [c["name"] for c in self.categories] or ["Other"]
        cur = self.f_category.get()
        self.f_category.configure(values=names)
        if cur in names:
            self.f_category.set(cur)
        else:
            self.f_category.set(names[0])

        used_in_ledger = sorted({e.get("category", "") for e in self.entries if e.get("category")})
        self.filter_category.configure(values=["All categories"] + used_in_ledger)
        self.r_category.configure(values=["All categories"] + used_in_ledger)

    # ============================================================
    #  ENTRY FORM LOGIC
    # ============================================================
    def set_type(self, t):
        self.current_type = t
        if t == "in":
            self.btn_type_in.configure(fg_color=C["in"], text_color="#0d1a12")
            self.btn_type_out.configure(fg_color=C["panel"], text_color=C["muted"])
        else:
            self.btn_type_out.configure(fg_color=C["out"], text_color="#26100a")
            self.btn_type_in.configure(fg_color=C["panel"], text_color=C["muted"])

    def reset_form(self):
        self.editing_id = None
        self.editing_flag.pack_forget()
        self.btn_cancel.pack_forget()
        self.btn_add.configure(text="ADD TO LEDGER")
        self.f_amount.delete(0, "end")
        self.f_party.delete(0, "end")
        self.f_note.delete(0, "end")
        self.f_date.delete(0, "end")
        self.f_date.insert(0, date.today().isoformat())
        self.set_type("in")

    def _validate_date(self, s):
        try:
            datetime.strptime(s.strip(), "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def submit_entry(self):
        d = self.f_date.get().strip()
        try:
            amount = float(self.f_amount.get().strip())
        except ValueError:
            amount = None
        category = self.f_category.get()
        party = self.f_party.get().strip()
        note = self.f_note.get().strip()

        if not self._validate_date(d):
            messagebox.showwarning("Invalid date", "Please use YYYY-MM-DD format.")
            return
        if amount is None or amount <= 0:
            messagebox.showwarning("Invalid amount", "Enter an amount greater than 0.")
            return

        if self.editing_id:
            existing = next((e for e in self.entries if e["id"] == self.editing_id), None)
            payload = {
                "date": d, "type": self.current_type, "amount": amount,
                "category": category, "party": party, "note": note,
                "createdAt": existing.get("createdAt") if existing else None,
            }
            eid = self.editing_id
            self.run_bg(lambda: self.client.set(f"entries/{eid}", payload),
                        on_done=lambda _: (self.reset_form(), self.refresh_data_async()))
        else:
            payload = {
                "date": d, "type": self.current_type, "amount": amount,
                "category": category, "party": party, "note": note,
                "createdAt": int(datetime.now().timestamp() * 1000),
            }
            self.run_bg(lambda: self.client.push("entries", payload),
                        on_done=lambda _: (self.reset_form(), self.refresh_data_async()))

    def set_opening(self):
        try:
            v = float(self.f_opening.get().strip())
        except ValueError:
            return
        self.f_opening.delete(0, "end")
        self.run_bg(lambda: self.client.set("meta/opening", v),
                    on_done=lambda _: self.refresh_data_async())

    def open_category_manager(self):
        if self.category_window is not None and self.category_window.winfo_exists():
            self.category_window.focus()
            return
        self.category_window = CategoryManagerWindow(self)

    def rename_category(self, cat, new_name):
        cid = cat["id"]
        old_name = cat["name"]

        def do_rename():
            self.client.update(f"categories/{cid}", {"name": new_name})
            affected = [e for e in self.entries if e.get("category") == old_name]
            if affected:
                updates = {f"{e['id']}/category": new_name for e in affected}
                self.client.update("entries", updates)

        self.run_bg(do_rename, on_done=lambda _: self.refresh_data_async())

    # ============================================================
    #  LEDGER TABLE
    # ============================================================
    def _with_running_balance(self):
        chrono = sorted(self.entries, key=lambda e: (e.get("date", ""), e.get("createdAt", 0)))
        running = self.opening
        out = []
        for e in chrono:
            amt = float(e.get("amount", 0) or 0)
            running += amt if e.get("type") == "in" else -amt
            out.append({**e, "balance": running})
        return out

    def render_ledger(self):
        rows = self._with_running_balance()

        total_in = sum(float(e.get("amount", 0) or 0) for e in self.entries if e.get("type") == "in")
        total_out = sum(float(e.get("amount", 0) or 0) for e in self.entries if e.get("type") == "out")
        net = self.opening + total_in - total_out

        self.card_opening.configure(text=fmt_money(self.opening))
        self.card_in.configure(text=fmt_money(total_in))
        self.card_out.configure(text=fmt_money(total_out))
        self.card_net.configure(text=fmt_money(net))

        search = self.search_box.get().lower().strip()
        type_filter = self.filter_type.get()
        cat_filter = self.filter_category.get()

        def keep(e):
            if type_filter == "Cash In only" and e.get("type") != "in":
                return False
            if type_filter == "Cash Out only" and e.get("type") != "out":
                return False
            if cat_filter != "All categories" and e.get("category") != cat_filter:
                return False
            if search:
                hay = f"{e.get('party','')} {e.get('note','')} {e.get('category','')}".lower()
                if search not in hay:
                    return False
            return True

        display = [r for r in rows if keep(r)][::-1]

        for i in self.tree.get_children():
            self.tree.delete(i)
        for e in display:
            self.tree.insert("", "end", iid=e["id"], values=(
                e.get("date", ""), e.get("party", ""), e.get("category", ""), e.get("note", ""),
                fmt_money(e["amount"]) if e.get("type") == "in" else "",
                fmt_money(e["amount"]) if e.get("type") == "out" else "",
                fmt_money(e["balance"]),
            ))
        self.count_label.configure(text=f"{len(self.entries)} entries")

    def _selected_entry(self, tree):
        sel = tree.selection()
        if not sel:
            return None
        eid = sel[0]
        return next((e for e in self.entries if e["id"] == eid), None)

    def edit_selected(self):
        e = self._selected_entry(self.tree)
        if not e:
            messagebox.showinfo("Select a row", "Select a transaction in the table first.")
            return
        self.editing_id = e["id"]
        self.editing_flag.pack(anchor="w", padx=18, pady=(0, 6))
        self.btn_cancel.pack(fill="x", padx=18, pady=(0, 6))
        self.btn_add.configure(text="UPDATE ENTRY")
        self.f_date.delete(0, "end"); self.f_date.insert(0, e.get("date", ""))
        self.f_amount.delete(0, "end"); self.f_amount.insert(0, str(e.get("amount", "")))
        self.f_party.delete(0, "end"); self.f_party.insert(0, e.get("party", ""))
        self.f_note.delete(0, "end"); self.f_note.insert(0, e.get("note", ""))
        if e.get("category") in self.f_category.cget("values"):
            self.f_category.set(e.get("category"))
        self.set_type(e.get("type", "in"))

    def delete_selected(self):
        e = self._selected_entry(self.tree)
        if not e:
            messagebox.showinfo("Select a row", "Select a transaction in the table first.")
            return
        if not messagebox.askyesno("Delete entry", "Delete this transaction?"):
            return
        eid = e["id"]
        if self.editing_id == eid:
            self.reset_form()
        self.run_bg(lambda: self.client.delete(f"entries/{eid}"),
                    on_done=lambda _: self.refresh_data_async())

    def export_ledger_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                             initialfile=f"cash-ledger-{date.today().isoformat()}.csv",
                                             filetypes=[("CSV", "*.csv")])
        if not path:
            return
        rows = self._with_running_balance()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Date", "Type", "Party", "Category", "Note", "Amount", "RunningBalance"])
            for e in rows:
                w.writerow([e.get("date"), "Cash In" if e.get("type") == "in" else "Cash Out",
                            e.get("party"), e.get("category"), e.get("note"),
                            f"{float(e.get('amount',0)):.2f}", f"{e['balance']:.2f}"])
        messagebox.showinfo("Exported", f"Saved to {path}")

    # ============================================================
    #  REPORT TAB
    # ============================================================
    def generate_report(self):
        rows = self._with_running_balance()
        from_d = self.r_from.get().strip()
        to_d = self.r_to.get().strip()
        type_filter = self.r_type.get()
        cat_filter = self.r_category.get()

        if from_d and not self._validate_date(from_d):
            messagebox.showwarning("Invalid date", "'From' date must be YYYY-MM-DD.")
            return
        if to_d and not self._validate_date(to_d):
            messagebox.showwarning("Invalid date", "'To' date must be YYYY-MM-DD.")
            return

        def keep(e):
            if from_d and e.get("date", "") < from_d:
                return False
            if to_d and e.get("date", "") > to_d:
                return False
            if type_filter == "Cash In only" and e.get("type") != "in":
                return False
            if type_filter == "Cash Out only" and e.get("type") != "out":
                return False
            if cat_filter != "All categories" and e.get("category") != cat_filter:
                return False
            return True

        filtered = [e for e in rows if keep(e)]
        self.last_report_rows = filtered

        for w in self.report_summary_frame.winfo_children():
            w.destroy()
        for i in self.report_tree.get_children():
            self.report_tree.delete(i)

        if not filtered:
            ctk.CTkLabel(self.report_summary_frame, text="No transactions match this range.",
                         text_color=C["muted"], font=FONT_LABEL).pack(anchor="w")
            return

        total_in = sum(float(e.get("amount", 0)) for e in filtered if e.get("type") == "in")
        total_out = sum(float(e.get("amount", 0)) for e in filtered if e.get("type") == "out")
        net = total_in - total_out

        for label, val, color in [
            ("Transactions", str(len(filtered)), C["white"]),
            ("Total In", fmt_money(total_in), C["in"]),
            ("Total Out", fmt_money(total_out), C["out"]),
            ("Net Change", fmt_money(net), C["brass_soft"]),
        ]:
            cell = ctk.CTkFrame(self.report_summary_frame, fg_color=C["bg"], corner_radius=6,
                                 border_width=1, border_color=C["line"])
            cell.pack(side="left", padx=6, fill="x", expand=True)
            ctk.CTkLabel(cell, text=label.upper(), font=FONT_LABEL, text_color=C["muted"]).pack(
                anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(cell, text=val, font=("Consolas", 16, "bold"), text_color=color).pack(
                anchor="w", padx=12, pady=(0, 8))

        for e in filtered:
            self.report_tree.insert("", "end", values=(
                e.get("date", ""), e.get("party", ""), e.get("category", ""), e.get("note", ""),
                fmt_money(e["amount"]) if e.get("type") == "in" else "",
                fmt_money(e["amount"]) if e.get("type") == "out" else "",
                fmt_money(e["balance"]),
            ))

    def reset_report(self):
        self.r_from.delete(0, "end")
        self.r_to.delete(0, "end")
        self.r_type.set("All types")
        self.r_category.set("All categories")
        self.last_report_rows = []
        for w in self.report_summary_frame.winfo_children():
            w.destroy()
        for i in self.report_tree.get_children():
            self.report_tree.delete(i)

    def export_report_csv(self):
        if not self.last_report_rows:
            self.generate_report()
        if not self.last_report_rows:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                             initialfile=f"cash-report-{date.today().isoformat()}.csv",
                                             filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Date", "Type", "Party", "Category", "Note", "Amount", "RunningBalance"])
            for e in self.last_report_rows:
                w.writerow([e.get("date"), "Cash In" if e.get("type") == "in" else "Cash Out",
                            e.get("party"), e.get("category"), e.get("note"),
                            f"{float(e.get('amount',0)):.2f}", f"{e['balance']:.2f}"])
        messagebox.showinfo("Exported", f"Saved to {path}")


if __name__ == "__main__":
    app = CashLedgerApp()
    app.mainloop()
