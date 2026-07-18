import { afterEach, describe, expect, test, vi } from "vitest";

import { LongPressController } from "./longPress";

function event(points: [number, number][]): TouchEvent {
    return {
        target: document.createElement("canvas"),
        touches: points.map(([clientX, clientY]) => ({ clientX, clientY })),
    } as unknown as TouchEvent;
}

describe("LongPressController", () => {
    afterEach(() => vi.useRealTimers());

    test("activates after 550 ms", () => {
        vi.useFakeTimers();
        const activate = vi.fn();
        const controller = new LongPressController(activate);
        controller.start(event([[20, 30]]));
        vi.advanceTimersByTime(549);
        expect(activate).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(activate).toHaveBeenCalledOnce();
    });

    test("cancels on drag, pinch, and touch end", () => {
        vi.useFakeTimers();
        const activate = vi.fn();
        const controller = new LongPressController(activate);
        controller.start(event([[20, 30]]));
        controller.move(event([[40, 30]]));
        vi.runAllTimers();
        controller.start(event([[20, 30]]));
        controller.move(event([[20, 30], [30, 30]]));
        vi.runAllTimers();
        controller.start(event([[20, 30]]));
        controller.cancel();
        vi.runAllTimers();
        expect(activate).not.toHaveBeenCalled();
    });
});
