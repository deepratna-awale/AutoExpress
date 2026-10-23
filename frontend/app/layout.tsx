import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/ui/theme-provider";
import { ResponsiveProvider } from "@/components/responsive-provider";
import { Toaster } from "@/components/ui/sonner";
import { LiveThemeProvider } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Auto Express",
  description: "Generate a full set of character expressions from one image",
  icons: {
    icon: [
      { url: "/favicon-rounded.png", type: "image/png" },
      { url: "/icon.png", type: "image/png" },
    ],
    apple: "/favicon-rounded.png",
  },
};

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: 'cover'
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full">
      <head>
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
      </head>
      <body
        className="antialiased h-full overflow-hidden"
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <LiveThemeProvider>
            <ResponsiveProvider>
              {children}
              <Toaster richColors position="bottom-right" />
            </ResponsiveProvider>
          </LiveThemeProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
