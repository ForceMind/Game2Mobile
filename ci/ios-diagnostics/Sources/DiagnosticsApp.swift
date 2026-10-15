// Standalone platform smoke target. Neither game runtime nor game assets are linked.
import Foundation
import Metal
import SwiftUI
import UIKit

@main
struct Game2MobileDiagnosticsApp: App {
    var body: some Scene {
        WindowGroup {
            DiagnosticsScreen()
        }
    }
}

private struct DiagnosticCheck: Identifiable {
    let id: String
    let title: String
    let detail: String
    let passed: Bool

    static func collect() -> [DiagnosticCheck] {
        let metal = MTLCreateSystemDefaultDevice()
        let bundle = Bundle.main.bundleIdentifier ?? "unknown"
        let storage = scratchStorageWorks()
        return [
            DiagnosticCheck(
                id: "runtime", title: "Apple runtime",
                detail: "\(UIDevice.current.model) · iOS \(UIDevice.current.systemVersion)",
                passed: true
            ),
            DiagnosticCheck(
                id: "metal", title: "Metal availability",
                detail: metal?.name ?? "No Metal device reported",
                passed: metal != nil
            ),
            DiagnosticCheck(
                id: "storage", title: "Temporary storage",
                detail: storage ? "Atomic write, read and cleanup passed" : "Write/read failed",
                passed: storage
            ),
            DiagnosticCheck(
                id: "bundle", title: "Diagnostic bundle identity",
                detail: bundle,
                passed: bundle == "com.game2mobile.diagnostics.smoke"
            )
        ]
    }

    private static func scratchStorageWorks() -> Bool {
        let file = FileManager.default.temporaryDirectory
            .appendingPathComponent("game2mobile-probe-\(UUID().uuidString)")
        let sample = Data("Game2Mobile diagnostic only".utf8)
        do {
            try sample.write(to: file, options: [.atomic])
            let fetched = try Data(contentsOf: file)
            try FileManager.default.removeItem(at: file)
            return fetched == sample
        } catch {
            try? FileManager.default.removeItem(at: file)
            return false
        }
    }
}

private struct DiagnosticsScreen: View {
    @State private var checks: [DiagnosticCheck] = []
    @State private var notice: String = ""

    private let background = Color(red: 12.0 / 255, green: 24.0 / 255, blue: 34.0 / 255)
    private let panel = Color(red: 23.0 / 255, green: 43.0 / 255, blue: 52.0 / 255)
    private let lime = Color(red: 182.0 / 255, green: 1, blue: 105.0 / 255)

    private var report: String {
        let outcomes = checks.map {
            "\($0.title): \($0.passed ? "PASS" : "CHECK") — \($0.detail)"
        }
        return (
            ["Game2Mobile Build Diagnostics",
             "Diagnostics only: game runtime and commercial game files are NOT included.",
             "Generated: \(ISO8601DateFormatter().string(from: Date()))",
             ""] + outcomes
        ).joined(separator: "\n")
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Game2Mobile")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                    .foregroundStyle(lime)
                    .accessibilityIdentifier("game2mobile.diagnostics.ready")

                Text("BUILD DIAGNOSTICS")
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .tracking(2.6)
                    .foregroundStyle(.white.opacity(0.78))

                VStack(alignment: .leading, spacing: 8) {
                    Text("Platform validation").font(.title2.bold())
                    Text("This is a non-playable build-system test application.")
                        .font(.subheadline)
                        .foregroundStyle(.white.opacity(0.8))
                    Text("No game, compatibility runtime or proprietary assets are included.")
                        .font(.footnote)
                        .foregroundStyle(.white.opacity(0.7))
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(panel, in: RoundedRectangle(cornerRadius: 20))

                VStack(alignment: .leading, spacing: 12) {
                    ForEach(checks) { check in
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: check.passed ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                                .foregroundStyle(check.passed ? lime : .orange)
                                .accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(check.title).font(.headline)
                                Text(check.detail)
                                    .font(.footnote)
                                    .foregroundStyle(.white.opacity(0.72))
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 5)
                    }
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(panel, in: RoundedRectangle(cornerRadius: 20))

                HStack(spacing: 12) {
                    Button("Run checks") {
                        checks = DiagnosticCheck.collect()
                        notice = "Checks refreshed"
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(lime)
                    .foregroundStyle(background)

                    Button("Copy report") {
                        UIPasteboard.general.string = report
                        notice = "Report copied"
                    }
                    .buttonStyle(.bordered)
                    .tint(lime)
                }

                if !notice.isEmpty {
                    Text(notice)
                        .font(.caption)
                        .foregroundStyle(lime)
                        .accessibilityIdentifier("game2mobile.diagnostics.notice")
                }
                Text("For developers only · Not a playable Game2Mobile release")
                    .font(.caption2)
                    .foregroundStyle(.white.opacity(0.56))
            }
            .foregroundStyle(.white)
            .frame(maxWidth: 640, alignment: .leading)
            .padding(24)
            .frame(maxWidth: .infinity)
        }
        .background(background.ignoresSafeArea())
        .task {
            checks = DiagnosticCheck.collect()
        }
    }
}
