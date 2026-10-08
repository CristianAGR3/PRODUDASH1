"""Password-protected deletion and the local deletion register."""
import getpass
import sqlite3
import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from core import display_date


class DeletionMixin:
    def build_deleted(self, page):
        header = ttk.Frame(page)
        header.pack(fill="x", pady=(0, 14))
        self.deleted_query = tk.StringVar()
        ttk.Label(header, text="Buscar ticket, cliente, operador, usuario o motivo", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(header)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.deleted_query, width=42).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Ver detalle e historial", bootstyle="secondary-outline", command=self.show_deleted_history).pack(side="left", padx=(10, 0))
        self.deleted_query.trace_add("write", lambda *args: self.refresh_deleted())
        self.deleted_count = ttk.Label(page, text="", style="Muted.TLabel")
        self.deleted_count.pack(anchor="w", pady=(0, 10))
        detail = ttk.Frame(page, style="Surface.TFrame", padding=15)
        detail.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Label(detail, text="Motivo del borrado", style="DetailTitle.TLabel").pack(anchor="w")
        self.deleted_reason_label = ttk.Label(detail, text="Selecciona un registro para revisar lo que se borró.", style="Surface.TLabel", wraplength=860)
        self.deleted_reason_label.pack(anchor="w", pady=(5, 5))
        self.deleted_meta_label = ttk.Label(detail, text="", style="SurfaceMuted.TLabel", wraplength=860)
        self.deleted_meta_label.pack(anchor="w")
        self.deleted_tree = self.make_tree(page, (("ticket", "Ticket", 100), ("client", "Cliente", 180),
            ("operator", "Operador", 115), ("status", "Estatus al borrar", 170),
            ("deleted_at", "Fecha de borrado", 150), ("reason", "Motivo", 260), ("user", "Usuario", 130)), height=5)
        self.deleted_tree.bind("<<TreeviewSelect>>", lambda event: self.render_deleted_detail())
        self.deleted_tree.bind("<Double-1>", lambda event: self.show_deleted_history())

    def refresh_deleted(self):
        if not hasattr(self, "deleted_tree"):
            return
        selected = self.deleted_tree.selection()
        keep = selected[0] if selected else None
        rows = self.db.deleted(self.deleted_query.get())
        self.deleted_tree.delete(*self.deleted_tree.get_children())
        for index, row in enumerate(rows):
            self.deleted_tree.insert("", "end", iid=str(row["id"]), tags=("odd" if index % 2 else "even",), values=(
                row["ticket"], row["client"], row["operator"], row["status"], display_date(row["deleted_at"]),
                row["deleted_reason"].replace("\n", " "), row["deleted_by"]))
        total = self.db.conn.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NOT NULL").fetchone()[0]
        self.deleted_count.configure(text=f"{len(rows)} de {total} borrados · Se conservan los datos y el historial en esta base.")
        if rows:
            self.deleted_tree.selection_set(keep if keep and self.deleted_tree.exists(keep) else str(rows[0]["id"]))
        self.render_deleted_detail()

    def render_deleted_detail(self):
        selected = self.deleted_tree.selection()
        if not selected:
            self.deleted_reason_label.configure(text="No hay borrados en esta búsqueda." if self.deleted_query.get() else "Aquí aparecerán los pedidos que borres y su motivo.")
            self.deleted_meta_label.configure(text="")
            return
        row = self.db.get(int(selected[0]), include_deleted=True)
        reason = row["deleted_reason"]
        self.deleted_reason_label.configure(text=reason if len(reason) <= 240 else reason[:237] + "…  (ver detalle)")
        self.deleted_meta_label.configure(text=f"Ticket #{row['ticket']} · {row['client']} · Operador: {row['operator']}\n"
            f"Borrado: {display_date(row['deleted_at'])} · Usuario de Windows: {row['deleted_by']}")

    def show_deleted_history(self):
        selected = self.deleted_tree.selection()
        if selected:
            self.show_order_history(int(selected[0]), include_deleted=True)
        else:
            messagebox.showinfo("Selecciona un borrado", "Selecciona un registro en la tabla primero.", parent=self)

    def update_password_label(self):
        if hasattr(self, "password_label"):
            configured = self.db.password_configured()
            self.password_label.configure(text="Contraseña definida para esta base. Cada borrado exige contraseña y motivo." if configured else
                "Se definirá al usar Borrar por primera vez. También puedes crearla aquí.")
            self.password_button.configure(text="Cambiar contraseña" if configured else "Crear contraseña")

    def management_dialog(self, title, height):
        dialog = ttk.Toplevel(self)
        dialog.title(title)
        dialog.geometry(f"620x{min(height, self.winfo_screenheight()-120)}")
        dialog.minsize(540, min(470, self.winfo_screenheight()-120))
        dialog.transient(self)
        dialog.grab_set()
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        box = ttk.Frame(dialog, padding=24)
        box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        ttk.Label(box, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16))
        area = ttk.Frame(box)
        area.grid(row=1, column=0, sticky="nsew")
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        canvas = tk.Canvas(area, highlightthickness=0, background=self.palette["bg"])
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        body = ttk.Frame(canvas, padding=(0, 0, 12, 4))
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_id, width=event.width))
        dialog.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta/120), "units") if event.widget.winfo_class() != "Text" else None)
        footer = ttk.Frame(box)
        footer.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        ttk.Separator(footer).pack(fill="x", pady=(0, 8))
        error = ttk.Label(footer, text="", foreground=self.palette["error"], wraplength=530)
        error.pack(fill="x", pady=(0, 8))
        buttons = ttk.Frame(footer)
        buttons.pack(fill="x")
        buttons.columnconfigure(0, weight=1)
        cancel = ttk.Button(buttons, text="Cancelar", width=12, bootstyle="secondary-outline", command=dialog.destroy)
        cancel.grid(row=0, column=1, sticky="e", padx=(0, 10))
        return dialog, body, buttons, error, cancel

    def configure_delete_password(self, on_success=None):
        configured = self.db.password_configured()
        dialog, body, buttons, error, cancel = self.management_dialog("Cambiar contraseña de borrado" if configured else "Crear contraseña de borrado", 550)
        ttk.Label(body, text="Esta contraseña autoriza el borrado de pedidos de esta base. Usa al menos 8 caracteres y guárdala en un lugar seguro.", style="Muted.TLabel", wraplength=510).pack(anchor="w", pady=(0, 12))
        variables, entries = {}, []
        fields = (("current", "Contraseña actual"),) if configured else ()
        for key, caption in (*fields, ("new", "Nueva contraseña"), ("repeat", "Repite la nueva contraseña")):
            ttk.Label(body, text=caption).pack(anchor="w", pady=(8, 4))
            variables[key] = tk.StringVar()
            entry = ttk.Entry(body, textvariable=variables[key], show="●")
            entry.pack(fill="x")
            entries.append(entry)
        def save():
            try:
                if variables["new"].get() != variables["repeat"].get():
                    raise ValueError("Las contraseñas no coinciden.")
                self.db.set_delete_password(variables["new"].get(), variables["current"].get() if configured else None)
            except (ValueError, sqlite3.Error) as exc:
                error.configure(text=str(exc))
                return
            for var in variables.values():
                var.set("")
            dialog.destroy()
            self.update_password_label()
            if on_success:
                on_success()
        button = ttk.Button(buttons, text="Guardar contraseña", width=20, bootstyle="success", command=save)
        button.grid(row=0, column=2, sticky="e")
        dialog.bind("<Control-Return>", lambda event: save())
        entries[0].focus_set()
        return {"dialog": dialog, "variables": variables, "save": save, "error": error, "save_button": button, "cancel_button": cancel}

    def delete_selected(self):
        if self.busy:
            messagebox.showinfo("Subida en curso", "Espera a que termine la subida para borrar pedidos.", parent=self)
            return
        order_id = self.selected_id()
        if order_id is None:
            return
        if not self.db.password_configured():
            return self.configure_delete_password(on_success=lambda: self.delete_order(order_id))
        return self.delete_order(order_id)

    def delete_order(self, order_id):
        try:
            row = self.db.get(order_id)
        except ValueError as exc:
            messagebox.showinfo("Pedido", str(exc), parent=self)
            return
        dialog, body, buttons, error, cancel = self.management_dialog("Borrar pedido", 580)
        preview = ttk.Frame(body, style="Surface.TFrame", padding=14)
        preview.pack(fill="x", pady=(0, 12))
        ttk.Label(preview, text=f"Ticket #{row['ticket']}", style="DetailTitle.TLabel", wraplength=480).pack(anchor="w")
        ttk.Label(preview, text=f"Cliente: {row['client']}\nOperador: {row['operator']}\nEstatus: {row['status']}", style="Surface.TLabel", wraplength=480).pack(anchor="w", pady=(5, 0))
        ttk.Label(body, text="Se retirará de los pedidos activos. El registro y su motivo quedarán en Borrados. Pulsa Subir a dashboard para actualizar la página.", style="Muted.TLabel", wraplength=510).pack(anchor="w", pady=(0, 12))
        ttk.Label(body, text="Contraseña de borrado *").pack(anchor="w", pady=(0, 4))
        password = tk.StringVar()
        entry = ttk.Entry(body, textvariable=password, show="●")
        entry.pack(fill="x")
        ttk.Label(body, text="Motivo del borrado *").pack(anchor="w", pady=(12, 4))
        reason = tk.Text(body, height=3, wrap="word", font=("Segoe UI", 10), background=self.palette["panel"],
                         foreground=self.palette["text"], insertbackground=self.palette["text"], relief="solid", bd=1)
        reason.pack(fill="x")
        account = getpass.getuser()
        ttk.Label(body, text=f"Usuario de Windows registrado: {account}", style="Muted.TLabel", wraplength=510).pack(anchor="w", pady=(8, 0))
        def confirm():
            try:
                self.db.delete(order_id, password.get(), reason.get("1.0", "end-1c"), account, expected_updated=row["updated_at"])
            except (ValueError, sqlite3.Error) as exc:
                password.set("")
                error.configure(text=str(exc))
                return
            password.set("")
            dialog.destroy()
            self.deleted_query.set("")
            self.refresh(silent=True)
            self.show_page("deleted")
            self.deleted_tree.selection_set(str(order_id))
            self.deleted_tree.see(str(order_id))
            self.render_deleted_detail()
        button = ttk.Button(buttons, text="Confirmar borrado", width=20, bootstyle="danger", command=confirm)
        button.grid(row=0, column=2, sticky="e")
        entry.focus_set()
        return {"dialog": dialog, "password": password, "reason": reason, "confirm": confirm, "error": error,
                "save_button": button, "cancel_button": cancel}
