"use client";

import { useEffect, useState } from "react";
import { ChevronRight, KeyRound, Link, Loader2, SlidersHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";
import { AUTO_FAMILY, useAutoExpress, type ConnectionStatus } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Combobox } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { LoraSelect } from "@/components/lora-select";
import { SliderField } from "@/components/slider-field";
import { WebUISetup } from "@/components/webui-setup";
import { ExpressionSettingsDialog } from "@/components/expression-settings-dialog";
import { AUTO_BACKEND, hasLogin, type LoginInput } from "@/lib/api";
import { FAMILY_DEFAULTS, detectFamily, type Adjustment } from "@/lib/model-defaults";
import { INPAINT_METHOD } from "@/lib/api";

function AdjustmentNote({ adjustment }: { adjustment?: Adjustment }) {
  if (!adjustment) return null;
  return (
    <p className="text-xs text-amber-600 dark:text-amber-400" role="status">
      <span className="font-medium">{adjustment.from}</span> {adjustment.reason}.
    </p>
  );
}

/** Login fields the user changed since the last connect. Secrets are dropped from memory once sent. */
type LoginDraft = Partial<Record<"username" | "password" | "token" | "headers", string>>;

function draftToInput(draft: LoginDraft): LoginInput | undefined {
  const input: LoginInput = {};
  if (draft.username !== undefined) input.username = draft.username.trim();
  // Empty secret fields mean "keep the saved one"; Forget login clears them.
  if (draft.password) input.password = draft.password;
  if (draft.token) input.token = draft.token.trim();
  if (draft.headers?.trim()) input.headers = draft.headers;
  return Object.keys(input).length ? input : undefined;
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
  const [perExpressionOpen, setPerExpressionOpen] = useState(false);
  const {
    backends,
    backend,
    setBackend,
    apiUrl,
    setApiUrl,
    connection,
    connect,
    login,
    loginNeeded,
    connectedBackend,
    options,
    editMethods,
    vramNote,
    method,
    setMethod,
    photoStyle,
    setPhotoStyle,
    pose,
    setPose,
    posesAvailable,
    intensity,
    setIntensity,
    familyDefaults,
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
  const autoDetect = backend === AUTO_BACKEND;
  const urlLabel = currentBackend && !autoDetect ? `${currentBackend.name} URL` : "WebUI URL";

  const [loginOpen, setLoginOpen] = useState(false);
  const [draft, setDraft] = useState<LoginDraft>({});
  const saved = hasLogin(login);
  useEffect(() => {
    if (loginNeeded) setLoginOpen(true);
  }, [loginNeeded]);
  const editDraft = (key: keyof LoginDraft) => (e: { target: { value: string } }) =>
    setDraft((current) => ({ ...current, [key]: e.target.value }));
  const submit = async (input?: LoginInput) => {
    // Keep what was typed if the server refused it, so it can be corrected.
    if (await connect(input)) setDraft({});
  };

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
              {urlLabel}
            </Label>
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                submit(draftToInput(draft));
              }}
            >
              <div className="flex gap-2">
                <Input
                  id="api-url"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  placeholder="http://host:7860 or https://your-pod-7860.proxy.runpod.net"
                  className="flex-1 text-sm"
                  autoComplete="off"
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
              </div>

              <Collapsible open={loginOpen} onOpenChange={setLoginOpen}>
                <CollapsibleTrigger
                  type="button"
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                >
                  <ChevronRight className={cn("h-3 w-3 transition-transform", loginOpen && "rotate-90")} />
                  <KeyRound className="h-3 w-3" />
                  Login
                  {saved && <span className="text-green-600 dark:text-green-400">(set)</span>}
                  {loginNeeded && <span className="text-amber-600 dark:text-amber-400">(needed)</span>}
                </CollapsibleTrigger>
                <CollapsibleContent className="space-y-2 pt-2">
                  <p className="text-xs text-muted-foreground">
                    For a WebUI with a login (A1111/Forge <code>--api-auth</code>, SwarmUI or InvokeAI accounts) or behind a
                    login proxy. It is only sent to this address, kept on the AutoExpress server, and never shown again.
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label htmlFor="login-username" className="text-xs">
                        Username or email
                      </Label>
                      <Input
                        id="login-username"
                        value={draft.username ?? login?.username ?? ""}
                        onChange={editDraft("username")}
                        autoComplete="username"
                        className="text-sm"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="login-password" className="text-xs">
                        Password
                      </Label>
                      <Input
                        id="login-password"
                        type="password"
                        value={draft.password ?? ""}
                        onChange={editDraft("password")}
                        placeholder={login?.password ? "Saved" : ""}
                        autoComplete="current-password"
                        className="text-sm"
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="login-token" className="text-xs">
                      Token
                    </Label>
                    <Input
                      id="login-token"
                      type="password"
                      value={draft.token ?? ""}
                      onChange={editDraft("token")}
                      placeholder={login?.token ? "Saved (empty keeps it)" : "Bearer token, or SwarmUI's swarm_token"}
                      autoComplete="off"
                      className="text-sm"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="login-headers" className="text-xs">
                      Extra headers
                    </Label>
                    <Textarea
                      id="login-headers"
                      value={draft.headers ?? ""}
                      onChange={editDraft("headers")}
                      placeholder={
                        login?.headers.length
                          ? `Saved: ${login.headers.join(", ")}. Typing here replaces them.`
                          : "One per line, e.g.\nCF-Access-Client-Id: ...\nCF-Access-Client-Secret: ..."
                      }
                      autoComplete="off"
                      spellCheck={false}
                      rows={2}
                      className="font-mono text-xs"
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button type="submit" size="sm" disabled={connection === "connecting"}>
                      Connect with login
                    </Button>
                    {saved && (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={connection === "connecting"}
                        onClick={() => submit({ forget_login: true })}
                      >
                        Forget login
                      </Button>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </form>
            {autoDetect && connectedBackend && connected && (
              <p className="text-xs text-muted-foreground" role="status">
                Detected <span className="font-medium text-foreground">{connectedBackend.name}</span>
              </p>
            )}
          </div>

          <WebUISetup />
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

          {editMethods && (
            <div className="space-y-2">
              <Label htmlFor="edit-method" className="text-sm font-medium">
                Method
              </Label>
              <Select value={method} onValueChange={setMethod}>
                <SelectTrigger id="edit-method" className="w-full">
                  <SelectValue placeholder="Face inpainting" />
                </SelectTrigger>
                <SelectContent>
                  {editMethods.map((m) => (
                    <SelectItem key={m.id} value={m.id} disabled={!m.available} title={m.description}>
                      {m.available ? m.name : `${m.name} (ComfyUI only)`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {method !== INPAINT_METHOD && (
                <>
                  <div className="flex items-center justify-center gap-3 text-sm">
                    <Label htmlFor="edit-style-toggle" className={cn(!photoStyle && "font-semibold")}>
                      Illustration
                    </Label>
                    <Switch id="edit-style-toggle" checked={photoStyle} onCheckedChange={setPhotoStyle} />
                    <Label htmlFor="edit-style-toggle" className={cn(photoStyle && "font-semibold")}>
                      Photo
                    </Label>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {editMethods.find((m) => m.id === method)?.description} {vramNote}
                  </p>
                </>
              )}
            </div>
          )}

          {editMethods && (
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-sm">
                <Switch id="pose-toggle" checked={pose && posesAvailable} onCheckedChange={setPose} disabled={!posesAvailable} />
                <Label htmlFor="pose-toggle">Change pose too</Label>
              </div>
              <p className="text-xs text-muted-foreground">
                {posesAvailable
                  ? "Adds a small sprite gesture to each expression (hands on the hips for anger, hands behind the back for curiosity) from the current pose. The outfit and background stay as they are."
                  : "Needs Qwen-Image-Edit on a ComfyUI backend."}
              </p>
            </div>
          )}

          <div className="space-y-1">
            <SliderField
              id="expression-intensity"
              label="Expression intensity"
              value={intensity ?? familyDefaults?.intensity ?? 0.5}
              onChange={(v) => setIntensity(Math.min(Math.max(Math.round(v * 100) / 100, 0), 1))}
              min={0}
              max={1}
              step={0.05}
            />
            <p className="text-xs text-muted-foreground">
              {intensity === null
                ? `Default for ${familyDefaults?.family ?? "this model"}. Realistic models start low; strong expressions look uncanny on real faces.`
                : "Custom. "}
              {intensity !== null && (
                <button type="button" className="underline" onClick={() => setIntensity(null)}>
                  Use the model default ({familyDefaults?.intensity ?? 0.5})
                </button>
              )}
            </p>
          </div>

          {method !== INPAINT_METHOD ? null : families ? (
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

        <button
          type="button"
          onClick={() => setPerExpressionOpen(true)}
          className="flex items-center gap-1.5 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          Advanced: per-expression prompts and settings
        </button>
        <ExpressionSettingsDialog open={perExpressionOpen} onOpenChange={setPerExpressionOpen} />
      </div>
    </ScrollArea>
  );
}
