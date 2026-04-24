
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val apiBaseUrl = providers.gradleProperty("BIST_BOT_API_BASE_URL")
    .orElse(providers.environmentVariable("BIST_BOT_API_BASE_URL"))
    .orElse("")
    .get()
val escapedApiBaseUrl = apiBaseUrl.replace("\\", "\\\\").replace("\"", "\\\"")

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

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.9.2")
    
    // API and JSON
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.code.gson:gson:2.10.1")
}
