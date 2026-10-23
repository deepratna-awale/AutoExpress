"use client";

import * as React from "react";
import { Check, ChevronsUpDown, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SelectedLora } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

interface LoraSelectProps {
  available: string[];
  value: SelectedLora[];
  onChange: (value: SelectedLora[]) => void;
}

/** Pick any number of LoRAs and set a strength for each. */
export function LoraSelect({ available, value, onChange }: LoraSelectProps) {
  const [open, setOpen] = React.useState(false);
  const selected = new Set(value.map((lora) => lora.name));
  // LoRAs read from an image may not be in the WebUI's list; keep them selectable.
  const options = Array.from(new Set([...available, ...value.map((lora) => lora.name)]));

  const toggle = (name: string) => {
    if (selected.has(name)) {
      onChange(value.filter((lora) => lora.name !== name));
    } else {
      onChange([...value, { name, strength: 1 }]);
    }
  };

  const setStrength = (name: string, strength: number) => {
    onChange(value.map((lora) => (lora.name === name ? { ...lora, strength } : lora)));
  };

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between font-normal">
            <span className="truncate">
              {value.length === 0 ? "Select LoRA(s)" : `${value.length} LoRA${value.length > 1 ? "s" : ""} selected`}
            </span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-(--radix-popover-trigger-width) min-w-64 p-0" align="start">
          <Command>
            <CommandInput placeholder="Search LoRAs..." className="h-9" />
            <CommandList>
              <CommandEmpty>{available.length === 0 ? "Connect to a WebUI to list LoRAs." : "No LoRA found."}</CommandEmpty>
              <CommandGroup>
                {options.map((name) => (
                  <CommandItem key={name} value={name} onSelect={() => toggle(name)}>
                    <Check className={cn("mr-2 h-4 w-4", selected.has(name) ? "opacity-100" : "opacity-0")} />
                    <span className="truncate">{name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {value.length > 0 && (
        <ul className="space-y-1">
          {value.map((lora) => (
            <li key={lora.name} className="flex items-center gap-2 rounded-md border px-2 py-1">
              <span
                className={cn("flex-1 truncate text-xs", !available.includes(lora.name) && available.length > 0 && "text-destructive")}
                title={!available.includes(lora.name) && available.length > 0 ? "Not found on the connected WebUI" : lora.name}
              >
                {lora.name}
              </span>
              <Input
                type="number"
                step={0.05}
                value={lora.strength}
                onChange={(e) => {
                  const next = parseFloat(e.target.value);
                  if (Number.isFinite(next)) setStrength(lora.name, next);
                }}
                className="h-7 w-16 px-1 text-right font-mono text-xs"
                aria-label={`${lora.name} strength`}
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                onClick={() => toggle(lora.name)}
                aria-label={`Remove ${lora.name}`}
              >
                <X className="h-3 w-3" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
