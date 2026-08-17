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

Nach einem geprüften Programm-Deployment werden die versionierten, idempotenten
Umweltkataloge ausschließlich in die Explore-Datenbank geladen:

```sh
sudo -u deploy /srv/explore/venv/bin/python /srv/explore/app/backend/manage.py import_noaa_earthquakes
sudo -u deploy /srv/explore/venv/bin/python /srv/explore/app/backend/manage.py import_noaa_tsunamis
```

Der Explore-Worker führt vor jedem Start automatisch
`resume_wikipedia_portal_scans` aus. Dabei werden ausschließlich verwaiste,
noch als `running` markierte Portal-Läufe auditierbar auf `partial` gesetzt und
der fortsetzbare Katalogscan erneut in Redis-Datenbank 1 eingereiht. Der Befehl
kann bei Bedarf auch kontrolliert von Hand ausgeführt werden:

```sh
sudo -u deploy /srv/explore/venv/bin/python /srv/explore/app/backend/manage.py \
  resume_wikipedia_portal_scans --languages de en fr --article-limit 50
```
