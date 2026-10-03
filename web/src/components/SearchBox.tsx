"use client";

import { useState } from "react";
import { Btn } from "./ui";

export function SearchBox({ initial, onSearch }: { initial: string; onSearch: (q: string) => void }) {
  const [v, setV] = useState(initial);
  return (
    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (v.trim()) onSearch(v.trim()); }}>
      <input
        aria-label="Search"
        value={v}
        onChange={(e) => setV(e.target.value)}
        placeholder="A prediction-market question, a ticker (ABNB), or a filing type (Results of Operations)"
        className="flex-1 rounded-full border border-white/80 bg-white/80 px-5 py-2.5 text-sm shadow-sm outline-none focus:ring-2 focus:ring-indigo-300"
      />
      <Btn onClick={() => onSearch(v.trim())} disabled={!v.trim()}>Search</Btn>
    </form>
  );
}
