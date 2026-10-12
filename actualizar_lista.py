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

# --- Canales repetidos ---
# Si un canal aparece con varios enlaces (mismo nombre, distinta resolucion), el de mejor
# resolucion queda en su categoria y los demas pasan a la categoria de respaldos.
AGRUPAR_RESPALDOS = True
CATEGORIA_RESPALDOS = "Respaldos"
# Quita la resolucion del nombre mostrado: "A24 (1080p)" -> "A24"
LIMPIAR_RESOLUCION_EN_NOMBRE = True


def cargar_json(ruta):
    if not os.path.exists(ruta):
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"\nERROR en {ruta}: JSON inválido (línea {e.lineno}, columna {e.colno}).")
            sys.exit(1)


def leer_listas():
    """
    Lee listas.txt. Una lista por linea:
        URL_de_la_lista
        URL_de_la_lista | URL_del_EPG        (EPG propio de esa lista)
        URL_de_la_lista | EPG_1,EPG_2        (varios EPG)
    Devuelve [(url_lista, [epgs])].
    """
    if os.path.exists(ARCHIVO_LISTAS):
        listas = []
        with open(ARCHIVO_LISTAS, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith("#"):
                    continue
                url, _, resto = l.partition("|")
                epgs = [e.strip() for e in resto.split(",") if e.strip()]
                listas.append((url.strip(), epgs))
        if listas:
            return listas
    print("ERROR: no hay listas configuradas en listas.txt")
    sys.exit(1)


def leer_urls():
    return [url for url, _ in leer_listas()]


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
        parches[sin_tildes(nombre)] = valor
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


RE_RESOLUCION = re.compile(r"\s*\(\s*(\d{3,4})\s*[pi]\s*\)", re.I)


def resolucion(nombre):
    """Resolucion indicada en el nombre ((1080p), (720p), 4K...). 0 si no dice."""
    m = RE_RESOLUCION.search(nombre)
    if m:
        return int(m.group(1))
    if re.search(r"\b4k\b", nombre, re.I):
        return 2160
    return 0


def clave_canal(nombre):
    """Mismo canal = mismo nombre sin resolucion, tildes, mayusculas ni [etiquetas]."""
    n = re.sub(r"\[[^\]]*\]", " ", normalizar(nombre))
    return re.sub(r"\s+", " ", n).strip()


def renombrar(extinf, nuevo):
    if "," not in extinf:
        return extinf
    return f"{extinf.rsplit(',', 1)[0]},{nuevo}"


def organizar(items):
    """
    Ordena los canales repetidos por resolucion (desc.) y, en empate, por orden de
    aparicion. Aplica el nombre limpio y envia los respaldos a su categoria.
    Devuelve la lista final de lineas.
    """
    grupos = {}
    for it in items:
        if it[0] == "canal" and it[1]["clave"]:
            grupos.setdefault(it[1]["clave"], []).append(it[1])

    con_respaldo = 0
    respaldos = []
    for clave, lista in grupos.items():
        lista.sort(key=lambda c: (-c["res"], c["idx"]))
        if len(lista) > 1:
            con_respaldo += 1
            print(f"  {RE_RESOLUCION.sub('', lista[0]['nombre']).strip()}: 1 principal + {len(lista) - 1} respaldo(s)")
        for pos, c in enumerate(lista):
            c["pos"] = pos

    salida = []
    for it in items:
        if it[0] == "txt":
            salida.append(it[1])
            continue
        c = it[1]
        bloque = c["bloque"]
        nombre = limpiar = c["nombre"]
        if LIMPIAR_RESOLUCION_EN_NOMBRE:
            limpiar = RE_RESOLUCION.sub("", nombre).strip() or nombre
        pos = c.get("pos", 0)
        if pos > 0:
            limpiar = f"{limpiar} ({pos + 1})"
        if LIMPIAR_RESOLUCION_EN_NOMBRE or pos > 0:
            bloque[0] = renombrar(bloque[0], limpiar)
        if AGRUPAR_RESPALDOS and pos > 0:
            bloque[0] = aplicar_atributo(bloque[0], "group-title", CATEGORIA_RESPALDOS)
            respaldos.append(c)
        else:
            salida.extend(bloque)

    for c in sorted(respaldos, key=lambda c: (c["clave"], c["pos"])):
        salida.extend(c["bloque"])

    print(f"Canales con respaldo: {con_respaldo} | enlaces en '{CATEGORIA_RESPALDOS}': "
          f"{len(respaldos)}")
    return salida


def procesar(lineas, parches, reglas, rotos):
    salida, usados = [], set()
    urls_vistas = set()
    rotos_vistos, informe = set(), []
    total = con_ua = con_logo = eliminados = duplicados_omitidos = 0

    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if not linea.startswith("#EXTINF"):
            salida.append(("txt", linea))
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

        bloque = [linea] + meta + ([lineas[j]] if j < len(lineas) else [])
        salida.append(("canal", {"bloque": bloque, "nombre": nombre,
                                 "clave": clave_canal(nombre),
                                 "res": resolucion(nombre), "idx": total}))
        
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

    return organizar(salida)


def main():
    epgs = leer_epg()
    epgs_origen, epgs_propios, lineas = [], [], []
    ok = 0

    for url, epgs_lista in leer_listas():
        texto = descargar(url)
        if texto is None:
            continue
        ok += 1
        if epgs_lista:
            print(f"  EPG propio de esta lista: {', '.join(epgs_lista)}")
            for e in epgs_lista:
                if e not in epgs_propios:
                    epgs_propios.append(e)
        for l in texto.splitlines():
            if l.startswith("#EXTM3U"):
                m = re.search(r'url-tvg="([^"]*)"', l)
                # Si la lista tiene EPG propio en listas.txt, no se usa el que trae en su cabecera
                if m and not epgs_lista:
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

    # epg.txt (global) manda sobre los EPG de cabecera de las listas; los EPG propios
    # definidos en listas.txt (URL | EPG) se suman siempre.
    final_epgs = list(dict.fromkeys((epgs or epgs_origen) + epgs_propios))
    cabecera = "#EXTM3U" + (f' url-tvg="{",".join(final_epgs)}"' if final_epgs else "")
    lineas.insert(0, cabecera)

    resultado = procesar(lineas, cargar_parches(), leer_eliminar(), cargar_rotos())
    
    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(resultado) + "\n")
        
    print(f"\nListo. Archivo generado: {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    main()
