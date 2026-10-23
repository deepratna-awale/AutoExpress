"use client";

import { useState } from "react";
import { AlertTriangle, Check, CheckCircle2, ChevronRight, Copy, ExternalLink, Loader2, RotateCw, XCircle } from "lucide-react";
import { toast } from "sonner";

import { CONNECTION_ITEM, type CapabilityFix, type CapabilityItem } from "@/lib/api";
import { useAutoExpress } from "@/lib/store";
import { cn, copyText } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

function CommandLine({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-start gap-1 rounded-md border bg-muted/60">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre px-2 py-1.5 font-mono text-xs">{command}</code>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        aria-label="Copy command"
        title="Copy"
        onClick={() =>
          copyText(command)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch((error) => toast.error(`Could not copy: ${error instanceof Error ? error.message : error}`))
        }
      >
        {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
}

function FixSteps({ fix }: { fix: CapabilityFix }) {
  return (
    <div className="space-y-2 pt-2 text-xs">
      {fix.steps.length > 0 && (
        <ol className="list-decimal space-y-1 pl-4 text-muted-foreground">
          {fix.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      )}
      {fix.commands.map((command, i) => (
        <CommandLine key={i} command={command} />
      ))}
      {fix.links.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1">
          {fix.links.map((link) => (
            <li key={link.url}>
              <a
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
              >
                {link.label}
                <ExternalLink className="h-3 w-3" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ItemIcon({ item }: { item: CapabilityItem }) {
  if (item.ok) return <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600 dark:text-green-400" aria-label="OK" />;
  if (item.required) return <XCircle className="h-4 w-4 shrink-0 text-destructive" aria-label="Missing" />;
  return <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-label="Recommended" />;
}

function ItemRow({ item }: { item: CapabilityItem }) {
  const missing = !item.ok;
  const [open, setOpen] = useState(missing && item.required);
  const label = (
    <span className="flex min-w-0 flex-1 flex-col">
      <span
        className={cn(
          "text-sm",
          missing && item.required && "text-destructive",
          missing && !item.required && "text-amber-700 dark:text-amber-400"
        )}
      >
        {item.label}
        {missing && !item.required && <span className="text-xs text-muted-foreground"> (optional)</span>}
      </span>
      {item.detail && <span className="text-xs text-muted-foreground">{item.detail}</span>}
    </span>
  );

  if (!missing || !item.fix) {
    return (
      <li className="flex items-start gap-2 py-1.5" data-key={item.key}>
        <ItemIcon item={item} />
        {label}
      </li>
    );
  }

  return (
    <li className="py-1.5" data-key={item.key}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-start gap-2 text-left">
          <ItemIcon item={item} />
          {label}
          <ChevronRight
            className={cn("mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
            aria-label={open ? "Hide fix" : "Show how to fix"}
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="pl-6">
          <FixSteps fix={item.fix} />
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}

/** Checklist of what the connected WebUI has and lacks, with steps to fix each gap. */
export function WebUISetup() {
  const { capabilities, checkingCapabilities, checkCapabilities, connection, connect } = useAutoExpress();
  if (!capabilities) return null;

  // A failed connect has nothing to re-check on the server; try connecting again instead.
  const connectionFailed = capabilities.items.some((item) => item.key === CONNECTION_ITEM);
  const busy = checkingCapabilities || connection === "connecting";

  const missingRequired = capabilities.items.filter((item) => !item.ok && item.required).length;
  const missingOptional = capabilities.items.filter((item) => !item.ok && !item.required).length;
  const summary = connectionFailed
    ? "Fix the connection, then retry"
    : missingRequired
    ? `${missingRequired} required ${missingRequired === 1 ? "item" : "items"} missing`
    : capabilities.ready
      ? missingOptional
        ? `Ready, ${missingOptional} optional ${missingOptional === 1 ? "item" : "items"} missing`
        : "Ready"
      : "Not ready";

  return (
    <div className="space-y-2 rounded-lg border p-3" aria-label={`${capabilities.name} setup`}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">
            {connectionFailed ? "Could not reach the WebUI" : `${capabilities.name} setup`}
          </p>
          <p
            className={cn(
              "text-xs",
              missingRequired || !capabilities.ready ? "text-destructive" : "text-green-600 dark:text-green-400"
            )}
            role="status"
          >
            {summary}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 shrink-0 gap-1 px-2 text-xs"
          onClick={connectionFailed ? connect : checkCapabilities}
          disabled={busy}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCw className="h-3.5 w-3.5" />}
          {connectionFailed ? "Retry" : "Re-check"}
        </Button>
      </div>
      {capabilities.error && <p className="text-xs text-destructive">{capabilities.error}</p>}
      {capabilities.items.length > 0 && (
        <ul className="divide-y">
          {capabilities.items.map((item) => (
            <ItemRow key={item.key} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}
