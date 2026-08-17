import SwiftUI

struct TimePickerSheet: View {
    @Binding var instant: TravelInstant
    @Environment(\.dismiss) private var dismiss

    @State private var precision: TimePrecision
    @State private var yearText: String
    @State private var eraIsBCE: Bool
    @State private var month: Int
    @State private var day: Int

    init(instant: Binding<TravelInstant>) {
        _instant = instant
        let value = instant.wrappedValue
        _precision = State(initialValue: value.precision)
        _yearText = State(initialValue: String(abs(value.year)))
        _eraIsBCE = State(initialValue: value.year < 0)
        _month = State(initialValue: value.month)
        _day = State(initialValue: value.day)
    }

    private var parsedYear: Int? {
        guard let value = Int(yearText.filter(\.isNumber)), value > 0, value <= 4_540_000_000 else { return nil }
        return eraIsBCE ? -value : value
    }

    var body: some View {
        NavigationStack {
            ZStack {
                CosmicBackground()
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        Text("Wie genau kennst du den Moment?")
                            .font(.title2.bold())

                        Picker("Genauigkeit", selection: $precision) {
                            ForEach(TimePrecision.allCases) { value in
                                Text(value.rawValue).tag(value)
                            }
                        }
                        .pickerStyle(.segmented)

                        GlassCard {
                            VStack(alignment: .leading, spacing: 16) {
                                Text("Jahreszahl")
                                    .font(.caption.weight(.bold))
                                    .foregroundStyle(AppTheme.textSecondary)

                                TextField("z. B. 1989", text: $yearText)
                                    .font(.system(size: 32, weight: .bold, design: .rounded))
                                    .keyboardType(.numberPad)
                                    .padding(14)
                                    .background(AppTheme.raised, in: RoundedRectangle(cornerRadius: 14))

                                Picker("Ära", selection: $eraIsBCE) {
                                    Text("n. Chr.").tag(false)
                                    Text("v. Chr.").tag(true)
                                }
                                .pickerStyle(.segmented)

                                if precision != .year {
                                    Divider().overlay(Color.white.opacity(0.12))
                                    Picker("Monat", selection: $month) {
                                        ForEach(1...12, id: \.self) { value in
                                            Text(Calendar.current.monthSymbols[value - 1]).tag(value)
                                        }
                                    }
                                }

                                if precision == .day {
                                    Picker("Tag", selection: $day) {
                                        ForEach(1...daysInSelectedMonth, id: \.self) { value in
                                            Text(String(value)).tag(value)
                                        }
                                    }
                                }
                            }
                        }

                        if let parsedYear {
                            Label(previewText(for: parsedYear), systemImage: "clock.arrow.circlepath")
                                .font(.headline)
                                .foregroundStyle(AppTheme.gold)
                                .frame(maxWidth: .infinity, alignment: .center)
                        } else {
                            Label("Bitte eine Jahreszahl von 1 bis 4,54 Milliarden eingeben", systemImage: "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundStyle(AppTheme.coral)
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Zeitpunkt")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Übernehmen") { save() }
                        .fontWeight(.semibold)
                        .disabled(parsedYear == nil)
                }
            }
        }
        .preferredColorScheme(.dark)
        .presentationDetents([.large])
    }

    private var daysInSelectedMonth: Int {
        guard !eraIsBCE, let selectedYear = parsedYear, selectedYear > 0,
              let date = Calendar.current.date(from: DateComponents(year: min(selectedYear, 9999), month: month)),
              let range = Calendar.current.range(of: .day, in: .month, for: date) else {
            return month == 2 ? 28 : ([4, 6, 9, 11].contains(month) ? 30 : 31)
        }
        return range.count
    }

    private func previewText(for year: Int) -> String {
        TravelInstant(year: year, month: month, day: min(day, daysInSelectedMonth), precision: precision).displayText
    }

    private func save() {
        guard let parsedYear else { return }
        instant = TravelInstant(year: parsedYear, month: month, day: min(day, daysInSelectedMonth), precision: precision)
        dismiss()
    }
}
