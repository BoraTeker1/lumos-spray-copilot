/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,jsx}",
    "./components/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ---------------------------------------------------------------
        // Foundation. Canvas is a warm, faintly green-shifted gray so the
        // white record surfaces read as documents sitting on a desk rather
        // than as panels on a blue-gray admin console.
        // ---------------------------------------------------------------
        canvas: "#F5F7F4",
        surface: "#FFFFFF",
        ink: "#17211B",
        muted: "#66736C",
        line: "#DCE2DC",
        // Focus is deliberately BLUE, not brand green: a focus ring must never
        // be confused with an approval state.
        focus: "#2E7CF6",

        // Brand green. The `leaf` name is kept (rather than adding a parallel
        // `brand` scale) so the ~100 existing `bg-leaf-*` / `text-leaf-700`
        // call sites re-skin from this one place. Darker and less saturated
        // than the old #16a34a — this product signs off on pesticide records.
        leaf: {
          DEFAULT: "#1F7A45",
          50: "#E6F4EA",
          100: "#D3EADD",
          600: "#1F7A45",
          700: "#176437",
          800: "#0F4D2A",
        },

        // ---------------------------------------------------------------
        // Semantic status pairs. Foreground/background are specified together
        // because they are only ever contrast-checked as a pair. `review` is
        // purple and separate from `info` blue on purpose: "a human must sign
        // this" is a different state from "here is some context".
        // ---------------------------------------------------------------
        ok: { fg: "#176437", bg: "#E6F4EA", line: "#BFE0CC" },
        risk: { fg: "#B42318", bg: "#FDECEA", line: "#F5C4BE" },
        warn: { fg: "#B54708", bg: "#FEF3E6", line: "#F3D0A8" },
        inspect: { fg: "#C56B17", bg: "#FEF0E5", line: "#F4CDA6" },
        review: { fg: "#6941C6", bg: "#F4F3FF", line: "#D9D2FB" },
        info: { fg: "#175CD3", bg: "#EEF4FF", line: "#C3D6F9" },
        draft: { fg: "#344054", bg: "#F2F4F7", line: "#D6DAE1" },
      },
      borderRadius: {
        control: "6px",
        card: "8px",
        drawer: "12px",
      },
      fontFamily: {
        // System stack by design: no webfont request at build or run time.
        // The repo ships no local font file, and a Google Fonts fetch would
        // add a build-time network dependency.
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      fontSize: {
        title: ["32px", { lineHeight: "40px", letterSpacing: "-0.02em" }],
        section: ["18px", { lineHeight: "24px", letterSpacing: "-0.01em" }],
        body: ["14px", { lineHeight: "20px" }],
        meta: ["12px", { lineHeight: "16px" }],
      },
    },
  },
  plugins: [],
};
