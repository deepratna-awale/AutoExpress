"use client";

import { useResponsive } from '@/components/responsive-provider';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export function ResponsiveDebugPanel() {
  const { isMobile, isTablet, isDesktop, isLargeScreen, screenSize, isSSR } = useResponsive();

  if (isSSR) {
    return (
      <Card className="fixed bottom-4 right-4 z-50 opacity-80">
        <CardContent className="p-3">
          <div className="text-sm text-muted-foreground">Loading responsive info...</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="fixed bottom-4 right-4 z-50 opacity-80">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Responsive Debug</CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0 space-y-2">
        <div className="flex flex-wrap gap-1">
          <Badge variant={isMobile ? "default" : "secondary"}>
            Mobile: {isMobile ? "✓" : "✗"}
          </Badge>
          <Badge variant={isTablet ? "default" : "secondary"}>
            Tablet: {isTablet ? "✓" : "✗"}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge variant={isDesktop ? "default" : "secondary"}>
            Desktop: {isDesktop ? "✓" : "✗"}
          </Badge>
          <Badge variant={isLargeScreen ? "default" : "secondary"}>
            Large: {isLargeScreen ? "✓" : "✗"}
          </Badge>
        </div>
        <div>
          <Badge variant="outline">Screen: {screenSize}</Badge>
        </div>
        <div className="text-xs text-muted-foreground">
          Window: {typeof window !== 'undefined' ? `${window.innerWidth}×${window.innerHeight}` : 'SSR'}
        </div>
      </CardContent>
    </Card>
  );
}
