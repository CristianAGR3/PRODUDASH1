"""Presentation, themes and charts for the desktop application."""
import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from core import STATUSES, display_date, ranking, summary
from sync import save_settings


LIGHT = {"bg": "#f2f5f3", "panel": "#ffffff", "soft": "#eaf0ec", "text": "#183c31",
         "muted": "#617b6f", "accent": "#168265", "sidebar": "#153c30", "error": "#b44949",
         "tones": ["#b87920", "#8160aa", "#238269", "#4475ad"],
         "tints": ["#fff4df", "#f3ecfc", "#e9f6ed", "#eaf2fd"]}
DARK = {"bg": "#111c18", "panel": "#1b2c24", "soft": "#23392e", "text": "#e5f1e9",
        "muted": "#a0bbae", "accent": "#39a77c", "sidebar": "#10291e", "error": "#f19999",
        "tones": ["#e6b76a", "#c3a0eb", "#7bd4af", "#90b9ee"],
        "tints": ["#352d1d", "#30233d", "#1c3c30", "#223650"]}


class AppearanceMixin:
    def initialize_appearance(self):
        self.dark = self.settings.get("theme") == "dark"
        self.palette = DARK if self.dark else LIGHT
        self.canvas_surfaces = []
        self.card_values = []
        self.card_lines = []

    def apply_styles(self):
        self.palette = p = DARK if self.dark else LIGHT
        self.configure(background=p["bg"])
        self.style.configure("TFrame", background=p["bg"])
        self.style.configure("TLabel", background=p["bg"], foreground=p["text"], font=("Segoe UI", 10))
        self.style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"], font=("Segoe UI", 9))
        self.style.configure("Eyebrow.TLabel", background=p["bg"], foreground=p["muted"], font=("Segoe UI", 9, "bold"))
        self.style.configure("Warning.TLabel", background=p["bg"], foreground=p["tones"][0], font=("Segoe UI", 9))
        self.style.configure("TButton", font=("Segoe UI", 9), padding=(10, 7))
        self.style.configure("secondary.Outline.TButton", foreground=p["text"], bordercolor=p["muted"], background=p["bg"])
        self.style.map("secondary.Outline.TButton", foreground=[("disabled", p["muted"]), ("active", "#ffffff"), ("!disabled", p["text"])],
                       background=[("active", p["accent"])], bordercolor=[("active", p["accent"]), ("!disabled", p["muted"])])
        self.style.configure("Title.TLabel", background=p["bg"], foreground=p["text"], font=("Segoe UI", 24, "bold"))
        self.style.configure("Section.TLabel", background=p["bg"], foreground=p["text"], font=("Segoe UI", 13, "bold"))
        self.style.configure("Surface.TFrame", background=p["panel"])
        self.style.configure("Surface.TLabel", background=p["panel"], foreground=p["text"], font=("Segoe UI", 10))
        self.style.configure("SurfaceMuted.TLabel", background=p["panel"], foreground=p["muted"], font=("Segoe UI", 9))
        self.style.configure("Card.TFrame", background=p["panel"], borderwidth=1, relief="solid", bordercolor=p["soft"])
        self.style.configure("CardCaption.TLabel", background=p["panel"], foreground=p["muted"], font=("Segoe UI", 9, "bold"))
        self.style.configure("CardValue.TLabel", background=p["panel"], foreground=p["text"], font=("Segoe UI", 25, "bold"))
        self.style.configure("CardName.TLabel", background=p["panel"], foreground=p["text"], font=("Segoe UI", 15, "bold"))
        self.style.configure("CardNote.TLabel", background=p["panel"], foreground=p["muted"], font=("Segoe UI", 9))
        self.style.configure("DetailTitle.TLabel", background=p["panel"], foreground=p["text"], font=("Segoe UI", 13, "bold"))
        self.style.configure("Treeview", rowheight=41, font=("Segoe UI", 10), background=p["panel"],
                             fieldbackground=p["panel"], foreground=p["text"], borderwidth=0)
        self.style.configure("Treeview.Heading", background=p["soft"], foreground=p["muted"],
                             font=("Segoe UI", 10, "bold"), padding=(8, 12))
        self.style.map("Treeview", background=[("selected", p["accent"])], foreground=[("selected", "#ffffff")])
        for canvas, role in list(self.canvas_surfaces):
            if canvas.winfo_exists():
                canvas.configure(background=p[role])
        for line, index in self.card_lines:
            line.configure(background=p["tones"][index] if index is not None else p["accent"])
        for widget, index in self.card_values:
            widget.configure(foreground=p["tones"][index] if index is not None else p["text"])
        trees = [getattr(self, "order_tree", None), getattr(self, "deleted_tree", None),
                 getattr(self, "delivery_tree", None), *getattr(self, "rank_trees", {}).values()]
        for tree in trees:
            if tree:
                tree.tag_configure("even", background=p["panel"], foreground=p["text"])
                tree.tag_configure("odd", background=p["soft"], foreground=p["text"])
        for name in ("subtitle", "sync_label", "footer", "result_label", "analysis_label", "db_label"):
            widget = getattr(self, name, None)
            if widget:
                widget.configure(foreground=p["muted"])
        if hasattr(self, "repaint_sidebar"):
            self.repaint_sidebar(self.sidebar)
            for key, button in self.nav.items():
                button.configure(bg="#2c5b47" if key == self.page_name else p["sidebar"], fg="#eaf6ee")
        if hasattr(self, "theme_button"):
            self.theme_button.configure(text="☀  Modo claro" if self.dark else "☾  Modo oscuro")
        if hasattr(self, "order_detail"):
            self.render_order_detail()

    def toggle_theme(self):
        self.dark = not self.dark
        self.style.theme_use("darkly" if self.dark else "litera")
        self.settings["theme"] = "dark" if self.dark else "light"
        self.apply_styles()
        self.refresh(silent=True)
        if not self.isolated:
            try:
                save_settings(self.settings)
            except OSError as exc:
                messagebox.showerror("Preferencia", f"El tema se aplicó, pero no se pudo guardar: {exc}", parent=self)

    def make_stat_card(self, parent, column, caption, index=None, name=False, compact=False):
        parent.columnconfigure(column, weight=1, uniform="metrics")
        frame = ttk.Frame(parent, style="Card.TFrame", padding=(11, 6 if compact else 11))
        frame.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 5))
        line = tk.Frame(frame, height=3)
        line.pack(fill="x", pady=(0, 5 if compact else 8))
        self.card_lines.append((line, index))
        ttk.Label(frame, text=caption, style="CardCaption.TLabel").pack(anchor="w")
        value = ttk.Label(frame, text="0", style="CardName.TLabel" if name else "CardValue.TLabel", wraplength=210 if name else 0)
        if compact:
            value.configure(font=("Segoe UI", 19, "bold"))
        value.pack(anchor="w", pady=(3, 1))
        note = ttk.Label(frame, text="", style="CardNote.TLabel")
        if not compact:
            note.pack(anchor="w")
        self.card_values.append((value, index))
        return value, note

    def build_order_detail(self, page):
        self.order_detail = ttk.Frame(page, style="Surface.TFrame", padding=(15, 10))
        self.order_detail.pack(side="bottom", fill="x", pady=(10, 0))
        self.order_detail.columnconfigure(0, weight=1)
        self.detail_title = ttk.Label(self.order_detail, text="Selecciona un pedido", style="DetailTitle.TLabel", wraplength=600)
        self.detail_title.grid(row=0, column=0, sticky="w")
        self.detail_status = ttk.Label(self.order_detail, text="", padding=(9, 5), font=("Segoe UI", 10, "bold"))
        self.detail_status.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(12, 0))
        self.detail_client = ttk.Label(self.order_detail, text="", style="Surface.TLabel", wraplength=680)
        self.detail_client.grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.detail_dates = ttk.Label(self.order_detail, text="", style="SurfaceMuted.TLabel", wraplength=920)
        self.detail_dates.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.detail_notes = ttk.Label(self.order_detail, text="", style="SurfaceMuted.TLabel", wraplength=900)

    def render_order_detail(self):
        selected = self.order_tree.selection() if hasattr(self, "order_tree") else ()
        if not selected:
            self.detail_title.configure(text="Selecciona un pedido para consultar su detalle")
            self.detail_client.configure(text="Doble clic en una fila para editar sus datos o cambiar el estatus.")
            self.detail_dates.configure(text="")
            self.detail_status.configure(text="", background=self.palette["panel"])
            self.detail_notes.grid_remove()
            return
        try:
            row = self.db.get(int(selected[0]))
        except ValueError:
            return
        self.detail_title.configure(text=f"Ticket #{row['ticket']}")
        self.detail_client.configure(text=f"{row['client']}  ·  Operador: {row['operator']}")
        index = STATUSES.index(row["status"])
        self.detail_status.configure(text="✓ " + row["status"] if index == 3 else "● " + row["status"],
                                     background=self.palette["tints"][index], foreground=self.palette["tones"][index])
        self.detail_dates.configure(text=f"Registro: {display_date(row['created_at'])}   ·   Último cambio: {display_date(row['updated_at'])}" +
                                   (f"   ·   Entrega: {display_date(row['delivered_at'])}" if row["delivered_at"] else ""))
        if row["notes"]:
            self.detail_notes.configure(text="Observaciones: " + row["notes"][:160].replace("\n", " "))
            self.detail_notes.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        else:
            self.detail_notes.grid_remove()
        self.arrange_detail()

    def arrange_detail(self):
        if not hasattr(self, "detail_dates"):
            return
        if getattr(self, "compact_mode", False):
            self.detail_client.grid_remove()
            self.detail_dates.grid_remove()
            self.detail_notes.grid_remove()
        else:
            self.detail_client.grid()
            self.detail_dates.grid()

    def adapt_layout(self, event=None):
        if event is not None and event.widget is not self:
            return
        compact = self.winfo_height() < 800
        if getattr(self, "compact_mode", None) == compact:
            return
        self.compact_mode = compact
        self.arrange_detail()
        if hasattr(self, "eyebrow"):
            if compact:
                self.eyebrow.pack_forget()
                self.subtitle.pack_forget()
                self.order_summary_caption.pack_forget()
            else:
                self.eyebrow.pack(anchor="w", before=self.title_label)
                self.subtitle.pack(anchor="w")
                self.order_summary_caption.pack(anchor="w", pady=(0, 8), before=self.order_cards)
            self.edit_button.configure(text="Editar" if compact else "Editar / estatus")
            self.csv_button.configure(text="CSV" if compact else "Exportar CSV")
        if hasattr(self, "analysis_metric_frame"):
            if compact:
                self.analysis_metric_frame.pack_forget()
            else:
                self.analysis_metric_frame.pack(fill="x", pady=(0, 14), before=self.analysis_charts_frame)
            self.operator_canvas.configure(height=144 if compact else 160)
            self.status_canvas.configure(height=144 if compact else 160)
            self.draw_analysis_charts()

    def build_analysis(self, page):
        self.analysis_label = ttk.Label(page, text="", foreground=self.palette["muted"], wraplength=930)
        self.analysis_label.pack(anchor="w", pady=(0, 12))
        metrics = ttk.Frame(page)
        self.analysis_metric_frame = metrics
        metrics.pack(fill="x", pady=(0, 14))
        self.analysis_metrics = {}
        for column, (key, caption, index, named) in enumerate((("total", "PEDIDOS EN LA VISTA", None, False),
                ("pending", "POR ENTREGAR", 0, False), ("leader", "MAYOR CARGA", 1, True), ("delivered", "ENTREGADOS", 3, False))):
            self.analysis_metrics[key] = self.make_stat_card(metrics, column, caption, index, named)
        charts = ttk.Frame(page)
        self.analysis_charts_frame = charts
        charts.pack(fill="x", pady=(0, 14))
        charts.columnconfigure(0, weight=3)
        charts.columnconfigure(1, weight=2)
        self.operator_canvas = self.chart_panel(charts, 0, "Carga por operador", "Los seis operadores con más pedidos")
        self.status_canvas = self.chart_panel(charts, 1, "Estado de los pedidos", "Distribución de la vista actual")
        self.operator_canvas.bind("<Configure>", lambda event: self.draw_analysis_charts())
        self.status_canvas.bind("<Configure>", lambda event: self.draw_analysis_charts())
        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)
        self.rank_trees = {}
        cols = (("name", "Responsable", 220), ("total", "Total", 80), ("pending", "Pendientes", 100),
                (STATUSES[0], "En proceso", 110), (STATUSES[1], "En resguardo", 120),
                (STATUSES[2], "Terminado", 105), (STATUSES[3], "Entregados", 110))
        for field, label in (("operator", "Por operador"), ("client", "Por cliente")):
            panel = ttk.Frame(notebook, padding=(10, 10))
            notebook.add(panel, text=label)
            tree = self.make_tree(panel, tuple((f, ("Operador" if field == "operator" else "Cliente") if f == "name" else title, width) for f, title, width in cols), height=3)
            tree.bind("<Double-1>", lambda event, f=field: self.filter_rank(f))
            self.rank_trees[field] = tree
        panel = ttk.Frame(notebook, padding=10)
        notebook.add(panel, text="Entregas por día")
        self.delivery_tree = self.make_tree(panel, (("date", "Fecha de entrega", 220), ("count", "Pedidos entregados", 180)), height=3)

    def chart_panel(self, parent, column, title, subtitle):
        panel = ttk.Frame(parent, style="Surface.TFrame", padding=(14, 10))
        panel.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6))
        ttk.Label(panel, text=title, style="DetailTitle.TLabel").pack(anchor="w")
        ttk.Label(panel, text=subtitle, style="SurfaceMuted.TLabel").pack(anchor="w", pady=(3, 7))
        canvas = tk.Canvas(panel, height=160, highlightthickness=0)
        canvas.pack(fill="x")
        self.canvas_surfaces.append((canvas, "panel"))
        return canvas

    def render_analysis(self, values, leader):
        for key, value in (("total", values["total"]), ("pending", values["pending"]),
                           ("delivered", values[STATUSES[3]]), ("leader", leader["name"] if leader else "Sin datos")):
            if key == "leader" and len(str(value)) > 28:
                value = str(value)[:25] + "…"
            self.analysis_metrics[key][0].configure(text=str(value))
        total = values["total"]
        rate = round(values[STATUSES[3]] / total * 100) if total else 0
        self.analysis_metrics["total"][1].configure(text="Filtros de Pedidos aplicados")
        self.analysis_metrics["pending"][1].configure(text="Proceso + resguardo + terminados")
        self.analysis_metrics["delivered"][1].configure(text=f"{rate}% del total")
        self.analysis_metrics["leader"][1].configure(text=f"{leader['total']} pedidos · {leader['pending']} pendientes" if leader else "Registra tu primer pedido")
        self.draw_analysis_charts()

    def draw_analysis_charts(self):
        if not hasattr(self, "operator_canvas"):
            return
        p = self.palette
        canvas = self.operator_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 240)
        groups = sorted(ranking(self.rows, "operator"), key=lambda row: (-row["total"], -row["pending"]))[:6]
        if not groups:
            canvas.create_text(width / 2, 75, text="Sin pedidos asignados todavía", fill=p["muted"], font=("Segoe UI", 10))
        else:
            maximum = max(row["total"] for row in groups)
            label_width = min(120, width * .32)
            bar_width = max(width - label_width - 40, 40)
            step = min(25, max((canvas.winfo_height() - 18) / max(len(groups), 1), 16))
            for index, row in enumerate(groups):
                y = 6 + index * step
                name = row["name"] if len(row["name"]) <= 18 else row["name"][:16] + "…"
                canvas.create_text(0, y + 6, text=name, anchor="w", fill=p["text"], font=("Segoe UI", 9))
                canvas.create_rectangle(label_width, y, label_width + bar_width, y + 13, fill=p["soft"], outline="")
                cursor = label_width
                for stage, status in enumerate(STATUSES):
                    length = row[status] / maximum * bar_width
                    if length:
                        canvas.create_rectangle(cursor, y, cursor + length, y + 13, fill=p["tones"][stage], outline="")
                        cursor += length
                canvas.create_text(width - 4, y + 6, text=str(row["total"]), anchor="e", fill=p["text"], font=("Segoe UI", 10, "bold"))
        canvas = self.status_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        values = summary(self.rows)
        total = values["total"]
        diameter = min(116, max(width * .36, 70))
        x, y = 4, 14
        canvas.create_oval(x, y, x + diameter, y + diameter, fill=p["soft"], outline="")
        start = 90
        if total:
            for index, status in enumerate(STATUSES):
                extent = values[status] / total * 360
                if extent:
                    canvas.create_arc(x, y, x + diameter, y + diameter, start=start, extent=-extent,
                                      style="pieslice", fill=p["tones"][index], outline=p["panel"], width=1)
                start -= extent
        hole = diameter * .23
        canvas.create_oval(x + hole, y + hole, x + diameter - hole, y + diameter - hole, fill=p["panel"], outline="")
        canvas.create_text(x + diameter / 2, y + diameter / 2 - 7, text=str(total), fill=p["text"], font=("Segoe UI", 19, "bold"))
        canvas.create_text(x + diameter / 2, y + diameter / 2 + 15, text="pedidos", fill=p["muted"], font=("Segoe UI", 8))
        legend_x = diameter + 19
        for index, label in enumerate(("En proceso", "En resguardo", "Terminados", "Entregados")):
            cy = 24 + index * 29
            canvas.create_oval(legend_x, cy, legend_x + 7, cy + 7, fill=p["tones"][index], outline="")
            canvas.create_text(legend_x + 14, cy + 3, text=label, anchor="w", fill=p["muted"], font=("Segoe UI", 8))
            canvas.create_text(width - 2, cy + 3, text=str(values[STATUSES[index]]), anchor="e", fill=p["text"], font=("Segoe UI", 10, "bold"))
