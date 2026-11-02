/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        gray: {
          50: '#fafaf8',
          100: '#242622',
          200: '#343632',
          300: '#4e514c',
          400: '#656962',
          500: '#777a74',
          600: '#8d908a',
          700: '#a3a59f',
          800: '#c1c3bd',
          900: '#e1e2dd'
        },
        seek: {
          dark: '#f7f7f4',
          card: '#ffffff',
          accent: '#365c48',
          ink: '#242622',
          muted: '#777a74',
          soft: '#edf2ed',
          border: '#e4e6e0'
        }
      }
    },
  },
  plugins: [],
}
