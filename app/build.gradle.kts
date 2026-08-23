import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("org.jlleitschuh.gradle.ktlint")
}

val releaseBaseUrlProvider =
    providers.gradleProperty("BULLETFEED_RELEASE_BASE_URL")
        .orElse(providers.environmentVariable("BULLETFEED_RELEASE_BASE_URL"))
val configuredReleaseBaseUrl = releaseBaseUrlProvider.orNull ?: "https://invalid.invalid/"

fun quotedBuildConfigString(value: String): String =
    "\"${value.replace("\\", "\\\\").replace("\"", "\\\"")}\""

android {
    namespace = "com.bulletfeed.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.bulletfeed.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    buildTypes {
        getByName("debug") {
            buildConfigField("String", "BASE_URL", quotedBuildConfigString("http://127.0.0.1:8000/"))
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        getByName("release") {
            buildConfigField("String", "BASE_URL", quotedBuildConfigString(configuredReleaseBaseUrl))
            manifestPlaceholders["usesCleartextTraffic"] = "false"
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

val validateReleaseBaseUrl by tasks.registering {
    doLast {
        val value = releaseBaseUrlProvider.orNull
            ?: error("BULLETFEED_RELEASE_BASE_URL is required for release builds")
        val uri = runCatching { URI(value) }.getOrElse {
            error("BULLETFEED_RELEASE_BASE_URL must be a valid absolute HTTPS URL")
        }
        val host = uri.host?.lowercase().orEmpty()
        require(uri.scheme == "https" && host.isNotBlank()) {
            "BULLETFEED_RELEASE_BASE_URL must use HTTPS"
        }
        require(host !in setOf("localhost", "127.0.0.1", "10.0.2.2") && !host.endsWith(".local")) {
            "BULLETFEED_RELEASE_BASE_URL must point to a public HTTPS backend"
        }
        require(value.endsWith("/")) {
            "BULLETFEED_RELEASE_BASE_URL must end with / for Retrofit"
        }
    }
}

tasks.configureEach {
    if (
        name.contains("Release", ignoreCase = false) &&
        (name.startsWith("assemble") || name.startsWith("bundle") || name.startsWith("package"))
    ) {
        dependsOn(validateReleaseBaseUrl)
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.05.01"))
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3:1.4.0")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.jakewharton.retrofit:retrofit2-kotlinx-serialization-converter:1.0.0")
    implementation("sh.calvin.reorderable:reorderable:3.1.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
