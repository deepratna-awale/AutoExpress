"use client";

import { AlertTriangle, Loader2, Play, RefreshCw } from "lucide-react";

import { useAutoExpress } from "@/lib/store";
import { expressionName } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { JobNotes } from "@/components/job-notes";

interface DropZoneInputsPanelProps {
  onViewImages: () => void;
}

export function DropZoneInputsPanel({ onViewImages }: DropZoneInputsPanelProps) {
  const { file, params, setParam, outputDirectory, setOutputDirectory, generating, job, generate, interrupt, loadImages } =
    useAutoExpress();
  const progress = generating && job ? job.progress : null;

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

      {progress && progress.total > 0 && (
        <div className="space-y-1" aria-live="polite">
          <Progress value={Math.round(((progress.done + (progress.step?.fraction ?? 0)) / progress.total) * 100)} />
          <p className="truncate text-xs text-muted-foreground">
            {job?.status === "queued"
              ? "Queued..."
              : `${progress.done} of ${progress.total}${progress.current ? ` · ${expressionName(progress.current)}` : ""}${
                  progress.step?.eta ? ` · ~${Math.ceil(progress.step.eta)}s` : ""
                }`}
          </p>
        </div>
      )}

      <JobNotes />

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
