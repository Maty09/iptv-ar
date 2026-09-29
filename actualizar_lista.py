#!/usr/bin/env python3
"""
Actualizador de lista M3U con User Agents personalizados
-----------------------------------------------------------
Qué hace:
  1. Descarga la lista M3U más reciente desde la URL que pongas abajo.
  2. Recorre canal por canal (cada bloque #EXTINF + URL).
  3. Si el nombre del canal coincide con una entrada de parches.json,
     le agrega (o reemplaza) la línea #EXTVLCOPT:http-user-agent=...
  4. Los canales que YA traían su propio user agent en la lista original
     NO se tocan (se respeta el que trae el repo), salvo que vos también
     los pongas en parches.json a propósito.
  5. Guarda el resultado en lista_final.m3u, que es el archivo que cargás
     en tu reproductor (VLC, TiviMate, Kodi, etc).

Cómo usarlo:
  1. Editá la variable URL_LISTA más abajo con el link "raw" de tu GitHub.
  2. Editá parches.json con los canales que necesitan un user agent.
  3. Corré:  python actualizar_lista.py
  4. Usá lista_final.m3u en tu reproductor.

Podés correr este script cada vez que quieras traer la versión más nueva
de la lista; tus parches se vuelven a aplicar solos.
"""

import json
import re
import urllib.request
import sys
import os

# ============ CONFIGURACIÓN ============
# Pegá acá el link RAW de tu lista en GitHub
# (el que empieza con https://raw.githubusercontent.com/...)
URL_LISTA = "PEGA_AQUI_TU_URL_RAW_DE_GITHUB"

ARCHIVO_PARCHES = "parches.json"
ARCHIVO_SALIDA = "lista_final.m3u"
# ========================================


def descargar_lista(url):
    print(f"Descargando lista desde:\n  {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as respuesta:
            contenido = respuesta.read().decode("utf-8", errors="replace")
        print(f"  OK, {len(contenido.splitlines())} líneas descargadas.")
        return contenido
    except Exception as e:
        print(f"ERROR al descargar la lista: {e}")
        sys.exit(1)


def cargar_parches(ruta):
    if not os.path.exists(ruta):
        print(f"Aviso: no existe {ruta} todavía, se crea uno vacío de ejemplo.")
        ejemplo = {
            "Nombre exacto del canal": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(ejemplo, f, indent=2, ensure_ascii=False)
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        datos = json.load(f)
    print(f"Parches cargados: {len(datos)} canal(es) con user agent personalizado.")
    return datos


def extraer_nombre_canal(linea_extinf):
    """
    De una línea #EXTINF:-1 tvg-id="..." ...,Nombre del canal
    devuelve solo "Nombre del canal" (lo que va después de la última coma).
    """
    if "," in linea_extinf:
        return linea_extinf.rsplit(",", 1)[1].strip()
    return ""


def procesar_lista(contenido, parches):
    lineas = contenido.splitlines()
    salida = []
    i = 0
    canales_parchados = 0
    canales_totales = 0

    while i < len(lineas):
        linea = lineas[i]

        if linea.startswith("#EXTINF"):
            canales_totales += 1
            nombre_canal = extraer_nombre_canal(linea)
            salida.append(linea)
            i += 1

            # Recolectar todas las líneas de metadata (#EXTVLCOPT, #KODIPROP, etc)
            # hasta llegar a la URL del stream
            lineas_meta = []
            while i < len(lineas) and lineas[i].startswith("#"):
                lineas_meta.append(lineas[i])
                i += 1

            # ¿Este canal tiene un parche definido?
            ua_nuevo = None
            for nombre_parche, user_agent in parches.items():
                if nombre_parche.strip().lower() == nombre_canal.strip().lower():
                    ua_nuevo = user_agent
                    break

            if ua_nuevo:
                # Sacar cualquier línea EXTVLCOPT de user-agent que ya existiera,
                # para no duplicar, y agregar la nueva
                lineas_meta = [
                    l for l in lineas_meta
                    if "http-user-agent" not in l.lower()
                ]
                lineas_meta.append(f"#EXTVLCOPT:http-user-agent={ua_nuevo}")
                canales_parchados += 1

            salida.extend(lineas_meta)

            # Ahora debería seguir la URL del stream
            if i < len(lineas):
                salida.append(lineas[i])
                i += 1
        else:
            salida.append(linea)
            i += 1

    print(f"\nCanales totales en la lista: {canales_totales}")
    print(f"Canales con user agent aplicado por parche: {canales_parchados}")
    return "\n".join(salida) + "\n"


def main():
    if URL_LISTA == "PEGA_AQUI_TU_URL_RAW_DE_GITHUB":
        print("ERROR: Todavía no configuraste la URL de tu lista.")
        print("Abrí este archivo con un editor de texto y reemplazá")
        print("la variable URL_LISTA por el link raw de tu GitHub.")
        sys.exit(1)

    contenido = descargar_lista(URL_LISTA)
    parches = cargar_parches(ARCHIVO_PARCHES)
    resultado = procesar_lista(contenido, parches)

    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        f.write(resultado)

    print(f"\nListo. Archivo generado: {ARCHIVO_SALIDA}")
    print("Cargá ese archivo en tu reproductor (VLC, TiviMate, Kodi, etc).")


if __name__ == "__main__":
    main()
