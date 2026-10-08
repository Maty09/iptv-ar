#!/usr/bin/env python3
"""
Actualizador de listas M3U (User Agents + Logos + Múltiples listas + Depuración por URL)
"""

import json
import os
import unicodedata
import re
import sys
import urllib.request

ARCHIVO_LISTAS = "listas.txt"
ARCHIVO_PARCHES = "parches.json"
ARCHIVO_EXTRAS = "canales_extra.m3u"
ARCHIVO_EPG = "epg.txt"
ARCHIVO_ELIMINAR = "eliminar.txt"
ARCHIVO_ROTOS = "enlaces_rotos.json"
ARCHIVO_SALIDA = "lista_final.m3u"


def cargar_json(ruta):
    if not os.path.exists(ruta):
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"\nERROR en {ruta}: JSON inválido (línea {e.lineno}, columna {e.colno}).")
            sys.exit(1)


def leer_urls():
    if os.path.exists(ARCHIVO_LISTAS):
        with open(ARCHIVO_LISTAS, "r", encoding="utf-8") as f:
            urls = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
            if urls:
                return urls
    print("ERROR: no hay listas configuradas en listas.txt")
    sys.exit(1)


def leer_epg():
    if not os.path.exists(ARCHIVO_EPG):
        return []
    with open(ARCHIVO_EPG, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def leer_eliminar():
    nombres, contiene, grupos, urls = set(), [], set(), set()
    if os.path.exists(ARCHIVO_ELIMINAR):
        with open(ARCHIVO_ELIMINAR, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith("#"):
                    continue
                bajo = l.lower()
                if bajo.startswith("http://") or bajo.startswith("https://"):
                    urls.add(l)
                elif bajo.startswith("contiene:"):
                    contiene.append(bajo[9:].strip())
                elif bajo.startswith("grupo:"):
                    grupos.add(bajo[6:].strip())
                else:
                    nombres.add(bajo)
    return nombres, contiene, grupos, urls


def cargar_rotos():
    datos = cargar_json(ARCHIVO_ROTOS)
    rotos = {}
    for url, v in datos.items():
        if isinstance(v, str):
            v = {"motivo": v}
        v.setdefault("eliminar", True)
        rotos[url.strip()] = v
    print(f"Enlaces marcados como rotos: {len(rotos)}")
    return rotos


def cargar_parches():
    datos = cargar_json(ARCHIVO_PARCHES)
    parches = {}
    for nombre, valor in datos.items():
        if isinstance(valor, str):
            valor = {"user_agent": valor}
        parches[nombre.strip().lower()] = valor
    print(f"Parches cargados: {len(parches)} canal(es).")
    return parches


def nombre_canal(extinf):
    return extinf.rsplit(",", 1)[1].strip() if "," in extinf else ""


def sin_tildes(texto):
    n = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn").strip()


def normalizar(nombre):
    n = sin_tildes(nombre)
    n = re.sub(r"\(\s*(\d{3,4}\s*[pi]|hd|fhd|uhd|sd|4k)\s*\)", " ", n)
    n = re.sub(r"\b(fhd|uhd|hd|sd|4k)\s*$", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def limpiar_url(url):
    """
    Normaliza la URL removiendo parámetros genéricos de consulta/sufijos
    como ?PlaylistM3UCL para detectar transmisiones duplicadas.
    """
    return url.strip().split("?PlaylistM3UCL")[0].strip()


def debe_eliminarse(extinf, url_canal, reglas):
    nombres, contiene, grupos, urls = reglas
    nombre = nombre_canal(extinf).lower()
    m = re.search(r'group-title="([^"]*)"', extinf)
    grupo = m.group(1).strip().lower() if m else ""
    return (nombre in nombres
            or url_canal in urls
            or any(c and c in nombre for c in contiene)
            or grupo in grupos)


def aplicar_atributo(extinf, atributo, valor):
    pattern = rf'{atributo}="[^"]*"'
    if re.search(pattern, extinf):
        return re.sub(pattern, f'{atributo}="{valor}"', extinf)
    if "," in extinf:
        cabecera, nombre = extinf.rsplit(",", 1)
        return f'{cabecera} {atributo}="{valor}",{nombre}'
    return extinf


def descargar(url):
    print(f"Descargando: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            texto = r.read().decode("utf-8", errors="replace")
            print(f"  OK, {len(texto.splitlines())} líneas")
            return texto
    except Exception as e:
        print(f"  AVISO: no se pudo descargar ({e}). Se omite esta lista.")
        return None


def procesar(lineas, parches, reglas, rotos):
    salida, usados = [], set()
    urls_vistas = set()
    rotos_vistos, informe = set(), []
    total = con_ua = con_logo = eliminados = duplicados_omitidos = 0

    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if not linea.startswith("#EXTINF"):
            salida.append(linea)
            i += 1
            continue

        # Extraer metadatos entre #EXTINF y la URL
        j = i + 1
        meta = []
        while j < len(lineas) and lineas[j].startswith("#"):
            meta.append(lineas[j])
            j += 1
        
        url_canal = lineas[j].strip() if j < len(lineas) else ""
        url_base = limpiar_url(url_canal)

        # Depuración: Evitar duplicados por URL de transmisión
        if url_base in urls_vistas:
            duplicados_omitidos += 1
            i = j + 1
            continue

        roto = rotos.get(url_canal) or rotos.get(url_base)
        if roto:
            rotos_vistos.add(url_canal)
            informe.append((nombre_canal(linea), url_canal, roto))

        # Verificar si se debe eliminar por regla o estar roto
        if (roto and roto["eliminar"]) or debe_eliminarse(linea, url_canal, reglas):
            eliminados += 1
            i = j + 1  # Saltar todo el bloque hasta pasada la URL
            continue

        urls_vistas.add(url_base)
        total += 1
        nombre = nombre_canal(linea)
        exacto = sin_tildes(nombre)
        base = normalizar(nombre)
        m = re.search(r'tvg-id="([^"]*)"', linea)
        tid = m.group(1).strip().lower() if m else ""

        # Búsqueda de parche
        parche = parches.get(base) or parches.get(tid) or parches.get(exacto)

        if parche:
            usados.add(base)
            if parche.get("logo"):
                linea = aplicar_atributo(linea, "tvg-logo", parche["logo"])
                con_logo += 1
            if parche.get("tvg_id"):
                linea = aplicar_atributo(linea, "tvg-id", parche["tvg_id"])
            if parche.get("user_agent"):
                meta = [m for m in meta if "http-user-agent" not in m.lower()]
                meta.append(f"#EXTVLCOPT:http-user-agent={parche['user_agent']}")
                con_ua += 1

        salida.append(linea)
        salida.extend(meta)
        if j < len(lineas):
            salida.append(lineas[j])
        
        i = j + 1

    print(f"\nCanales totales procesados: {total}")
    print(f"Canales duplicados eliminados: {duplicados_omitidos}")
    print(f"Con user agent aplicado: {con_ua}")
    print(f"Con logo aplicado: {con_logo}")
    print(f"Canales eliminados por filtros: {eliminados}")

    if informe:
        print("\nENLACES MARCADOS COMO ROTOS:")
        for nombre, url, r in informe:
            accion = "ELIMINADO" if r["eliminar"] else "se mantiene"
            print(f"  [{accion}] {nombre} -> {r.get('motivo', 'sin motivo')}")

    return salida


def main():
    epgs = leer_epg()
    epgs_origen, lineas = [], []
    ok = 0

    for url in leer_urls():
        texto = descargar(url)
        if texto is None:
            continue
        ok += 1
        for l in texto.splitlines():
            if l.startswith("#EXTM3U"):
                m = re.search(r'url-tvg="([^"]*)"', l)
                if m:
                    for u in m.group(1).split(","):
                        u = u.strip()
                        if u and u not in epgs_origen:
                            epgs_origen.append(u)
            else:
                lineas.append(l)

    if ok == 0:
        print("ERROR: no se pudo descargar ninguna lista.")
        sys.exit(1)

    if os.path.exists(ARCHIVO_EXTRAS):
        with open(ARCHIVO_EXTRAS, "r", encoding="utf-8") as f:
            extras = [l.rstrip("\n") for l in f if not l.startswith("#EXTM3U")]
        print(f"Canales extra sumados desde {ARCHIVO_EXTRAS}")
        lineas += extras

    final_epgs = epgs or epgs_origen
    cabecera = "#EXTM3U" + (f' url-tvg="{",".join(final_epgs)}"' if final_epgs else "")
    lineas.insert(0, cabecera)

    resultado = procesar(lineas, cargar_parches(), leer_eliminar(), cargar_rotos())
    
    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(resultado) + "\n")
        
    print(f"\nListo. Archivo generado: {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    main()
