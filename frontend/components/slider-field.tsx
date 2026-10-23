"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";

interface SliderFieldProps {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
}

/** A slider paired with a number box, like the legacy UI's range + number inputs. */
export function SliderField({ id, label, value, onChange, min, max, step }: SliderFieldProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id} className="text-sm font-medium">
          {label}
        </Label>
        <Input
          id={id}
          type="number"
          value={Number.isFinite(value) ? value : ""}
          min={min}
          step={step}
          onChange={(e) => {
            const next = parseFloat(e.target.value);
            if (Number.isFinite(next)) onChange(next);
          }}
          className="h-7 w-20 px-2 text-right font-mono text-xs"
        />
      </div>
      <Slider
        value={[Math.min(Math.max(value, min), max)]}
        onValueChange={([next]) => onChange(next)}
        min={min}
        max={max}
        step={step}
        aria-label={label}
      />
    </div>
  );
}
