import type { Config } from "tailwindcss";

// Colours are CSS variables (app/globals.css) so light and dark mode share one set of classes
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), card: v("card"), line: v("line"), ink: v("ink"), muted: v("muted"),
        ok: v("ok"), bad: v("bad"), warn: v("warn"), info: v("info"),
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
} satisfies Config;
