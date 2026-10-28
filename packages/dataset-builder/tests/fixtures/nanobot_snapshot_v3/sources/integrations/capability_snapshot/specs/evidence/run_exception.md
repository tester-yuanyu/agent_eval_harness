---
snapshot_id: evidence.run_exception
description: Caller-owned observation of a native raised Python exception or cancellation;
  exporter does not implement capture.
consumer_roles:
- builder
- evaluator
required: false
applicable_result_paths:
- raised_exception
- cancelled
---

# Exceptional exit

A proposed evaluator capture envelope, not an emitted Nanobot payload. Availability
remains unknown until an evaluator implements the observer. Catch cancellation
separately; do not swallow BaseException indiscriminately.
