"""Ports count as down only when the bound repo needs them."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fps_services


class ExpectedPortsTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        env = {k: v for k, v in os.environ.items() if k != "FPS_PORTS"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_a_repo_that_needs_no_services_expects_no_ports(self):
        self.write("README.md", "# just scripts\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [])

    def test_no_bound_repo_expects_no_ports(self):
        self.assertEqual(fps_services.expected_ports(None), [])

    def test_compose_published_ports_are_expected_under_their_service_names(self):
        self.write("docker-compose.yml", """services:
  db:
    image: postgres:16
    ports:
      - "5432:5432"
  cache:
    image: redis:7
    ports:
      - 127.0.0.1:6379:6379
  worker:
    image: app
""")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("5432", "db"), ("6379", "cache")])

    def test_compose_yaml_name_is_read_too(self):
        self.write("compose.yaml", "services:\n  mail:\n    ports:\n      - '1025:1025'\n      - \"8025:8025/tcp\"\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("1025", "mail"), ("8025", "mail")])

    def test_a_postgres_database_yml_expects_postgres(self):
        self.write("config/database.yml", "default: &default\n  adapter: postgresql\n  host: localhost\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("5432", "postgres")])

    def test_database_yml_port_wins_over_the_default(self):
        self.write("config/database.yml", "development:\n  adapter: postgresql\n  port: 54329\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("54329", "postgres")])

    def test_sqlite_needs_no_port(self):
        self.write("config/database.yml", "development:\n  adapter: sqlite3\n  database: storage/development.sqlite3\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [])

    def test_a_port_named_twice_is_expected_once(self):
        self.write("docker-compose.yml", "services:\n  postgres:\n    ports:\n      - \"5432:5432\"\n")
        self.write("config/database.yml", "development:\n  adapter: postgresql\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("5432", "postgres")])

    def test_a_local_database_url_in_an_env_file_expects_its_port(self):
        self.write(".env.example", "DATABASE_URL=postgres://localhost:54329/foodi_dex\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("54329", "postgres")])

    def test_a_local_redis_url_expects_redis(self):
        self.write(".env", "REDIS_URL=redis://127.0.0.1:6379/0\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("6379", "redis")])

    def test_a_url_without_a_port_expects_the_default(self):
        self.write(".env.local", "DATABASE_URL=postgresql://app:secret@localhost/app_dev\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [("5432", "postgres")])

    def test_a_hosted_database_is_not_a_local_port(self):
        self.write(".env.local", "DATABASE_URL=postgres://user:pw@db.example.supabase.co:5432/postgres\n")
        self.assertEqual(fps_services.expected_ports(str(self.repo)), [])

    def test_fps_ports_still_overrides(self):
        self.write("config/database.yml", "development:\n  adapter: postgresql\n")
        with mock.patch.dict(os.environ, {"FPS_PORTS": "3000:web"}):
            self.assertEqual(fps_services.expected_ports(str(self.repo)), [("3000", "web")])

    def test_an_empty_fps_ports_expects_nothing(self):
        self.write("config/database.yml", "development:\n  adapter: postgresql\n")
        with mock.patch.dict(os.environ, {"FPS_PORTS": ""}):
            self.assertEqual(fps_services.expected_ports(str(self.repo)), [])

    def test_problems_report_no_port_errors_for_a_repo_that_needs_none(self):
        with mock.patch.object(fps_services, "listening", return_value=False):
            self.assertEqual(fps_services._port_problems(str(self.repo)), [])

    def test_problems_report_a_needed_port_that_is_down(self):
        self.write("config/database.yml", "development:\n  adapter: postgresql\n")
        with mock.patch.object(fps_services, "listening", return_value=False):
            self.assertEqual(fps_services._port_problems(str(self.repo)),
                             [("error", "postgres is not listening on 5432")])


if __name__ == "__main__":
    unittest.main()
