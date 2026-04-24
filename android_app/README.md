# BIST Bot Android WebView prototype

This folder contains a minimal Android Studio project that loads local HTML assets in a WebView.

## Included

- `dashboard.html`
- `analysis.html`
- `signals.html`
- `settings.html`
- `MainActivity.kt` with JavaScript and DOM storage enabled
- bottom navigation wired with `file:///android_asset/...` links
- `INTERNET` permission for Tailwind CDN, Google Fonts, and remote images
- API URL injected through `BIST_BOT_API_BASE_URL` Gradle property or environment variable

## Open in Android Studio

1. Open `android_app` as a project.
2. Let Gradle sync.
3. Run the `app` module on an emulator or device.

## API configuration

Set the API endpoint at build time instead of editing Kotlin source:

```powershell
$env:BIST_BOT_API_BASE_URL="https://your-api.example.com"
.\gradlew.bat :app:assembleDebug
```

If the value is omitted, the prototype skips live API calls and renders bundled demo data.

## Replace demo assets with your real screens

Copy your production-ready HTML files into `app/src/main/assets/` and keep the same filenames, or update the links in the asset files.

## Next integration step

For real API connectivity, prefer native networking with Retrofit/OkHttp and use the WebView prototype only to validate UI and navigation.
