Get-CimInstance Win32_Process -Filter "Name='node.exe'" | ForEach-Object {
  $cl = $_.CommandLine
  if ($cl -and $cl -match 'd2-crossqc') {
    Write-Output ("MATCH PID=" + $_.ProcessId + " : " + $cl.Substring(0, [Math]::Min(160, $cl.Length)))
  }
}
