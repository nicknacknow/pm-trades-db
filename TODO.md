# TODO

- Add `--date` and `--duration` CLI params to `backup.sh` so it can run
  retroactively / catch up after missed days (defaults: today, 1 day).
- Swap Redis pub/sub for a persistent queue (LIST or stream) so backpressure
  during `VACUUM FULL` doesn't lose messages.
- Implement retention cleanup in `backup.sh` or a separate cron job
  (suggested: keep daily increments for 30 days).
