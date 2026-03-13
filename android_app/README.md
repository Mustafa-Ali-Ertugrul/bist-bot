# BIST Bot Android APK

## Kurulum

1. **Android Studio** indir ve kur
2. Bu klasörü Android Studio'da aç (File → Open → android_app)
3. Build → Build Bundle(s) / APK(s) → Build APK

## Alternatif (Terminal ile)

```bash
cd android_app
./gradlew assembleRelease
```

APK dosyası: `app/build/outputs/apk/release/app-release.apk`

## Not

- Uygulama Streamlit web sitesini WebView içinde açar
- İnternet bağlantısı gereklidir
- Ekran açık kalır (battery drain olabilir)
