import type { Metadata } from "next";
import Script from "next/script";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import { Nav } from "@/components/Nav";
import { VoiceButton } from "@/components/voice/VoiceButton";
import { StoreProvider } from "@/lib/store";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"], weight: ["400", "500"] });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], style: ["normal", "italic"], axes: ["opsz"] });

export const metadata: Metadata = {
  title: "PolyBridge",
  description: "PolyBridge reads event probabilities from prediction markets and options, and makes a hedge for the stocks you hold.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} ${newsreader.variable} antialiased`}>
      <body>
        <div style={{ position: "relative", minHeight: "100vh" }}>
          <StoreProvider>
            <Nav />
            {children}
            <VoiceButton />
          </StoreProvider>
        </div>
        <Script src="/thinking-orbs.js" strategy="afterInteractive" />
      </body>
    </html>
  );
}
