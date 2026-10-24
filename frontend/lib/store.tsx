"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  api,
  INPAINT_METHOD,
  ApiError,
  AUTO_BACKEND,
  connectionReport,
  isActiveJob,
  resolveOutputDir,
  type Job,
  type BackendInfo,
  type EditMethod,
  type FamilyDefaults,
  type Capabilities,
  type ExpressionFamily,
  type LoraSelection,
  type UploadResponse,
} from "@/lib/api";
import { FAMILY_DEFAULTS, detectFamily, reconcileSelections, type Adjustment } from "@/lib/model-defaults";

export type ConnectionStatus = "idle" | "connecting" | "connected" | "error";

export interface SelectedLora {
  name: string;
  strength: number;
}

export interface Parameters {
  model: string;
  sampler: string;
  scheduler: string;
  loras: SelectedLora[];
  clipSkip: number;
  seed: number;
  steps: number;
  width: number;
  height: number;
  cfgScale: number;
  denoisingStrength: number;
  prompt: string;
  negativePrompt: string;
}

export const DEFAULT_PARAMETERS: Parameters = {
  model: "",
  sampler: "",
  scheduler: "",
  loras: [],
  clipSkip: 2,
  seed: -1,
  steps: 32,
  width: 512,
  height: 768,
  cfgScale: 7,
  denoisingStrength: 0.5,
  prompt: "",
  negativePrompt: "",
};

export const AUTO_FAMILY = "auto";
const POLL_INTERVAL_MS = 2500;
const JOB_POLL_INTERVAL_MS = 1500;
const SETTINGS_KEY = "autoexpress-connection";

type Adjustments = Partial<Record<"model" | "sampler" | "scheduler", Adjustment>>;

interface Options {
  models: string[];
  samplers: string[];
  schedulers: string[];
  loras: string[];
}

interface AutoExpressState {
  // Connection
  backends: BackendInfo[] | null;
  backend: string;
  setBackend: (id: string) => void;
  apiUrl: string;
  setApiUrl: (url: string) => void;
  connection: ConnectionStatus;
  connect: () => Promise<void>;
  /** The WebUI that answered the last connect, e.g. the one "auto" detected. */
  connectedBackend: { id: string; name: string } | null;
  options: Options;
  /** Setup checklist for the connected WebUI, null on backends without it. */
  capabilities: Capabilities | null;
  checkingCapabilities: boolean;
  checkCapabilities: () => Promise<void>;

  // How the expression is changed; null when the backend has no /edit-methods
  editMethods: EditMethod[] | null;
  vramNote: string;
  method: string;
  setMethod: (id: string) => void;
  /** Instruction edit wording for drawn images or for photos. */
  photoStyle: boolean;
  setPhotoStyle: (value: boolean) => void;
  /** 0..1 expression strength the user picked, or null to use the model family's default. */
  intensity: number | null;
  setIntensity: (value: number | null) => void;
  /** Defaults of the family the selected model and prompt style resolve to. */
  familyDefaults: (FamilyDefaults & { family: string }) | null;

  // Prompt style
  families: ExpressionFamily[] | null;
  family: string;
  setFamily: (id: string) => void;
  isRealistic: boolean;
  setRealistic: (value: boolean) => void;

  // Parameters
  params: Parameters;
  setParam: <K extends keyof Parameters>(key: K, value: Parameters[K]) => void;
  /** Values swapped because the connected WebUI doesn't offer them. */
  adjustments: Adjustments;
  /** Sets sampler, scheduler, steps, CFG and clip skip to what the selected model's family usually uses. */
  applyModelDefaults: () => void;

  // Input image
  file: File | null;
  imageDataUrl: string | null;
  rawMetadata: string | null;
  uploading: boolean;
  setFile: (file: File | null) => Promise<void>;

  // Generation and output
  outputDirectory: string;
  setOutputDirectory: (dir: string) => void;
  generating: boolean;
  /** The running job on backends with the job API, null otherwise. */
  job: Job | null;
  generate: () => Promise<void>;
  interrupt: () => Promise<void>;
  images: string[];
  galleryDir: string;
  galleryVersion: number;
  loadImages: (dir?: string, refresh?: boolean) => Promise<void>;
}

const AutoExpressContext = createContext<AutoExpressState | undefined>(undefined);

function toNumber(value: unknown, fallback: number) {
  const n = typeof value === "number" ? value : parseFloat(String(value));
  return Number.isFinite(n) ? n : fallback;
}

function normalizeLoras(loras: LoraSelection[] | string | null | undefined): SelectedLora[] {
  if (!Array.isArray(loras)) return [];
  return loras
    .filter((lora) => lora && typeof lora.lora_name === "string")
    .map((lora) => ({ name: lora.lora_name.trim(), strength: toNumber(lora.lora_strength, 1) }));
}

function loraTag(name: string) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`<lora:\\s*${escaped}\\s*:[^>]*>`, "gi");
}

/**
 * The backend appends every selected LoRA to the prompt. LoRAs already written in
 * the prompt (e.g. read from the input image) get the strength from the LoRA list
 * instead of being added a second time.
 */
function applyLoras(prompt: string, loras: SelectedLora[]) {
  let adPrompt = prompt;
  const extra: LoraSelection[] = [];
  for (const lora of loras) {
    const tag = loraTag(lora.name);
    if (tag.test(adPrompt)) {
      adPrompt = adPrompt.replace(loraTag(lora.name), `<lora:${lora.name}:${lora.strength}>`);
    } else {
      extra.push({ lora_name: lora.name, lora_strength: lora.strength });
    }
  }
  return { adPrompt, extra };
}

function reconcileParams(base: Parameters, opts: Options, fillMissing: boolean) {
  if (opts.models.length === 0 && opts.samplers.length === 0) return { params: base, adjustments: {} };
  const result = reconcileSelections(base, opts);
  const params = { ...base, model: result.model, sampler: result.sampler, scheduler: result.scheduler };
  if (fillMissing) {
    const family = FAMILY_DEFAULTS[detectFamily(params.model)];
    const pick = (preferred: string[], available: string[]) =>
      preferred.find((name) => available.includes(name)) ?? available[0] ?? "";
    if (!params.sampler) params.sampler = pick(family.samplers, opts.samplers);
    if (!params.scheduler) params.scheduler = pick(family.schedulers, opts.schedulers);
  }
  return { params, adjustments: result.adjustments };
}

function readDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function AutoExpressProvider({ children }: { children: React.ReactNode }) {
  const [backends, setBackends] = useState<BackendInfo[] | null>(null);
  const [backend, setBackendState] = useState("a1111");
  const [apiUrl, setApiUrl] = useState("");
  const [connection, setConnection] = useState<ConnectionStatus>("idle");
  const [connectedBackend, setConnectedBackend] = useState<{ id: string; name: string } | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [checkingCapabilities, setCheckingCapabilities] = useState(false);
  const [options, setOptions] = useState<Options>({ models: [], samplers: [], schedulers: [], loras: [] });

  const [editMethods, setEditMethods] = useState<EditMethod[] | null>(null);
  const [vramNote, setVramNote] = useState("");
  const [method, setMethodState] = useState(INPAINT_METHOD);
  const [photoStyle, setPhotoStyleState] = useState(false);
  const [intensity, setIntensity] = useState<number | null>(null);
  const [familyDefaults, setFamilyDefaults] = useState<(FamilyDefaults & { family: string }) | null>(null);
  // Family defaults only fill in what the user hasn't chosen themselves.
  const touchedRef = useRef({ method: false, photoStyle: false });
  const setMethod = useCallback((id: string) => {
    touchedRef.current.method = true;
    setMethodState(id);
  }, []);
  const setPhotoStyle = useCallback((value: boolean) => {
    touchedRef.current.photoStyle = true;
    setPhotoStyleState(value);
  }, []);

  const [families, setFamilies] = useState<ExpressionFamily[] | null>(null);
  const [family, setFamilyState] = useState(AUTO_FAMILY);
  const [isRealistic, setRealisticState] = useState(false);

  const [params, setParams] = useState<Parameters>(DEFAULT_PARAMETERS);

  const [file, setFileState] = useState<File | null>(null);
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  const [rawMetadata, setRawMetadata] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const [outputDirectory, setOutputDirectory] = useState("");
  const [generating, setGenerating] = useState(false);
  const [images, setImages] = useState<string[]>([]);
  const [galleryDir, setGalleryDir] = useState("");
  const [galleryVersion, setGalleryVersion] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [adjustments, setAdjustments] = useState<Adjustments>({});
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const setParam = useCallback(<K extends keyof Parameters>(key: K, value: Parameters[K]) => {
    setParams((prev) => ({ ...prev, [key]: value }));
    if (key === "model" || key === "sampler" || key === "scheduler") {
      setAdjustments((prev) => {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key as keyof Adjustments];
        return next;
      });
    }
  }, []);

  const paramsRef = useRef(params);
  paramsRef.current = params;

  /** Swap auto-filled values the WebUI doesn't have for the closest match or family default. */
  const reconcile = useCallback((base: Parameters, opts: Options, fillMissing = false) => {
    const next = reconcileParams(base, opts, fillMissing);
    paramsRef.current = next.params;
    setParams(next.params);
    setAdjustments(next.adjustments);
  }, []);

  const applyModelDefaults = useCallback(() => {
    const opts = optionsRef.current;
    const prev = paramsRef.current;
    const family = FAMILY_DEFAULTS[detectFamily(prev.model)];
    const pick = (preferred: string[], available: string[], current: string) =>
      available.length === 0 ? current : (preferred.find((name) => available.includes(name)) ?? current);
    const next = {
      ...prev,
      sampler: pick(family.samplers, opts.samplers, prev.sampler),
      scheduler: pick(family.schedulers, opts.schedulers, prev.scheduler),
      steps: family.steps,
      cfgScale: family.cfgScale,
      clipSkip: family.clipSkip,
    };
    paramsRef.current = next;
    setParams(next);
    setAdjustments({});
    toast.success(`Applied ${family.label} defaults`);
  }, []);

  /** Which methods the selected WebUI supports; falls back to inpainting when the chosen one isn't. */
  const loadEditMethods = useCallback(() => {
    api
      .editMethods()
      .then((data) => {
        setEditMethods(data?.methods ?? null);
        setVramNote(data?.vram_note ?? "");
        setMethodState((current) =>
          data?.methods.some((m) => m.id === current && m.available) ? current : INPAINT_METHOD
        );
      })
      .catch(() => setEditMethods(null));
  }, []);

  // Restore the last used connection. Unless the user picked a WebUI, prefer
  // detecting it, then whatever the server is set to.
  const backendChosenRef = useRef(false);
  useEffect(() => {
    loadEditMethods();
    let savedBackend: string | undefined;
    try {
      const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null");
      if (saved?.apiUrl) setApiUrl(saved.apiUrl);
      if (saved?.backend && saved.backendChosen) {
        setBackendState(saved.backend);
        savedBackend = saved.backend;
        backendChosenRef.current = true;
      }
    } catch {
      // Storage unavailable
    }

    api
      .backends()
      .then((data) => {
        if (!data) return;
        setBackends(data.backends);
        const listed = (id?: string) => !!id && data.backends.some((b) => b.id === id);
        if (listed(savedBackend)) return;
        if (listed(AUTO_BACKEND)) setBackendState(AUTO_BACKEND);
        else if (data.selected) setBackendState(data.selected);
        if (data.url) setApiUrl(data.url);
      })
      .catch(() => setBackends(null));

    api
      .expressionFamilies()
      .then((data) => {
        if (!data) return;
        setFamilies(data.families);
        setFamilyState(data.selected || AUTO_FAMILY);
      })
      .catch(() => setFamilies(null));
  }, [loadEditMethods]);

  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiUrl, backend, backendChosen: backendChosenRef.current }));
    } catch {
      // Storage unavailable
    }
  }, [apiUrl, backend]);

  const setBackend = useCallback(
    (id: string) => {
      const previous = backends?.find((b) => b.id === backend);
      const next = backends?.find((b) => b.id === id);
      // Swap the URL along with the backend unless the user typed a custom one.
      if (next?.default_url && (!apiUrl || apiUrl === previous?.default_url)) {
        setApiUrl(next.default_url);
      }
      backendChosenRef.current = true;
      setBackendState(id);
      setConnection("idle");
      setConnectedBackend(null);
      setCapabilities(null);
    },
    [apiUrl, backend, backends]
  );

  const checkCapabilities = useCallback(async () => {
    setCheckingCapabilities(true);
    try {
      setCapabilities(await api.capabilities());
    } catch (error) {
      toast.error(`Could not check the WebUI: ${error instanceof Error ? error.message : error}`);
    } finally {
      setCheckingCapabilities(false);
    }
  }, []);

  const connect = useCallback(async () => {
    setConnection("connecting");
    setCapabilities(null);
    try {
      const result = await api.connect(apiUrl.trim(), backends ? backend : undefined);
      const found = result?.backend ? { id: result.backend, name: result.name || result.backend } : null;
      setConnectedBackend(found);
      if (result?.url) setApiUrl(result.url);
      const [models, samplers, schedulers, loras] = await Promise.all([
        api.models(),
        api.samplers(),
        api.schedulers(),
        api.loras(),
      ]);
      setOptions({ models, samplers, schedulers, loras });
      loadEditMethods();
      reconcile(paramsRef.current, { models, samplers, schedulers, loras });
      if (models.length === 0) {
        setConnection("error");
        toast.error("Connected, but the WebUI returned no models. Is it running with its API enabled?");
      } else {
        setConnection("connected");
        const to = result?.detected && found ? ` to ${found.name}` : "";
        toast.success(`Connected${to}: ${models.length} models, ${loras.length} LoRAs`);
      }
      checkCapabilities();
    } catch (error) {
      setConnection("error");
      setConnectedBackend(null);
      const message = error instanceof Error ? error.message : String(error);
      if (error instanceof ApiError && error.status !== 400) setCapabilities(connectionReport(message, error.fix));
      toast.error(`Could not connect: ${message}`);
    }
  }, [apiUrl, backend, backends, reconcile, checkCapabilities, loadEditMethods]);

  // Each model family has calibrated defaults: realistic models get much gentler expressions.
  useEffect(() => {
    let cancelled = false;
    api
      .expressionDefaults(params.model, family)
      .then((data) => {
        if (cancelled || !data) return;
        setFamilyDefaults({ family: data.family, ...data.defaults });
        if (!touchedRef.current.photoStyle) setPhotoStyleState(data.defaults.edit_style === "photo");
        if (!touchedRef.current.method && editMethods?.some((m) => m.id === data.defaults.method && m.available)) {
          setMethodState(data.defaults.method);
        }
      })
      .catch(() => {
        if (!cancelled) setFamilyDefaults(null);
      });
    return () => {
      cancelled = true;
    };
  }, [params.model, family, editMethods]);

  const setFamily = useCallback((id: string) => {
    const previous = family;
    setFamilyState(id);
    api.setExpressionFamily(id).catch((error) => {
      setFamilyState(previous);
      toast.error(`Could not set prompt style: ${error instanceof Error ? error.message : error}`);
    });
  }, [family]);

  const setRealistic = useCallback((value: boolean) => {
    setRealisticState(value);
    api.setRealistic(value).catch((error) => {
      setRealisticState(!value);
      toast.error(`Could not set style: ${error instanceof Error ? error.message : error}`);
    });
  }, []);

  const applyImageData = useCallback((data: UploadResponse) => {
    const prev = paramsRef.current;
    const cleaned = data.cleaned_data;
    if (!cleaned) {
      toast.info("No generation parameters found in this image, so the model's usual settings are used.");
      reconcile(
        { ...prev, width: toNumber(data.width, prev.width), height: toNumber(data.height, prev.height) },
        optionsRef.current,
        true
      );
      return;
    }
    reconcile(
      {
        ...prev,
        model: cleaned.ad_checkpoint ?? prev.model,
        sampler: cleaned.ad_sampler ?? prev.sampler,
        scheduler: cleaned.ad_scheduler ?? prev.scheduler,
        loras: normalizeLoras(cleaned.loras),
        clipSkip: toNumber(cleaned.ad_clip_skip, prev.clipSkip),
        seed: toNumber(cleaned.seed, prev.seed),
        steps: toNumber(cleaned.ad_steps, prev.steps),
        width: toNumber(cleaned.width ?? data.width, prev.width),
        height: toNumber(cleaned.height ?? data.height, prev.height),
        cfgScale: toNumber(cleaned.ad_cfg_scale, prev.cfgScale),
        denoisingStrength: toNumber(cleaned.ad_denoising_strength, prev.denoisingStrength),
        prompt: cleaned.ad_prompt ?? "",
        negativePrompt: cleaned.ad_negative_prompt ?? "",
      },
      optionsRef.current,
      true
    );
  }, [reconcile]);

  const setFile = useCallback(
    async (next: File | null) => {
      setFileState(next);
      setRawMetadata(null);
      if (!next) {
        setImageDataUrl(null);
        return;
      }
      setOutputDirectory(next.name.trim().split(".").slice(0, -1).join(".") || next.name);
      setImageDataUrl(await readDataUrl(next));

      setUploading(true);
      try {
        const data = await api.upload(next);
        setRawMetadata(data.uncleaned_data && data.uncleaned_data !== "None" ? data.uncleaned_data : null);
        applyImageData(data);
      } catch (error) {
        toast.error(`Could not read image metadata: ${error instanceof Error ? error.message : error}`);
      } finally {
        setUploading(false);
      }
    },
    [applyImageData]
  );

  const loadImages = useCallback(
    async (dir?: string, refresh = true) => {
      const target = resolveOutputDir(dir ?? outputDirectory);
      try {
        const files = await api.listImages(target);
        setGalleryDir(target);
        setImages(files ?? []);
        // Expressions overwrite files with the same names, so bust the browser cache.
        if (refresh) setGalleryVersion(Date.now());
      } catch (error) {
        toast.error(`Failed to load images: ${error instanceof Error ? error.message : error}`);
      }
    },
    [outputDirectory]
  );

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const finishJob = useCallback(
    (finished: Job) => {
      stopPolling();
      setGenerating(false);
      setJob(finished);
      loadImages(finished.output_dir, false);
      if (finished.status === "completed") {
        toast.success(`Finished generating expressions in Output/${finished.output_dir}`);
        if (finished.notes?.length) toast.warning("Some expression LoRAs were missing, see the note above the prompt.");
      } else if (finished.status === "cancelled") {
        toast.info(`Stopped after ${finished.progress.done} of ${finished.progress.total} expressions.`);
      } else {
        toast.error(finished.error?.message || "Generation failed");
      }
    },
    [loadImages, stopPolling]
  );

  // Follow a job until it ends, refreshing the gallery as expressions land.
  const trackJob = useCallback(
    (started: Job) => {
      setJob(started);
      setGenerating(true);
      setGalleryDir(started.output_dir);
      loadImages(started.output_dir);
      stopPolling();
      let lastDone = started.progress.done;
      let busy = false;
      pollRef.current = setInterval(async () => {
        if (busy) return;
        busy = true;
        try {
          const latest = await api.job(started.id);
          setJob(latest);
          if (latest.progress.done !== lastDone) {
            lastDone = latest.progress.done;
            loadImages(latest.output_dir, false);
          }
          if (!isActiveJob(latest)) finishJob(latest);
        } catch {
          // Transient error; try again on the next tick
        } finally {
          busy = false;
        }
      }, JOB_POLL_INTERVAL_MS);
    },
    [finishJob, loadImages, stopPolling]
  );

  // Pick up a job that is still running, e.g. after a page reload.
  useEffect(() => {
    api
      .jobs()
      .then((jobs) => {
        const active = jobs?.find(isActiveJob);
        if (active) trackJob(active);
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const generate = useCallback(async () => {
    if (!imageDataUrl) {
      toast.error("Drop an input image first.");
      return;
    }
    const dir = resolveOutputDir(outputDirectory);
    const { adPrompt, extra } = applyLoras(params.prompt, params.loras);
    setGenerating(true);
    setJob(null);
    loadImages(dir);
    stopPolling();
    // Older backends answer only when the whole set is done; watch the folder meanwhile.
    pollRef.current = setInterval(() => loadImages(dir, false), POLL_INTERVAL_MS);

    let tracking = false;
    try {
      const result = await api.generate({
        init_images: imageDataUrl,
        output_dir: outputDirectory,
        ad_scheduler: params.scheduler,
        loras: extra,
        seed: params.seed,
        ad_prompt: adPrompt,
        ad_negative_prompt: params.negativePrompt,
        ad_steps: params.steps,
        ad_checkpoint: params.model,
        ad_sampler: params.sampler,
        ad_clip_skip: params.clipSkip,
        ad_cfg_scale: params.cfgScale,
        ad_denoising_strength: params.denoisingStrength,
        ...(editMethods ? { method } : {}),
        ...(method !== INPAINT_METHOD ? { edit_style: photoStyle ? "photo" : "illustration" } : {}),
        ...(intensity !== null ? { expression_intensity: intensity } : {}),
      });
      if (result.job_id && result.job && isActiveJob(result.job)) {
        tracking = true;
        trackJob(result.job);
      } else if (result.job) {
        tracking = true;
        finishJob(result.job);
      } else if (result.status === "success") {
        toast.success(`Finished generating expressions in Output/${dir}`);
      } else {
        toast.error(result.message || "Generation failed");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      // Point at the setup checklist: the fix for an unreachable WebUI, or what it is missing.
      if (error instanceof ApiError && error.fix) setCapabilities(connectionReport(message, error.fix));
      else if (error instanceof ApiError && error.status === 409) checkCapabilities();
      toast.error(`Generation failed: ${message}`);
    } finally {
      if (!tracking) {
        stopPolling();
        setGenerating(false);
        loadImages(dir, false);
      }
    }
  }, [imageDataUrl, outputDirectory, params, editMethods, method, photoStyle, intensity, loadImages, stopPolling, trackJob, finishJob, checkCapabilities]);

  const interrupt = useCallback(async () => {
    try {
      if (isActiveJob(job)) {
        await api.cancelJob(job.id);
      } else {
        await api.interrupt();
      }
      toast.info("Stopping after the current expression.");
    } catch (error) {
      toast.error(`Could not interrupt: ${error instanceof Error ? error.message : error}`);
    }
  }, [job]);

  const value = useMemo<AutoExpressState>(
    () => ({
      backends,
      backend,
      setBackend,
      apiUrl,
      setApiUrl,
      connection,
      connect,
      connectedBackend,
      options,
      editMethods,
      vramNote,
      method,
      setMethod,
      photoStyle,
      setPhotoStyle,
      intensity,
      setIntensity,
      familyDefaults,
      capabilities,
      checkingCapabilities,
      checkCapabilities,
      families,
      family,
      setFamily,
      isRealistic,
      setRealistic,
      params,
      setParam,
      adjustments,
      applyModelDefaults,
      file,
      imageDataUrl,
      rawMetadata,
      uploading,
      setFile,
      outputDirectory,
      setOutputDirectory,
      generating,
      job,
      generate,
      interrupt,
      images,
      galleryDir,
      galleryVersion,
      loadImages,
    }),
    [
      backends, backend, setBackend, apiUrl, connection, connect, connectedBackend, options,
      capabilities, checkingCapabilities, checkCapabilities, editMethods, vramNote, method, setMethod, photoStyle, setPhotoStyle, intensity, familyDefaults,
      families, family, setFamily,
      isRealistic, setRealistic, params, setParam, adjustments, applyModelDefaults, file, imageDataUrl, rawMetadata, uploading, setFile,
      outputDirectory, generating, job, generate, interrupt, images, galleryDir, galleryVersion, loadImages,
    ]
  );

  return <AutoExpressContext.Provider value={value}>{children}</AutoExpressContext.Provider>;
}

export function useAutoExpress() {
  const context = useContext(AutoExpressContext);
  if (!context) throw new Error("useAutoExpress must be used within an AutoExpressProvider");
  return context;
}
