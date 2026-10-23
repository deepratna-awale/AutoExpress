"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useTheme } from "next-themes";

export interface ThemeColors {
  background: string;
  foreground: string;
  card: string;
  "card-foreground": string;
  popover: string;
  "popover-foreground": string;
  primary: string;
  "primary-foreground": string;
  secondary: string;
  "secondary-foreground": string;
  muted: string;
  "muted-foreground": string;
  accent: string;
  "accent-foreground": string;
  destructive: string;
  "destructive-foreground": string;
  border: string;
  input: string;
  ring: string;
  sidebar: string;
  "sidebar-foreground": string;
  "sidebar-primary": string;
  "sidebar-primary-foreground": string;
  "sidebar-accent": string;
  "sidebar-accent-foreground": string;
  "sidebar-border": string;
  "sidebar-ring": string;
}

export type ThemeMode = "light" | "dark";

export interface ThemeStyles {
  light: ThemeColors;
  dark: ThemeColors;
}

export interface ThemeState {
  preset: string;
  currentMode: ThemeMode;
  styles: ThemeStyles;
}

export interface ThemePreset {
  label: string;
  styles: ThemeStyles;
}

// Matches the values in app/globals.css
const DEFAULT_STYLES: ThemeStyles = {
  light: {
    background: "oklch(1.0000 0 0)",
    foreground: "oklch(0.3211 0 0)",
    card: "oklch(1.0000 0 0)",
    "card-foreground": "oklch(0.3211 0 0)",
    popover: "oklch(1.0000 0 0)",
    "popover-foreground": "oklch(0.3211 0 0)",
    primary: "oklch(0.6231 0.1880 259.8145)",
    "primary-foreground": "oklch(1.0000 0 0)",
    secondary: "oklch(0.9670 0.0029 264.5419)",
    "secondary-foreground": "oklch(0.4461 0.0263 256.8018)",
    muted: "oklch(0.9846 0.0017 247.8389)",
    "muted-foreground": "oklch(0.5510 0.0234 264.3637)",
    accent: "oklch(0.9514 0.0250 236.8242)",
    "accent-foreground": "oklch(0.3791 0.1378 265.5222)",
    destructive: "oklch(0.6368 0.2078 25.3313)",
    "destructive-foreground": "oklch(1.0000 0 0)",
    border: "oklch(0.9276 0.0058 264.5313)",
    input: "oklch(0.9276 0.0058 264.5313)",
    ring: "oklch(0.6231 0.1880 259.8145)",
    sidebar: "oklch(0.9846 0.0017 247.8389)",
    "sidebar-foreground": "oklch(0.3211 0 0)",
    "sidebar-primary": "oklch(0.6231 0.1880 259.8145)",
    "sidebar-primary-foreground": "oklch(1.0000 0 0)",
    "sidebar-accent": "oklch(0.9514 0.0250 236.8242)",
    "sidebar-accent-foreground": "oklch(0.3791 0.1378 265.5222)",
    "sidebar-border": "oklch(0.9276 0.0058 264.5313)",
    "sidebar-ring": "oklch(0.6231 0.1880 259.8145)",
  },
  dark: {
    background: "oklch(0.2046 0 0)",
    foreground: "oklch(0.9219 0 0)",
    card: "oklch(0.2686 0 0)",
    "card-foreground": "oklch(0.9219 0 0)",
    popover: "oklch(0.2686 0 0)",
    "popover-foreground": "oklch(0.9219 0 0)",
    primary: "oklch(0.6231 0.1880 259.8145)",
    "primary-foreground": "oklch(1.0000 0 0)",
    secondary: "oklch(0.2686 0 0)",
    "secondary-foreground": "oklch(0.9219 0 0)",
    muted: "oklch(0.2686 0 0)",
    "muted-foreground": "oklch(0.7155 0 0)",
    accent: "oklch(0.3791 0.1378 265.5222)",
    "accent-foreground": "oklch(0.8823 0.0571 254.1284)",
    destructive: "oklch(0.6368 0.2078 25.3313)",
    "destructive-foreground": "oklch(1.0000 0 0)",
    border: "oklch(0.3715 0 0)",
    input: "oklch(0.3715 0 0)",
    ring: "oklch(0.6231 0.1880 259.8145)",
    sidebar: "oklch(0.2046 0 0)",
    "sidebar-foreground": "oklch(0.9219 0 0)",
    "sidebar-primary": "oklch(0.6231 0.1880 259.8145)",
    "sidebar-primary-foreground": "oklch(1.0000 0 0)",
    "sidebar-accent": "oklch(0.3791 0.1378 265.5222)",
    "sidebar-accent-foreground": "oklch(0.8823 0.0571 254.1284)",
    "sidebar-border": "oklch(0.3715 0 0)",
    "sidebar-ring": "oklch(0.6231 0.1880 259.8145)",
  },
};

function derive(base: ThemeStyles, overrides: { light?: Partial<ThemeColors>; dark?: Partial<ThemeColors> }): ThemeStyles {
  return {
    light: { ...base.light, ...overrides.light },
    dark: { ...base.dark, ...overrides.dark },
  };
}

// Deep navy and cyan of the original AutoExpress UI
const CLASSIC = derive(DEFAULT_STYLES, {
  dark: {
    background: "oklch(0.1950 0.0180 278.0000)",
    card: "oklch(0.2400 0.0220 278.0000)",
    popover: "oklch(0.2400 0.0220 278.0000)",
    secondary: "oklch(0.2700 0.0240 278.0000)",
    muted: "oklch(0.2700 0.0240 278.0000)",
    primary: "oklch(0.7900 0.1400 220.0000)",
    "primary-foreground": "oklch(0.1950 0.0180 278.0000)",
    accent: "oklch(0.3200 0.0400 260.0000)",
    "accent-foreground": "oklch(0.9200 0.0400 220.0000)",
    border: "oklch(0.3300 0.0250 278.0000)",
    input: "oklch(0.3300 0.0250 278.0000)",
    ring: "oklch(0.7900 0.1400 220.0000)",
    sidebar: "oklch(0.1700 0.0160 278.0000)",
    "sidebar-primary": "oklch(0.7900 0.1400 220.0000)",
    "sidebar-accent": "oklch(0.3200 0.0400 260.0000)",
    "sidebar-border": "oklch(0.3300 0.0250 278.0000)",
    "sidebar-ring": "oklch(0.7900 0.1400 220.0000)",
  },
  light: {
    primary: "oklch(0.6000 0.1400 230.0000)",
    ring: "oklch(0.6000 0.1400 230.0000)",
    "sidebar-primary": "oklch(0.6000 0.1400 230.0000)",
    "sidebar-ring": "oklch(0.6000 0.1400 230.0000)",
  },
});

const ROSE = derive(DEFAULT_STYLES, {
  light: {
    primary: "oklch(0.6450 0.2150 16.4390)",
    ring: "oklch(0.6450 0.2150 16.4390)",
    accent: "oklch(0.9600 0.0200 17.0000)",
    "accent-foreground": "oklch(0.4500 0.1600 16.0000)",
    "sidebar-primary": "oklch(0.6450 0.2150 16.4390)",
    "sidebar-ring": "oklch(0.6450 0.2150 16.4390)",
  },
  dark: {
    primary: "oklch(0.6450 0.2150 16.4390)",
    ring: "oklch(0.6450 0.2150 16.4390)",
    accent: "oklch(0.3500 0.0900 16.0000)",
    "accent-foreground": "oklch(0.9200 0.0400 16.0000)",
    "sidebar-primary": "oklch(0.6450 0.2150 16.4390)",
    "sidebar-accent": "oklch(0.3500 0.0900 16.0000)",
    "sidebar-ring": "oklch(0.6450 0.2150 16.4390)",
  },
});

const EMERALD = derive(DEFAULT_STYLES, {
  light: {
    primary: "oklch(0.6000 0.1300 163.0000)",
    ring: "oklch(0.6000 0.1300 163.0000)",
    accent: "oklch(0.9500 0.0300 163.0000)",
    "accent-foreground": "oklch(0.4000 0.0900 163.0000)",
    "sidebar-primary": "oklch(0.6000 0.1300 163.0000)",
    "sidebar-ring": "oklch(0.6000 0.1300 163.0000)",
  },
  dark: {
    primary: "oklch(0.7000 0.1500 163.0000)",
    "primary-foreground": "oklch(0.2046 0 0)",
    ring: "oklch(0.7000 0.1500 163.0000)",
    accent: "oklch(0.3400 0.0600 163.0000)",
    "accent-foreground": "oklch(0.9200 0.0400 163.0000)",
    "sidebar-primary": "oklch(0.7000 0.1500 163.0000)",
    "sidebar-accent": "oklch(0.3400 0.0600 163.0000)",
    "sidebar-ring": "oklch(0.7000 0.1500 163.0000)",
  },
});

const THEME_PRESETS: Record<string, ThemePreset> = {
  default: { label: "Default", styles: DEFAULT_STYLES },
  classic: { label: "AutoExpress Classic", styles: CLASSIC },
  rose: { label: "Rose", styles: ROSE },
  emerald: { label: "Emerald", styles: EMERALD },
};

export const THEME_PRESETS_META: Record<string, { label: string }> = Object.fromEntries(
  Object.entries(THEME_PRESETS).map(([key, preset]) => [key, { label: preset.label }])
);

export function getPresetNames() {
  return Object.keys(THEME_PRESETS);
}

export async function loadPreset(name: string): Promise<ThemePreset | null> {
  return THEME_PRESETS[name] ?? null;
}

function cssBlock(selector: string, colors: ThemeColors) {
  const lines = Object.entries(colors).map(([key, value]) => `  --${key}: ${value};`);
  return `${selector} {\n${lines.join("\n")}\n}`;
}

export function generateCSSVariables(state: ThemeState) {
  return `${cssBlock(":root", state.styles.light)}\n\n${cssBlock(".dark", state.styles.dark)}\n`;
}

const STORAGE_KEY = "autoexpress-theme";
const STYLE_ELEMENT_ID = "autoexpress-live-theme";

interface LiveThemeContextValue {
  themeState: ThemeState;
  updateThemeColor: (key: keyof ThemeColors, value: string) => void;
  updateThemeMode: (mode: ThemeMode) => void;
  resetTheme: () => void;
  applyPreset: (name: string, styles: ThemeStyles) => void;
}

const LiveThemeContext = createContext<LiveThemeContextValue | undefined>(undefined);

const INITIAL_STATE: ThemeState = { preset: "default", currentMode: "light", styles: DEFAULT_STYLES };

export function LiveThemeProvider({ children }: { children: React.ReactNode }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [themeState, setThemeState] = useState<ThemeState>(INITIAL_STATE);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (saved?.styles?.light && saved?.styles?.dark) {
        setThemeState((prev) => ({
          ...prev,
          preset: saved.preset ?? "custom",
          styles: { light: { ...DEFAULT_STYLES.light, ...saved.styles.light }, dark: { ...DEFAULT_STYLES.dark, ...saved.styles.dark } },
        }));
      }
    } catch {
      // Storage unavailable or corrupt
    }
    setLoaded(true);
  }, []);

  // Follow the light/dark mode chosen through next-themes
  useEffect(() => {
    if (resolvedTheme === "light" || resolvedTheme === "dark") {
      setThemeState((prev) => (prev.currentMode === resolvedTheme ? prev : { ...prev, currentMode: resolvedTheme }));
    }
  }, [resolvedTheme]);

  // Apply and persist the colors
  useEffect(() => {
    if (!loaded) return;
    let style = document.getElementById(STYLE_ELEMENT_ID) as HTMLStyleElement | null;
    if (!style) {
      style = document.createElement("style");
      style.id = STYLE_ELEMENT_ID;
      document.head.appendChild(style);
    }
    style.textContent = generateCSSVariables(themeState);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ preset: themeState.preset, styles: themeState.styles }));
    } catch {
      // Storage unavailable
    }
  }, [loaded, themeState.preset, themeState.styles]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateThemeColor = useCallback((key: keyof ThemeColors, value: string) => {
    setThemeState((prev) => ({
      ...prev,
      preset: "custom",
      styles: { ...prev.styles, [prev.currentMode]: { ...prev.styles[prev.currentMode], [key]: value } },
    }));
  }, []);

  const updateThemeMode = useCallback(
    (mode: ThemeMode) => {
      setTheme(mode);
      setThemeState((prev) => ({ ...prev, currentMode: mode }));
    },
    [setTheme]
  );

  const resetTheme = useCallback(() => {
    setThemeState((prev) => ({ ...prev, preset: "default", styles: DEFAULT_STYLES }));
  }, []);

  const applyPreset = useCallback((name: string, styles: ThemeStyles) => {
    setThemeState((prev) => ({ ...prev, preset: name, styles }));
  }, []);

  return (
    <LiveThemeContext.Provider value={{ themeState, updateThemeColor, updateThemeMode, resetTheme, applyPreset }}>
      {children}
    </LiveThemeContext.Provider>
  );
}

export function useLiveTheme() {
  const context = useContext(LiveThemeContext);
  if (!context) throw new Error("useLiveTheme must be used within a LiveThemeProvider");
  return context;
}
