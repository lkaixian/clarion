# MediBridge release build shrink/obfuscation rules.
#
# Flutter's own engine + plugin registrant classes are already kept by the
# Flutter Gradle plugin's default rules. The extra keeps below are for the
# specific plugins this app uses, which reflectively construct classes
# (e.g. via method channels) that R8 doesn't see referenced statically.

# dio / OkHttp-style networking internals occasionally rely on reflection
# for platform detection.
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**

# flutter_secure_storage uses Android Keystore / EncryptedSharedPreferences.
-keep class androidx.security.crypto.** { *; }

# Keep Gson-style model fields alive if ever introduced by a future dependency.
-keepattributes Signature
-keepattributes *Annotation*

# flutter_local_notifications serializes scheduled-notification data with
# Gson under the hood (for the boot-rebooting receiver) — without these,
# R8 can strip fields Gson needs reflection to see.
-keep class com.dexterous.** { *; }
-dontwarn com.google.gson.**
-keepattributes EnclosingMethod
-keepattributes InnerClasses
-keep class * extends java.util.TimeZone
-keep class org.threeten.bp.** { *; }

# mobile_scanner (Google ML Kit barcode scanning) — ML Kit models load
# some classes reflectively based on the device's installed modules.
-keep class com.google.mlkit.vision.barcode.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_barcode.** { *; }
-dontwarn com.google.mlkit.**

# nfc_manager's pigeon-generated platform channel classes.
-keep class dev.flutter.plugins.nfcmanager.** { *; }

# permission_handler / url_launcher method-channel plugin classes.
-keep class com.baseflow.permissionhandler.** { *; }
-keep class io.flutter.plugins.urllauncher.** { *; }

# external_app_launcher (MySejahtera launcher) — plain method-channel
# plugin, but keep it explicitly rather than relying on default coverage.
-keep class com.example.launchexternalapp.** { *; }
