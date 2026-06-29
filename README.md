# Radar Tokol — GitHub Pages + API-Football + The Odds API

Esta versión integra dos fuentes:

- **API-Football:** calendario, horario, estado y marcador.
- **The Odds API:** cuotas 1X2 de varias casas y probabilidades implícitas sin margen.

También incluye **Tokol**, que lee `data.json` y explica los datos disponibles.

## Qué se actualiza automáticamente

- Partidos nuevos
- Horarios en Ciudad de México
- Estado y marcador
- Cuotas 1X2 de varias casas
- Probabilidad del local, empate y visitante después de retirar el margen de cada casa
- Consenso promedio entre las casas disponibles
- Movimiento del consenso respecto a la actualización anterior
- Créditos restantes de The Odds API dentro de `data.json`

Todavía no se automatizan:

- Lesiones
- Alineaciones confirmadas
- Estadísticas avanzadas y forma
- Un modelo propio para determinar valor esperado

Las probabilidades sin margen representan el consenso del mercado; no garantizan resultados ni significan por sí mismas que exista una apuesta rentable.

## Archivos importantes

- `index.html`
- `data.json`
- `scripts/update_data.py`
- `scripts/update_odds.py`
- `.github/workflows/update_matches.yml`
- `.github/workflows/update_odds.yml`
- `requirements.txt`
- `.nojekyll`

## 1. Subir el paquete

Descomprime el ZIP y sube todo a la raíz de tu repositorio. Asegúrate de incluir las carpetas ocultas `.github` y los archivos `.nojekyll` y `.gitignore`.

## 2. Clave de API-Football

En tu repositorio entra en:

**Settings → Secrets and variables → Actions → Secrets → New repository secret**

Crea:

- Nombre: `API_FOOTBALL_KEY`
- Valor: tu clave de API-Football

Variables recomendadas en la pestaña **Variables**:

- `API_FOOTBALL_LEAGUE_ID` = `1`
- `API_FOOTBALL_SEASON` = `2026`

Si API-Football no devuelve partidos, verifica el identificador correcto de la competición en su panel.

## 3. Clave gratuita de The Odds API

Crea una cuenta en The Odds API y copia tu clave. Luego crea otro secreto de GitHub:

- Nombre: `THE_ODDS_API_KEY`
- Valor: tu clave de The Odds API

Variables recomendadas:

- `THE_ODDS_SPORT_KEY` = `soccer_fifa_world_cup`
- `THE_ODDS_REGIONS` = `eu`

La configuración predeterminada pide:

- Una región: `eu`
- Un mercado: `h2h`
- Formato interno decimal

Eso cuesta normalmente **un crédito por ejecución**. Con una ejecución cada seis horas, el consumo aproximado es de 120 a 124 créditos al mes, dentro de los 500 créditos del plan gratuito, siempre que no aumentes regiones o mercados.

## 4. Permitir escritura de GitHub Actions

Entra en:

**Settings → Actions → General → Workflow permissions**

Selecciona:

**Read and write permissions**

Guarda el cambio.

## 5. Probar la integración

Primero ejecuta:

1. **Actions**
2. **Actualizar partidos con API-Football**
3. **Run workflow**

Después ejecuta:

1. **Actions**
2. **Actualizar cuotas con The Odds API**
3. **Run workflow**

El segundo workflow necesita que los partidos ya existan en `data.json` para poder relacionarlos con las cuotas.

## 6. Cómo calcula las probabilidades

Por cada casa:

1. Convierte la cuota decimal en probabilidad implícita: `1 / cuota`.
2. Suma las probabilidades del local, empate y visitante.
3. Divide cada probabilidad entre esa suma para retirar el margen.
4. Promedia las probabilidades normalizadas de todas las casas disponibles.

La web muestra ese promedio como **probabilidad sin margen**.

## 7. Seguridad

- Las claves solo deben guardarse en GitHub Secrets.
- Nunca las pongas en `index.html`, `data.json` ni archivos públicos.
- `.env` está ignorado mediante `.gitignore`.
- `.env.example` contiene únicamente nombres de variables, sin secretos.
- Los scripts no imprimen las claves en los registros.

## 8. Tokol

Tokol puede responder preguntas como:

- “¿Cuáles debo evitar?”
- “¿Cuál es el próximo partido?”
- “¿Qué cuota tiene México?”
- “¿Cuáles son las probabilidades sin margen?”
- “¿Cuándo se actualizaron los datos?”

Tokol todavía no es una IA generativa conectada a un modelo externo. Interpreta los datos procesados y almacenados en `data.json`.

## 9. Limitaciones

- La región `eu` no garantiza casas mexicanas como Caliente o Playdoit.
- Una casa puede no publicar un partido o desaparecer temporalmente de la respuesta.
- GitHub Actions puede retrasar ejecuciones programadas.
- El mercado `h2h` de fútbol incluye local, empate y visitante en 90 minutos.
- Aumentar regiones o mercados aumenta el consumo de créditos.
