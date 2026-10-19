package com.clarion.mobile_flutter

import android.content.Intent
import android.nfc.NdefMessage
import android.nfc.NdefRecord
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

// local_auth (biometric / device PIN prompt) needs a FragmentActivity.
class MainActivity : FlutterFragmentActivity() {
    private var pendingTag: Map<String, String?>? = null
    private var channel: MethodChannel? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        // Blocks screenshots and screen recording of the whole app and blanks
        // its thumbnail in the recents list -- every screen shows PHI.
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        super.onCreate(savedInstanceState)
        pendingTag = tagFromIntent(intent)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "clarion/launch_tag").also {
            // Dart pulls the tag that launched us once it is ready; a tap while
            // the app is already running is pushed via onNewIntent below.
            it.setMethodCallHandler { call, result ->
                if (call.method == "take") {
                    result.success(pendingTag)
                    pendingTag = null
                } else {
                    result.notImplemented()
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        tagFromIntent(intent)?.let {
            pendingTag = it
            channel?.invokeMethod("tag", it)
        }
    }

    /** UID + the on-tag Text record from an NFC-dispatch intent, or null. */
    private fun tagFromIntent(intent: Intent?): Map<String, String?>? {
        if (intent?.action != NfcAdapter.ACTION_NDEF_DISCOVERED) return null
        val tag: Tag? = if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(NfcAdapter.EXTRA_TAG, Tag::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(NfcAdapter.EXTRA_TAG)
        }
        val uid = tag?.id?.joinToString("") { "%02X".format(it) }
        var text: String? = null
        @Suppress("DEPRECATION")
        val raw = intent.getParcelableArrayExtra(NfcAdapter.EXTRA_NDEF_MESSAGES)
        for (m in raw.orEmpty()) {
            for (r in (m as NdefMessage).records) {
                if (r.tnf == NdefRecord.TNF_WELL_KNOWN && r.type.contentEquals(NdefRecord.RTD_TEXT) && r.payload.isNotEmpty()) {
                    val lang = r.payload[0].toInt() and 0x3F
                    if (r.payload.size >= 1 + lang) {
                        text = String(r.payload, 1 + lang, r.payload.size - 1 - lang, Charsets.UTF_8)
                    }
                }
            }
        }
        // Consume the action so a config change / relaunch doesn't replay it.
        intent.action = Intent.ACTION_MAIN
        return if (uid == null) null else mapOf("uid" to uid, "text" to text)
    }
}
