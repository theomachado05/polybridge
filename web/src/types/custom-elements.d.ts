import type { CSSProperties, HTMLAttributes } from "react";

type CE = HTMLAttributes<HTMLElement> & { style?: CSSProperties; class?: string };

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      /** public/thinking-orbs.js (MIT port of github.com/Jakubantalik/thinking-orbs). */
      "thinking-orb": CE & { state?: string; size?: string | number; ink?: string; theme?: string; speed?: string | number; paused?: string };
    }
  }
}
