import MapKit
import SwiftUI

struct JourneyView: View {
    let request: JourneyRequest
    @State private var selectedCategory: KnowledgeCategory
    @StateObject private var researchModel: ResearchViewModel

    init(request: JourneyRequest) {
        self.request = request
        _researchModel = StateObject(wrappedValue: ResearchViewModel(request: request))
        _selectedCategory = State(initialValue: .overview)
    }

    private var snapshot: HistoricalSnapshot {
        HistoricalAtlas().snapshot(for: request)
    }

    private var visibleFacts: [ContextFact] {
        selectedCategory == .overview ? snapshot.facts : snapshot.facts.filter { $0.category == selectedCategory }
    }

    var body: some View {
        ZStack {
            CosmicBackground()

            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    hero
                    categoryPicker
                    summaryCard
                    facts
                    reconstructionNote
                }
                .padding(.bottom, 40)
            }
            .scrollIndicators(.hidden)
        }
        .navigationTitle(request.instant.displayText)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(AppTheme.ink.opacity(0.9), for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .task {
            await researchModel.loadIfNeeded()
        }
    }

    private var hero: some View {
        ZStack(alignment: .bottomLeading) {
            Map(initialPosition: .region(MKCoordinateRegion(
                center: request.coordinate,
                span: MKCoordinateSpan(latitudeDelta: 1.8, longitudeDelta: 1.8)
            ))) {
                Marker(request.locationName, coordinate: request.coordinate)
                    .tint(AppTheme.coral)
            }
            .allowsHitTesting(false)
            .frame(height: 310)

            LinearGradient(
                colors: [.clear, AppTheme.ink.opacity(0.35), AppTheme.ink],
                startPoint: .top,
                endPoint: .bottom
            )

            VStack(alignment: .leading, spacing: 8) {
                Text(snapshot.eraName.uppercased())
                    .font(.caption.weight(.bold))
                    .tracking(1.8)
                    .foregroundStyle(AppTheme.gold)

                Text(snapshot.headline)
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                    .lineLimit(3)

                HStack(spacing: 8) {
                    Label(request.locationName, systemImage: "mappin")
                    Text("·")
                    Text(request.instant.displayText)
                }
                .font(.subheadline.weight(.medium))
                .foregroundStyle(AppTheme.textSecondary)

                Label("Geografischer Bezug: heutige Karte", systemImage: "info.circle")
                    .font(.caption2)
                    .foregroundStyle(Color.white.opacity(0.52))
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
    }

    private var categoryPicker: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 9) {
                ForEach(KnowledgeCategory.allCases) { category in
                    Button {
                        withAnimation(.snappy) { selectedCategory = category }
                    } label: {
                        Label(categoryTitle(category), systemImage: category.icon)
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 13)
                            .padding(.vertical, 10)
                            .foregroundStyle(selectedCategory == category ? AppTheme.ink : Color.white.opacity(0.78))
                            .background(selectedCategory == category ? category.tint : AppTheme.raised, in: Capsule())
                    }
                }
            }
            .padding(.horizontal, 20)
        }
        .scrollIndicators(.hidden)
    }

    private func categoryTitle(_ category: KnowledgeCategory) -> String {
        guard category == .sources, case .loaded(let bundle) = researchModel.state else {
            return category.rawValue
        }
        return "Quellen \(bundle.evidence.count)"
    }

    private var summaryCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 15) {
                Text("PANORAMA")
                    .font(.caption2.weight(.bold))
                    .tracking(1.8)
                    .foregroundStyle(AppTheme.mint)
                Text(snapshot.summary)
                    .font(.body)
                    .lineSpacing(4)

                Divider().overlay(Color.white.opacity(0.1))

                Label(snapshot.atmosphere, systemImage: "wind")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(AppTheme.textSecondary)
            }
        }
        .padding(.horizontal, 20)
    }

    @ViewBuilder
    private var facts: some View {
        if selectedCategory == .sources {
            ResearchSourcesView(model: researchModel, request: request)
        } else {
            LazyVStack(spacing: 14) {
            ForEach(visibleFacts) { fact in
                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Image(systemName: fact.category.icon)
                                .font(.headline)
                                .foregroundStyle(fact.category.tint)
                                .frame(width: 38, height: 38)
                                .background(fact.category.tint.opacity(0.12), in: Circle())
                            Text(fact.category.rawValue.uppercased())
                                .font(.caption2.weight(.bold))
                                .tracking(1.4)
                                .foregroundStyle(fact.category.tint)
                            Spacer()
                        }

                        Text(fact.title)
                            .font(.title3.weight(.bold))
                        Text(fact.body)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.textSecondary)
                            .lineSpacing(4)

                        if let detail = fact.detail {
                            Text(detail)
                                .font(.caption)
                                .padding(10)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(AppTheme.raised, in: RoundedRectangle(cornerRadius: 11))
                        }
                    }
                }
            }
            }
            .padding(.horizontal, 20)
        }
    }

    private var reconstructionNote: some View {
        VStack(alignment: .leading, spacing: 9) {
            Label("Wie sicher ist dieses Bild?", systemImage: "scope")
                .font(.headline)
                .foregroundStyle(AppTheme.gold)
            Text(snapshot.confidence)
                .font(.subheadline)
                .foregroundStyle(AppTheme.textSecondary)
            Text("Die Epochenkontexte bleiben kuratierte Synthesen. Unter „Quellen“ findest du live geladene Belege mit Provenienz, Lizenz und einer getrennten Bewertung ihrer räumlichen und zeitlichen Aussagekraft.")
                .font(.caption)
                .foregroundStyle(Color.white.opacity(0.48))
                .lineSpacing(3)
        }
        .padding(20)
    }
}
