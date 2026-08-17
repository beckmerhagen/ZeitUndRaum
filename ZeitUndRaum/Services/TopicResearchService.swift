import CoreLocation
import Foundation

@MainActor
final class TopicResearchModel: ObservableObject {
    @Published private(set) var candidates: [TopicCandidate] = []
    @Published private(set) var profile: TopicProfile?
    @Published private(set) var context: TopicContext?
    @Published private(set) var isSearching = false
    @Published private(set) var isLoadingContext = false
    @Published private(set) var errorMessage: String?

    private let service = TopicResearchService()
    private let originCoordinate: CLLocationCoordinate2D
    private let originName: String

    init(originCoordinate: CLLocationCoordinate2D, originName: String) {
        self.originCoordinate = originCoordinate
        self.originName = originName
    }

    func search(_ term: String, focus: TimeFocus, radiusKilometers: Int) async {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isSearching = true
        errorMessage = nil
        context = nil
        profile = nil

        do {
            candidates = try await service.searchCandidates(term: trimmed)
            guard let first = candidates.first else {
                errorMessage = "Zu diesem Stichwort wurde kein eindeutiger Wissenseintrag gefunden."
                isSearching = false
                return
            }
            await select(first, focus: focus, radiusKilometers: radiusKilometers)
        } catch {
            errorMessage = "Die Themensuche ist gerade nicht erreichbar."
        }
        isSearching = false
    }

    func select(_ candidate: TopicCandidate, focus: TimeFocus, radiusKilometers: Int) async {
        isSearching = true
        errorMessage = nil
        do {
            let loadedProfile = try await service.loadProfile(candidate: candidate)
            profile = loadedProfile
            await reloadContext(focus: focus, radiusKilometers: radiusKilometers)
        } catch {
            errorMessage = "Die Eckdaten für „\(candidate.label)“ konnten nicht geladen werden."
        }
        isSearching = false
    }

    func reloadContext(focus: TimeFocus, radiusKilometers: Int) async {
        guard let profile else { return }
        isLoadingContext = true
        context = await service.loadContext(
            profile: profile,
            focus: focus,
            radiusKilometers: radiusKilometers,
            fallbackCoordinate: originCoordinate,
            fallbackName: originName
        )
        isLoadingContext = false
    }
}

struct TopicResearchService {
    private let session: URLSession = .shared

    func searchCandidates(term: String) async throws -> [TopicCandidate] {
        var components = URLComponents(string: "https://de.wikipedia.org/w/api.php")!
        components.queryItems = [
            URLQueryItem(name: "action", value: "query"),
            URLQueryItem(name: "format", value: "json"),
            URLQueryItem(name: "generator", value: "search"),
            URLQueryItem(name: "gsrsearch", value: term),
            URLQueryItem(name: "gsrnamespace", value: "0"),
            URLQueryItem(name: "gsrlimit", value: "10"),
            URLQueryItem(name: "prop", value: "pageprops|description"),
            URLQueryItem(name: "ppprop", value: "wikibase_item")
        ]
        let data = try await data(from: components.url!)
        let root = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let query = root?["query"] as? [String: Any]
        let pages = query?["pages"] as? [String: [String: Any]] ?? [:]

        return pages.values.compactMap { page -> (Int, TopicCandidate)? in
            guard let title = page["title"] as? String,
                  let pageprops = page["pageprops"] as? [String: Any],
                  let qid = pageprops["wikibase_item"] as? String else { return nil }
            let description = page["description"] as? String ?? "Wissenseintrag"
            guard !description.localizedCaseInsensitiveContains("Begriffsklärung") else { return nil }
            let index = page["index"] as? Int ?? 999
            return (index, TopicCandidate(id: qid, label: title, description: description, articleTitle: title))
        }
        .sorted { $0.0 < $1.0 }
        .map(\.1)
        .uniqued(by: \.id)
    }

    func loadProfile(candidate: TopicCandidate) async throws -> TopicProfile {
        async let structuredData = fetchStructuredProfile(candidate: candidate)
        async let articleData = fetchArticle(candidate: candidate)
        let (structured, article) = try await (structuredData, articleData)

        let wikidataURL = URL(string: "https://www.wikidata.org/wiki/\(candidate.id)")!
        let wikidataProvenance = SourceProvenance(
            provider: "Wikidata",
            recordID: candidate.id,
            sourceURL: wikidataURL,
            licenseName: "CC0 1.0",
            licenseURL: URL(string: "https://www.wikidata.org/wiki/Wikidata:Copyright"),
            retrievedAt: .now,
            queryDescription: "Strukturierte Zeit-, Orts- und Eröffnungsangaben zum Thema"
        )

        var milestones = structured.dates.map { date in
            TopicMilestone(
                id: "wd-\(date.property)-\(date.value)",
                label: propertyLabel(date.property),
                value: displayDate(date.value),
                year: firstYear(in: date.value),
                confidence: .high,
                provenance: wikidataProvenance
            )
        }

        if let article {
            milestones.append(contentsOf: extractMilestones(from: article.fullExtract, sourceURL: article.articleURL, recordID: candidate.articleTitle))
        }
        milestones = milestones.uniqued(by: \.value).sorted { ($0.year ?? Int.max) < ($1.year ?? Int.max) }

        let structuredStarts = structured.dates.filter { ["P580", "P571", "P2031"].contains($0.property) }.compactMap { firstYear(in: $0.value) }
        let structuredEnds = structured.dates.filter { ["P582", "P576", "P2032", "P1619"].contains($0.property) }.compactMap { firstYear(in: $0.value) }
        let textStarts = milestones.filter { $0.label == "Beginn" || $0.label == "Baubeginn" }.compactMap(\.year)
        let textEnds = milestones.filter { $0.label == "Ende" || $0.label == "Eröffnung/Fertigstellung" }.compactMap(\.year)
        let allYears = milestones.compactMap(\.year)
        let start = structuredStarts.min() ?? textStarts.min() ?? allYears.min()
        let end = structuredEnds.max() ?? textEnds.max() ?? start ?? allYears.max()

        return TopicProfile(
            candidate: candidate,
            summary: article?.summary ?? candidate.description,
            imageURL: article?.imageURL,
            articleURL: article?.articleURL ?? structured.articleURL,
            coordinate: structured.coordinate,
            milestones: Array(milestones.prefix(10)),
            startYear: start,
            endYear: end
        )
    }

    func loadContext(
        profile: TopicProfile,
        focus: TimeFocus,
        radiusKilometers: Int,
        fallbackCoordinate: CLLocationCoordinate2D,
        fallbackName: String
    ) async -> TopicContext {
        let range = profile.range(for: focus)
        let center = profile.coordinate ?? fallbackCoordinate
        let centerName = profile.coordinate == nil ? fallbackName : profile.candidate.label
        let radius = max(1, min(radiusKilometers, 1_000))

        async let structures = capture("Zeitgleiche Bauwerke") {
            try await fetchConstructions(range: range, center: center, radius: radius, excluding: profile.candidate.id)
        }
        async let cultures = capture("Kulturelle Strömungen") {
            try await fetchCultures(range: range)
        }
        async let events = capture("Weitere Ereignisse") {
            try await fetchEvents(range: range, center: center, radius: radius, excluding: profile.candidate.id)
        }

        let results = await [structures, cultures, events]
        return TopicContext(
            range: range,
            centerCoordinate: center,
            centerName: centerName,
            radiusKilometers: radius,
            connections: results.flatMap(\.items).uniqued(by: \.id),
            errors: results.compactMap(\.error)
        )
    }

    private struct StructuredProfile {
        let dates: [(property: String, value: String)]
        let coordinate: CLLocationCoordinate2D?
        let articleURL: URL?
    }

    private struct ArticleData {
        let summary: String
        let fullExtract: String
        let imageURL: URL?
        let articleURL: URL
    }

    private func fetchStructuredProfile(candidate: TopicCandidate) async throws -> StructuredProfile {
        let sparql = """
        SELECT ?property ?date ?coord ?article WHERE {
          VALUES ?item { wd:\(candidate.id) }
          VALUES ?property { wdt:P571 wdt:P580 wdt:P582 wdt:P1619 wdt:P576 wdt:P585 wdt:P2031 wdt:P2032 }
          OPTIONAL { ?item ?property ?date. }
          OPTIONAL { ?item wdt:P625 ?coord. }
          OPTIONAL { ?article schema:about ?item; schema:isPartOf <https://de.wikipedia.org/>. }
        }
        """
        let response = try await sparqlBindings(query: sparql)
        let dates = response.compactMap { binding -> (String, String)? in
            guard let propertyURL = binding["property"], let date = binding["date"] else { return nil }
            return (propertyURL.components(separatedBy: "/").last ?? propertyURL, date)
        }
        let coordinate = response.compactMap { $0["coord"].flatMap(coordinate(fromWKT:)) }.first
        let articleURL = response.compactMap { $0["article"].flatMap(URL.init(string:)) }.first
        return StructuredProfile(dates: dates.uniqued(by: { "\($0.0)-\($0.1)" }), coordinate: coordinate, articleURL: articleURL)
    }

    private func fetchArticle(candidate: TopicCandidate) async throws -> ArticleData? {
        var components = URLComponents(string: "https://de.wikipedia.org/w/api.php")!
        components.queryItems = [
            URLQueryItem(name: "action", value: "query"),
            URLQueryItem(name: "format", value: "json"),
            URLQueryItem(name: "prop", value: "extracts|pageimages"),
            URLQueryItem(name: "explaintext", value: "1"),
            URLQueryItem(name: "piprop", value: "thumbnail"),
            URLQueryItem(name: "pithumbsize", value: "1000"),
            URLQueryItem(name: "redirects", value: "1"),
            URLQueryItem(name: "titles", value: candidate.articleTitle)
        ]
        let data = try await data(from: components.url!)
        let root = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let query = root?["query"] as? [String: Any]
        let pages = query?["pages"] as? [String: [String: Any]]
        guard let page = pages?.values.first,
              let extract = page["extract"] as? String else { return nil }
        let title = page["title"] as? String ?? candidate.articleTitle
        let encodedTitle = title.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? title
        let articleURL = URL(string: "https://de.wikipedia.org/wiki/\(encodedTitle.replacingOccurrences(of: " ", with: "_"))")!
        let thumbnail = page["thumbnail"] as? [String: Any]
        let imageURL = (thumbnail?["source"] as? String).flatMap(URL.init(string:))
        let summary = extract.components(separatedBy: "\n\n").first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? extract
        return ArticleData(summary: summary, fullExtract: extract, imageURL: imageURL, articleURL: articleURL)
    }

    private func extractMilestones(from text: String, sourceURL: URL, recordID: String) -> [TopicMilestone] {
        let provenance = SourceProvenance(
            provider: "Wikipedia",
            recordID: recordID,
            sourceURL: sourceURL,
            licenseName: "CC BY-SA – siehe Artikelseite",
            licenseURL: URL(string: "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/de"),
            retrievedAt: .now,
            queryDescription: "Automatisch erkannte datierte Sätze; anschließend als mittel sicher markiert"
        )
        var sentences: [String] = []
        text.enumerateSubstrings(in: text.startIndex..<text.endIndex, options: .bySentences) { substring, _, _, _ in
            if let substring { sentences.append(substring.trimmingCharacters(in: .whitespacesAndNewlines)) }
        }
        let keywords = ["bau", "begann", "begannen", "ausbruch", "ausbrach", "eröffnet", "fertig", "vollendet", "endete", "beendet", "gegründet", "revolution", "krieg", "denkmalschutz"]

        return sentences.compactMap { sentence -> TopicMilestone? in
            let lower = sentence.lowercased()
            guard keywords.contains(where: lower.contains), let year = years(in: sentence).first else { return nil }
            let label: String
            if lower.contains("baubeginn") || lower.contains("bauarbeiten beg") ||
                (lower.contains("bau") && lower.contains("begonnen")) {
                label = "Baubeginn"
            } else if lower.contains("begann") || lower.contains("begannen") || lower.contains("begonnen") || lower.contains("ausbrach") {
                label = "Beginn"
            } else if lower.contains("eröffnet") || lower.contains("fertig") || lower.contains("vollendet") {
                label = "Eröffnung/Fertigstellung"
            } else if lower.contains("endete") || lower.contains("beendet") {
                label = "Ende"
            } else if lower.contains("gegründet") {
                label = "Gründung"
            } else {
                label = "Historischer Eckpunkt"
            }
            return TopicMilestone(
                id: "wiki-\(sentence.hashValue)",
                label: label,
                value: sentence,
                year: year,
                confidence: .medium,
                provenance: provenance
            )
        }
        .uniqued(by: \.value)
        .prefix(8)
        .map { $0 }
    }

    private struct CapturedConnections {
        let items: [TopicConnection]
        let error: String?
    }

    private func capture(_ name: String, operation: () async throws -> [TopicConnection]) async -> CapturedConnections {
        do { return CapturedConnections(items: try await operation(), error: nil) }
        catch { return CapturedConnections(items: [], error: "\(name) konnten nicht vollständig geladen werden.") }
    }

    private func fetchConstructions(range: ClosedRange<Int>, center: CLLocationCoordinate2D, radius: Int, excluding qid: String) async throws -> [TopicConnection] {
        let sparql = """
        SELECT DISTINCT ?item ?itemLabel ?date ?coord ?typeLabel WHERE {
          SERVICE wikibase:around {
            ?item wdt:P625 ?coord .
            bd:serviceParam wikibase:center "Point(\(center.longitude) \(center.latitude))"^^geo:wktLiteral .
            bd:serviceParam wikibase:radius "\(radius)" .
          }
          ?item wdt:P31 ?type.
          { VALUES ?type { wd:Q811979 } }
          UNION { ?type wdt:P279 wd:Q811979 }
          UNION { ?type wdt:P279/wdt:P279 wd:Q811979 }
          { ?item wdt:P571 ?date } UNION { ?item wdt:P1619 ?date }
          FILTER(?item != wd:\(qid) && YEAR(?date) >= \(range.lowerBound) && YEAR(?date) <= \(range.upperBound))
          SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
        }
        LIMIT 18
        """
        return try await connections(from: sparql, kind: .construction, range: range, center: center, radius: radius)
    }

    private func fetchCultures(range: ClosedRange<Int>) async throws -> [TopicConnection] {
        let sparql = """
        SELECT DISTINCT ?item ?itemLabel ?date ?end ?coord ?typeLabel WHERE {
          VALUES ?type { wd:Q968159 wd:Q49773 }
          ?item wdt:P31 ?type .
          { ?item wdt:P580 ?date } UNION { ?item wdt:P571 ?date }
          OPTIONAL { ?item wdt:P582 ?end. }
          OPTIONAL { ?item wdt:P625 ?coord. }
          FILTER(
            YEAR(?date) <= \(range.upperBound) &&
            ((BOUND(?end) && YEAR(?end) >= \(range.lowerBound)) ||
             (!BOUND(?end) && YEAR(?date) >= \(range.lowerBound - 50)))
          )
          SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
        }
        LIMIT 14
        """
        return try await connections(from: sparql, kind: .culture, range: range, center: nil, radius: nil)
    }

    private func fetchEvents(range: ClosedRange<Int>, center: CLLocationCoordinate2D, radius: Int, excluding qid: String) async throws -> [TopicConnection] {
        let sparql = """
        SELECT DISTINCT ?item ?itemLabel ?date ?coord ?typeLabel WHERE {
          SERVICE wikibase:around {
            ?item wdt:P625 ?coord .
            bd:serviceParam wikibase:center "Point(\(center.longitude) \(center.latitude))"^^geo:wktLiteral .
            bd:serviceParam wikibase:radius "\(radius)" .
          }
          ?item wdt:P585 ?date .
          OPTIONAL { ?item wdt:P31 ?type. }
          FILTER(?item != wd:\(qid) && YEAR(?date) >= \(range.lowerBound) && YEAR(?date) <= \(range.upperBound))
          SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
        }
        LIMIT 16
        """
        return try await connections(from: sparql, kind: .event, range: range, center: center, radius: radius)
    }

    private func connections(
        from sparql: String,
        kind: TopicConnectionKind,
        range: ClosedRange<Int>,
        center: CLLocationCoordinate2D?,
        radius: Int?
    ) async throws -> [TopicConnection] {
        let bindings = try await sparqlBindings(query: sparql)
        return bindings.compactMap { binding -> TopicConnection? in
            guard let item = binding["item"], let label = binding["itemLabel"] else { return nil }
            let qid = item.components(separatedBy: "/").last ?? item
            let year = binding["date"].flatMap(firstYear(in:))
            let coordinate = binding["coord"].flatMap(coordinate(fromWKT:))
            let distance = center.flatMap { origin in coordinate.map { distanceKilometers(from: origin, to: $0) } }
            let type = binding["typeLabel"]
            let sourceURL = URL(string: item.replacingOccurrences(of: "http://", with: "https://"))!
            let spatialText: String
            if kind == .culture {
                spatialText = coordinate == nil ? "überregional; kein belastbarer Einzelpunkt" : "Ort in Wikidata erfasst"
            } else {
                spatialText = distance.map { "\($0.formatted(.number.precision(.fractionLength(1)))) km vom Fokus" } ?? "Distanz nicht bestimmbar"
            }
            let description: String
            switch kind {
            case .construction:
                description = "\(type ?? "Bauwerk") mit Entstehungs- oder Eröffnungsdatum im gewählten Zeitfenster."
            case .culture:
                description = "Kulturelle oder soziale Bewegung, deren dokumentierter Zeitraum das Fokusfenster überlappt."
            case .event:
                description = "Datierter Eintrag im gewählten räumlichen und zeitlichen Umfeld."
            }

            var uncertaintyReasons = [
                "Zeitliche oder räumliche Nähe zeigt einen möglichen Kontext, aber noch keinen ursächlichen Zusammenhang.",
                "Wikidata-Angaben können unvollständig sein und unterschiedliche Datierungslogiken verwenden."
            ]
            if kind == .construction {
                uncertaintyReasons.append("Für eine schnelle Ortsabfrage werden Bauwerkstypen bis zu zwei Hierarchiestufen unter „bauliche Struktur“ berücksichtigt.")
            } else if kind == .culture {
                uncertaintyReasons.append("Fehlt ein Enddatum, wird eine Strömung höchstens 50 Jahre nach ihrem dokumentierten Beginn als möglicherweise aktiv behandelt.")
            }

            return TopicConnection(
                id: "\(kind.rawValue)-\(qid)",
                kind: kind,
                title: label,
                description: description,
                year: year,
                coordinate: coordinate,
                distanceKilometers: distance,
                provenance: SourceProvenance(
                    provider: "Wikidata",
                    recordID: qid,
                    sourceURL: sourceURL,
                    licenseName: "CC0 1.0",
                    licenseURL: URL(string: "https://www.wikidata.org/wiki/Wikidata:Copyright"),
                    retrievedAt: .now,
                    queryDescription: radius.map { "\(range.lowerBound)–\(range.upperBound), Radius \($0) km" } ?? "\(range.lowerBound)–\(range.upperBound), überregional"
                ),
                uncertainty: UncertaintyAssessment(
                    confidence: .medium,
                    spatialLabel: spatialText,
                    temporalLabel: year.map(String.init) ?? "Zeitraum überlappt",
                    reasons: uncertaintyReasons
                )
            )
        }
        .uniqued(by: \.id)
    }

    private func sparqlBindings(query: String) async throws -> [[String: String]] {
        var components = URLComponents(string: "https://query.wikidata.org/sparql")!
        components.queryItems = [
            URLQueryItem(name: "query", value: query),
            URLQueryItem(name: "format", value: "json")
        ]
        let responseData = try await data(from: components.url!, accept: "application/sparql-results+json")
        let root = try JSONSerialization.jsonObject(with: responseData) as? [String: Any]
        let results = root?["results"] as? [String: Any]
        let bindings = results?["bindings"] as? [[String: [String: Any]]] ?? []
        return bindings.map { binding in
            binding.reduce(into: [String: String]()) { partial, item in
                if let value = item.value["value"] as? String { partial[item.key] = value }
            }
        }
    }

    private func data(from url: URL, accept: String = "application/json") async throws -> Data {
        var request = URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad, timeoutInterval: 25)
        request.setValue(accept, forHTTPHeaderField: "Accept")
        request.setValue("ZeitUndRaum/1.0 (iOS topic research client)", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else { throw URLError(.badServerResponse) }
        return data
    }

    private func propertyLabel(_ property: String) -> String {
        switch property {
        case "P571": "Entstehung/Gründung"
        case "P580": "Beginn"
        case "P582": "Ende"
        case "P1619": "Offizielle Eröffnung"
        case "P576": "Auflösung/Ende"
        case "P585": "Zeitpunkt"
        case "P2031": "Arbeitsbeginn"
        case "P2032": "Arbeitsende"
        default: "Eckdatum"
        }
    }

    private func displayDate(_ value: String) -> String {
        guard let year = firstYear(in: value) else { return value }
        return year < 0 ? "\(abs(year)) v. Chr." : String(year)
    }

    private func firstYear(in value: String) -> Int? { years(in: value).first }

    private func years(in value: String) -> [Int] {
        guard let regex = try? NSRegularExpression(pattern: "(?<!\\d)-?\\d{3,4}(?!\\d)") else { return [] }
        return regex.matches(in: value, range: NSRange(value.startIndex..., in: value)).compactMap { match in
            guard let range = Range(match.range, in: value) else { return nil }
            return Int(value[range])
        }
    }

    private func coordinate(fromWKT value: String) -> CLLocationCoordinate2D? {
        guard let start = value.firstIndex(of: "("), let end = value.firstIndex(of: ")") else { return nil }
        let values = value[value.index(after: start)..<end].split(separator: " ").compactMap { Double($0) }
        guard values.count == 2 else { return nil }
        return CLLocationCoordinate2D(latitude: values[1], longitude: values[0])
    }

    private func distanceKilometers(from lhs: CLLocationCoordinate2D, to rhs: CLLocationCoordinate2D) -> Double {
        CLLocation(latitude: lhs.latitude, longitude: lhs.longitude)
            .distance(from: CLLocation(latitude: rhs.latitude, longitude: rhs.longitude)) / 1_000
    }
}

private extension Array {
    func uniqued<Key: Hashable>(by keyPath: KeyPath<Element, Key>) -> [Element] {
        uniqued { $0[keyPath: keyPath] }
    }

    func uniqued<Key: Hashable>(by key: (Element) -> Key) -> [Element] {
        var seen = Set<Key>()
        return filter { seen.insert(key($0)).inserted }
    }
}
