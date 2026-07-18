import type { ApiModMeta } from "../apiTypes";
import type { Section } from "../core/components/contextMenu/types";
import { type GlobalId, type LocalId } from "../core/id";
import type { Sync } from "../core/models/types";
import type { SYSTEMS_STATE } from "../core/systems";
import type { System } from "../core/systems/models";
import type { IShape } from "../game/interfaces/shape";
import type { Tracker } from "../game/systems/trackers/models";
import type { PanelTab } from "../game/systems/ui/types";
import type { MovementGuard } from "../game/systems/ui/movementGuards";
import type { TemplateTargetRequest, TemplateTargetResult } from "../game/systems/ui/templateTargeting";

import type { ModDataBlockFunctions } from "./db";

export interface Mod {
    events?: {
        init?: (meta: ApiModMeta) => Promise<void>;
        initGame?: (data: ModLoad & ModDataBlockFunctions) => Promise<void>;
        loadLocation?: () => Promise<void>;

        preTrackerUpdate?: (id: LocalId, tracker: Tracker, delta: Partial<Tracker>, syncTo: Sync) => Partial<Tracker>;
    };
}

interface ModLoad {
    currentUser: string;
    systems: Record<string, System>;
    systemsState: typeof SYSTEMS_STATE;

    ui: {
        shape: {
            registerContextMenuEntry: (entry: (shape: LocalId) => Section[]) => void;
            registerTab: (tab: PanelTab, filter: (shape: LocalId) => boolean) => void;
            registerMovementGuard: (guard: MovementGuard) => void;
            beginTemplateTargeting: (
                request: TemplateTargetRequest,
                completion: (result: TemplateTargetResult) => void,
            ) => Promise<void>;
        };
    };

    getShape: (shape: LocalId) => IShape | undefined;
    getGlobalId: (id: LocalId) => GlobalId | undefined;
}
