# Tripanion Explore – Produktion

Die Produktionsinstallation ist von WIS getrennt:

- Anwendung: `/srv/explore`
- Datenbank: `tripanion_explore`
- Datenbankrolle: `explore_app`
- Redis-Datenbank: `1`
- Dienste: `explore.service`, `explore-worker.service`
- Nginx-Host: `explore.tripanion.com`

`server-bootstrap.sh` legt ausschließlich Explore-Ressourcen an. Die vorhandenen
WIS-Verzeichnisse, Dienste, Datenbank und Nginx-Konfiguration werden nicht verändert.
