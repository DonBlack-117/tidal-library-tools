#!/usr/bin/env bash
# Compila static/css/app.css con Tailwind 3. Solo hace falta al cambiar clases
# en templates/ o static/js/; el CSS compilado va en el repo, así la web no
# necesita internet ni Node para correr.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
npx --yes tailwindcss@3 -c tailwind.config.js -i static/css/input.css -o static/css/app.css --minify
