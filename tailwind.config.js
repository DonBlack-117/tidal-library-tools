// Configuración de Tailwind 3. Compilar con: scripts/construir-css.sh
module.exports = {
  content: ['./templates/**/*.html', './static/js/**/*.js'],
  theme: {
    extend: {
      colors: {
        ink:    '#0E1012',   // fondo
        panel:  '#14171A',   // superficies
        raised: '#1A1E22',   // controles
        line:   '#252A2F',   // bordes
        mute:   '#7D868F',   // texto secundario
        soft:   '#A9B1B8',   // texto de apoyo
        accent: '#7CC6D6',   // único acento
      },
      fontFamily: {
        sans: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"Geist Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
}
