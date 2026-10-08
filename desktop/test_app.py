import base64
import csv
import json
import tempfile
import unittest
from pathlib import Path
from core import Database, STATUSES, export_csv, ranking, summary
from sync import Publisher, SyncError, protect


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


if __name__ == "__main__":
    unittest.main()
