import CoreLocation
import Foundation

struct HistoricalAtlas {
    func snapshot(for request: JourneyRequest) -> HistoricalSnapshot {
        let year = request.instant.year
        let place = request.locationName

        if year < -541_000_000 { return earlyEarth(place: place) }
        if year < -66_000_000 { return ancientLife(place: place, year: year) }
        if year < -2_600_000 { return ageOfMammals(place: place) }
        if year < -10_000 { return iceAge(place: place, coordinate: request.coordinate) }
        if year < -3_000 { return neolithic(place: place) }
        if year < 500 { return antiquity(place: place, year: year) }
        if year < 1_450 { return middleAges(place: place, year: year) }
        if year < 1_750 { return earlyModern(place: place, year: year) }
        if year < 1_900 { return industrialAge(place: place, year: year) }
        if year < 1_945 { return worldWars(place: place, year: year) }
        if year < 1_990 { return postwar(place: place, year: year) }
        return contemporary(place: place, year: year)
    }

    private func fact(_ category: KnowledgeCategory, _ title: String, _ body: String, _ detail: String? = nil) -> ContextFact {
        ContextFact(category: category, title: title, body: body, detail: detail)
    }

    private func earlyEarth(place: String) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: "Frühe Erde",
            headline: "Eine Welt, lange bevor Orte Namen hatten",
            summary: "Die heutige Landschaft von \(place) existiert noch nicht. Kontinente, Atmosphäre und Ozeane verändern sich über gewaltige Zeiträume.",
            atmosphere: "Fremd · geologisch aktiv · ohne komplexes Leben",
            confidence: "Rekonstruktion aus Geologie, Geochemie und Modellierung",
            facts: [
                fact(.nature, "Planet im Umbau", "Vulkanismus, Einschläge und Plattentektonik formen die Erdkruste. Die Position dieses Punktes lässt sich für so frühe Zeiten nur grob zurückrechnen."),
                fact(.science, "Spuren im Gestein", "Isotope und sehr alte Minerale wie Zirkone liefern Hinweise auf frühe Kruste, Wasser und Atmosphäre."),
                fact(.society, "Noch keine Menschen", "Gesellschaft, Sprache und politische Ordnung entstehen erst Milliarden Jahre später."),
                fact(.politics, "Keine politischen Räume", "Grenzen und Staaten sind menschliche Konstruktionen – in dieser Epoche gibt es sie nicht."),
                fact(.culture, "Tiefe Zeit", "Unsere Vorstellung dieser Epoche ist selbst Kulturgeschichte: Sie entstand durch Geologie, Evolutionstheorie und moderne Messtechnik.")
            ])
    }

    private func ancientLife(place: String, year: Int) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: year < -252_000_000 ? "Paläozoikum" : "Mesozoikum",
            headline: "Kontinente wandern, Lebenswelten entstehen",
            summary: "An der späteren Position von \(place) können sich Meer, Küste oder Land abwechseln. Die heutige Topografie ist noch fern.",
            atmosphere: "Dynamisch · artenreich · geologisch fern",
            confidence: "Regionale Näherung aus Fossilien und Paläogeografie",
            facts: [
                fact(.nature, "Andere Ökosysteme", year < -252_000_000 ? "Leben erobert schrittweise das Land; Wälder, Insekten und frühe Wirbeltiere verändern die Biosphäre." : "Reptilien dominieren viele Lebensräume; Blütenpflanzen verbreiten sich erst spät in dieser langen Epoche."),
                fact(.science, "Paläogeografische Adresse", "Der Punkt auf deiner heutigen Karte bewegte sich mit seiner Kontinentalplatte und lag unter anderen Breiten."),
                fact(.society, "Vor der Menschheit", "Es gibt weder Menschen noch überlieferte soziale Systeme."),
                fact(.politics, "Natur ohne Staaten", "Politische Kategorien sind auf diese Zeit nicht anwendbar."),
                fact(.culture, "Ein Bild aus Fragmenten", "Museen, Forschung und Popkultur machen aus Fossilfragmenten unsere Vorstellung dieser Welt.")
            ])
    }

    private func ageOfMammals(place: String) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: "Zeitalter der Säugetiere",
            headline: "Die moderne Welt nimmt langsam Gestalt an",
            summary: "Klima, Gebirge und Meeresströmungen verändern sich. Rund um den späteren Ort \(place) entwickeln sich zunehmend vertraute Pflanzengemeinschaften.",
            atmosphere: "Wandelnd · klimatisch vielfältig · vormenschlich",
            confidence: "Grobe zeitliche Einordnung; lokale Details variieren stark",
            facts: [
                fact(.nature, "Neue Nischen", "Nach dem Massenaussterben am Ende der Kreidezeit diversifizieren sich Säugetiere und Vögel stark."),
                fact(.science, "Klimaarchive", "Sedimente, Pollen und Sauerstoffisotope dokumentieren langfristige Erwärmungs- und Abkühlungsphasen."),
                fact(.society, "Frühe Homininen erst spät", "Die menschliche Entwicklungsgeschichte beginnt nur in einem sehr jungen Abschnitt dieser Epoche."),
                fact(.politics, "Keine Herrschaftssysteme", "Es existieren noch keine menschlichen Institutionen."),
                fact(.culture, "Unser Ursprung wird erforschbar", "Fossilien und Genetik verbinden die Geschichte des Menschen mit der Evolution allen Lebens.")
            ])
    }

    private func iceAge(place: String, coordinate: CLLocationCoordinate2D) -> HistoricalSnapshot {
        let northern = coordinate.latitude > 45
        return HistoricalSnapshot(
            eraName: "Eiszeitalter",
            headline: northern ? "Kälte prägt Land und Leben" : "Menschen leben in einer kühleren Welt",
            summary: northern ? "Die Region um \(place) kann je nach Zeitpunkt vergletschert, tundrenartig oder eisfrei sein." : "Auch fern der großen Eisschilde beeinflussen trockenere und kühlere Klimaphasen die Landschaft um \(place).",
            atmosphere: "Kühl · mobil · von Jahreszeiten bestimmt",
            confidence: "Klimatische Näherung; eine exakte Rekonstruktion braucht das genaue Jahr",
            facts: [
                fact(.nature, "Große Klimasprünge", "Kalt- und Warmzeiten verschieben Küsten, Vegetationszonen und Lebensräume. Viele heute vertraute Landschaften entstehen erst danach."),
                fact(.science, "Wissen aus Eis und Sediment", "Eisbohrkerne, Pollen, Tierknochen und Ablagerungen machen Temperatur und Umwelt rekonstruierbar."),
                fact(.society, "Kleine, mobile Gruppen", "Menschen organisieren sich in flexiblen Gemeinschaften und verbinden Jagd, Sammeln, Fürsorge und weite soziale Netze."),
                fact(.politics, "Aushandlung statt Staat", "Es gibt keine Staaten. Einfluss, Alter, Können, Verwandtschaft und Kooperation strukturieren Gruppen."),
                fact(.culture, "Symbolische Welten", "Werkzeuge, Bestattungen, Schmuck, Musik und Bilder zeigen komplexes Denken und lokale Traditionen.")
            ])
    }

    private func neolithic(place: String) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: "Sesshaftwerdung & frühe Städte",
            headline: "Landschaft wird zum Lebensraum – und zum Besitz",
            summary: "Je nach Region erreichen Ackerbau, Viehhaltung und dauerhafte Siedlungen den Raum um \(place) zu sehr unterschiedlichen Zeiten.",
            atmosphere: "Experimentell · gemeinschaftlich · zunehmend hierarchisch",
            confidence: "Überregionaler Kontext; lokale Chronologie kann abweichen",
            facts: [
                fact(.nature, "Menschlich geprägte Landschaft", "Rodung, Weide und Anbau verändern Böden, Artenvielfalt und Waldgrenzen zunehmend."),
                fact(.science, "Kalenderwissen", "Saat, Ernte und Tierhaltung fördern genaue Beobachtung von Jahreszeiten, Wetter und Himmelsbewegungen."),
                fact(.society, "Dörfer, Vorräte, Arbeitsteilung", "Mehr Menschen leben dauerhaft zusammen. Besitz, Tausch und soziale Unterschiede werden sichtbarer."),
                fact(.politics, "Frühe Zentren von Macht", "In manchen Weltregionen entstehen Städte, Verwaltung, Abgaben und monumentale Herrschaft; andernorts bleiben Strukturen dezentral."),
                fact(.culture, "Erinnerung aus Dingen", "Keramik, Bauten, Rituale und später Schrift tragen Wissen über Generationen.")
            ])
    }

    private func antiquity(place: String, year: Int) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: "Antike Welt",
            headline: "Reiche, Städte und Ideen sind weit vernetzt",
            summary: "\(place) liegt in einer Welt regionaler Mächte und weitreichender Handelsnetze. Die lokale Situation hängt stark davon ab, ob der Ort innerhalb oder außerhalb eines Großreichs liegt.",
            atmosphere: "Urban an Zentren · agrarisch im Alltag · politisch ungleich",
            confidence: "Historischer Überblick für das Jahr \(abs(year))",
            facts: [
                fact(.nature, "Kulturlandschaften", "Landwirtschaft, Bergbau, Holzverbrauch und Städte verändern regional Wälder, Böden und Gewässer."),
                fact(.science, "Beobachten und ordnen", "Mathematik, Medizin, Astronomie und Naturphilosophie entwickeln sich in mehreren Kulturkreisen und werden über Handelswege ausgetauscht."),
                fact(.society, "Status bestimmt Möglichkeiten", "Familie, Herkunft, Geschlecht, Bürgerrecht, Besitz und Unfreiheit prägen das Leben stärker als eine moderne nationale Identität."),
                fact(.politics, "Vielfältige Herrschaft", "Stadtstaaten, Republiken, Königreiche und Imperien konkurrieren. Verwaltung und Recht verbinden große Räume, oft durch Gewalt."),
                fact(.culture, "Mehrsprachige Welt", "Mündliche Tradition, Theater, Religion, Philosophie und Schriftkulturen existieren nebeneinander.")
            ])
    }

    private func middleAges(place: String, year: Int) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: "Mittelalterliche Welt",
            headline: "Der Alltag ist lokal, die Verbindungen reichen weit",
            summary: "Rund um \(place) bestimmen Landschaft, Herrschaft und Religion den Rhythmus des Lebens. Handel, Pilgerwege und Wissensnetze verbinden den Ort mit fernen Regionen.",
            atmosphere: "Lokal verwurzelt · religiös geprägt · stark hierarchisch",
            confidence: "Überregionaler Kontext; ‚Mittelalter‘ ist eine europäische Periodisierung",
            facts: [
                fact(.nature, "Wälder, Felder, Allmenden", "Der Großteil der Menschen lebt von Landnutzung. Klima- und Ernteschwankungen wirken direkt auf Ernährung und Gesundheit."),
                fact(.science, "Wissen wandert", "Gelehrte in islamischen, europäischen, afrikanischen und asiatischen Zentren bewahren, prüfen und erweitern Medizin, Mathematik und Astronomie."),
                fact(.society, "Gemeinschaft und Abhängigkeit", "Haushalt, Dorf, Zunft, Hof und religiöse Gemeinschaft geben Schutz und Zugehörigkeit, setzen aber enge Grenzen."),
                fact(.politics, "Überlappende Herrschaft", "Lokale Herren, Städte, Dynastien und religiöse Autoritäten beanspruchen gleichzeitig Rechte und Abgaben."),
                fact(.culture, "Sichtbare Glaubenswelten", "Bauten, Feste, Bilder, Musik und Erzählungen machen eine meist mündlich geprägte Kultur öffentlich erlebbar.")
            ])
    }

    private func earlyModern(place: String, year: Int) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: "Frühe Neuzeit",
            headline: "Neue Weltbilder treffen auf alte Ordnungen",
            summary: "Druckmedien, religiöse Konflikte, Fernhandel und stärkere Staaten verändern auch die Wahrnehmung von \(place). Die Folgen globaler Expansion sind ungleich verteilt.",
            atmosphere: "Neugierig · konfliktreich · globaler verknüpft",
            confidence: "Historischer Überblick um \(year)",
            facts: [
                fact(.nature, "Globaler biologischer Austausch", "Pflanzen, Tiere und Krankheitserreger werden zwischen Kontinenten verschoben – mit tiefen ökologischen und menschlichen Folgen."),
                fact(.science, "Messbare Welt", "Beobachtung, Experiment, Navigation und neue Instrumente verändern Astronomie, Medizin und Kartografie."),
                fact(.society, "Ständische Ordnung im Wandel", "Geburt bleibt entscheidend, doch Städte, Handel, Bildung und Konfession schaffen neue soziale Bewegungen und Konflikte."),
                fact(.politics, "Verdichtete Staatlichkeit", "Verwaltung, Steuern und stehende Heere wachsen. Koloniale Expansion verbindet Macht mit Ausbeutung und Gewalt."),
                fact(.culture, "Druck und Öffentlichkeit", "Bücher, Flugblätter, Übersetzungen und Bilder beschleunigen die Verbreitung von Wissen, Propaganda und Glaubensvorstellungen.")
            ])
    }

    private func industrialAge(place: String, year: Int) -> HistoricalSnapshot {
        let revolution = (1789...1815).contains(year)
        return HistoricalSnapshot(
            eraName: revolution ? "Zeitalter der Revolutionen" : "Industrialisierung",
            headline: revolution ? "Freiheit wird zur politischen Forderung" : "Maschinen, Städte und Nationen verändern den Alltag",
            summary: "\(place) ist Teil einer Welt beschleunigter Kommunikation und wachsender Nationalstaaten. Industrialisierung verläuft regional sehr ungleich.",
            atmosphere: "Beschleunigt · erfinderisch · sozial angespannt",
            confidence: "Historischer Überblick um \(year)",
            facts: [
                fact(.nature, "Fossile Energie verändert Landschaft", "Kohle, Bergbau, Fabriken und Eisenbahnen steigern Produktion – und Luftverschmutzung sowie Eingriffe in Flüsse und Böden."),
                fact(.science, "Professionelle Forschung", "Labore, Universitäten und Fachgesellschaften systematisieren Wissen. Geologie, Evolution und Thermodynamik verändern Weltbilder."),
                fact(.society, "Neue Klassen und Bewegungen", "Lohnarbeit, Urbanisierung und Bildung wachsen. Arbeiter-, Frauen- und Reformbewegungen fordern Teilhabe."),
                fact(.politics, revolution ? "Revolutionäre Öffentlichkeit" : "Nationalstaat und Imperium", revolution ? "Menschen- und Bürgerrechte werden formuliert, zugleich bleiben viele Gruppen ausgeschlossen und Gewalt prägt den Umbruch." : "Verfassungen und Parlamente gewinnen an Bedeutung, während Imperien koloniale Herrschaft weiter ausbauen."),
                fact(.culture, "Massenmedien entstehen", "Zeitungen, Fotografie, Museen und öffentliche Unterhaltung erreichen ein wachsendes Publikum.")
            ])
    }

    private func worldWars(place: String, year: Int) -> HistoricalSnapshot {
        let wartime = (1914...1918).contains(year) || (1939...1945).contains(year)
        return HistoricalSnapshot(
            eraName: wartime ? "Weltkrieg" : "Zwischenkriegszeit",
            headline: wartime ? "Totaler Krieg greift tief in das zivile Leben ein" : "Eine fragile Ordnung zwischen Aufbruch und Krise",
            summary: "Die Lage in \(place) hängt von Frontverlauf, Besatzung und Regime ab. Global prägen Krieg, Zwangsmigration und industrialisierte Gewalt diese Jahrzehnte.",
            atmosphere: wartime ? "Bedroht · mobilisiert · von Verlust geprägt" : "Modern · polarisiert · wirtschaftlich unsicher",
            confidence: "Für lokale Aussagen sind tagesgenaue Quellen besonders wichtig",
            facts: [
                fact(.nature, "Umwelt im Krieg", "Rohstoffbedarf, Zerstörung, Befestigungen und Giftstoffe hinterlassen langfristige Spuren in Landschaften."),
                fact(.science, "Forschung zwischen Nutzen und Gewalt", "Medizin, Kommunikation, Luftfahrt und Physik entwickeln sich schnell; Wissenschaft wird zugleich militärisch und rassistisch instrumentalisiert."),
                fact(.society, "Alltag unter Zwang", "Rationierung, Propaganda, Flucht, Verfolgung und veränderte Arbeit prägen Millionen Leben – sehr unterschiedlich nach Ort und Zugehörigkeit."),
                fact(.politics, "Demokratie, Diktatur, Imperium", "Autoritäre und faschistische Regime zerstören Rechte. Koloniale Herrschaft bleibt ein zentraler Teil der Weltordnung."),
                fact(.culture, "Moderne und Propaganda", "Film, Radio, Design und Avantgarde erreichen Massenpublika; dieselben Medien dienen auch Kontrolle und Mobilisierung.")
            ])
    }

    private func postwar(place: String, year: Int) -> HistoricalSnapshot {
        let berlinMoment = place.localizedCaseInsensitiveContains("Berlin") && year == 1989
        return HistoricalSnapshot(
            eraName: berlinMoment ? "Friedliche Revolution" : "Nachkriegszeit & Kalter Krieg",
            headline: berlinMoment ? "Eine geteilte Stadt öffnet ihre Übergänge" : "Zwei Machtblöcke prägen eine dekolonisierende Welt",
            summary: berlinMoment ? "Am 9. November 1989 führen politische Umbrüche und eine missverständliche Pressekonferenz zur Öffnung der Berliner Grenzübergänge. Menschen feiern auf und an der Mauer." : "\(place) liegt in einer Welt zwischen Wiederaufbau, Systemkonkurrenz, Dekolonisierung und neuen sozialen Bewegungen.",
            atmosphere: berlinMoment ? "Ungläubig · dicht gedrängt · euphorisch" : "Modernisierend · angespannt · hoffnungsvoll",
            confidence: berlinMoment ? "Gut dokumentiertes Ereignis; Erleben war individuell verschieden" : "Historischer Überblick um \(year)",
            facts: [
                fact(.nature, "Umwelt wird politisch", "Smog, Chemikalien, Atomenergie und sichtbare Wald- und Gewässerschäden fördern neue Umweltbewegungen."),
                fact(.science, "Vom Atomzeitalter zum Computer", "Raumfahrt, Molekularbiologie, Satelliten und Mikroelektronik verändern Wissen und Alltag."),
                fact(.society, berlinMoment ? "Begegnung über Grenzen" : "Wohlstand und Protest", berlinMoment ? "Familien, Freunde und Fremde begegnen sich nach jahrzehntelanger Teilung. Die kommenden sozialen Umbrüche sind noch offen." : "Bildung, Konsum und Lebenserwartung wachsen vielerorts; Bürgerrechts-, Frauen- und Friedensbewegungen stellen Hierarchien infrage."),
                fact(.politics, berlinMoment ? "Die Mauer verliert ihre Funktion" : "Blockkonfrontation und Dekolonisierung", berlinMoment ? "Die DDR-Führung verliert Kontrolle über die Ausreiseregelung. Die staatliche Einheit folgt erst am 3. Oktober 1990." : "USA und Sowjetunion konkurrieren global. Gleichzeitig erringen frühere Kolonien Unabhängigkeit und suchen eigene politische Wege."),
                fact(.culture, "Globale Popkultur", "Fernsehen, Musik und Jugendkulturen überschreiten Grenzen; lokale Szenen eignen sie sich auf eigene Weise an.")
            ])
    }

    private func contemporary(place: String, year: Int) -> HistoricalSnapshot {
        HistoricalSnapshot(
            eraName: "Vernetzte Gegenwart",
            headline: "Der Ort ist lokal – seine Beziehungen sind global",
            summary: "\(place) ist durch Daten, Handel, Klima und Migration mit weit entfernten Räumen verbunden. Der gleiche Zeitpunkt wird je nach Lebenslage völlig unterschiedlich erlebt.",
            atmosphere: "Vernetzt · schnell · widersprüchlich",
            confidence: year > 2026 ? "Zukunftsszenario, keine historische Aussage" : "Gegenwartsüberblick; lokale Daten können ergänzt werden",
            facts: [
                fact(.nature, "Klimawandel wird lokal", "Hitze, Starkregen, Wasserverfügbarkeit und Artenverschiebungen zeigen globale Veränderungen an konkreten Orten."),
                fact(.science, "Wissen in Echtzeit", "Digitale Messnetze, Genomik, Erdbeobachtung und künstliche Intelligenz vergrößern Erkenntnismöglichkeiten – und Verantwortung."),
                fact(.society, "Viele Öffentlichkeiten", "Alltag findet zugleich physisch und digital statt. Alterung, Urbanisierung und Migration verändern Gemeinschaften."),
                fact(.politics, "Geteilte Herausforderungen", "Staaten bleiben mächtig, doch Klima, Pandemien, Finanz- und Informationsströme überschreiten Grenzen."),
                fact(.culture, "Archive für alle?", "Noch nie waren so viele Bilder und Stimmen zugänglich. Zugleich entscheiden Plattformen und Zugänge, was sichtbar bleibt.")
            ])
    }
}
