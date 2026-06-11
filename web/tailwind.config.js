/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // --- Semantic EOC tokens (single source: :root RGB-channel vars in
        // index.css). Use rgb(var(--x) / <alpha-value>) so opacity utilities
        // like bg-eoc-surface/40 and text-eoc-secondary work. ---
        // One `eoc` color group drives every utility prefix from the same RGB
        // channels: bg-eoc-{ground,surface,raised,border}, border-eoc-border,
        // and the text family text-eoc-{primary,secondary,dim,faint}. The text
        // and surface keys never collide because they're addressed by different
        // utility prefixes (bg-/border- vs text-).
        eoc: {
          ground: 'rgb(var(--eoc-ground) / <alpha-value>)',
          surface: 'rgb(var(--eoc-surface) / <alpha-value>)',
          raised: 'rgb(var(--eoc-raised) / <alpha-value>)',
          border: 'rgb(var(--eoc-border) / <alpha-value>)',
          // text family — primary value text; secondary/dim share #94a3b8;
          // faint (#475569) reserved for NON-text decoration only.
          primary: 'rgb(var(--text-eoc-primary) / <alpha-value>)',
          secondary: 'rgb(var(--text-eoc-secondary) / <alpha-value>)',
          dim: 'rgb(var(--text-eoc-secondary) / <alpha-value>)',
          faint: 'rgb(var(--text-eoc-faint) / <alpha-value>)',
        },
        signal: {
          amber: 'rgb(var(--signal-amber) / <alpha-value>)',
          red: 'rgb(var(--signal-red) / <alpha-value>)',
          green: 'rgb(var(--signal-green) / <alpha-value>)',
          cyan: 'rgb(var(--signal-cyan) / <alpha-value>)',
          // Legacy dim alias preserved for components not yet migrated.
          'red-dim': '#7f1d1d',
        },
        // --- Legacy palette (kept so un-migrated components keep compiling;
        // surfaces migrate themselves off these). ---
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
