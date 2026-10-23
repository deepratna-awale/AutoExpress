"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { api, expressionName } from "@/lib/api";
import { useAutoExpress } from "@/lib/store";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
  type CarouselApi,
} from "@/components/ui/carousel";

interface ImageCarouselProps {
  isInDrawer?: boolean;
}

function isTyping(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
}

export function ImageCarousel({ isInDrawer = false }: ImageCarouselProps) {
  const { images, galleryDir, galleryVersion, generating, loadImages } = useAutoExpress();
  const [carousel, setCarousel] = useState<CarouselApi>();
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (!carousel) return;
    const onSelect = () => setCurrent(carousel.selectedScrollSnap());
    onSelect();
    carousel.on("select", onSelect);
    carousel.on("reInit", onSelect);
    return () => {
      carousel.off("select", onSelect);
      carousel.off("reInit", onSelect);
    };
  }, [carousel]);

  // Arrow keys move between expressions, as in the legacy viewer
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!carousel || isTyping(event.target)) return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        carousel.scrollPrev();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        carousel.scrollNext();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [carousel]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div
        className={cn(
          "flex shrink-0 items-center justify-between gap-2 border-b",
          isInDrawer ? "p-2 sm:p-3" : "p-3 pr-8 sm:p-4 sm:pr-12"
        )}
      >
        <div className="min-w-0">
          <h3 className={cn("font-semibold", isInDrawer ? "text-sm sm:text-base" : "text-base sm:text-lg")}>
            Generated Images
          </h3>
          {galleryDir && <p className="truncate text-xs text-muted-foreground">Output/{galleryDir}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {generating && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Generating" />}
          <Badge variant="secondary" className="text-xs">
            {images.length > 0 ? `${current + 1} of ${images.length}` : "0 images"}
          </Badge>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => loadImages(galleryDir || undefined)} aria-label="Reload images">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-hidden">
        {images.length > 0 ? (
          <div className={cn("flex h-full w-full flex-col", isInDrawer ? "p-2 sm:p-4" : "p-3 sm:p-6")}>
            <Carousel setApi={setCarousel} className="flex h-full w-full flex-col" opts={{ align: "center", loop: true }}>
              <CarouselContent className="h-full" containerClassName="min-h-0 flex-1">
                {images.map((image) => (
                  <CarouselItem key={image} className="h-full">
                    <div className="relative h-full w-full">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={api.imageUrl(galleryDir, image, galleryVersion)}
                        alt={expressionName(image)}
                        className="absolute inset-0 h-full w-full rounded-lg object-contain"
                        loading="lazy"
                      />
                      <p
                        className={cn(
                          "absolute bottom-2 left-1/2 -translate-x-1/2 rounded bg-black/60 px-3 py-1 font-medium text-white",
                          isInDrawer ? "text-sm" : "text-sm sm:text-base"
                        )}
                      >
                        {expressionName(image)}
                      </p>
                    </div>
                  </CarouselItem>
                ))}
              </CarouselContent>
              <CarouselPrevious className="left-2" />
              <CarouselNext className="right-2" />
            </Carousel>
          </div>
        ) : (
          <div className="p-4 text-center">
            <p className="mb-2 text-sm text-muted-foreground">
              {generating
                ? "Waiting for the first expression..."
                : galleryDir
                  ? `No PNG images found in Output/${galleryDir}.`
                  : "No generated images to display."}
            </p>
            <p className="text-xs text-muted-foreground">
              Type a character name in the output folder field and press Enter, or generate a set.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
