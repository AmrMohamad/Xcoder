import XCTest
@testable import XcodeMCPServer

final class RequestBudgetTests: XCTestCase {
    func testWorkDeadlineReservesResponseTime() {
        let clock = ContinuousClock()
        let receivedAt = clock.now
        let budget = RequestBudget(
            receivedAt: receivedAt,
            timeout: .seconds(50),
            responseReserve: .seconds(2)
        )

        XCTAssertEqual(receivedAt.duration(to: budget.deadline).secondsDouble, 50, accuracy: 0.000_001)
        XCTAssertEqual(receivedAt.duration(to: budget.workDeadline()).secondsDouble, 48, accuracy: 0.000_001)
        XCTAssertTrue(budget.hasWorkTimeRemaining(clock: clock))
    }

    func testExpiredBudgetHasNoRemainingDuration() async throws {
        let clock = ContinuousClock()
        let budget = RequestBudget(
            receivedAt: clock.now,
            timeout: .milliseconds(10),
            responseReserve: .milliseconds(1)
        )
        try await clock.sleep(for: .milliseconds(20))

        XCTAssertEqual(budget.remaining(clock: clock), .zero)
        XCTAssertFalse(budget.hasWorkTimeRemaining(clock: clock))
    }
}
