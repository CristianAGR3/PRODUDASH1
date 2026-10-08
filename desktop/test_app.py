import base64
import csv
import json
import tempfile
import unittest
import io
import sqlite3
import urllib.error
from unittest.mock import patch
from pathlib import Path
from core import Database, STATUSES, export_csv, ranking, summary
from sync import Publisher, SyncError, protect, explain_http_error


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "pedidos.db")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add(self, ticket="00001", status=STATUSES[0], operator="José"):
        return self.db.save(ticket, "Cliente Uno", operator, status, notes="Observación local")

    def test_empty_database(self):
        self.assertEqual(self.db.search(), [])
        self.assertEqual(self.db.meta("revision"), "0")

    def test_register_automatic_dates_and_history(self):
        row = self.db.get(self.add())
        self.assertEqual(row["ticket"], "00001")
        self.assertTrue(row["created_at"])
        self.assertEqual(row["created_at"], row["updated_at"])
        self.assertEqual(len(self.db.history(row["id"])), 1)

    def test_duplicate_ticket_rolls_back(self):
        self.add("ABC")
        with self.assertRaises(ValueError):
            self.add(" abc ")
        self.assertEqual(len(self.db.search()), 1)
        self.assertEqual(self.db.meta("revision"), "1")

    def test_required_fields_and_status(self):
        for values in (("", "Cliente", "Op"), ("1", "", "Op"), ("1", "Cliente", "")):
            with self.assertRaises(ValueError):
                self.db.save(*values)
        with self.assertRaises(ValueError):
            self.db.save("1", "Cliente", "Op", "Otro estado")
        self.assertEqual(self.db.search(), [])

    def test_all_statuses_and_pending_counts(self):
        for i, status in enumerate(STATUSES):
            self.add(str(i), status)
        stats = summary(self.db.search())
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["pending"], 3)
        for status in STATUSES:
            self.assertEqual(stats[status], 1)

    def test_delivery_reopen_and_history(self):
        order_id = self.add()
        stamp = self.db.get(order_id)["created_at"]
        for status in STATUSES[1:]:
            self.db.save("00001", "Cliente Uno", "José", status, order_id=order_id)
        self.assertIsNotNone(self.db.get(order_id)["delivered_at"])
        self.db.save("00001", "Cliente Uno", "José", STATUSES[0], order_id=order_id)
        self.assertIsNone(self.db.get(order_id)["delivered_at"])
        self.assertEqual(self.db.get(order_id)["created_at"], stamp)
        self.assertEqual(len(self.db.history(order_id)), 5)

    def test_concurrent_edit_rejected(self):
        order_id = self.add()
        old = self.db.get(order_id)["updated_at"]
        other = Database(self.db.path)
        try:
            other.save("00001", "Cliente Uno", "Ana", STATUSES[1], order_id=order_id)
            with self.assertRaises(ValueError):
                self.db.save("00001", "Cliente Uno", "José", order_id=order_id, expected_updated=old)
            self.assertEqual(self.db.get(order_id)["operator"], "Ana")
        finally:
            other.close()

    def test_search_accent_case_and_literal_wildcards(self):
        self.add("ABC%_")
        self.assertEqual(len(self.db.search("jose")), 1)
        self.assertEqual(len(self.db.search("ABC%_")), 1)
        self.assertEqual(len(self.db.search("no existe")), 0)
        self.assertEqual(len(self.db.search(status=STATUSES[3])), 0)

    def test_date_filter_uses_mexico_date(self):
        order_id = self.add()
        with self.db.conn:
            self.db.conn.execute("UPDATE orders SET created_at='2026-10-09T03:00:00+00:00' WHERE id=?", (order_id,))
        self.assertEqual(len(self.db.search(date_from="2026-10-08", date_to="2026-10-08")), 1)
        self.assertEqual(len(self.db.search(date_from="2026-10-09")), 0)
        with self.assertRaises(ValueError):
            self.db.search(date_from="bad")
        with self.assertRaises(ValueError):
            self.db.search(date_from="2026-10-09", date_to="2026-10-08")

    def test_ranking_merges_case_and_accent(self):
        self.add("1", operator="José")
        self.add("2", operator="JOSE")
        self.add("3", status=STATUSES[3], operator="Ana")
        stats = ranking(self.db.search(), "operator")
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats[0]["total"], 2)
        self.assertEqual(stats[0]["pending"], 2)

    def test_snapshot_preserves_ticket_and_omits_notes(self):
        self.add(status=STATUSES[3])
        snapshot = self.db.snapshot()
        row = snapshot["orders"][0]
        self.assertEqual(row["id"], "00001")
        self.assertEqual(row["delivery"], "ENTREGADO")
        self.assertEqual(row["status"], STATUSES[3])
        self.assertNotIn("notes", row)
        self.assertEqual(snapshot["meta"]["revision"], 1)

    def test_backup_preserves_orders_and_history(self):
        self.add()
        backup = Path(self.temp.name) / "backup.db"
        self.db.backup(backup)
        other = Database(backup)
        try:
            self.assertEqual(len(other.search()), 1)
            self.assertEqual(other.meta("database_id"), self.db.meta("database_id"))
            self.assertEqual(len(other.history(other.search()[0]["id"])), 1)
        finally:
            other.close()

    def test_csv_formula_injection(self):
        self.db.save("=1+1", "+formula", "@name")
        path = Path(self.temp.name) / "orders.csv"
        export_csv(self.db.search(), path)
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[1][0], "'=1+1")
        self.assertEqual(rows[1][1], "'+formula")


class DeletionTests(unittest.TestCase):
    password = "Prueba-borrado-123"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "pedidos.db")
        self.order_id = self.db.save("T-01", "Cliente", "José", notes="Nota conservada")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_first_password_setup_and_rotation(self):
        self.assertFalse(self.db.password_configured())
        for password in ("corta", "        "):
            with self.assertRaises(ValueError):
                self.db.set_delete_password(password)
        self.db.set_delete_password(self.password)
        record = self.db.meta("delete_password")
        self.assertNotIn(self.password, record)
        self.assertTrue(self.db.verify_delete_password(self.password))
        with self.assertRaises(ValueError):
            self.db.set_delete_password("Otra-contraseña", "equivocada")
        self.assertEqual(record, self.db.meta("delete_password"))
        self.db.set_delete_password("Otra-contraseña", self.password)
        self.assertFalse(self.db.verify_delete_password(self.password))
        self.assertTrue(self.db.verify_delete_password("Otra-contraseña"))
        self.assertEqual(self.db.meta("revision"), "1")

    def test_rejected_deletions_preserve_orders_history_revision(self):
        with self.assertRaises(ValueError):
            self.db.delete(self.order_id, self.password, "Duplicado", "QA")
        self.db.set_delete_password(self.password)
        for password, reason in (("incorrecta", "Duplicado"), (self.password, "  "), (self.password, "a"), (self.password, "x"*1001)):
            with self.assertRaises(ValueError):
                self.db.delete(self.order_id, password, reason, "QA")
        self.assertEqual(len(self.db.search()), 1)
        self.assertEqual(len(self.db.history(self.order_id)), 1)
        self.assertEqual(self.db.meta("revision"), "1")
        self.assertEqual(self.db.deleted(), [])

    def test_delete_audit_counts_and_snapshot(self):
        self.db.set_delete_password(self.password)
        delivered_id = self.db.save("T-02", "Otro cliente", "Ana", STATUSES[3])
        before = self.db.get(self.order_id)
        deleted = self.db.delete(self.order_id, self.password, "  Captura duplicada  ", "QA Windows", before["updated_at"])
        self.assertEqual(deleted["deleted_reason"], "Captura duplicada")
        self.assertEqual(deleted["deleted_by"], "QA Windows")
        self.assertEqual(deleted["notes"], before["notes"])
        self.assertEqual(deleted["created_at"], before["created_at"])
        self.assertTrue(deleted["deleted_at"])
        self.assertEqual(self.db.meta("revision"), "3")
        self.assertEqual(summary(self.db.search())["total"], 1)
        self.assertEqual(summary(self.db.search())["pending"], 0)
        self.assertEqual(self.db.names("operator"), ["Ana"])
        self.assertEqual([r["id"] for r in self.db.search()], [delivered_id])
        event = self.db.history(self.order_id)[0]
        self.assertEqual(event["action"], "Borrado")
        self.assertEqual(json.loads(event["before_json"]), before)
        self.assertEqual(json.loads(event["after_json"]), deleted)
        self.assertNotIn(self.password, event["after_json"])
        self.assertEqual(len(self.db.deleted("jose")), 1)
        self.assertEqual(len(self.db.deleted("duplicada")), 1)
        self.assertEqual(len(self.db.deleted("qa windows")), 1)
        snapshot = self.db.snapshot()
        self.assertEqual([r["id"] for r in snapshot["orders"]], ["T-02"])
        self.assertEqual(snapshot["meta"]["revision"], 3)
        for secret in ("Captura duplicada", "QA Windows", "delete_password", self.password):
            self.assertNotIn(secret, json.dumps(snapshot))
        with self.assertRaises(ValueError):
            self.db.get(self.order_id)
        with self.assertRaises(ValueError):
            self.db.save("T-01", "Cliente", "José", order_id=self.order_id)
        with self.assertRaises(ValueError):
            self.db.delete(self.order_id, self.password, "De nuevo", "QA")
        self.assertEqual(self.db.meta("revision"), "3")

    def test_stale_deletion_rejected(self):
        self.db.set_delete_password(self.password)
        before = self.db.get(self.order_id)
        other = Database(self.db.path)
        try:
            other.save("T-01", "Cliente", "Ana", STATUSES[2], order_id=self.order_id)
            with self.assertRaises(ValueError):
                self.db.delete(self.order_id, self.password, "Duplicado", "QA", before["updated_at"])
            self.assertEqual(self.db.get(self.order_id)["operator"], "Ana")
            self.assertEqual(self.db.deleted(), [])
            self.assertEqual(self.db.meta("revision"), "2")
        finally:
            other.close()

    def test_backup_preserves_password_and_deletions(self):
        self.db.set_delete_password(self.password)
        self.db.delete(self.order_id, self.password, "Cancelado por cliente", "QA")
        target = Path(self.temp.name) / "respaldo.db"
        self.db.backup(target)
        copy = Database(target)
        try:
            self.assertTrue(copy.verify_delete_password(self.password))
            self.assertEqual(copy.deleted(), self.db.deleted())
            self.assertEqual(copy.history(self.order_id), self.db.history(self.order_id))
        finally:
            copy.close()

    def test_version_one_migration_preserves_records_and_backup(self):
        target = Path(self.temp.name) / "version1.db"
        conn = sqlite3.connect(target)
        conn.executescript("""
            CREATE TABLE orders (id INTEGER PRIMARY KEY, ticket TEXT NOT NULL UNIQUE COLLATE NOCASE,
                client TEXT NOT NULL, operator TEXT NOT NULL, status TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, delivered_at TEXT);
            CREATE TABLE history (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
                changed_at TEXT NOT NULL, action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL);
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata VALUES ('database_id','conservar-identidad'),('revision','7'),('published_revision','6');
            INSERT INTO orders VALUES (42,'00123','Cliente real','Operador real','Terminado','Nota anterior',
                '2026-10-08T15:00:00+00:00','2026-10-08T16:00:00+00:00',NULL);
            INSERT INTO history VALUES (9,42,'2026-10-08T15:00:00+00:00','Registro',NULL,'{"ticket":"00123"}');
            PRAGMA user_version=1;
        """)
        conn.close()
        copy = Database(target)
        try:
            self.assertEqual(copy.meta("database_id"), "conservar-identidad")
            self.assertEqual(copy.meta("revision"), "7")
            self.assertEqual(copy.meta("published_revision"), "6")
            self.assertEqual(copy.get(42)["notes"], "Nota anterior")
            self.assertEqual(copy.history(42)[0]["id"], 9)
            self.assertEqual(copy.deleted(), [])
            backup = sqlite3.connect(copy.migration_backup)
            try:
                self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(backup.execute("SELECT ticket FROM orders WHERE id=42").fetchone()[0], "00123")
            finally:
                backup.close()
        finally:
            copy.close()
        copy = Database(target)
        self.assertIsNone(copy.migration_backup)
        copy.close()
        self.assertEqual(len(list(target.parent.glob("version1_respaldo_antes_1_1_*.db"))), 1)


class SyncTests(unittest.TestCase):
    def publisher(self, remote):
        p = Publisher("CristianAGR3/PRODUDASH1", "main", "test-not-a-real-token")
        self.sent = None
        def request(url, data=None):
            if data is None:
                return {"sha": "remote-sha", "encoding": "base64", "content": base64.b64encode(json.dumps(remote).encode()).decode()}
            self.sent = data
            return {"content": {"sha": "new-sha"}}
        p.request = request
        return p

    def snapshot(self):
        return {"meta": {"databaseId": "local-db", "revision": 3}, "orders": [{"id": "1"}]}

    def test_publish_payload(self):
        p = self.publisher({"meta": {"databaseId": "local-db", "revision": 2}, "orders": []})
        self.assertEqual(p.publish(self.snapshot()), "new-sha")
        self.assertEqual(self.sent["sha"], "remote-sha")
        self.assertEqual(json.loads(base64.b64decode(self.sent["content"])), self.snapshot())

    def test_other_database_requires_explicit_replace(self):
        p = self.publisher({"meta": {"databaseId": "other"}, "orders": []})
        with self.assertRaises(SyncError):
            p.publish(self.snapshot())
        self.assertIsNone(self.sent)
        self.assertEqual(p.publish(self.snapshot(), allow_replace=True), "new-sha")

    def test_newer_revision_rejected(self):
        p = self.publisher({"meta": {"databaseId": "local-db", "revision": 4}, "orders": []})
        with self.assertRaises(SyncError):
            p.publish(self.snapshot())

    def test_changed_sha_rejected(self):
        p = self.publisher({"meta": {"databaseId": "local-db", "revision": 2}, "orders": []})
        with self.assertRaises(SyncError):
            p.publish(self.snapshot(), last_sha="old-sha")

    def test_token_windows_encryption(self):
        encrypted = protect("sample-token")
        self.assertNotIn("sample-token", encrypted)
        self.assertEqual(protect(encrypted, decrypt=True), "sample-token")

    def test_permission_rejection_shows_repository_and_required_permission(self):
        exc = urllib.error.HTTPError("https://api.github.com", 403, "Forbidden",
                                     {"X-Accepted-GitHub-Permissions": "contents=write"},
                                     io.BytesIO(b'{"message":"Resource not accessible by personal access token"}'))
        self.addCleanup(exc.close)
        message = explain_http_error(exc, "test-token", "CristianAGR3/PRODUDASH1", "PUT")
        self.assertIn("Only select repositories", message)
        self.assertIn("PRODUDASH1", message)
        self.assertIn("contents=write", message)
        self.assertIn("HTTP 403", message)

    def test_rate_limit_is_distinguished_from_permissions(self):
        exc = urllib.error.HTTPError("https://api.github.com", 403, "Forbidden",
                                     {"X-RateLimit-Remaining": "0", "Retry-After": "60"},
                                     io.BytesIO(b'{"message":"API rate limit exceeded"}'))
        self.addCleanup(exc.close)
        message = explain_http_error(exc, "test-token", "CristianAGR3/PRODUDASH1", "GET")
        self.assertIn("60 segundos", message)
        self.assertNotIn("Only select repositories", message)

    def test_error_does_not_reveal_token(self):
        token = "github_pat_private_secret"
        body = json.dumps({"message": f"Rejected {token}"}).encode()
        exc = urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {}, io.BytesIO(body))
        self.addCleanup(exc.close)
        message = explain_http_error(exc, token, "CristianAGR3/PRODUDASH1", "PUT")
        self.assertNotIn(token, message)
        self.assertIn("credencial oculta", message)

    def test_request_reports_actual_github_error(self):
        body = io.BytesIO(b'{"message":"Resource not accessible by personal access token"}')
        exc = urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {}, body)
        publisher = Publisher("CristianAGR3/PRODUDASH1", "main", "sample-token")
        with patch("urllib.request.urlopen", side_effect=exc):
            with self.assertRaisesRegex(SyncError, "Detalle de GitHub"):
                publisher.request(publisher.url, data={"test": "payload"})
        self.assertTrue(body.closed)


if __name__ == "__main__":
    unittest.main()
