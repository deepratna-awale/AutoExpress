"use client";

import * as React from "react";
import { useState } from "react";
import { Settings2, Palette, Wrench, Sliders } from "lucide-react";

import { NavMain } from "@/components/nav-main";
import { NavUser } from "@/components/nav-user";
import { ThemeEditor } from "@/components/theme-editor";
import Image from "next/image";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarMenuButton,
  SidebarMenu,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";

// AutoExpress specific data
const data = {
  user: {
    name: "AutoExpress User",
    email: "user@autoexpress.ai",
    avatar: "/favicon.ico",
  },
  teams: [
    {
      name: "Auto Express",
    },
  ],
  navMain: [
    {
      title: "Image Tools",
      url: "#",
      icon: Wrench,
      isActive: true,
      items: [
        {
          title: "Remove Background",
          url: "#",
        },
        {
          title: "Change Background",
          url: "#",
        },
        {
          title: "Change Sky",
          url: "#",
        },
        {
          title: "Outpaint",
          url: "#",
        },
      ],
    },
    {
      title: "Advanced",
      url: "#",
      isActive: true,
      icon: Sliders,
      items: [
        {
          title: "Model Settings",
          url: "#",
        },
        {
          title: "LoRA Management",
          url: "#",
        },
        {
          title: "Style Management",
          url: "#",
        },
      ],
    },
    {
      title: "Settings",
      url: "#",
      isActive: true,
      icon: Settings2,
      items: [
        {
          title: "GUI Settings",
          url: "#",
        },
        {
          title: "Theme Editor",
          url: "#theme-editor",
        },
      ],
    },
  ],
};

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const [themeEditorOpen, setThemeEditorOpen] = useState(false);

  // Handle theme editor navigation
  const handleNavigation = (url: string) => {
    if (url === "#theme-editor") {
      setThemeEditorOpen(true);
    }
  }

  return (
    <>
      
      <Sidebar collapsible="icon" {...props}>
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                size="lg"
                className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              >
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg">
                  <Image
                    src="/favicon-rounded.png"
                    alt="Auto Express Logo"
                    className="size-6"
                    width={24}
                    height={24}
                    priority
                  />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">Auto Express</span>
                  <span className="truncate text-xs text-muted-foreground">
                    Expression Generator
                  </span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <NavMain items={data.navMain} onNavigate={handleNavigation} />
        </SidebarContent>
        <SidebarRail />
      </Sidebar>

      {/* Theme Editor Dialog */}
      <Dialog open={themeEditorOpen} onOpenChange={setThemeEditorOpen}>
        <DialogContent className="w-100% max-h-[95vh] overflow-hidden">
          <DialogHeader>
            <DialogTitle>Theme Editor</DialogTitle>
            <DialogDescription>Customize App Appearance</DialogDescription>
          </DialogHeader>
          <ScrollArea>
            <ThemeEditor />
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  );
}
