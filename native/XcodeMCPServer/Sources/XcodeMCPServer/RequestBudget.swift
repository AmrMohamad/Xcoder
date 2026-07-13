import Foundation

enum RequestTimeoutStage: String, Sendable {
    case argumentValidation = "argument_validation"
    case queue
    case processLaunch = "process_launch"
    case execution
    case outputDrain = "output_drain"
    case responseEncoding = "response_encoding"
}

struct RequestBudget: Sendable {
    let receivedAt: ContinuousClock.Instant
    let deadline: ContinuousClock.Instant
    let responseReserve: Duration

    init(
        receivedAt: ContinuousClock.Instant,
        timeout: Duration,
        responseReserve: Duration = .seconds(2)
    ) {
        self.receivedAt = receivedAt
        self.deadline = receivedAt.advanced(by: timeout)
        self.responseReserve = responseReserve
    }

    func remaining(clock: ContinuousClock = .init()) -> Duration {
        max(.zero, clock.now.duration(to: deadline))
    }

    func workDeadline() -> ContinuousClock.Instant {
        deadline.advanced(by: .zero - responseReserve)
    }

    func hasWorkTimeRemaining(clock: ContinuousClock = .init()) -> Bool {
        clock.now < workDeadline()
    }
}

extension Duration {
    var secondsDouble: Double {
        let parts = components
        return Double(parts.seconds) + Double(parts.attoseconds) / 1_000_000_000_000_000_000
    }
}
