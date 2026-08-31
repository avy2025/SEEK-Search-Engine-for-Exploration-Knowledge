/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        seek: {
          dark: '#0b0f19',
          card: '#131b2e',
          accent: '#3b82f6',
          purple: '#8b5cf6',
          border: '#1e293b'
        }
      }
    },
  },
  plugins: [],
}
