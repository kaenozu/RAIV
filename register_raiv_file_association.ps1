param()

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $PSCommandPath
$progId = 'RAIV.Image'
$extensions = @('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.zip', '.cbz', '.rar', '.cbr', '.7z', '.cb7')
$raivExe = Join-Path $scriptDir 'RAIV.exe'
if (Test-Path $raivExe) {
    $openCommand = '"{0}" "{1}"' -f $raivExe, '%1'
} else {
    $vbsPath = Join-Path $scriptDir 'run_raiv.vbs'
    $openCommand = 'wscript.exe "{0}" "{1}"' -f $vbsPath, '%1'
}

function Invoke-RegAdd {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [switch] $Default,
        [string] $Name,
        [Parameter(Mandatory)] [ValidateSet('REG_SZ', 'REG_NONE')] [string] $Type,
        [string] $Data = ''
    )

    $arguments = @('add', $Path)
    if ($Default) {
        $arguments += '/ve'
    } elseif ($Name) {
        $arguments += @('/v', $Name)
    }
    $arguments += @('/t', $Type, '/d', $Data, '/f')
    & reg.exe @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "reg.exe failed for $Path"
    }
}

Write-Host 'Registering RAIV file association for current user...'
Write-Host ''

Invoke-RegAdd -Path "HKCU\Software\Classes\$progId" -Default -Type REG_SZ -Data 'RAIV Image Viewer'
Invoke-RegAdd -Path "HKCU\Software\Classes\$progId\shell\open\command" -Default -Type REG_SZ -Data $openCommand

foreach ($extension in $extensions) {
    Invoke-RegAdd -Path "HKCU\Software\Classes\$extension\OpenWithProgids" -Name $progId -Type REG_NONE
    Invoke-RegAdd -Path "HKCU\Software\Classes\$extension" -Default -Type REG_SZ -Data $progId
}

Write-Host 'Done.'
Write-Host "RAIV has been registered for: $($extensions -join ' ')"
Write-Host ''
Write-Host 'NOTE:'
Write-Host '- On modern Windows, the final default-app decision may still require one-time confirmation in Settings.'
Write-Host '- Opening Default apps now...'
try {
    Start-Process 'ms-settings:defaultapps'
} catch {
    Write-Host 'Could not open Settings automatically. Please open Default apps manually.'
}
Write-Host ''
Write-Host 'In Settings, choose default apps by file type and set RAIV for the extensions you want.'