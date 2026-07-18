"""Controller and native-vision helpers for the offline encounter importer."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


def one(cursor: sqlite3.Cursor, query: str, values: tuple, label: str) -> sqlite3.Row:
    rows = cursor.execute(query, values).fetchall()
    if len(rows) != 1:
        raise ValueError(f"Expected one {label}, found {len(rows)}")
    return rows[0]


def load_mapping(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != 1 or not isinstance(value.get("characterUsers"), dict):
        raise ValueError("Controller config must use schemaVersion 1 and characterUsers.")
    return {str(key): str(user) for key, user in value["characterUsers"].items() if user}


def validate_mapping(cursor: sqlite3.Cursor, character_ids: list[str], mapping: dict[str, str]) -> dict[str, int]:
    users = {row["name"]: int(row["id"]) for row in cursor.execute("SELECT id,name FROM user")}
    failures = []
    for character_id in character_ids:
        username = mapping.get(character_id)
        if not username:
            failures.append(f"No PlanarAlly username is mapped to character {character_id}.")
        elif username not in users:
            failures.append(f"PlanarAlly user {username} mapped to {character_id} does not exist.")
    if failures:
        raise ValueError(" ".join(failures))
    return users


def ensure_player_room(cursor: sqlite3.Cursor, user_id: int, room_id: int, location_id: int) -> None:
    row = cursor.execute(
        "SELECT id FROM player_room WHERE player_id=? AND room_id=?", (user_id, room_id)
    ).fetchone()
    if row:
        cursor.execute("UPDATE player_room SET active_location_id=? WHERE id=?", (location_id, row["id"]))
    else:
        cursor.execute(
            "INSERT INTO player_room (role,player_id,room_id,active_location_id) VALUES (0,?,?,?)",
            (user_id, room_id, location_id),
        )


def ensure_location_user_option(cursor: sqlite3.Cursor, user_id: int, location_id: int, layer_id: int) -> None:
    row = cursor.execute(
        "SELECT id FROM location_user_option WHERE location_id=? AND user_id=?", (location_id, user_id)
    ).fetchone()
    if row:
        cursor.execute("UPDATE location_user_option SET active_layer_id=? WHERE id=?", (layer_id, row["id"]))
    else:
        cursor.execute(
            "INSERT INTO location_user_option (location_id,user_id,pan_x,pan_y,zoom_display,active_layer_id) "
            "VALUES (?,?,0,0,0,?)", (location_id, user_id, layer_id),
        )


def ensure_participant_locations(
    cursor: sqlite3.Cursor, user_ids: set[int], location_id: int, layer_id: int,
) -> None:
    for user_id in user_ids:
        ensure_location_user_option(cursor, user_id, location_id, layer_id)


def vision_range(character: dict) -> int:
    for feature in character.get("features", []):
        if isinstance(feature, list) and feature and str(feature[0]).lower() == "darkvision":
            match = re.search(r"\d+(?:\.\d+)?", str(feature[1] if len(feature) > 1 else ""))
            if match:
                return round(float(match.group()))
    return 10


def grant_token_control(cursor: sqlite3.Cursor, shape_id: str, user_id: int, sight_metres: int) -> None:
    cursor.execute(
        "INSERT INTO shape_owner (shape_id,user_id,edit_access,vision_access,movement_access) VALUES (?,?,1,1,1)",
        (shape_id, user_id),
    )
    cursor.execute(
        "INSERT INTO aura (uuid,shape_id,vision_source,visible,name,value,dim,colour,active,border_colour,angle,direction) "
        "VALUES (?,?,1,0,'Character vision',?,0,'rgba(0,0,0,0)',1,'rgba(0,0,0,0)',360,0)",
        (__import__("uuid").uuid4().hex, shape_id, sight_metres),
    )
