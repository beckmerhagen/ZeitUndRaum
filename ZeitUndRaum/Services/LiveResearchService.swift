import CoreLocation
import Foundation

@MainActor
final class ResearchViewModel: ObservableObject {
    enum State {
        case idle
        case loading
        case loaded(ResearchBundle)
    }

    @Published private(set) var state: State = .idle
    private let request: JourneyRequest
    private let service = LiveResearchService()

    init(request: JourneyRequest) {
        self.request = request
    }

    func loadIfNeeded() async {
        guard case .idle = state else { return }
        await refresh()
    }

    func refresh() async {
        state = .loading
        state = .loaded(await service.research(for: request))
    }
}

struct HistoricalMapLink {
    static func url(for request: JourneyRequest) -> URL? {
        let instant = request.instant
        guard instant.year > 0, instant.year <= 9_999 else { return nil }
        let month = instant.precision == .year ? 1 : instant.month
        let day = instant.precision == .day ? instant.day : 1
        let date = String(format: "%04d-%02d-%02d", instant.year, month, day)
        let url = "https://www.openhistoricalmap.org/#map=12/\(request.coordinate.latitude)/\(request.coordinate.longitude)&date=\(date)"
        return URL(string: url)
    }
}

struct LiveResearchService {
    private let session: URLSession = .shared
    private let retrievedAt = Date.now

    func research(for request: JourneyRequest) async -> ResearchBundle {
        async let backend = providerResult("Zeit & Raum Wissensserver") { try await fetchBackend(for: request) }
        async let commons = providerResult("Wikimedia Commons") { try await fetchCommons(for: request) }
        async let wikidata = providerResult("Wikidata") { try await fetchWikidata(for: request) }
        async let gbif = providerResult("GBIF") { try await fetchGBIF(for: request) }
        async let library = providerResult("Library of Congress") { try await fetchLibraryOfCongress(for: request) }

        Task { try? await requestBackendResearch(for: request) }
        let responses = await [backend, commons, wikidata, gbif, library]
        let items = responses.flatMap(\.items)
        let errors = responses.compactMap(\.error)
        return ResearchBundle(
            evidence: items.sorted(by: evidenceOrder),
            providerErrors: errors,
            loadedAt: .now
        )
    }

    private struct ProviderResult {
        let items: [ResearchEvidence]
        let error: String?
    }

    private func providerResult(
        _ provider: String,
        operation: () async throws -> [ResearchEvidence]
    ) async -> ProviderResult {
        do {
            return ProviderResult(items: try await operation(), error: nil)
        } catch {
            return ProviderResult(items: [], error: "\(provider) war beim letzten Abruf nicht erreichbar.")
        }
    }

    private func evidenceOrder(_ lhs: ResearchEvidence, _ rhs: ResearchEvidence) -> Bool {
        let confidence: [EvidenceConfidence: Int] = [.high: 0, .medium: 1, .low: 2]
        let left = confidence[lhs.uncertainty.confidence] ?? 3
        let right = confidence[rhs.uncertainty.confidence] ?? 3
        if left != right { return left < right }
        return (lhs.distanceKilometers ?? 99_999) < (rhs.distanceKilometers ?? 99_999)
    }

    // MARK: - Zeit & Raum knowledge API

    private var backendBaseURL: URL? {
        let configured = ProcessInfo.processInfo.environment["ZEIT_UND_RAUM_API_URL"]
            ?? UserDefaults.standard.string(forKey: "ZEIT_UND_RAUM_API_URL")
            ?? "http://127.0.0.1:8010/api/v1"
        return URL(string: configured)
    }

    private func fetchBackend(for request: JourneyRequest) async throws -> [ResearchEvidence] {
        guard let backendBaseURL,
              var components = URLComponents(url: backendBaseURL.appendingPathComponent("context/"), resolvingAgainstBaseURL: false)
        else { throw URLError(.badURL) }
        let window = temporalWindow(for: request.instant.year)
        components.queryItems = [
            URLQueryItem(name: "lat", value: String(request.coordinate.latitude)),
            URLQueryItem(name: "lon", value: String(request.coordinate.longitude)),
            URLQueryItem(name: "year", value: String(request.instant.year)),
            URLQueryItem(name: "radius_km", value: "75"),
            URLQueryItem(name: "window_years", value: String(window)),
            URLQueryItem(name: "include_candidates", value: "true")
        ]
        guard let url = components.url else { throw URLError(.badURL) }
        let responseData = try await data(from: url)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        let response = try decoder.decode(BackendContextResponse.self, from: responseData)

        return response.assertions.compactMap { assertion in
            guard let source = assertion.evidence.first?.source,
                  let sourceURL = URL(string: source.url) else { return nil }
            let score = Double(assertion.confidence) ?? 0.4
            let confidence: EvidenceConfidence = score >= 0.8 ? .high : score >= 0.55 ? .medium : .low
            let statusLabel: String
            switch assertion.status {
            case "verified": statusLabel = "Belegte Aussage"
            case "disputed": statusLabel = "Widersprüchliche Quellenlage"
            default: statusLabel = "Automatisch gefundener Kandidat"
            }
            let spatialLabel = assertion.distanceKm.map {
                "\($0.formatted(.number.precision(.fractionLength(1)))) km entfernt"
            } ?? "Ortsbezug ohne berechenbare Entfernung"
            let temporalLabel: String = {
                guard let start = assertion.timeStartYear else { return "Zeitliche Einordnung offen" }
                guard let end = assertion.timeEndYear, end != start else { return formatYear(start) }
                return "\(formatYear(start))–\(formatYear(end))"
            }()

            return ResearchEvidence(
                id: "backend-\(assertion.id)",
                kind: .event,
                title: assertion.subject.canonicalName,
                summary: assertion.value,
                imageURL: nil,
                observedYear: assertion.timeStartYear,
                distanceKilometers: assertion.distanceKm,
                provenance: SourceProvenance(
                    provider: "Zeit & Raum · \(source.provider)",
                    recordID: source.recordId,
                    sourceURL: sourceURL,
                    licenseName: source.licenseName,
                    licenseURL: source.licenseUrl.flatMap(URL.init(string:)),
                    retrievedAt: source.retrievedAt,
                    queryDescription: "Eigene Raum-Zeit-API; \(statusLabel.lowercased())"
                ),
                uncertainty: UncertaintyAssessment(
                    confidence: confidence,
                    spatialLabel: spatialLabel,
                    temporalLabel: temporalLabel,
                    reasons: [
                        statusLabel,
                        "Vertrauen \(Int((score * 100).rounded())) Prozent; die Originalquelle bleibt maßgeblich."
                    ]
                )
            )
        }
    }

    private func requestBackendResearch(for request: JourneyRequest) async throws {
        guard let backendBaseURL else { throw URLError(.badURL) }
        let url = backendBaseURL.appendingPathComponent("research/")
        let window = temporalWindow(for: request.instant.year)
        let payload = BackendResearchPayload(
            query: request.locationName,
            latitude: request.coordinate.latitude,
            longitude: request.coordinate.longitude,
            radiusKm: 75,
            timeStartYear: request.instant.year - window,
            timeEndYear: request.instant.year + window,
            topics: ["Ortsgeschichte"],
            languages: ["de", "en"]
        )
        var urlRequest = URLRequest(url: url, timeoutInterval: 12)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        urlRequest.httpBody = try encoder.encode(payload)
        let (_, response) = try await session.data(for: urlRequest)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw URLError(.badServerResponse)
        }
    }

    private struct BackendContextResponse: Decodable {
        let assertions: [BackendAssertion]
    }

    private struct BackendAssertion: Decodable {
        let id: String
        let subject: BackendEntity
        let value: String
        let timeStartYear: Int?
        let timeEndYear: Int?
        let distanceKm: Double?
        let status: String
        let confidence: String
        let evidence: [BackendEvidence]
    }

    private struct BackendEntity: Decodable { let canonicalName: String }
    private struct BackendEvidence: Decodable { let source: BackendSource }
    private struct BackendSource: Decodable {
        let provider: String
        let url: String
        let recordId: String
        let licenseName: String
        let licenseUrl: String?
        let retrievedAt: Date
    }

    private struct BackendResearchPayload: Encodable {
        let query: String
        let latitude: Double
        let longitude: Double
        let radiusKm: Int
        let timeStartYear: Int
        let timeEndYear: Int
        let topics: [String]
        let languages: [String]
    }

    // MARK: - Wikidata events

    private func fetchWikidata(for request: JourneyRequest) async throws -> [ResearchEvidence] {
        let year = request.instant.year
        guard year >= -10_000, year <= 9_999 else { return [] }
        let window = temporalWindow(for: year)
        let minYear = year - window
        let maxYear = year + window
        let latitude = request.coordinate.latitude
        let longitude = request.coordinate.longitude

        let sparql = """
        SELECT DISTINCT ?item ?itemLabel ?date ?location ?description WHERE {
          SERVICE wikibase:around {
            ?item wdt:P625 ?location .
            bd:serviceParam wikibase:center "Point(\(longitude) \(latitude))"^^geo:wktLiteral .
            bd:serviceParam wikibase:radius "75" .
          }
          { ?item wdt:P585 ?date } UNION { ?item wdt:P580 ?date } UNION { ?item wdt:P571 ?date }
          FILTER(YEAR(?date) >= \(minYear) && YEAR(?date) <= \(maxYear))
          OPTIONAL { ?item schema:description ?description . FILTER(LANG(?description) = "de") }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
        }
        LIMIT 12
        """

        var components = URLComponents(string: "https://query.wikidata.org/sparql")!
        components.queryItems = [
            URLQueryItem(name: "query", value: sparql),
            URLQueryItem(name: "format", value: "json")
        ]
        let data = try await data(from: components.url!, accept: "application/sparql-results+json")
        let response = try JSONDecoder().decode(WikidataResponse.self, from: data)

        return response.results.bindings.prefix(8).compactMap { binding in
            guard let itemURL = URL(string: binding.item.value.replacingOccurrences(of: "http://", with: "https://")) else { return nil }
            let eventYear = firstYear(in: binding.date.value)
            let eventCoordinate = coordinate(fromWKT: binding.location.value)
            let distance = eventCoordinate.map { distanceKilometers(from: request.coordinate, to: $0) }
            let temporalDistance = eventYear.map { abs($0 - year) }
            let temporalLabel = eventYear.map { formatYear($0) } ?? "Datum ohne interpretierbare Genauigkeit"
            let confidence: EvidenceConfidence = (distance ?? 999) <= 25 && (temporalDistance ?? window) <= max(1, window / 3) ? .medium : .low

            return ResearchEvidence(
                id: "wikidata-\(binding.item.value)",
                kind: .event,
                title: binding.itemLabel.value,
                summary: binding.description?.value ?? "Ortsbezogener Datensatz mit einem Zeitbezug um \(temporalLabel).",
                imageURL: nil,
                observedYear: eventYear,
                distanceKilometers: distance,
                provenance: SourceProvenance(
                    provider: "Wikidata",
                    recordID: binding.item.value.components(separatedBy: "/").last ?? binding.item.value,
                    sourceURL: itemURL,
                    licenseName: "CC0 1.0",
                    licenseURL: URL(string: "https://www.wikidata.org/wiki/Wikidata:Copyright"),
                    retrievedAt: retrievedAt,
                    queryDescription: "Ereignisse und Objekte im Radius 75 km, Zeitfenster \(formatYear(minYear))–\(formatYear(maxYear))"
                ),
                uncertainty: UncertaintyAssessment(
                    confidence: confidence,
                    spatialLabel: distance.map { "\($0.formatted(.number.precision(.fractionLength(1)))) km vom gewählten Punkt" } ?? "Koordinate ohne Distanzprüfung",
                    temporalLabel: temporalLabel,
                    reasons: [
                        "Wikidata wird gemeinschaftlich gepflegt; einzelne Aussagen können unvollständig oder unterschiedlich belegt sein.",
                        "Die Koordinate bezeichnet den Datensatz, nicht zwingend den gesamten Wirkungsraum."
                    ]
                )
            )
        }
    }

    private struct WikidataResponse: Decodable {
        let results: Results
        struct Results: Decodable { let bindings: [Binding] }
        struct Binding: Decodable {
            let item: Value
            let itemLabel: Value
            let date: Value
            let location: Value
            let description: Value?
        }
        struct Value: Decodable { let value: String }
    }

    // MARK: - Wikimedia Commons archive

    private func fetchCommons(for request: JourneyRequest) async throws -> [ResearchEvidence] {
        var components = URLComponents(string: "https://commons.wikimedia.org/w/api.php")!
        components.queryItems = [
            URLQueryItem(name: "action", value: "query"),
            URLQueryItem(name: "format", value: "json"),
            URLQueryItem(name: "generator", value: "geosearch"),
            URLQueryItem(name: "ggsprimary", value: "all"),
            URLQueryItem(name: "ggsnamespace", value: "6"),
            URLQueryItem(name: "ggsradius", value: "10000"),
            URLQueryItem(name: "ggscoord", value: "\(request.coordinate.latitude)|\(request.coordinate.longitude)"),
            URLQueryItem(name: "ggslimit", value: "40"),
            URLQueryItem(name: "prop", value: "imageinfo|coordinates"),
            URLQueryItem(name: "iiprop", value: "url|extmetadata"),
            URLQueryItem(name: "iiurlwidth", value: "720"),
            URLQueryItem(name: "iiextmetadatalanguage", value: "de")
        ]
        let data = try await data(from: components.url!)
        let response = try JSONDecoder().decode(CommonsResponse.self, from: data)
        let pages = response.query?.pages.values ?? Dictionary<String, CommonsResponse.Page>().values
        let targetYear = request.instant.year

        return pages.compactMap { page -> ResearchEvidence? in
            guard let info = page.imageinfo?.first,
                  let sourceString = info.descriptionurl,
                  let sourceURL = URL(string: sourceString) else { return nil }
            let metadata = info.extmetadata ?? [:]
            let originalDate = metadata["DateTimeOriginal"]?.value
            let titleYear = firstYear(in: page.title).flatMap { (1_400...2_030).contains($0) ? $0 : nil }
            let observedYear = originalDate.flatMap(firstYear(in:)) ?? titleYear
            let pageCoordinate = page.coordinates?.first.map { CLLocationCoordinate2D(latitude: $0.lat, longitude: $0.lon) }
            let distance = pageCoordinate.map { distanceKilometers(from: request.coordinate, to: $0) }
            let description = cleanHTML(metadata["ImageDescription"]?.value ?? "")
            let licenseName = cleanHTML(metadata["LicenseShortName"]?.value ?? metadata["UsageTerms"]?.value ?? "Lizenz am Objekt prüfen")
            let licenseURL = metadata["LicenseUrl"].flatMap { URL(string: $0.value) }
            let temporalDistance = observedYear.map { abs($0 - targetYear) }
            let confidence: EvidenceConfidence
            if distance ?? 999 <= 5, let temporalDistance, temporalDistance <= max(2, temporalWindow(for: targetYear) / 2) {
                confidence = .high
            } else if observedYear != nil {
                confidence = .medium
            } else {
                confidence = .low
            }
            let artist = cleanHTML(metadata["Artist"]?.value ?? "Unbekannt")
            let title = page.title.replacingOccurrences(of: "File:", with: "")

            return ResearchEvidence(
                id: "commons-\(page.pageid)",
                kind: .archive,
                title: title,
                summary: description.isEmpty ? "Georeferenziertes Medienobjekt von \(artist)." : description,
                imageURL: info.thumburl.flatMap(URL.init(string:)),
                observedYear: observedYear,
                distanceKilometers: distance,
                provenance: SourceProvenance(
                    provider: "Wikimedia Commons",
                    recordID: String(page.pageid),
                    sourceURL: sourceURL,
                    licenseName: licenseName,
                    licenseURL: licenseURL,
                    retrievedAt: retrievedAt,
                    queryDescription: "Georeferenzierte Medien im Radius 10 km; anschließend nach zeitlicher Nähe sortiert"
                ),
                uncertainty: UncertaintyAssessment(
                    confidence: confidence,
                    spatialLabel: distance.map { "\($0.formatted(.number.precision(.fractionLength(1)))) km entfernt" } ?? "Georeferenz laut Medienobjekt",
                    temporalLabel: observedYear.map(formatYear) ?? "Aufnahme-/Entstehungsdatum nicht maschinenlesbar",
                    reasons: [
                        "Die Georeferenz kann Aufnahmeort, Motiv oder einen nur ungefähr beschriebenen Ort bezeichnen.",
                        observedYear == nil ? "Ohne maschinenlesbares Entstehungsdatum ist die zeitliche Zuordnung schwach." : "Das Entstehungsdatum beschreibt das Medium, nicht immer die dargestellte Epoche."
                    ]
                )
            )
        }
        .sorted { temporalRank($0, targetYear: targetYear) < temporalRank($1, targetYear: targetYear) }
        .prefix(6)
        .map { $0 }
    }

    private struct CommonsResponse: Decodable {
        let query: Query?
        struct Query: Decodable { let pages: [String: Page] }
        struct Page: Decodable {
            let pageid: Int
            let title: String
            let imageinfo: [ImageInfo]?
            let coordinates: [Coordinate]?
        }
        struct ImageInfo: Decodable {
            let thumburl: String?
            let descriptionurl: String?
            let extmetadata: [String: MetadataValue]?
        }
        struct MetadataValue: Decodable { let value: String }
        struct Coordinate: Decodable { let lat: Double; let lon: Double }
    }

    // MARK: - Library of Congress maps

    private func fetchLibraryOfCongress(for request: JourneyRequest) async throws -> [ResearchEvidence] {
        var components = URLComponents(string: "https://www.loc.gov/maps/")!
        components.queryItems = [
            URLQueryItem(name: "fo", value: "json"),
            URLQueryItem(name: "q", value: request.locationName),
            URLQueryItem(name: "c", value: "20"),
            URLQueryItem(name: "at", value: "results")
        ]
        let data = try await data(from: components.url!)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let results = object?["results"] as? [[String: Any]] ?? []
        let targetYear = request.instant.year

        return results.compactMap { item -> ResearchEvidence? in
            guard let title = item["title"] as? String,
                  let rawID = item["id"] as? String,
                  let sourceURL = URL(string: rawID.replacingOccurrences(of: "http://", with: "https://")) else { return nil }
            let dateText = item["date"] as? String
            let observedYear = dateText.flatMap(firstYear(in:))
            let descriptions = item["description"] as? [String]
            let imageStrings = item["image_url"] as? [String]
            let imageURL = imageStrings?.dropFirst().first.flatMap(URL.init(string:)) ?? imageStrings?.first.flatMap(URL.init(string:))
            let itemID = sourceURL.lastPathComponent
            let nearInTime = observedYear.map { abs($0 - targetYear) <= temporalWindow(for: targetYear) } ?? false

            return ResearchEvidence(
                id: "loc-\(itemID)",
                kind: .archive,
                title: title,
                summary: descriptions?.first ?? "Digitalisiertes historisches Kartenobjekt aus den Beständen der Library of Congress.",
                imageURL: imageURL,
                observedYear: observedYear,
                distanceKilometers: nil,
                provenance: SourceProvenance(
                    provider: "Library of Congress",
                    recordID: itemID,
                    sourceURL: sourceURL,
                    licenseName: "Rechtehinweis je Objekt",
                    licenseURL: URL(string: "https://www.loc.gov/legal/"),
                    retrievedAt: retrievedAt,
                    queryDescription: "Kartenbestand, Textsuche nach „\(request.locationName)“, danach zeitlich gerankt"
                ),
                uncertainty: UncertaintyAssessment(
                    confidence: nearInTime ? .medium : .low,
                    spatialLabel: "Ortsbezug aus Katalogtext; nicht koordinatengeprüft",
                    temporalLabel: observedYear.map(formatYear) ?? "Datierung nicht maschinenlesbar",
                    reasons: [
                        "Die Textsuche kann gleichnamige Orte oder nur indirekt bezogene Karten finden.",
                        "Katalogdatum, dargestellter Zeitraum und Herstellungsdatum können voneinander abweichen."
                    ]
                )
            )
        }
        .sorted { temporalRank($0, targetYear: targetYear) < temporalRank($1, targetYear: targetYear) }
        .prefix(4)
        .map { $0 }
    }

    // MARK: - GBIF scientific occurrences

    private func fetchGBIF(for request: JourneyRequest) async throws -> [ResearchEvidence] {
        let targetYear = request.instant.year
        if targetYear > 2_030 || targetYear < -541_000_000 { return [] }

        var components = URLComponents(string: "https://api.gbif.org/v1/occurrence/search")!
        var queryItems = [
            URLQueryItem(name: "geo_distance", value: "\(request.coordinate.latitude),\(request.coordinate.longitude),50km"),
            URLQueryItem(name: "hasGeospatialIssue", value: "false"),
            URLQueryItem(name: "limit", value: "10")
        ]

        var geologicalLabel: String?
        if targetYear >= 1_500 {
            let window = min(20, temporalWindow(for: targetYear))
            queryItems.append(URLQueryItem(name: "year", value: "\(max(1_500, targetYear - window)),\(min(2_030, targetYear + window))"))
        } else if let filter = geologicalFilter(for: targetYear) {
            geologicalLabel = filter.label
            queryItems.append(URLQueryItem(name: "basisOfRecord", value: "FOSSIL_SPECIMEN"))
            queryItems.append(URLQueryItem(name: filter.parameter, value: filter.value))
        } else {
            return []
        }
        components.queryItems = queryItems

        let data = try await data(from: components.url!)
        let response = try JSONDecoder().decode(GBIFResponse.self, from: data)

        return response.results.prefix(6).map { record in
            let sourceURL = URL(string: "https://www.gbif.org/occurrence/\(record.key)")!
            let recordCoordinate: CLLocationCoordinate2D? = {
                guard let lat = record.decimalLatitude, let lon = record.decimalLongitude else { return nil }
                return CLLocationCoordinate2D(latitude: lat, longitude: lon)
            }()
            let distance = recordCoordinate.map { distanceKilometers(from: request.coordinate, to: $0) }
            let observedYear = geologicalLabel == nil ? record.year : nil
            let temporalDistance = observedYear.map { abs($0 - targetYear) }
            let spatialGood = (record.coordinateUncertaintyInMeters ?? 50_000) <= 5_000 && (distance ?? 999) <= 25
            let temporalGood = geologicalLabel != nil || (temporalDistance ?? 999) <= 5
            let confidence: EvidenceConfidence = spatialGood && temporalGood ? .high : .medium
            let dataset = record.datasetTitle ?? record.datasetName ?? record.institutionCode ?? "GBIF-Datensatz"
            let timeDescription = geologicalLabel ?? record.eventDate ?? record.year.map(String.init) ?? "ohne genaues Belegdatum"
            let geologicRecordLabel = record.earliestPeriodOrLowestSystem ?? record.earliestEpochOrLowestSeries
            let summary = "\(record.basisOfRecord?.germanLabel ?? "Biodiversitätsbeleg") aus „\(dataset)“, zeitlicher Bezug: \(geologicRecordLabel ?? timeDescription)."
            let licenseURL = record.license.flatMap(URL.init(string:))

            return ResearchEvidence(
                id: "gbif-\(record.key)",
                kind: .science,
                title: record.scientificName ?? record.acceptedScientificName ?? "Biologischer Beleg #\(record.key)",
                summary: summary,
                imageURL: record.media?.first?.identifier.flatMap(URL.init(string:)),
                observedYear: observedYear,
                distanceKilometers: distance,
                provenance: SourceProvenance(
                    provider: "GBIF",
                    recordID: String(record.key),
                    sourceURL: sourceURL,
                    licenseName: record.license ?? "Lizenz am Datensatz prüfen",
                    licenseURL: licenseURL,
                    retrievedAt: retrievedAt,
                    queryDescription: geologicalLabel.map { "Fossilbelege im Radius 50 km, geologische Einheit \($0)" } ?? "Artenbelege im Radius 50 km und zeitnah zu \(formatYear(targetYear))"
                ),
                uncertainty: UncertaintyAssessment(
                    confidence: confidence,
                    spatialLabel: record.coordinateUncertaintyInMeters.map { "Koordinatenunsicherheit ±\($0.formatted(.number.precision(.fractionLength(0)))) m" } ?? distance.map { "\($0.formatted(.number.precision(.fractionLength(1)))) km entfernt; keine Unsicherheitsangabe" } ?? "Keine interpretierbare Koordinate",
                    temporalLabel: geologicalLabel ?? observedYear.map(formatYear) ?? "Geologische/zeitliche Genauigkeit begrenzt",
                    reasons: [
                        geologicalLabel == nil ? "Das Datum bezeichnet Beobachtung oder Sammlung, nicht zwingend die gesamte historische Verbreitung." : "Eine geologische Einheit umfasst meist Millionen Jahre; sie ist kein Beleg für das exakte Zieljahr.",
                        record.issues?.isEmpty == false ? "Der Datensatz enthält weitere GBIF-Prüfhinweise: \(record.issues!.joined(separator: ", "))." : "GBIF meldet für diese Auswahl keine groben Georeferenzierungsfehler."
                    ]
                )
            )
        }
    }

    private struct GBIFResponse: Decodable {
        let results: [Record]
        struct Record: Decodable {
            let key: Int64
            let scientificName: String?
            let acceptedScientificName: String?
            let datasetTitle: String?
            let datasetName: String?
            let institutionCode: String?
            let eventDate: String?
            let year: Int?
            let decimalLatitude: Double?
            let decimalLongitude: Double?
            let coordinateUncertaintyInMeters: Double?
            let basisOfRecord: String?
            let earliestPeriodOrLowestSystem: String?
            let earliestEpochOrLowestSeries: String?
            let issues: [String]?
            let license: String?
            let media: [Media]?
        }
        struct Media: Decodable { let identifier: String? }
    }

    // MARK: - Shared helpers

    private func data(from url: URL, accept: String = "application/json") async throws -> Data {
        var request = URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad, timeoutInterval: 22)
        request.setValue(accept, forHTTPHeaderField: "Accept")
        request.setValue("ZeitUndRaum/1.0 (iOS educational research client)", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw URLError(.badServerResponse)
        }
        return data
    }

    private func temporalWindow(for year: Int) -> Int {
        switch year {
        case 1_900...: 5
        case 1_700...: 20
        case 500...: 75
        case 1...: 200
        case (-10_000)...: 500
        default: 5_000
        }
    }

    private func temporalRank(_ evidence: ResearchEvidence, targetYear: Int) -> Int {
        evidence.observedYear.map { abs($0 - targetYear) } ?? Int.max
    }

    private func firstYear(in value: String) -> Int? {
        guard let regex = try? NSRegularExpression(pattern: "-?\\d{3,4}"),
              let match = regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
              let range = Range(match.range, in: value) else { return nil }
        return Int(value[range])
    }

    private func coordinate(fromWKT value: String) -> CLLocationCoordinate2D? {
        guard let start = value.firstIndex(of: "("), let end = value.firstIndex(of: ")") else { return nil }
        let numbers = value[value.index(after: start)..<end].split(separator: " ").compactMap { Double($0) }
        guard numbers.count == 2 else { return nil }
        return CLLocationCoordinate2D(latitude: numbers[1], longitude: numbers[0])
    }

    private func distanceKilometers(from lhs: CLLocationCoordinate2D, to rhs: CLLocationCoordinate2D) -> Double {
        CLLocation(latitude: lhs.latitude, longitude: lhs.longitude)
            .distance(from: CLLocation(latitude: rhs.latitude, longitude: rhs.longitude)) / 1_000
    }

    private func formatYear(_ year: Int) -> String {
        year < 0 ? "\(abs(year)) v. Chr." : String(year)
    }

    private func cleanHTML(_ value: String) -> String {
        let withoutTags = value.replacingOccurrences(of: "<[^>]+>", with: " ", options: .regularExpression)
        return withoutTags
            .replacingOccurrences(of: "&nbsp;", with: " ")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&#39;", with: "'")
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func geologicalFilter(for year: Int) -> (parameter: String, value: String, label: String)? {
        switch year {
        case ..<(-485_400_000): ("earliestPeriodOrLowestSystem", "Cambrian", "Kambrium")
        case ..<(-443_800_000): ("earliestPeriodOrLowestSystem", "Ordovician", "Ordovizium")
        case ..<(-419_200_000): ("earliestPeriodOrLowestSystem", "Silurian", "Silur")
        case ..<(-358_900_000): ("earliestPeriodOrLowestSystem", "Devonian", "Devon")
        case ..<(-298_900_000): ("earliestPeriodOrLowestSystem", "Carboniferous", "Karbon")
        case ..<(-251_900_000): ("earliestPeriodOrLowestSystem", "Permian", "Perm")
        case ..<(-201_400_000): ("earliestPeriodOrLowestSystem", "Triassic", "Trias")
        case ..<(-145_000_000): ("earliestPeriodOrLowestSystem", "Jurassic", "Jura")
        case ..<(-66_000_000): ("earliestPeriodOrLowestSystem", "Cretaceous", "Kreide")
        case ..<(-23_030_000): ("earliestPeriodOrLowestSystem", "Paleogene", "Paläogen")
        case ..<(-2_580_000): ("earliestPeriodOrLowestSystem", "Neogene", "Neogen")
        case ..<(-11_700): ("earliestPeriodOrLowestSystem", "Quaternary", "Quartär")
        case ..<1_500: ("earliestEpochOrLowestSeries", "Holocene", "Holozän")
        default: nil
        }
    }
}

private extension String {
    var germanLabel: String {
        switch self {
        case "HUMAN_OBSERVATION": "Beobachtung"
        case "MACHINE_OBSERVATION": "automatische Beobachtung"
        case "PRESERVED_SPECIMEN": "Sammlungsbeleg"
        case "FOSSIL_SPECIMEN": "Fossilbeleg"
        case "LITERATURE": "Literaturbeleg"
        default: lowercased().replacingOccurrences(of: "_", with: " ")
        }
    }
}
