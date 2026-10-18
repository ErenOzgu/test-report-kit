# Surefire: one run with a retry

1 run of 1 commit · 4 tests · 0 failing · 1 flaky · 0 always skipped

Per run, one character for each run in order: `.` passed, `F` failed, `E` error, `s` skipped, `r` passed after the test tool retried it, `-` not in that run.

## Failing in every run (0)

None.

## Flaky: passed and failed on the same code (1)

| Test | Per run | Failed | Retried in-run | Failure signatures |
|---|---|---:|---:|---|
| `com.example.OrderServiceTest::notifiesWarehouse` | `r` | 50 % | 1 | `ef1a8ae3` |

## Failure signatures (1)

| Id | Failures | Tests | Runs | Normalised message |
|---|---:|---:|---:|---|
| `ef1a8ae3` | 1 | 1 | 1 | `Connection refused: localhost:N` |

## Slowest tests (median seconds, top 4)

| Test | Seconds |
|---|---:|
| `com.example.OrderServiceTest::notifiesWarehouse` | 1.904 |
| `com.example.OrderServiceTest::createsOrder` | 0.120 |
| `com.example.OrderServiceTest::appliesVoucher` | 0.087 |
| `com.example.OrderServiceTest::cancelsOrder` | 0.054 |
