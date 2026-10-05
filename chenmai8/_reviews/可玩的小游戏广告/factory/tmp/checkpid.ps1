foreach ($p in 7632, 34172) {
  $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
  if ($proc) { "PID=$p Name=$($proc.Name) Path=$($proc.Path)" } else { "PID=$p not found" }
}
