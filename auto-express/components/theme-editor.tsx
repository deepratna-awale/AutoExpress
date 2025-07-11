"use client";

import React, { useState, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import Color from "color";
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

// Helper function to convert OKLCH to hex for color picker
const oklchToHex = (oklchString: string): string => {
  try {
    if (oklchString.startsWith('oklch(')) {
      // Extract values from oklch(L C H) format
      const match = oklchString.match(/oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/);
      if (match) {
        const [, l, c, h] = match.map(Number);
        // Simplified conversion: L*100 for lightness, C*100 for saturation
        const lightness = Math.min(Math.max(l * 100, 0), 100);
        const saturation = Math.min(Math.max(c * 100, 0), 100);
        const hue = h || 0;
        
        return Color.hsl(hue, saturation, lightness).hex();
      }
    }
    
    // Try to parse as regular color (fallback)
    return Color(oklchString).hex();
  } catch {
    return "#808080"; // Gray fallback
  }
};

// Helper function to convert hex to OKLCH
const hexToOklch = (hex: string): string => {
  try {
    const color = Color(hex);
    const hsl = color.hsl();
    
    // Convert HSL to OKLCH-like values
    const l = (hsl.lightness() / 100).toFixed(4);
    const c = (hsl.saturationl() / 100 * 0.37).toFixed(4); // Scale chroma appropriately
    const h = hsl.hue().toFixed(4);
    
    return `oklch(${l} ${c} ${h})`;
  } catch {
    return hex; // Fallback to original if conversion fails
  }
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
    } catch (error) {
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
