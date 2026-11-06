# Crea la tarea de Windows que recoge los datos del clan cada dia a las 11:01.
# Si el PC estaba apagado a esa hora, se lanza en cuanto se encienda.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$action = New-ScheduledTaskAction -Execute (Join-Path $dir '..\.venv\Scripts\pythonw.exe') -Argument 'clan_sync.py' -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 11:01
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'CoC Asistente - Clan diario' -Action $action -Trigger $trigger -Settings $settings -Description 'Guarda guerras, ligas y estado de los miembros del clan' -Force | Out-Null
Write-Output 'Tarea creada: cada dia a las 11:01'
