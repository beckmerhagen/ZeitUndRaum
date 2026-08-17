import CoreLocation
import MapKit
import SwiftUI

private enum AtlasSearchScope: String, CaseIterable, Identifiable {
    case place = "Ort"
    case topic = "Thema"
    var id: Self { self }
}

struct RootView: View {
    @StateObject private var locationService = LocationService()
    @StateObject private var placeResearch = PlaceResearchModel()
    @StateObject private var speech = SpeechInputService()

    @State private var instant = TravelInstant(year: Calendar.current.component(.year, from: .now))
    @State private var timelineProgress = TemporalScale.progress(for: Calendar.current.component(.year, from: .now))
    @State private var coordinate = CLLocationCoordinate2D(latitude: 52.5200, longitude: 13.4050)
    @State private var locationName = "Berlin"
    @State private var camera: MapCameraPosition = .region(MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 52.5200, longitude: 13.4050),
        span: MKCoordinateSpan(latitudeDelta: 0.45, longitudeDelta: 0.45)
    ))
    @State private var visibleRegion = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 52.5200, longitude: 13.4050),
        span: MKCoordinateSpan(latitudeDelta: 0.45, longitudeDelta: 0.45)
    )

    @State private var timeFocus: TimeFocus = .decade
    @State private var radiusKilometers = 25
    @State private var query = ""
    @State private var searchScope: AtlasSearchScope = .place
    @State private var isPlaceSearching = false
    @State private var searchError: String?
    @State private var showTimePicker = false
    @State private var showDossier = false
    @State private var showTopicExplorer = false
    @State private var topicInitialQuery = ""
    @State private var didRequestInitialLocation = false
    @FocusState private var searchIsFocused: Bool

    private let radiusPresets = [1, 10, 25, 50, 250, 1_000]

    private var request: JourneyRequest {
        JourneyRequest(instant: instant, coordinate: coordinate, locationName: locationName)
    }

    private var snapshot: HistoricalSnapshot {
        HistoricalAtlas().snapshot(for: request)
    }

    var body: some View {
        ZStack {
            MapReader { proxy in
                Map(position: $camera) {
                    MapCircle(center: coordinate, radius: CLLocationDistance(radiusKilometers * 1_000))
                        .foregroundStyle(AppTheme.mint.opacity(0.10))
                        .stroke(AppTheme.mint.opacity(0.65), lineWidth: 2)
                    if let dossier = placeResearch.dossier {
                        ForEach(dossier.nearby.filter { $0.coordinate != nil }.prefix(12)) { point in
                            if let pointCoordinate = point.coordinate {
                                Marker(point.title, systemImage: "building.columns", coordinate: pointCoordinate)
                                    .tint(AppTheme.gold)
                            }
                        }
                    }

                    Marker(locationName, coordinate: coordinate)
                        .tint(AppTheme.coral)
                }
                .mapStyle(.standard(elevation: .realistic, emphasis: .muted))
                .mapControls {
                    MapCompass()
                    MapScaleView()
                    MapUserLocationButton()
                }
                .onMapCameraChange(frequency: .onEnd) { context in
                    visibleRegion = context.region
                }
                .onTapGesture { point in
                    guard !searchIsFocused, let chosen = proxy.convert(point, from: .local) else { return }
                    chooseMapPoint(chosen)
                }
                .ignoresSafeArea()
            }

            LinearGradient(
                colors: [Color.black.opacity(0.58), .clear, .clear, Color.black.opacity(0.72)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()
            .allowsHitTesting(false)
        }
        .overlay(alignment: .top) { topOverlay }
        .overlay(alignment: .bottom) { bottomOverlay }
        .tint(AppTheme.mint)
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showTimePicker) {
            TimePickerSheet(instant: $instant)
                .onDisappear { timelineProgress = TemporalScale.progress(for: instant.year) }
        }
        .fullScreenCover(isPresented: $showDossier) {
            PlaceDossierView(
                model: placeResearch,
                request: request,
                timeFocus: timeFocus,
                radiusKilometers: radiusKilometers,
                onChooseYear: setYear,
                onChoosePlace: choosePlacePoint
            )
        }
        .fullScreenCover(isPresented: $showTopicExplorer) {
            TopicExplorerView(
                originCoordinate: coordinate,
                originName: locationName,
                initialQuery: topicInitialQuery,
                initialTimeFocus: timeFocus,
                initialRadiusKilometers: radiusKilometers,
                onTravel: applyTopicTravel
            )
        }
        .onAppear {
            guard !didRequestInitialLocation else { return }
            didRequestInitialLocation = true
            locationService.requestCurrentLocation()
            Task { await placeResearch.load(placeName: locationName, coordinate: coordinate) }
        }
        .onChange(of: locationService.currentCoordinate?.latitude) { _, _ in
            guard let current = locationService.currentCoordinate else { return }
            setLocation(name: locationService.currentPlaceName ?? "Mein Standort", coordinate: current)
        }
        .onChange(of: locationService.currentPlaceName) { _, name in
            guard let name, locationService.currentCoordinate != nil else { return }
            locationName = name
        }
        .onChange(of: speech.transcript) { _, transcript in
            if !transcript.isEmpty { query = transcript }
        }
    }

    private var topOverlay: some View {
        VStack(alignment: .leading, spacing: 12) {
            searchField

            if !searchIsFocused {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Wo möchtest du")
                    Text("die Zeit betreten?")
                }
                .font(.system(size: 32, weight: .bold, design: .rounded))
                .tracking(-0.7)
                .shadow(color: .black.opacity(0.6), radius: 8, y: 3)

                Label("Tippe auf die Karte oder suche einen Ort", systemImage: "hand.tap")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color.white.opacity(0.8))
                    .shadow(color: .black.opacity(0.7), radius: 5)
            }

            if let searchError {
                Label(searchError, systemImage: "exclamationmark.circle")
                    .font(.caption)
                    .padding(9)
                    .background(.ultraThickMaterial, in: Capsule())
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
    }

    private var searchField: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField(searchScope == .place ? "Ort suchen" : "Thema entdecken", text: $query)
                    .focused($searchIsFocused)
                    .textInputAutocapitalization(.sentences)
                    .submitLabel(.search)
                    .onSubmit { performSearch() }
                if isPlaceSearching {
                    ProgressView().controlSize(.small)
                } else if !query.isEmpty {
                    Button { query = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }
                }
                Button {
                    Task { await speech.toggle() }
                } label: {
                    Image(systemName: speech.isRecording ? "waveform.circle.fill" : "mic.circle.fill")
                        .font(.title3)
                        .foregroundStyle(speech.isRecording ? AppTheme.coral : AppTheme.mint)
                }
                .accessibilityLabel(speech.isRecording ? "Aufnahme beenden" : "Suche sprechen")
            }
            .padding(.horizontal, 14)
            .frame(height: 49)
            .background(.ultraThickMaterial, in: RoundedRectangle(cornerRadius: 16))

            if searchIsFocused {
                Picker("Suchart", selection: $searchScope) {
                    ForEach(AtlasSearchScope.allCases) { scope in
                        Label(scope.rawValue, systemImage: scope == .place ? "mappin" : "sparkle.magnifyingglass").tag(scope)
                    }
                }
                .pickerStyle(.segmented)
                .padding(5)
                .background(.ultraThickMaterial, in: RoundedRectangle(cornerRadius: 13))
            }
        }
        .shadow(color: .black.opacity(0.25), radius: 16, y: 6)
    }

    private var bottomOverlay: some View {
        VStack(spacing: 11) {
            Button { showDossier = true } label: {
                HStack(spacing: 12) {
                    Image(systemName: "mappin.circle.fill")
                        .font(.title2)
                        .foregroundStyle(AppTheme.coral)
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text(locationName).font(.headline)
                            if placeResearch.isLoading { ProgressView().controlSize(.mini) }
                        }
                        Text(placeTeaser)
                            .font(.caption)
                            .foregroundStyle(AppTheme.textSecondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "chevron.up")
                        .font(.caption.bold())
                }
                .padding(13)
                .background(.ultraThickMaterial, in: RoundedRectangle(cornerRadius: 18))
            }
            .buttonStyle(.plain)

            VStack(spacing: 9) {
                HStack(alignment: .center) {
                    Button { setYear(instant.year - 1) } label: {
                        Image(systemName: "chevron.left").frame(width: 34, height: 34)
                    }
                    Spacer()
                    Button { showTimePicker = true } label: {
                        VStack(spacing: 1) {
                            Text(instant.displayText)
                                .font(.system(size: 26, weight: .bold, design: .rounded).monospacedDigit())
                                .foregroundStyle(AppTheme.gold)
                            Text(snapshot.eraName)
                                .font(.caption2)
                                .foregroundStyle(AppTheme.textSecondary)
                        }
                    }
                    Spacer()
                    Button { setYear(instant.year + 1) } label: {
                        Image(systemName: "chevron.right").frame(width: 34, height: 34)
                    }
                }

                Slider(value: $timelineProgress, in: 0...1) { _ in
                    instant.precision = .year
                    instant.year = TemporalScale.year(for: timelineProgress)
                }
                .tint(AppTheme.gold)

                HStack(spacing: 8) {
                    Menu {
                        ForEach(TimeFocus.allCases) { focus in
                            Button {
                                timeFocus = focus
                            } label: {
                                if timeFocus == focus { Label(focus.rawValue, systemImage: "checkmark") }
                                else { Text(focus.rawValue) }
                            }
                        }
                    } label: {
                        focusChip(timeFocus.rawValue, icon: "clock")
                    }

                    Menu {
                        ForEach(radiusPresets, id: \.self) { radius in
                            Button {
                                radiusKilometers = radius
                                zoomToSpatialFocus()
                            } label: {
                                if radiusKilometers == radius { Label("\(radius) km", systemImage: "checkmark") }
                                else { Text("\(radius) km") }
                            }
                        }
                    } label: {
                        focusChip("\(radiusKilometers) km", icon: "scope")
                    }

                    Spacer(minLength: 0)

                    Button {
                        setYear(Calendar.current.component(.year, from: .now))
                    } label: {
                        Text("JETZT")
                            .font(.caption2.weight(.bold))
                            .foregroundStyle(AppTheme.mint)
                            .padding(.horizontal, 9)
                            .padding(.vertical, 8)
                            .background(AppTheme.mint.opacity(0.12), in: Capsule())
                    }
                }
            }
            .padding(14)
            .background(.ultraThickMaterial, in: RoundedRectangle(cornerRadius: 22))
        }
        .padding(.horizontal, 14)
        .padding(.bottom, 8)
        .shadow(color: .black.opacity(0.28), radius: 20, y: 8)
    }

    private var placeTeaser: String {
        if let overview = placeResearch.dossier?.overview {
            return overview.description
        }
        if let error = placeResearch.errorMessage { return error }
        return snapshot.headline
    }

    private func focusChip(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(AppTheme.raised.opacity(0.82), in: Capsule())
    }

    private func performSearch() {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !term.isEmpty else { return }
        speech.stop()
        searchError = nil
        searchIsFocused = false

        if searchScope == .topic {
            topicInitialQuery = term
            showTopicExplorer = true
            return
        }

        isPlaceSearching = true
        Task {
            defer { isPlaceSearching = false }
            let searchRequest = MKLocalSearch.Request()
            searchRequest.naturalLanguageQuery = term
            searchRequest.region = visibleRegion
            do {
                let response = try await MKLocalSearch(request: searchRequest).start()
                guard let item = response.mapItems.first else {
                    searchError = "Kein Ort gefunden."
                    return
                }
                setLocation(
                    name: item.name ?? item.placemark.locality ?? term,
                    coordinate: item.placemark.coordinate
                )
                query = ""
            } catch {
                searchError = "Die Ortssuche ist gerade nicht erreichbar."
            }
        }
    }

    private func chooseMapPoint(_ chosen: CLLocationCoordinate2D) {
        coordinate = chosen
        locationName = "Ort wird bestimmt …"
        Task {
            let name = await LocationService.placeName(for: chosen)
            setLocation(name: name, coordinate: chosen, moveCamera: false)
        }
    }

    private func choosePlacePoint(_ point: PlacePoint) {
        guard let newCoordinate = point.coordinate else { return }
        setLocation(name: point.title, coordinate: newCoordinate)
    }

    private func setLocation(name: String, coordinate newCoordinate: CLLocationCoordinate2D, moveCamera: Bool = true) {
        coordinate = newCoordinate
        locationName = name
        if moveCamera { zoomToSpatialFocus() }
        Task { await placeResearch.load(placeName: name, coordinate: newCoordinate) }
    }

    private func setYear(_ year: Int) {
        let adjusted = year == 0 ? 1 : max(-4_540_000_000, min(year, Calendar.current.component(.year, from: .now)))
        instant = TravelInstant(year: adjusted)
        timelineProgress = TemporalScale.progress(for: adjusted)
    }

    private func zoomToSpatialFocus() {
        let latitudeDelta = max(0.025, min(80, Double(radiusKilometers) * 2.5 / 111))
        let longitudeCorrection = max(0.25, cos(coordinate.latitude * .pi / 180))
        let longitudeDelta = min(160, latitudeDelta / longitudeCorrection)
        withAnimation(.easeInOut(duration: 0.55)) {
            camera = .region(MKCoordinateRegion(
                center: coordinate,
                span: MKCoordinateSpan(latitudeDelta: latitudeDelta, longitudeDelta: longitudeDelta)
            ))
        }
    }

    private func applyTopicTravel(_ selection: TopicTravelSelection) {
        setYear(selection.year)
        timeFocus = selection.timeFocus
        radiusKilometers = selection.radiusKilometers
        if let topicCoordinate = selection.coordinate {
            setLocation(name: selection.locationName ?? selection.topicTitle, coordinate: topicCoordinate)
        }
        showTopicExplorer = false
    }
}
