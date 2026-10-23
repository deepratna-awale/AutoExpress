"use client";

import { useState } from "react";
import { AlertTriangle, ExternalLink, X } from "lucide-react";

import type { JobNote } from "@/lib/api";
import { useAutoExpress } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";

function NoteRow({ note }: { note: JobNote }) {
  return (
    <li className="space-y-1 py-3">
      <p className="text-sm font-medium">{note.title || note.name}</p>
      <p className="text-xs text-muted-foreground">
        {note.file_name}
        {note.size_mb ? ` · ${note.size_mb.toFixed(note.size_mb < 10 ? 1 : 0)} MB` : ""}
      </p>
      {note.message && <p className="text-sm">{note.message}</p>}
      {note.url && (
        <a
          href={note.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
        >
          Download page
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </li>
  );
}

/** Notes from the last finished run, such as expression LoRAs the WebUI lacks. */
export function JobNotes() {
  const { job } = useAutoExpress();
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const notes = job?.notes ?? [];
  if (!job || job.status === "queued" || job.status === "running") return null;
  if (notes.length === 0 || dismissed === job.id) return null;

  const loras = notes.filter((note) => note.kind === "missing_lora").length;
  const summary =
    loras === notes.length
      ? `${loras} expression ${loras === 1 ? "LoRA" : "LoRAs"} couldn't be installed`
      : `${notes.length} ${notes.length === 1 ? "note" : "notes"} from this run`;

  return (
    <>
      <div
        className="flex items-center gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-800 dark:text-amber-300"
        role="status"
      >
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate">{summary}</span>
        <button type="button" className="shrink-0 font-medium underline-offset-4 hover:underline" onClick={() => setOpen(true)}>
          Details
        </button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0"
          aria-label="Dismiss"
          onClick={() => setDismissed(job.id)}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Missing expression LoRAs</DialogTitle>
            <DialogDescription>
              The expressions were generated without these. Download each into the WebUI&apos;s LoRA folder, refresh its
              LoRA list, then generate again.
            </DialogDescription>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh]">
            <ul className="divide-y">
              {notes.map((note, i) => (
                <NoteRow key={`${note.name}-${i}`} note={note} />
              ))}
            </ul>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  );
}
