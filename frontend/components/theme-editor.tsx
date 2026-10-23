"use client";

import React, { useState, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { 
  Palette, 
  RotateCcw, 
  Copy,
  Check,
  Sun,
  Moon
} from "lucide-react";
import { toast } from "sonner";
import { useLiveTheme, ThemeColors, generateCSSVariables, getPresetNames, loadPreset, THEME_PRESETS_META } from "@/lib/theme";

// Color categories for organization
const COLOR_CATEGORIES = {
  basic: {
    label: "Basic Colors",
    colors: ["background", "foreground", "card", "card-foreground", "popover", "popover-foreground"] as (keyof ThemeColors)[]
  },
  semantic: {
    label: "Semantic Colors", 
    colors: ["primary", "primary-foreground", "secondary", "secondary-foreground", "accent", "accent-foreground", "destructive", "destructive-foreground"] as (keyof ThemeColors)[]
  },
  surface: {
    label: "Surface & Borders",
    colors: ["muted", "muted-foreground", "border", "input", "ring"] as (keyof ThemeColors)[]
  },
  sidebar: {
    label: "Sidebar Colors",
    colors: ["sidebar", "sidebar-foreground", "sidebar-primary", "sidebar-primary-foreground", "sidebar-accent", "sidebar-accent-foreground", "sidebar-border", "sidebar-ring"] as (keyof ThemeColors)[]
  }
};

// Helper function to format color names for display
const formatColorName = (colorKey: string): string => {
  return colorKey
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};

// OKLCH <-> sRGB conversion (https://bottosson.github.io/posts/oklab/) for the native color input
const oklchToHex = (oklchString: string): string => {
  const match = oklchString.match(/oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/);
  if (!match) return "#808080";
  const [l, c, h] = match.slice(1).map(Number);
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);

  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;

  const linear = [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ];
  return (
    "#" +
    linear
      .map((x) => {
        const v = x <= 0.0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - 0.055;
        return Math.round(Math.min(Math.max(v, 0), 1) * 255)
          .toString(16)
          .padStart(2, "0");
      })
      .join("")
  );
};

const hexToOklch = (hex: string): string => {
  const value = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const x = parseInt(value.slice(i, i + 2), 16) / 255;
    return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  });

  const l_ = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m_ = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s_ = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);

  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_;
  const A = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_;
  const B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_;

  const C = Math.sqrt(A * A + B * B);
  let H = (Math.atan2(B, A) * 180) / Math.PI;
  if (H < 0) H += 360;
  return `oklch(${L.toFixed(4)} ${C < 0.0001 ? 0 : C.toFixed(4)} ${C < 0.0001 ? 0 : H.toFixed(4)})`;
};

interface ThemeEditorProps {
  className?: string;
}

export function ThemeEditor({ className }: ThemeEditorProps) {
  const { themeState, updateThemeColor, updateThemeMode, resetTheme, applyPreset } = useLiveTheme();
  const [copied, setCopied] = useState(false);

  const currentColors = themeState.styles[themeState.currentMode];

  // Memoized color update handler
  const handleColorChange = useCallback((colorKey: keyof ThemeColors, newColor: string) => {
    const oklchColor = hexToOklch(newColor);
    updateThemeColor(colorKey, oklchColor);
  }, [updateThemeColor]);

  // Theme mode toggle handler
  const handleThemeToggle = useCallback((mode: 'light' | 'dark') => {
    updateThemeMode(mode);
  }, [updateThemeMode]);

  // Reset theme handler
  const handleReset = useCallback(() => {
    resetTheme();
    toast.success("Theme reset to defaults");
  }, [resetTheme]);

  // Export theme as CSS
  const handleExportCSS = useCallback(async () => {
    try {
      const cssVariables = generateCSSVariables(themeState);
      await navigator.clipboard.writeText(cssVariables);
      setCopied(true);
      toast.success("CSS variables copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy CSS");
    }
  }, [themeState]);

  // Apply preset handler
  const handlePresetChange = useCallback(async (presetName: string) => {
    try {
      const preset = await loadPreset(presetName);
      if (preset) {
        applyPreset(presetName, preset.styles);
        toast.success(`Applied ${preset.label} theme`);
      } else {
        toast.error(`Failed to load ${presetName} theme`);
      }
    } catch (error) {
      console.error('Error applying preset:', error);
      toast.error(`Error applying ${presetName} theme`);
    }
  }, [applyPreset]);

  // Color picker input component
  const ColorPickerComponent = useCallback(({ colorKey, color }: { colorKey: keyof ThemeColors; color: string }) => {
    const hexColor = oklchToHex(color);
    
    return (
      <div className="relative">
        <input
          type="color"
          value={hexColor}
          onChange={(e) => handleColorChange(colorKey, e.target.value)}
          className="w-8 h-8 border-2 border-border rounded-md cursor-pointer bg-transparent 
                     hover:border-primary/50 focus:border-primary focus:outline-none focus:ring-2 
                     focus:ring-primary/20 transition-all duration-200"
          aria-label={`Edit ${formatColorName(colorKey)}`}
          title={`Click to edit ${formatColorName(colorKey)}`}
        />
      </div>
    );
  }, [handleColorChange]);

  if (!themeState) {
    return null;
  }

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Palette className="h-5 w-5" />
              Theme Editor
            </CardTitle>
            <CardDescription>
              Customize your theme colors with live preview
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={themeState.currentMode === 'light' ? 'default' : 'outline'}
              size="sm"
              onClick={() => handleThemeToggle('light')}
              className="flex items-center gap-2"
            >
              <Sun className="h-4 w-4" />
              Light
            </Button>
            <Button
              variant={themeState.currentMode === 'dark' ? 'default' : 'outline'}
              size="sm"
              onClick={() => handleThemeToggle('dark')}
              className="flex items-center gap-2"
            >
              <Moon className="h-4 w-4" />
              Dark
            </Button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-6">
        {/* Theme Preset Selector */}
        <div className="space-y-2">
          <Label className="text-sm font-medium">Theme Presets</Label>
          <Select onValueChange={handlePresetChange}>
            <SelectTrigger>
              <SelectValue placeholder="Choose a preset theme..." />
            </SelectTrigger>
            <SelectContent>
              {getPresetNames().map((presetKey) => (
                <SelectItem key={presetKey} value={presetKey}>
                  {THEME_PRESETS_META[presetKey]?.label || presetKey}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <Button variant="outline" onClick={handleReset} className="flex items-center gap-2">
            <RotateCcw className="h-4 w-4" />
            Reset Theme
          </Button>
          <Button onClick={handleExportCSS} className="flex items-center gap-2">
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied!" : "Copy CSS"}
          </Button>
        </div>

        <Separator />

        {/* Color Categories as Tabs */}
        <Tabs defaultValue="basic" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            {Object.entries(COLOR_CATEGORIES).map(([categoryKey, category]) => (
              <TabsTrigger key={categoryKey} value={categoryKey} className="text-xs">
                {category.label}
              </TabsTrigger>
            ))}
          </TabsList>
          
          {Object.entries(COLOR_CATEGORIES).map(([categoryKey, category]) => (
            <TabsContent key={categoryKey} value={categoryKey} className="mt-4">
              <ScrollArea className="h-80">
                <div className="space-y-3">
                  {category.colors.map((colorKey) => (
                    <div key={colorKey} className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <ColorPickerComponent 
                          colorKey={colorKey} 
                          color={currentColors[colorKey]} 
                        />
                        <div>
                          <Label className="text-sm font-medium">
                            {formatColorName(colorKey)}
                          </Label>
                          <p className="text-xs text-muted-foreground font-mono">
                            {currentColors[colorKey]}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>
    </Card>
  );
}
