import type { LocalId } from "../../../core/id";

export interface MovementCandidate {
    shape: LocalId;
    from: [number, number];
    to: [number, number];
}

export type MovementGuard = (candidate: MovementCandidate) => boolean | Promise<boolean>;

const guards: MovementGuard[] = [];

export function registerMovementGuard(guard: MovementGuard): void {
    guards.push(guard);
}

export async function approveMovements(candidates: MovementCandidate[]): Promise<boolean> {
    for (const candidate of candidates) {
        for (const guard of guards) {
            if (!(await guard(candidate))) return false;
        }
    }
    return true;
}
