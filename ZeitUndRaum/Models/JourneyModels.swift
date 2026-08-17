import CoreLocation
import SwiftUI

enum TimePrecision: String, CaseIterable, Identifiable {
    case year = "Jahr"
    case month = "Monat"
    case day = "Tag"

    var id: Self { self }
}

struct TravelInstant: Equatable {
    var year: Int
    var month: Int = 1
    var day: Int = 1
    var precision: TimePrecision = .year

    static let berlinWall = TravelInstant(year: 1989, month: 11, day: 9, precision: .day)

    var eraLabel: String {
        year < 0 ? "v. Chr." : "n. Chr."
    }

    var displayYear: String {
        let absolute = abs(year)
        return year < 0 ? "\(absolute) v. Chr." : String(absolute)
    }

    var displayText: String {
        guard year > 0 else { return displayYear }
        switch precision {
        case .year:
            return displayYear
        case .month:
            let symbols = Calendar.current.monthSymbols
            return "\(symbols[max(0, min(month - 1, 11))]) \(displayYear)"
        case .day:
            return String(format: "%02d.%02d.%@", day, month, displayYear)
        }
    }
}

struct JourneyRequest: Identifiable, Hashable {
    let id = UUID()
    var instant: TravelInstant
    var coordinate: CLLocationCoordinate2D
    var locationName: String

    static func == (lhs: JourneyRequest, rhs: JourneyRequest) -> Bool {
        lhs.id == rhs.id
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}

enum KnowledgeCategory: String, CaseIterable, Identifiable {
    case overview = "Überblick"
    case sources = "Quellen"
    case nature = "Natur"
    case science = "Wissen"
    case society = "Gesellschaft"
    case politics = "Politik"
    case culture = "Kultur"

    var id: Self { self }

    var icon: String {
        switch self {
        case .overview: "sparkles"
        case .nature: "leaf.fill"
        case .science: "atom"
        case .society: "person.3.fill"
        case .politics: "building.columns.fill"
        case .culture: "theatermasks.fill"
        case .sources: "books.vertical.fill"
        }
    }

    var tint: Color {
        switch self {
        case .overview: Color(red: 0.93, green: 0.73, blue: 0.34)
        case .nature: Color(red: 0.37, green: 0.78, blue: 0.58)
        case .science: Color(red: 0.33, green: 0.74, blue: 0.88)
        case .society: Color(red: 0.78, green: 0.57, blue: 0.91)
        case .politics: Color(red: 0.94, green: 0.48, blue: 0.42)
        case .culture: Color(red: 0.96, green: 0.64, blue: 0.38)
        case .sources: Color(red: 0.34, green: 0.84, blue: 0.76)
        }
    }
}

struct ContextFact: Identifiable {
    let id = UUID()
    let category: KnowledgeCategory
    let title: String
    let body: String
    let detail: String?
}

struct HistoricalSnapshot {
    let eraName: String
    let headline: String
    let summary: String
    let atmosphere: String
    let confidence: String
    let facts: [ContextFact]
}

enum TemporalScale {
    private static let anchors: [(progress: Double, year: Double)] = [
        (0.00, -4_540_000_000),
        (0.14, -541_000_000),
        (0.27, -66_000_000),
        (0.39, -2_600_000),
        (0.54, -10_000),
        (0.66, -3_000),
        (0.76, 1),
        (0.84, 1_500),
        (1.00, 2_026)
    ]

    static func year(for progress: Double) -> Int {
        let value = max(0, min(progress, 1))
        for pair in zip(anchors, anchors.dropFirst()) {
            if value <= pair.1.progress {
                let fraction = (value - pair.0.progress) / (pair.1.progress - pair.0.progress)
                let rawYear = pair.0.year + fraction * (pair.1.year - pair.0.year)
                let roundedYear = Int(rawYear.rounded())
                return roundedYear == 0 ? (rawYear < 0 ? -1 : 1) : roundedYear
            }
        }
        return 2_026
    }

    static func progress(for year: Int) -> Double {
        let value = Double(year)
        for pair in zip(anchors, anchors.dropFirst()) {
            if value <= pair.1.year {
                let fraction = (value - pair.0.year) / (pair.1.year - pair.0.year)
                return pair.0.progress + fraction * (pair.1.progress - pair.0.progress)
            }
        }
        return 1
    }
}
