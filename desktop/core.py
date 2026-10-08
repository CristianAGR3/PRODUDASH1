"""SQLite storage and dashboard export for PRODU Control."""
from __future__ import annotations
import csv
import hashlib
import hmac
import json
import secrets
import sqlite3
import unicodedata
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

STATUSES = ("En proceso", "En resguardo", "Terminado", "Entregado a cliente")
MX = ZoneInfo("America/Mexico_City")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFD", str(value))
                   if not unicodedata.combining(c)).casefold().strip()


def local_datetime(value):
    return datetime.fromisoformat(value).astimezone(MX)


def display_date(value):
    return local_datetime(value).strftime("%d/%m/%Y %H:%M") if value else "—"


def validate_date(value):
    if value:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Escribe las fechas como AAAA-MM-DD, por ejemplo 2026-10-08.") from None


def summary(rows):
    counts = Counter(r["status"] for r in rows)
    return {"total": len(rows), "pending": len(rows) - counts[STATUSES[3]],
            **{s: counts[s] for s in STATUSES}}


def ranking(rows, field):
    groups = {}
    for row in rows:
        key = normalized(row[field])
        groups.setdefault(key, {"name": row[field], "rows": []})["rows"].append(row)
    result = [{"name": g["name"], **summary(g["rows"])} for g in groups.values()]
    return sorted(result, key=lambda r: (-r["pending"], -r["total"], normalized(r["name"])))


class Database:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        existing = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version not in (0, 1, 2) or (existing and not any(r[0] == "orders" for r in existing)):
            self.conn.close()
            raise ValueError("El archivo elegido no es una base de PRODU Control compatible.")
        self.migration_backup = None
        if version == 1:
            self.migration_backup = self.path.with_name(
                f"{self.path.stem}_respaldo_antes_1_1_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db")
            with closing(sqlite3.connect(self.migration_backup)) as target:
                self.conn.backup(target)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY, ticket TEXT NOT NULL UNIQUE COLLATE NOCASE,
                client TEXT NOT NULL, operator TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN
                    ('En proceso','En resguardo','Terminado','Entregado a cliente')),
                notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, delivered_at TEXT,
                deleted_at TEXT, deleted_reason TEXT NOT NULL DEFAULT '',
                deleted_by TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
                changed_at TEXT NOT NULL, action TEXT NOT NULL,
                before_json TEXT, after_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS orders_status_idx ON orders(status);
            CREATE INDEX IF NOT EXISTS history_order_idx ON history(order_id);
        """)
        with self.conn:
            columns = {r[1] for r in self.conn.execute("PRAGMA table_info(orders)")}
            for field, definition in (("deleted_at", "TEXT"),
                                      ("deleted_reason", "TEXT NOT NULL DEFAULT ''"),
                                      ("deleted_by", "TEXT NOT NULL DEFAULT ''")):
                if field not in columns:
                    self.conn.execute(f"ALTER TABLE orders ADD COLUMN {field} {definition}")
            self.conn.execute("CREATE INDEX IF NOT EXISTS orders_deleted_idx ON orders(deleted_at)")
            self.conn.execute("PRAGMA user_version = 2")
            self.conn.execute("INSERT OR IGNORE INTO metadata VALUES ('database_id', ?)", (str(uuid.uuid4()),))
            self.conn.execute("INSERT OR IGNORE INTO metadata VALUES ('revision', '0')")
        self.conn.execute("PRAGMA journal_mode = WAL")

    def close(self):
        self.conn.close()

    def meta(self, key):
        r = self.conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return r[0] if r else ""

    def set_meta(self, key, value):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, str(value)))

    def get(self, order_id, include_deleted=False):
        sql = "SELECT * FROM orders WHERE id=?" + ("" if include_deleted else " AND deleted_at IS NULL")
        r = self.conn.execute(sql, (order_id,)).fetchone()
        if r is None:
            raise ValueError("El pedido ya no está disponible.")
        return dict(r)

    def password_configured(self):
        return bool(self.meta("delete_password"))

    def verify_delete_password(self, password):
        raw = self.meta("delete_password")
        if not raw:
            raise ValueError("Define primero la contraseña de borrado.")
        if not isinstance(password, str) or not 1 <= len(password) <= 256:
            return False
        try:
            record = json.loads(raw)
            if record.get("algorithm") != "pbkdf2-sha256" or not 100000 <= int(record["iterations"]) <= 2000000:
                raise ValueError
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                         bytes.fromhex(record["salt"]), int(record["iterations"])).hex()
            return hmac.compare_digest(actual, record["digest"])
        except (ValueError, KeyError, TypeError):
            raise ValueError("La configuración de la contraseña no es compatible.") from None

    def set_delete_password(self, password, current_password=None):
        if not isinstance(password, str) or not 8 <= len(password) <= 256:
            raise ValueError("La contraseña debe tener entre 8 y 256 caracteres.")
        if not password.strip():
            raise ValueError("La contraseña no puede contener solamente espacios.")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            if self.password_configured() and not self.verify_delete_password(current_password):
                raise ValueError("La contraseña actual es incorrecta.")
            salt = secrets.token_bytes(32)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600000).hex()
            record = {"algorithm": "pbkdf2-sha256", "iterations": 600000,
                      "salt": salt.hex(), "digest": digest}
            self.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('delete_password', ?)",
                              (json.dumps(record),))

    def delete(self, order_id, password, reason, deleted_by, expected_updated=None):
        reason, deleted_by = str(reason).strip(), str(deleted_by).strip()
        if not 3 <= len(reason) <= 1000:
            raise ValueError("Escribe el motivo del borrado (entre 3 y 1000 caracteres).")
        if not deleted_by or len(deleted_by) > 160:
            raise ValueError("No se pudo identificar al usuario del borrado.")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            if not self.verify_delete_password(password):
                raise ValueError("Contraseña incorrecta. El pedido no se borró.")
            before = self.get(order_id)
            if expected_updated and before["updated_at"] != expected_updated:
                raise ValueError("Otra sesión modificó este pedido. Revisa sus datos antes de borrarlo.")
            stamp = now()
            self.conn.execute("UPDATE orders SET deleted_at=?,deleted_reason=?,deleted_by=?,updated_at=? WHERE id=?",
                              (stamp, reason, deleted_by, stamp, order_id))
            after = self.get(order_id, include_deleted=True)
            self.conn.execute("INSERT INTO history(order_id,changed_at,action,before_json,after_json) VALUES(?,?,?,?,?)",
                              (order_id, stamp, "Borrado", json.dumps(before, ensure_ascii=False),
                               json.dumps(after, ensure_ascii=False)))
            self.conn.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        return after

    def deleted(self, query=""):
        q = normalized(query)
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM orders WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC,id DESC")]
        return [r for r in rows if not q or q in normalized(" ".join(str(r[k]) for k in
                ("ticket", "client", "operator", "deleted_reason", "deleted_by")))]

    def save(self, ticket, client, operator, status=STATUSES[0], notes="", order_id=None, expected_updated=None):
        fields = {"ticket": str(ticket).strip(), "client": str(client).strip(),
                  "operator": str(operator).strip(), "status": status, "notes": str(notes).strip()}
        for name, label in (("ticket", "ticket"), ("client", "cliente"), ("operator", "operador")):
            if not fields[name]:
                raise ValueError(f"El campo {label} es obligatorio.")
            if len(fields[name]) > (80 if name == "ticket" else 160):
                raise ValueError(f"El campo {label} es demasiado largo.")
            if any(ord(c) < 32 for c in fields[name]):
                raise ValueError(f"El campo {label} contiene caracteres no válidos.")
        if status not in STATUSES:
            raise ValueError("Elige un estatus válido.")
        if len(fields["notes"]) > 4000:
            raise ValueError("Las observaciones admiten hasta 4000 caracteres.")
        stamp = now()
        before = None
        try:
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                if order_id is not None:
                    before = self.get(order_id)
                    if expected_updated and before["updated_at"] != expected_updated:
                        raise ValueError("Otra sesión modificó este pedido. Cierra y vuelve a abrirlo antes de guardar.")
                    delivered = (before["delivered_at"] or stamp) if status == STATUSES[3] else None
                    self.conn.execute("""UPDATE orders SET ticket=?, client=?, operator=?, status=?,
                        notes=?, updated_at=?, delivered_at=? WHERE id=?""",
                        (*fields.values(), stamp, delivered, order_id))
                else:
                    delivered = stamp if status == STATUSES[3] else None
                    cur = self.conn.execute("""INSERT INTO orders
                        (ticket,client,operator,status,notes,created_at,updated_at,delivered_at)
                        VALUES (?,?,?,?,?,?,?,?)""", (*fields.values(), stamp, stamp, delivered))
                    order_id = cur.lastrowid
                after = self.get(order_id)
                self.conn.execute("INSERT INTO history(order_id,changed_at,action,before_json,after_json) VALUES(?,?,?,?,?)",
                                  (order_id, stamp, "Actualización" if before else "Registro",
                                   json.dumps(before, ensure_ascii=False) if before else None,
                                   json.dumps(after, ensure_ascii=False)))
                self.conn.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        except sqlite3.IntegrityError as exc:
            if "orders.ticket" in str(exc):
                raise ValueError("Ese ticket ya está registrado. Consúltalo en Pedidos o Borrados; cada ticket es único.") from None
            raise
        return order_id

    def search(self, query="", status="Todos", operator="Todos", date_from="", date_to=""):
        validate_date(date_from)
        validate_date(date_to)
        if date_from and date_to and date_from > date_to:
            raise ValueError("La fecha inicial no puede ser mayor que la final.")
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM orders WHERE deleted_at IS NULL ORDER BY created_at DESC,id DESC")]
        q = normalized(query)
        return [r for r in rows
                if (not q or q in normalized(" ".join(str(r[k]) for k in ("ticket", "client", "operator", "notes"))))
                and (status == "Todos" or r["status"] == status)
                and (operator == "Todos" or normalized(r["operator"]) == normalized(operator))
                and (not date_from or local_datetime(r["created_at"]).date().isoformat() >= date_from)
                and (not date_to or local_datetime(r["created_at"]).date().isoformat() <= date_to)]

    def names(self, field):
        if field not in ("operator", "client"):
            raise ValueError("Campo inválido.")
        names = {}
        for r in self.conn.execute(f"SELECT {field} FROM orders WHERE deleted_at IS NULL ORDER BY id"):
            names.setdefault(normalized(r[0]), r[0])
        return sorted(names.values(), key=normalized)

    def history(self, order_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM history WHERE order_id=? ORDER BY id DESC", (order_id,))]

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination == self.path:
            raise ValueError("El respaldo debe guardarse en otro archivo.")
        if destination.exists():
            raise ValueError("El archivo de respaldo ya existe. Elige un nombre nuevo.")
        with closing(sqlite3.connect(destination)) as target:
            self.conn.backup(target)

    def snapshot(self):
        with self.conn:
            self.conn.execute("BEGIN")
            rows = self.search()
            database_id = self.meta("database_id")
            revision = int(self.meta("revision"))
        orders = []
        for r in rows:
            dt = local_datetime(r["created_at"])
            orders.append({"id": r["ticket"], "client": r["client"], "operator": r["operator"],
                           "cutter": r["operator"], "status": r["status"],
                           "movement": "Producción", "production": "TERMINADO" if r["status"] in STATUSES[2:] else r["status"].upper(),
                           "delivery": "ENTREGADO" if r["status"] == STATUSES[3] else "PENDIENTE",
                           "receiver": "SIN REGISTRO", "driver": None,
                           "date": dt.strftime("%d/%m/%Y"), "time": dt.strftime("%H:%M"),
                           "recordAt": dt.isoformat(), "updatedAt": r["updated_at"], "deliveredAt": r["delivered_at"]})
        return {"meta": {"schemaVersion": 4, "generatedAt": now(), "source": "SQLite · PRODU Control",
                         "sourceModifiedAt": max((r["updated_at"] for r in rows), default=None),
                         "lastRecordAt": rows[0]["created_at"] if rows else None,
                         "totalOrders": len(rows), "databaseId": database_id, "revision": revision}, "orders": orders}


def export_csv(rows, path):
    def safe(value):
        s = str(value or "")
        return "'" + s if s.lstrip().startswith(("=", "+", "-", "@")) else s
    with open(path, "w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["Ticket", "Cliente", "Operador", "Estatus", "Registro", "Última modificación", "Entrega", "Observaciones"])
        for r in rows:
            writer.writerow([safe(r[k]) for k in ("ticket", "client", "operator", "status")] +
                            [display_date(r[k]) for k in ("created_at", "updated_at", "delivered_at")] + [safe(r["notes"])])
