import Foundation

@main
enum HealthRedactionBenchmark {
    static func main() {
        let samples = (0..<10_000).map { ["distribution", "upload-archive", "--api-key-id", "SECRET-\($0)", "--api-key-path=/Users/private/AuthKey.p8"] }
        let clock = ContinuousClock()
        let elapsed = clock.measure {
            for arguments in samples {
                _ = arguments.compactMap { argument in
                    argument.hasPrefix("--") ? String(argument.split(separator: "=", maxSplits: 1)[0]) : nil
                }
            }
        }
        print("health_argument_shape_iterations=\(samples.count) duration=\(elapsed)")
    }
}
