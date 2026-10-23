"use client";

import { useState } from "react";
import { Info, Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { useAutoExpress } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Dropzone, DropzoneEmptyState } from "@/components/ui/shadcn-io/dropzone";

// The Flask /upload route accepts these
const ACCEPTED_IMAGE_TYPES = {
  "image/png": [".png"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/gif": [".gif"],
};

export function DropZonePanel() {
  const { file, imageDataUrl, rawMetadata, uploading, setFile } = useAutoExpress();
  const [metadataOpen, setMetadataOpen] = useState(false);

  return (
    <div className="h-full min-h-0 p-2 sm:p-4">
      <Card className="relative h-full py-0">
        <CardContent className="h-full p-4">
          <Dropzone
            onDrop={(accepted) => accepted[0] && setFile(accepted[0])}
            onError={(error) => toast.error(error.message)}
            accept={ACCEPTED_IMAGE_TYPES}
            maxFiles={1}
            className="h-full min-h-[240px] w-full"
          >
            {imageDataUrl && file ? (
              <div className="relative h-full w-full">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imageDataUrl}
                  alt={file.name}
                  title={rawMetadata ?? undefined}
                  className="absolute inset-0 h-full w-full rounded-lg object-contain"
                />
                <p className="absolute bottom-2 left-2 right-2 truncate rounded bg-black/50 px-2 py-1 text-center text-xs text-white">
                  {file.name}
                </p>
                {uploading && (
                  <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-background/40">
                    <Loader2 className="h-6 w-6 animate-spin" />
                  </div>
                )}
              </div>
            ) : (
              <DropzoneEmptyState />
            )}
          </Dropzone>

          {file && (
            <Button
              variant="secondary"
              size="icon"
              className="absolute right-6 top-6 z-10 h-8 w-8 rounded-full shadow-sm"
              onClick={() => setFile(null)}
              aria-label={`Remove ${file.name}`}
            >
              <X className="h-4 w-4" />
            </Button>
          )}

          <div className="absolute bottom-1 right-1 sm:bottom-2 sm:right-2">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => rawMetadata && setMetadataOpen(true)}
                    aria-label="Show raw generation data"
                  >
                    <Info className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="left" className="max-w-xs text-xs">
                  {rawMetadata
                    ? "Click to see the raw generation data read from this image."
                    : "Drop an image, then click this icon or hover over the image to see its raw generation data. It helps you fill in parameters that weren't detected."}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </CardContent>
      </Card>

      <Dialog open={metadataOpen} onOpenChange={setMetadataOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Raw generation data</DialogTitle>
            <DialogDescription>{file?.name}</DialogDescription>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh]">
            <pre className="whitespace-pre-wrap break-words font-mono text-xs">{rawMetadata}</pre>
          </ScrollArea>
          <div className="flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => rawMetadata && navigator.clipboard.writeText(rawMetadata).then(() => toast.success("Copied"))}
            >
              Copy
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
