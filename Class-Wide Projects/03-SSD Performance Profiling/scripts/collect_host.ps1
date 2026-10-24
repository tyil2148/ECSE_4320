# Run in Windows PowerShell, not inside a Linux shell.
# Read-only metadata collection. No disks are modified and no serial numbers are collected.
param([string]$OutputPath = "$PWD\host_metadata.json")
$ErrorActionPreference = "Stop"
$notes = @()
$physical = @()
$reliability = @()
try {
    $physical = @(Get-PhysicalDisk | Select-Object FriendlyName, @{Name="MediaType";Expression={$_.MediaType.ToString()}}, @{Name="BusType";Expression={$_.BusType.ToString()}}, Size, HealthStatus, OperationalStatus)
    foreach ($disk in Get-PhysicalDisk) {
        try {
            $c = $disk | Get-StorageReliabilityCounter
            $reliability += [PSCustomObject]@{Name=$disk.FriendlyName; Temperature=$c.Temperature; TemperatureMax=$c.TemperatureMax; Wear=$c.Wear; PowerOnHours=$c.PowerOnHours}
        } catch { $notes += "Reliability counters unavailable for $($disk.FriendlyName): $($_.Exception.Message)" }
    }
} catch { $notes += "Physical disk metadata unavailable: $($_.Exception.Message)" }
$metadata = [ordered]@{
    CapturedUtc = [DateTime]::UtcNow.ToString("o")
    Computer = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, TotalPhysicalMemory
    CPU = @(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed)
    OS = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber
    Drives = @(Get-CimInstance Win32_DiskDrive | Select-Object Model, FirmwareRevision, Size, InterfaceType, DeviceID)
    PhysicalDisks = $physical
    ReliabilityCounters = $reliability
    Volumes = @(Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter, FileSystemType, Size, SizeRemaining)
    ActivePowerScheme = (powercfg /getactivescheme | Out-String).Trim()
    WslVersion = (wsl.exe --version | Out-String).Trim()
    WslDistributions = (wsl.exe --list --verbose | Out-String).Trim()
    Notes = $notes
    MappingReminder = "Manually identify the Windows volume containing this WSL distribution's ext4.vhdx and its physical SSD. A guest SCSI disk name is not the physical SSD interface."
}
$metadata | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Output "Saved $OutputPath"
