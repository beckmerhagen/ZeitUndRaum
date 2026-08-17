import Foundation
import SwiftUI

enum EvidenceKind: String, CaseIterable, Identifiable, Sendable {
    case archive = "Archiv"
    case event = "Ereignis"
    case science = "Wissenschaft"

    var id: Self { self }

    var icon: String {
        switch self {
        case .archive: "photo.on.rectangle.angled"
        case .event: "point.3.connected.trianglepath.dotted"
        case .science: "cross.case.fill"
        }
    }

    var tint: Color {
        switch self {
        case .archive: AppTheme.gold
        case .event: AppTheme.coral
        case .science: AppTheme.mint
        }
    }
}

enum EvidenceConfidence: String, Sendable {
    case high = "hoch"
    case medium = "mittel"
    case low = "gering"

    var tint: Color {
        switch self {
        case .high: AppTheme.mint
        case .medium: AppTheme.gold
        case .low: AppTheme.coral
        }
    }
}

struct SourceProvenance: Hashable, Sendable {
    let provider: String
    let recordID: String
    let sourceURL: URL
    let licenseName: String
    let licenseURL: URL?
    let retrievedAt: Date
    let queryDescription: String
}

struct UncertaintyAssessment: Hashable, Sendable {
    let confidence: EvidenceConfidence
    let spatialLabel: String
    let temporalLabel: String
    let reasons: [String]
}

struct ResearchEvidence: Identifiable, Hashable, Sendable {
    let id: String
    let kind: EvidenceKind
    let title: String
    let summary: String
    let imageURL: URL?
    let observedYear: Int?
    let distanceKilometers: Double?
    let provenance: SourceProvenance
    let uncertainty: UncertaintyAssessment
}

struct ResearchBundle: Sendable {
    let evidence: [ResearchEvidence]
    let providerErrors: [String]
    let loadedAt: Date

    static let empty = ResearchBundle(evidence: [], providerErrors: [], loadedAt: .now)
}
