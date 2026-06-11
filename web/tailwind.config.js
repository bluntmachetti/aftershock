/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // EOC palette
        slate: {
          950: '#0a0e1a',
          900: '#0f1624',
          800: '#1a2235',
          700: '#243047',
          600: '#2e3d5a',
        },
        amber: {
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
        },
        signal: {
          red: '#ef4444',
          'red-dim': '#7f1d1d',
        },
        phosphor: {
          green: '#4ade80',
          'green-dim': '#14532d',
        },
        cyan: {
          400: '#22d3ee',
          500: '#06b6d4',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        display: ['"Share Tech Mono"', 'monospace'],
        sans: ['"Share Tech"', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        glow: 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          from: { boxShadow: '0 0 4px #f59e0b40, 0 0 8px #f59e0b20' },
          to: { boxShadow: '0 0 8px #f59e0b80, 0 0 16px #f59e0b40' },
        },
      },
    },
  },
  plugins: [],
}
