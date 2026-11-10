# Geplande werkronde zonder mens (besluit 2026-11-02): Taakplanner, elke dinsdag 09:00.
# Draait `claude -p "/werkronde gepland"` op account b, schrijft een log en stuurt Telegram
# alleen als de ronde iets voor Bart heeft (eindregel MELDEN: ja) of als de ronde mislukt.
# De regels voor de ronde zelf staan in .claude/commands/werkronde.md (modus gepland).
#
#   Inrichten:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\werkronde_gepland.ps1 -Registreer
#   Rooktest:   ... -Registreer -Test, dan Start-ScheduledTask AgentTrader-werkronde-rooktest
#               (alleen stap 1, stuurt altijd een Telegram-bericht; dezelfde omgeving als dinsdag)
#   Logs:       logs\werkronde\  (genegeerd door git via *.log)
#
# Alleen ASCII in dit bestand: Windows PowerShell 5.1 leest een bestand zonder BOM als ANSI.
param([switch]$Test, [switch]$Registreer)

$ErrorActionPreference = 'Continue'
$Repo = Split-Path -Parent $PSScriptRoot
$TaakNaam = 'AgentTrader-werkronde'
$MaxUren = 3.5   # de Taakplanner stopt na 4 uur; dit script meldt het zelf eerder

if ($Registreer) {
    # Zonder venster: conhost --headless geeft de keten (powershell, claude, bash, ssh) een
    # console zonder scherm. Met alleen -WindowStyle Hidden verscheen er toch een venster;
    # dat sluiten doodde ssh (exit 137) en claude (0xC000013A) - rooktest 02-11.
    $arg = '--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    if ($Test) { $arg = $arg + ' -Test'; $TaakNaam = $TaakNaam + '-rooktest' }
    $actie = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument $arg -WorkingDirectory $Repo
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At '09:00'
    $inst = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 4)
    $p = @{ TaskName = $TaakNaam; Action = $actie; Settings = $inst; Force = $true
            Description = 'Agent Trader: werkronde zonder mens (scripts\werkronde_gepland.ps1)' }
    if (-not $Test) { $p['Trigger'] = $trigger }   # rooktest-taak: alleen handmatig starten
    Register-ScheduledTask @p | Out-Null
    Get-ScheduledTask -TaskName $TaakNaam | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
    return
}

$modus = 'gepland'
if ($Test) { $modus = 'rooktest' }
$LogDir = Join-Path $Repo 'logs\werkronde'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stempel = Get-Date -Format 'yyyy-MM-dd_HHmm'
$Log = Join-Path $LogDir ($stempel + '_' + $modus + '.log')
$UitBestand = Join-Path $LogDir ($stempel + '_' + $modus + '.json.log')
$FoutBestand = Join-Path $LogDir ($stempel + '_' + $modus + '.stderr.log')
$LeegIn = Join-Path $LogDir 'leeg-stdin.log'
Set-Content -Path $LeegIn -Value $null

function Schrijf([string]$t) {
    Add-Content -Path $Log -Value ((Get-Date -Format 'HH:mm:ss') + ' ' + $t) -Encoding UTF8
}

function Stuur-Telegram([string]$tekst) {
    $waarden = @{}
    $envBestand = Join-Path $Repo '.env.adk'
    if (Test-Path $envBestand) {
        Get-Content $envBestand | ForEach-Object {
            if ($_ -match '^\s*(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)\s*=\s*(.+?)\s*$') {
                $waarden[$matches[1]] = $matches[2].Trim('"').Trim("'")
            }
        }
    }
    if (-not $waarden['TELEGRAM_BOT_TOKEN'] -or -not $waarden['TELEGRAM_CHAT_ID']) {
        Schrijf 'TELEGRAM: geen token/chat_id in .env.adk, bericht niet verstuurd'
        return
    }
    if ($tekst.Length -gt 3800) { $tekst = $tekst.Substring(0, 3800) + ' ...' }
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $json = ConvertTo-Json @{ chat_id = $waarden['TELEGRAM_CHAT_ID']; text = $tekst }
        $bytes = [Text.Encoding]::UTF8.GetBytes($json)
        $uri = 'https://api.telegram.org/bot' + $waarden['TELEGRAM_BOT_TOKEN'] + '/sendMessage'
        Invoke-RestMethod -Method Post -Uri $uri -Body $bytes -ContentType 'application/json; charset=utf-8' | Out-Null
        Schrijf 'TELEGRAM: verstuurd'
    } catch {
        Schrijf ('TELEGRAM: mislukt: ' + $_.Exception.Message)
    }
}

# Zelfde account als een interactieve sessie in deze map (zie de claude-functie in het
# PowerShell-profiel): account b, en geen API-key die de claude.ai-login zou overrulen.
$env:CLAUDE_CONFIG_DIR = Join-Path $env:USERPROFILE '.claude-b'
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $Repo

Schrijf ('START modus=' + $modus + ' repo=' + $Repo)
$pull = (& git -C $Repo pull --ff-only 2>&1 | Out-String).Trim()
Schrijf ('git pull: ' + $pull)

# Pc wakker houden zolang de ronde loopt: op 03-11 viel hij om 09:56 midden in de review in
# slaap. Geldt voor deze thread en vervalt vanzelf als dit script eindigt.
# 0x80000003 = ES_CONTINUOUS + ES_SYSTEM_REQUIRED + ES_DISPLAY_REQUIRED: deze pc heeft Modern
# Standby (S0), daar kan alleen ES_SYSTEM_REQUIRED tekort schieten zodra het scherm uitgaat.
Add-Type -Namespace AgentTrader -Name Slaap -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
if ([AgentTrader.Slaap]::SetThreadExecutionState([uint32]2147483651) -eq 0) { Schrijf 'WAKKER HOUDEN mislukt' }

$exe = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
$argumenten = '-p "/werkronde ' + $modus + '" --output-format stream-json --verbose --permission-mode auto --permission-prompts none'
Schrijf ('claude ' + $argumenten)
try {
    $p = Start-Process -FilePath $exe -ArgumentList $argumenten -WorkingDirectory $Repo -NoNewWindow `
        -RedirectStandardInput $LeegIn -RedirectStandardOutput $UitBestand -RedirectStandardError $FoutBestand -PassThru
    $null = $p.Handle   # nodig zodat ExitCode na afloop leesbaar is (PS 5.1)
    $klaar = $p.WaitForExit([int]($MaxUren * 3600 * 1000))
} catch {
    Schrijf ('START MISLUKT: ' + $_.Exception.Message)
    Stuur-Telegram ('Geplande werkronde kon niet starten: ' + $_.Exception.Message + "`nLog: " + $Log)
    exit 1
}

$datum = Get-Date -Format 'dd-MM'
if (-not $klaar) {
    try { $p.Kill() } catch {}
    Schrijf ('TIJD OP na ' + $MaxUren + ' uur, proces gestopt')
    Stuur-Telegram ('Geplande werkronde ' + $datum + ' liep langer dan ' + $MaxUren + ' uur en is gestopt. Mogelijk halverwege iets; start een sessie en zeg werkronde.' + "`nLog: " + $Log)
    exit 1
}

$code = $p.ExitCode
# stream-json: een JSON-regel per gebeurtenis (live te volgen); de laatste met type=result telt
$j = $null
if (Test-Path $UitBestand) {
    foreach ($regel in (Get-Content -Encoding UTF8 $UitBestand)) {
        if ($regel -notmatch '"type"\s*:\s*"result"') { continue }
        try { $j = $regel | ConvertFrom-Json } catch {}
    }
}
$sessie = ''
if ($j) {
    $sessie = [string]$j.session_id
    Schrijf ('exit=' + $code + ' is_error=' + $j.is_error + ' beurten=' + $j.num_turns + ' duur_min=' + [math]::Round($j.duration_ms / 60000, 1) + ' sessie=' + $sessie)
} else {
    Schrijf ('exit=' + $code + ' geen JSON-uitvoer')
}
$hervat = ''
if ($sessie) { $hervat = "`nVerder in een sessie: claude --resume " + $sessie }

if ($code -ne 0 -or -not $j -or $j.is_error) {
    $fout = ''
    if (Test-Path $FoutBestand) { $fout = (Get-Content -Raw -Encoding UTF8 $FoutBestand) }
    if ($fout) { $fout = $fout.Trim(); if ($fout.Length -gt 400) { $fout = $fout.Substring($fout.Length - 400) } }
    Schrijf ('MISLUKT: ' + $fout)
    Stuur-Telegram ('Geplande werkronde ' + $datum + ' mislukt (exit ' + $code + '). ' + $fout + "`nLog: " + $Log + $hervat)
    exit 1
}

$tekst = ([string]$j.result).Trim()
$m = [regex]::Match($tekst, '(?im)^[\s\*_]*MELDEN:\s*(ja|nee)[\s\*_]*$')
if (-not $m.Success) {
    Schrijf 'GEEN EINDREGEL (MELDEN: ja/nee ontbreekt)'
    Stuur-Telegram ('Werkronde ' + $datum + ' is klaar, maar zonder eindoordeel. Laatste tekst:' + "`n" + $tekst + $hervat)
    exit 0
}
$rest = $tekst.Substring($m.Index + $m.Length).Trim()
Schrijf ('MELDEN: ' + $m.Groups[1].Value.ToLower())
Schrijf ('EINDBERICHT: ' + $rest)

if ($Test) {
    Stuur-Telegram ('Rooktest geplande werkronde (dinsdag 09:00): ' + $rest)
} elseif ($m.Groups[1].Value.ToLower() -eq 'ja') {
    Stuur-Telegram ('Werkronde ' + $datum + ':' + "`n" + $rest + $hervat)
}
Schrijf 'KLAAR'
exit 0
