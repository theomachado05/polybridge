import type { Metadata } from "next";
import Script from "next/script";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import { Nav } from "@/components/Nav";
import { StoreProvider } from "@/lib/store";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"], weight: ["400", "500"] });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], style: ["normal", "italic"], axes: ["opsz"] });

export const metadata: Metadata = {
  title: "PolyBridge",
  description: "Prediction-market signals in, fee- and tax-aware equity hedges out.",
};

const ELEVENLABS_AGENT_ID = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} ${newsreader.variable} antialiased`}>
      <body>
        <div style={{ position: "relative", minHeight: "100vh" }}>
          <div className="pb-bg" aria-hidden>
            <div className="pb-blob pb-blob-1" />
            <div className="pb-blob pb-blob-2" />
            <div className="pb-blob pb-blob-3" />
            <div className="pb-grid" />
          </div>
          <StoreProvider>
            <Nav />
            {children}
          </StoreProvider>
        </div>
        <Script src="/thinking-orbs.js" strategy="afterInteractive" />
        {ELEVENLABS_AGENT_ID ? (
          <>
            <elevenlabs-convai agent-id={ELEVENLABS_AGENT_ID} />
            <Script src="https://unpkg.com/@elevenlabs/convai-widget-embed" strategy="afterInteractive" />
          </>
        ) : null}
      </body>
    </html>
  );
}
