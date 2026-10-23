/**
 * Typical generation settings per model family, used when a value read from an
 * image (or left over from another WebUI) isn't available on the connected one.
 */

export type ModelFamily = "sd15" | "sdxl" | "pony" | "illustrious" | "flux" | "sd3";

export interface FamilyDefaults {
  label: string;
  /** Preferred samplers, best first. Names as A1111/Forge list them. */
  samplers: string[];
  /** Preferred schedulers, best first. */
  schedulers: string[];
  steps: number;
  cfgScale: number;
  width: number;
  height: number;
  clipSkip: number;
}

export const FAMILY_DEFAULTS: Record<ModelFamily, FamilyDefaults> = {
  sd15: {
    label: "SD 1.5",
    samplers: ["DPM++ 2M", "Euler a", "DPM++ 2M Karras", "euler_ancestral"],
    schedulers: ["Karras", "Automatic", "karras", "normal"],
    steps: 25,
    cfgScale: 7,
    width: 512,
    height: 768,
    clipSkip: 2,
  },
  sdxl: {
    label: "SDXL",
    samplers: ["DPM++ 2M SDE", "DPM++ 2M", "Euler a", "dpmpp_2m_sde", "dpmpp_2m"],
    schedulers: ["Karras", "Automatic", "karras", "normal"],
    steps: 30,
    cfgScale: 6,
    width: 832,
    height: 1216,
    clipSkip: 1,
  },
  pony: {
    label: "Pony",
    samplers: ["Euler a", "DPM++ 2M SDE", "euler_ancestral"],
    schedulers: ["Normal", "Automatic", "Karras", "normal"],
    steps: 25,
    cfgScale: 7,
    width: 832,
    height: 1216,
    clipSkip: 2,
  },
  illustrious: {
    label: "Illustrious",
    samplers: ["Euler a", "DPM++ 2M", "euler_ancestral"],
    schedulers: ["Normal", "Automatic", "Karras", "normal"],
    steps: 28,
    cfgScale: 5.5,
    width: 832,
    height: 1216,
    clipSkip: 2,
  },
  flux: {
    label: "Flux",
    samplers: ["Euler", "euler", "[Forge] Flux Realistic"],
    schedulers: ["Simple", "Beta", "simple", "beta", "Automatic"],
    steps: 20,
    cfgScale: 1,
    width: 896,
    height: 1152,
    clipSkip: 1,
  },
  sd3: {
    label: "SD 3",
    samplers: ["Euler", "DPM++ 2M", "euler"],
    schedulers: ["SGM Uniform", "Simple", "sgm_uniform", "Automatic"],
    steps: 28,
    cfgScale: 4.5,
    width: 1024,
    height: 1024,
    clipSkip: 1,
  },
};

// Checked in order, first match wins (Pony and Illustrious merges are SDXL too).
const FAMILY_PATTERNS: [ModelFamily, RegExp][] = [
  ["flux", /flux|schnell/i],
  ["sd3", /sd3|sd_3|sd-3|stable.?diffusion.?3/i],
  ["pony", /pony|pdxl|autismmix|score_?9/i],
  ["illustrious", /illustrious|\billu|noob|\bwai[-_ ]|obsession/i],
  ["sdxl", /xl|sdxl|juggernaut|animagine|playground|realvis|dreamshaper.?xl|zavychroma|turbo|lightning/i],
];

export function detectFamily(modelName: string | null | undefined): ModelFamily {
  if (!modelName) return "sd15";
  return FAMILY_PATTERNS.find(([, pattern]) => pattern.test(modelName))?.[0] ?? "sd15";
}

function normalize(name: string) {
  return name
    .toLowerCase()
    .replace(/\s*\[[a-f0-9]+\]$/, "")
    .replace(/\.(safetensors|ckpt|pt|pth|gguf)$/, "")
    .replace(/[^a-z0-9]/g, "");
}

function findAvailable(wanted: string, available: string[]) {
  const key = normalize(wanted);
  return available.find((option) => option === wanted) ?? available.find((option) => normalize(option) === key);
}

function firstAvailable(preferred: string[], available: string[]) {
  for (const name of preferred) {
    const match = findAvailable(name, available);
    if (match) return match;
  }
  return undefined;
}

/** The installed checkpoint closest to `wanted`: same name first, then same family. */
export function closestModel(wanted: string, available: string[]): string | undefined {
  if (available.length === 0) return undefined;
  const exact = findAvailable(wanted, available);
  if (exact) return exact;
  const key = normalize(wanted);
  const partial = key && available.find((option) => normalize(option).includes(key) || key.includes(normalize(option)));
  if (partial) return partial;
  const family = detectFamily(wanted);
  return available.find((option) => detectFamily(option) === family) ?? available[0];
}

export interface Adjustment {
  from: string;
  to: string;
  reason: string;
}

export interface Reconciled {
  model: string;
  sampler: string;
  scheduler: string;
  adjustments: Partial<Record<"model" | "sampler" | "scheduler", Adjustment>>;
}

/**
 * Swaps values the connected WebUI doesn't offer for the closest match or the
 * family's usual setting. Empty option lists are left alone (the backend has
 * no such concept, or isn't connected).
 */
export function reconcileSelections(
  current: { model: string; sampler: string; scheduler: string },
  options: { models: string[]; samplers: string[]; schedulers: string[] }
): Reconciled {
  const result: Reconciled = { ...current, adjustments: {} };

  if (current.model && options.models.length > 0) {
    const match = closestModel(current.model, options.models);
    if (match && match !== current.model) {
      const exactName = normalize(match) === normalize(current.model);
      if (!exactName) {
        result.adjustments.model = {
          from: current.model,
          to: match,
          reason: `not installed, using the closest ${FAMILY_DEFAULTS[detectFamily(current.model)].label} checkpoint`,
        };
      }
      result.model = match;
    }
  }

  const family = FAMILY_DEFAULTS[detectFamily(result.model || current.model)];
  let sampler = current.sampler;
  let scheduler = current.scheduler;

  // Older A1111 names put the schedule in the sampler: "DPM++ 2M Karras".
  if (sampler && options.samplers.length > 0 && !findAvailable(sampler, options.samplers)) {
    const split = sampler.match(/^(.*)\s+(Karras|Exponential|SGM Uniform|Simple|Beta|Normal)$/i);
    if (split && findAvailable(split[1], options.samplers)) {
      sampler = split[1];
      if (!scheduler || scheduler === "Automatic") scheduler = split[2];
    }
  }

  if (options.samplers.length > 0) {
    const match = sampler ? findAvailable(sampler, options.samplers) : undefined;
    if (match) {
      result.sampler = match;
    } else if (sampler) {
      const fallback = firstAvailable(family.samplers, options.samplers) ?? options.samplers[0];
      result.adjustments.sampler = { from: sampler, to: fallback, reason: `not available, using the ${family.label} default` };
      result.sampler = fallback;
    }
  }

  if (options.schedulers.length > 0) {
    const match = scheduler ? findAvailable(scheduler, options.schedulers) : undefined;
    if (match) {
      result.scheduler = match;
    } else if (scheduler) {
      const fallback = firstAvailable(family.schedulers, options.schedulers) ?? options.schedulers[0];
      result.adjustments.scheduler = { from: scheduler, to: fallback, reason: `not available, using the ${family.label} default` };
      result.scheduler = fallback;
    }
  }

  return result;
}
