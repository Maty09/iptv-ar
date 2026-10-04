#!/usr/bin/env python3
"""
Actualizador de listas M3U (user agents + logos + varias listas + canales extra)
--------------------------------------------------------------------------------
1. Lee las URLs de listas.txt (una por linea) y descarga cada lista.
   Si listas.txt no existe, usa URL_LISTA (compatibilidad con la version anterior).
2. Suma canales_extra.m3u (si existe) al final.
3. Aplica parches.json: por canal, user agent y/o logo.
4. Guarda todo junto en lista_final.m3u.
"""

import json
import os
import re
import sys
import urllib.request

# Solo se usa si NO existe listas.txt
URL_LISTA = "https://raw.githubusercontent.com/iptv-org/iptv/refs/heads/master/streams/ar.m3u"

ARCHIVO_LISTAS = "listas.txt"
ARCHIVO_PARCHES = "parches.json"
ARCHIVO_EXTRAS = "canales_extra.m3u"
ARCHIVO_EPG = "epg.txt"
ARCHIVO_ELIMINAR = "eliminar.txt"
ARCHIVO_ROTOS = "enlaces_rotos.json"
ARCHIVO_SALIDA = "lista_final.m3u"


def leer_urls():
    if os.path.exists(ARCHIVO_LISTAS):
        with open(ARCHIVO_LISTAS, "r", encoding="utf-8") as f:
            urls = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    elif URL_LISTA != "PEGA_AQUI_TU_URL_RAW_DE_GITHUB":
        urls = [URL_LISTA]
    else:
        urls = []
    if not urls:
        print("ERROR: no hay listas configuradas. Agrega URLs en listas.txt")
        sys.exit(1)
    return urls


def leer_epg():
    if not os.path.exists(ARCHIVO_EPG):
        return []
    with open(ARCHIVO_EPG, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def leer_eliminar():
    """Reglas de eliminar.txt. Formatos por linea:
       Nombre exacto del canal
       contiene: texto      (borra todo canal cuyo nombre incluya ese texto)
       grupo: Nombre        (borra todo un group-title)
    """
    nombres, contiene, grupos = set(), [], set()
    if os.path.exists(ARCHIVO_ELIMINAR):
        with open(ARCHIVO_ELIMINAR, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith("#"):
                    continue
                bajo = l.lower()
                if bajo.startswith("contiene:"):
                    contiene.append(bajo[9:].strip())
                elif bajo.startswith("grupo:"):
                    grupos.add(bajo[6:].strip())
                else:
                    nombres.add(bajo)
    return nombres, contiene, grupos


def cargar_rotos():
    """enlaces_rotos.json: link -> motivo (texto), o
       link -> {"motivo": "...", "eliminar": false}  (solo avisa, no borra)"""
    if not os.path.exists(ARCHIVO_ROTOS):
        return {}
    with open(ARCHIVO_ROTOS, "r", encoding="utf-8") as f:
        datos = json.load(f)
    rotos = {}
    for url, v in datos.items():
        if isinstance(v, str):
            v = {"motivo": v}
        v.setdefault("eliminar", True)
        rotos[url.strip()] = v
    print(f"Enlaces marcados como rotos: {len(rotos)}")
    return rotos


def debe_eliminarse(extinf, reglas):
    nombres, contiene, grupos = reglas
    nombre = nombre_canal(extinf).lower()
    m = re.search(r'group-title="([^"]*)"', extinf)
    grupo = m.group(1).strip().lower() if m else ""
    return (nombre in nombres
            or any(c and c in nombre for c in contiene)
            or grupo in grupos)


def poner_tvg_id(extinf, tvg_id):
    if re.search(r'tvg-id="[^"]*"', extinf):
        return re.sub(r'tvg-id="[^"]*"', f'tvg-id="{tvg_id}"', extinf)
    if "," in extinf:
        cabecera, nombre = extinf.rsplit(",", 1)
        return f'{cabecera} tvg-id="{tvg_id}",{nombre}'
    return extinf


def descargar(url):
    print(f"Descargando: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            texto = r.read().decode("utf-8", errors="replace")
        print(f"  OK, {len(texto.splitlines())} lineas")
        return texto
    except Exception as e:
        print(f"  AVISO: no se pudo descargar ({e}). Se omite esta lista.")
        return None


def cargar_parches():
    """Acepta dos formatos por canal:
       "Canal": "user agent"                              (formato viejo)
       "Canal": {"user_agent": "...", "logo": "..."}      (formato nuevo)
    """
    if not os.path.exists(ARCHIVO_PARCHES):
        print(f"Aviso: no existe {ARCHIVO_PARCHES}, se sigue sin parches.")
        return {}
    with open(ARCHIVO_PARCHES, "r", encoding="utf-8") as f:
        datos = json.load(f)
    parches = {}
    for nombre, valor in datos.items():
        if isinstance(valor, str):
            valor = {"user_agent": valor}
        parches[nombre.strip().lower()] = valor
    print(f"Parches cargados: {len(parches)} canal(es).")
    return parches


def nombre_canal(extinf):
    return extinf.rsplit(",", 1)[1].strip() if "," in extinf else ""


def poner_logo(extinf, logo):
    if re.search(r'tvg-logo="[^"]*"', extinf):
        return re.sub(r'tvg-logo="[^"]*"', f'tvg-logo="{logo}"', extinf)
    if "," in extinf:
        cabecera, nombre = extinf.rsplit(",", 1)
        return f'{cabecera} tvg-logo="{logo}",{nombre}'
    return extinf


def procesar(lineas, parches, reglas, rotos):
    salida, usados = [], set()
    rotos_vistos, informe = set(), []
    total = con_ua = con_logo = eliminados = 0
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if not linea.startswith("#EXTINF"):
            salida.append(linea)
            i += 1
            continue

        j = i + 1
        while j < len(lineas) and lineas[j].startswith("#"):
            j += 1
        url_canal = lineas[j].strip() if j < len(lineas) else ""
        roto = rotos.get(url_canal)
        if roto:
            rotos_vistos.add(url_canal)
            informe.append((nombre_canal(linea), url_canal, roto))

        if (roto and roto["eliminar"]) or debe_eliminarse(linea, reglas):
            eliminados += 1
            i += 1
            while i < len(lineas) and lineas[i].startswith("#"):
                i += 1
            i += 1  # salta la URL del stream
            continue

        total += 1
        clave = nombre_canal(linea).lower()
        parche = parches.get(clave)
        meta = []
        i += 1
        while i < len(lineas) and lineas[i].startswith("#"):
            meta.append(lineas[i])
            i += 1

        if parche:
            usados.add(clave)
            if parche.get("logo"):
                linea = poner_logo(linea, parche["logo"])
                con_logo += 1
            if parche.get("tvg_id"):
                linea = poner_tvg_id(linea, parche["tvg_id"])
            if parche.get("user_agent"):
                meta = [m for m in meta if "http-user-agent" not in m.lower()]
                meta.append(f"#EXTVLCOPT:http-user-agent={parche['user_agent']}")
                con_ua += 1

        salida.append(linea)
        salida.extend(meta)
        if i < len(lineas):
            salida.append(lineas[i])
            i += 1

    print(f"\nCanales totales: {total}")
    print(f"Con user agent aplicado: {con_ua}")
    print(f"Con logo aplicado: {con_logo}")
    print(f"Canales eliminados: {eliminados}")
    if informe:
        print("\nENLACES MARCADOS COMO ROTOS:")
        for nombre, url, r in informe:
            accion = "ELIMINADO" if r["eliminar"] else "se mantiene"
            print(f"  [{accion}] {nombre} -> {r.get('motivo', 'sin motivo')}")
    ya_no = [u for u in rotos if u not in rotos_vistos]
    if ya_no:
        print("\nEstos enlaces de enlaces_rotos.json ya no estan en la lista (se pueden borrar del archivo):")
        for u in ya_no:
            print(f"  - {u}")
    faltan = [k for k in parches if k not in usados]
    if faltan:
        print("\nAVISO: estos parches no coincidieron con ningun canal:")
        for k in faltan:
            print(f"  - {k}")
    return salida


def main():
    epgs = leer_epg()
    cabecera = "#EXTM3U"
    if epgs:
        cabecera += f' url-tvg="{",".join(epgs)}"'
        print(f"EPG configurado: {len(epgs)} fuente(s).")
    lineas = [cabecera]
    ok = 0
    for url in leer_urls():
        texto = descargar(url)
        if texto is None:
            continue
        ok += 1
        lineas += [l for l in texto.splitlines() if not l.startswith("#EXTM3U")]

    if ok == 0:
        print("ERROR: no se pudo descargar ninguna lista.")
        sys.exit(1)

    if os.path.exists(ARCHIVO_EXTRAS):
        with open(ARCHIVO_EXTRAS, "r", encoding="utf-8") as f:
            extras = [l.rstrip("\n") for l in f if not l.startswith("#EXTM3U")]
        print(f"Canales extra sumados desde {ARCHIVO_EXTRAS}")
        lineas += extras

    resultado = procesar(lineas, cargar_parches(), leer_eliminar(), cargar_rotos())
    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(resultado) + "\n")
    print(f"\nListo. Archivo generado: {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    main()
