"use client";

import { useState } from "react";
import { Sliders, Images } from "lucide-react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "@/components/ui/resizable";
import { ParametersPanel } from "@/components/parameters-panel";
import { DropZonePanel } from "@/components/drop-zone-panel";
import { DropZoneInputsPanel } from "@/components/drop-zone-inputs-panel";
import { ImageCarousel } from "@/components/image-carousel";
import { Button } from "@/components/ui/button";
import { useResponsive } from "@/components/responsive-provider";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

export function AutoExpressApp() {
  const [showCarousel, setShowCarousel] = useState(false);
  const [parametersOpen, setParametersOpen] = useState(false);
  
  // Shared state for files and form data that persists across layout changes
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [outputDirectory, setOutputDirectory] = useState("");
  
  // Responsive breakpoints using react-responsive
  const { isLargeScreen } = useResponsive();

  return (
    <SidebarProvider>
      <div className="flex w-full mobile-safe" style={{ height: '100dvh', minHeight: '100vh' }}>
        {/* Sidebar - uses default behavior, overlays on small screens */}
        <AppSidebar />
        
        <main className="flex-1 flex flex-col min-w-0">
          {/* Header with controls */}
          <div className="border-b p-2 flex items-center gap-2 shrink-0 bg-background">
            {/* Sidebar Trigger - works for all screen sizes */}
            <SidebarTrigger />
            
            <h1 className="text-sm sm:text-lg font-semibold truncate">Auto Express</h1>
            
            <div className="ml-auto flex gap-2">
              {/* Parameters Button - Show as sheet on mobile/tablet, hidden on desktop */}
              {!isLargeScreen && (
                <Sheet open={parametersOpen} onOpenChange={setParametersOpen}>
                  <SheetTrigger asChild>
                    <Button variant="outline" size="sm">
                      <span className="hidden xs:inline">Parameters</span>
                      <Sliders className="h-4 w-4 xs:ml-2" />
                    </Button>
                  </SheetTrigger>
                  <SheetContent side="right" className="w-80">
                    <SheetHeader className="sr-only">
                      <SheetTitle>Parameters</SheetTitle>
                      <SheetDescription>
                        Adjust generation parameters
                      </SheetDescription>
                    </SheetHeader>
                    <ParametersPanel />
                  </SheetContent>
                </Sheet>
              )}
              
              {/* Toggle Images Panel Button */}
              <Button 
                variant={showCarousel ? "default" : "outline"} 
                size="sm"
                onClick={() => setShowCarousel(!showCarousel)}
              >
                <span className="hidden xs:inline">
                  {showCarousel ? "Hide Images" : "Show Images"}
                </span>
                <Images className="h-4 w-4 xs:ml-2" />
              </Button>
            </div>
          </div>
          
          {/* Mobile/Tablet Carousel Drawer - only for smaller screens */}
          {showCarousel && !isLargeScreen && (
            <Drawer open={true} onOpenChange={setShowCarousel}>
              <DrawerContent style={{ height: 'calc(100dvh - env(safe-area-inset-bottom) - 8vh)' }} className="flex flex-col">
                {/* Drawer handle/indicator */}
                <div className="mx-auto mt-2 h-1 w-12 rounded-full bg-muted-foreground/20" />
                <DrawerHeader className="sr-only">
                  <DrawerTitle>Generated Images</DrawerTitle>
                  <DrawerDescription>
                    View generated images
                  </DrawerDescription>
                </DrawerHeader>
                <div className="flex-1 overflow-hidden">
                  <ImageCarousel isInDrawer={true} />
                </div>
              </DrawerContent>
            </Drawer>
          )}
          
          {/* Main Content Area */}
          <div className="flex-1 overflow-hidden min-h-0">
            {/* Large Desktop Layout (lg and up) - Resizable panels */}
            {isLargeScreen ? (
              <ResizablePanelGroup direction="horizontal" className="h-full">
                {/* Parameters Panel - Column 1 - Only show on lg+ */}
                <ResizablePanel defaultSize={20} minSize={0} maxSize={30}>
                  <ParametersPanel />
                </ResizablePanel>
                <ResizableHandle withHandle />
                
                {/* Dropzone Area - Split into dropzone and inputs */}
                <ResizablePanel defaultSize={showCarousel ? 35 : 55} minSize={0}>
                  <ResizablePanelGroup direction="vertical" className="h-full">
                    {/* Dropzone */}
                    <ResizablePanel defaultSize={70} minSize={0}>
                      <DropZonePanel 
                        onViewImages={() => setShowCarousel(true)} 
                        showCarousel={showCarousel}
                        showInputs={false} // Don't show inputs in this panel
                        selectedFiles={selectedFiles}
                        setSelectedFiles={setSelectedFiles}
                        prompt={prompt}
                        setPrompt={setPrompt}
                        negativePrompt={negativePrompt}
                        setNegativePrompt={setNegativePrompt}
                        outputDirectory={outputDirectory}
                        setOutputDirectory={setOutputDirectory}
                      />
                    </ResizablePanel>
                    
                    <ResizableHandle withHandle />
                    
                    {/* Dropzone Inputs */}
                    <ResizablePanel defaultSize={30} minSize={0} maxSize={60}>
                      <DropZoneInputsPanel 
                        onViewImages={() => setShowCarousel(true)}
                        selectedFiles={selectedFiles}
                        setSelectedFiles={setSelectedFiles}
                        prompt={prompt}
                        setPrompt={setPrompt}
                        negativePrompt={negativePrompt}
                        setNegativePrompt={setNegativePrompt}
                        outputDirectory={outputDirectory}
                        setOutputDirectory={setOutputDirectory}
                      />
                    </ResizablePanel>
                  </ResizablePanelGroup>
                </ResizablePanel>
                
                {/* Carousel Panel - Column 3 */}
                {showCarousel && (
                  <>
                    <ResizableHandle withHandle />
                    <ResizablePanel defaultSize={25} minSize={0} maxSize={50}>
                      <div className="h-full overflow-hidden">
                        <ImageCarousel isInDrawer={false} />
                      </div>
                    </ResizablePanel>
                  </>
                )}
              </ResizablePanelGroup>
            ) : (
              /* Mobile and Tablet Layout - No resizable panels */
              <div className="h-full flex flex-col">
                {/* Drop Zone Panel - Takes top half */}
                <div className="flex-1 min-h-0">
                  <DropZonePanel 
                    onViewImages={() => setShowCarousel(true)} 
                    showCarousel={showCarousel}
                    showInputs={false} // Don't show inputs in this panel on mobile
                    selectedFiles={selectedFiles}
                    setSelectedFiles={setSelectedFiles}
                    prompt={prompt}
                    setPrompt={setPrompt}
                    negativePrompt={negativePrompt}
                    setNegativePrompt={setNegativePrompt}
                    outputDirectory={outputDirectory}
                    setOutputDirectory={setOutputDirectory}
                  />
                </div>
                
                {/* Inputs Panel - Takes bottom half */}
                <div className="flex-1 min-h-0 border-t">
                  <DropZoneInputsPanel 
                    onViewImages={() => setShowCarousel(true)}
                    selectedFiles={selectedFiles}
                    setSelectedFiles={setSelectedFiles}
                    prompt={prompt}
                    setPrompt={setPrompt}
                    negativePrompt={negativePrompt}
                    setNegativePrompt={setNegativePrompt}
                    outputDirectory={outputDirectory}
                    setOutputDirectory={setOutputDirectory}
                  />
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </SidebarProvider>
  );
}
