import type { CSSProperties, HTMLAttributes } from "react";

type CE = HTMLAttributes<HTMLElement> & { style?: CSSProperties; class?: string };

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "thinking-orb": CE & { state?: string; size?: string | number; ink?: string; theme?: string; speed?: string | number; paused?: string };
    }
  }
}
