"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, Loader2, RotateCcw, Upload } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  expressionName,
  INPAINT_METHOD,
  resolveOutputDir,
  type ExpressionOverride,
  type ExpressionOverrides,
  type ExpressionOverrideSettings,
} from "@/lib/api";
import { useAutoExpress } from "@/lib/store";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

type NumberKey = Exclude<keyof ExpressionOverrideSettings, "ad_negative_prompt">;

interface Field {
  key: NumberKey;
  label: string;
  step: number;
  min: number;
  max: number;
}

const SEED: Field = { key: "seed", label: "Seed", step: 1, min: -1, max: Number.MAX_SAFE_INTEGER };
const INTENSITY: Field = { key: "expression_intensity", label: "Intensity", step: 0.05, min: 0, max: 1 };
const INPAINT_FIELDS: Field[] = [
  SEED,
  INTENSITY,
  { key: "ad_denoising_strength", label: "Denoising", step: 0.05, min: 0, max: 1 },
  { key: "ad_steps", label: "Steps", step: 1, min: 1, max: 150 },
  { key: "ad_cfg_scale", label: "CFG scale", step: 0.5, min: 0, max: 30 },
];
const EDIT_FIELDS: Field[] = [
  SEED,
  INTENSITY,
  { key: "edit_steps", label: "Edit steps", step: 1, min: 1, max: 100 },
  { key: "edit_cfg_scale", label: "Edit CFG", step: 0.5, min: 0, max: 20 },
];

/** What the editor holds per expression: text boxes, empty meaning "use the shared value". */
interface Draft {
  prompt: string;
  negative: string;
  numbers: Partial<Record<NumberKey, string>>;
}

function toDraft(override: ExpressionOverride | undefined, defaultPrompt: string): Draft {
  const settings = override?.settings ?? {};
  const numbers: Draft["numbers"] = {};
  for (const [key, value] of Object.entries(settings)) {
    if (key !== "ad_negative_prompt" && typeof value === "number") numbers[key as NumberKey] = String(value);
  }
  return { prompt: override?.prompt ?? defaultPrompt, negative: settings.ad_negative_prompt ?? "", numbers };
}

/** The override a draft stands for; the default wording left as is is not stored, so it keeps following the intensity. */
function fromDraft(draft: Draft, defaultPrompt: string): ExpressionOverride {
  const settings: ExpressionOverrideSettings = {};
  for (const [key, text] of Object.entries(draft.numbers)) {
    const value = parseFloat(text ?? "");
    if (text?.trim() && Number.isFinite(value)) settings[key as NumberKey] = value;
  }
  if (draft.negative.trim()) settings.ad_negative_prompt = draft.negative.trim();
  const prompt = draft.prompt.trim();
  return {
    ...(prompt && prompt !== defaultPrompt.trim() ? { prompt } : {}),
    ...(Object.keys(settings).length ? { settings } : {}),
  };
}

function isEmpty(override: ExpressionOverride) {
  return !override.prompt && !Object.keys(override.settings ?? {}).length;
}

interface ExpressionSettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The expression to show first, e.g. the one on screen in the gallery. */
  expression?: string | null;
}

/**
 * Advanced: each expression's own prompt and settings, saved with the character (Output/<name>/autoexpress_overrides.json)
 * and used on every run, plus a retry of a single expression with them.
 */
export function ExpressionSettingsDialog({ open, onOpenChange, expression }: ExpressionSettingsDialogProps) {
  const {
    galleryDir, outputDirectory, images, method, params, intensity, familyDefaults, family, photoStyle, pose, posesAvailable,
    generating, imageDataUrl, retryExpression,
  } = useAutoExpress();
  const dir = galleryDir || resolveOutputDir(outputDirectory);
  const instruct = method !== INPAINT_METHOD;
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saved, setSaved] = useState<ExpressionOverrides>({});
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [remember, setRemember] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);

  const names = useMemo(() => Object.keys(defaults), [defaults]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [prompts, stored] = await Promise.all([
        api.expressionPrompts({
          method: instruct ? method : INPAINT_METHOD,
          ad_checkpoint: params.model,
          family,
          ...(intensity !== null ? { expression_intensity: intensity } : {}),
          ...(instruct ? { edit_style: photoStyle ? "photo" : "illustration" } : {}),
          ...(pose && posesAvailable ? { pose: true } : {}),
        }),
        api.expressionOverrides(dir),
      ]);
      if (!prompts || stored === null) {
        toast.error("This AutoExpress server has no per-expression settings. Update it.");
        onOpenChange(false);
        return;
      }
      setDefaults(prompts.prompts);
      setSaved(stored);
      setDrafts(Object.fromEntries(Object.entries(prompts.prompts).map(([name, text]) => [name, toDraft(stored[name], text)])));
      setSelected((current) => {
        const wanted = expression?.toLowerCase();
        if (wanted && wanted in prompts.prompts) return wanted;
        return current in prompts.prompts ? current : Object.keys(prompts.prompts)[0] ?? "";
      });
    } catch (error) {
      toast.error(`Could not load the expression settings: ${error instanceof Error ? error.message : error}`);
    } finally {
      setLoading(false);
    }
  }, [dir, method, instruct, params.model, family, intensity, photoStyle, pose, posesAvailable, expression, onOpenChange]);

  useEffect(() => {
    if (open) load();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const current = drafts[selected];
  const currentDefault = defaults[selected] ?? "";
  const overrides = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(drafts)
          .map(([name, draft]) => [name, fromDraft(draft, defaults[name] ?? "")] as const)
          .filter(([, override]) => !isEmpty(override))
      ) as ExpressionOverrides,
    [drafts, defaults]
  );
  const dirty = JSON.stringify(overrides) !== JSON.stringify(saved);
  const hasImage = images.some((file) => file.replace(/\.[^.]+$/, "").toLowerCase() === selected);

  const update = (patch: Partial<Draft>) => setDrafts((all) => ({ ...all, [selected]: { ...all[selected], ...patch } }));
  const setNumber = (key: NumberKey, text: string) => update({ numbers: { ...current.numbers, [key]: text } });

  const shared: Record<NumberKey, string> = {
    seed: String(params.seed),
    expression_intensity: String(intensity ?? familyDefaults?.intensity ?? "default"),
    ad_denoising_strength: String(params.denoisingStrength),
    ad_steps: String(params.steps),
    ad_cfg_scale: String(params.cfgScale),
    edit_steps: "default",
    edit_cfg_scale: "default",
  };

  const save = async (next: ExpressionOverrides = overrides, quiet = false) => {
    setBusy(true);
    try {
      const result = await api.saveExpressionOverrides(dir, next);
      setSaved(result.expressions);
      if (!quiet) toast.success(`Saved per-expression settings for Output/${dir}.`);
      return true;
    } catch (error) {
      toast.error(`Could not save: ${error instanceof Error ? error.message : error}`);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const importFile = async (file: File) => {
    try {
      const data = JSON.parse(await file.text());
      const imported: ExpressionOverrides = data?.expressions ?? data;
      if (!imported || typeof imported !== "object") throw new Error("not an AutoExpress settings file");
      if (await save(imported, true)) {
        setDrafts(Object.fromEntries(names.map((name) => [name, toDraft(imported[name], defaults[name])])));
        toast.success(`Imported settings for ${Object.keys(imported).length} expressions into Output/${dir}.`);
      }
    } catch (error) {
      toast.error(`Could not import ${file.name}: ${error instanceof Error ? error.message : error}`);
    }
  };

  const retry = async () => {
    const override = fromDraft(current, currentDefault);
    if (remember && dirty) {
      // Keep the edits of the other expressions too, so a retry never drops them.
      if (!(await save(overrides, true))) return;
    }
    onOpenChange(false);
    await retryExpression(selected, override, false);
  };

  const fields = instruct ? EDIT_FIELDS : INPAINT_FIELDS;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-[calc(100vw-2rem)] max-w-3xl sm:max-w-3xl flex-col gap-3 overflow-hidden p-4 sm:p-6">
        <DialogHeader>
          <DialogTitle>Per-expression settings</DialogTitle>
          <DialogDescription>
            Give single expressions their own prompt and settings. They are saved with the character in Output/{dir} and used on
            every run; empty fields use the shared settings.
          </DialogDescription>
        </DialogHeader>

        {loading || !current ? (
          <div className="flex flex-1 items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Loading" />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-3 sm:flex-row">
            <ScrollArea className="max-h-32 shrink-0 rounded-md border sm:max-h-none sm:w-44">
              <ul className="flex flex-wrap gap-1 p-1 sm:flex-col sm:flex-nowrap">
                {names.map((name) => (
                  <li key={name}>
                    <button
                      type="button"
                      onClick={() => setSelected(name)}
                      className={cn(
                        "flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-sm hover:bg-accent",
                        name === selected && "bg-accent font-medium"
                      )}
                    >
                      {expressionName(name)}
                      {overrides[name] && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-label="has its own settings" />}
                    </button>
                  </li>
                ))}
              </ul>
            </ScrollArea>

            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-3 pr-2">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <Label htmlFor="expression-prompt">{instruct ? "Edit instruction" : "Expression prompt"}</Label>
                    {current.prompt.trim() !== currentDefault.trim() && (
                      <button type="button" className="text-xs text-muted-foreground underline" onClick={() => update({ prompt: currentDefault })}>
                        Reset to default
                      </button>
                    )}
                  </div>
                  <Textarea
                    id="expression-prompt"
                    value={current.prompt}
                    onChange={(e) => update({ prompt: e.target.value })}
                    rows={instruct ? 5 : 3}
                    className="font-mono text-xs"
                  />
                  <p className="text-xs text-muted-foreground">
                    {instruct
                      ? "Sent to Qwen-Image-Edit as the whole instruction for this expression."
                      : "Replaces this expression's tags; your character prompt, quality tags and LoRAs are still added."}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {fields.map((field) => (
                    <div key={field.key} className="space-y-1">
                      <Label htmlFor={`override-${field.key}`} className="text-xs">
                        {field.label}
                      </Label>
                      <Input
                        id={`override-${field.key}`}
                        type="number"
                        step={field.step}
                        min={field.min}
                        max={field.max}
                        value={current.numbers[field.key] ?? ""}
                        placeholder={shared[field.key]}
                        onChange={(e) => setNumber(field.key, e.target.value)}
                        className="h-8 text-sm"
                      />
                    </div>
                  ))}
                </div>

                {!instruct && (
                  <div className="space-y-1">
                    <Label htmlFor="override-negative" className="text-xs">
                      Negative prompt
                    </Label>
                    <Input
                      id="override-negative"
                      value={current.negative}
                      placeholder="The shared negative prompt"
                      onChange={(e) => update({ negative: e.target.value })}
                      className="h-8 text-sm"
                    />
                  </div>
                )}
              </div>
            </ScrollArea>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <Button variant="ghost" size="sm" asChild>
            <a href={api.exportOverridesUrl(dir)} download>
              <Download className="mr-1 h-4 w-4" /> Export
            </a>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => fileInput.current?.click()} disabled={busy || loading}>
            <Upload className="mr-1 h-4 w-4" /> Import
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) importFile(file);
            }}
          />
          <div className="flex-1" />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Switch checked={remember} onCheckedChange={setRemember} aria-label="Remember the edits when retrying" />
            Remember
          </label>
          <Button
            variant="outline"
            size="sm"
            onClick={retry}
            disabled={busy || loading || generating || !imageDataUrl || !current}
            title={!imageDataUrl ? "Drop the character's input image first." : hasImage ? `Make ${expressionName(selected)} again` : `Make ${expressionName(selected)}`}
          >
            <RotateCcw className="mr-1 h-4 w-4" /> {hasImage ? "Retry" : "Generate"} {current ? expressionName(selected) : ""}
          </Button>
          <Button size="sm" onClick={() => save()} disabled={busy || loading || !dirty}>
            {busy && <Loader2 className="mr-1 h-4 w-4 animate-spin" />} Save
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
