import CoreLocation
import MapKit
import SwiftUI

struct LocationPickerSheet: View {
    @Binding var coordinate: CLLocationCoordinate2D
    @Binding var locationName: String
    @Environment(\.dismiss) private var dismiss

    @State private var draftCoordinate: CLLocationCoordinate2D
    @State private var draftName: String
    @State private var query = ""
    @State private var camera: MapCameraPosition
    @State private var visibleRegion: MKCoordinateRegion
    @State private var isSearching = false

    init(coordinate: Binding<CLLocationCoordinate2D>, locationName: Binding<String>) {
        _coordinate = coordinate
        _locationName = locationName
        let initial = coordinate.wrappedValue
        _draftCoordinate = State(initialValue: initial)
        _draftName = State(initialValue: locationName.wrappedValue)
        let region = MKCoordinateRegion(center: initial, span: MKCoordinateSpan(latitudeDelta: 8, longitudeDelta: 8))
        _visibleRegion = State(initialValue: region)
        _camera = State(initialValue: .region(region))
    }

    var body: some View {
        NavigationStack {
            MapReader { proxy in
                Map(position: $camera) {
                    Marker(draftName, coordinate: draftCoordinate)
                        .tint(AppTheme.coral)
                }
                .mapStyle(.standard(elevation: .realistic))
                .mapControls {
                    MapCompass()
                    MapScaleView()
                }
                .onMapCameraChange { context in
                    visibleRegion = context.region
                }
                .onTapGesture { point in
                    guard let chosen = proxy.convert(point, from: .local) else { return }
                    select(chosen)
                }
                .safeAreaInset(edge: .top) {
                    searchBar
                        .padding(.horizontal, 14)
                        .padding(.top, 8)
                }
                .safeAreaInset(edge: .bottom) {
                    selectionPanel
                }
            }
            .navigationTitle("Ort wählen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    private var searchBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
            TextField("Stadt, Region oder Adresse", text: $query)
                .textInputAutocapitalization(.words)
                .submitLabel(.search)
                .onSubmit { search() }
            if isSearching {
                ProgressView().controlSize(.small)
            } else if !query.isEmpty {
                Button { query = "" } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 48)
        .background(.ultraThickMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: .black.opacity(0.18), radius: 12, y: 5)
    }

    private var selectionPanel: some View {
        VStack(spacing: 12) {
            Capsule()
                .fill(Color.secondary.opacity(0.45))
                .frame(width: 38, height: 5)

            HStack(spacing: 12) {
                Image(systemName: "mappin.circle.fill")
                    .font(.title2)
                    .foregroundStyle(AppTheme.coral)
                VStack(alignment: .leading, spacing: 2) {
                    Text(draftName)
                        .font(.headline)
                        .lineLimit(1)
                    Text("Tippe auf die Karte, um den Punkt zu versetzen")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            Button {
                coordinate = draftCoordinate
                locationName = draftName
                dismiss()
            } label: {
                PrimaryButtonLabel(title: "Diesen Ort wählen", icon: "checkmark")
            }
        }
        .padding(16)
        .background(.ultraThickMaterial)
    }

    private func select(_ newCoordinate: CLLocationCoordinate2D) {
        draftCoordinate = newCoordinate
        draftName = "Ort wird bestimmt …"
        Task {
            draftName = await LocationService.placeName(for: newCoordinate)
        }
    }

    private func search() {
        guard !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        isSearching = true
        Task {
            defer { isSearching = false }
            let request = MKLocalSearch.Request()
            request.naturalLanguageQuery = query
            request.region = visibleRegion
            do {
                let response = try await MKLocalSearch(request: request).start()
                guard let item = response.mapItems.first else { return }
                let foundCoordinate = item.placemark.coordinate
                draftCoordinate = foundCoordinate
                draftName = item.name ?? item.placemark.locality ?? query
                withAnimation(.easeInOut) {
                    camera = .region(MKCoordinateRegion(center: foundCoordinate, span: MKCoordinateSpan(latitudeDelta: 0.5, longitudeDelta: 0.5)))
                }
            } catch {
                draftName = "Kein Ort gefunden"
            }
        }
    }
}
