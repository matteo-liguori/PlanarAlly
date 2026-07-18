export interface LongPressPoint {
    clientX: number;
    clientY: number;
    target: EventTarget;
}

export class LongPressController {
    private timer: ReturnType<typeof setTimeout> | undefined;
    private origin: LongPressPoint | undefined;

    constructor(
        private readonly activate: (point: LongPressPoint) => void,
        private readonly delayMs = 550,
        private readonly tolerancePx = 10,
    ) {}

    start(event: TouchEvent): void {
        this.cancel();
        if (event.touches.length !== 1 || event.target === null) return;
        const touch = event.touches[0];
        if (touch === undefined) return;
        this.origin = { clientX: touch.clientX, clientY: touch.clientY, target: event.target };
        this.timer = setTimeout(() => {
            const point = this.origin;
            this.timer = undefined;
            this.origin = undefined;
            if (point !== undefined) this.activate(point);
        }, this.delayMs);
    }

    move(event: TouchEvent): void {
        if (this.origin === undefined) return;
        if (event.touches.length !== 1) return this.cancel();
        const touch = event.touches[0];
        if (touch === undefined) return this.cancel();
        const distance = Math.hypot(touch.clientX - this.origin.clientX, touch.clientY - this.origin.clientY);
        if (distance > this.tolerancePx) this.cancel();
    }

    cancel(): void {
        if (this.timer !== undefined) clearTimeout(this.timer);
        this.timer = undefined;
        this.origin = undefined;
    }
}
