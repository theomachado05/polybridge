import type { Metadata } from "next";
import Script from "next/script";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import { Nav } from "@/components/Nav";
import { EngineStrip } from "@/components/micro/EngineStrip";
import { VoiceButton } from "@/components/voice/VoiceButton";
import { StoreProvider } from "@/lib/store";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"], weight: ["400", "500"] });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], style: ["normal", "italic"], axes: ["opsz"] });

export const metadata: Metadata = {
  title: "PolyBridge",
  description: "PolyBridge checks thin prediction-market books against their own date logic and the options chain, and shows what each check has and has not passed.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} ${newsreader.variable} antialiased`}>
      <body>
        <div className="pb-voice-shell" style={{ position: "relative", minHeight: "100vh", boxSizing: "border-box" }}>
          <StoreProvider>
            <Nav />
            <EngineStrip />
            {children}
            <VoiceButton />
          </StoreProvider>
        </div>
        <Script src="/thinking-orbs.js" strategy="afterInteractive" />
      </body>
    </html>
  );
}
