# tidal-library-tools

Conjunto de scripts en Python para gestionar tu biblioteca musical en Tidal usando la API no oficial [`tidalapi`](https://github.com/tamland/python-tidal).

## Herramientas incluidas

| Script | Descripción |
|--------|-------------|
| `sincronizar_tidal.py` | Busca canciones de tu carpeta local en Tidal y las agrega a *My Tracks* |
| `mejorar_calidad_tidal.py` | Reemplaza canciones en *My Tracks* por versiones de mayor calidad de audio |
| `limpiar_duplicados_tidal.py` | Detecta y elimina canciones duplicadas en *My Tracks* |

## Requisitos

- Python 3.8 o superior
- Cuenta de Tidal (HiFi o HiFi Plus recomendado)

## Instalación

```bash
pip install tidalapi
```

## Uso

Cada script se ejecuta de forma independiente. Al correrlo por primera vez, se abrirá el navegador para que inicies sesión en Tidal.

```bash
# Sincronizar música local con Tidal
python sincronizar_tidal.py

# Mejorar calidad de audio de tu biblioteca
python mejorar_calidad_tidal.py

# Eliminar duplicados
python limpiar_duplicados_tidal.py
```

## Notas

- Los scripts respetan un límite de velocidad (`RATE_LIMIT_DELAY`) para no saturar la API de Tidal.
- El archivo de sesión (`tidal-session.json`) guarda tu autenticación localmente y está excluido del repositorio por seguridad.
- Los archivos `.txt` de resultados también están excluidos del repositorio.
