import { describe, expect, test, vi } from "vitest";

import { approveMovements, registerMovementGuard } from "./movementGuards";

describe("movement guards", () => {
    test("rejects a move when a registered guard refuses it", async () => {
        const guard = vi.fn().mockResolvedValue(false);
        registerMovementGuard(guard);
        const accepted = await approveMovements([{shape: "shape" as never, from: [0, 0], to: [50, 0]}]);
        expect(accepted).toBe(false);
        expect(guard).toHaveBeenCalledOnce();
    });
});
