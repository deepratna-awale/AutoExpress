"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Loader2, Search, Upload, X } from "lucide-react";

import {
  api,
  errorMessage,
  ApiError,
  type CharacterLoraResult,
  type Job,
  type Live2DInfo,
  type Live2DPictureReport,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";

const MAX_PICTURES = 8;
const RESOLUTIONS = [1024, 1280, 1536, 2048];

interface Picture {
  name: string;
  dataUrl: string;
}

function readFile(file: File): Promise<Picture> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, dataUrl: String(reader.result) });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function messageOf(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return errorMessage(error) || (error instanceof Error ? error.message : String(error));
}

/** Live2D model kit: pictures in, a layered Cubism-ready PSD (plus expressions for SillyTavern) out. */
export function Live2DDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [info, setInfo] = useState<Live2DInfo | null>(null);
  const [pictures, setPictures] = useState<Picture[]>([]);
  const [reports, setReports] = useState<Live2DPictureReport[]>([]);
  const [best, setBest] = useState(0);
  const [chosen, setChosen] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [loras, setLoras] = useState<CharacterLoraResult[] | null>(null);
  const [lora, setLora] = useState<CharacterLoraResult | null>(null);
  const [resolution, setResolution] = useState(2048);
  const [lowVram, setLowVram] = useState(false);
  const [variants, setVariants] = useState(true);
  const [outfitLayers, setOutfitLayers] = useState(false);
  const [adultConfirmed, setAdultConfirmed] = useState(false);
  const [description, setDescription] = useState("");
  const [innerWear, setInnerWear] = useState("");
  const [outfitPrompt, setOutfitPrompt] = useState("");
  const [outerGarment, setOuterGarment] = useState("");
  const [usePromptData, setUsePromptData] = useState(true);
  const [clothingSlots, setClothingSlots] = useState(true);
  const [expressionArt, setExpressionArt] = useState(true);
  const [neutralPose, setNeutralPose] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    api
      .live2d()
      .then((data) => {
        setInfo(data);
        if (data) setResolution(data.defaults.resolution);
      })
      .catch((e) => setError(messageOf(e)));
  }, [open]);

  // Follow the running job.
  useEffect(() => {
    if (!job || ["completed", "failed", "cancelled"].includes(job.status)) return;
    const timer = setTimeout(() => {
      api.job(job.id).then(setJob).catch((e) => setError(messageOf(e)));
    }, 2000);
    return () => clearTimeout(timer);
  }, [job]);

  const addFiles = useCallback(
    async (files: FileList | File[]) => {
      setError(null);
      const images = Array.from(files).filter((file) => file.type.startsWith("image/"));
      const added = await Promise.all(images.map(readFile));
      const next = [...pictures, ...added].slice(0, MAX_PICTURES);
      setPictures(next);
      setChosen(null);
      if (!name && added[0]) setName(added[0].name.replace(/\.[^.]+$/, ""));
      if (!next.length) return;
      setBusy("Checking the pictures");
      try {
        const result = await api.live2dCheck(next.map((p) => p.dataUrl));
        setReports(result.reports);
        setBest(result.best);
      } catch (e) {
        setError(messageOf(e));
      } finally {
        setBusy(null);
      }
    },
    [pictures, name]
  );

  const removePicture = (index: number) => {
    const next = pictures.filter((_, i) => i !== index);
    setPictures(next);
    setReports(reports.filter((_, i) => i !== index));
    setChosen(null);
    setBest(0);
  };

  const findLora = async () => {
    if (!name.trim()) return;
    setBusy("Looking for a character LoRA on Civitai");
    setError(null);
    try {
      const result = await api.characterLora(name.trim());
      setLoras(result.results);
      setLora(result.results.find((r) => r.installed_name) ?? null);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(null);
    }
  };

  const build = async () => {
    setError(null);
    setBusy("Starting");
    try {
      const response = await api.buildLive2D({
        images: pictures.map((p) => p.dataUrl),
        name: name.trim() || "character",
        settings: {
          resolution,
          low_vram: lowVram,
          variants: variants ? "auto" : "none",
          outfit_layers: outfitLayers,
          adult_confirmed: outfitLayers && adultConfirmed,
          ...(outfitLayers && description.trim() ? { character_description: description.trim() } : {}),
          ...(outfitLayers && innerWear.trim() ? { inner_wear: innerWear.trim() } : {}),
          ...(outfitPrompt.trim() ? { outfit_prompt: outfitPrompt.trim() } : {}),
          ...(clothingSlots && outerGarment.trim() ? { outer_garment: outerGarment.trim() } : {}),
          use_prompt_data: usePromptData,
          clothing_slots: clothingSlots,
          expression_art: expressionArt,
          neutral_pose: neutralPose,
          ...(chosen !== null ? { base_index: chosen } : {}),
        },
        character_lora: lora ? { entry: lora.entry, installed_name: lora.installed_name } : null,
      });
      if (response.job) setJob(response.job);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(null);
    }
  };

  const running = job && !["completed", "failed", "cancelled"].includes(job.status);
  const kit = job?.live2d;
  const picked = chosen ?? best;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[95vh] overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Live2D model kit</DialogTitle>
          <DialogDescription>
            Split a character into the layers of a Live2D model: a Cubism-ready PSD with blink and mouth art, plus
            expressions for the SillyTavern Live2D extension.
          </DialogDescription>
        </DialogHeader>
        <ScrollArea className="max-h-[78vh] pr-3">
          <div className="space-y-5 pb-2">
            {info && !info.ready && (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <p className="font-medium">{info.message}</p>
                {info.fix?.commands?.length ? (
                  <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 text-xs">{info.fix.commands.join("\n")}</pre>
                ) : null}
                <p className="mt-2 text-xs text-muted-foreground">{info.vram_note}</p>
              </div>
            )}

            {/* Pictures */}
            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Pictures of the character (up to {MAX_PICTURES})</Label>
                <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()} disabled={pictures.length >= MAX_PICTURES}>
                  <Upload className="mr-2 h-4 w-4" /> Add
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={(e) => e.target.files && addFiles(e.target.files)}
                />
              </div>
              <div
                className="grid min-h-28 grid-cols-2 gap-3 rounded-md border border-dashed p-3 sm:grid-cols-4"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  addFiles(e.dataTransfer.files);
                }}
              >
                {pictures.length === 0 && (
                  <p className="col-span-full self-center text-center text-sm text-muted-foreground">Drop pictures here</p>
                )}
                {pictures.map((picture, index) => {
                  const report = reports[index];
                  return (
                    <button
                      type="button"
                      key={`${picture.name}-${index}`}
                      onClick={() => setChosen(index)}
                      className={`relative rounded-md border p-1 text-left ${index === picked ? "ring-2 ring-primary" : ""}`}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={picture.dataUrl} alt={picture.name} className="h-28 w-full rounded object-contain" />
                      <span
                        role="button"
                        tabIndex={0}
                        aria-label="Remove"
                        onClick={(e) => {
                          e.stopPropagation();
                          removePicture(index);
                        }}
                        className="absolute right-1 top-1 rounded bg-background/80 p-0.5"
                      >
                        <X className="h-3 w-3" />
                      </span>
                      {report && (
                        <span className="mt-1 block text-xs text-muted-foreground">
                          Score {report.score}
                          {index === picked ? " · used" : ""}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              {reports[picked] && (
                <ul className="space-y-1 text-sm">
                  {reports[picked].checks.map((check) => (
                    <li key={check.id} className="flex gap-2">
                      {check.ok ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
                      ) : (
                        <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${check.level === "error" ? "text-red-600" : "text-amber-600"}`} />
                      )}
                      <span>{check.message}</span>
                    </li>
                  ))}
                </ul>
              )}
              {info?.advice && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-muted-foreground">{info.advice.title}</summary>
                  <ul className="ml-5 mt-2 list-disc space-y-1">
                    {info.advice.best.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  <p className="mt-2 font-medium">Helps even more</p>
                  <ul className="ml-5 list-disc space-y-1">
                    {info.advice.extras.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  <p className="mt-2 font-medium">Avoid</p>
                  <ul className="ml-5 list-disc space-y-1">
                    {info.advice.avoid.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </details>
              )}
            </section>

            {/* Character and LoRA */}
            <section className="space-y-2">
              <Label htmlFor="live2d-name">Character name</Label>
              <div className="flex gap-2">
                <Input id="live2d-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Hinata Hyuga" />
                <Button variant="outline" onClick={findLora} disabled={!name.trim() || !!busy}>
                  <Search className="mr-2 h-4 w-4" /> Find LoRA
                </Button>
              </div>
              {loras && loras.length === 0 && (
                <p className="text-sm text-muted-foreground">No character LoRA found. The edits work from the pictures alone.</p>
              )}
              {loras && loras.length > 0 && (
                <ul className="space-y-2 text-sm">
                  {loras.map((result) => (
                    <li key={result.entry.name} className="flex items-start justify-between gap-2 rounded border p-2">
                      <div>
                        <a href={result.page} target="_blank" rel="noreferrer" className="font-medium underline-offset-4 hover:underline">
                          {result.entry.title}
                        </a>
                        <span className="ml-2 text-xs text-muted-foreground">{result.entry.base_model}</span>
                        <p className="text-xs text-muted-foreground">
                          {result.installed_name ? `On the WebUI as ${result.installed_name}` : result.install?.message}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant={lora?.entry.name === result.entry.name ? "default" : "outline"}
                        disabled={!result.installed_name}
                        onClick={() => setLora(lora?.entry.name === result.entry.name ? null : result)}
                      >
                        {lora?.entry.name === result.entry.name ? "Using" : "Use"}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Settings */}
            <section className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="live2d-resolution">Layer resolution</Label>
                <select
                  id="live2d-resolution"
                  value={resolution}
                  onChange={(e) => setResolution(Number(e.target.value))}
                  className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                >
                  {RESOLUTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value} px
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center justify-between gap-2 sm:flex-col sm:items-start">
                <Label htmlFor="live2d-variants">Draw blink and mouth art</Label>
                <Switch id="live2d-variants" checked={variants} onCheckedChange={setVariants} />
              </div>
              <div className="flex items-center justify-between gap-2 sm:flex-col sm:items-start">
                <Label htmlFor="live2d-neutral-pose">Neutral pose, full-body skeleton</Label>
                <Switch id="live2d-neutral-pose" checked={neutralPose} onCheckedChange={setNeutralPose} />
              </div>
              <div className="flex items-center justify-between gap-2 sm:flex-col sm:items-start">
                <Label htmlFor="live2d-expression-art">Angry brows, grin and tears</Label>
                <Switch id="live2d-expression-art" checked={expressionArt && variants} disabled={!variants} onCheckedChange={setExpressionArt} />
              </div>
              <div className="flex items-center justify-between gap-2 sm:flex-col sm:items-start">
                <Label htmlFor="live2d-lowvram">Low VRAM (8-12 GB)</Label>
                <Switch id="live2d-lowvram" checked={lowVram} onCheckedChange={setLowVram} />
              </div>
            </section>

            {/* Swappable clothing */}
            <section className="space-y-3 rounded-md border p-3">
              <div className="space-y-2">
                <Label htmlFor="live2d-outfit">Outfit (optional)</Label>
                <input
                  id="live2d-outfit"
                  value={outfitPrompt}
                  onChange={(e) => setOutfitPrompt(e.target.value)}
                  maxLength={300}
                  placeholder="Keep the picture's clothes, or e.g. a black blazer and a pleated skirt"
                  className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                />
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={clothingSlots} onChange={(e) => setClothingSlots(e.target.checked)} />
                  <span>Coat on its own layer, with a drawn half-off state (two more edits)</span>
                </label>
                {clothingSlots && (
                  <div className="space-y-1">
                    <Label htmlFor="live2d-outer">Outer garment (optional)</Label>
                    <input
                      id="live2d-outer"
                      value={outerGarment}
                      onChange={(e) => setOuterGarment(e.target.value)}
                      maxLength={60}
                      placeholder="e.g. dark green haori, or none. Empty: from the card, prompt or a vision model"
                      className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                    />
                  </div>
                )}
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={usePromptData} onChange={(e) => setUsePromptData(e.target.checked)} />
                  <span>Read the clothing from the picture&apos;s prompt data when a field is empty</span>
                </label>
              </div>
              <div className="flex items-center justify-between gap-2">
                <div>
                  <Label htmlFor="live2d-outfits">Swappable clothing</Label>
                  <p className="text-xs text-muted-foreground">
                    Body, inner wear (top and bottom) and outer clothes as separate layers the puppet can switch, one piece at a time
                    or all at once. Drawn adult characters only, never photos.
                  </p>
                </div>
                <Switch id="live2d-outfits" checked={outfitLayers} onCheckedChange={setOutfitLayers} />
              </div>
              {outfitLayers && (
                <div className="space-y-2">
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={adultConfirmed}
                      onChange={(e) => setAdultConfirmed(e.target.checked)}
                    />
                    <span>This character is an adult (18 or older) and the picture is a drawing, not a photo of a real person.</span>
                  </label>
                  <Label htmlFor="live2d-description">Character description (optional)</Label>
                  <textarea
                    id="live2d-description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                    maxLength={2000}
                    placeholder="Build, skin, anything the body layer should match"
                    className="w-full rounded-md border bg-background px-2 py-1 text-sm"
                  />
                  <Label htmlFor="live2d-inner">Inner wear (optional)</Label>
                  <input
                    id="live2d-inner"
                    value={innerWear}
                    onChange={(e) => setInnerWear(e.target.value)}
                    maxLength={200}
                    placeholder="From the prompt data, else matching lace lingerie"
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  />
                </div>
              )}
            </section>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex items-center gap-3">
              <Button onClick={build} disabled={!pictures.length || !!busy || !!running || (info !== null && !info.ready) || (outfitLayers && !adultConfirmed)}>
                {busy || running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Build the kit
              </Button>
              {running && job && (
                <Button variant="outline" onClick={() => api.cancelJob(job.id).then(() => api.job(job.id)).then(setJob)}>
                  Cancel
                </Button>
              )}
              {busy && <span className="text-sm text-muted-foreground">{busy}…</span>}
            </div>

            {job && running && (
              <div className="space-y-1">
                <Progress value={Math.round(job.progress.fraction * 100)} />
                <p className="text-xs text-muted-foreground">{job.progress.current ?? job.status}</p>
              </div>
            )}
            {job?.status === "failed" && <p className="text-sm text-red-600">{job.error?.message}</p>}

            {kit && (
              <section className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  {kit.puppet_zip && (
                    <Button asChild>
                      <a href={kit.puppet_zip} download>
                        <Download className="mr-2 h-4 w-4" /> Puppet (.zip)
                      </a>
                    </Button>
                  )}
                  {kit.puppet_preview && (
                    <Button asChild variant="outline">
                      <a href={kit.puppet_preview} target="_blank" rel="noreferrer">
                        Try the puppet
                      </a>
                    </Button>
                  )}
                  <Button asChild variant={kit.puppet_zip ? "outline" : "default"}>
                    <a href={kit.zip} download>
                      <Download className="mr-2 h-4 w-4" /> Kit (.zip)
                    </a>
                  </Button>
                  <Button asChild variant="outline">
                    <a href={kit.psd} download>
                      Cubism PSD
                    </a>
                  </Button>
                  <Button asChild variant="outline">
                    <a href={kit.seethrough_psd} download>
                      See-through PSD
                    </a>
                  </Button>
                </div>
                {kit.puppet_zip && (
                  <p className="text-sm text-muted-foreground">
                    The puppet plays right away in SillyTavern: unzip it into <code>assets/live2d</code> and pick its
                    .puppet.model.json in the Live2D extension (the AutoExpress extension must be installed too). The
                    kit is for making a full Live2D model in Cubism Editor.
                  </p>
                )}
                <p className="text-sm">
                  {kit.layers} layers in {kit.groups.length} parts: {kit.groups.join(", ")}.
                  {kit.switches.length ? ` Hidden for blinking and talking: ${kit.switches.map((s) => s.layer).join(", ")}.` : ""}
                </p>
                {[...kit.missing.map((m) => m.message), ...kit.notes].map((line) => (
                  <p key={line} className="flex gap-2 text-sm">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                    {line}
                  </p>
                ))}
                <div className="grid gap-3 sm:grid-cols-[1fr_2fr]">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={kit.preview} alt="Reassembled layers" className="w-full rounded border bg-[conic-gradient(#eee_25%,#fff_0_50%,#eee_0_75%,#fff_0)] bg-[length:16px_16px]" />
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={kit.sheet} alt="Every layer" className="w-full rounded border" />
                </div>
                <p className="text-xs text-muted-foreground">
                  Open the PSD in Live2D Cubism Editor to rig it (the README in the kit walks through it), or drop the See-through PSD into
                  StretchyStudio for an instant rig. After exporting from Cubism, add the 28 emotions with
                  <code className="mx-1 rounded bg-muted px-1">python -m autoexpress_core.live2d attach &lt;model folder&gt;</code>.
                </p>
              </section>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
