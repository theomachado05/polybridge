// Brokerage and venue logos for the Connect and Profile screens. Only the simulator and Webull paper take orders
// (GET /account names the active one); every other brokerage card is a saved preference and is labelled so.
export const LOGO = (d: string) => `https://www.google.com/s2/favicons?domain=${d}&sz=128`;

export interface Broker { id: string; name: string; sub: string; domain: string; logo: string }
export const BROKERS: Broker[] = [
  { id: "webull", name: "Webull", sub: "Paper account. Orders go to this account.", domain: "webull.com" },
  { id: "alpaca", name: "Alpaca", sub: "Not connected. Preference only.", domain: "alpaca.markets" },
  { id: "ibkr", name: "Interactive Brokers", sub: "Not connected. Preference only.", domain: "interactivebrokers.com" },
  { id: "schwab", name: "Schwab", sub: "Not connected. Preference only.", domain: "schwab.com" },
  { id: "robinhood", name: "Robinhood", sub: "Not connected. Preference only.", domain: "robinhood.com" },
].map((b) => ({ ...b, logo: LOGO(b.domain) }));

/** The only brokerage the backend can route orders to (besides its built-in simulator). */
export const ROUTABLE_BROKER = "webull";
