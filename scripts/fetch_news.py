#!/usr/bin/env python3
"""
Descarga los feeds RSS definidos en config/sources.json, los limpia y publica
un JSON por pantalla en docs/data/.

Decisiones de diseno, todas nacidas de probar feeds reales:

- Los titulos llegan con entidades HTML y etiquetas incrustadas. Se limpian.
- Los items NO vienen ordenados por fecha (comprobado en Expansion). El orden
  cronologico se calcula aqui, nunca se confia en el orden del feed.
- Hay feeds que se quedan parados dias (comprobado en Marca). Se registra la
  antiguedad del item mas reciente para que la pantalla pueda avisar.
- Hay medios que sirven titulares tipo gancho, inutiles sin la foto y el clic.
  Se filtran por longitud minima y se penalizan por 'peso' en la config.
- Un fallo de un feed nunca puede tumbar la pantalla entera: cada feed se
  captura por separado y el resultado incluye el estado de cada uno.

Modo de ordenacion:
  portadas -> por prominencia (posicion en el feed x peso del medio)
  ultimas  -> por fecha de publicacion descendente
Se elige por hora local; se puede forzar con --modo.
"""

import argparse
import hashlib
import html
import json
import pathlib
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "sources.json"
SALIDA = RAIZ / "docs" / "data"

TZ = timezone(timedelta(hours=2))  # Europe/Madrid en horario de verano
UA = "Mozilla/5.0 (compatible; trmnl-dashboard/1.0; +https://github.com/)"
TIMEOUT = 20

LONGITUD_MINIMA_TITULAR = 30   # por debajo, casi siempre es un gancho
HORA_CAMBIO_MODO = 12          # antes: portadas; despues: ultimas
PALABRAS_VACIAS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "a", "ante", "con", "en", "para", "por", "sin", "sobre", "tras", "y", "o",
    "que", "se", "su", "sus", "lo", "es", "son", "ha", "han", "the", "of", "to",
}


# ---------------------------------------------------------------- utilidades

def limpiar(texto):
    """Quita etiquetas, deshace entidades HTML y normaliza espacios."""
    if not texto:
        return ""
    t = html.unescape(texto)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)                 # entidades dobles, las hay
    t = t.replace("\u00a0", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalizar(texto):
    """Version canonica para comparar titulares entre medios."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return [p for p in t.split() if len(p) > 2 and p not in PALABRAS_VACIAS]


def parsear_fecha(cadena):
    if not cadena:
        return None
    cadena = cadena.strip()
    try:
        d = parsedate_to_datetime(cadena)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for formato in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(cadena, formato)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def descargar(url):
    peticion = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "es,ca;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
        return respuesta.read()


# ------------------------------------------------------------------ extraer

def extraer_items(datos):
    """Devuelve [(titulo, enlace, fecha)] soportando RSS 2.0 y Atom."""
    raiz = ET.fromstring(datos)
    items = []

    for item in raiz.iter():
        etiqueta = item.tag.split("}")[-1]
        if etiqueta not in ("item", "entry"):
            continue

        titulo = enlace = fecha_txt = None
        for hijo in item:
            nombre = hijo.tag.split("}")[-1]
            if nombre == "title" and titulo is None:
                titulo = hijo.text
            elif nombre == "link" and enlace is None:
                enlace = hijo.get("href") or hijo.text
            elif nombre in ("pubDate", "published", "updated", "date") and fecha_txt is None:
                fecha_txt = hijo.text

        titulo = limpiar(titulo)
        if titulo:
            items.append((titulo, (enlace or "").strip(), parsear_fecha(fecha_txt)))

    return items


def leer_feed(feed):
    """Nunca lanza. Devuelve (lista_titulares, diagnostico)."""
    medio = feed["medio"]
    diagnostico = {"medio": medio, "url": feed["url"], "ok": False,
                   "items": 0, "error": None, "antiguedad_min": None}
    try:
        crudo = descargar(feed["url"])
    except urllib.error.HTTPError as e:
        diagnostico["error"] = f"HTTP {e.code}"
        return [], diagnostico
    except Exception as e:
        diagnostico["error"] = f"{type(e).__name__}: {e}"[:120]
        return [], diagnostico

    try:
        crudos = extraer_items(crudo)
    except ET.ParseError as e:
        diagnostico["error"] = f"XML invalido: {e}"[:120]
        return [], diagnostico

    ahora = datetime.now(timezone.utc)
    titulares, mas_reciente = [], None

    for posicion, (titulo, enlace, fecha) in enumerate(crudos):
        if len(titulo) < LONGITUD_MINIMA_TITULAR:
            continue                      # gancho, no titular
        if fecha and (mas_reciente is None or fecha > mas_reciente):
            mas_reciente = fecha
        titulares.append({
            "titulo": titulo,
            "medio": medio,
            "enlace": enlace,
            "fecha": fecha.astimezone(TZ).isoformat() if fecha else None,
            "_ts": fecha.timestamp() if fecha else 0.0,
            "_posicion": posicion,
            "_peso": float(feed.get("peso", 1.0)),
            "_clave": normalizar(titulo),
        })

    diagnostico["ok"] = True
    diagnostico["items"] = len(titulares)
    diagnostico["descartados_por_gancho"] = len(crudos) - len(titulares)
    if mas_reciente:
        diagnostico["antiguedad_min"] = int((ahora - mas_reciente).total_seconds() // 60)
    return titulares, diagnostico


# --------------------------------------------------------- deduplicar y ordenar

def parecidos(a, b):
    """Solape de Jaccard entre dos titulares normalizados."""
    ca, cb = set(a), set(b)
    if not ca or not cb:
        return 0.0
    return len(ca & cb) / len(ca | cb)


def agrupar(titulares, umbral=0.45):
    """Agrupa titulares que cuentan lo mismo. El grupo hereda el mejor item."""
    grupos = []
    for t in titulares:
        for g in grupos:
            if parecidos(t["_clave"], g["representante"]["_clave"]) >= umbral:
                g["miembros"].append(t)
                if t["_ts"] > g["representante"]["_ts"]:
                    g["representante"] = t
                break
        else:
            grupos.append({"representante": t, "miembros": [t]})

    for g in grupos:
        medios = []
        for m in g["miembros"]:
            if m["medio"] not in medios:
                medios.append(m["medio"])
        g["medios"] = medios
        g["consenso"] = len(medios)
    return grupos


def ordenar(grupos, modo):
    if modo == "ultimas":
        grupos.sort(key=lambda g: g["representante"]["_ts"], reverse=True)
    else:
        def prominencia(g):
            r = g["representante"]
            return (g["consenso"] * 2.0) + (r["_peso"] * 10.0 / (1 + r["_posicion"]))
        grupos.sort(key=prominencia, reverse=True)
    return grupos


# ------------------------------------------------------------------ pantalla

def construir(nombre, bloque, modo):
    todos, diagnosticos = [], []
    for feed in bloque["feeds"]:
        titulares, diag = leer_feed(feed)
        todos.extend(titulares)
        diagnosticos.append(diag)

    grupos = ordenar(agrupar(todos), modo)
    tope = bloque.get("max_titulares", 7)
    tope_medio = bloque.get("max_por_medio", 2)

    # Un medio que publica cada hora se come la pantalla entera en modo
    # cronologico mientras los que publican cada dos dias no salen nunca.
    # El tope por medio mantiene la diversidad; si al final faltan lineas,
    # se rellenan con lo descartado antes que dejar huecos.
    salida, usados, sobrantes = [], {}, []
    for g in grupos:
        r = g["representante"]
        principal = g["medios"][0]
        entrada = {
            "titular": r["titulo"],
            "medios": g["medios"][:3],
            "consenso": g["consenso"],
            "fecha": r["fecha"],
            "enlace": r["enlace"],
        }
        if usados.get(principal, 0) < tope_medio and len(salida) < tope:
            salida.append(entrada)
            usados[principal] = usados.get(principal, 0) + 1
        else:
            sobrantes.append(entrada)

    for entrada in sobrantes:
        if len(salida) >= tope:
            break
        salida.append(entrada)

    activos = [d for d in diagnosticos if d["ok"]]
    edades = [d["antiguedad_min"] for d in activos if d["antiguedad_min"] is not None]

    return {
        "pantalla": nombre,
        "titulo": bloque["titulo"],
        "modo": modo,
        "generado": datetime.now(TZ).isoformat(timespec="seconds"),
        "titulares": salida,
        "salud": {
            "feeds_totales": len(diagnosticos),
            "feeds_ok": len(activos),
            "feeds_caidos": [d["medio"] for d in diagnosticos if not d["ok"]],
            "antiguedad_minima_min": min(edades) if edades else None,
            "detalle": diagnosticos,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["auto", "portadas", "ultimas"], default="auto")
    ap.add_argument("--pantalla", help="procesar solo una pantalla")
    ap.add_argument("--salida", default=str(SALIDA))
    args = ap.parse_args()

    modo = args.modo
    if modo == "auto":
        modo = "portadas" if datetime.now(TZ).hour < HORA_CAMBIO_MODO else "ultimas"

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    destino = pathlib.Path(args.salida)
    destino.mkdir(parents=True, exist_ok=True)

    codigo = 0
    for nombre, bloque in config.items():
        if nombre.startswith("_"):
            continue
        if args.pantalla and nombre != args.pantalla:
            continue

        datos = construir(nombre, bloque, modo)
        (destino / f"{nombre}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

        salud = datos["salud"]
        print(f"{nombre:10s} modo={modo:8s} "
              f"feeds {salud['feeds_ok']}/{salud['feeds_totales']}  "
              f"titulares {len(datos['titulares'])}")
        for d in salud["detalle"]:
            if d["ok"]:
                edad = f"{d['antiguedad_min']} min" if d["antiguedad_min"] is not None else "sin fecha"
                print(f"    ok    {d['medio']:16s} {d['items']:3d} items  "
                      f"({d.get('descartados_por_gancho', 0)} ganchos)  ultimo hace {edad}")
            else:
                print(f"    FALLO {d['medio']:16s} {d['error']}")
        if salud["feeds_ok"] == 0:
            codigo = 1

    return codigo


if __name__ == "__main__":
    sys.exit(main())
