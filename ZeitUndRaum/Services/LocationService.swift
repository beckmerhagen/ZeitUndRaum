import CoreLocation
import Foundation

@MainActor
final class LocationService: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published private(set) var authorizationStatus: CLAuthorizationStatus
    @Published private(set) var currentCoordinate: CLLocationCoordinate2D?
    @Published private(set) var currentPlaceName: String?
    @Published private(set) var errorMessage: String?

    private let manager = CLLocationManager()

    override init() {
        authorizationStatus = manager.authorizationStatus
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
    }

    func requestCurrentLocation() {
        errorMessage = nil
        switch manager.authorizationStatus {
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        case .authorizedAlways, .authorizedWhenInUse:
            manager.requestLocation()
        case .denied, .restricted:
            errorMessage = "Der Standortzugriff ist deaktiviert. Du kannst weiterhin einen Ort auf der Karte wählen."
        @unknown default:
            errorMessage = "Der Standort ist gerade nicht verfügbar."
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            authorizationStatus = manager.authorizationStatus
            if manager.authorizationStatus == .authorizedWhenInUse || manager.authorizationStatus == .authorizedAlways {
                manager.requestLocation()
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        Task { @MainActor in
            currentCoordinate = location.coordinate
            currentPlaceName = await Self.placeName(for: location.coordinate)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            errorMessage = "Dein Standort konnte nicht bestimmt werden."
        }
    }

    static func placeName(for coordinate: CLLocationCoordinate2D) async -> String {
        let location = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
        do {
            let places = try await CLGeocoder().reverseGeocodeLocation(location)
            guard let place = places.first else { return "Gewählter Ort" }
            if let locality = place.locality {
                return locality
            }
            return place.name ?? place.country ?? "Gewählter Ort"
        } catch {
            return "\(coordinate.latitude.formatted(.number.precision(.fractionLength(2)))), \(coordinate.longitude.formatted(.number.precision(.fractionLength(2))))"
        }
    }
}
