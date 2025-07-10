"use client";

import { useState } from "react";
import Image from "next/image";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
  type CarouselApi,
} from "@/components/ui/carousel";
import { useEffect } from "react";
import { useResponsive } from "@/components/responsive-provider";

interface ImageCarouselProps {
  isInDrawer?: boolean;
}

export function ImageCarousel({ isInDrawer = false }: ImageCarouselProps) {
  const [api, setApi] = useState<CarouselApi>();
  const [current, setCurrent] = useState(0);
  const [count, setCount] = useState(0);
  const { } = useResponsive(); // Keep import for future use
  const [images] = useState<string[]>([
    // Placeholder image URLs - in real app these would come from API
    "/placeholder-1.svg",
    "/placeholder-2.svg", 
    "/placeholder-3.svg"
  ]);

  useEffect(() => {
    if (!api) {
      return;
    }

    setCount(api.scrollSnapList().length);
    setCurrent(api.selectedScrollSnap() + 1);

    api.on("select", () => {
      setCurrent(api.selectedScrollSnap() + 1);
    });
  }, [api]);

  // Global keyboard navigation
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!api) return;
      
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        api.scrollPrev();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        api.scrollNext();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [api]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header - make it more compact for drawer */}
      <div className={`flex items-center justify-between border-b shrink-0 ${
        isInDrawer ? 'p-2 sm:p-3' : 'p-3 sm:p-4 pr-8 sm:pr-12'
      }`}>
        <h3 className={`font-semibold ${isInDrawer ? 'text-sm sm:text-base' : 'text-base sm:text-lg'}`}>
          Generated Images
        </h3>
        <Badge variant="secondary" className="shrink-0 text-xs">
          {images.length > 0 ? `${current} of ${count}` : "0 images"}
        </Badge>
      </div>

      {/* Main Carousel Area - optimized for drawer */}
      <div className="flex-1 flex flex-col justify-center items-center overflow-hidden min-h-0">
        {images.length > 0 ? (
          <div className={`w-full h-full flex flex-col ${
            isInDrawer ? 'p-2 sm:p-4' : 'p-3 sm:p-6'
          }`}>
            <Carousel setApi={setApi} className="w-full h-full flex flex-col" opts={{ align: "center" }}>
              <CarouselContent className="flex-1">
                {images.map((image, index) => (
                  <CarouselItem key={index} className="h-full">
                    <Card className="w-full h-full overflow-hidden">
                      <CardContent className="p-0 h-full flex flex-col">
                        <div className="flex-1 flex flex-col items-center justify-center space-y-2 overflow-hidden">
                          {/* Image container - responsive height based on context */}
                          <div className={`relative w-full flex-1 flex items-center justify-center overflow-hidden ${
                            isInDrawer 
                              ? 'min-h-[45vh] max-h-[70vh]' 
                              : 'max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh]'
                          }`}>
                            <Image
                              src={image}
                              alt={`Expression ${index + 1}`}
                              width={800}
                              height={600}
                              className="w-full h-full object-contain rounded-lg"
                              priority={index === current}
                              onError={(e) => {
                                // Fallback for missing images
                                e.currentTarget.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='400' height='400' viewBox='0 0 400 400'%3E%3Crect width='400' height='400' fill='%23f0f0f0'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-family='Arial, sans-serif' font-size='16' fill='%23666'%3ENo Image%3C/text%3E%3C/svg%3E";
                              }}
                            />
                          </div>
                          {/* Info section - compact for drawer */}
                          <div className={`text-center shrink-0 ${isInDrawer ? 'p-2' : 'p-2 sm:p-4'}`}>
                            <p className={`font-medium ${isInDrawer ? 'text-xs sm:text-sm' : 'text-sm sm:text-lg'}`}>
                              {`expression_${index + 1}`}
                            </p>
                            <p className={`text-muted-foreground ${isInDrawer ? 'text-xs' : 'text-xs sm:text-sm'}`}>
                              Generated image • Use arrow keys or buttons to navigate
                            </p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </CarouselItem>
                ))}
              </CarouselContent>
              <CarouselPrevious className={`left-2 ${
                isInDrawer ? 'h-6 w-6 sm:h-8 sm:w-8' : 'h-8 w-8 sm:h-10 sm:w-10'
              }`} />
              <CarouselNext className={`right-2 ${
                isInDrawer ? 'h-6 w-6 sm:h-8 sm:w-8' : 'h-8 w-8 sm:h-10 sm:w-10'
              }`} />
            </Carousel>
          </div>
        ) : (
          <div className="text-center p-4">
            <div className={`bg-muted rounded-lg flex items-center justify-center mb-4 ${
              isInDrawer ? 'w-48 h-48' : 'w-64 h-64'
            }`}>
              <p className="text-muted-foreground">No images loaded</p>
            </div>
            <p className={`text-muted-foreground mb-2 ${isInDrawer ? 'text-xs' : 'text-sm'}`}>
              No generated images to display
            </p>
            <p className={`text-muted-foreground ${isInDrawer ? 'text-xs' : 'text-xs'}`}>
              Load images using the output directory field in the main panel
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
