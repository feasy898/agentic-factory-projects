Get-Process | Sort-Object -Property CPU -Descending | Select-Object -First 12 | ForEach-Object {
  "{0,-30} PID={1,-8} CPU_s={2,-10} Mem_MB={3}" -f $_.Name, $_.Id, [math]::Round($_.CPU,0), [math]::Round($_.WorkingSet64/1MB,0)
}
