"""Location and floor setup used by the offline encounter importer."""

from __future__ import annotations

import sqlite3

from import_controllers import one


def create_options(cursor: sqlite3.Cursor, unit_size: float, unit: str) -> int:
    cursor.execute(
        "INSERT INTO location_options (unit_size,unit_size_unit,use_grid,full_fow,fow_opacity,fow_los,"
        "vision_mode,vision_min_range,vision_max_range,spawn_locations,move_player_on_token_change,grid_type,"
        "air_map_background,ground_map_background,underground_map_background,limit_movement_during_initiative,"
        "drop_ratio) VALUES (?,?,1,1,0.3,1,'triangle',0,1000,'[]',1,'SQUARE','none','none','none',0,1)",
        (unit_size, unit),
    )
    return int(cursor.lastrowid)


def create_floor(cursor: sqlite3.Cursor, location_id: int) -> None:
    cursor.execute(
        "INSERT INTO floor (location_id,\"index\",name,player_visible,type_,background_color) "
        "VALUES (?,0,'ground',1,1,NULL)",
        (location_id,),
    )
    floor_id = int(cursor.lastrowid)
    layers = [
        ("map", "normal", 1, 0, 1), ("grid", "grid", 1, 0, 0),
        ("tokens", "normal", 1, 1, 1), ("dm", "normal", 0, 0, 1),
        ("fow", "fow", 1, 0, 1), ("fow-players", "fow-players", 1, 0, 0),
        ("draw", "normal", 1, 1, 0),
    ]
    cursor.executemany(
        "INSERT INTO layer (floor_id,name,type_,player_visible,player_editable,selectable,\"index\") "
        "VALUES (?,?,?,?,?,?,?)",
        [(floor_id, name, type_, visible, editable, selectable, index)
         for index, (name, type_, visible, editable, selectable) in enumerate(layers)],
    )


def configure_location(cursor: sqlite3.Cursor, room_id: int, name: str,
                       unit_size: float, unit: str) -> sqlite3.Row:
    rows = cursor.execute("SELECT * FROM location WHERE room_id=? AND name=?", (room_id, name)).fetchall()
    if len(rows) > 1:
        raise ValueError(f"Expected at most one location named {name}, found {len(rows)}")
    if rows:
        location = rows[0]
    else:
        next_index = int(cursor.execute(
            "SELECT COALESCE(MAX(\"index\"),0)+1 FROM location WHERE room_id=?", (room_id,)
        ).fetchone()[0])
        cursor.execute(
            "INSERT INTO location (room_id,name,options_id,\"index\",archived) VALUES (?,?,NULL,?,0)",
            (room_id, name, next_index),
        )
        location = one(cursor, "SELECT * FROM location WHERE id=?", (cursor.lastrowid,), "location")
        create_floor(cursor, int(location["id"]))
    options_id = location["options_id"]
    if options_id is None:
        options_id = create_options(cursor, unit_size, unit)
        cursor.execute("UPDATE location SET options_id=? WHERE id=?", (options_id, location["id"]))
    else:
        cursor.execute(
            "UPDATE location_options SET unit_size=?,unit_size_unit=?,use_grid=1,full_fow=1,fow_los=1,"
            "vision_min_range=0,grid_type='SQUARE' WHERE id=?",
            (unit_size, unit, options_id),
        )
    return one(cursor, "SELECT * FROM location WHERE id=?", (location["id"],), "location")
