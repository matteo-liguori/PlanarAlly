import type { LocalId } from "../../../core/id";

export type TemplateShape = "square" | "circle" | "cone" | "hex";

export interface TemplateTargetRequest {
    shape: TemplateShape;
    size: number;
    focus: LocalId;
}

export interface TemplateTargetResult {
    tokenIds: LocalId[];
    originDistance: number;
}

type Handler = (
    request: TemplateTargetRequest,
    completion: (result: TemplateTargetResult) => void,
) => Promise<void>;

let handler: Handler | undefined;

export function registerTemplateTargetingHandler(value: Handler): void {
    handler = value;
}

export async function beginTemplateTargeting(
    request: TemplateTargetRequest,
    completion: (result: TemplateTargetResult) => void,
): Promise<void> {
    if (handler === undefined) throw new Error("The spell template tool is not ready.");
    await handler(request, completion);
}
