import CoreLocation
import Foundation

@MainActor
final class PlaceResearchModel: ObservableObject {
    @Published private(set) var dossier: PlaceDossier?
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    private let service = PlaceResearchService()
    private var requestID = UUID()

    func load(placeName: String, coordinate: CLLocationCoordinate2D) async {
        let id = UUID()
        requestID = id
        isLoading = true
        errorMessage = nil
        do {
            let result = try await service.load(placeName: placeName, coordinate: coordinate)
            guard requestID == id else { return }
            dossier = result
        } catch {
            guard requestID == id else { return }
            errorMessage = "Der Ortsüberblick ist momentan nicht erreichbar."
        }
        if requestID == id { isLoading = false }
    }
}

struct PlaceResearchService {
    private let session: URLSession = .shared

    func load(placeName: String, coordinate: CLLocationCoordinate2D) async throws -> PlaceDossier {
        async let exactResult = fetchExactArticle(placeName: placeName)
        async let nearbyResult = fetchNearby(coordinate: coordinate)
        let (exact, nearbyArticles) = try await (exactResult, nearbyResult)

        var overviewArticle = exact
        if overviewArticle == nil, let nearest = nearbyArticles.first {
            overviewArticle = try await fetchExactArticle(placeName: nearest.title) ?? nearest
        }
        let qids = ([overviewArticle].compactMap { $0?.qid } + nearbyArticles.compactMap(\.qid))
        let structuredDates = try await fetchDates(qids: Array(Set(qids)))

        let overview = overviewArticle.map { makePoint($0, dates: structuredDates[$0.qid ?? ""] ?? []) }
        let overviewID = overviewArticle?.pageID
        let nearby = nearbyArticles
            .filter { $0.pageID != overviewID }
            .prefix(12)
            .map { makePoint($0, dates: structuredDates[$0.qid ?? ""] ?? []) }
        let history = overviewArticle.map(extractHistory) ?? []

        return PlaceDossier(
            placeName: overview?.title ?? placeName,
            overview: overview,
            nearby: nearby,
            history: history,
            loadedAt: .now
        )
    }

    private struct WikiArticle {
        let pageID: String
        let qid: String?
        let title: String
        let description: String
        let extract: String
        let coordinate: CLLocationCoordinate2D?
        let imageURL: URL?
        let articleURL: URL
    }

    private func fetchExactArticle(placeName: String) async throws -> WikiArticle? {
        var components = URLComponents(string: "https://de.wikipedia.org/w/api.php")!
        components.queryItems = [
            URLQueryItem(name: "action", value: "query"),
            URLQueryItem(name: "format", value: "json"),
            URLQueryItem(name: "prop", value: "extracts|pageimages|coordinates|pageprops|description"),
            URLQueryItem(name: "explaintext", value: "1"),
            URLQueryItem(name: "piprop", value: "thumbnail"),
            URLQueryItem(name: "pithumbsize", value: "1200"),
            URLQueryItem(name: "redirects", value: "1"),
            URLQueryItem(name: "titles", value: placeName)
        ]
        let pages = try await wikiPages(from: components.url!)
        return pages.first.flatMap(parseArticle)
    }

    private func fetchNearby(coordinate: CLLocationCoordinate2D) async throws -> [WikiArticle] {
        var components = URLComponents(string: "https://de.wikipedia.org/w/api.php")!
        components.queryItems = [
            URLQueryItem(name: "action", value: "query"),
            URLQueryItem(name: "format", value: "json"),
            URLQueryItem(name: "generator", value: "geosearch"),
            URLQueryItem(name: "ggsprimary", value: "all"),
            URLQueryItem(name: "ggscoord", value: "\(coordinate.latitude)|\(coordinate.longitude)"),
            URLQueryItem(name: "ggsradius", value: "10000"),
            URLQueryItem(name: "ggslimit", value: "20"),
            URLQueryItem(name: "prop", value: "extracts|pageimages|coordinates|pageprops|description"),
            URLQueryItem(name: "exintro", value: "1"),
            URLQueryItem(name: "explaintext", value: "1"),
            URLQueryItem(name: "exchars", value: "900"),
            URLQueryItem(name: "piprop", value: "thumbnail"),
            URLQueryItem(name: "pithumbsize", value: "700")
        ]
        return try await wikiPages(from: components.url!)
            .sorted { ($0["index"] as? Int ?? 999) < ($1["index"] as? Int ?? 999) }
            .compactMap(parseArticle)
            .filter {
                !$0.title.hasPrefix("Liste") &&
                !$0.description.localizedCaseInsensitiveContains("Wikimedia-Liste")
            }
    }

    private func wikiPages(from url: URL) async throws -> [[String: Any]] {
        let data = try await data(from: url)
        let root = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let query = root?["query"] as? [String: Any]
        let pages = query?["pages"] as? [String: [String: Any]] ?? [:]
        return Array(pages.values)
    }

    private func parseArticle(_ page: [String: Any]) -> WikiArticle? {
        guard page["missing"] == nil,
              let title = page["title"] as? String,
              let pageIDValue = page["pageid"] else { return nil }
        let pageID = String(describing: pageIDValue)
        let pageprops = page["pageprops"] as? [String: Any]
        guard pageprops?["disambiguation"] == nil else { return nil }
        let qid = pageprops?["wikibase_item"] as? String
        let coordinates = page["coordinates"] as? [[String: Any]]
        let coordinate: CLLocationCoordinate2D? = coordinates?.first.flatMap { item in
            guard let lat = item["lat"] as? Double, let lon = item["lon"] as? Double else { return nil }
            return CLLocationCoordinate2D(latitude: lat, longitude: lon)
        }
        let thumbnail = page["thumbnail"] as? [String: Any]
        let imageURL = (thumbnail?["source"] as? String).flatMap(URL.init(string:))
        let encodedTitle = title.replacingOccurrences(of: " ", with: "_").addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? title
        guard let articleURL = URL(string: "https://de.wikipedia.org/wiki/\(encodedTitle)") else { return nil }
        return WikiArticle(
            pageID: pageID,
            qid: qid,
            title: title,
            description: page["description"] as? String ?? "Wikipedia-Ortseintrag",
            extract: page["extract"] as? String ?? "",
            coordinate: coordinate,
            imageURL: imageURL,
            articleURL: articleURL
        )
    }

    private func fetchDates(qids: [String]) async throws -> [String: [PlaceDate]] {
        guard !qids.isEmpty else { return [:] }
        var components = URLComponents(string: "https://www.wikidata.org/w/api.php")!
        components.queryItems = [
            URLQueryItem(name: "action", value: "wbgetentities"),
            URLQueryItem(name: "format", value: "json"),
            URLQueryItem(name: "ids", value: qids.joined(separator: "|")),
            URLQueryItem(name: "props", value: "claims")
        ]
        let responseData = try await data(from: components.url!)
        let root = try JSONSerialization.jsonObject(with: responseData) as? [String: Any]
        let entities = root?["entities"] as? [String: [String: Any]] ?? [:]
        let properties = ["P571": "Entstehung", "P580": "Beginn", "P582": "Ende", "P1619": "Eröffnung", "P576": "Auflösung"]

        return entities.reduce(into: [String: [PlaceDate]]()) { result, entry in
            let claims = entry.value["claims"] as? [String: [[String: Any]]] ?? [:]
            let sourceURL = URL(string: "https://www.wikidata.org/wiki/\(entry.key)")!
            let provenance = SourceProvenance(
                provider: "Wikidata",
                recordID: entry.key,
                sourceURL: sourceURL,
                licenseName: "CC0 1.0",
                licenseURL: URL(string: "https://www.wikidata.org/wiki/Wikidata:Copyright"),
                retrievedAt: .now,
                queryDescription: "Strukturierte Eckdaten des Orts- oder Bauwerkseintrags"
            )
            var dates: [PlaceDate] = []
            for (property, label) in properties {
                for (index, claim) in (claims[property] ?? []).enumerated() {
                    let mainsnak = claim["mainsnak"] as? [String: Any]
                    let datavalue = mainsnak?["datavalue"] as? [String: Any]
                    let value = datavalue?["value"] as? [String: Any]
                    guard let time = value?["time"] as? String, let year = firstYear(in: time) else { continue }
                    dates.append(PlaceDate(id: "\(entry.key)-\(property)-\(index)", label: label, year: year, provenance: provenance))
                }
            }
            result[entry.key] = dates.sorted { $0.year < $1.year }
        }
    }

    private func makePoint(_ article: WikiArticle, dates: [PlaceDate]) -> PlacePoint {
        let provenance = SourceProvenance(
            provider: "Wikipedia",
            recordID: article.pageID,
            sourceURL: article.articleURL,
            licenseName: "CC BY-SA – siehe Artikelseite",
            licenseURL: URL(string: "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/de"),
            retrievedAt: .now,
            queryDescription: "Ortsnaher deutschsprachiger Artikel im Umkreis von 10 km"
        )
        let summary = article.extract.components(separatedBy: "\n\n").first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? article.extract
        return PlacePoint(
            id: article.pageID,
            title: article.title,
            description: article.description,
            summary: summary,
            coordinate: article.coordinate,
            imageURL: article.imageURL,
            articleURL: article.articleURL,
            dates: dates,
            provenance: provenance
        )
    }

    private func extractHistory(from article: WikiArticle) -> [PlaceHistoryMoment] {
        let provenance = SourceProvenance(
            provider: "Wikipedia",
            recordID: article.pageID,
            sourceURL: article.articleURL,
            licenseName: "CC BY-SA – siehe Artikelseite",
            licenseURL: URL(string: "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/de"),
            retrievedAt: .now,
            queryDescription: "Automatisch erkannte datierte Sätze aus dem vollständigen Ortsartikel"
        )
        let keywords = ["krieg", "schwed", "munitions", "erbaut", "errichtet", "gegründ", "zerstört", "belager", "besetzt", "stadt", "kirche", "revolution", "brand", "eröffnet"]
        var sentences: [String] = []
        article.extract.enumerateSubstrings(in: article.extract.startIndex..<article.extract.endIndex, options: .bySentences) { substring, _, _, _ in
            if let substring { sentences.append(substring.trimmingCharacters(in: .whitespacesAndNewlines)) }
        }
        return sentences.flatMap { sentence -> [PlaceHistoryMoment] in
            let lower = sentence.lowercased()
            guard keywords.contains(where: lower.contains) else { return [] }
            return years(in: sentence).prefix(2).map { year in
                PlaceHistoryMoment(id: "\(article.pageID)-\(year)-\(sentence.hashValue)", year: year, text: sentence, provenance: provenance)
            }
        }
        .reduce(into: [PlaceHistoryMoment]()) { result, moment in
            if !result.contains(where: { $0.text == moment.text }) { result.append(moment) }
        }
        .sorted { $0.year < $1.year }
    }

    private func data(from url: URL) async throws -> Data {
        var request = URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad, timeoutInterval: 25)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("ZeitUndRaum/1.0 (iOS place research client)", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else { throw URLError(.badServerResponse) }
        return data
    }

    private func firstYear(in value: String) -> Int? { years(in: value).first }

    private func years(in value: String) -> [Int] {
        guard let regex = try? NSRegularExpression(pattern: "(?<!\\d)-?\\d{3,4}(?!\\d)") else { return [] }
        return regex.matches(in: value, range: NSRange(value.startIndex..., in: value)).compactMap { match in
            guard let range = Range(match.range, in: value) else { return nil }
            return Int(value[range])
        }
    }
}
