$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$toolchain = Join-Path $repo '.tools/android-toolchain'
if (-not $env:JAVA_HOME -and (Test-Path "$toolchain/jdk")) {
    $env:JAVA_HOME = (Get-ChildItem "$toolchain/jdk" -Directory | Select-Object -First 1).FullName
}
if (-not $env:ANDROID_HOME -and (Test-Path "$toolchain/sdk")) {
    $env:ANDROID_HOME = "$toolchain/sdk"
}
$env:GRADLE_USER_HOME = Join-Path $repo '.tools/gradle-home'
$signingKey = Join-Path $env:USERPROFILE '.ssh/hector-android-release.jks'
$signingPassword = Join-Path $env:USERPROFILE '.ssh/hector-android-signing-password.txt'
if (-not (Test-Path $signingKey) -or -not (Test-Path $signingPassword)) {
    throw 'Restore the Hector Android signing key and password before building an update.'
}
$gradle = "$toolchain/gradle/gradle-8.11.1/bin/gradle.bat"
if (-not (Test-Path $gradle)) { $gradle = Join-Path $PSScriptRoot 'gradlew.bat' }
& $gradle -p $PSScriptRoot assembleRelease testDebugUnitTest lintDebug --console plain
if ($LASTEXITCODE -ne 0) { throw 'Android build or checks failed.' }
$output = Join-Path $repo 'dist/Hector-Android.apk'
New-Item -ItemType Directory -Force (Split-Path $output -Parent) | Out-Null
try {
    $env:HECTOR_ANDROID_PASS = (Get-Content -LiteralPath $signingPassword -Raw).Trim()
    & "$env:ANDROID_HOME/build-tools/35.0.0/apksigner.bat" sign --ks $signingKey --ks-key-alias hector --ks-pass env:HECTOR_ANDROID_PASS --key-pass env:HECTOR_ANDROID_PASS --out $output "$PSScriptRoot/app/build/outputs/apk/release/app-release-unsigned.apk"
    if ($LASTEXITCODE -ne 0) { throw 'APK signing failed.' }
} finally {
    Remove-Item Env:HECTOR_ANDROID_PASS -ErrorAction SilentlyContinue
}
& "$env:ANDROID_HOME/build-tools/35.0.0/apksigner.bat" verify $output
if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
Write-Output "Created: $output"
