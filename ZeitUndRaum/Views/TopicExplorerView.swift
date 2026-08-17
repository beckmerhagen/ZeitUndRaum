import CoreLocation
import MapKit
import SwiftUI

struct TopicExplorerView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model: TopicResearchModel
    @StateObject private var speech = SpeechInputService()
    @State private var query: String
    @State private var timeFocus: TimeFocus
    @State private var radiusKilometers: Int

    private let examples = ["Alter Elbtunnel", "Französische Revolution", "Dreißigjähriger Krieg"]
    private let radiusPresets = [1, 10, 50, 250, 1_000]
    private let initialQuery: String
    private let onTravel: ((TopicTravelSelection) -> Void)?

    init(
        originCoordinate: CLLocationCoordinate2D,
        originName: String,
        initialQuery: String = "",
        initialTimeFocus: TimeFocus = .exact,
        initialRadiusKilometers: Int = 50,
        onTravel: ((TopicTravelSelection) -> Void)? = nil
    ) {
        _model = StateObject(wrappedValue: TopicResearchModel(originCoordinate: originCoordinate, originName: originName))
        _query = State(initialValue: initialQuery)
        _timeFocus = State(initialValue: initialTimeFocus)
        _radiusKilometers = State(initialValue: initialRadiusKilometers)
        self.initialQuery = initialQuery
        self.onTravel = onTravel
    }

    var body: some View {
        NavigationStack {
            ZStack {
                CosmicBackground()

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 22) {
                        introduction
                        searchCard

                        if model.isSearching && model.profile == nil {
                            loadingCard("Thema und Eckdaten werden recherchiert …")
                        }

                        if let error = model.errorMessage {
                            errorCard(error)
                        }

                        if model.candidates.count > 1 {
                            candidatePicker
                        }

                        if let profile = model.profile {
                            profileView(profile)
                            focusControls(profile)
                            contextView(profile)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 42)
                }
                .scrollIndicators(.hidden)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Schließen") { dismiss() }
                }
            }
            .onChange(of: speech.transcript) { _, transcript in
                if !transcript.isEmpty { query = transcript }
            }
            .task {
                guard !initialQuery.isEmpty, model.profile == nil else { return }
                await performSearch()
            }
        }
        .tint(AppTheme.mint)
        .preferredColorScheme(.dark)
    }

    private var introduction: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("ZUSAMMENHÄNGE", systemImage: "point.3.connected.trianglepath.dotted")
                .font(.caption.weight(.bold))
                .tracking(1.8)
                .foregroundStyle(AppTheme.mint)
            Text("Ein Stichwort.\nSeine Welt.")
                .font(.system(size: 37, weight: .bold, design: .rounded))
                .tracking(-1)
            Text("Wir verbinden Eckdaten mit zeitgleichen Bauwerken, Ereignissen und kulturellen Strömungen. Nähe ist dabei ein Hinweis – kein Beweis für Ursache und Wirkung.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.textSecondary)
                .lineSpacing(4)
        }
        .padding(.top, 8)
    }

    private var searchCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 9) {
                    Image(systemName: "sparkle.magnifyingglass")
                        .foregroundStyle(AppTheme.gold)
                    TextField("z. B. Elbtunnel", text: $query)
                        .textInputAutocapitalization(.sentences)
                        .submitLabel(.search)
                        .onSubmit { Task { await performSearch() } }

                    Button {
                        Task { await speech.toggle() }
                    } label: {
                        Image(systemName: speech.isRecording ? "waveform.circle.fill" : "mic.circle.fill")
                            .font(.title2)
                            .foregroundStyle(speech.isRecording ? AppTheme.coral : AppTheme.mint)
                            .symbolEffect(.pulse, isActive: speech.isRecording)
                    }
                    .accessibilityLabel(speech.isRecording ? "Aufnahme beenden" : "Stichwort sprechen")

                    Button { Task { await performSearch() } } label: {
                        Image(systemName: "arrow.right")
                            .font(.headline)
                            .foregroundStyle(AppTheme.ink)
                            .frame(width: 38, height: 38)
                            .background(AppTheme.mint, in: Circle())
                    }
                    .disabled(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isSearching)
                    .accessibilityLabel("Thema suchen")
                }
                .padding(10)
                .background(AppTheme.raised, in: RoundedRectangle(cornerRadius: 16))

                if speech.isRecording {
                    Label("Ich höre zu … Tippe auf das Mikrofon, wenn du fertig bist.", systemImage: "waveform")
                        .font(.caption)
                        .foregroundStyle(AppTheme.coral)
                } else if let error = speech.errorMessage {
                    Text(error).font(.caption).foregroundStyle(AppTheme.coral)
                }

                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(examples, id: \.self) { example in
                            Button(example) {
                                query = example
                                Task { await performSearch() }
                            }
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 11)
                            .padding(.vertical, 8)
                            .background(AppTheme.raised, in: Capsule())
                        }
                    }
                }
                .scrollIndicators(.hidden)
            }
        }
        .cardShadow()
    }

    private var candidatePicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("WELCHES THEMA MEINST DU?")
                .font(.caption2.weight(.bold))
                .tracking(1.4)
                .foregroundStyle(AppTheme.textSecondary)

            ScrollView(.horizontal) {
                HStack(spacing: 10) {
                    ForEach(model.candidates.prefix(5)) { candidate in
                        Button {
                            Task { await model.select(candidate, focus: timeFocus, radiusKilometers: radiusKilometers) }
                        } label: {
                            HStack(alignment: .top, spacing: 10) {
                                Image(systemName: model.profile?.candidate.id == candidate.id ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(AppTheme.mint)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(candidate.label).font(.subheadline.weight(.semibold))
                                    Text(candidate.description)
                                        .font(.caption)
                                        .foregroundStyle(AppTheme.textSecondary)
                                        .lineLimit(2)
                                }
                                Spacer(minLength: 0)
                            }
                            .frame(width: 260, alignment: .leading)
                            .padding(13)
                            .background(AppTheme.panel, in: RoundedRectangle(cornerRadius: 16))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .scrollIndicators(.hidden)
        }
    }

    @ViewBuilder
    private func profileView(_ profile: TopicProfile) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 15) {
                if let imageURL = profile.imageURL {
                    AsyncImage(url: imageURL) { phase in
                        switch phase {
                        case .success(let image): image.resizable().scaledToFill()
                        case .failure: imagePlaceholder
                        default: ZStack { imagePlaceholder; ProgressView() }
                        }
                    }
                    .frame(height: 190)
                    .frame(maxWidth: .infinity)
                    .clipShape(RoundedRectangle(cornerRadius: 17))
                    .clipped()
                }

                Text(profile.candidate.description.uppercased())
                    .font(.caption2.weight(.bold))
                    .tracking(1.3)
                    .foregroundStyle(AppTheme.gold)
                Text(profile.candidate.label)
                    .font(.title2.bold())
                Text(profile.summary)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineSpacing(4)

                if let articleURL = profile.articleURL {
                    Link(destination: articleURL) {
                        Label("Übersichtsartikel öffnen", systemImage: "arrow.up.right.square")
                            .font(.subheadline.weight(.semibold))
                    }
                }
            }
        }

        VStack(alignment: .leading, spacing: 12) {
            Label("Eckdaten", systemImage: "calendar.badge.clock")
                .font(.title3.bold())
            if profile.milestones.isEmpty {
                Text("In den strukturierten Quellen sind keine eindeutigen Eckdaten hinterlegt.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.textSecondary)
            } else {
                ForEach(profile.milestones) { milestone in
                    MilestoneCard(milestone: milestone, hasTopicPlace: profile.coordinate != nil) { includePlace in
                        guard let year = milestone.year else { return }
                        onTravel?(TopicTravelSelection(
                            year: year,
                            coordinate: includePlace ? profile.coordinate : nil,
                            locationName: includePlace ? profile.candidate.label : nil,
                            topicTitle: profile.candidate.label,
                            timeFocus: timeFocus,
                            radiusKilometers: radiusKilometers
                        ))
                        dismiss()
                    }
                }
            }
        }
    }

    private func focusControls(_ profile: TopicProfile) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 17) {
                Label("Fokus verändern", systemImage: "scope")
                    .font(.title3.bold())

                VStack(alignment: .leading, spacing: 8) {
                    Text("ZEITRAUM").focusLabel()
                    Picker("Zeitraum", selection: $timeFocus) {
                        ForEach(TimeFocus.allCases) { focus in Text(focus.rawValue).tag(focus) }
                    }
                    .pickerStyle(.segmented)
                    Text(rangeDescription(profile.range(for: timeFocus)))
                        .font(.caption)
                        .foregroundStyle(AppTheme.textSecondary)
                }

                VStack(alignment: .leading, spacing: 9) {
                    HStack {
                        Text("UMKREIS").focusLabel()
                        Spacer()
                        Text("\(radiusKilometers) km")
                            .font(.subheadline.weight(.bold).monospacedDigit())
                            .foregroundStyle(AppTheme.mint)
                    }

                    ScrollView(.horizontal) {
                        HStack(spacing: 8) {
                            ForEach(radiusPresets, id: \.self) { radius in
                                Button(radius == 1_000 ? "1000 km" : "\(radius) km") {
                                    radiusKilometers = radius
                                }
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(radiusKilometers == radius ? AppTheme.ink : .white)
                                .padding(.horizontal, 11)
                                .padding(.vertical, 8)
                                .background(radiusKilometers == radius ? AppTheme.mint : AppTheme.raised, in: Capsule())
                            }
                        }
                    }
                    .scrollIndicators(.hidden)

                    Stepper("Genau einstellen", value: $radiusKilometers, in: 1...1_000)
                        .font(.subheadline)
                }

                Button {
                    Task { await model.reloadContext(focus: timeFocus, radiusKilometers: radiusKilometers) }
                } label: {
                    Label("Zusammenhänge neu berechnen", systemImage: "arrow.triangle.2.circlepath")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .foregroundStyle(AppTheme.ink)
                        .background(AppTheme.mint, in: RoundedRectangle(cornerRadius: 14))
                }
                .disabled(model.isLoadingContext)
            }
        }
    }

    @ViewBuilder
    private func contextView(_ profile: TopicProfile) -> some View {
        if model.isLoadingContext {
            loadingCard("Zeitliche und räumliche Nachbarschaften werden gesucht …")
        }

        if let context = model.context {
            VStack(alignment: .leading, spacing: 15) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("DIE WELT DARUM HERUM")
                        .font(.caption2.weight(.bold))
                        .tracking(1.5)
                        .foregroundStyle(AppTheme.mint)
                    Text("\(rangeDescription(context.range)) · \(context.radiusKilometers) km um \(context.centerName)")
                        .font(.title3.bold())
                }

                contextMap(context, profile: profile)

                ForEach(TopicConnectionKind.allCases) { kind in
                    let connections = context.connections.filter { $0.kind == kind }
                    VStack(alignment: .leading, spacing: 10) {
                        Label(kind.rawValue, systemImage: kind.icon)
                            .font(.headline)
                            .foregroundStyle(kind.tint)
                        if connections.isEmpty {
                            Text("Keine passend datierten Einträge in den verbundenen Quellen gefunden.")
                                .font(.caption)
                                .foregroundStyle(AppTheme.textSecondary)
                                .padding(.vertical, 4)
                        } else {
                            ForEach(connections) { connection in
                                ConnectionCard(connection: connection)
                            }
                        }
                    }
                }

                if !context.errors.isEmpty {
                    GlassCard {
                        DisclosureGroup("Einige Quellen antworteten nicht") {
                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(context.errors, id: \.self) { Text($0).font(.caption) }
                            }
                            .foregroundStyle(AppTheme.textSecondary)
                            .padding(.top, 8)
                        }
                    }
                }

                Label("Diese Ansicht zeigt Überschneidungen. Ein historischer Zusammenhang muss anschließend durch Fachliteratur oder Archive belegt werden.", systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineSpacing(3)
            }
        }
    }

    private func contextMap(_ context: TopicContext, profile: TopicProfile) -> some View {
        Map(initialPosition: .region(MKCoordinateRegion(
            center: context.centerCoordinate,
            span: MKCoordinateSpan(
                latitudeDelta: max(0.06, Double(context.radiusKilometers) / 45),
                longitudeDelta: max(0.08, Double(context.radiusKilometers) / 30)
            )
        ))) {
            Marker(profile.candidate.label, coordinate: context.centerCoordinate)
                .tint(AppTheme.coral)
            ForEach(context.connections.filter { $0.coordinate != nil }.prefix(24)) { connection in
                if let coordinate = connection.coordinate {
                    Marker(connection.title, systemImage: connection.kind.icon, coordinate: coordinate)
                        .tint(connection.kind.tint)
                }
            }
        }
        .frame(height: 215)
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .id("\(context.centerCoordinate.latitude)-\(context.radiusKilometers)-\(context.range.lowerBound)")
    }

    private func loadingCard(_ text: String) -> some View {
        GlassCard {
            HStack(spacing: 13) {
                ProgressView().tint(AppTheme.mint)
                Text(text).font(.subheadline.weight(.semibold))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func errorCard(_ text: String) -> some View {
        GlassCard {
            Label(text, systemImage: "exclamationmark.triangle.fill")
                .font(.subheadline)
                .foregroundStyle(AppTheme.coral)
        }
    }

    private var imagePlaceholder: some View {
        Rectangle()
            .fill(AppTheme.raised)
            .overlay { Image(systemName: "photo").font(.largeTitle).foregroundStyle(AppTheme.gold) }
    }

    private func rangeDescription(_ range: ClosedRange<Int>) -> String {
        if range.lowerBound == range.upperBound { return displayYear(range.lowerBound) }
        return "\(displayYear(range.lowerBound))–\(displayYear(range.upperBound))"
    }

    private func displayYear(_ year: Int) -> String {
        year < 0 ? "\(abs(year)) v. Chr." : String(year)
    }

    private func performSearch() async {
        speech.stop()
        await model.search(query, focus: timeFocus, radiusKilometers: radiusKilometers)
    }
}

private struct MilestoneCard: View {
    let milestone: TopicMilestone
    let hasTopicPlace: Bool
    let onTravel: (Bool) -> Void
    @State private var showSource = false

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 9) {
                HStack {
                    Text(milestone.label.uppercased())
                        .font(.caption2.weight(.bold))
                        .tracking(1.1)
                        .foregroundStyle(AppTheme.gold)
                    Spacer()
                    confidenceBadge(milestone.confidence)
                }
                Text(milestone.value)
                    .font(milestone.value.count < 20 ? .title3.bold() : .subheadline)
                    .lineSpacing(3)
                if milestone.year != nil {
                    HStack(spacing: 9) {
                        Button("Zeit übernehmen") { onTravel(false) }
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                            .background(AppTheme.mint.opacity(0.14), in: Capsule())
                        if hasTopicPlace {
                            Button { onTravel(true) } label: {
                                Label("Mit Ort", systemImage: "mappin")
                                    .font(.caption.weight(.semibold))
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 8)
                                    .background(AppTheme.raised, in: Capsule())
                            }
                        }
                    }
                }
                DisclosureGroup("Herkunft", isExpanded: $showSource) {
                    SourceDetails(provenance: milestone.provenance)
                        .padding(.top, 8)
                }
                .font(.caption.weight(.semibold))
            }
        }
    }
}

private struct ConnectionCard: View {
    let connection: TopicConnection
    @State private var showDetails = false

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 11) {
                HStack(alignment: .firstTextBaseline) {
                    Text(connection.title).font(.headline)
                    Spacer()
                    if let year = connection.year { Text(String(year)).font(.caption.bold().monospacedDigit()).foregroundStyle(connection.kind.tint) }
                }
                Text(connection.description)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineSpacing(3)
                HStack(spacing: 12) {
                    if let distance = connection.distanceKilometers {
                        Label("\(distance.formatted(.number.precision(.fractionLength(1)))) km", systemImage: "location")
                    }
                    Label("Vertrauen \(connection.uncertainty.confidence.rawValue)", systemImage: "checkmark.seal")
                }
                .font(.caption2)
                .foregroundStyle(connection.uncertainty.confidence.tint)

                DisclosureGroup("Herkunft & Unsicherheit", isExpanded: $showDetails) {
                    VStack(alignment: .leading, spacing: 8) {
                        Label(connection.uncertainty.spatialLabel, systemImage: "scope")
                        Label(connection.uncertainty.temporalLabel, systemImage: "clock")
                        ForEach(connection.uncertainty.reasons, id: \.self) { reason in
                            Label(reason, systemImage: "exclamationmark.circle")
                        }
                        SourceDetails(provenance: connection.provenance)
                    }
                    .font(.caption)
                    .foregroundStyle(AppTheme.textSecondary)
                    .padding(.top, 8)
                }
                .font(.subheadline.weight(.semibold))

                Link(destination: connection.provenance.sourceURL) {
                    Label("Originalquelle öffnen", systemImage: "arrow.up.right.square")
                        .font(.subheadline.weight(.semibold))
                }
            }
        }
    }
}

private struct SourceDetails: View {
    let provenance: SourceProvenance

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("\(provenance.provider) · \(provenance.recordID)")
            Text(provenance.queryDescription)
            Text("Lizenz: \(provenance.licenseName)")
            Text("Abruf: \(provenance.retrievedAt.formatted(date: .numeric, time: .shortened))")
            Link("Datensatz öffnen", destination: provenance.sourceURL)
        }
        .font(.caption)
        .foregroundStyle(AppTheme.textSecondary)
    }
}

private func confidenceBadge(_ confidence: EvidenceConfidence) -> some View {
    Text("Vertrauen \(confidence.rawValue)")
        .font(.caption2.weight(.bold))
        .foregroundStyle(confidence.tint)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(confidence.tint.opacity(0.12), in: Capsule())
}

private extension Text {
    func focusLabel() -> some View {
        font(.caption2.weight(.bold))
            .tracking(1.2)
            .foregroundStyle(AppTheme.textSecondary)
    }
}
