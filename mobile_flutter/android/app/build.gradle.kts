import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing (P1.13). `rootProject` here is `android/` (this file lives
// in `android/app/`), so this reads `android/key.properties` -- see
// `android/key.properties.example` for the template + keystore-generation
// command. Deliberately absent from git (repo-root .gitignore); a real
// signing key is a long-lived credential the team must generate and hold
// themselves, not something to fabricate in source control. Its absence is
// NOT a hard build failure -- `flutter build apk --release` still works,
// falling back to Android's public debug key, so local/demo release builds
// keep working without the real credential. That fallback is loud (see
// buildTypes.release below) so a real, distributable release can't be
// shipped by accident.
val keystorePropertiesFile = rootProject.file("key.properties")
val hasKeystoreProperties = keystorePropertiesFile.exists()
val keystoreProperties = Properties()
if (hasKeystoreProperties) {
    FileInputStream(keystorePropertiesFile).use { keystoreProperties.load(it) }
}

android {
    namespace = "com.clarion.mobile_flutter"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        // Required by flutter_local_notifications (it uses java.time APIs
        // that need desugaring to run on minSdk < 26).
        isCoreLibraryDesugaringEnabled = true
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.clarion.mobile_flutter"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 29 // Android 10 and newer only
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasKeystoreProperties) {
            create("release") {
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            if (hasKeystoreProperties) {
                signingConfig = signingConfigs.getByName("release")
            } else {
                // No android/key.properties -- see the block above this
                // `android {}` for why this isn't a hard failure. Loud
                // warning so a `flutter build apk --release` run without the
                // real key can't be mistaken for a distributable build.
                logger.warn(
                    "WARNING: android/key.properties not found -- signing " +
                        "this release build with the DEBUG key. This APK/AAB " +
                        "is for local/demo use only and must NOT be " +
                        "distributed or uploaded to Play Console. See " +
                        "android/key.properties.example.",
                )
                signingConfig = signingConfigs.getByName("debug")
            }

            // Keep the shipped APK small — this matters on the low-end,
            // low-storage Android phones this app's Senior Citizen Mode
            // audience is likely to actually own.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
        debug {
            // Debug builds stay unminified/unshrunk for fast iteration and
            // readable stack traces; this is also the config `flutter build
            // apk --debug` produces, and what this project's README reports
            // an APK size for.
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}

flutter {
    source = "../.."
}
