import MapKit
import SwiftUI

struct PlaceDossierView: View {
    @ObservedObject var model: PlaceResearchModel
    let request: JourneyRequest
    let timeFocus: TimeFocus
    let radiusKilometers: Int
    let onChooseYear: (Int) -> Void
    let onChoosePlace: (PlacePoint) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var journeyRequest: JourneyRequest?

    private var snapshot: HistoricalSnapshot { HistoricalAtlas().snapshot(for: request) }

    var body: some View {
        NavigationStack {
            ZStack {
                CosmicBackground()
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 22) {
                        header

                        if model.isLoading {
                            GlassCard {
                                HStack(spacing: 12) {
                                    ProgressView().tint(AppTheme.mint)
                                    Text("Ortsgeschichte und Sehenswürdigkeiten werden geladen …")
                                        .font(.subheadline.weight(.semibold))
                                }
                            }
                        } else if let dossier = model.dossier {
                            overview(dossier)
                            timeContext(dossier)
                            nearby(dossier)
                            history(dossier)
                            sourceNote(dossier)
                        } else if let error = model.errorMessage {
                            GlassCard {
                                Label(error, systemImage: "wifi.exclamationmark")
                                    .foregroundStyle(AppTheme.coral)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 40)
                }
                .scrollIndicators(.hidden)
            }
            .navigationTitle(request.locationName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Karte") { dismiss() }
                }
            }
            .navigationDestination(item: $journeyRequest) { request in
                JourneyView(request: request)
            }
        }
        .tint(AppTheme.mint)
        .preferredColorScheme(.dark)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(request.instant.year == Calendar.current.component(.year, from: .now) ? "ORT IM JETZT" : "ORT IN DER ZEIT")
                .font(.caption2.weight(.bold))
                .tracking(1.5)
                .foregroundStyle(AppTheme.mint)
            Text("\(request.locationName) · \(request.instant.displayText)")
                .font(.system(size: 32, weight: .bold, design: .rounded))
            Text("\(timeFocus.rawValue) zeitlich · \(radiusKilometers) km räumlich")
                .font(.subheadline)
                .foregroundStyle(AppTheme.textSecondary)
        }
        .padding(.top, 8)
    }

    private func overview(_ dossier: PlaceDossier) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 14) {
                if let imageURL = dossier.overview?.imageURL {
                    AsyncImage(url: imageURL) { phase in
                        switch phase {
                        case .success(let image): image.resizable().scaledToFill()
                        default: Rectangle().fill(AppTheme.raised).overlay { ProgressView() }
                        }
                    }
                    .frame(height: 185)
                    .frame(maxWidth: .infinity)
                    .clipShape(RoundedRectangle(cornerRadius: 17))
                    .clipped()
                }

                Label("Stadt & Überblick", systemImage: "building.2.fill")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(AppTheme.gold)
                Text(dossier.overview?.summary.isEmpty == false ? dossier.overview!.summary : snapshot.summary)
                    .font(.body)
                    .lineSpacing(4)
                if let articleURL = dossier.overview?.articleURL {
                    Link("Ortsartikel und Quellen öffnen", destination: articleURL)
                        .font(.subheadline.weight(.semibold))
                }
            }
        }
    }

    private func timeContext(_ dossier: PlaceDossier) -> some View {
        let moments = dossier.moments(around: request.instant, focus: timeFocus)
        return VStack(alignment: .leading, spacing: 12) {
            Label("Kontext zu \(request.instant.displayText)", systemImage: "clock.arrow.circlepath")
                .font(.title3.bold())
                .foregroundStyle(AppTheme.coral)

            GlassCard {
                VStack(alignment: .leading, spacing: 10) {
                    Text(snapshot.headline).font(.headline)
                    Text(snapshot.summary)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineSpacing(3)
                }
            }

            if moments.isEmpty {
                Text("Im angeschlossenen Ortsartikel wurde für dieses Zeitfenster kein eindeutiger lokaler Satz erkannt. Das bedeutet nicht, dass hier nichts geschah.")
                    .font(.caption)
                    .foregroundStyle(AppTheme.textSecondary)
                    .padding(.horizontal, 4)
            } else {
                ForEach(moments.prefix(8)) { moment in
                    HistoryMomentCard(moment: moment) {
                        onChooseYear(moment.year)
                        dismiss()
                    }
                }
            }

            Button {
                journeyRequest = request
            } label: {
                PrimaryButtonLabel(title: "Ort und Zeit vertiefen", icon: "arrow.up.right")
            }
            .buttonStyle(.plain)
        }
    }

    private func nearby(_ dossier: PlaceDossier) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Orte & Sehenswürdigkeiten", systemImage: "camera.fill")
                .font(.title3.bold())
                .foregroundStyle(AppTheme.gold)

            if dossier.nearby.isEmpty {
                Text("Im Umkreis sind derzeit keine verknüpften Wikipedia-Ortseinträge vorhanden.")
                    .font(.caption)
                    .foregroundStyle(AppTheme.textSecondary)
            } else {
                ForEach(dossier.nearby) { point in
                    PlacePointCard(point: point, onChooseYear: { year in
                        onChooseYear(year)
                        dismiss()
                    }, onChoosePlace: {
                        onChoosePlace(point)
                        dismiss()
                    })
                }
            }
        }
    }

    private func history(_ dossier: PlaceDossier) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Geschichtliche Anknüpfungspunkte", systemImage: "point.3.connected.trianglepath.dotted")
                .font(.title3.bold())
                .foregroundStyle(AppTheme.mint)

            if dossier.history.isEmpty {
                Text("Keine automatisch datierten Passagen erkannt.")
                    .font(.caption)
                    .foregroundStyle(AppTheme.textSecondary)
            } else {
                ForEach(dossier.history.prefix(16)) { moment in
                    HistoryMomentCard(moment: moment) {
                        onChooseYear(moment.year)
                        dismiss()
                    }
                }
            }
        }
    }

    private func sourceNote(_ dossier: PlaceDossier) -> some View {
        Label("Ortsartikel und nahe Einträge stammen aus Wikipedia; strukturierte Eckdaten aus Wikidata. Automatisch erkannte Sätze sind Hinweise und werden nicht als gesicherte Kausalität ausgegeben.", systemImage: "checkmark.seal")
            .font(.caption)
            .foregroundStyle(AppTheme.textSecondary)
            .lineSpacing(3)
            .padding(.horizontal, 4)
    }
}

private struct PlacePointCard: View {
    let point: PlacePoint
    let onChooseYear: (Int) -> Void
    let onChoosePlace: () -> Void
    @State private var showSource = false

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 11) {
                HStack(alignment: .top, spacing: 12) {
                    if let imageURL = point.imageURL {
                        AsyncImage(url: imageURL) { phase in
                            if case .success(let image) = phase { image.resizable().scaledToFill() }
                            else { Rectangle().fill(AppTheme.raised) }
                        }
                        .frame(width: 82, height: 82)
                        .clipShape(RoundedRectangle(cornerRadius: 13))
                        .clipped()
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text(point.title).font(.headline)
                        Text(point.description)
                            .font(.caption)
                            .foregroundStyle(AppTheme.textSecondary)
                            .lineLimit(3)
                    }
                    Spacer(minLength: 0)
                }

                if !point.summary.isEmpty {
                    Text(point.summary)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(5)
                }

                if !point.dates.isEmpty {
                    ScrollView(.horizontal) {
                        HStack(spacing: 8) {
                            ForEach(point.dates) { date in
                                Button { onChooseYear(date.year) } label: {
                                    Label("\(date.label) \(displayYear(date.year))", systemImage: "clock")
                                        .font(.caption.weight(.semibold))
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 8)
                                        .background(AppTheme.gold.opacity(0.14), in: Capsule())
                                }
                            }
                        }
                    }
                    .scrollIndicators(.hidden)
                }

                HStack {
                    if point.coordinate != nil {
                        Button("Auf Karte wählen") { onChoosePlace() }
                    }
                    Spacer()
                    Link("Quelle", destination: point.articleURL)
                }
                .font(.subheadline.weight(.semibold))

                DisclosureGroup("Herkunft & Sicherheit", isExpanded: $showSource) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Wikipedia · Datensatz \(point.provenance.recordID)")
                        Text(point.provenance.queryDescription)
                        Text("Nahe Einträge sind nicht automatisch Sehenswürdigkeiten; die Einordnung hängt von der Quelldichte ab.")
                    }
                    .font(.caption)
                    .foregroundStyle(AppTheme.textSecondary)
                    .padding(.top, 7)
                }
                .font(.caption.weight(.semibold))
            }
        }
    }
}

private struct HistoryMomentCard: View {
    let moment: PlaceHistoryMoment
    let onTravel: () -> Void

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Text(displayYear(moment.year))
                    .font(.title3.bold().monospacedDigit())
                    .foregroundStyle(AppTheme.mint)
                Text(moment.text)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineSpacing(3)
                HStack {
                    Button("Zu diesem Jahr") { onTravel() }
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    Link("Quelle", destination: moment.provenance.sourceURL)
                        .font(.caption.weight(.semibold))
                }
            }
        }
    }
}

private func displayYear(_ year: Int) -> String {
    year < 0 ? "\(abs(year)) v. Chr." : String(year)
}

