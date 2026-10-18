# Checkout service: 4 runs of one commit

4 runs of 1 commit · 9 tests · 1 failing · 2 flaky · 1 always skipped

Per run, one character for each run in order: `.` passed, `F` failed, `E` error, `s` skipped, `r` passed after the test tool retried it, `-` not in that run.

## Failing in every run (1)

| Test | Per run | Failure signatures |
|---|---|---|
| `tests.test_payment::test_refund_partial` | `FFFF` | `ac1458b2` |

## Flaky: passed and failed on the same code (2)

| Test | Per run | Failed | Retried in-run | Failure signatures |
|---|---|---:|---:|---|
| `tests.test_orders::test_concurrent_checkout` | `E.EE` | 75 % | – | `fbc297b2` |
| `tests.test_payment::test_charge_retries` | `.F.F` | 50 % | – | `69540622` |

## Failure signatures (3)

| Id | Failures | Tests | Runs | Normalised message |
|---|---:|---:|---:|---|
| `ac1458b2` | 4 | 1 | 4 | `AssertionError: assert N == N` |
| `fbc297b2` | 3 | 1 | 3 | `sqlite3.OperationalError: database is locked` |
| `69540622` | 2 | 1 | 2 | `TimeoutError: payment gateway did not answer within N s (request <hex>)` |

## Slowest tests (median seconds, top 9)

| Test | Seconds |
|---|---:|
| `tests.test_orders::test_slow_report` | 4.225 |
| `tests.test_payment::test_charge_retries` | 2.712 |
| `tests.test_search::test_index_rebuild` | 1.200 |
| `tests.test_orders::test_concurrent_checkout` | 0.900 |
| `tests.test_payment::test_refund_partial` | 0.021 |
| `tests.test_cart::test_total_with_discount` | 0.006 |
| `tests.test_cart::test_add_item` | 0.004 |
| `tests.test_cart::test_remove_item` | 0.003 |
| `tests.test_shipping::test_label_printing` | 0.000 |

## Not in every run (1)

| Test | Missing from |
|---|---:|
| `tests.test_search::test_index_rebuild` | 2 of 4 |

_1 test was skipped in every run._
