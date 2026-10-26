from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.database import Database
from app.refresh import refresh


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_sources_are_skipped_and_backup_is_created(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            database = Database(path)
            database.initialize()
            with database.connect() as db:
                db.execute("UPDATE sources SET enabled=0 WHERE name='grasser'")
            synchronize = AsyncMock(return_value=SimpleNamespace(errors=0, complete=True))
            with patch("app.refresh.load_settings", return_value=SimpleNamespace(database_path=path)), \
                 patch("app.refresh.available_providers", return_value=("vikisews", "grasser")), \
                 patch("app.refresh.create_provider", side_effect=lambda name: name), \
                 patch("app.refresh.CatalogService", return_value=SimpleNamespace(synchronize=synchronize)):
                self.assertEqual(await refresh(), 0)
            synchronize.assert_awaited_once_with("vikisews")
            backup = next((Path(directory) / "backups").glob("*.sqlite3"))
            with Database(backup).connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 5)

    async def test_source_failure_does_not_stop_other_sources(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            synchronize = AsyncMock(side_effect=[TimeoutError(), SimpleNamespace(errors=0, complete=True)])
            with patch("app.refresh.load_settings", return_value=SimpleNamespace(database_path=path)), \
                 patch("app.refresh.available_providers", return_value=("vikisews", "grasser")), \
                 patch("app.refresh.create_provider", side_effect=lambda name: name), \
                 patch("app.refresh.CatalogService", return_value=SimpleNamespace(synchronize=synchronize)):
                self.assertEqual(await refresh(), 1)
            self.assertEqual([call.args[0] for call in synchronize.await_args_list], ["vikisews", "grasser"])
