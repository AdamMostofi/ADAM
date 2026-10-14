# ADAM Thread Safety Design

## Problem

The InferenceEngine uses a regular dict for beliefs, which is not thread-safe for concurrent writes. Race conditions can occur when multiple threads call add_fact(), retract(), or infer() simultaneously.

## Solution 1: RLock (Implemented)

Uses a reentrant lock around all mutating and reading operations.

```python
import threading

class InferenceEngine:
    def __init__(self):
        self.beliefs = {}
        self.lock = threading.RLock()

    def add_fact(self, fact):
        with self.lock:
            # safe to mutate

    def query(self, ...):
        with self.lock:
            # safe to read
```

**Why RLock:** Allows the same thread to acquire the lock multiple times. Needed because add_fact() calls _check_contradictions() which calls add_fact() again.

**Trade-offs:**
- Simple, minimal code change
- Readers block each other (even though reads don't mutate)
- GIL provides some protection for simple dict operations in CPython, but explicit locking is correct across all Python implementations

## Solution 2: Actor Model (Future Alternative)

All operations go through a single-threaded event loop. Other threads send messages to the loop.

```python
import queue
import threading

class InferenceEngine:
    def __init__(self):
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            msg = self._queue.get()
            if msg[0] == "add":
                self._add_fact(msg[1])
            elif msg[0] == "query":
                return self._query(msg[1])
            # ...

    def add_fact(self, fact):
        self._queue.put(("add", fact))

    def query(self, subject=None, predicate=None, object=None):
        self._queue.put(("query", (subject, predicate, object)))
        return self._queue.get()
```

**When to use:** If read performance becomes a bottleneck (many concurrent queries while writes are rare). Allows lock-free reads from the caller's perspective.

**Trade-offs:**
- More complex (message passing, result waiting)
- Query becomes synchronous across threads
- Overkill for current expected usage

## Recommendation

RLock is the right choice now. Upgrade to actor model only if profiling shows lock contention is a bottleneck.
