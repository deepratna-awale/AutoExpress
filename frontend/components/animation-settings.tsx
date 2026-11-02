"use client";

import { Loader2 } from "lucide-react";

import { useAutoExpress } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

const FORMAT_LABELS: Record<string, string> = { webp: "WebP", apng: "APNG", gif: "GIF" };

/** Animate every expression into a looping clip, with an idle (neutral) motion that fits the character. */
export function AnimationSettings() {
  const {
    animationInfo,
    animate,
    setAnimate,
    character,
    idleMotion,
    setIdleMotion,
    suggestIdleMotion,
    suggestingIdle,
    animationFormats,
    setAnimationFormats,
    animationFast,
    setAnimationFast,
    imageDataUrl,
    generating,
  } = useAutoExpress();
  if (!animationInfo) return null;
  const on = animate && animationInfo.available;

  const toggleFormat = (format: string) => {
    const next = animationFormats.includes(format) ? animationFormats.filter((f) => f !== format) : [...animationFormats, format];
    if (next.length) setAnimationFormats(next);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <Switch id="animate-toggle" checked={on} onCheckedChange={setAnimate} disabled={!animationInfo.available || generating} />
        <Label htmlFor="animate-toggle">Animate sprites</Label>
      </div>
      <p className="text-xs text-muted-foreground">
        {animationInfo.available
          ? "Turns each expression into a short looping clip with Wan 2.2 image to video. Neutral becomes the character's idle animation. With Remove background on, the clips are transparent too."
          : "Needs a ComfyUI backend with Wan 2.2 image to video."}
      </p>

      {on && (
        <div className="space-y-2 rounded-md border p-2">
          <Label htmlFor="idle-motion" className="text-xs">
            Idle animation{character ? ` for ${character.name}` : ""}
          </Label>
          <Textarea
            id="idle-motion"
            value={idleMotion}
            onChange={(e) => setIdleMotion(e.target.value)}
            placeholder={
              character
                ? "Filled in from the character card."
                : "How the character idles, e.g. sways playfully and winks. Left empty, it comes from the character card."
            }
            className="min-h-[72px] text-xs"
            disabled={generating}
          />
          <div className="flex flex-wrap gap-1">
            {(
              [
                ["card", "From the card"],
                ["web", "Card + wiki"],
                ["llm", "Ask the LLM"],
              ] as const
            ).map(([source, label]) => (
              <Button
                key={source}
                type="button"
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                disabled={!imageDataUrl || suggestingIdle || generating || (source === "llm" && !animationInfo.llm.configured)}
                title={source === "llm" && !animationInfo.llm.configured ? "Set AUTOEXPRESS_LLM_URL (any OpenAI compatible endpoint) to use an LLM." : undefined}
                onClick={() => suggestIdleMotion(source)}
              >
                {label}
              </Button>
            ))}
            {suggestingIdle && <Loader2 className="h-4 w-4 animate-spin self-center" />}
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span className="text-muted-foreground">Save as</span>
            {animationInfo.formats.map((format) => (
              <label key={format} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={animationFormats.includes(format)}
                  onChange={() => toggleFormat(format)}
                  disabled={generating}
                />
                {FORMAT_LABELS[format] ?? format}
              </label>
            ))}
          </div>
          <label className="flex items-center gap-1 text-xs" title="Wan 2.2's 4-step LoRAs: about 6x faster, but the mouth may move as if talking.">
            <input type="checkbox" checked={animationFast} onChange={(e) => setAnimationFast(e.target.checked)} disabled={generating} />
            Fast (4 steps, lower quality)
          </label>
          <p className="text-xs text-muted-foreground">{animationInfo.vram_note}</p>
        </div>
      )}
    </div>
  );
}
