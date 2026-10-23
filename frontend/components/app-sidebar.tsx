"use client";

import * as React from "react";
import { useState } from "react";
import { Settings2 } from "lucide-react";
import { useTheme } from "next-themes";

import { NavMain } from "@/components/nav-main";
import { ThemeEditor } from "@/components/theme-editor";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ThemeSwitcher } from "@/components/ui/shadcn-io/theme-switcher";

const navMain = [
  {
    title: "Settings",
    url: "#",
    isActive: true,
    icon: Settings2,
    items: [
      { title: "GUI Settings", url: "#gui-settings" },
      { title: "Theme Editor", url: "#theme-editor" },
    ],
  },
];

type ThemeChoice = "light" | "dark" | "system";

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const [themeEditorOpen, setThemeEditorOpen] = useState(false);
  const [guiSettingsOpen, setGuiSettingsOpen] = useState(false);
  const { theme, setTheme } = useTheme();

  const handleNavigation = (url: string) => {
    if (url === "#theme-editor") setThemeEditorOpen(true);
    if (url === "#gui-settings") setGuiSettingsOpen(true);
  };

  return (
    <>
      <Sidebar collapsible="icon" {...props}>
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src="/favicon-rounded.png" alt="Auto Express Logo" className="size-6" width={24} height={24} />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">Auto Express</span>
                  <span className="truncate text-xs text-muted-foreground">Expression Generator</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <NavMain items={navMain} onNavigate={handleNavigation} />
        </SidebarContent>
        <SidebarFooter className="items-center group-data-[collapsible=icon]:hidden">
          <ThemeSwitcher value={(theme as ThemeChoice) ?? "system"} onChange={setTheme} />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>

      <Dialog open={guiSettingsOpen} onOpenChange={setGuiSettingsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>GUI Settings</DialogTitle>
            <DialogDescription>These settings are saved in this browser.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <Label>Appearance</Label>
              <ThemeSwitcher value={(theme as ThemeChoice) ?? "system"} onChange={setTheme} />
            </div>
            <div className="flex items-center justify-between">
              <Label>Colors</Label>
              <button
                type="button"
                className="text-sm text-primary underline-offset-4 hover:underline"
                onClick={() => {
                  setGuiSettingsOpen(false);
                  setThemeEditorOpen(true);
                }}
              >
                Open theme editor
              </button>
            </div>
            <div className="flex items-center justify-between">
              <Label>Classic interface</Label>
              <a href="/classic" className="text-sm text-primary underline-offset-4 hover:underline">
                Open the original UI
              </a>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={themeEditorOpen} onOpenChange={setThemeEditorOpen}>
        <DialogContent className="max-h-[95vh] overflow-hidden sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Theme Editor</DialogTitle>
            <DialogDescription>Customize App Appearance</DialogDescription>
          </DialogHeader>
          <ScrollArea className="max-h-[80vh]">
            <ThemeEditor />
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  );
}
