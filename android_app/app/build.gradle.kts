
plugins {
    id("com.android.application")
}

val apiBaseUrl = providers.gradleProperty("BIST_BOT_API_BASE_URL")
    .orElse(providers.environmentVariable("BIST_BOT_API_BASE_URL"))
    .orElse("")
    .get()
val escapedApiBaseUrl = apiBaseUrl.replace("\\", "\\\\").replace("\"", "\\\"")

// Operator console base URL (the Flask UI host). Kept separate from the legacy
// API base so the WebView target can change without touching API wiring.
//
// orElse() does not help here: an unset Gradle property resolves to "", which is
// a *value*, so a chained fallback never fires. Filter blanks explicitly and keep
// a last-resort default so a fresh clone always points somewhere real.
val defaultBaseUrl = "https://inputs-streams-glow-hired.trycloudflare.com"
val baseUrlCandidates: List<String?> = listOf(
    providers.gradleProperty("BIST_BOT_BASE_URL").orNull,
    providers.environmentVariable("BIST_BOT_BASE_URL").orNull,
    apiBaseUrl.takeIf { it.isNotBlank() },
    defaultBaseUrl,
)
val baseUrl: String = baseUrlCandidates.firstOrNull { !it.isNullOrBlank() } ?: defaultBaseUrl
val escapedBaseUrl = baseUrl.replace("\\", "\\\\").replace("\"", "\\\"")

android {
    namespace = "com.bistbot.prototype"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.bistbot.prototype"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "API_BASE_URL", "\"$escapedApiBaseUrl\"")
        buildConfigField("String", "BASE_URL", "\"$escapedBaseUrl\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // AGP 9 ships built-in Kotlin support; the standalone plugin is gone.
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }

    buildFeatures {
        buildConfig = true
        viewBinding = true
    }
}

dependencies {
    // Pinned to the last releases that build against compileSdk 34; the 1.19.x /
    // 1.14.x lines require compileSdk 37, which is not installed.
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.9.3")

    // API and JSON
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.code.gson:gson:2.14.0")
}
