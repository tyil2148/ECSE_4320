# Run manually from Windows PowerShell. No settings are changed.
# Keep this output with the Linux run metadata.
$ErrorActionPreference = 'Continue'
'WINDOWS CPU'
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
'WINDOWS MEMORY'
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
'WINDOWS OS'
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber
'WINDOWS POWER PLAN'
powercfg /getactivescheme
'WSL VERSION'
wsl --version
'WSL DISTRIBUTIONS'
wsl --list --verbose
'WSL CONFIGURATION'
$configPath = Join-Path $env:USERPROFILE '.wslconfig'
if (Test-Path $configPath) { Get-Content $configPath } else { 'No .wslconfig file; defaults apply.' }
