# Zeit & Raum

Eine Raum-Zeit-Plattform für virtuelle Reisen durch Erd- und Menschheitsgeschichte. Die aktuelle Entwicklung konzentriert sich auf die gemeinsame Wissens-API und eine responsive React-Web-App. Der vorhandene iOS-Client bleibt vorerst unverändert.

## Lokaler Start

Voraussetzung ist Docker Desktop.

```sh
cp .env.example .env
docker compose up --build -d
```

Danach sind erreichbar:

- Webclient: [http://localhost:5174](http://localhost:5174)
- API-Status: [http://localhost:8010/api/v1/health/](http://localhost:8010/api/v1/health/)
- Django-Administration: [http://localhost:8010/admin/](http://localhost:8010/admin/)

Die abweichenden Ports vermeiden Konflikte mit anderen lokalen Projekten. Die Daten liegen in Docker-Volumes und bleiben bei `docker compose down` erhalten.
Der Webserver leitet `/api` intern an Django weiter. Dadurch kann die Web-App auch über die Netzwerkadresse des Rechners auf einem Smartphone oder Tablet geöffnet werden, ohne dass das Endgerät fälschlich seine eigene `localhost`-Adresse verwendet.

## Architektur

- Django REST API als gemeinsamer Vertrag für alle Clients
- PostgreSQL 17 mit PostGIS 3.5 für kombinierte Raum-Zeit-Abfragen; das Multi-Arch-Image läuft auf Apple Silicon nativ als ARM64
- Redis und Celery für fortlaufende Hintergrundrecherche
- React, Vite und Leaflet für den Webclient

Der `ExplorationContext` ist der gemeinsame Zustand aller Bedienwege. Er speichert Ort, Kartenzoom, Fokusjahr, Zeitfenster, Radius, Thema, Perspektiven, Sprachen und den Umgang mit automatisch gefundenen Aussagen. Zeit und Raum sind zwei unabhängige Achsen: Das Zeitfenster kann endlich oder „Alle Zeiten“, der räumliche Fokus endlich oder „Weltweit“ sein. Bei endlichen Achsen gilt eine harte Schnittmenge – sichtbar sind nur Befunde innerhalb des gewählten Zeitfensters **und** innerhalb des Radius. Erst danach werden die wichtigsten Treffer nach Vertrauen, belegender Evidenz, Entfernung und Aktualität geordnet und auf standardmäßig 500, höchstens 1000 Befunde begrenzt. Durch Verkleinern eines der beiden Fokusse wird die Auswahl entsprechend feiner.

Der `anchor_mode` bestimmt die Blickrichtung: `space` zeigt die Geschichte des festgehaltenen Ortes, `event` hält ein Ereignis mit seinem eigenen Zeitraum fest, `time` zeigt die georeferenzierten Befunde der gewählten Raum-Zeit-Schnittmenge und `environment` durchsucht Naturereignis-Kategorien über alle gespeicherten Zeiten – ohne Ortsangabe weltweit, mit einer kombinierten Eingabe wie `Hamburg Sturmflut` am aufgelösten Ort. Ein Ereignis besitzt einen eigenen `focus_entity`; der räumliche Ausgangsort bleibt daneben erhalten. Dadurch kann man einen Schauplatz betreten und anschließend zum selben Ereignisdossier zurückkehren. Automatische externe Recherche wird bei „Alle Zeiten“ oder „Weltweit“ nicht grenzenlos gestartet; diese Ansichten ordnen den bereits gespeicherten Wissensbestand. Jede Änderung ist partiell. Eine Versionsnummer schützt vor unbemerktem Überschreiben bei parallelen Eingaben.

Die Web-App merkt sich die Kontext-ID lokal und ergänzt sie als `?context=…` in der Adresse. Damit überlebt der Raum-Zeit-Zustand ein Neuladen und kann über denselben Link auf einem anderen Endgerät geöffnet werden.

Die Wissensbasis speichert einzelne Aussagen statt kopierter Artikel. Jede Aussage besitzt einen Zeitraum, einen optionalen Ortsbezug, eine Vertrauensstufe und Belege mit Herkunft, Lizenz und Abrufzeit. Automatisch gefundene Aussagen beginnen als `candidate`; kuratierte Aussagen sind `verified`, Konflikte können als `disputed` erhalten bleiben.

Die Zeit→Raum-Ansicht bezeichnet diese Datensätze bewusst als Befunde, nicht pauschal als Ereignisse. Eine nachvollziehbare Präsentationsklassifikation unterscheidet unter anderem Konflikte, Naturereignisse, politische, religiöse und kulturelle Ereignisse, Kunstwerke, Bauwerke, Persönlichkeiten, Organisationen, Bewegungen und Orte. Automatisch erkannte Häufungen werden getrennt von ihren Belegen als Muster oder offene Forschungsfragen dargestellt. Eine gemeinsame Zeit und Kategorie begründen weder Kausalität noch eine religiöse oder politische Deutung; dafür müssen Beteiligte, Motive und wissenschaftliche Quellen geprüft werden.

Längerfristige Entwicklungen wie Nationalismus, Kolonialismus, Industrialisierung oder Kleine Eiszeit werden als `HistoricalProcess` modelliert. Ein Prozess besitzt einen eigenen Zeitraum, Raumbezug, Typ und Vertrauenswert, wird aber stets durch einzelne, quellengebundene Aussagen definiert. `ProcessAssertionRelation` verbindet ihn mit Ereignissen, Bauwerken, Texten oder Beobachtungen. Jede Verbindung trägt verpflichtend eine von vier Evidenzstufen: belegter Zusammenhang, wissenschaftlich plausible Einordnung, automatisch erkannte Ähnlichkeit oder bloße Gleichzeitigkeit. Gleichzeitigkeit kann technisch nicht als Ursache oder Einfluss gespeichert werden; algorithmische Ähnlichkeit benötigt einen benannten und versionierten Algorithmus.

Bei Wikidata-Treffern führt der bevorzugte Link über die Objekt-ID unmittelbar zum Wikipedia-Artikel in der bevorzugten Browsersprache, sofern ein entsprechender Artikel existiert. Die Lebensbedingungen nennen den verwendeten Ort, die Koordinaten, den Radius und das historische Zeitfenster ausdrücklich; moderne Klimanormalwerte bleiben als Vergleichsdaten gekennzeichnet und werden nicht als Messung des historischen Jahres ausgegeben.

Wikipedia-Portale bilden eine zusätzliche, kuratierte Entdeckungsschicht. `WikipediaPortal`, `PortalArticle` und `PortalScanRun` halten Portalrevision, Artikellink, Scanfortsetzung und Fehler getrennt fest. Das Portal gilt ausdrücklich nicht als Tatsachenevidenz: Jede extrahierte Aussage verweist auf den konkreten Artikel und dessen Fundstelle; der Portalweg wird nur als `discovery_only` ausgewiesen. Der langsame Hintergrundlauf verarbeitet kleine Pakete, respektiert Wikimedia-Drosselungen, repariert unvollständig gelieferte Artikel und lässt sich nach Unterbrechungen fortsetzen.

Die frühere AMD64-Datenbank wurde vor der ARM64-Umstellung logisch gesichert. Das alte Docker-Volume `zeitundraum_postgres_data` bleibt als externe Rückfallkopie bestehen und wird selbst durch `docker compose down -v` nicht entfernt. Der laufende ARM64-Bestand liegt getrennt in `zeitundraum_postgres_data_arm64`; lokale Dumps unter `backups/` werden nicht versioniert.

Eine Benutzeranfrage wird zuerst als Ort, Ereignis oder Thema aufgelöst. Entscheidend ist immer der eigentliche erste Wikipedia-Treffer; ein koordinatenloses Ereignis wird nicht mehr durch einen späteren Suchtreffer fälschlich zum Ort. Ein erkannter Ort verschiebt nur den räumlichen Fokus. Ein erkanntes Ereignis übernimmt seinen belegten Zeitraum, bewahrt aber den Ausgangsort. Der Worker importiert georeferenzierte Artikel aus der Umgebung und datierte Aussagekandidaten aus Wikipedia. Ereignisschauplätze stammen zusätzlich aus strukturierten Wikidata-Beziehungen (`P361`) und direkt verknüpften Wikipedia-Artikeln. Beim Wechsel zu einem Zeitanker recherchiert ein weiterer Wikidata-Adapter weltweit Objekte und Ereignisse mit Datum und Koordinate. Alle Adapter deduplizieren über stabile Fingerprints. Bilder, Kurzbeschreibungen, Objekt-IDs, Entfernungen, Lizenzen und Abrufzeiten bleiben als Herkunftsangaben erhalten. Nicht georeferenzierte Treffer werden ausdrücklich nicht am Anfrageort verankert.

## API

Wichtige Endpunkte:

- `POST /api/v1/exploration-contexts/` – einen stabilen Raum-Zeit-Kontext anlegen
- `GET/PATCH /api/v1/exploration-contexts/{id}/` – Kontext lesen oder partiell verändern
- `POST /api/v1/exploration-contexts/{id}/resolve/` – Eingabe als Ort, Ereignis, Naturereignis-Kategorie oder Thema einordnen
- `GET /api/v1/exploration-contexts/{id}/results/` – passende Aussagen für diesen Kontext
- `GET /api/v1/exploration-contexts/{id}/timeline/` – datierte Ortschronik unabhängig vom aktuellen Fokusjahr
- `GET /api/v1/exploration-contexts/{id}/time-world/` – georeferenzierte Befunde der harten Raum-Zeit-Schnittmenge, gerankt und begrenzt (`limit`, maximal 1000)
- `GET /api/v1/exploration-contexts/{id}/processes/` – am gewählten Ort und in der gewählten Zeit sichtbare historische Prozesse samt Evidenzprofil
- `GET /api/v1/exploration-contexts/{id}/event-dossier/` – Ereignisüberblick, Verlauf, Schauplätze und Bezug zum festgehaltenen Ausgangsort
- `GET /api/v1/exploration-contexts/{id}/environmental-events/` – Naturereignisse nach Kategorie über alle gespeicherten Zeiten, weltweit oder mit Ortsbezug
- `POST /api/v1/exploration-contexts/{id}/research/` – Recherche direkt aus dem gespeicherten Kontext
- `GET /api/v1/context/` – Aussagen nach Koordinate, Radius, Jahr und Zeitfenster
- `POST /api/v1/research/` – eine vertiefte Recherche anlegen
- `GET /api/v1/research/{id}/` – Fortschritt und Ergebniszahl abrufen
- `GET /api/v1/entities/` – Wissensobjekte durchsuchen
- `GET /api/v1/sources/` – Quellenregister anzeigen
- `GET /api/v1/wikipedia-portals/` – Portal-Katalog mit Sprache, Scanstand und Aussagezahl
- `GET /api/v1/historical-processes/?year=1816&q=Klima` – historische Prozesse nach Zeit, Typ oder Suchbegriff
- `GET /api/v1/historical-processes/{id}/` – Prozess mit definierenden Aussagen und allen qualifizierten Verbindungen
- `GET /api/v1/process-assertion-relations/?evidence_level=documented` – Prozessbezüge nach Evidenzstufe

Beispiel:

```text
/api/v1/context/?lat=53.836&lon=9.489&year=1814&radius_km=25&window_years=10
```

Beim Start werden idempotent einige belegte Krempe-Beispiele geladen. Sie machen die vollständige Strecke von PostGIS über die API bis zur Web-App sofort sichtbar.

Portal-Katalog und kontrollierten Hintergrundscan starten:

```sh
docker compose exec api python manage.py discover_wikipedia_portals --languages de en fr --queue-scan --article-limit 50
```

Die globalen NOAA/NCEI-Kataloge für bedeutende Erdbeben und dokumentierte
Tsunami-Auswirkungen werden idempotent importiert:

```sh
docker compose exec api python manage.py import_noaa_earthquakes
docker compose exec api python manage.py import_noaa_tsunamis
```

Die kuratierten Startdossiers werden ebenfalls idempotent aus bereits
quellengebundenen Aussagen aufgebaut. Fehlen die erforderlichen Belege, wird
ein Dossier sichtbar übersprungen statt mit ungesicherten Aussagen gefüllt:

```sh
docker compose exec api python manage.py seed_historical_dossiers
```

## Funktionen

- nichtlineare Zeitachse von der frühen Erde bis heute
- vollflächige, frei zoombare und antippbare Karte als dauerhafte Hauptansicht
- aktueller Standort als Einstieg; Ortswechsel bewahren Jahr, Zeitfenster und räumlichen Radius
- Ortsdossiers mit Stadtüberblick, nahen Sehenswürdigkeiten und anklickbaren historischen Eckdaten
- freie Themensuche per Tastatur oder deutschem Spracheingang
- weltweite, zeitlich unbeschränkte Kategoriesuche nach Vulkanen, Erdbeben, Sturmfluten, Hochwasser, Dürren, Hitzewellen, Frostperioden und Flusslaufverlagerungen
- Ortsauflösung mit mehrsprachiger Wikipedia-Suche und WikiNearby-ähnlicher Umgebungssuche
- anklickbarer Pivot „Ort → Zeit“ mit markanten Jahreszahlen und Zeiträumen
- umgekehrter Pivot „Zeit → Raum“ mit Weltkarte und anklickbaren Ereignisorten
- eigener Ereignisanker mit Überblick, Verlauf, Schauplätzen, lokalem Bezug und gleichzeitigem Weltgeschehen
- automatische weltweite Zeitrecherche über Wikidata mit CC0-, Objekt- und Unsicherheitsangaben
- automatisch extrahierte Eckdaten mit auswählbaren Wikipedia-/Wikidata-Treffern
- Kontextsuche nach zeitgleichen Bauwerken, Ereignissen und kulturellen oder sozialen Bewegungen
- quellengebundene historische Prozesse mit strikt getrennten Ebenen für Beleg, plausible Einordnung, Ähnlichkeit und Gleichzeitigkeit
- unabhängiger zeitlicher Fokus auf ein Ereignis, zehn, dreißig oder hundert Jahre beziehungsweise „Alle Zeiten“
- unabhängiger räumlicher Fokus von 1 bis 1.000 km beziehungsweise „Weltweit“
- genaue Eingabe von Jahr, Monat oder Tag, auch vor Christus
- aktueller Standort oder freie Auswahl/Suche auf der Apple-Karte
- epochengerechte Panoramen zu Natur, Wissen, Gesellschaft, Politik und Kultur
- datumsgefilterte historische Karten über OpenHistoricalMap
- orts- und zeitnahe Archivobjekte aus Wikimedia Commons und der Library of Congress
- strukturierte Ereignisdaten aus Wikidata sowie Arten- und Fossilbelege aus GBIF
- Herkunft, Objekt-ID, Lizenz, Suchmethode, Abrufzeit und Unsicherheitsangaben je Live-Quelle
- sichtbare Hinweise auf heutige Kartengrundlagen und die Sicherheit einer Rekonstruktion
- vollständig lokale Beispieldaten als erweiterbare Basis

## iPhone-Client

`ZeitUndRaum.xcodeproj` mit Xcode öffnen und auf einem iPhone-Simulator oder Gerät mit iOS 17 oder neuer starten.

Im Simulator verwendet die App standardmäßig `http://127.0.0.1:8010/api/v1`. Für ein echtes iPhone muss in der Scheme-Umgebung `ZEIT_UND_RAUM_API_URL` auf die im lokalen Netz erreichbare Serveradresse gesetzt werden. Für einen öffentlichen Betrieb ist HTTPS verpflichtend.

Die bisherige direkte Recherche über Wikidata, Wikimedia Commons, GBIF und Library of Congress bleibt als Rückfall- und Vergleichsschicht bestehen. Ergebnisse der eigenen API erscheinen als zusätzliche Quelle „Zeit & Raum“.

## Prüfungen

```sh
docker compose run --rm api python manage.py test
docker compose run --rm --no-deps web npm run build
xcodebuild -project ZeitUndRaum.xcodeproj -scheme ZeitUndRaum -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath /tmp/ZeitUndRaumDerivedData CODE_SIGNING_ALLOWED=NO build
```

## Nächste produktreife Erweiterungen

Die ersten Dossiers für Malta, Krempe, Tambora 1815–1816, Lissabon 1755 und Hamburg 1962 bilden nun die redaktionelle Referenz. Als nächstes werden ihre offenen Wirkungsfragen mit fachwissenschaftlichen Quellen und expliziten Relationsbelegen ergänzt, bevor regelbasierte Muster über Typ, Zeit und Raum folgen. Erst auf diesem stabilen Bestand wird `pgvector` für semantische Kandidaten eingesetzt; seine Treffer bleiben als automatisch erkannte Ähnlichkeiten gekennzeichnet und werden nie ohne zusätzliche Evidenz zu Ursachen. Weitere Quellenadapter, ein redaktioneller Prüfablauf, Benutzerkonten, API-Drosselung und externe Backups folgen schrittweise.
