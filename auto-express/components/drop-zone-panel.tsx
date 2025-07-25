"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Image from "next/image";
import { Play, AlertTriangle, RefreshCw, Info, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Dropzone, DropzoneEmptyState } from "@/components/ui/shadcn-io/dropzone";
import type { SDMetadata } from "@/lib/metadata-parser";

// Types
interface DropZonePanelProps {
  onViewImages: () => void;
  showCarousel?: boolean;
  showInputs?: boolean;
  selectedFiles: File[];
  setSelectedFiles: (files: File[]) => void;
  prompt: string;
  setPrompt: (prompt: string) => void;
  negativePrompt: string;
  setNegativePrompt: (negativePrompt: string) => void;
  outputDirectory: string;
  setOutputDirectory: (directory: string) => void;
}

interface FileWithUrl extends File {
  url?: string;
}

// Constants
const ACCEPTED_IMAGE_TYPES = {
  "image/*": [".png", ".jpg", ".jpeg", ".gif", ".webp"]
};
const MAX_FILES = 1;

export function DropZonePanel({ 
  onViewImages, 
  showCarousel = false, 
  showInputs = true,
  selectedFiles,
  setSelectedFiles,
  prompt,
  setPrompt,
  negativePrompt,
  setNegativePrompt,
  outputDirectory,
  setOutputDirectory
}: DropZonePanelProps) {
  // Convert File[] to FileWithUrl[] for display and maintain URLs
  const [filesWithUrls, setFilesWithUrls] = useState<FileWithUrl[]>([]);
  const filesWithUrlsRef = useRef<FileWithUrl[]>([]);
  // Store raw metadata for tooltip display
  const [rawMetadata, setRawMetadata] = useState<SDMetadata | null>(null);

  // Sync selectedFiles with filesWithUrls and create URLs
  useEffect(() => {
    const currentFilesWithUrls = filesWithUrlsRef.current;
    
    // Clean up old URLs that are no longer needed
    const currentUrls = new Set(selectedFiles.map(f => f.name));
    currentFilesWithUrls.forEach(fileWithUrl => {
      if (!currentUrls.has(fileWithUrl.name) && fileWithUrl.url) {
        URL.revokeObjectURL(fileWithUrl.url);
      }
    });

    // Create new FileWithUrl array
    const newFilesWithUrls = selectedFiles.map(file => {
      // Try to find existing file with URL to avoid recreating
      const existingFile = currentFilesWithUrls.find(f => f.name === file.name && f.size === file.size);
      if (existingFile && existingFile.url) {
        return existingFile;
      }
      
      // Create new file with URL
      const fileWithUrl = file as FileWithUrl;
      fileWithUrl.url = URL.createObjectURL(file);
      return fileWithUrl;
    });

    filesWithUrlsRef.current = newFilesWithUrls;
    setFilesWithUrls(newFilesWithUrls);

    // Parse metadata from the first selected file
    if (selectedFiles.length > 0) {
      parseImageMetadata(selectedFiles[0]);
    } else {
      setRawMetadata(null);
    }
  }, [selectedFiles]); // Only depend on selectedFiles to avoid infinite loop

  // Cleanup function for object URLs to prevent memory leaks
  useEffect(() => {
    return () => {
      filesWithUrls.forEach(file => {
        if (file.url) {
          URL.revokeObjectURL(file.url);
        }
      });
    };
  }, [filesWithUrls]);

  const handleDrop = useCallback((acceptedFiles: File[]) => {
    setSelectedFiles(acceptedFiles);
  }, [setSelectedFiles]);

  // Parse metadata from image file
  const parseImageMetadata = useCallback(async (file: File) => {
    if (!file.type.startsWith('image/')) return;
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const response = await fetch('/api/parse-metadata', {
        method: 'POST',
        body: formData,
      });
      
      if (!response.ok) {
        throw new Error('Failed to parse metadata');
      }
      
      const result = await response.json();
      
      if (result.success) {
        // Set raw metadata for tooltip display
        if (result.rawMetadata) {
          setRawMetadata(result.rawMetadata);
        }
        
        // Update prompt and negative prompt if found in metadata
        if (result.updatedValues) {
          if (result.updatedValues.prompt) {
            setPrompt(result.updatedValues.prompt);
          }
          if (result.updatedValues.negativePrompt) {
            setNegativePrompt(result.updatedValues.negativePrompt);
          }
        }
      } else {
        setRawMetadata(null);
      }
    } catch (error) {
      console.error('Error parsing image metadata:', error);
      setRawMetadata(null);
    }
  }, [setPrompt, setNegativePrompt]);

  const handleRemoveFile = useCallback((index: number) => {
    const newFiles = selectedFiles.filter((_, i) => i !== index);
    setSelectedFiles(newFiles);
  }, [selectedFiles, setSelectedFiles]);

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

  const renderFileGrid = () => (
    <div className="w-full h-full flex items-center justify-center">
      {filesWithUrls.map((file, index) => (
        <div key={`${file.name}-${index}`} className="relative w-full h-full">
          <div
            onClick={(e) => {
              e.stopPropagation();
              handleRemoveFile(index);
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                e.stopPropagation();
                handleRemoveFile(index);
              }
            }}
            className="absolute top-2 right-2 z-10 h-8 w-8 p-0 rounded-full shadow-sm cursor-pointer flex items-center justify-center bg-gray border border-blue-400 hover:bg-gray-500 transition-colors"
            aria-label={`Remove ${file.name}`}
          >
            <X className="h-4 w-4 text-blue-300 hover:text-blue-500" />
          </div>
          <div className="relative w-full h-full">
            <Image
              src={file.url!}
              alt={file.name}
              fill
              className="object-contain rounded-lg"
              sizes="50vw"
            />
          </div>
          <p className="absolute bottom-2 left-2 right-2 text-xs bg-black/50 text-white px-2 py-1 rounded text-center truncate">
            {file.name}
          </p>
        </div>
      ))}
    </div>
  );

  const renderDropzoneContent = () => {
    if (filesWithUrls.length === 0) {
      return <DropzoneEmptyState />;
    }

    return (
      <div className="w-full h-full">
        {renderFileGrid()}
      </div>
    );
  };

  const renderInfoTooltip = () => (
    <div className="absolute bottom-1 right-1 sm:bottom-2 sm:right-2">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button id="info-button" variant="ghost" size="icon" className="h-5 w-5 sm:h-6 sm:w-6">
              <Info className="h-3 w-3 sm:h-4 sm:w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left" className="bg-muted max-w-md max-h-96 overflow-auto rounded-lg border-2xl">
            {rawMetadata ? (
              <div className="space-y-2">
                <p className="text-xs font-semibold">Raw Image Metadata:</p>
                <pre className="text-xs whitespace-pre-wrap break-words">
                  {JSON.stringify(rawMetadata, null, 2)}
                </pre>
              </div>
            ) : (
              <p className="max-w-xs text-xs sm:text-sm">
                Drop image and click on this icon or hover over the image to see the raw generation data. 
                This can help you fill in the missing parameters manually if not autodetected.
              </p>
            )}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );

  const renderActionButtons = () => (
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
  );

  // When carousel is visible, always use vertical layout (inputs below dropzone)
  // When carousel is hidden, use responsive layout (horizontal on large screens)
  const useVerticalLayout = showCarousel;

  // If showInputs is false, only render the dropzone
  if (!showInputs) {
    return (
      <div className="h-full p-2 sm:p-4 min-h-0">
        <Card className="relative h-full">
          <CardContent className="p-4 h-full">
            <Dropzone
              onDrop={handleDrop}
              accept={ACCEPTED_IMAGE_TYPES}
              maxFiles={MAX_FILES}
              className="w-full h-full min-h-[300px]"
            >
              {renderDropzoneContent()}
            </Dropzone>
            
            {renderInfoTooltip()}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className={`h-full flex ${useVerticalLayout ? 'flex-col' : 'flex-col lg:flex-row'} overflow-hidden`}>
      {/* Drop Zone - Takes full width when carousel is shown on small screens */}
      <div className={`${useVerticalLayout ? 'flex-1' : 'flex-1'} p-2 sm:p-4 min-h-0`}>
        <Card className="relative h-full">
          <CardContent className="p-4 h-full">
            <Dropzone
              onDrop={handleDrop}
              accept={ACCEPTED_IMAGE_TYPES}
              maxFiles={MAX_FILES}
              className="w-full h-full min-h-[300px]"
            >
              {renderDropzoneContent()}
            </Dropzone>
            
            {renderInfoTooltip()}
          </CardContent>
        </Card>
      </div>

      {/* Controls Panel - Goes below when carousel is shown on small screens */}
      <div className={`${useVerticalLayout ? 'w-full' : 'flex-1'} p-2 sm:p-4 flex flex-col space-y-3 sm:space-y-4 min-h-0`}>
        {/* Action Buttons */}
        {renderActionButtons()}

        {/* Prompt Textarea */}
        <div className="flex-1 min-h-0">
          <Textarea
            placeholder="Prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className="h-full min-h-[80px] resize-none text-sm"
            aria-label="Enter your generation prompt"
          />
        </div>

        {/* Negative Prompt Textarea */}
        <div className="flex-1 min-h-0">
          <Textarea
            placeholder="Negative prompt..."
            value={negativePrompt}
            onChange={(e) => setNegativePrompt(e.target.value)}
            className="h-full min-h-[80px] resize-none text-sm"
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
    </div>
  );
}
