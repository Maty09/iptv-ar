#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys

import actualizar_lista as al


def enlaces_a_borrar(incluir_no_eliminar):
    """Devuelve el set de URLs (normalizadas) de eliminar.txt y enlaces_rotos.json."""
    desde_txt = set(al.leer_eliminar()[3])
    desde_json = set()
    omitidos = []
    for url, datos in al.cargar_rotos().items():
        if datos.get("eliminar") or incluir_no_eliminar:
            desde_json.add(url)
        else:
            omitidos.append(url)

    if omitidos:
        print(f"  (se ignoran {len(omitidos)} enlace(s) de enlaces_rotos.json con "
              f'"eliminar": false; usa --incluir-no-eliminar para sumarlos)')

    todos = desde_txt | desde_json
    print(f"Enlaces a borrar: {len(desde_txt)} en eliminar.txt + "
          f"{len(desde_json)} en enlaces_rotos.json "
          f"({len(todos)} unicos)\n")
    return {al.limpiar_url(u) for u in todos}


def leer_lineas(offline):
    lineas, ok = [], 0
    if not offline:
        for url in al.leer_urls():
            texto = al.descargar(url)
            if texto is not None:
                ok += 1
                lineas += texto.splitlines()
        if ok == 0:
            print("AVISO: no se pudo descargar ninguna lista, uso lista_final.m3u\n")

    if os.path.exists(al.ARCHIVO_EXTRAS):
        with open(al.ARCHIVO_EXTRAS, "r", encoding="utf-8") as f:
            lineas += [l.rstrip("\n") for l in f]

    if offline or ok == 0:
        if not os.path.exists(al.ARCHIVO_SALIDA):
            print(f"ERROR: tampoco existe {al.ARCHIVO_SALIDA}")
            sys.exit(1)
        with open(al.ARCHIVO_SALIDA, "r", encoding="utf-8") as f:
            lineas += [l.rstrip("\n") for l in f]
    return lineas


def extraer_canales(lineas):
    """Lista de (linea_extinf, url)."""
    canales, i = [], 0
    while i < len(lineas):
        if lineas[i].startswith("#EXTINF"):
            j = i + 1
            while j < len(lineas) and lineas[j].startswith("#"):
                j += 1
            if j < len(lineas):
                canales.append((lineas[i], lineas[j].strip()))
            i = j + 1
        else:
            i += 1
    return canales


def clave_parche(extinf, claves):
    """Misma prioridad que actualizar_lista.py: nombre normalizado, tvg-id, nombre exacto."""
    nombre = al.nombre_canal(extinf)
    m = re.search(r'tvg-id="([^"]*)"', extinf)
    tid = m.group(1).strip().lower() if m else ""
    for candidata in (al.normalizar(nombre), tid, al.sin_tildes(nombre)):
        if candidata and candidata in claves:
            return candidata
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="no modifica parches.json")
    ap.add_argument("--offline", action="store_true", help="no descarga, usa lista_final.m3u")
    ap.add_argument("--incluir-no-eliminar", action="store_true",
                    help='considera tambien enlaces_rotos.json con "eliminar": false')
    args = ap.parse_args()

    borrar = enlaces_a_borrar(args.incluir_no_eliminar)
    if not borrar:
        print("No hay enlaces para procesar. Nada que hacer.")
        return

    reglas = al.leer_eliminar()
    canales = extraer_canales(leer_lineas(args.offline))

    parches_orig = al.cargar_json(al.ARCHIVO_PARCHES)
    # clave normalizada -> claves reales en el JSON
    claves = {}
    for k in parches_orig:
        claves.setdefault(k.strip().lower(), []).append(k)

    usos = {}                 # clave -> {"borrados": set(nombres), "activos": set(nombres)}
    encontrados = set()       # enlaces a borrar que aparecen en alguna lista
    sin_parche = []

    for extinf, url in canales:
        es_enlace_borrado = al.limpiar_url(url) in borrar
        if es_enlace_borrado:
            encontrados.add(al.limpiar_url(url))

        clave = clave_parche(extinf, claves)
        if clave is None:
            if es_enlace_borrado:
                sin_parche.append(al.nombre_canal(extinf))
            continue

        se_elimina = es_enlace_borrado or al.debe_eliminarse(extinf, url, reglas)
        u = usos.setdefault(clave, {"borrados": set(), "activos": set()})
        (u["borrados"] if se_elimina else u["activos"]).add(al.nombre_canal(extinf))

    # Entradas que se pueden borrar: tienen algun enlace borrado y ningun canal activo
    a_borrar, conservadas = [], []
    for clave, u in usos.items():
        enlace_afectado = any(
            al.limpiar_url(url) in borrar
            for extinf, url in canales
            if clave_parche(extinf, claves) == clave
        )
        if not enlace_afectado:
            continue
        if u["activos"]:
            conservadas.append((clave, u))
        else:
            a_borrar.append(clave)

    # ---- Informe ----
    print("PARCHES A ELIMINAR (ya no queda ningun canal activo que los use):")
    if a_borrar:
        for c in sorted(a_borrar):
            for real in claves[c]:
                p = parches_orig[real]
                print(f"  - {real}")
                print(f"      logo:       {p.get('logo') or '(vacio)'}")
                print(f"      user_agent: {(p.get('user_agent') or '(vacio)')[:70]}")
    else:
        print("  (ninguno)")

    if conservadas:
        print("\nPARCHES CONSERVADOS (otros enlaces activos comparten el nombre):")
        for c, u in sorted(conservadas):
            print(f"  = {claves[c][0]}  ->  {len(u['activos'])} canal(es) activo(s)")

    if sin_parche:
        print(f"\nCanales con enlace borrado pero SIN entrada en parches.json: "
              f"{len(set(sin_parche))}")

    no_encontrados = borrar - encontrados
    if no_encontrados:
        print(f"\nEnlaces que no aparecen en ninguna lista ({len(no_encontrados)}):")
        for u in sorted(no_encontrados):
            print(f"  ? {u}")

    # ---- Escritura ----
    if not a_borrar:
        print("\nparches.json queda igual.")
        return

    if args.dry_run:
        print(f"\n[dry-run] Se eliminarian {sum(len(claves[c]) for c in a_borrar)} "
              f"entrada(s). No se modifico nada.")
        return

    nuevos = dict(parches_orig)
    for c in a_borrar:
        for real in claves[c]:
            nuevos.pop(real, None)

    with open(al.ARCHIVO_PARCHES, "w", encoding="utf-8") as f:
        json.dump(nuevos, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nListo. parches.json: {len(parches_orig)} -> {len(nuevos)} entradas.")


if __name__ == "__main__":
    main()
