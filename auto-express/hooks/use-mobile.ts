import { useMediaQuery } from 'react-responsive'

// Breakpoint constants to match Tailwind CSS
const MOBILE_BREAKPOINT = 768
const TABLET_BREAKPOINT = 1024
const DESKTOP_BREAKPOINT = 1280
const LARGE_DESKTOP_BREAKPOINT = 1536

// Hook for mobile detection (< 768px)
export function useIsMobile() {
  return useMediaQuery({ maxWidth: MOBILE_BREAKPOINT - 1 })
}

// Hook for tablet detection (768px - 1023px)
export function useIsTablet() {
  return useMediaQuery({ 
    minWidth: MOBILE_BREAKPOINT, 
    maxWidth: TABLET_BREAKPOINT - 1 
  })
}

// Hook for desktop detection (>= 1024px)
export function useIsDesktop() {
  return useMediaQuery({ minWidth: TABLET_BREAKPOINT })
}

// Hook for large desktop detection (>= 1280px)
export function useIsLargeDesktop() {
  return useMediaQuery({ minWidth: DESKTOP_BREAKPOINT })
}

// Hook for extra large desktop detection (>= 1536px)
export function useIsXLDesktop() {
  return useMediaQuery({ minWidth: LARGE_DESKTOP_BREAKPOINT })
}

// Combined hook that returns screen size category
export function useScreenSize(): 'mobile' | 'tablet' | 'desktop' | 'large' | 'xl' {
  const isMobile = useIsMobile()
  const isTablet = useIsTablet()
  const isLargeDesktop = useIsLargeDesktop()
  const isXLDesktop = useIsXLDesktop()

  if (isMobile) return 'mobile'
  if (isTablet) return 'tablet'
  if (isXLDesktop) return 'xl'
  if (isLargeDesktop) return 'large'
  return 'desktop'
}

// Additional utility hooks for common breakpoint combinations
export function useIsMobileOrTablet() {
  return useMediaQuery({ maxWidth: TABLET_BREAKPOINT - 1 })
}

export function useIsTabletOrDesktop() {
  return useMediaQuery({ minWidth: MOBILE_BREAKPOINT })
}

// Hook for specific Tailwind breakpoints
export function useTailwindBreakpoint(breakpoint: 'sm' | 'md' | 'lg' | 'xl' | '2xl') {
  const breakpoints = {
    sm: 640,
    md: 768,
    lg: 1024,
    xl: 1280,
    '2xl': 1536
  }
  
  return useMediaQuery({ minWidth: breakpoints[breakpoint] })
}
