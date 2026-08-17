import CoreLocation
import Foundation

struct PlaceDate: Identifiable, Hashable, Sendable {
    let id: String
    let label: String
    let year: Int
    let provenance: SourceProvenance
}

struct PlacePoint: Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let description: String
    let summary: String
    let coordinate: CLLocationCoordinate2D?
    let imageURL: URL?
    let articleURL: URL
    let dates: [PlaceDate]
    let provenance: SourceProvenance

    static func == (lhs: PlacePoint, rhs: PlacePoint) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

struct PlaceHistoryMoment: Identifiable, Hashable, Sendable {
    let id: String
    let year: Int
    let text: String
    let provenance: SourceProvenance
}

struct PlaceDossier: Sendable {
    let placeName: String
    let overview: PlacePoint?
    let nearby: [PlacePoint]
    let history: [PlaceHistoryMoment]
    let loadedAt: Date

    func moments(around instant: TravelInstant, focus: TimeFocus) -> [PlaceHistoryMoment] {
        let range: ClosedRange<Int>
        switch focus {
        case .exact: range = (instant.year - 3)...(instant.year + 3)
        case .decade: range = (instant.year - 5)...(instant.year + 5)
        case .century: range = (instant.year - 50)...(instant.year + 50)
        }
        return history.filter { range.contains($0.year) }
    }
}

