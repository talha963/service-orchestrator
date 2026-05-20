$ErrorActionPreference = 'Stop'
$scriptDir = $PSScriptRoot
$androidDir = "C:\AndroidEnv"

Write-Host "Creating directories..."
if (!(Test-Path $androidDir)) { New-Item -ItemType Directory -Path $androidDir | Out-Null }
if (!(Test-Path "$androidDir\jdk")) { New-Item -ItemType Directory -Path "$androidDir\jdk" | Out-Null }
if (!(Test-Path "$androidDir\cmdline-tools")) { New-Item -ItemType Directory -Path "$androidDir\cmdline-tools" | Out-Null }
if (!(Test-Path "$androidDir\cmdline-tools\latest")) { New-Item -ItemType Directory -Path "$androidDir\cmdline-tools\latest" | Out-Null }

$cmdlineToolsUrl = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"

Write-Host "Downloading Android Command Line Tools..."
if (!(Test-Path "$androidDir\cmdline-tools.zip")) {
    Invoke-WebRequest -Uri $cmdlineToolsUrl -OutFile "$androidDir\cmdline-tools.zip" -UseBasicParsing
}

Write-Host "Extracting JDK..."
if (!(Test-Path "$androidDir\jdk\bin\java.exe")) {
    if (Test-Path "$androidDir\jdk_temp") { Remove-Item -Path "$androidDir\jdk_temp" -Recurse -Force }
    New-Item -ItemType Directory -Path "$androidDir\jdk_temp" | Out-Null
    cmd.exe /c "tar -xf `"$androidDir\jdk.zip`" -C `"$androidDir\jdk_temp`""
    $jdkFolder = Get-ChildItem -Path "$androidDir\jdk_temp" | Select-Object -First 1
    Move-Item -Path "$($jdkFolder.FullName)\*" -Destination "$androidDir\jdk" -Force
    Remove-Item -Path "$androidDir\jdk_temp" -Recurse -Force
}

Write-Host "Extracting Command Line Tools..."
if (!(Test-Path "$androidDir\cmdline-tools\latest\bin\sdkmanager.bat")) {
    if (Test-Path "$androidDir\cmdline-tools_temp") { Remove-Item -Path "$androidDir\cmdline-tools_temp" -Recurse -Force }
    New-Item -ItemType Directory -Path "$androidDir\cmdline-tools_temp" | Out-Null
    cmd.exe /c "tar -xf `"$androidDir\cmdline-tools.zip`" -C `"$androidDir\cmdline-tools_temp`""
    Move-Item -Path "$androidDir\cmdline-tools_temp\cmdline-tools\*" -Destination "$androidDir\cmdline-tools\latest" -Force
    Remove-Item -Path "$androidDir\cmdline-tools_temp" -Recurse -Force
}

$env:JAVA_HOME = "$androidDir\jdk21"
$env:ANDROID_HOME = "$androidDir"
$env:PATH = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\cmdline-tools\latest\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"

Write-Host "Accepting licenses and installing SDKs..."
$yesParams = "y`n" * 10
$yesParams | sdkmanager.bat "platform-tools" "platforms;android-34" "build-tools;34.0.0"

Write-Host "Setting up Capacitor project..."
cd $scriptDir

# Create www folder and move assets
if (!(Test-Path "www")) {
    New-Item -ItemType Directory -Path "www" | Out-Null
}
Copy-Item "index.html" "www\" -Force
Copy-Item "styles.css" "www\" -Force
Copy-Item "app.js" "www\" -Force

if (!(Test-Path "package.json")) {
    cmd.exe /c "npm init -y"
}

# Add capacitor dependencies
cmd.exe /c "npm install @capacitor/core"
cmd.exe /c "npm install @capacitor/cli --save-dev"
cmd.exe /c "npm install @capacitor/android"

# Initialize capacitor
if (!(Test-Path "capacitor.config.json")) {
    cmd.exe /c "npx cap init app com.antigravity.orchestrator --web-dir www"
}

# Add android platform
if (!(Test-Path "android")) {
    cmd.exe /c "npx cap add android"
} else {
    cmd.exe /c "npx cap sync android"
}

Write-Host "Building APK..."
cd "$scriptDir\android"
if (Test-Path "app\build\outputs\apk\debug\app-debug.apk") {
    Remove-Item "app\build\outputs\apk\debug\app-debug.apk" -Force
}
cmd.exe /c "gradlew.bat assembleDebug"

if (Test-Path "app\build\outputs\apk\debug\app-debug.apk") {
    Copy-Item "app\build\outputs\apk\debug\app-debug.apk" "$scriptDir\ServiceOrchestrator.apk"
    Write-Host "SUCCESS: APK created at $scriptDir\ServiceOrchestrator.apk"
} else {
    Write-Host "FAILED: APK not found."
}
