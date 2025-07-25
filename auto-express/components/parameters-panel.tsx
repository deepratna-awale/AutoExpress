"use client";

import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Combobox } from "@/components/ui/combobox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Link, Loader2 } from "lucide-react";
import { useModels, useSamplers, useSchedulers, useLoRAs } from "@/hooks/use-webui-api";
import type { SDModel, Sampler, Scheduler, LoRA } from "@/lib/webui-types";
import type { ParameterValidation } from "@/lib/metadata-parser";
import type { ParseMetadataResponse } from "@/lib/api-types";

interface ParametersPanelProps {
  selectedFiles?: File[];
}

export function ParametersPanel({ selectedFiles }: ParametersPanelProps) {
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

  // State for validation
  const [parameterValidation, setParameterValidation] = useState<ParameterValidation>({
    model: { isValid: false },
    sampler: { isValid: false },
    scheduler: { isValid: false },
    lora: { isValid: false },
  });

  // API hooks
  const { data: modelsData, execute: fetchModels, loading: modelsLoading } = useModels();
  const { data: samplersData, execute: fetchSamplers, loading: samplersLoading } = useSamplers();
  const { data: schedulersData, execute: fetchSchedulers, loading: schedulersLoading } = useSchedulers();
  const { data: lorasData, execute: fetchLoRAs, loading: lorasLoading } = useLoRAs();

  // Transform API data to dropdown options
  const modelOptions = modelsData && Array.isArray(modelsData) ? modelsData.map((model: SDModel) => {
    // Use the model_name for consistent identification
    return {
      value: model.model_name,
      label: model.title, // Show the full title in the UI
    };
  }) : [
    { value: "model1", label: "Model 1" },
    { value: "model2", label: "Model 2" },
    { value: "sd15", label: "Stable Diffusion 1.5" },
    { value: "sdxl", label: "Stable Diffusion XL" },
  ];

  const samplerOptions = samplersData && Array.isArray(samplersData) ? samplersData.map((sampler: Sampler) => ({
    value: sampler.name,
    label: sampler.name,
  })) : [
    { value: "euler", label: "Euler" },
    { value: "euler_a", label: "Euler A" },
    { value: "dpm", label: "DPM++" },
    { value: "dpm_karras", label: "DPM++ Karras" },
  ];

  const schedulerOptions = schedulersData && Array.isArray(schedulersData) ? schedulersData.map((scheduler: Scheduler) => ({
    value: scheduler.name,
    label: scheduler.label || scheduler.name,
  })) : [
    { value: "normal", label: "Normal" },
    { value: "karras", label: "Karras" },
    { value: "exponential", label: "Exponential" },
  ];

  const loraOptions = lorasData && Array.isArray(lorasData) ? lorasData.map((lora: LoRA) => ({
    value: lora.name,
    label: lora.alias || lora.name,
  })) : [
    { value: "lora1", label: "LoRA 1" },
    { value: "lora2", label: "LoRA 2" },
    { value: "character_lora", label: "Character LoRA" },
    { value: "style_lora", label: "Style LoRA" },
  ];

  // Options for comboboxes
  const styleOptions = [
    { value: "anime", label: "Anime" },
    { value: "realistic", label: "Realistic" },
    { value: "semi-realistic", label: "Semi-Realistic" },
    { value: "cartoon", label: "Cartoon" },
  ];

  // Fetch data when connect button is pressed
  const handleConnect = () => {
    // Ensure the API URL has the correct format
    const baseUrl = apiUrl.startsWith('http') ? apiUrl : `http://${apiUrl}`;
    
    fetchModels(undefined, baseUrl);
    fetchSamplers(undefined, baseUrl);
    fetchSchedulers(undefined, baseUrl);
    fetchLoRAs(undefined, baseUrl);
  };

  // Parse metadata from selected files when they change
  useEffect(() => {
    const parseMetadata = async () => {
      if (!selectedFiles || selectedFiles.length === 0) {
        // Reset validation when no files
        setParameterValidation({
          model: { isValid: false },
          sampler: { isValid: false },
          scheduler: { isValid: false },
          lora: { isValid: false },
        });
        return;
      }

      // Parse the first selected file
      const file = selectedFiles[0];
      if (!file.type.startsWith('image/')) return;

      try {
        // Call server-side metadata parsing API
        const formData = new FormData();
        formData.append('file', file);
        formData.append('apiUrl', `http://${apiUrl}`);
        
        const response = await fetch('/api/parse-metadata', {
          method: 'POST',
          body: formData,
        });
        
        if (!response.ok) {
          throw new Error('Failed to parse metadata');
        }
        
        const result: ParseMetadataResponse = await response.json();
        
        if (result.success && result.updatedValues) {
          console.log('Parsed metadata:', result.rawMetadata);
          console.log('Updated values:', result.updatedValues);
          
          // Update form fields using validated values, with fallbacks to raw metadata
          const values = result.updatedValues;
          const rawMetadata = result.rawMetadata;
          
          if (values.model !== undefined) setModel(values.model);
          else if (rawMetadata?.model !== undefined) setModel(rawMetadata.model);
          
          if (values.sampler !== undefined) setSampler(values.sampler);
          else if (rawMetadata?.sampler !== undefined) setSampler(rawMetadata.sampler);
          
          if (values.scheduler !== undefined) setScheduler(values.scheduler);
          else if (rawMetadata?.scheduler !== undefined) setScheduler(rawMetadata.scheduler);
          
          if (values.lora !== undefined) setLora(values.lora);
          else if (rawMetadata?.loras !== undefined && rawMetadata.loras.length > 0) {
            // Convert loras array to string format for the UI as fallback
            const loraString = rawMetadata.loras.map(lora => `${lora.name}:${lora.strength}`).join(', ');
            setLora(loraString);
          }
          
          if (values.clipSkip !== undefined) setClipSkip(values.clipSkip);
          if (values.seed !== undefined) setSeed(values.seed);
          if (values.steps !== undefined) setSteps([values.steps]);
          if (values.width !== undefined) setWidth([values.width]);
          if (values.height !== undefined) setHeight([values.height]);
          if (values.cfgScale !== undefined) setCfgScale([values.cfgScale]);
          if (values.denoisingStrength !== undefined) setDenoisingStrength([values.denoisingStrength]);

          // Update validation state using results from API
          if (result.validation) {
            setParameterValidation(result.validation);
          } else {
            // Reset validation state to valid since we populated values
            setParameterValidation({
              model: { isValid: true },
              sampler: { isValid: true },
              scheduler: { isValid: true },
              lora: { isValid: true },
            });
          }
        }
      } catch (error) {
        console.error('Error parsing image metadata:', error);
      }
    };

    parseMetadata();
  }, [selectedFiles, apiUrl]);

  // Helper function to get validation state for comboboxes - always return valid since we're not validating
  const getValidationState = (validationResult: { isValid: boolean }) => {
    return 'valid' as const;
  };

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
            <Button 
              id="connect-button"
              size="icon" 
              variant="outline" 
              className="shrink-0 h-9 w-9" 
              onClick={handleConnect}
              disabled={modelsLoading || samplersLoading || schedulersLoading || lorasLoading}
            >
              {modelsLoading || samplersLoading || schedulersLoading || lorasLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Link className="h-4 w-4" />
              )}
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
            <Label className="text-sm font-medium">
              Model {modelsLoading && <span className="text-xs text-muted-foreground">(Loading...)</span>}
            </Label>
            <Combobox
              options={modelOptions}
              value={model}
              onValueChange={setModel}
              placeholder={modelsLoading ? "Loading models..." : "Select model"}
              searchPlaceholder="Search models..."
              validationState={getValidationState(parameterValidation.model)}
            />
          </div>

          {/* Sampler and Scheduler Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
            <div className="space-y-2 sm:space-y-3">
              <Label className="text-sm font-medium">
                Sampler {samplersLoading && <span className="text-xs text-muted-foreground">(Loading...)</span>}
              </Label>
              <Combobox
                options={samplerOptions}
                value={sampler}
                onValueChange={setSampler}
                placeholder={samplersLoading ? "Loading samplers..." : "Select sampler"}
                searchPlaceholder="Search samplers..."
                validationState={getValidationState(parameterValidation.sampler)}
              />
            </div>
            <div className="space-y-2 sm:space-y-3">
              <Label className="text-sm font-medium">
                Scheduler {schedulersLoading && <span className="text-xs text-muted-foreground">(Loading...)</span>}
              </Label>
              <Combobox
                options={schedulerOptions}
                value={scheduler}
                onValueChange={setScheduler}
                placeholder={schedulersLoading ? "Loading schedulers..." : "Select scheduler"}
                searchPlaceholder="Search schedulers..."
                validationState={getValidationState(parameterValidation.scheduler)}
              />
            </div>
          </div>

          {/* LoRA */}
          <div className="space-y-2 sm:space-y-3">
            <Label className="text-sm font-medium">
              LoRA(s) {lorasLoading && <span className="text-xs text-muted-foreground">(Loading...)</span>}
            </Label>
            <Combobox
              options={loraOptions}
              value={lora}
              onValueChange={setLora}
              placeholder={lorasLoading ? "Loading LoRAs..." : "Select LoRA(s)"}
              searchPlaceholder="Search LoRAs..."
              validationState={getValidationState(parameterValidation.lora)}
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
