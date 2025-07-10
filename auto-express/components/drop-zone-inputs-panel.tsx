"use client";

import { useCallback } from "react";
import { Play, AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

interface DropZoneInputsPanelProps {
  onViewImages: () => void;
  selectedFiles: File[];
  setSelectedFiles: (files: File[]) => void;
  prompt: string;
  setPrompt: (prompt: string) => void;
  negativePrompt: string;
  setNegativePrompt: (negativePrompt: string) => void;
  outputDirectory: string;
  setOutputDirectory: (directory: string) => void;
}

export function DropZoneInputsPanel({ 
  onViewImages,
  selectedFiles,
  setSelectedFiles: _, // eslint-disable-line @typescript-eslint/no-unused-vars
  prompt,
  setPrompt,
  negativePrompt,
  setNegativePrompt,
  outputDirectory,
  setOutputDirectory
}: DropZoneInputsPanelProps) {

  const handleGenerate = useCallback(() => {
    console.log("Generate clicked");
    // TODO: Add generation logic here
  }, []);

  const handleInterrupt = useCallback(() => {
    console.log("Interrupt clicked");
    // TODO: Add interrupt logic here
  }, []);

  const handleLoadImages = useCallback(() => {
    console.log("Load images clicked");
    onViewImages();
  }, [onViewImages]);

  const handleKeyPress = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleLoadImages();
    }
  }, [handleLoadImages]);

  return (
    <div className="h-full p-2 sm:p-4 flex flex-col space-y-3 sm:space-y-4 min-h-0 bg-background">
      {/* Action Buttons */}
      <div className="flex gap-2">
        <Button 
          onClick={handleGenerate} 
          className="flex-1 text-sm"
          disabled={selectedFiles.length === 0}
        >
          <Play className="h-3 w-3 sm:h-4 sm:w-4 mr-1 sm:mr-2" />
          <span className="hidden xs:inline">
            {selectedFiles.length === 0 
              ? "Generate" 
              : selectedFiles.length === 1 
              ? "Generate" 
              : `Generate ${selectedFiles.length}`
            }
          </span>
          <span className="xs:hidden">Gen</span>
        </Button>
        <Button onClick={handleInterrupt} variant="destructive" className="text-sm">
          <AlertTriangle className="h-3 w-3 sm:h-4 sm:w-4 mr-1 sm:mr-2" />
          <span className="hidden xs:inline">Interrupt</span>
          <span className="xs:hidden">Stop</span>
        </Button>
      </div>

      {/* Prompt Textarea */}
      <div className="flex-1 min-h-0">
        <Textarea
          placeholder="Prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          className="h-full resize-none text-sm"
          aria-label="Enter your generation prompt"
        />
      </div>

      {/* Negative Prompt Textarea */}
      <div className="flex-1 min-h-0">
        <Textarea
          placeholder="Negative prompt..."
          value={negativePrompt}
          onChange={(e) => setNegativePrompt(e.target.value)}
          className="h-full resize-none text-sm"
          aria-label="Enter your negative prompt"
        />
      </div>

      {/* Output Directory */}
      <div className="flex gap-2">
        <Input
          placeholder="Character_Name"
          value={outputDirectory}
          onChange={(e) => setOutputDirectory(e.target.value)}
          onKeyPress={handleKeyPress}
          className="text-sm"
          aria-label="Output directory name"
        />
        <Button 
          onClick={handleLoadImages} 
          variant="outline" 
          size="icon" 
          className="shrink-0"
          aria-label="Load images"
        >
          <RefreshCw className="h-3 w-3 sm:h-4 sm:w-4" />
        </Button>
      </div>
    </div>
  );
}
