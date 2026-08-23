# trmnl-dashboard

Datos para las pantallas de un TRMNL X (1872 × 1404, 16 grises).

GitHub Actions descarga y prepara los datos, los publica como JSON estático en
GitHub Pages, y TRMNL los consume como *polling URL* de un Private Plugin que
los renderiza con una plantilla Liquid. Sin intervención manual en ningún punto.

```
Actions (cron)  →  scripts/*.py  →  docs/data/*.json  →  GitHub Pages  →  TRMNL
```

## Puesta en marcha

1. Crear el repositorio en GitHub (público: Pages gratuito lo exige).
2. Settings → Pages → Source: `Deploy from a branch`, rama `main`, carpeta `/docs`.
3. Settings → Actions → General → Workflow permissions: `Read and write`.
4. Actions → *Actualizar datos* → `Run workflow` para la primera ejecución.
5. Comprobar que responde `https://USUARIO.github.io/REPO/data/tiempo.json`.
6. En TRMNL: Private Plugin → estrategia `Polling` → esa URL → plantilla Liquid.

Ninguna credencial es necesaria por ahora. Cuando las haya, van en
Settings → Secrets, nunca en el JSON publicado, que es visible para cualquiera.

## Qué hay

| Fichero | Qué hace |
|---|---|
| `scripts/fetch_news.py` | Descarga los RSS, limpia, deduplica, ordena y puntúa |
| `scripts/fetch_weather.py` | Open-Meteo: 12 horas, 7 días y lógica del aviso de lluvia |
| `config/sources.json` | Feeds de las cuatro pantallas de noticias |
| `docs/data/*.json` | Salida que consume TRMNL |
| `.github/workflows/actualizar.yml` | Cron cada 30 min |

Probar en local, sin tocar nada publicado:

```bash
python3 scripts/fetch_news.py --pantalla farma --modo ultimas --salida /tmp
python3 scripts/fetch_weather.py
```

## Decisiones que vienen de probar feeds reales

**Los títulos llegan sucios.** Entidades HTML y etiquetas `<br>` incrustadas
dentro del `<title>`. Se limpian antes de publicar.

**El orden del feed no es cronológico.** Comprobado en Expansión: los items
vienen mezclados. El orden por fecha se calcula aquí, nunca se hereda.

**Hay medios que sirven ganchos, no titulares.** Marca publica cosas como
«Es 'Año Mariano'», inútiles sin la foto y el clic. Se descartan los títulos
de menos de 30 caracteres y el campo `peso` permite penalizar a un medio entero.

**Un medio prolífico se come la pantalla.** Redacción Médica publica cada hora
y Diariofarma cada dos días: ordenando por fecha, la pantalla de farma salía
entera de un solo medio. `max_por_medio` lo evita, con relleno posterior para
no dejar huecos.

**Los feeds se quedan parados sin avisar.** El de Marca llevaba dos días
detenido. Cada JSON incluye `salud.antiguedad_minima_min` para que la pantalla
pueda mostrar la antigüedad en lugar de fingir frescura.

**Un feed caído no puede tumbar la pantalla.** Cada descarga se captura por
separado; `salud.feeds_caidos` dice cuáles han fallado y por qué.

## Estado de las fuentes

Verificado el 23/08/2026. Los `HTTP 403` son del proxy del entorno donde se
probó, no de los medios, y no deberían darse en Actions. Los `HTTP 404` sí son
URL incorrectos que hay que corregir.

| Pantalla | Situación |
|---|---|
| Tiempo | Funciona. Open-Meteo, sin clave |
| Farma | 4 de 7 feeds: Diariofarma, El Global, Redacción Médica, FiercePharma |
| Economía | Expansión confirmado. Faltan por verificar los demás |
| Deportes | Marca confirmado, calidad baja. Faltan los demás |
| Generales | Sin verificar, todos bloqueados por el proxy de pruebas |

FiercePharma responde pero devuelve cero items: hay que mirar la estructura
de su XML.

Pendiente de corregir URL: INE, Banco de España, Invertia, PMFarma, AEMPS, EMA,
NBA.

## Pendiente

- Plantillas Liquid de las cinco pantallas (`templates/`).
- Cotizaciones y monetarios: hoja de cálculo con `GOOGLEFINANCE` más un
  disparador de Apps Script que fuerce el recálculo y publique el JSON. Sin el
  disparador, una hoja cerrada sirve valores viejos sin avisar.
- Bàsquet: **en suspenso**. La web de la Federació está tras verificación
  anti-bots y no vamos a sortearla. Requiere pedir acceso a la FCBQ. Sin una
  fuente automatizable, esta pantalla no cumple el requisito de autonomía y
  no entra.
