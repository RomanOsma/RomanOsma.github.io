#!/usr/bin/env python3
"""Actualiza data/tutorias.json con las grabaciones del repositorio de contenidos digitales de la UNED.

Lo ejecuta GitHub Actions cada día (.github/workflows/actualizar-tutorias.yml) y también se puede lanzar a mano:
    python scripts/actualizar_tutorias.py

1. Vuelve a leer las carpetas vigiladas (CARPETAS) y añade los vídeos nuevos.
2. Busca carpetas nuevas del curso actual de cada asignatura (descubrimiento) y las apunta en "nuevas".
Nunca borra datos: si una descarga falla o la página cambia de forma, se conserva lo anterior.
"""
import datetime
import html
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = 'https://contenidosdigitales.uned.es'
UA = 'panel-uned-actualizador/1.0 (estudiante UNED; consulta diaria de pocas paginas)'
OUT = pathlib.Path(__file__).resolve().parent.parent / 'data' / 'tutorias.json'
CARPETAS = ['45970', '37572', '45509', '39058', '53847']
CODIGOS = {   # código del panel → códigos con los que puede aparecer en el título de la carpeta
    '71031010': ['71031010'], '71031027': ['71031027'], '71031033': ['71031033', '71901037'], '7103104-': ['7103104-'],
    '71901020': ['71901020'], '71031056': ['71031056'], '71031062': ['71031062', '71901072'], '71031079': ['71031079'],
    '71031085': ['71031085'], '71031091': ['71031091'], '7103110-': ['7103110-'],
}
AREAS = {'71031033': 'Lógica y Estructuras Discretas', '71901020': 'Fundamentos de Programación'}
NOMBRES = {
    '71031010': 'Fundamentos de Cálculo para la IA', '71031027': 'Fundamentos Algebraicos para la IA', '7103104-': 'Fundamentos de Computadores',
    '71031056': 'Fundamentos de Estadística para la IA', '71031062': 'Programación Orientada a Objetos', '71031079': 'Introducción a la Inteligencia Artificial',
    '71031085': 'Fundamentos de Autómatas, Gramáticas y Lenguajes', '71031091': 'Adquisición, Procesado y Tratamiento de la Información', '7103110-': 'Redes',
}
DEGREES = ['GRADO EN INGENIERÍA EN INTELIGENCIA ARTIFICIAL', 'GRADO EN INGENIERÍA EN TECNOLOGÍAS DE LA INFORMACIÓN', 'GRADO EN INGENIERÍA INFORMÁTICA']
MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
MAX_PETICIONES, PAUSA, MAX_PAGINAS, MAX_DETALLES = 70, 1.5, 12, 4
peticiones = 0


def pedir(url):
    global peticiones
    if peticiones >= MAX_PETICIONES:
        return None
    peticiones += 1
    time.sleep(PAUSA)
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'es'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:   # red caída, 404, bloqueo…: se conserva lo anterior
            print(f'  aviso: {url} -> {e}', file=sys.stderr)
            time.sleep(3)
    return None


def texto(fragmento):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', fragmento))).strip()


def fecha_de(t):
    m = re.search(r'\b(20\d{2})(\d{2})(\d{2})(\d?)\b', t)
    if m:
        try:
            d = datetime.date(int(m[1]), int(m[2]), int(m[3]))
            return f"{'~' if m[4] else ''}{d.day} {MESES[d.month - 1]} {d.year}"   # «~»: el repositorio trae una errata en la fecha
        except ValueError:
            pass
    m = re.search(r'\b(20\d{2})-(\d{2})-(\d{2})\b', t)
    if m:
        try:
            d = datetime.date(int(m[1]), int(m[2]), int(m[3]))
            return f'{d.day} {MESES[d.month - 1]} {d.year}'
        except ValueError:
            pass
    return ''


def limpiar_titulo(t):
    t = re.sub(r'\b20\d{6,7}\b[.\s-]*', '', t)
    return re.sub(r'\s+', ' ', t).strip(' .-·')[:160]


def videos_de(pagina):
    """[[titulo, id, fecha], ...] de una página de listado (carpeta o búsqueda)."""
    marcas = [(m.start(), m.group(1)) for m in re.finditer(r'cadena-campus_(\d+)', pagina)]
    out, vistos = [], set()
    for i, (pos, vid) in enumerate(marcas):
        if vid in vistos:
            continue
        vistos.add(vid)
        fin = next((p for p, v in marcas[i + 1:] if v != vid), min(len(pagina), pos + 2500))
        zona = pagina[max(0, pos - 300):fin]
        titulos = [texto(m.group(1)) for m in re.finditer(r'<a[^>]+cadena-campus_%s[^>]*>(.*?)</a>' % vid, zona, re.S)]
        titulo = max(titulos, key=len) if titulos else ''
        out.append([limpiar_titulo(titulo) or f'Grabación {vid}', vid, fecha_de(texto(pagina[pos:fin]))])
    return out


def carpeta(term):
    """Todos los vídeos de una carpeta (recorre las páginas ?page=N)."""
    todos, vistos = [], set()
    for n in range(MAX_PAGINAS):
        pagina = pedir(f'{BASE}/taxonomy/term/{term}' + (f'?page={n}' if n else ''))
        if not pagina:
            break
        nuevos = [v for v in videos_de(pagina) if v[1] not in vistos]
        if not nuevos:
            break
        vistos.update(v[1] for v in nuevos)
        todos += nuevos
    titulo = ''
    if todos and pagina:
        m = re.search(r'<h1[^>]*>(.*?)</h1>', pagina, re.S)
        titulo = texto(m.group(1)) if m else ''
    return todos, titulo


def fusionar(previos, nuevos):
    """Une por id: nunca se pierde un vídeo ya guardado; título y fecha nuevos solo si no están vacíos."""
    por_id = {v[1]: list(v) for v in previos}
    for t, vid, f in nuevos:
        a = por_id.setdefault(vid, [t, vid, f])
        if t and not t.startswith('Grabación '):
            a[0] = t
        if f:
            a[2] = f
    return sorted(por_id.values(), key=lambda v: int(v[1]))


def url_busqueda(code, desde, hasta):
    f = [f'f%5B{i}%5D=degree_sbp%3A' + urllib.parse.quote_plus(d) for i, d in enumerate(DEGREES)]
    f += [f'f%5B3%5D=language_repo_sbp%3A' + urllib.parse.quote_plus('Español'), 'f%5B4%5D=model_sbp%3A6277']
    area, nombre = AREAS.get(code), NOMBRES.get(code, '')
    if area:
        f.append('f%5B5%5D=subject_area_sbp%3A' + urllib.parse.quote_plus(area))
    texto_libre = '' if area else urllib.parse.quote_plus(nombre)
    return f'{BASE}/search-basic-cw?search_api_fulltext={texto_libre}&field_creation_date%5Bmin%5D={desde}&field_creation_date%5Bmax%5D={hasta}&' + '&'.join(f)


def descubrir(hoy, conocidas):
    """Carpetas nuevas del curso actual para cada asignatura (mejor esfuerzo)."""
    desde = f'{hoy.year if hoy.month >= 9 else hoy.year - 1}-10-01'
    encontradas = {}
    for code in CODIGOS:
        pagina = pedir(url_busqueda(code, desde, hoy.isoformat()))
        ids = list(dict.fromkeys(re.findall(r'cadena-campus_(\d+)', pagina or '')))
        cubiertos = set()
        for vid in ids[:MAX_DETALLES * 3]:
            if vid in cubiertos or len(cubiertos) >= MAX_DETALLES * 20:
                continue
            detalle = pedir(f'{BASE}/recurso/cadena-campus_{vid}')
            for term, titulo in re.findall(r'<a[^>]+href="[^"]*/taxonomy/term/(\d+)"[^>]*>([^<]+)</a>', detalle or ''):
                m = re.search(r'\(([\d;\-]+)\)\s*$', titulo.strip())
                if term in conocidas or term in encontradas or not m or not set(m[1].split(';')) & set(CODIGOS[code]):
                    continue
                videos, h1 = carpeta(term)
                if videos:
                    cubiertos.update(v[1] for v in videos)
                    curso = f"curso {hoy.year if hoy.month >= 9 else hoy.year - 1}/{str(hoy.year + (1 if hoy.month >= 9 else 0))[2:]}"
                    encontradas[term] = {'code': code, 'term': int(term), 't': f'{texto(titulo)} · {curso}', 'videos': videos}
    return encontradas


def main():
    hoy = datetime.date.today()
    previo = json.loads(OUT.read_text(encoding='utf8')) if OUT.exists() else {}
    series = dict(previo.get('series', {}))
    nuevas = {str(n['term']): n for n in previo.get('nuevas', []) if isinstance(n, dict) and 'term' in n}
    for term in CARPETAS:
        videos, _ = carpeta(term)
        if videos:
            series[term] = {'videos': fusionar(series.get(term, {}).get('videos', []), videos)}
        print(f'carpeta {term}: {len(videos)} vídeos leídos, {len(series.get(term, {}).get("videos", []))} guardados')
    for term, n in descubrir(hoy, set(CARPETAS)).items():
        previos = nuevas.get(term, {}).get('videos', [])
        nuevas[term] = {**n, 'videos': fusionar(previos, n['videos'])}
        print(f'carpeta nueva {term} ({n["code"]}): {len(nuevas[term]["videos"])} vídeos')
    for term in list(nuevas):                                   # las nuevas que pasan a vigilarse a mano se retiran de "nuevas"
        if term in CARPETAS:
            del nuevas[term]
    datos = {'series': series, 'nuevas': sorted(nuevas.values(), key=lambda n: n['term'])}
    anterior = {k: previo.get(k) for k in ('series', 'nuevas')}
    if datos != anterior or not OUT.exists():
        datos = {'actualizado': hoy.isoformat(), **datos}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + '\n', encoding='utf8')
        print('data/tutorias.json actualizado')
    else:
        print('Sin cambios')
    print(f'peticiones realizadas: {peticiones}')


if __name__ == '__main__':
    main()
