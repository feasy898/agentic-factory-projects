$ErrorActionPreference = 'Stop'
function S([int[]]$c) { return -join ($c | ForEach-Object { [char]$_ }) }
$everyFriday  = S @(0x6BCF,0x5468,0x4E94)                      # mei zhou wu
$periodic     = S @(0x5468,0x671F,0x6027,0x6C47,0x62A5)        # zhou qi xing hui bao
$done         = S @(0x672C,0x5468,0x5B8C,0x6210)               # ben zhou wan cheng
$plan         = S @(0x4E0B,0x5468,0x8BA1,0x5212)               # xia zhou ji hua
$risk         = S @(0x98CE,0x9669,0x4E0E,0x6C42,0x52A9)        # feng xian yu qiu zhu

$base = 'D:\workspace\zcode' + [char]0x7814 + [char]0x7A76
$path = Join-Path $base 'skillfactory\assets\paper-to-skill\tests\ab\ab-002-weekly-report\baseline\SKILL.md'
$t = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
if ($t -match '(?s)^---\r?\n(.*?)\r?\n---') {
  $fm = $Matches[1]
  $name = [regex]::Match($fm, '(?m)^name:\s*(.+?)\s*$').Groups[1].Value
  $desc = [regex]::Match($fm, '(?ms)^description:\s*(.+)$').Groups[1].Value.Trim()
  Write-Output ("name=[" + $name + "] len=" + $name.Length)
  Write-Output ("name_matches_agentskills_pattern=" + (($name -cmatch '^[a-z0-9]+(-[a-z0-9]+)*$') -and ($name.Length -le 64)))
  Write-Output ("desc_len_chars=" + $desc.Length)
  Write-Output ("desc_le_1024=" + ($desc.Length -le 1024))
  Write-Output ("desc_has_friday_trigger=" + ($desc.Contains($everyFriday)))
  Write-Output ("desc_has_periodic_trigger=" + ($desc.Contains($periodic)))
  Write-Output ("desc_has_three_sections=" + (($desc.Contains($done)) -and ($desc.Contains($plan)) -and ($desc.Contains($risk))))
} else {
  Write-Output 'NO_FRONTMATTER'
}
