import CoreLocation
import SwiftUI

@main
struct ZeitUndRaumApp: App {
    var body: some Scene {
        WindowGroup {
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--demo-krempe-dossier") {
                KrempeDossierDemo()
                    .preferredColorScheme(.dark)
            } else if ProcessInfo.processInfo.arguments.contains("--demo-topic") {
                TopicExplorerView(
                    originCoordinate: CLLocationCoordinate2D(latitude: 53.5511, longitude: 9.9937),
                    originName: "Hamburg",
                    initialQuery: "Alter Elbtunnel"
                )
                .preferredColorScheme(.dark)
            } else {
                RootView().preferredColorScheme(.dark)
            }
            #else
            RootView().preferredColorScheme(.dark)
            #endif
        }
    }
}

#if DEBUG
private struct KrempeDossierDemo: View {
    @StateObject private var model = PlaceResearchModel()
    private let coordinate = CLLocationCoordinate2D(latitude: 53.8365, longitude: 9.4896)

    var body: some View {
        PlaceDossierView(
            model: model,
            request: JourneyRequest(instant: TravelInstant(year: 1628), coordinate: coordinate, locationName: "Krempe"),
            timeFocus: .decade,
            radiusKilometers: 25,
            onChooseYear: { _ in },
            onChoosePlace: { _ in }
        )
        .task { await model.load(placeName: "Krempe", coordinate: coordinate) }
    }
}
#endif
