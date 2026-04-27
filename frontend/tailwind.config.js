/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#070a0f',
        s1:      '#0d1117',
        s2:      '#131b24',
        s3:      '#1a2535',
        border:  '#1e2d3d',
        border2: '#243547',
        cyan:    '#00d4ff',
        green:   '#00e87a',
        yellow:  '#f5c400',
        red:     '#ff3b5c',
        orange:  '#ff7b00',
        text1:   '#c8d8e8',
        text2:   '#5a7080',
        text3:   '#3a5060',
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', 'monospace'],
        sans: ['"IBM Plex Sans"', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
