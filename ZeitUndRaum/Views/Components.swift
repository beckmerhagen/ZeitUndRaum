import SwiftUI

enum AppTheme {
    static let ink = Color(red: 0.035, green: 0.055, blue: 0.11)
    static let panel = Color(red: 0.075, green: 0.105, blue: 0.17)
    static let raised = Color(red: 0.105, green: 0.14, blue: 0.21)
    static let mint = Color(red: 0.18, green: 0.82, blue: 0.74)
    static let gold = Color(red: 0.94, green: 0.71, blue: 0.31)
    static let coral = Color(red: 0.93, green: 0.39, blue: 0.37)
    static let textSecondary = Color.white.opacity(0.66)
}

struct CosmicBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [AppTheme.ink, Color(red: 0.06, green: 0.08, blue: 0.16), AppTheme.ink],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            GeometryReader { proxy in
                Circle()
                    .fill(AppTheme.mint.opacity(0.10))
                    .frame(width: 260, height: 260)
                    .blur(radius: 70)
                    .offset(x: proxy.size.width * 0.55, y: 90)
                Circle()
                    .fill(AppTheme.coral.opacity(0.08))
                    .frame(width: 220, height: 220)
                    .blur(radius: 70)
                    .offset(x: -100, y: proxy.size.height * 0.55)
            }
        }
        .ignoresSafeArea()
    }
}

struct SectionLabel: View {
    let number: String
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number)
                .font(.caption.weight(.bold).monospacedDigit())
                .foregroundStyle(AppTheme.ink)
                .frame(width: 28, height: 28)
                .background(AppTheme.mint, in: Circle())

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.title3.weight(.bold))
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.textSecondary)
            }
        }
    }
}

struct GlassCard<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(AppTheme.panel.opacity(0.92))
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
    }
}

struct PrimaryButtonLabel: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 10) {
            Text(title)
                .font(.headline)
            Image(systemName: icon)
                .font(.headline)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .foregroundStyle(AppTheme.ink)
        .background(
            LinearGradient(colors: [AppTheme.mint, Color(red: 0.38, green: 0.9, blue: 0.75)], startPoint: .leading, endPoint: .trailing),
            in: RoundedRectangle(cornerRadius: 18, style: .continuous)
        )
    }
}

struct EraPill: View {
    let title: String
    let isSelected: Bool

    var body: some View {
        Text(title)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 13)
            .padding(.vertical, 9)
            .foregroundStyle(isSelected ? AppTheme.ink : Color.white.opacity(0.8))
            .background(isSelected ? AppTheme.gold : AppTheme.raised, in: Capsule())
    }
}

extension View {
    func cardShadow() -> some View {
        shadow(color: .black.opacity(0.22), radius: 18, y: 10)
    }
}
