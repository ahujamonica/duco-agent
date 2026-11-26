/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: "#14243A", 700: "#1C304B", 600: "#27405F", 100: "#E7ECF3" },
        brand: { DEFAULT: "#3867D6", 600: "#2F56B4", 50: "#EEF3FE" },
        teal: { DEFAULT: "#16A39A", 600: "#0F867E", 50: "#E7F7F5" },
        ink: { DEFAULT: "#1F2937", muted: "#667085", soft: "#8A94A6" },
        canvas: "#F5F7FB",
        line: "#E6EAF2",
        amber: { DEFAULT: "#B7791F", 50: "#FFF8EB" },
        danger: { DEFAULT: "#C53030", 50: "#FEF2F2" },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Inter",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(20,36,58,.04), 0 8px 24px -16px rgba(20,36,58,.18)",
        lift: "0 18px 48px -20px rgba(20,36,58,.28)",
      },
      borderRadius: { xl2: "16px" },
      keyframes: {
        "fade-up": { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        pulseSoft: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".45" } },
        shimmer: { "0%": { backgroundPosition: "-300px 0" }, "100%": { backgroundPosition: "300px 0" } },
      },
      animation: {
        "fade-up": "fade-up .35s ease-out both",
        "pulse-soft": "pulseSoft 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
