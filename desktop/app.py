"""PRODU Control - portable Windows order management."""
from __future__ import annotations
import argparse
import json
import logging
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk
from core import Database, STATUSES, display_date, export_csv, local_datetime, ranking, summary
from sync import DEFAULTS, SETTINGS_DIR, Publisher, load_settings, protect, save_settings
from appearance import AppearanceMixin
from management import DeletionMixin

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
VERSION = "1.1.0"


class Application(AppearanceMixin, DeletionMixin, ttk.Window):
    def __init__(self, db_path=None, isolated=False):
        initial_settings = dict(DEFAULTS) if isolated else load_settings()
        super().__init__(themename="darkly" if initial_settings.get("theme") == "dark" else "litera",
                         title="PRODU · Control de pedidos", size=(1360, 900), minsize=(1000, 620))
        self.geometry(f"{min(1280, self.winfo_screenwidth()-70)}x{min(820, self.winfo_screenheight()-100)}")
        self.isolated = isolated
        self.settings = initial_settings
        self.initialize_appearance()
        self.db = Database(db_path or self.settings.get("db_path") or BASE_DIR / "pedidos.db")
        self.token = ""
        if self.settings.get("token_encrypted"):
            try:
                self.token = protect(self.settings["token_encrypted"], decrypt=True)
            except ValueError:
                self.after(500, lambda: messagebox.showinfo("Credencial", "Vuelve a introducir el token en Configuración.", parent=self))
        self.rows = []
        self.events = queue.Queue()
        self.busy = False
        self.page_name = "orders"
        self.search_job = None
        self.sort_key = None
        self.sort_reverse = False
        self.apply_styles()
        try:
            self.iconbitmap(str(Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "produ.ico"))
        except tk.TclError:
            pass
        self.build()
        self.apply_styles()
        self.refresh()
        self.bind("<Configure>", self.adapt_layout, add="+")
        self.after_idle(self.adapt_layout)
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.bind("<Control-n>", lambda e: self.edit_order())
        self.bind("<Control-f>", lambda e: self.focus_search())
        self.bind("<F5>", lambda e: self.refresh())
        self.after(100, self.poll)
        self.after(15000, self.periodic_refresh)

    def build(self):
        sidebar = tk.Frame(self, bg="#173b35", width=205)
        self.sidebar = sidebar
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="▦ PRODU", bg="#173b35", fg="#f2f7f4", font=("Segoe UI", 20, "bold"), anchor="w").pack(fill="x", padx=20, pady=(30, 2))
        tk.Label(sidebar, text="CONTROL DE PEDIDOS", bg="#173b35", fg="#aec5b9", font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=22, pady=(0, 35))
        self.nav = {}
        for key, label in (("orders", "▤   Pedidos"), ("analysis", "▥   Análisis"), ("deleted", "⌫   Borrados"), ("settings", "⚙   Configuración")):
            b = tk.Button(sidebar, text=label, command=lambda k=key: self.show_page(k), bg="#173b35", fg="#e6eee9",
                          activebackground="#2b5347", activeforeground="white", relief="flat", bd=0,
                          anchor="w", font=("Segoe UI", 12), padx=14, pady=13, cursor="hand2")
            b.pack(fill="x", padx=10, pady=4)
            self.nav[key] = b
        bottom = tk.Frame(sidebar, bg="#173b35")
        bottom.pack(side="bottom", fill="x", padx=22, pady=25)
        tk.Label(bottom, text="●  SQLite local", bg="#173b35", fg="#b5d59e", font=("Segoe UI", 10), anchor="w").pack(fill="x")
        tk.Label(bottom, text=f"PRODU Control {VERSION}\nRegistro sin conexión", bg="#173b35", fg="#aec5b9", justify="left", font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(8, 0))
        main = ttk.Frame(self, padding=(22, 16))
        main.pack(side="left", fill="both", expand=True)
        header = ttk.Frame(main)
        header.pack(fill="x")
        titles = ttk.Frame(header)
        titles.pack(side="left", fill="x", expand=True)
        self.eyebrow = ttk.Label(titles, text="PRODUCCIÓN / CONTROL OPERATIVO", style="Eyebrow.TLabel")
        self.eyebrow.pack(anchor="w")
        self.title_label = ttk.Label(titles, text="Pedidos de producción", style="Title.TLabel")
        self.title_label.pack(anchor="w", pady=(4, 3))
        self.subtitle = ttk.Label(titles, text="Registra, localiza y da seguimiento a cada pedido.", style="Muted.TLabel")
        self.subtitle.pack(anchor="w")
        actions = ttk.Frame(header)
        actions.pack(side="right", anchor="n", pady=(5, 0))
        action_row = ttk.Frame(actions)
        action_row.pack(anchor="e")
        self.theme_button = ttk.Button(action_row, text="☾  Modo oscuro", bootstyle="secondary-outline", command=self.toggle_theme)
        self.theme_button.pack(side="left", padx=(0, 8))
        self.upload_btn = ttk.Button(action_row, text="↑  Subir a dashboard", bootstyle="success", command=self.upload)
        self.upload_btn.pack(side="left")
        ttk.Button(actions, text="Abrir dashboard ↗", bootstyle="link", command=self.open_dashboard).pack(anchor="e", pady=(3, 0))
        self.sync_label = ttk.Label(main, text="", style="Muted.TLabel", wraplength=930)
        self.sync_label.pack(fill="x", pady=(10, 10))
        self.pages = {}
        self.page_container = ttk.Frame(main)
        self.footer = ttk.Label(main, text="", style="Muted.TLabel", font=("Segoe UI", 9))
        self.footer.pack(side="bottom", fill="x", pady=(8, 0))
        self.page_container.pack(fill="both", expand=True)
        for name in ("orders", "analysis", "deleted", "settings"):
            self.pages[name] = ttk.Frame(self.page_container)
        self.build_orders(self.pages["orders"])
        self.build_analysis(self.pages["analysis"])
        self.build_deleted(self.pages["deleted"])
        self.build_settings(self.pages["settings"])
        # Apply legacy Tk colors after ttkbootstrap has initialized its widgets.
        def color_sidebar(widget):
            if isinstance(widget, (tk.Frame, tk.Label)):
                widget.configure(background=self.palette["sidebar"])
            if isinstance(widget, tk.Label):
                widget.configure(foreground="#e6eee9")
            for child in widget.winfo_children():
                color_sidebar(child)
        color_sidebar(sidebar)
        self.repaint_sidebar = color_sidebar
        self.show_page("orders")

    def build_orders(self, page):
        self.order_summary_caption = ttk.Label(page, text="RESUMEN DE LA VISTA", style="Eyebrow.TLabel")
        self.order_summary_caption.pack(anchor="w", pady=(0, 8))
        cards = ttk.Frame(page)
        self.order_cards = cards
        cards.pack(fill="x")
        self.kpis = {}
        self.kpi_notes = {}
        for i, (key, label, index) in enumerate((("total", "TOTAL", None), (STATUSES[0], "EN PROCESO", 0),
                (STATUSES[1], "RESGUARDO", 1), (STATUSES[2], "TERMINADOS", 2),
                (STATUSES[3], "ENTREGADOS", 3), ("pending", "POR ENTREGAR", 0))):
            self.kpis[key], self.kpi_notes[key] = self.make_stat_card(cards, i, label, index, compact=True)
        filters = ttk.Frame(page, padding=(0, 15, 0, 12))
        filters.pack(fill="x")
        for i, weight in enumerate((3, 2, 2, 1, 1, 0)):
            filters.columnconfigure(i, weight=weight)
        self.query_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Todos")
        self.operator_var = tk.StringVar(value="Todos")
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        for i, text in enumerate(("Buscar ticket, cliente u operador", "Estatus", "Operador", "Desde · AAAA-MM-DD", "Hasta · AAAA-MM-DD")):
            ttk.Label(filters, text=text, style="Muted.TLabel").grid(row=0, column=i, sticky="w", pady=(0, 5))
        self.search_entry = ttk.Entry(filters, textvariable=self.query_var, width=26)
        self.search_entry.grid(row=1, column=0, sticky="ew", padx=(0, 9))
        ttk.Combobox(filters, textvariable=self.status_var, values=("Todos", *STATUSES), state="readonly", width=19).grid(row=1, column=1, sticky="ew", padx=(0, 9))
        self.operator_combo = ttk.Combobox(filters, textvariable=self.operator_var, values=("Todos",), state="readonly", width=16)
        self.operator_combo.grid(row=1, column=2, sticky="ew", padx=(0, 9))
        for i, var in enumerate((self.from_var, self.to_var), start=3):
            entry = ttk.Entry(filters, textvariable=var, width=12)
            entry.grid(row=1, column=i, sticky="ew", padx=(0, 9))
            entry.bind("<Return>", lambda e: self.refresh())
            entry.bind("<FocusOut>", lambda e: self.refresh(silent=True))
        ttk.Button(filters, text="Limpiar", bootstyle="secondary-outline", command=self.clear_filters).grid(row=1, column=5, sticky="ew")
        for var in (self.query_var, self.status_var, self.operator_var):
            var.trace_add("write", lambda *args: self.schedule_search())
        tools = ttk.Frame(page)
        tools.pack(fill="x", pady=(0, 10))
        tools.columnconfigure(0, weight=1)
        edit_tools = ttk.Frame(tools)
        edit_tools.grid(row=0, column=0, sticky="w")
        report_tools = ttk.Frame(tools)
        report_tools.grid(row=0, column=1, sticky="e")
        ttk.Button(edit_tools, text="+  Nuevo pedido", bootstyle="success", command=self.edit_order).pack(side="left")
        self.edit_button = ttk.Button(edit_tools, text="Editar / estatus", bootstyle="secondary-outline", command=self.edit_selected)
        self.edit_button.pack(side="left", padx=6)
        ttk.Button(edit_tools, text="Historial", bootstyle="secondary-outline", command=self.show_history).pack(side="left")
        ttk.Button(edit_tools, text="Borrar", bootstyle="danger-outline", command=self.delete_selected).pack(side="left", padx=8)
        ttk.Button(report_tools, text="↻  Actualizar", bootstyle="secondary-outline", command=self.refresh).pack(side="left", padx=(0, 8))
        self.csv_button = ttk.Button(report_tools, text="Exportar CSV", bootstyle="secondary-outline", command=self.export)
        self.csv_button.pack(side="left")
        def arrange_tools(event):
            narrow = event.width < edit_tools.winfo_reqwidth() + report_tools.winfo_reqwidth() + 15
            report_tools.grid_configure(row=1 if narrow else 0, column=0 if narrow else 1,
                                        sticky="w" if narrow else "e", pady=(8, 0) if narrow else 0)
        tools.bind("<Configure>", arrange_tools)
        self.result_label = ttk.Label(page, text="", style="Muted.TLabel", wraplength=920)
        self.result_label.pack(side="bottom", anchor="w", pady=(10, 0))
        self.build_order_detail(page)
        columns = (("ticket", "Ticket", 95), ("client", "Cliente", 185), ("operator", "Operador", 120),
                   ("status", "Estatus", 175), ("created_at", "Registro", 145), ("updated_at", "Último cambio", 145))
        self.order_tree = self.make_tree(page, columns, height=6)
        self.order_tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.order_tree.bind("<<TreeviewSelect>>", lambda e: self.render_order_detail())
        for field, title, width in columns:
            self.order_tree.heading(field, text=title, command=lambda f=field: self.sort_orders(f))

    def make_tree(self, parent, columns, height=None):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=tuple(c[0] for c in columns), show="headings", selectmode="browse", height=height or 10)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        for field, label, width in columns:
            tree.heading(field, text=label)
            tree.column(field, width=width, minwidth=80, anchor="w" if field in ("ticket", "client", "operator", "status", "name") else "center")
        return tree

    def build_settings(self, page):
        canvas = tk.Canvas(page, highlightthickness=0)
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set, background=self.style.colors.bg)
        self.canvas_surfaces.append((canvas, "bg"))
        inner = ttk.Frame(canvas, padding=(0, 0, 12, 10))
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(inner_id, width=event.width))
        self.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units") if self.page_name == "settings" else None, add="+")
        page = inner
        ttk.Label(page, text="Conexión con GitHub", style="Section.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(page, text="La subida reemplaza la vista publicada con todos los pedidos de esta base. Los filtros no limitan la subida.", style="Muted.TLabel", wraplength=920).pack(anchor="w", pady=(0, 13))
        self.repo_var = tk.StringVar(value=self.settings["repository"])
        self.branch_var = tk.StringVar(value=self.settings["branch"])
        self.url_var = tk.StringVar(value=self.settings["dashboard_url"])
        self.token_var = tk.StringVar(value=self.token)
        form = ttk.Frame(page)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for i, (label, var) in enumerate((("Repositorio", self.repo_var), ("Rama", self.branch_var), ("Dirección del dashboard", self.url_var), ("Token personal de GitHub", self.token_var))):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", padx=(0, 22), pady=7)
            ttk.Entry(form, textvariable=var, show="●" if i == 3 else "", width=64).grid(row=i, column=1, sticky="ew", pady=7)
        self.remember_var = tk.BooleanVar(value=bool(self.settings.get("token_encrypted")))
        ttk.Checkbutton(page, text="Recordar token en esta cuenta de Windows (cifrado)", variable=self.remember_var, bootstyle="success-round-toggle").pack(anchor="w", pady=(10, 5))
        ttk.Label(page, text="Crea un token de acceso específico para PRODUDASH1 con permiso Contents: Read and write.\nEl token se introduce aquí; no lo envíes por chat. Nunca se publica en el repositorio.", style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(0, 8))
        self.replace_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(page, text="Permitir sustituir datos de otra base en la próxima subida", variable=self.replace_var, bootstyle="warning-round-toggle").pack(anchor="w", pady=(4, 5))
        ttk.Label(page, text="Repositorio público: ticket, cliente, operador, estatus y fechas serán visibles en Internet. Las observaciones permanecen en la base local.", style="Warning.TLabel", wraplength=900).pack(anchor="w", pady=(0, 10))
        buttons = ttk.Frame(page)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Guardar configuración", bootstyle="success", command=self.save_config).pack(side="left")
        ttk.Button(buttons, text="Crear token ↗", bootstyle="secondary-outline", command=lambda: webbrowser.open("https://github.com/settings/personal-access-tokens/new")).pack(side="left", padx=10)
        ttk.Separator(page).pack(fill="x", pady=20)
        ttk.Label(page, text="Base de datos y respaldos", style="Section.TLabel").pack(anchor="w")
        self.db_label = ttk.Label(page, text=str(self.db.path), style="Muted.TLabel", wraplength=910)
        self.db_label.pack(anchor="w", pady=(6, 12))
        buttons = ttk.Frame(page)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Crear respaldo .db", bootstyle="secondary-outline", command=self.backup).pack(side="left")
        ttk.Button(buttons, text="Abrir otra base .db", bootstyle="secondary-outline", command=self.switch_db).pack(side="left", padx=10)
        ttk.Separator(page).pack(fill="x", pady=20)
        ttk.Label(page, text="Protección del borrado", style="Section.TLabel").pack(anchor="w")
        self.password_label = ttk.Label(page, text="", style="Muted.TLabel", wraplength=890)
        self.password_label.pack(anchor="w", pady=(6, 10))
        self.password_button = ttk.Button(page, text="Crear contraseña", bootstyle="secondary-outline", command=self.configure_delete_password)
        self.password_button.pack(anchor="w")
        ttk.Label(page, text="Pendientes = en proceso + en resguardo + terminados sin entregar.\nCada ticket es único; el historial conserva los cambios. Para corregir un pedido, edítalo.", style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(15, 0))

    def show_page(self, name):
        self.page_name = name
        for key, page in self.pages.items():
            page.pack_forget()
            self.nav[key].configure(bg="#2c5b47" if key == name else self.palette["sidebar"])
        self.pages[name].pack(fill="both", expand=True)
        title, subtitle = {"orders": ("Pedidos de producción", "Registra, localiza y da seguimiento a cada pedido."),
                           "analysis": ("Carga y entregas", "Consulta quién concentra más pedidos y cuántos faltan por entregar."),
                           "deleted": ("Registro de borrados", "Consulta qué se borró, cuándo, quién lo hizo y por qué."),
                           "settings": ("Configuración", "Conecta el dashboard y administra tus respaldos.")}[name]
        self.title_label.configure(text=title)
        self.subtitle.configure(text=subtitle)
        if name == "analysis":
            self.refresh()
        elif name == "deleted":
            self.refresh_deleted()

    def schedule_search(self):
        if self.search_job:
            self.after_cancel(self.search_job)
        self.search_job = self.after(180, lambda: self.refresh(silent=True))

    def clear_filters(self):
        self.query_var.set("")
        self.status_var.set("Todos")
        self.operator_var.set("Todos")
        self.from_var.set("")
        self.to_var.set("")
        self.refresh()

    def refresh(self, silent=False):
        self.search_job = None
        try:
            self.rows = self.db.search(self.query_var.get(), self.status_var.get(), self.operator_var.get(), self.from_var.get().strip(), self.to_var.get().strip())
        except ValueError as exc:
            self.result_label.configure(text=str(exc), foreground="#b45353")
            if not silent:
                messagebox.showerror("Filtros", str(exc), parent=self)
            return
        values = summary(self.rows)
        for key, widget in self.kpis.items():
            widget.configure(text=str(values[key]))
            self.kpi_notes[key].configure(text="Vista filtrada" if key == "total" else
                f"{round(values[key] / values['total'] * 100) if values['total'] else 0}% del total")
        self.operator_combo.configure(values=("Todos", *self.db.names("operator")))
        self.draw_orders()
        total = self.db.conn.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL").fetchone()[0]
        self.result_label.configure(text=(f"{len(self.rows)} de {total} pedidos · Pendientes = proceso + resguardo + terminados sin entregar."
                                         if total else "Sin pedidos activos. Haz clic en + Nuevo pedido para registrar uno."), foreground=self.palette["muted"])
        for field, tree in self.rank_trees.items():
            tree.delete(*tree.get_children())
            for index, row in enumerate(ranking(self.rows, field)):
                tree.insert("", "end", tags=("odd" if index % 2 else "even",), values=(row["name"], row["total"], row["pending"], *(row[s] for s in STATUSES)))
        daily = {}
        for row in self.rows:
            if row["status"] == STATUSES[3] and row["delivered_at"]:
                date = local_datetime(row["delivered_at"]).date().isoformat()
                daily[date] = daily.get(date, 0) + 1
        self.delivery_tree.delete(*self.delivery_tree.get_children())
        for index, date in enumerate(sorted(daily, reverse=True)):
            self.delivery_tree.insert("", "end", tags=("odd" if index % 2 else "even",), values=(date, daily[date]))
        leaders = ranking(self.rows, "operator")
        lead = max(leaders, key=lambda r: r["total"]) if leaders else None
        self.analysis_label.configure(text=f"Vista actual: {values['total']} pedidos · {values['pending']} pendientes · {values[STATUSES[3]]} entregados. " +
                                      (f"Mayor total: {lead['name']} ({lead['total']})." if lead else "Registra pedidos para ver el análisis."))
        self.render_analysis(values, lead)
        self.refresh_deleted()
        self.update_password_label()
        revision = int(self.db.meta("revision"))
        published = int(self.db.meta("published_revision") or "-1")
        published_at = self.db.meta("published_at")
        text = (f"Última subida: {display_date(published_at)}" if published_at else "Todavía no se ha subido esta base al dashboard")
        text += " · Datos locales actualizados" if revision == published else " · Hay cambios por subir"
        self.sync_label.configure(text="●  " + text)
        self.footer.configure(text=f"Base: {self.db.path.name}   ·   F5 actualizar   ·   Ctrl+N nuevo pedido   ·   Ctrl+F buscar")

    def draw_orders(self):
        selected = self.order_tree.selection()
        keep = selected[0] if selected else None
        self.order_tree.delete(*self.order_tree.get_children())
        rows = sorted(self.rows, key=lambda r: str(r[self.sort_key]).casefold(), reverse=self.sort_reverse) if self.sort_key else self.rows
        for index, row in enumerate(rows):
            self.order_tree.insert("", "end", iid=str(row["id"]), values=(row["ticket"], row["client"], row["operator"],
                ("✓ " if row["status"] == STATUSES[3] else "● ") + row["status"], display_date(row["created_at"]), display_date(row["updated_at"])),
                tags=("odd" if index % 2 else "even",))
        if keep and self.order_tree.exists(keep):
            self.order_tree.selection_set(keep)
        elif rows:
            self.order_tree.selection_set(str(rows[0]["id"]))
        self.render_order_detail()

    def sort_orders(self, field):
        self.sort_reverse = not self.sort_reverse if self.sort_key == field else False
        self.sort_key = field
        self.draw_orders()

    def selected_id(self):
        selection = self.order_tree.selection()
        if not selection:
            messagebox.showinfo("Selecciona un pedido", "Selecciona un pedido en la tabla primero.", parent=self)
            return None
        return int(selection[0])

    def edit_selected(self):
        order_id = self.selected_id()
        if order_id is not None:
            self.edit_order(order_id)

    def edit_order(self, order_id=None):
        if self.busy:
            messagebox.showinfo("Subida en curso", "Espera a que termine la subida para editar pedidos.", parent=self)
            return
        row = self.db.get(order_id) if order_id is not None else None
        dialog = ttk.Toplevel(self)
        dialog.title("Editar pedido" if row else "Nuevo pedido")
        dialog.geometry(f"610x{min(680, self.winfo_screenheight()-120)}")
        dialog.minsize(560, min(520, self.winfo_screenheight()-120))
        dialog.resizable(True, True)
        dialog.transient(self)
        dialog.grab_set()
        box = ttk.Frame(dialog, padding=24)
        box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        heading = ttk.Frame(box)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(heading, text="Editar pedido" if row else "Registrar pedido", style="Section.TLabel").pack(anchor="w")
        ttk.Label(heading, text=("Registro original: " + display_date(row["created_at"])) if row else "La fecha y hora se asignan automáticamente al guardar.", style="Muted.TLabel", wraplength=500).pack(anchor="w", pady=(5, 0))
        # Keep actions in a separate, fully sized row. The form can scroll on
        # small screens or with larger Windows text without clipping buttons.
        footer = ttk.Frame(box)
        footer.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        ttk.Separator(footer).pack(fill="x", pady=(0, 8))
        error = ttk.Label(footer, text="", foreground=self.palette["error"], wraplength=500)
        error.pack(anchor="w", fill="x", pady=(0, 8))
        buttons = ttk.Frame(footer)
        buttons.pack(fill="x")
        buttons.columnconfigure(0, weight=1)
        form_area = ttk.Frame(box)
        form_area.grid(row=1, column=0, sticky="nsew")
        form_area.rowconfigure(0, weight=1)
        form_area.columnconfigure(0, weight=1)
        canvas = tk.Canvas(form_area, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(form_area, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set, background=self.style.colors.bg)
        fields = ttk.Frame(canvas, padding=(0, 0, 12, 2))
        fields_id = canvas.create_window((0, 0), window=fields, anchor="nw")
        fields.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(fields_id, width=event.width))
        def scroll_form(event):
            if event.widget.winfo_class() in ("TCombobox", "Text"):
                return None
            canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        dialog.bind("<MouseWheel>", scroll_form)
        variables = {}
        entries = []
        for field, label in (("ticket", "Ticket *"), ("client", "Cliente *"), ("operator", "Operador *"), ("status", "Estatus *")):
            ttk.Label(fields, text=label).pack(anchor="w", pady=(6, 4))
            var = tk.StringVar(value=row[field] if row else (STATUSES[0] if field == "status" else ""))
            variables[field] = var
            if field in ("client", "operator", "status"):
                widget = ttk.Combobox(fields, textvariable=var, values=STATUSES if field == "status" else self.db.names(field), state="readonly" if field == "status" else "normal")
            else:
                widget = ttk.Entry(fields, textvariable=var)
            widget.pack(fill="x")
            entries.append(widget)
        ttk.Label(fields, text="Observaciones (opcionales, solo en la base local)", wraplength=490).pack(anchor="w", pady=(12, 5))
        notes = tk.Text(fields, height=4, font=("Segoe UI", 10), relief="solid", bd=1, wrap="word",
                        background=self.palette["panel"], foreground=self.palette["text"], insertbackground=self.palette["text"])
        notes.pack(fill="x")
        if row:
            notes.insert("1.0", row["notes"])
        def save():
            try:
                self.db.save(**{k: v.get() for k, v in variables.items()}, notes=notes.get("1.0", "end-1c"), order_id=order_id,
                             expected_updated=row["updated_at"] if row else None)
            except (ValueError, OSError) as exc:
                error.configure(text=str(exc))
                return
            dialog.destroy()
            self.refresh()
        cancel_button = ttk.Button(buttons, text="Cancelar", width=12, bootstyle="secondary-outline", command=dialog.destroy)
        cancel_button.grid(row=0, column=1, sticky="e", padx=(0, 10))
        save_button = ttk.Button(buttons, text="Guardar pedido", width=16, bootstyle="success", command=save)
        save_button.grid(row=0, column=2, sticky="e")
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.bind("<Control-Return>", lambda e: save())
        entries[0].focus_set()
        return {"dialog": dialog, "variables": variables, "save": save, "notes": notes, "error": error,
                "save_button": save_button, "cancel_button": cancel_button, "form_canvas": canvas}

    def show_history(self):
        order_id = self.selected_id()
        if order_id is None:
            return
        return self.show_order_history(order_id)

    def show_order_history(self, order_id, include_deleted=False):
        row = self.db.get(order_id, include_deleted=include_deleted)
        dialog = ttk.Toplevel(self)
        dialog.title(f"Historial · Ticket {row['ticket']}")
        dialog.geometry("760x540")
        dialog.transient(self)
        text = tk.Text(dialog, wrap="word", font=("Segoe UI", 11), padx=20, pady=15,
                       background=self.palette["panel"], foreground=self.palette["text"])
        scroll = ttk.Scrollbar(dialog, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        text.pack(fill="both", expand=True)
        text.insert("end", f"TICKET #{row['ticket']}\nCliente: {row['client']}\nOperador: {row['operator']}\nEstatus: {row['status']}\n"
                    f"Registro: {display_date(row['created_at'])}\n")
        if row["deleted_at"]:
            text.insert("end", f"\nBORRADO: {display_date(row['deleted_at'])}\nUsuario de Windows: {row['deleted_by']}\nMotivo: {row['deleted_reason']}\n")
        if row["notes"]:
            text.insert("end", f"Observaciones: {row['notes']}\n")
        text.insert("end", "\nHISTORIAL DE CAMBIOS\n\n")
        for event in self.db.history(order_id):
            before = json.loads(event["before_json"]) if event["before_json"] else {}
            after = json.loads(event["after_json"])
            text.insert("end", f"{display_date(event['changed_at'])} · {event['action']}\n")
            for key, label in (("ticket", "Ticket"), ("client", "Cliente"), ("operator", "Operador"), ("status", "Estatus"),
                               ("notes", "Observaciones"), ("deleted_at", "Fecha de borrado"), ("deleted_by", "Usuario"), ("deleted_reason", "Motivo")):
                if before.get(key) != after.get(key):
                    value = display_date(after.get(key)) if key == "deleted_at" else after.get(key, "—")
                    text.insert("end", f"  {label}: {before.get(key) or '—'} → {value}\n")
            text.insert("end", "\n")
        text.configure(state="disabled")
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        return dialog, text

    def filter_rank(self, field):
        tree = self.rank_trees[field]
        if tree.selection():
            name = tree.item(tree.selection()[0], "values")[0]
            self.clear_filters()
            if field == "operator":
                self.operator_var.set(name)
            else:
                self.query_var.set(name)
            self.show_page("orders")
            self.refresh()

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="pedidos.csv", filetypes=[("CSV", "*.csv")])
        if path:
            export_csv(self.rows, path)
            messagebox.showinfo("Exportado", f"Se exportaron {len(self.rows)} pedidos de la vista actual.", parent=self)

    def backup(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".db", initialfile=f"respaldo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db", filetypes=[("SQLite", "*.db")])
        if path:
            try:
                self.db.backup(path)
                messagebox.showinfo("Respaldo listo", "Se guardó una copia completa con pedidos, historial, borrados y protección del borrado.", parent=self)
            except ValueError as exc:
                messagebox.showerror("Respaldo", str(exc), parent=self)

    def switch_db(self):
        if self.busy:
            messagebox.showinfo("Subida en curso", "Espera a que termine la subida.", parent=self)
            return
        path = filedialog.askopenfilename(parent=self, filetypes=[("SQLite", "*.db")])
        if path:
            try:
                candidate = Database(path)
            except Exception as exc:
                messagebox.showerror("Base de datos", str(exc), parent=self)
                return
            self.db.close()
            self.db = candidate
            self.settings["db_path"] = str(self.db.path)
            if not self.isolated:
                save_settings(self.settings)
            self.db_label.configure(text=str(self.db.path))
            self.clear_filters()

    def save_config(self, notify=True):
        repository = self.repo_var.get().strip()
        branch = self.branch_var.get().strip()
        token = self.token_var.get().strip()
        url = self.url_var.get().strip()
        try:
            Publisher(repository, branch, token or "validation-only")
            if not url.startswith("https://"):
                raise ValueError("La dirección del dashboard debe comenzar con https://.")
            encrypted = protect(token) if self.remember_var.get() and token else ""
            self.settings.update(repository=repository, branch=branch, dashboard_url=url, token_encrypted=encrypted)
            if not self.isolated:
                save_settings(self.settings)
            self.token = token
        except (ValueError, OSError) as exc:
            messagebox.showerror("Configuración", str(exc), parent=self)
            return False
        if notify:
            messagebox.showinfo("Configuración", "Configuración guardada.", parent=self)
        return True

    def upload(self):
        if self.busy:
            return
        if not self.save_config(notify=False):
            return
        if not self.token:
            self.show_page("settings")
            messagebox.showinfo("Conectar GitHub", "Introduce tu token de GitHub en Configuración para activar la subida.", parent=self)
            return
        snapshot = self.db.snapshot()
        replace = self.replace_var.get()
        count = len(snapshot["orders"])
        if not messagebox.askyesno("Subir al dashboard", f"Se publicarán {count} pedidos en {self.settings['repository']}.\nTicket, cliente, operador, estatus y fechas serán públicos.\n" + ("Esta subida puede sustituir datos de otra base.\n" if replace else "") + "¿Subir ahora?", parent=self):
            return
        self.busy = True
        self.upload_btn.configure(state="disabled", text="Subiendo…")
        self.sync_label.configure(text="Subiendo la información a GitHub…")
        publish_key = "remote_sha:" + self.settings["repository"] + ":" + self.settings["branch"]
        last_sha = self.db.meta(publish_key)
        publisher = Publisher(self.settings["repository"], self.settings["branch"], self.token)
        def work():
            try:
                sha = publisher.publish(snapshot, last_sha=last_sha, allow_replace=replace)
                self.events.put(("success", (sha, snapshot["meta"]["revision"], snapshot["meta"]["generatedAt"], publish_key)))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            kind, result = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.upload_btn.configure(state="normal", text="↑  Subir a dashboard")
            if kind == "success":
                sha, revision, stamp, key = result
                self.db.set_meta(key, sha)
                self.db.set_meta("published_revision", revision)
                self.db.set_meta("published_at", stamp)
                self.replace_var.set(False)
                self.refresh()
                messagebox.showinfo("Subida completada", "GitHub recibió los pedidos. El dashboard consulta los cambios automáticamente; si acabas de actualizar la página, pulsa Actualizar datos.", parent=self)
            else:
                self.refresh()
                messagebox.showerror("No se pudo subir", result, parent=self)
        self.after(100, self.poll)

    def periodic_refresh(self):
        if not self.busy and not self.grab_current():
            self.refresh(silent=True)
        self.after(15000, self.periodic_refresh)

    def open_dashboard(self):
        webbrowser.open(self.url_var.get().strip() or DEFAULTS["dashboard_url"])

    def focus_search(self):
        self.show_page("orders")
        self.search_entry.focus_set()

    def close_app(self):
        if self.busy:
            messagebox.showinfo("Subida en curso", "Espera a que finalice antes de cerrar.", parent=self)
            return
        self.db.close()
        self.destroy()

    def report_callback_exception(self, exc, value, tb):
        logging.error("Error de interfaz", exc_info=(exc, value, tb))
        messagebox.showerror("PRODU Control", f"No se pudo completar la operación: {value}\nLos pedidos guardados permanecen en la base.", parent=self)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="Ruta a un archivo de base de datos")
    parser.add_argument("--self-test", action="store_true", help="Comprobar el ejecutable sin abrir la interfaz")
    args = parser.parse_args()
    if args.self_test:
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "test.db")
            order_id = db.save("TEST-001", "Cliente de prueba", "Operador de prueba")
            db.save("TEST-001", "Cliente de prueba", "Operador de prueba", STATUSES[3], order_id=order_id)
            assert summary(db.search())[STATUSES[3]] == 1
            assert db.snapshot()["orders"][0]["status"] == STATUSES[3]
            db.set_delete_password("Prueba-temporal-1")
            db.delete(order_id, "Prueba-temporal-1", "Prueba del ejecutable", "self-test")
            assert not db.search() and not db.snapshot()["orders"]
            assert db.deleted()[0]["deleted_reason"] == "Prueba del ejecutable"
            assert db.history(order_id)[0]["action"] == "Borrado"
            db.close()
        return
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=SETTINGS_DIR / "errores.log", level=logging.ERROR, encoding="utf-8")
    try:
        app = Application(db_path=args.db)
        app.mainloop()
    except Exception as exc:
        logging.exception("Inicio")
        messagebox.showerror("No se pudo iniciar", f"{exc}\nCopia el programa a una carpeta con permisos de escritura y vuelve a abrirlo.")


if __name__ == "__main__":
    main()
