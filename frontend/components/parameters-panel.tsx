"use client";

import { Link, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { AUTO_FAMILY, useAutoExpress, type ConnectionStatus } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { LoraSelect } from "@/components/lora-select";
import { SliderField } from "@/components/slider-field";
import { FAMILY_DEFAULTS, detectFamily, type Adjustment } from "@/lib/model-defaults";

function AdjustmentNote({ adjustment }: { adjustment?: Adjustment }) {
  if (!adjustment) return null;
  return (
    <p className="text-xs text-amber-600 dark:text-amber-400" role="status">
      <span className="font-medium">{adjustment.from}</span> {adjustment.reason}.
    </p>
  );
}

const CONNECT_BUTTON_CLASSES: Record<ConnectionStatus, string> = {
  idle: "",
  connecting: "",
  connected: "border-green-500 text-green-600 dark:text-green-400",
  error: "border-destructive text-destructive",
};

// Model names come back as "name.safetensors [hash]"; show them without the noise.
function cleanModelName(name: string) {
  return name
    .replace(/\s*\[[a-f0-9]+\]$/i, "")
    .replace(/\.(safetensors|ckpt|pt|pth|gguf)$/i, "")
    .trim();
}

function toOptions(values: string[], current: string, clean?: (value: string) => string) {
  // Keep a value read from an image selectable even when the WebUI doesn't list it.
  const all = current && !values.includes(current) ? [current, ...values] : values;
  return all.map((value) => ({ value, label: clean ? clean(value) : value }));
}

function validation(values: string[], current: string, connected: boolean) {
  if (!connected || !current) return "none" as const;
  return values.includes(current) ? ("valid" as const) : ("invalid" as const);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 sm:space-y-4">
      <h3 className="border-b pb-2 text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </section>
  );
}

export function ParametersPanel() {
  const {
    backends,
    backend,
    setBackend,
    apiUrl,
    setApiUrl,
    connection,
    connect,
    options,
    families,
    family,
    setFamily,
    isRealistic,
    setRealistic,
    params,
    setParam,
    adjustments,
    applyModelDefaults,
  } = useAutoExpress();
  const modelFamily = FAMILY_DEFAULTS[detectFamily(params.model)];

  const connected = connection === "connected";
  const currentBackend = backends?.find((b) => b.id === backend);
  const placeholderUrl = currentBackend?.default_url.replace(/^https?:\/\//, "") ?? "127.0.0.1:7860";

  return (
    <ScrollArea className="h-full">
      <div className="space-y-5 p-3 sm:space-y-6 sm:p-6">
        {/* WebUI connection */}
        <Section title="WebUI Connection">
          {backends && backends.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="backend-select" className="text-sm font-medium">
                Backend
              </Label>
              <Select value={backend} onValueChange={setBackend}>
                <SelectTrigger id="backend-select" className="w-full">
                  <SelectValue placeholder="Select WebUI" />
                </SelectTrigger>
                <SelectContent>
                  {backends.map((b) => (
                    <SelectItem key={b.id} value={b.id}>
                      {b.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="api-url" className="text-sm font-medium">
              {currentBackend ? `${currentBackend.name} API` : "A1111 API"}
            </Label>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                connect();
              }}
            >
              <Input
                id="api-url"
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
                placeholder={placeholderUrl}
                className="flex-1 text-sm"
              />
              <Button
                type="submit"
                size="icon"
                variant="outline"
                className={cn("h-9 w-9 shrink-0", CONNECT_BUTTON_CLASSES[connection])}
                disabled={connection === "connecting"}
                aria-label="Connect"
                title={connection === "connected" ? "Connected, click to refresh lists" : "Connect"}
              >
                {connection === "connecting" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link className="h-4 w-4" />}
              </Button>
            </form>
          </div>
        </Section>

        {/* Generation settings */}
        <Section title="Generation Settings">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label className="text-sm font-medium">Model</Label>
              {params.model && (
                <button
                  type="button"
                  onClick={applyModelDefaults}
                  className="text-xs text-primary underline-offset-4 hover:underline"
                  title={`Sampler, scheduler, steps, CFG and clip skip that ${modelFamily.label} models usually use`}
                >
                  Use {modelFamily.label} defaults
                </button>
              )}
            </div>
            <Combobox
              options={toOptions(options.models, params.model, cleanModelName)}
              value={params.model}
              onValueChange={(value) => setParam("model", value)}
              placeholder="Select model"
              searchPlaceholder="Search models..."
              emptyText={options.models.length ? "No model found." : "Connect to list models."}
              validationState={validation(options.models, params.model, connected)}
            />
            <AdjustmentNote adjustment={adjustments.model} />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
            <div className="space-y-2">
              <Label className="text-sm font-medium">Sampler</Label>
              <Combobox
                options={toOptions(options.samplers, params.sampler)}
                value={params.sampler}
                onValueChange={(value) => setParam("sampler", value)}
                placeholder="Select"
                searchPlaceholder="Search samplers..."
                emptyText={options.samplers.length ? "No sampler found." : "Connect to list samplers."}
                validationState={validation(options.samplers, params.sampler, connected)}
              />
              <AdjustmentNote adjustment={adjustments.sampler} />
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium">Scheduler</Label>
              <Combobox
                options={toOptions(options.schedulers, params.scheduler)}
                value={params.scheduler}
                onValueChange={(value) => setParam("scheduler", value)}
                placeholder="Select"
                searchPlaceholder="Search schedulers..."
                emptyText={options.schedulers.length ? "No scheduler found." : "Connect to list schedulers."}
                validationState={validation(options.schedulers, params.scheduler, connected)}
              />
              <AdjustmentNote adjustment={adjustments.scheduler} />
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-sm font-medium">LoRA(s)</Label>
            <LoraSelect available={options.loras} value={params.loras} onChange={(value) => setParam("loras", value)} />
          </div>

          {families ? (
            <div className="space-y-2">
              <Label htmlFor="prompt-style" className="text-sm font-medium">
                Prompt Style
              </Label>
              <Select value={family} onValueChange={setFamily}>
                <SelectTrigger id="prompt-style" className="w-full">
                  <SelectValue placeholder="Auto (from model name)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO_FAMILY}>Auto (from model name)</SelectItem>
                  {families.map((f) => (
                    <SelectItem key={f.id} value={f.id} title={`${f.description}\ne.g. ${f.models.join(", ")}`}>
                      {f.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {family !== AUTO_FAMILY && (
                <p className="text-xs text-muted-foreground">{families.find((f) => f.id === family)?.description}</p>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center gap-3 text-sm">
              <Label htmlFor="style-toggle" className={cn(!isRealistic && "font-semibold")}>
                Anime
              </Label>
              <Switch id="style-toggle" checked={isRealistic} onCheckedChange={setRealistic} />
              <Label htmlFor="style-toggle" className={cn(isRealistic && "font-semibold")}>
                Realistic
              </Label>
            </div>
          )}
        </Section>

        {/* Basic parameters */}
        <Section title="Basic Parameters">
          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            <div className="space-y-2">
              <Label htmlFor="clip-skip" className="text-sm font-medium">
                Clip Skip
              </Label>
              <Input
                id="clip-skip"
                type="number"
                min={1}
                value={params.clipSkip}
                onChange={(e) => setParam("clipSkip", Number(e.target.value))}
                className="text-center text-sm"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="seed" className="text-sm font-medium">
                Seed
              </Label>
              <Input
                id="seed"
                type="number"
                min={-1}
                value={params.seed}
                onChange={(e) => setParam("seed", Number(e.target.value))}
                className="text-center text-sm"
              />
            </div>
          </div>
        </Section>

        {/* Sampling */}
        <Section title="Generation Parameters">
          <SliderField id="steps" label="Steps" value={params.steps} onChange={(v) => setParam("steps", v)} min={1} max={40} step={1} />
          <SliderField id="width" label="Width" value={params.width} onChange={(v) => setParam("width", v)} min={64} max={2048} step={8} />
          <SliderField id="height" label="Height" value={params.height} onChange={(v) => setParam("height", v)} min={64} max={2048} step={8} />
          <SliderField id="cfg-scale" label="CFG Scale" value={params.cfgScale} onChange={(v) => setParam("cfgScale", v)} min={0} max={20} step={0.5} />
          <SliderField
            id="denoising-strength"
            label="Denoising Strength"
            value={params.denoisingStrength}
            onChange={(v) => setParam("denoisingStrength", v)}
            min={0}
            max={1}
            step={0.05}
          />
        </Section>
      </div>
    </ScrollArea>
  );
}
