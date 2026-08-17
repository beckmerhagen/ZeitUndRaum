import SwiftUI
import WebKit

struct HistoricalMapSheet: View {
    let request: JourneyRequest
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationStack {
            Group {
                if let url = HistoricalMapLink.url(for: request) {
                    ZStack(alignment: .bottom) {
                        HistoricalMapWebView(url: url)
                        Text("Kartendaten: OpenHistoricalMap-Mitwirkende · überwiegend CC0, Ausnahmen je Objekt")
                            .font(.caption2)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .background(.ultraThickMaterial, in: Capsule())
                            .padding(10)
                    }
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button { openURL(url) } label: {
                                Image(systemName: "safari")
                            }
                            .accessibilityLabel("In Safari öffnen")
                        }
                    }
                } else {
                    ContentUnavailableView(
                        "Für diese Zeit nicht verfügbar",
                        systemImage: "map.fill",
                        description: Text("OpenHistoricalMap kann in dieser Ansicht nur Jahreszahlen der gemeinsamen Zeitrechnung darstellen.")
                    )
                }
            }
            .navigationTitle("Historische Karte")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Schließen") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}

private struct HistoricalMapWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.allowsBackForwardNavigationGestures = true
        webView.isOpaque = false
        webView.backgroundColor = UIColor(AppTheme.ink)
        webView.scrollView.backgroundColor = UIColor(AppTheme.ink)
        webView.load(URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard webView.url != url else { return }
        webView.load(URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad))
    }
}
