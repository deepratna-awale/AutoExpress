"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Combobox } from "@/components/ui/combobox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Link } from "lucide-react";

export function ParametersPanel() {
  const [apiUrl, setApiUrl] = useState("127.0.0.1:7860");
  const [style, setStyle] = useState("");
  const [model, setModel] = useState("");
  const [sampler, setSampler] = useState("");
  const [scheduler, setScheduler] = useState("");
  const [lora, setLora] = useState("");
  const [clipSkip, setClipSkip] = useState(2);
  const [seed, setSeed] = useState(-1);
  const [steps, setSteps] = useState([32]);
  const [width, setWidth] = useState([512]);
  const [height, setHeight] = useState([768]);
  const [cfgScale, setCfgScale] = useState([7]);
  const [denoisingStrength, setDenoisingStrength] = useState([0.5]);

  // Options for comboboxes
  const styleOptions = [
    { value: "anime", label: "Anime" },
    { value: "realistic", label: "Realistic" },
    { value: "semi-realistic", label: "Semi-Realistic" },
    { value: "cartoon", label: "Cartoon" },
  ];
  const modelOptions = [
    { value: "model1", label: "Model 1" },
    { value: "model2", label: "Model 2" },
    { value: "sd15", label: "Stable Diffusion 1.5" },
    { value: "sdxl", label: "Stable Diffusion XL" },
  ];

  const samplerOptions = [
    { value: "euler", label: "Euler" },
    { value: "euler_a", label: "Euler A" },
    { value: "dpm", label: "DPM++" },
    { value: "dpm_karras", label: "DPM++ Karras" },
  ];

  const schedulerOptions = [
    { value: "normal", label: "Normal" },
    { value: "karras", label: "Karras" },
    { value: "exponential", label: "Exponential" },
  ];

  const loraOptions = [
    { value: "lora1", label: "LoRA 1" },
    { value: "lora2", label: "LoRA 2" },
    { value: "character_lora", label: "Character LoRA" },
    { value: "style_lora", label: "Style LoRA" },
  ];

  return (
    <ScrollArea className="h-full">
      <div className="p-3 sm:p-6 space-y-4 sm:space-y-6">
        {/* A1111 API Connection */}
        <div className="space-y-2 sm:space-y-3">
          <Label htmlFor="api-url" className="text-sm font-medium">
            SD Web UI Connection
          </Label>
          <div className="flex gap-2">
            <Input
              id="api-url"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="127.0.0.1:7860"
              className="flex-1 text-sm"
            />
            <Button size="icon" variant="outline" className="shrink-0 h-9 w-9">
              <Link className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Generation Settings */}
        <div className="space-y-3 sm:space-y-4">
          <div className="pb-2 border-b">
            <h3 className="text-sm font-semibold text-foreground">
              Generation Settings
            </h3>
          </div>

          {/* Style Selector */}
          <div className="space-y-2 sm:space-y-3">
            <Label className="text-sm font-medium">Style</Label>
            <Combobox
              options={styleOptions}
              value={style}
              onValueChange={setStyle}
              placeholder="Select style"
              searchPlaceholder="Search styles..."
            />
          </div>

          {/* Model Dropdown */}
          <div className="space-y-2 sm:space-y-3">
            <Label className="text-sm font-medium">Model</Label>
            <Combobox
              options={modelOptions}
              value={model}
              onValueChange={setModel}
              placeholder="Select model"
              searchPlaceholder="Search models..."
            />
          </div>

          {/* Sampler and Scheduler Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
            <div className="space-y-2 sm:space-y-3">
              <Label className="text-sm font-medium">Sampler</Label>
              <Combobox
                options={samplerOptions}
                value={sampler}
                onValueChange={setSampler}
                placeholder="Select sampler"
                searchPlaceholder="Search samplers..."
              />
            </div>
            <div className="space-y-2 sm:space-y-3">
              <Label className="text-sm font-medium">Scheduler</Label>
              <Combobox
                options={schedulerOptions}
                value={scheduler}
                onValueChange={setScheduler}
                placeholder="Select scheduler"
                searchPlaceholder="Search schedulers..."
              />
            </div>
          </div>

          {/* LoRA */}
          <div className="space-y-2 sm:space-y-3">
            <Label className="text-sm font-medium">LoRA(s)</Label>
            <Combobox
              options={loraOptions}
              value={lora}
              onValueChange={setLora}
              placeholder="Select LoRA(s)"
              searchPlaceholder="Search LoRAs..."
            />
          </div>
        </div>

        {/* Basic Parameters */}
        <div className="space-y-3 sm:space-y-4">
          <div className="pb-2 border-b">
            <h3 className="text-sm font-semibold text-foreground">
              Basic Parameters
            </h3>
          </div>

          {/* Clip Skip and Seed */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
            <div className="space-y-2 sm:space-y-3">
              <Label htmlFor="clip-skip" className="text-sm font-medium">
                Clip Skip
              </Label>
              <Input
                id="clip-skip"
                type="number"
                value={clipSkip}
                onChange={(e) => setClipSkip(Number(e.target.value))}
                className="text-center text-sm"
              />
            </div>
            <div className="space-y-2 sm:space-y-3">
              <Label htmlFor="seed" className="text-sm font-medium">
                Seed
              </Label>
              <Input
                id="seed"
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                min={-1}
                className="text-center text-sm"
              />
            </div>
          </div>
        </div>

        {/* Generation Parameters */}
        <div className="space-y-3 sm:space-y-4">
          <div className="pb-2 border-b">
            <h3 className="text-sm font-semibold text-foreground">
              Generation Parameters
            </h3>
          </div>

          {/* Steps Slider */}
          <div className="space-y-2 sm:space-y-3">
            <div className="flex justify-between items-center">
              <Label className="text-sm font-medium">Steps</Label>
              <div className="bg-muted px-2 py-1 rounded text-xs font-mono">
                {steps[0]}
              </div>
            </div>
            <Slider
              value={steps}
              onValueChange={setSteps}
              max={40}
              min={1}
              step={1}
              className="w-full"
            />
          </div>

          {/* Dimensions */}
          <div className="space-y-3 sm:space-y-4">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Dimensions
            </h4>

            {/* Width and Height in a row */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
              <div className="space-y-2 sm:space-y-3">
                <div className="flex justify-between items-center">
                  <Label className="text-sm font-medium">Width</Label>
                  <div className="bg-muted px-2 py-1 rounded text-xs font-mono">
                    {width[0]}
                  </div>
                </div>
                <Slider
                  value={width}
                  onValueChange={setWidth}
                  max={2048}
                  min={64}
                  step={64}
                  className="w-full"
                />
              </div>

              <div className="space-y-2 sm:space-y-3">
                <div className="flex justify-between items-center">
                  <Label className="text-sm font-medium">Height</Label>
                  <div className="bg-muted px-2 py-1 rounded text-xs font-mono">
                    {height[0]}
                  </div>
                </div>
                <Slider
                  value={height}
                  onValueChange={setHeight}
                  max={2048}
                  min={64}
                  step={64}
                  className="w-full"
                />
              </div>
            </div>
          </div>

          {/* CFG Scale Slider */}
          <div className="space-y-2 sm:space-y-3">
            <div className="flex justify-between items-center">
              <Label className="text-sm font-medium">CFG Scale</Label>
              <div className="bg-muted px-2 py-1 rounded text-xs font-mono">
                {cfgScale[0]}
              </div>
            </div>
            <Slider
              value={cfgScale}
              onValueChange={setCfgScale}
              max={20}
              min={1}
              step={0.5}
              className="w-full"
            />
          </div>

          {/* Denoising Strength Slider */}
          <div className="space-y-2 sm:space-y-3">
            <div className="flex justify-between items-center">
              <Label className="text-sm font-medium">Denoising Strength</Label>
              <div className="bg-muted px-2 py-1 rounded text-xs font-mono">
                {denoisingStrength[0].toFixed(2)}
              </div>
            </div>
            <Slider
              value={denoisingStrength}
              onValueChange={setDenoisingStrength}
              max={1}
              min={0}
              step={0.05}
              className="w-full"
            />
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}
