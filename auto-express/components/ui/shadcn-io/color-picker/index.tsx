"use client"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { Range, Root, Thumb, Track } from "@radix-ui/react-slider"
import Color from "color"
import { PipetteIcon } from "lucide-react"
import {
  type ChangeEventHandler,
  type ComponentProps,
  type HTMLAttributes,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react"
import { createContext, useContext } from "react"

interface ColorPickerContextValue {
  hue: number
  saturation: number
  lightness: number
  alpha: number
  mode: string
  setHue: (hue: number) => void
  setSaturation: (saturation: number) => void
  setLightness: (lightness: number) => void
  setAlpha: (alpha: number) => void
  setMode: (mode: string) => void
}

const ColorPickerContext = createContext<ColorPickerContextValue | undefined>(undefined)

export const useColorPicker = () => {
  const context = useContext(ColorPickerContext)

  if (!context) {
    throw new Error("useColorPicker must be used within a ColorPickerProvider")
  }

  return context
}

export type ColorPickerProps = HTMLAttributes<HTMLDivElement> & {
  value?: Parameters<typeof Color>[0]
  defaultValue?: Parameters<typeof Color>[0]
  onChange?: (value: Parameters<typeof Color.rgb>[0]) => void
  mode?: string
}

export const ColorPicker = ({ value, defaultValue = "#000000", onChange, mode: initialMode = "hex", className, ...props }: ColorPickerProps) => {
  const color = value ? Color(value) : Color(defaultValue)

  const [hue, setHue] = useState(color.hue() || 0)
  const [saturation, setSaturation] = useState(color.saturationl() || 100)
  const [lightness, setLightness] = useState(color.lightness() || 50)
  const [alpha, setAlpha] = useState(color.alpha() * 100)
  const [mode, setMode] = useState(initialMode || "hex")

  // Update color when controlled value changes
  useEffect(() => {
    if (value) {
      try {
        const newColor = Color(value)
        setHue(newColor.hue() || 0)
        setSaturation(newColor.saturationl() || 100)
        setLightness(newColor.lightness() || 50)
        setAlpha(newColor.alpha() * 100)
      } catch (error) {
        console.error('Error parsing color value:', error, value)
      }
    }
  }, [value])

  // Notify parent of changes
  useEffect(() => {
    if (onChange) {
      const color = Color.hsl(hue, saturation, lightness).alpha(alpha / 100)
      
      if (mode === "hex") {
        // Return hex string for hex mode
        onChange(color.hex())
      } else {
        // Return RGBA array for other modes
        const rgba = color.rgb().array()
        onChange([rgba[0], rgba[1], rgba[2], alpha / 100])
      }
    }
  }, [hue, saturation, lightness, alpha, onChange, mode])

  return (
    <ColorPickerContext.Provider
      value={{
        hue,
        saturation,
        lightness,
        alpha,
        mode,
        setHue,
        setSaturation,
        setLightness,
        setAlpha,
        setMode,
      }}
    >
      <div className={cn("grid w-full gap-4", className)} {...props} />
    </ColorPickerContext.Provider>
  )
}

export type ColorPickerSelectionProps = HTMLAttributes<HTMLDivElement>

export const ColorPickerSelection = ({ className, ...props }: ColorPickerSelectionProps) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const { hue, saturation, lightness, setSaturation, setLightness } = useColorPicker()

  // Calculate position based on current saturation and lightness
  const position = {
    x: saturation / 100,
    y: 1 - (lightness / 100)
  }

  const handlePointerMove = useCallback(
    (event: PointerEvent) => {
      if (!isDragging || !containerRef.current) {
        return
      }

      const rect = containerRef.current.getBoundingClientRect()
      const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
      const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))

      // Update both saturation and lightness
      setSaturation(x * 100)
      setLightness((1 - y) * 100)
    },
    [isDragging, setSaturation, setLightness],
  )

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("pointermove", handlePointerMove)
      window.addEventListener("pointerup", () => setIsDragging(false))
    }
    return () => {
      window.removeEventListener("pointermove", handlePointerMove)
      window.removeEventListener("pointerup", () => setIsDragging(false))
    }
  }, [isDragging, handlePointerMove])

  return (
    <div
      ref={containerRef}
      className={cn("relative aspect-[4/3] w-full cursor-crosshair rounded", className)}
      style={{
        background: `linear-gradient(0deg,rgb(0,0,0),transparent),linear-gradient(90deg,rgb(255,255,255),hsl(${hue},100%,50%))`,
      }}
      onPointerDown={(e) => {
        e.preventDefault()
        setIsDragging(true)
        handlePointerMove(e.nativeEvent)
      }}
      {...props}
    >
      <div
        className="-translate-x-1/2 -translate-y-1/2 pointer-events-none absolute h-4 w-4 rounded-full border-2 border-white"
        style={{
          left: `${position.x * 100}%`,
          top: `${position.y * 100}%`,
          boxShadow: "0 0 0 1px rgba(0,0,0,0.5)",
        }}
      />
    </div>
  )
}

export type ColorPickerHueProps = HTMLAttributes<HTMLDivElement>

export const ColorPickerHue = ({ className, ...props }: ColorPickerHueProps) => {
  const { hue, setHue } = useColorPicker()

  return (
    <Root
      value={[hue]}
      max={360}
      step={1}
      className={cn("relative flex h-4 w-full touch-none", className)}
      onValueChange={([hue]) => setHue(hue)}
    >
      <Track className="relative my-0.5 h-3 w-full grow rounded-full bg-[linear-gradient(90deg,#FF0000,#FFFF00,#00FF00,#00FFFF,#0000FF,#FF00FF,#FF0000)]">
        <Range className="absolute h-full" />
      </Track>
      <Thumb className="block h-4 w-4 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50" />
    </Root>
  )
}

export type ColorPickerAlphaProps = HTMLAttributes<HTMLDivElement>

export const ColorPickerAlpha = ({ className, ...props }: ColorPickerAlphaProps) => {
  const { alpha, setAlpha } = useColorPicker()

  return (
    <Root
      value={[alpha]}
      max={100}
      step={1}
      className={cn("relative flex h-4 w-full touch-none", className)}
      onValueChange={([alpha]) => setAlpha(alpha)}
    >
      <Track
        className="relative my-0.5 h-3 w-full grow rounded-full"
        style={{
          background:
            'url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAMUlEQVQ4T2NkYGAQYcAP3uCTZhw1gGGYhAGBZIA/nYDCgBDAm9BGDWAAJyRCgLaBCAAgXwixzAS0pgAAAABJRU5ErkJggg==") left center',
        }}
      >
        <div className="absolute inset-0 rounded-full bg-gradient-to-r from-transparent to-primary/50" />
        <Range className="absolute h-full rounded-full bg-transparent" />
      </Track>
      <Thumb className="block h-4 w-4 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50" />
    </Root>
  )
}

export type ColorPickerEyeDropperProps = ComponentProps<typeof Button>

export const ColorPickerEyeDropper = ({ className, ...props }: ColorPickerEyeDropperProps) => {
  const { setHue, setSaturation, setLightness, setAlpha } = useColorPicker()

  const handleEyeDropper = async () => {
    try {
      // @ts-ignore - EyeDropper API is experimental
      const eyeDropper = new EyeDropper()
      const result = await eyeDropper.open()
      const color = Color(result.sRGBHex)
      const [h, s, l] = color.hsl().array()

      setHue(h)
      setSaturation(s)
      setLightness(l)
      setAlpha(100)
    } catch (error) {
      console.error("EyeDropper failed:", error)
    }
  }

  return (
    <Button
      variant="outline"
      size="icon"
      onClick={handleEyeDropper}
      className={cn("shrink-0 text-muted-foreground", className)}
      {...props}
    >
      <PipetteIcon size={16} />
    </Button>
  )
}

export type ColorPickerOutputProps = ComponentProps<typeof SelectTrigger>

const formats = ["hex", "rgb", "css", "hsl"]

export const ColorPickerOutput = ({ className, ...props }: ColorPickerOutputProps) => {
  const { mode, setMode } = useColorPicker()

  return (
    <Select value={mode} onValueChange={setMode}>
      <SelectTrigger className="h-8 w-[4.5rem] shrink-0 text-xs" {...props}>
        <SelectValue placeholder="Mode" />
      </SelectTrigger>
      <SelectContent>
        {formats.map((format) => (
          <SelectItem key={format} value={format} className="text-xs">
            {format.toUpperCase()}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

type PercentageInputProps = ComponentProps<typeof Input>

const PercentageInput = ({ className, onChange, ...props }: PercentageInputProps) => {
  return (
    <div className="relative">
      <Input
        type="text"
        onChange={onChange}
        {...props}
        className={cn("h-8 w-[3.25rem] rounded-l-none bg-secondary px-2 text-xs shadow-none", className)}
      />
      <span className="-translate-y-1/2 absolute top-1/2 right-2 text-muted-foreground text-xs">%</span>
    </div>
  )
}

export type ColorPickerFormatProps = HTMLAttributes<HTMLDivElement>

export const ColorPickerFormat = ({ className, ...props }: ColorPickerFormatProps) => {
  const { hue, saturation, lightness, alpha, mode, setHue, setSaturation, setLightness, setAlpha } = useColorPicker()
  const color = Color.hsl(hue, saturation, lightness, alpha / 100)

  if (mode === "hex") {
    const hex = color.hex()

    const handleChange: ChangeEventHandler<HTMLInputElement> = (event) => {
      try {
        const newColor = Color(event.target.value)

        setHue(newColor.hue())
        setSaturation(newColor.saturationl())
        setLightness(newColor.lightness())
        setAlpha(newColor.alpha() * 100)
      } catch (error) {
        console.error("Invalid hex color:", error)
      }
    }

    return (
      <div className={cn("-space-x-px relative flex items-center shadow-sm", className)} {...props}>
        <span className="-translate-y-1/2 absolute top-1/2 left-2 text-xs">#</span>
        <Input
          type="text"
          value={hex}
          onChange={handleChange}
          className="h-8 rounded-r-none bg-secondary px-2 text-xs shadow-none"
        />
        <PercentageInput value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} />
      </div>
    )
  }

  if (mode === "rgb") {
    const rgb = color
      .rgb()
      .array()
      .map((value) => Math.round(value))

    return (
      <div className={cn("-space-x-px flex items-center shadow-sm", className)} {...props}>
        {rgb.map((value, index) => (
          <Input
            key={index}
            type="text"
            value={value}
            readOnly
            className={cn(
              "h-8 rounded-r-none bg-secondary px-2 text-xs shadow-none",
              index && "rounded-l-none",
              className,
            )}
          />
        ))}
        <PercentageInput value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} />
      </div>
    )
  }

  if (mode === "css") {
    const rgb = color
      .rgb()
      .array()
      .map((value) => Math.round(value))

    return (
      <div className={cn("w-full shadow-sm", className)} {...props}>
        <Input
          type="text"
          className="h-8 w-full bg-secondary px-2 text-xs shadow-none"
          value={`rgba(${rgb.join(", ")}, ${alpha}%)`}
          readOnly
          {...props}
        />
      </div>
    )
  }

  if (mode === "hsl") {
    const hsl = color
      .hsl()
      .array()
      .map((value) => Math.round(value))

    return (
      <div className={cn("-space-x-px flex items-center shadow-sm", className)} {...props}>
        {hsl.map((value, index) => (
          <Input
            key={index}
            type="text"
            value={value}
            readOnly
            className={cn(
              "h-8 rounded-r-none bg-secondary px-2 text-xs shadow-none",
              index && "rounded-l-none",
              className,
            )}
          />
        ))}
        <PercentageInput value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} />
      </div>
    )
  }

  return null
}

