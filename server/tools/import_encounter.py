"""Offline, idempotent PlanarAlly encounter importer for local campaign data."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mmap
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

from import_controllers import ensure_participant_locations, ensure_player_room, grant_token_control, load_mapping, one, validate_mapping, vision_range
IMPORT_TAG = "veyra_import"
FONT = "bold 28px sans-serif"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--assets-dir", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--encounter", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--controllers", required=True, type=Path)
    parser.add_argument("--unit-size", type=float, default=2.0)
    parser.add_argument("--unit", default="m")
    return parser.parse_args()


def load_map_metadata(path: Path) -> tuple[dict, int, int]:
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        key = data.rfind(b'"image"')
        if key < 0:
            raise ValueError(f"Map has no embedded image: {path}")
        colon = data.find(b":", key + 7)
        image_start = data.find(b'"', colon + 1) + 1
        image_end = data.find(b'"', image_start)
        if colon < 0 or image_start <= 0 or image_end < 0:
            raise ValueError(f"Map image field is malformed: {path}")
        metadata = json.loads(data[:image_start] + b'"' + data[image_end + 1 :])
        return metadata, image_start, image_end


def extract_embedded_image(path: Path, start: int, end: int, assets_dir: Path) -> tuple[str, Path]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1()
    descriptor, temporary_name = tempfile.mkstemp(prefix="pa-map-", dir=assets_dir)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with path.open("rb") as source, temporary.open("wb") as target:
            source.seek(start)
            remaining = end - start
            carry = b""
            while remaining:
                block = source.read(min(4 * 1024 * 1024, remaining))
                remaining -= len(block)
                block = carry + block
                usable = len(block) - (len(block) % 4)
                decoded = base64.b64decode(block[:usable], validate=True)
                target.write(decoded)
                digest.update(decoded)
                carry = block[usable:]
            if carry:
                decoded = base64.b64decode(carry, validate=True)
                target.write(decoded)
                digest.update(decoded)
        file_hash = digest.hexdigest()
        destination = assets_dir / file_hash[:2] / file_hash[2:4] / file_hash
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            temporary.unlink()
        else:
            os.replace(temporary, destination)
        return file_hash, destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def copy_asset(path: Path, assets_dir: Path) -> tuple[str, Path]:
    digest = hashlib.sha1()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    file_hash = digest.hexdigest()
    destination = assets_dir / file_hash[:2] / file_hash[2:4] / file_hash
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(path, destination)
    return file_hash, destination


def find_character(repo: Path, character_id: str) -> dict:
    matches = list((repo / "characters").glob(f"*/{character_id}.json"))
    if len(matches) != 1:
        raise ValueError(f"Expected one character JSON for {character_id}, found {len(matches)}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


def load_combatants(repo: Path, encounter: dict, mapping: dict[str, str]) -> list[dict]:
    combatants = []
    colours = ["#3974d8", "#8b5bd6", "#2c9b67"]
    for index, character_id in enumerate(encounter["players"]):
        data = find_character(repo, character_id)
        name = data["character_name"]
        combatants.append(
            {
                "name": name,
                "definition_id": character_id,
                "label": "".join(part[0] for part in name.split()[:2]).upper(),
                "hp": int(data["combat"]["max_hp"]),
                "colour": colours[index % len(colours)],
                "player": True,
                "asset": None,
                "controller": mapping.get(character_id),
                "vision": vision_range(data),
            }
        )
    enemy_dir = repo / "dm_notes" / "session_1" / "enemies" / "jsons" / "enemy_types"
    token_dir = repo / "dm_notes" / "session_1" / "enemy_tokens" / "previews"
    for group in encounter["enemies"]:
        data = json.loads((enemy_dir / f"{group['type']}.json").read_text(encoding="utf-8"))
        token = token_dir / f"{group['type']}.png"
        for number in range(1, int(group["count"]) + 1):
            suffix = f" {number}" if int(group["count"]) > 1 else ""
            combatants.append(
                {
                    "name": f"{data['name']}{suffix}",
                    "definition_id": group["type"],
                    "label": "".join(part[0] for part in data["name"].split()[:2]).upper(),
                    "hp": int(data["hp"]),
                    "colour": "#a43d46",
                    "player": False,
                    "asset": token if token.exists() else None, "controller": None, "vision": 0,
                }
            )
    return combatants


def shape_values(layer: int, type_: str, x: float, y: float, name: str, index: int, **overrides) -> dict:
    values = {
        "uuid": str(uuid.uuid4()), "layer_id": layer, "type_": type_, "x": x, "y": y, "name": name,
        "name_visible": 1, "fill_colour": "#444", "stroke_colour": "#fff", "vision_obstruction": 0,
        "movement_obstruction": 0, "draw_operator": "source-over", "index": index,
        "options": json.dumps([[IMPORT_TAG, True]]), "badge": 1, "show_badge": 0,
        "default_edit_access": 0, "default_vision_access": 0, "is_invisible": 0, "is_defeated": 0,
        "default_movement_access": 0, "is_locked": 0, "angle": 0, "stroke_width": 2,
        "asset_id": None, "group_id": None, "ignore_zoom_size": 0, "is_door": 0,
        "is_teleport_zone": 0, "character_id": None, "odd_hex_orientation": 0, "size_x": 1,
        "size_y": 1, "show_cells": 0, "cell_fill_colour": None, "cell_stroke_colour": None,
        "cell_stroke_width": None,
    }
    values.update(overrides)
    return values


def insert_shape(cursor: sqlite3.Cursor, values: dict) -> str:
    columns = ", ".join(f'"{name}"' for name in values)
    placeholders = ", ".join("?" for _ in values)
    cursor.execute(f"INSERT INTO shape ({columns}) VALUES ({placeholders})", tuple(values.values()))
    return values["uuid"]


def ensure_asset(cursor: sqlite3.Cursor, owner: int, parent: int, name: str, file_hash: str) -> int:
    row = cursor.execute(
        "SELECT id FROM asset WHERE owner_id=? AND parent_id=? AND name=?", (owner, parent, name)
    ).fetchone()
    if row:
        cursor.execute("UPDATE asset SET file_hash=? WHERE id=?", (file_hash, row["id"]))
        return int(row["id"])
    cursor.execute(
        "INSERT INTO asset (owner_id, parent_id, name, file_hash) VALUES (?, ?, ?, ?)",
        (owner, parent, name, file_hash),
    )
    return int(cursor.lastrowid)


def create_options(cursor: sqlite3.Cursor, unit_size: float, unit: str) -> int:
    cursor.execute(
        "INSERT INTO location_options (unit_size,unit_size_unit,use_grid,full_fow,fow_opacity,fow_los,"
        "vision_mode,vision_min_range,vision_max_range,spawn_locations,move_player_on_token_change,grid_type,"
        "air_map_background,ground_map_background,underground_map_background,limit_movement_during_initiative,"
        "drop_ratio) VALUES (?,?,1,0,0.3,0,'triangle',500,1000,'[]',1,'SQUARE','none','none','none',0,1)",
        (unit_size, unit),
    )
    return int(cursor.lastrowid)


def create_floor(cursor: sqlite3.Cursor, location_id: int) -> None:
    cursor.execute(
        "INSERT INTO floor (location_id,\"index\",name,player_visible,type_,background_color) "
        "VALUES (?,0,'ground',0,1,NULL)",
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


def ensure_campaign(cursor: sqlite3.Cursor, user_id: int, name: str, unit_size: float, unit: str) -> sqlite3.Row:
    rows = cursor.execute("SELECT * FROM room WHERE creator_id=? AND name=?", (user_id, name)).fetchall()
    if len(rows) > 1:
        raise ValueError(f"Expected at most one campaign named {name}, found {len(rows)}")
    if rows:
        return rows[0]
    options_id = create_options(cursor, unit_size, unit)
    cursor.execute(
        "INSERT INTO room (name,creator_id,invitation_code,is_locked,default_options_id,logo_id,enable_chat,enable_dice) "
        "VALUES (?,?,?,0,?,NULL,1,1)",
        (name, user_id, str(uuid.uuid4()), options_id),
    )
    room_id = int(cursor.lastrowid)
    cursor.execute("INSERT INTO location (room_id,name,options_id,\"index\",archived) VALUES (?,'start',NULL,1,0)",
                   (room_id,))
    start_id = int(cursor.lastrowid)
    create_floor(cursor, start_id)
    cursor.execute(
        "INSERT INTO player_room (role,player_id,room_id,active_location_id,user_options_id,notes,last_played) "
        "VALUES (1,?,?,?,NULL,NULL,NULL)",
        (user_id, room_id, start_id),
    )
    return one(cursor, "SELECT * FROM room WHERE id=?", (room_id,), "campaign")


def configure_location(cursor: sqlite3.Cursor, room_id: int, name: str, unit_size: float, unit: str) -> sqlite3.Row:
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
            "UPDATE location_options SET unit_size=?,unit_size_unit=?,use_grid=1,grid_type='SQUARE' WHERE id=?",
            (unit_size, unit, options_id),
        )
    return one(cursor, "SELECT * FROM location WHERE id=?", (location["id"],), "location")


def import_shapes(cursor: sqlite3.Cursor, metadata: dict, layers: dict[str, int], map_asset: int, map_hash: str,
                  combatants: list[dict], token_assets: dict[str, tuple[int, str]], users: dict[str, int]) -> tuple[int, int]:
    resolution = metadata["resolution"]
    width = float(resolution["map_size"]["x"]) * 50
    height = float(resolution["map_size"]["y"]) * 50
    map_shape = shape_values(layers["map"], "assetrect", 0, 0, "Woodlands Watchtower Camp", 0,
                             name_visible=0, is_locked=1, asset_id=map_asset)
    map_uuid = insert_shape(cursor, map_shape)
    src = f"/static/assets/{map_hash[:2]}/{map_hash[2:4]}/{map_hash}"
    cursor.execute("INSERT INTO asset_rect (shape_id,width,height,src) VALUES (?,?,?,?)",
                   (map_uuid, width, height, src))
    obstacle_count = 0
    for points, closed, door in [
        *((line, True, False) for line in metadata.get("line_of_sight", [])),
        *((portal.get("bounds", []), bool(portal.get("closed")), True) for portal in metadata.get("portals", [])),
    ]:
        if len(points) < 2:
            continue
        absolute = [[float(point["x"]) * 50, float(point["y"]) * 50] for point in points]
        wall = shape_values(layers["fow"], "polygon", absolute[0][0], absolute[0][1], "Imported wall",
                            obstacle_count, name_visible=0, stroke_colour="#df4242" if closed else "#3388dd",
                            vision_obstruction=2 if closed else 0, movement_obstruction=1 if closed else 0,
                            is_door=1 if door else 0)
        wall_uuid = insert_shape(cursor, wall)
        cursor.execute("INSERT INTO polygon (shape_id,vertices,line_width,open_polygon) VALUES (?,?,2,1)",
                       (wall_uuid, json.dumps(absolute[1:])))
        obstacle_count += 1
    positions = [(0.12, 0.80), (0.16, 0.80), (0.20, 0.80), (0.35, 0.60), (0.42, 0.57),
                 (0.50, 0.55), (0.58, 0.58), (0.39, 0.42), (0.48, 0.38), (0.57, 0.43),
                 (0.46, 0.25), (0.55, 0.27), (0.50, 0.18)]
    for index, combatant in enumerate(combatants):
        px, py = positions[index] if index < len(positions) else (0.25 + index * 0.03, 0.70)
        token_asset = token_assets.get(combatant["name"])
        type_ = "assetrect" if token_asset else "circulartoken"
        token = shape_values(layers["tokens"], type_, width * px, height * py, combatant["name"], index,
                             fill_colour=combatant["colour"], default_edit_access=0,
                             default_vision_access=0, default_movement_access=0,
                             asset_id=token_asset[0] if token_asset else None,
                             options=json.dumps([[IMPORT_TAG, True],
                                                 ["veyra_definition_id", combatant["definition_id"]],
                                                 ["veyra_combatant_name", combatant["name"]]]))
        token_uuid = insert_shape(cursor, token)
        if combatant["controller"]:
            grant_token_control(cursor, token_uuid, users[combatant["controller"]], combatant["vision"])
        if token_asset:
            token_hash = token_asset[1]
            token_src = f"/static/assets/{token_hash[:2]}/{token_hash[2:4]}/{token_hash}"
            cursor.execute("INSERT INTO asset_rect (shape_id,width,height,src) VALUES (?,50,50,?)",
                           (token_uuid, token_src))
        else:
            cursor.execute("INSERT INTO circular_token (shape_id,radius,viewing_angle,text,font) VALUES (?,25,NULL,?,?)",
                           (token_uuid, combatant["label"], FONT))
        cursor.execute(
            "INSERT INTO tracker (uuid,shape_id,visible,name,value,maxvalue,draw,primary_color,secondary_color) "
            "VALUES (?,?,1,'HP',?,?,1,'#38b000','#c1121f')",
            (str(uuid.uuid4()), token_uuid, combatant["hp"], combatant["hp"]),
        )
    return obstacle_count, len(combatants)


def main() -> None:
    args = parse_args()
    for path in (args.db, args.repo, args.encounter, args.map):
        if not path.exists():
            raise FileNotFoundError(path)
    metadata, image_start, image_end = load_map_metadata(args.map)
    map_hash, _ = extract_embedded_image(args.map, image_start, image_end, args.assets_dir)
    encounter = json.loads(args.encounter.read_text(encoding="utf-8"))
    mapping = load_mapping(args.controllers)
    combatants = load_combatants(args.repo, encounter, mapping)
    connection = sqlite3.connect(args.db, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            cursor = connection.cursor()
            user = one(cursor, "SELECT * FROM user WHERE name=?", (args.user,), "user")
            users = validate_mapping(cursor, encounter["players"], mapping)
            room = ensure_campaign(cursor, user["id"], args.campaign, args.unit_size, args.unit)
            location = configure_location(cursor, room["id"], args.location, args.unit_size, args.unit)
            for character_id in encounter["players"]:
                ensure_player_room(cursor, users[mapping[character_id]], room["id"], location["id"])
            floors = cursor.execute("SELECT id FROM floor WHERE location_id=?", (location["id"],)).fetchall()
            if len(floors) != 1:
                raise ValueError(f"Expected one floor in {args.location}, found {len(floors)}")
            layers = {row["name"]: row["id"] for row in cursor.execute(
                "SELECT id,name FROM layer WHERE floor_id=?", (floors[0]["id"],)
            )}
            for required in ("map", "tokens", "fow"):
                if required not in layers:
                    raise ValueError(f"Location is missing required layer: {required}")
            participants = {int(user["id"]), *(users[mapping[item]] for item in encounter["players"])}
            ensure_participant_locations(cursor, participants, location["id"], layers["tokens"])
            layer_ids = tuple(layers.values())
            placeholders = ",".join("?" for _ in layer_ids)
            cursor.execute(
                f"DELETE FROM shape WHERE layer_id IN ({placeholders}) AND options LIKE ?",
                (*layer_ids, f'%"{IMPORT_TAG}"%'),
            )
            root = cursor.execute(
                "SELECT id FROM asset WHERE owner_id=? AND parent_id IS NULL AND name='/'", (user["id"],)
            ).fetchone()
            if root is None:
                cursor.execute("INSERT INTO asset (owner_id,parent_id,name,file_hash) VALUES (?,NULL,'/',NULL)",
                               (user["id"],))
                root_id = int(cursor.lastrowid)
            else:
                root_id = int(root["id"])
            map_asset = ensure_asset(cursor, user["id"], root_id, "Veyra import - Watchtower map", map_hash)
            token_assets = {}
            for combatant in combatants:
                if combatant["asset"] is None:
                    continue
                token_hash, _ = copy_asset(combatant["asset"], args.assets_dir)
                asset_id = ensure_asset(cursor, user["id"], root_id,
                                        f"Veyra import - {combatant['name']}", token_hash)
                token_assets[combatant["name"]] = (asset_id, token_hash)
            obstacles, tokens = import_shapes(cursor, metadata, layers, map_asset, map_hash,
                                              combatants, token_assets, users)
            cursor.execute("UPDATE player_room SET active_location_id=? WHERE room_id=? AND role=1",
                           (location["id"], room["id"]))
        print(json.dumps({"campaign": args.campaign, "location": args.location, "tokens": tokens,
                          "obstacles": obstacles, "map_hash": map_hash, "unit": f"{args.unit_size:g} {args.unit}"}))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
