import Foundation

struct FIFO<Element> {
    private var storage: [Element?] = []
    private var head = 0
    mutating func append(_ value: Element) { storage.append(value) }
    mutating func popFirst() -> Element? {
        guard head < storage.count else { return nil }
        defer { storage[head] = nil; head += 1 }
        return storage[head]
    }
}

@main
enum QueueLifecycleBenchmark {
    static func main() {
        var queue = FIFO<Int>()
        let clock = ContinuousClock()
        let elapsed = clock.measure {
            for value in 0..<100_000 { queue.append(value) }
            for _ in 0..<100_000 { _ = queue.popFirst() }
        }
        print("queue_operations=200000 duration=\(elapsed)")
    }
}
