# Instalación rápida

1. Sube todos los archivos a la raíz del repositorio.
2. Crea el secreto `API_FOOTBALL_KEY`.
3. Crea el secreto `THE_ODDS_API_KEY`.
4. Crea las variables:
   - `API_FOOTBALL_LEAGUE_ID=1`
   - `API_FOOTBALL_SEASON=2026`
   - `THE_ODDS_SPORT_KEY=soccer_fifa_world_cup`
   - `THE_ODDS_REGIONS=eu`
5. Activa `Read and write permissions` en GitHub Actions.
6. Ejecuta primero `Actualizar partidos con API-Football`.
7. Ejecuta después `Actualizar cuotas con The Odds API`.
8. Revisa `data.json` y abre GitHub Pages.
