import { coreStore } from "../../../store/core";
import type { IShape } from "../../interfaces/shape";
import { polygon2path } from "../../rendering/basic";
import { gameState } from "../../systems/game/state";
import { locationSettingsState } from "../../systems/settings/location/state";

type Polygon = [number, number][];
type ExploredState = { polygons: Polygon[]; lastCenters: Record<string, [number, number]> };
type VisionShape = IShape & { _visionPolygon?: Polygon };

const PREFIX = "veyra-explored-fog:v1:";
const MAX_POLYGONS = 240;
const MIN_CAPTURE_DISTANCE = 10;

function storageKey(floor: number): string {
    return `${PREFIX}${gameState.raw.roomCreator}/${gameState.raw.roomName}/${coreStore.state.username}/${locationSettingsState.raw.activeLocation}/${floor}`;
}

function load(floor: number): ExploredState {
    try {
        const parsed = JSON.parse(localStorage.getItem(storageKey(floor)) ?? "null") as ExploredState | null;
        if (parsed && Array.isArray(parsed.polygons) && parsed.lastCenters) return parsed;
    } catch (error) {
        console.warn("Could not read explored fog history; starting a fresh history.", error);
    }
    return { polygons: [], lastCenters: {} };
}

function save(floor: number, state: ExploredState): void {
    try {
        localStorage.setItem(storageKey(floor), JSON.stringify(state));
    } catch (error) {
        console.warn("Could not persist explored fog history.", error);
    }
}

export function rememberVisibleAreas(floor: number, shapes: IShape[]): Polygon[] {
    if (gameState.raw.isDm) return [];
    const state = load(floor);
    let changed = false;
    for (const shape of shapes) {
        if (shape.floorId !== floor) continue;
        void shape.visionPolygon;
        const polygon = (shape as VisionShape)._visionPolygon;
        if (!polygon || polygon.length < 3) continue;
        const previous = state.lastCenters[String(shape.id)];
        const moved = previous === undefined || Math.hypot(shape.center.x - previous[0], shape.center.y - previous[1]) >= MIN_CAPTURE_DISTANCE;
        if (!moved) continue;
        state.polygons.push(polygon.map(([x, y]) => [x, y]));
        state.lastCenters[String(shape.id)] = [shape.center.x, shape.center.y];
        changed = true;
    }
    if (state.polygons.length > MAX_POLYGONS) {
        state.polygons.splice(0, state.polygons.length - MAX_POLYGONS);
        changed = true;
    }
    if (changed) save(floor, state);
    return state.polygons;
}

export function drawExploredAreas(context: CanvasRenderingContext2D, polygons: Polygon[]): void {
    if (polygons.length === 0) return;
    context.save();
    context.globalCompositeOperation = "source-over";
    context.fillStyle = "rgba(0, 0, 0, 0.45)";
    for (const polygon of polygons) context.fill(polygon2path(polygon));
    context.restore();
}

export function clearExploredFog(): void {
    const prefix = `${PREFIX}${gameState.raw.roomCreator}/${gameState.raw.roomName}/${coreStore.state.username}/`;
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
        const key = localStorage.key(index);
        if (key?.startsWith(prefix)) localStorage.removeItem(key);
    }
}

(window as Window & { veyraResetExploredFog?: () => void }).veyraResetExploredFog = clearExploredFog;
