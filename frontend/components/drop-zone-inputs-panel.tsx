"use client";

import { AlertTriangle, Loader2, Play, RefreshCw } from "lucide-react";

import { useAutoExpress } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface DropZoneInputsPanelProps {
  onViewImages: () => void;
}

export function DropZoneInputsPanel({ onViewImages }: DropZoneInputsPanelProps) {
  const { file, params, setParam, outputDirectory, setOutputDirectory, generating, generate, interrupt, loadImages } =
    useAutoExpress();

  const handleLoadImages = () => {
    loadImages();
    onViewImages();
  };

  const handleGenerate = () => {
    onViewImages();
    generate();
  };

  return (
    <div className="flex h-full min-h-0 flex-col space-y-3 bg-background p-2 sm:space-y-4 sm:p-4">
      <div className="flex gap-2">
        <Button onClick={handleGenerate} className="flex-1 text-sm" disabled={!file || generating}>
          {generating ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin sm:mr-2" />
          ) : (
            <Play className="mr-1 h-4 w-4 sm:mr-2" />
          )}
          {generating ? "Generating..." : "Generate"}
        </Button>
        <Button onClick={interrupt} variant="destructive" className="text-sm">
          <AlertTriangle className="mr-1 h-4 w-4 sm:mr-2" />
          Interrupt
        </Button>
      </div>

      <Textarea
        placeholder="Prompt"
        value={params.prompt}
        onChange={(e) => setParam("prompt", e.target.value)}
        className="min-h-[60px] flex-1 resize-none border-green-600/60 text-sm"
        aria-label="Prompt"
      />

      <Textarea
        placeholder="Negative prompt..."
        value={params.negativePrompt}
        onChange={(e) => setParam("negativePrompt", e.target.value)}
        className="min-h-[60px] flex-1 resize-none border-red-600/60 text-sm"
        aria-label="Negative prompt"
      />

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          handleLoadImages();
        }}
      >
        <Input
          placeholder="Character_Name"
          value={outputDirectory}
          onChange={(e) => setOutputDirectory(e.target.value)}
          className="text-sm"
          aria-label="Output folder name"
          title="Expressions are saved to Output/<this name>"
        />
        <Button type="submit" variant="outline" size="icon" className="shrink-0" aria-label="Load images">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
