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


def cargar_parches_detectando_duplicados():
    """
    Carga parches.json sin perder las claves repetidas (json.load se queda
    en silencio con la ultima). Devuelve (dict_sin_repetidas, total_de_entradas,
    {clave: [valores en orden de aparicion]}).
    """
    if not os.path.exists(al.ARCHIVO_PARCHES):
        return {}, 0, {}
    llamadas = []

    def hook(pares):
        llamadas.append(pares)
        return dict(pares)

    try:
        with open(al.ARCHIVO_PARCHES, "r", encoding="utf-8") as f:
            datos = json.load(f, object_pairs_hook=hook)
    except json.JSONDecodeError as e:
        print(f"ERROR en {al.ARCHIVO_PARCHES}: JSON invalido "
              f"(linea {e.lineno}, columna {e.colno}).")
        sys.exit(1)

    pares = llamadas[-1] if llamadas else []   # el ultimo hook es el nivel superior
    apariciones = {}
    for k, v in pares:
        apariciones.setdefault(k, []).append(v)
    repetidas = {k: v for k, v in apariciones.items() if len(v) > 1}
    return datos, len(pares), repetidas


def clave_parche(extinf, claves):
    """Misma prioridad que actualizar_lista.py: nombre normalizado, tvg-id, nombre exacto."""
    nombre = al.nombre_canal(extinf)
    m = re.search(r'tvg-id="([^"]*)"', extinf)
    tid = m.group(1).strip().lower() if m else ""
    for candidata in (al.normalizar(nombre), tid, al.sin_tildes(nombre)):
        if candidata and candidata in claves:
            return candidata
    return None


def resumen(p):
    ua = (p.get("user_agent") or "")[:40]
    return f'logo={p.get("logo") or "-"} | ua={ua or "-"}'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="no modifica parches.json")
    ap.add_argument("--offline", action="store_true", help="no descarga, usa lista_final.m3u")
    ap.add_argument("--incluir-no-eliminar", action="store_true",
                    help='considera tambien enlaces_rotos.json con "eliminar": false')
    args = ap.parse_args()

    parches_orig, total_entradas, repetidas = cargar_parches_detectando_duplicados()

    # clave normalizada -> claves reales en el JSON
    claves = {}
    for k in parches_orig:
        claves.setdefault(al.sin_tildes(k), []).append(k)

    a_quitar = set()   # claves reales a borrar del JSON

    # ---------- 1) Duplicados ----------
    print("=== DUPLICADOS EN parches.json ===")
    hay = False
    for k, vals in repetidas.items():
        hay = True
        if all(v == vals[-1] for v in vals):
            print(f"  - \"{k}\" estaba {len(vals)} veces (identicas): se deja una.")
        else:
            print(f"  - \"{k}\" estaba {len(vals)} veces con contenido DISTINTO: "
                  f"se deja la ultima (la que ya usaba el actualizador)")
            for n, v in enumerate(vals, 1):
                print(f"      #{n}: {resumen(v)}")
    # mismo canal escrito distinto (mayusculas / tildes)
    for norm, reales in claves.items():
        if len(reales) < 2:
            continue
        hay = True
        valores = [parches_orig[r] for r in reales]
        if all(v == valores[-1] for v in valores):
            print(f"  - mismo canal escrito distinto, contenido igual: {reales}. "
                  f"Se deja \"{reales[-1]}\".")
            a_quitar.update(reales[:-1])
        else:
            print(f"  ! mismo canal escrito distinto y con contenido DISTINTO, "
                  f"NO se borra (revisar a mano): {reales}")
    if not hay:
        print("  (ninguno)")
    print()

    # ---------- 2) Enlaces eliminados ----------
    borrar = enlaces_a_borrar(args.incluir_no_eliminar)
    if not borrar:
        print("No hay enlaces para procesar en eliminar.txt / enlaces_rotos.json.")
    else:
        reglas = al.leer_eliminar()
        canales = extraer_canales(leer_lineas(args.offline))
        claves = {}
        for k in parches_orig:
            if k not in a_quitar:
                claves.setdefault(al.sin_tildes(k), []).append(k)

        usos = {}
        encontrados = set()
        sin_parche = []
        afectadas = set()

        for extinf, url in canales:
            es_borrado = al.limpiar_url(url) in borrar
            if es_borrado:
                encontrados.add(al.limpiar_url(url))
            clave = clave_parche(extinf, claves)
            if clave is None:
                if es_borrado:
                    sin_parche.append(al.nombre_canal(extinf))
                continue
            if es_borrado:
                afectadas.add(clave)
            se_elimina = es_borrado or al.debe_eliminarse(extinf, url, reglas)
            u = usos.setdefault(clave, {"borrados": set(), "activos": set()})
            (u["borrados"] if se_elimina else u["activos"]).add(al.nombre_canal(extinf))

        sueltas, conservadas = [], []
        for clave in afectadas:
            (conservadas if usos[clave]["activos"] else sueltas).append(clave)

        print("=== PARCHES DE ENLACES ELIMINADOS ===")
        print("Se eliminan (ya no queda ningun canal activo que los use):")
        if sueltas:
            for c in sorted(sueltas):
                for real in claves[c]:
                    p = parches_orig[real]
                    print(f"  - {real}")
                    print(f"      logo:       {p.get('logo') or '(vacio)'}")
                    print(f"      user_agent: {(p.get('user_agent') or '(vacio)')[:70]}")
                    a_quitar.add(real)
        else:
            print("  (ninguno)")

        if conservadas:
            print("\nSe conservan (otros enlaces activos comparten el nombre):")
            for c in sorted(conservadas):
                print(f"  = {claves[c][0]}  ->  {len(usos[c]['activos'])} canal(es) activo(s)")
        if sin_parche:
            print(f"\nCanales con enlace borrado pero SIN entrada en parches.json: "
                  f"{len(set(sin_parche))}")
        no_encontrados = borrar - encontrados
        if no_encontrados:
            print(f"\nEnlaces que no aparecen en ninguna lista ({len(no_encontrados)}):")
            for u in sorted(no_encontrados):
                print(f"  ? {u}")
        print()

    # ---------- 3) Escritura ----------
    nuevos = {k: v for k, v in parches_orig.items() if k not in a_quitar}
    hay_cambios = bool(repetidas) or bool(a_quitar)

    if not hay_cambios:
        print("parches.json queda igual.")
        return
    if args.dry_run:
        print(f"[dry-run] parches.json pasaria de {total_entradas} a {len(nuevos)} "
              f"entradas. No se modifico nada.")
        return

    with open(al.ARCHIVO_PARCHES, "w", encoding="utf-8") as f:
        json.dump(nuevos, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Listo. parches.json: {total_entradas} -> {len(nuevos)} entradas.")


if __name__ == "__main__":
    main()
