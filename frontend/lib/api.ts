/**
 * Client for the AutoExpress Flask backend.
 *
 * In production the Flask app serves the exported frontend, so every call is
 * same-origin. During `next dev` the requests are rewritten to the Flask
 * server (see next.config.ts).
 */

export interface BackendInfo {
  id: string;
  name: string;
  /** Missing on "auto", which has no URL of its own. */
  default_url?: string;
}

/** The id that asks the server to work out which WebUI answers at the URL. */
export const AUTO_BACKEND = "auto";

export interface ConnectResponse {
  status: string;
  /** The WebUI that answered; with "auto", the one that was detected. */
  backend?: string;
  name?: string;
  url?: string;
  detected?: boolean;
}

export interface CapabilityFix {
  steps: string[];
  commands: string[];
  links: { label: string; url: string }[];
}

export interface CapabilityItem {
  key: string;
  label: string;
  ok: boolean;
  detail: string | null;
  required: boolean;
  fix: CapabilityFix | null;
}

/** A one-row report for a WebUI that could not be reached, so its fix shows in the setup checklist. */
export function connectionReport(message: string, fix: CapabilityFix | null): Capabilities {
  return {
    backend: "",
    name: "WebUI",
    url: "",
    ready: false,
    error: null,
    detected: false,
    missing: ["Connection"],
    items: [{ key: CONNECTION_ITEM, label: "Connection", ok: false, detail: message, required: true, fix }],
  };
}

export const CONNECTION_ITEM = "connection";

/** What the connected WebUI has and lacks for AutoExpress, from GET /backend/capabilities. */
export interface Capabilities {
  backend: string;
  name: string;
  url: string;
  ready: boolean;
  error: string | null;
  detected: boolean;
  missing: string[];
  items: CapabilityItem[];
}

export interface BackendsResponse {
  selected: string;
  url: string;
  backends: BackendInfo[];
}

export interface ExpressionFamily {
  id: string;
  name: string;
  description: string;
  models: string[];
}

export interface ExpressionFamiliesResponse {
  selected: string;
  families: ExpressionFamily[];
}

/** A way to change the expression: face inpainting, or the instruction edit mode (Qwen-Image-Edit). */
export interface EditMethod {
  id: string;
  name: string;
  description: string;
  /** Whether the connected WebUI can do it. */
  available: boolean;
}

export interface EditMethodsResponse {
  backend: string;
  methods: EditMethod[];
  vram_note: string;
}

export const INPAINT_METHOD = "inpaint";

/** Whether exports can be cut out of their background (rembg on the AutoExpress server). */
export interface BackgroundRemovalInfo {
  available: boolean;
  models: { illustration: string; photo: string };
  install_command: string;
}

export interface LoraSelection {
  lora_name: string;
  lora_strength: number | string;
}

/** Parameters parsed from an image by `autoexpress.modules.image_parser`. */
export interface CleanedImageData {
  ad_checkpoint: string | null;
  ad_sampler: string | null;
  ad_scheduler: string | null;
  loras: LoraSelection[] | string | null;
  ad_clip_skip: number | string;
  seed: number | string;
  ad_steps: number | string;
  width: number | null;
  height: number | null;
  ad_cfg_scale: number | string;
  ad_denoising_strength: number | string;
  ad_prompt: string | null;
  ad_negative_prompt: string | null;
}

export interface UploadResponse {
  cleaned_data: CleanedImageData | null;
  uncleaned_data: string | null;
  width: number | null;
  height: number | null;
}

export interface GenerateRequest {
  init_images: string;
  output_dir: string;
  ad_scheduler: string;
  loras: LoraSelection[];
  seed: number;
  ad_prompt: string;
  ad_negative_prompt: string;
  ad_steps: number;
  ad_checkpoint: string;
  ad_sampler: string;
  ad_clip_skip: number;
  ad_cfg_scale: number;
  ad_denoising_strength: number;
  method?: string;
  /** Instruction edit wording: "illustration" keeps the art style, "photo" keeps a photo realistic. */
  edit_style?: string;
  /** 0..1 expression strength; omitted means the model family's calibrated default. */
  expression_intensity?: number;
  /** Save every expression with a transparent background. */
  remove_background?: boolean;
}

/** What works best for a model family: method, expression intensity and instruction edit wording. */
export interface FamilyDefaults {
  method: string;
  intensity: number;
  edit_style: string;
}

export interface ExpressionDefaultsResponse {
  family: string;
  defaults: FamilyDefaults;
}

export interface JobProgress {
  done: number;
  total: number;
  fraction: number;
  current: string | null;
  step: { fraction: number; eta: number | null } | null;
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

/** A generation job, from backends with the job API (GET /jobs). */
export interface Job {
  id: string;
  status: JobStatus;
  backend: string;
  backend_name: string;
  output_dir: string;
  progress: JobProgress;
  images: { expression: string; url: string }[];
  error: { code: string; message: string } | null;
  notes?: JobNote[];
}

/** An expression LoRA the WebUI lacks and AutoExpress couldn't install itself. */
export interface JobNote {
  kind: string;
  name: string;
  title: string;
  file_name: string;
  size_mb: number | null;
  url: string;
  message: string;
}

export interface GenerateResponse {
  status: string;
  message?: string;
  job_id?: string;
  job?: Job;
}

export function isActiveJob(job: Job | null | undefined): job is Job {
  return !!job && (job.status === "queued" || job.status === "running");
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public body: unknown = null) {
    super(message);
  }

  /** Steps to fix an unreachable WebUI or a refused login, when the backend sends them. */
  get fix(): CapabilityFix | null {
    const error = (this.body as { error?: { fix?: CapabilityFix } } | null)?.error;
    return error && typeof error === "object" && error.fix ? error.fix : null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON body (e.g. an HTML error page)
  }
  if (!response.ok) {
    throw new ApiError(errorMessage(body) || `${response.status} ${response.statusText}`, response.status, body);
  }
  return body as T;
}

/** Pulls a readable message out of `{error: "..."}`, `{error: {message}}` or `{message}`. */
export function errorMessage(body: unknown): string {
  if (!body || typeof body !== "object") return "";
  const { error, message } = body as { error?: unknown; message?: unknown };
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && typeof (error as { message?: unknown }).message === "string") {
    return (error as { message: string }).message;
  }
  return typeof message === "string" ? message : "";
}

function postJson<T>(path: string, data: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Returns null when the backend does not expose the endpoint (older backends). */
async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405)) {
      return null;
    }
    throw error;
  }
}

async function stringList(path: string): Promise<string[]> {
  const data = await request<unknown>(path);
  return Array.isArray(data) ? data.filter((item): item is string => typeof item === "string") : [];
}

export const api = {
  backends: () => optional(request<BackendsResponse>("/backends")),

  connect: (url: string, backend?: string) =>
    postJson<ConnectResponse>("/receive_data", backend ? { text: url, backend } : { text: url }),

  capabilities: () => optional(request<Capabilities>("/backend/capabilities")),

  models: () => stringList("/get-models"),
  samplers: () => stringList("/get-samplers"),
  schedulers: () => stringList("/get-schedulers"),
  loras: () => stringList("/get-loras"),

  upload: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<UploadResponse>("/upload", { method: "POST", body: formData });
  },

  /**
   * Starts a generation. Backends with the job API answer at once with a job to
   * poll; older ones ignore `wait` and answer when the whole set is done.
   */
  generate: (data: GenerateRequest) => postJson<GenerateResponse>("/generate", { ...data, wait: false }),

  jobs: async () => (await optional(request<{ jobs: Job[] }>("/jobs")))?.jobs ?? null,
  job: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
  cancelJob: (id: string) => postJson<unknown>(`/jobs/${encodeURIComponent(id)}/cancel`, {}),

  interrupt: () => postJson<unknown>("/interrupt", {}),

  expressionFamilies: () => optional(request<ExpressionFamiliesResponse>("/expression-families")),
  setExpressionFamily: (family: string) => postJson<unknown>("/expression-family", { family }),

  editMethods: () => optional(request<EditMethodsResponse>("/edit-methods")),
  backgroundRemoval: () => optional(request<BackgroundRemovalInfo>("/background-removal")),
  expressionDefaults: (checkpoint: string, family: string) =>
    optional(
      request<ExpressionDefaultsResponse>(
        `/expression-defaults?checkpoint=${encodeURIComponent(checkpoint)}&family=${encodeURIComponent(family)}`
      )
    ),

  setRealistic: (isRealistic: boolean) => postJson<unknown>("/toggle", { isRealistic }),

  /** PNG file names in Output/<dir>, or null when the folder does not exist yet. */
  listImages: async (dir: string): Promise<string[] | null> => {
    try {
      const files = await request<unknown>(`/images/${encodePath(dir)}`);
      return Array.isArray(files)
        ? files.filter((f): f is string => typeof f === "string" && f.toLowerCase().endsWith(".png")).sort()
        : [];
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },

  imageUrl: (dir: string, file: string, version?: number) =>
    `/image/${encodePath(dir)}/${encodeURIComponent(file)}${version ? `?v=${version}` : ""}`,
};

function encodePath(path: string) {
  return path
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
}

/** Same rule the Flask /generate route uses to pick the output folder. */
export function resolveOutputDir(outputDirectory: string) {
  return outputDirectory.trim().replace(/\.[^.]*$/, "") || "New_Character";
}

/** "smile.png" -> "Smile", matching the legacy viewer. */
export function expressionName(file: string) {
  const name = file.replace(/\.[^.]+$/, "").replace(/_/g, " ");
  return name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
}
