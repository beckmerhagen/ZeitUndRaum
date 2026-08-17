import CoreLocation
import Foundation
import SwiftUI

enum TimeFocus: String, CaseIterable, Identifiable, Sendable {
    case exact = "Ereignis"
    case decade = "10 Jahre"
    case century = "100 Jahre"

    var id: Self { self }
}

enum TopicConnectionKind: String, CaseIterable, Identifiable, Sendable {
    case construction = "Zeitgleich gebaut"
    case culture = "Kulturelle Strömungen"
    case event = "Weitere Ereignisse"

    var id: Self { self }

    var icon: String {
        switch self {
        case .construction: "hammer.fill"
        case .culture: "theatermasks.fill"
        case .event: "point.3.connected.trianglepath.dotted"
        }
    }

    var tint: Color {
        switch self {
        case .construction: AppTheme.mint
        case .culture: AppTheme.gold
        case .event: AppTheme.coral
        }
    }
}

struct TopicCandidate: Identifiable, Hashable, Sendable {
    let id: String
    let label: String
    let description: String
    let articleTitle: String
}

struct TopicMilestone: Identifiable, Hashable, Sendable {
    let id: String
    let label: String
    let value: String
    let year: Int?
    let confidence: EvidenceConfidence
    let provenance: SourceProvenance
}

struct TopicProfile: Hashable, Sendable {
    let candidate: TopicCandidate
    let summary: String
    let imageURL: URL?
    let articleURL: URL?
    let coordinate: CLLocationCoordinate2D?
    let milestones: [TopicMilestone]
    let startYear: Int?
    let endYear: Int?

    static func == (lhs: TopicProfile, rhs: TopicProfile) -> Bool {
        lhs.candidate == rhs.candidate && lhs.milestones == rhs.milestones
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(candidate)
        hasher.combine(milestones)
    }
}

struct TopicConnection: Identifiable, Hashable, Sendable {
    let id: String
    let kind: TopicConnectionKind
    let title: String
    let description: String
    let year: Int?
    let coordinate: CLLocationCoordinate2D?
    let distanceKilometers: Double?
    let provenance: SourceProvenance
    let uncertainty: UncertaintyAssessment

    static func == (lhs: TopicConnection, rhs: TopicConnection) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

struct TopicContext: Sendable {
    let range: ClosedRange<Int>
    let centerCoordinate: CLLocationCoordinate2D
    let centerName: String
    let radiusKilometers: Int
    let connections: [TopicConnection]
    let errors: [String]
}

struct TopicTravelSelection: Sendable {
    let year: Int
    let coordinate: CLLocationCoordinate2D?
    let locationName: String?
    let topicTitle: String
    let timeFocus: TimeFocus
    let radiusKilometers: Int
}

extension TopicProfile {
    func range(for focus: TimeFocus) -> ClosedRange<Int> {
        let knownStart = startYear ?? milestones.compactMap(\.year).min() ?? Calendar.current.component(.year, from: .now)
        let knownEnd = endYear ?? milestones.compactMap(\.year).max() ?? knownStart
        let center = knownStart + (knownEnd - knownStart) / 2

        switch focus {
        case .exact:
            return min(knownStart, knownEnd)...max(knownStart, knownEnd)
        case .decade:
            return (center - 5)...(center + 5)
        case .century:
            return (center - 50)...(center + 50)
        }
    }
}
