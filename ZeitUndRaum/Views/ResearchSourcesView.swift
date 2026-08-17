import SwiftUI

struct ResearchSourcesView: View {
    @ObservedObject var model: ResearchViewModel
    let request: JourneyRequest
    @State private var showHistoricalMap = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            historicalMapCard

            switch model.state {
            case .idle, .loading:
                loadingView
            case .loaded(let bundle):
                loadedView(bundle)
            }
        }
        .padding(.horizontal, 20)
        .sheet(isPresented: $showHistoricalMap) {
            HistoricalMapSheet(request: request)
        }
    }

    private var historicalMapCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Image(systemName: "map.fill")
                        .font(.title2)
                        .foregroundStyle(AppTheme.mint)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Historische Karte").font(.headline)
                        Text("OpenHistoricalMap · datumsgefiltert")
                            .font(.caption)
                            .foregroundStyle(AppTheme.textSecondary)
                    }
                    Spacer()
                }

                Text("Zeigt erfasste historische Grenzen, Wege und Objekte für den gewählten Ort und Zeitpunkt. Die Abdeckung ist je nach Region und Epoche unterschiedlich.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineSpacing(3)

                HStack(spacing: 8) {
                    sourceBadge("CC0*", icon: "checkmark.seal.fill")
                    sourceBadge("räumlich variabel", icon: "scope")
                    sourceBadge(request.instant.displayYear, icon: "clock")
                }

                Button { showHistoricalMap = true } label: {
                    Label(
                        HistoricalMapLink.url(for: request) == nil ? "Für diese Epoche nicht verfügbar" : "Historische Karte öffnen",
                        systemImage: "arrow.up.right.square"
                    )
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(AppTheme.raised, in: RoundedRectangle(cornerRadius: 14))
                }
                .disabled(HistoricalMapLink.url(for: request) == nil)

                Text("* OpenHistoricalMap-Daten sind überwiegend CC0; einzelne Objekte können andere offene Lizenzen tragen.")
                    .font(.caption2)
                    .foregroundStyle(Color.white.opacity(0.45))
            }
        }
    }

    private var loadingView: some View {
        GlassCard {
            HStack(spacing: 14) {
                ProgressView().tint(AppTheme.mint)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Ortsnahe Quellen werden geprüft …").font(.headline)
                    Text("Archive, Ereignisdaten und wissenschaftliche Belege")
                        .font(.caption)
                        .foregroundStyle(AppTheme.textSecondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func loadedView(_ bundle: ResearchBundle) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text("\(bundle.evidence.count) Live-Quellen").font(.title3.bold())
                Text("Abruf \(bundle.loadedAt.formatted(date: .numeric, time: .shortened))")
                    .font(.caption)
                    .foregroundStyle(AppTheme.textSecondary)
            }
            Spacer()
            Button { Task { await model.refresh() } } label: {
                Image(systemName: "arrow.clockwise")
                    .frame(width: 40, height: 40)
                    .background(AppTheme.raised, in: Circle())
            }
            .accessibilityLabel("Quellen neu laden")
        }

        if bundle.evidence.isEmpty {
            GlassCard {
                ContentUnavailableView(
                    "Keine passenden Treffer",
                    systemImage: "books.vertical",
                    description: Text("Für diese Kombination aus Ort und Zeit liefern die angeschlossenen Quellen momentan keine belastbaren Treffer.")
                )
            }
        } else {
            ForEach(EvidenceKind.allCases) { kind in
                let matches = bundle.evidence.filter { $0.kind == kind }
                if !matches.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        Label(kind.rawValue, systemImage: kind.icon)
                            .font(.headline)
                            .foregroundStyle(kind.tint)
                        ForEach(matches) { evidence in
                            EvidenceCard(evidence: evidence)
                        }
                    }
                }
            }
        }

        if !bundle.providerErrors.isEmpty {
            GlassCard {
                DisclosureGroup("Teilweise nicht erreichbar") {
                    VStack(alignment: .leading, spacing: 7) {
                        ForEach(bundle.providerErrors, id: \.self) { error in
                            Label(error, systemImage: "wifi.exclamationmark")
                                .font(.caption)
                                .foregroundStyle(AppTheme.textSecondary)
                        }
                    }
                    .padding(.top, 10)
                }
                .font(.subheadline.weight(.semibold))
            }
        }

        Text("Die Vertrauensstufe wird von Zeit & Raum aus räumlicher Nähe, Datierungsgenauigkeit und bekannten Metadatenlücken berechnet. Sie ist keine Bewertung durch den jeweiligen Anbieter.")
            .font(.caption)
            .foregroundStyle(Color.white.opacity(0.48))
            .lineSpacing(3)
            .padding(.horizontal, 4)
    }

    private func sourceBadge(_ text: String, icon: String) -> some View {
        Label(text, systemImage: icon)
            .font(.caption2.weight(.semibold))
            .lineLimit(1)
            .padding(.horizontal, 9)
            .padding(.vertical, 7)
            .background(AppTheme.raised, in: Capsule())
    }
}

private struct EvidenceCard: View {
    let evidence: ResearchEvidence
    @State private var showDetails = false

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 13) {
                if let imageURL = evidence.imageURL {
                    AsyncImage(url: imageURL) { phase in
                        switch phase {
                        case .success(let image): image.resizable().scaledToFill()
                        case .failure: imagePlaceholder
                        default: ZStack { imagePlaceholder; ProgressView() }
                        }
                    }
                    .frame(height: 155)
                    .frame(maxWidth: .infinity)
                    .clipShape(RoundedRectangle(cornerRadius: 15, style: .continuous))
                    .clipped()
                }

                HStack(spacing: 8) {
                    Text(evidence.provenance.provider.uppercased())
                        .font(.caption2.weight(.bold))
                        .tracking(1.2)
                        .foregroundStyle(evidence.kind.tint)
                    Spacer()
                    Text("Vertrauen \(evidence.uncertainty.confidence.rawValue)")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(evidence.uncertainty.confidence.tint)
                        .padding(.horizontal, 9)
                        .padding(.vertical, 6)
                        .background(evidence.uncertainty.confidence.tint.opacity(0.12), in: Capsule())
                }

                Text(evidence.title).font(.headline)
                Text(evidence.summary)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineSpacing(3)
                    .lineLimit(7)

                VStack(alignment: .leading, spacing: 5) {
                    Label(evidence.uncertainty.spatialLabel, systemImage: "scope")
                    Label(evidence.uncertainty.temporalLabel, systemImage: "clock")
                }
                .font(.caption2)
                .foregroundStyle(Color.white.opacity(0.55))

                DisclosureGroup(isExpanded: $showDetails) {
                    VStack(alignment: .leading, spacing: 9) {
                        ForEach(evidence.uncertainty.reasons, id: \.self) { reason in
                            Label(reason, systemImage: "exclamationmark.circle")
                                .font(.caption)
                                .foregroundStyle(AppTheme.textSecondary)
                        }
                        Divider().overlay(Color.white.opacity(0.1))
                        metadataRow("Datensatz", evidence.provenance.recordID)
                        metadataRow("Lizenz", evidence.provenance.licenseName)
                        metadataRow("Abfrage", evidence.provenance.queryDescription)
                        metadataRow("Abgerufen", evidence.provenance.retrievedAt.formatted(date: .numeric, time: .shortened))
                        if let licenseURL = evidence.provenance.licenseURL {
                            Link("Lizenzhinweis öffnen", destination: licenseURL)
                                .font(.caption.weight(.semibold))
                        }
                    }
                    .padding(.top, 10)
                } label: {
                    Text("Herkunft & Unsicherheit").font(.subheadline.weight(.semibold))
                }

                Link(destination: evidence.provenance.sourceURL) {
                    Label("Originalquelle öffnen", systemImage: "arrow.up.right.square")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 11)
                        .background(AppTheme.raised, in: RoundedRectangle(cornerRadius: 13))
                }
            }
        }
    }

    private var imagePlaceholder: some View {
        Rectangle()
            .fill(AppTheme.raised)
            .overlay {
                Image(systemName: evidence.kind.icon)
                    .font(.largeTitle)
                    .foregroundStyle(evidence.kind.tint.opacity(0.6))
            }
    }

    private func metadataRow(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title.uppercased())
                .font(.system(size: 9, weight: .bold))
                .tracking(1)
                .foregroundStyle(Color.white.opacity(0.42))
            Text(value).font(.caption).foregroundStyle(AppTheme.textSecondary)
        }
    }
}
