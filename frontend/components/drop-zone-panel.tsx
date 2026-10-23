"use client";

import { useCallback, useEffect, useState } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { AlertCircle, CheckCircle2, FileText, ImageUp, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { useAutoExpress } from "@/lib/store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";

// The Flask /upload route accepts these
const ACCEPTED_IMAGE_TYPES = {
  "image/png": [".png"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/gif": [".gif"],
};
const MAX_SIZE = 25 * 1024 * 1024;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  const mb = bytes / 1024 / 1024;
  return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`;
}

function rejectionMessage(rejection: FileRejection) {
  const error = rejection.errors[0];
  switch (error?.code) {
    case "file-invalid-type":
      return `${rejection.file.name} isn't a PNG, JPG or GIF.`;
    case "file-too-large":
      return `${rejection.file.name} is ${formatBytes(rejection.file.size)}; the limit is ${formatBytes(MAX_SIZE)}.`;
    case "too-many-files":
      return "Drop one image at a time.";
    default:
      return error?.message ?? "That file can't be used.";
  }
}

function isTyping(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA"].includes(target.tagName));
}

export function DropZonePanel() {
  const { file, imageDataUrl, rawMetadata, uploading, setFile } = useAutoExpress();
  const [error, setError] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null);
  const [metadataOpen, setMetadataOpen] = useState(false);

  const accept = useCallback(
    (next: File) => {
      setError(null);
      setDimensions(null);
      setFile(next);
    },
    [setFile]
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject, open } = useDropzone({
    accept: ACCEPTED_IMAGE_TYPES,
    maxSize: MAX_SIZE,
    multiple: false,
    // With an image loaded, clicking the preview shouldn't open the file picker; Replace does.
    noClick: !!file,
    onDropAccepted: (files) => accept(files[0]),
    onDropRejected: (rejections) => setError(rejectionMessage(rejections[0])),
  });

  // Paste an image from the clipboard anywhere outside a text field
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (isTyping(event.target)) return;
      const item = Array.from(event.clipboardData?.files ?? []).find((f) => f.type.startsWith("image/"));
      if (!item) return;
      event.preventDefault();
      if (!Object.keys(ACCEPTED_IMAGE_TYPES).includes(item.type)) {
        setError("Pasted image isn't a PNG, JPG or GIF.");
        return;
      }
      if (item.size > MAX_SIZE) {
        setError(`Pasted image is ${formatBytes(item.size)}; the limit is ${formatBytes(MAX_SIZE)}.`);
        return;
      }
      const extension = item.type.split("/")[1].replace("jpeg", "jpg");
      const named = item.name && item.name !== "image.png" ? item : new File([item], `Pasted_Character.${extension}`, { type: item.type });
      accept(named);
      toast.success("Image pasted");
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [accept]);

  const dragState = isDragReject ? "reject" : isDragActive ? "active" : "idle";

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 p-2 sm:p-4">
      <div
        {...getRootProps({
          "aria-label": file ? `Input image ${file.name}. Drop another image to replace it.` : "Upload an input image",
        })}
        className={cn(
          "group relative flex min-h-[220px] flex-1 cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border-2 border-dashed transition-colors outline-none",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          file ? "cursor-default border-solid border-border bg-muted/30" : "border-muted-foreground/30 hover:border-primary/60 hover:bg-primary/5",
          dragState === "active" && "border-primary bg-primary/10",
          dragState === "reject" && "border-destructive bg-destructive/10",
          error && !file && dragState === "idle" && "border-destructive/60"
        )}
      >
        <input {...getInputProps()} />

        {imageDataUrl && file ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={imageDataUrl}
              alt={file.name}
              onLoad={(e) => setDimensions({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })}
              className="absolute inset-0 h-full w-full object-contain p-2"
            />
            {uploading && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background/60 backdrop-blur-[1px]">
                <Loader2 className="h-6 w-6 animate-spin" />
                <p className="text-sm">Reading generation data...</p>
              </div>
            )}
          </>
        ) : (
          <div className="flex max-w-sm flex-col items-center gap-3 px-6 text-center">
            <div
              className={cn(
                "flex h-14 w-14 items-center justify-center rounded-full bg-muted transition-colors",
                dragState === "active" && "bg-primary/15 text-primary",
                dragState === "reject" && "bg-destructive/15 text-destructive"
              )}
            >
              {dragState === "reject" ? <AlertCircle className="h-6 w-6" /> : <ImageUp className="h-6 w-6" />}
            </div>
            <div className="space-y-1">
              <p className="text-base font-medium">
                {dragState === "active"
                  ? "Release to upload"
                  : dragState === "reject"
                    ? "This file type isn't supported"
                    : "Drop your character image here"}
              </p>
              <p className="text-sm text-muted-foreground">
                or <span className="font-medium text-primary underline-offset-4 group-hover:underline">browse</span>, or paste
                with <kbd className="rounded border bg-muted px-1 font-mono text-xs">Ctrl</kbd>/
                <kbd className="rounded border bg-muted px-1 font-mono text-xs">⌘</kbd>+
                <kbd className="rounded border bg-muted px-1 font-mono text-xs">V</kbd>
              </p>
            </div>
            <p className="text-xs text-muted-foreground">PNG, JPG or GIF, up to {formatBytes(MAX_SIZE)}. Generation settings are read from the image.</p>
          </div>
        )}

        {/* Drop-to-replace overlay while an image is loaded */}
        {file && dragState !== "idle" && (
          <div
            className={cn(
              "absolute inset-0 flex items-center justify-center rounded-xl text-sm font-medium",
              dragState === "active" ? "bg-primary/20 text-primary" : "bg-destructive/20 text-destructive"
            )}
          >
            {dragState === "active" ? "Release to replace" : "This file type isn't supported"}
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="flex items-center gap-1.5 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </p>
      )}

      {file && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border bg-card px-3 py-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium" title={file.name}>
              {file.name}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatBytes(file.size)}
              {dimensions && ` · ${dimensions.width}×${dimensions.height}`}
            </p>
          </div>
          {!uploading &&
            (rawMetadata ? (
              <Badge variant="secondary" className="gap-1">
                <CheckCircle2 className="h-3 w-3 text-green-600 dark:text-green-400" />
                Settings found
              </Badge>
            ) : (
              <Badge variant="outline" className="text-muted-foreground">
                No generation data
              </Badge>
            ))}
          <div className="flex items-center gap-1">
            {rawMetadata && (
              <Button variant="ghost" size="sm" onClick={() => setMetadataOpen(true)}>
                <FileText className="h-4 w-4" />
                <span className="hidden sm:inline">Data</span>
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={open}>
              <RefreshCw className="h-4 w-4" />
              <span className="hidden sm:inline">Replace</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => {
                setError(null);
                setDimensions(null);
                setFile(null);
              }}
            >
              <Trash2 className="h-4 w-4" />
              <span className="hidden sm:inline">Remove</span>
            </Button>
          </div>
        </div>
      )}

      {!file && (
        <Button variant="outline" size="sm" className="self-center sm:hidden" onClick={open}>
          <Upload className="h-4 w-4" />
          Choose image
        </Button>
      )}

      <Dialog open={metadataOpen} onOpenChange={setMetadataOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Generation data</DialogTitle>
            <DialogDescription>
              Read from {file?.name}. Use it to fill in anything that wasn&apos;t detected.
            </DialogDescription>
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
