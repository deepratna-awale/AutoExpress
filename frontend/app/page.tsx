"use client";

import { EmoticaApp } from "@/components/emotica-app";
import { EmoticaProvider } from "@/lib/store";

export default function Home() {
  return (
    <EmoticaProvider>
      <EmoticaApp />
    </EmoticaProvider>
  );
}
