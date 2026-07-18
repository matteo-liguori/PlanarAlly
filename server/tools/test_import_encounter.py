"""Integration tests for the Veyra offline encounter importer."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
SOURCE_DB = REPO / "vtt_experiments/planarally/app/planarally.dist/data/planar.sqlite"
ENCOUNTER = REPO / "dm_notes/session_1/enemies/jsons/sylvara_two_wolves_ipad_test.json"
MAP = REPO / "combat_tracker/maps/Woodlands Whatchtower Camp - Woodlands Camp.df2vtt"
CONTROLLERS = REPO / "combat_tracker/config/planarally_users.json"


class ImportEncounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [path for path in (SOURCE_DB, ENCOUNTER, MAP, CONTROLLERS) if not path.exists()]
        if missing:
            raise unittest.SkipTest(f"Local PlanarAlly fixture is unavailable: {missing}")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database, self.assets = root / "planar.sqlite", root / "assets"
        with closing(sqlite3.connect(SOURCE_DB)) as source, closing(sqlite3.connect(self.database)) as destination:
            source.backup(destination)
        self.location = f"Importer Test {uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def command(self, controllers: Path = CONTROLLERS, location: str | None = None) -> list[str]:
        return [
            sys.executable, str(TOOLS / "import_encounter.py"), "--db", str(self.database),
            "--assets-dir", str(self.assets), "--repo", str(REPO), "--encounter", str(ENCOUNTER),
            "--map", str(MAP), "--user", "SupremeComander", "--campaign", "Veyra - Old Watchtower Test",
            "--location", location or self.location, "--controllers", str(controllers), "--unit-size", "2", "--unit", "m",
        ]

    def run_import(self) -> dict:
        result = subprocess.run(self.command(), cwd=TOOLS, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def imported_shapes(self, connection: sqlite3.Connection) -> list[sqlite3.Row]:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT shape.* FROM shape JOIN layer ON layer.id=shape.layer_id "
            "JOIN floor ON floor.id=layer.floor_id JOIN location ON location.id=floor.location_id "
            "WHERE location.name=? AND shape.options LIKE '%veyra_import%'", (self.location,),
        ).fetchall()

    def test_repeatable_import_preserves_unique_tokens_ownership_vision_and_obstacles(self) -> None:
        first = self.run_import()
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            first_shapes = self.imported_shapes(connection)
            first_ids = {row["uuid"] for row in first_shapes}
        second = self.run_import()
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            shapes = self.imported_shapes(connection)
            token_rows = [row for row in shapes if "veyra_definition_id" in row["options"]]
            wolf_rows = [row for row in token_rows if "bloomed_wolf" in row["options"]]
            player = next(row for row in token_rows if "imogen_circle_of_wildfire" in row["options"])
            ownership = connection.execute(
                "SELECT * FROM shape_owner WHERE shape_id=? AND edit_access=1 AND vision_access=1 AND movement_access=1",
                (player["uuid"],),
            ).fetchall()
            vision = connection.execute(
                "SELECT value FROM aura WHERE shape_id=? AND vision_source=1 AND active=1", (player["uuid"],),
            ).fetchall()
            obstacles = [row for row in shapes if row["vision_obstruction"] or row["movement_obstruction"]]
            doors = [row for row in shapes if row["is_door"]]
            wall_vertices = connection.execute(
                "SELECT polygon.vertices FROM polygon JOIN shape ON shape.uuid=polygon.shape_id "
                "JOIN layer ON layer.id=shape.layer_id JOIN floor ON floor.id=layer.floor_id "
                "JOIN location ON location.id=floor.location_id WHERE location.name=? AND shape.name='Imported wall'",
                (self.location,),
            ).fetchall()
            camera_rows = connection.execute(
                "SELECT pan_x,pan_y,zoom_display,active_layer_id FROM location_user_option "
                "JOIN location ON location.id=location_user_option.location_id WHERE location.name=?",
                (self.location,),
            ).fetchall()
            vision_options = connection.execute(
                "SELECT full_fow,fow_los,vision_min_range FROM location_options JOIN location "
                "ON location.options_id=location_options.id WHERE location.name=?", (self.location,),
            ).fetchone()
            floor_visible = connection.execute(
                "SELECT floor.player_visible FROM floor JOIN location ON location.id=floor.location_id "
                "WHERE location.name=?", (self.location,),
            ).fetchone()[0]
        self.assertEqual(first["tokens"], second["tokens"])
        self.assertEqual(len(shapes), len(first_shapes))
        self.assertFalse(first_ids & {row["uuid"] for row in shapes})
        self.assertEqual(len(token_rows), 3)
        self.assertEqual(len({row["uuid"] for row in wolf_rows}), 2)
        self.assertEqual(len({row["name"] for row in wolf_rows}), 2)
        self.assertEqual(len(ownership), 1)
        self.assertEqual(len(vision), 1)
        self.assertGreater(float(vision[0]["value"]), 0)
        self.assertGreater(len(obstacles), 0)
        self.assertGreater(len(doors), 0)
        self.assertTrue(all(max(abs(value) for point in json.loads(row["vertices"]) for value in point) < 1000
                            for row in wall_vertices))
        self.assertEqual(len(camera_rows), 2)
        self.assertTrue(all(row["zoom_display"] == 0.5 for row in camera_rows))
        self.assertTrue(all(row["pan_x"] != 0 and row["pan_y"] != 0 for row in camera_rows))
        self.assertEqual(tuple(vision_options), (1, 1, 0.0))
        self.assertEqual(floor_visible, 1)

    def test_missing_controller_rolls_back_without_creating_location(self) -> None:
        bad = Path(self.temp.name) / "bad-controllers.json"
        shutil.copyfile(CONTROLLERS, bad)
        value = json.loads(bad.read_text(encoding="utf-8"))
        value["characterUsers"]["imogen_circle_of_wildfire"] = "missing-user"
        bad.write_text(json.dumps(value), encoding="utf-8")
        location = f"Rollback Test {uuid.uuid4().hex[:8]}"
        result = subprocess.run(self.command(bad, location), cwd=TOOLS, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM location WHERE name=?", (location,)).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
