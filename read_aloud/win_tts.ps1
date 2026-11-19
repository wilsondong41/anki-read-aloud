# Read Aloud add-on: Windows voices.
#
#   win_tts.ps1 -List                         one line per installed voice:
#                                             kind<TAB>name<TAB>language<TAB>gender
#   win_tts.ps1 -Kind sapi -Voice "Microsoft Zira Desktop" -Out x.wav
#   win_tts.ps1 -Kind onecore -Voice "Microsoft Libby" -Out x.wav
#
# The text to say comes from the RA_TEXT environment variable (no quoting
# problems). "sapi" voices are the classic desktop ones (System.Speech);
# "onecore" voices are the ones added in Settings > Time & language > Speech.

param(
    [switch]$List,
    [string]$Kind = "sapi",
    [string]$Voice = "",
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"

function Get-OneCore {
    $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
    return [Windows.Media.SpeechSynthesis.SpeechSynthesizer]
}

if ($List) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    try {
        Add-Type -AssemblyName System.Speech
        $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
        foreach ($v in $s.GetInstalledVoices()) {
            if ($v.Enabled) {
                $i = $v.VoiceInfo
                "sapi`t$($i.Name)`t$($i.Culture.Name)`t$($i.Gender)"
            }
        }
        $s.Dispose()
    } catch {}
    try {
        $type = Get-OneCore
        foreach ($v in $type::AllVoices) {
            "onecore`t$($v.DisplayName)`t$($v.Language)`t$($v.Gender)"
        }
    } catch {}
    exit 0
}

$text = $env:RA_TEXT
if (-not $text -or -not $Out) { exit 2 }

if ($Kind -eq "onecore") {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $type = Get-OneCore
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
    $match = $type::AllVoices | Where-Object { $_.DisplayName -eq $Voice } | Select-Object -First 1
    # A voice that isn't installed (yet) fails, so its audio isn't cached
    # under its name; the add-on then tries the default voice.
    if ($Voice -and -not $match) { exit 3 }
    if ($match) { $synth.Voice = $match }
    $op = $synth.SynthesizeTextToStreamAsync($text)
    $task = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($op))
    $stream = $task.Result
    $in = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
    $file = [System.IO.File]::Create($Out)
    try { $in.CopyTo($file) } finally { $file.Close(); $in.Close() }
} else {
    Add-Type -AssemblyName System.Speech
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    if ($Voice) { $s.SelectVoice($Voice) }
    $s.SetOutputToWaveFile($Out)
    $s.Speak($text)
    $s.Dispose()
}
exit 0
