# Checkout service: two commits

8 runs of 2 commits · 20 tests · 1 failing · 3 flaky · 2 always skipped

Per run, one character for each run in order: `.` passed, `F` failed, `E` error, `s` skipped, `r` passed after the test tool retried it, `-` not in that run.

## Failing in every run (1)

| Test | Commit | Per run | Failure signatures |
|---|---|---|---|
| `tests.test_payment::test_refund_partial` | `3f9a1c2` | `FFFF` | `ac1458b2` |

## Flaky: passed and failed on the same code (3)

| Test | Commit | Per run | Failed | Retried in-run | Failure signatures |
|---|---|---|---:|---:|---|
| `tests.test_orders::test_concurrent_checkout` | `3f9a1c2` | `E.EE` | 75 % | – | `fbc297b2` |
| `tests.test_payment::test_charge_retries` | `3f9a1c2` | `.F.F` | 50 % | – | `69540622` |
| `tests.test_cart::test_price_rounding` | `7be04d1` | `FF.F` | 75 % | – | `01b48e1d` |

## Failure signatures (4)

| Id | Failures | Tests | Runs | Normalised message |
|---|---:|---:|---:|---|
| `ac1458b2` | 4 | 1 | 4 | `AssertionError: assert N == N` |
| `01b48e1d` | 3 | 1 | 3 | `AssertionError: N != N` |
| `fbc297b2` | 3 | 1 | 3 | `sqlite3.OperationalError: database is locked` |
| `69540622` | 2 | 1 | 2 | `TimeoutError: payment gateway did not answer within N s (request <hex>)` |

## Slowest tests (median seconds, top 10)

| Test | Commit | Seconds |
|---|---|---:|
| `tests.test_orders::test_slow_report` | `7be04d1` | 10.050 |
| `tests.test_orders::test_slow_report` | `3f9a1c2` | 4.225 |
| `tests.test_payment::test_charge_retries` | `3f9a1c2` | 2.712 |
| `tests.test_search::test_index_rebuild` | `3f9a1c2` | 1.200 |
| `tests.test_search::test_index_rebuild` | `7be04d1` | 1.200 |
| `tests.test_orders::test_concurrent_checkout` | `3f9a1c2` | 0.900 |
| `tests.test_orders::test_concurrent_checkout` | `7be04d1` | 0.900 |
| `tests.test_payment::test_charge_retries` | `7be04d1` | 0.410 |
| `tests.test_search::test_query_ranking` | `7be04d1` | 0.300 |
| `tests.test_payment::test_refund_partial` | `3f9a1c2` | 0.021 |

## Not in every run (1)

| Test | Missing from |
|---|---:|
| `tests.test_search::test_index_rebuild` | 2 of 4 |

_2 tests were skipped in every run._
