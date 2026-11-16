-- Script wrk : à la fin du test, imprime une ligne "WRKCSV" lisible par run_benchmarks.py.
-- (wrk --latency ne donne que p50/p75/p90/p99 ; ce script ajoute le p95.)
-- Les latences de wrk sont en microsecondes, la durée aussi.
done = function(summary, latency, requests)
  local e = summary.errors
  io.write(string.format(
    "WRKCSV requests=%d duration_us=%d bytes=%d " ..
    "err_connect=%d err_read=%d err_write=%d err_status=%d err_timeout=%d " ..
    "lat_min_us=%d lat_max_us=%d lat_mean_us=%.1f lat_stdev_us=%.1f " ..
    "p50_us=%d p90_us=%d p95_us=%d p99_us=%d\n",
    summary.requests, summary.duration, summary.bytes,
    e.connect, e.read, e.write, e.status, e.timeout,
    latency.min, latency.max, latency.mean, latency.stdev,
    latency:percentile(50), latency:percentile(90), latency:percentile(95), latency:percentile(99)))
end
