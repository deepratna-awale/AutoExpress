"use client"

import * as React from "react"
import {
  Settings2,
  Palette,
  Wrench,
  Sliders,
} from "lucide-react"

import { NavMain } from "@/components/nav-main"
import { NavUser } from "@/components/nav-user"
import Image from "next/image"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarMenuButton,
  SidebarMenu,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

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
      icon: Settings2,
      items: [
        {
          title: "GUI Settings",
          url: "#",
        },
      ],
    },
  ],
};

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
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
                <span className="truncate text-xs text-muted-foreground">Expression Generator</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={data.navMain} />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
