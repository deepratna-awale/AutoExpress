"use client";

import React, { createContext, useContext, useEffect, useState } from 'react';
import { useMediaQuery } from 'react-responsive';

interface ResponsiveContextType {
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  isLargeScreen: boolean;
  screenSize: 'mobile' | 'tablet' | 'desktop' | 'large' | 'xl';
  isSSR: boolean;
}

const ResponsiveContext = createContext<ResponsiveContextType | undefined>(undefined);

export function ResponsiveProvider({ children }: { children: React.ReactNode }) {
  const [isSSR, setIsSSR] = useState(true);

  // Use react-responsive hooks
  const isMobile = useMediaQuery({ maxWidth: 767 });
  const isTablet = useMediaQuery({ minWidth: 768, maxWidth: 1023 });
  const isDesktop = useMediaQuery({ minWidth: 1024 });
  const isLargeScreen = useMediaQuery({ minWidth: 1024 });
  const isXLarge = useMediaQuery({ minWidth: 1280 });
  const is2XLarge = useMediaQuery({ minWidth: 1536 });

  const getScreenSize = (): 'mobile' | 'tablet' | 'desktop' | 'large' | 'xl' => {
    if (isSSR) return 'desktop';
    if (isMobile) return 'mobile';
    if (isTablet) return 'tablet';
    if (is2XLarge) return 'xl';
    if (isXLarge) return 'large';
    return 'desktop';
  };

  useEffect(() => {
    setIsSSR(false);
  }, []);

  const value = {
    isMobile: isSSR ? false : isMobile,
    isTablet: isSSR ? false : isTablet,
    isDesktop: isSSR ? true : isDesktop,
    isLargeScreen: isSSR ? true : isLargeScreen,
    screenSize: getScreenSize(),
    isSSR,
  };

  return (
    <ResponsiveContext.Provider value={value}>
      {children}
    </ResponsiveContext.Provider>
  );
}

export function useResponsive() {
  const context = useContext(ResponsiveContext);
  if (context === undefined) {
    throw new Error('useResponsive must be used within a ResponsiveProvider');
  }
  return context;
}
