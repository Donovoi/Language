package com.example.field_app_flutter

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {
    private var microphone: MicrophoneCheck? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        microphone = MicrophoneCheck(this, flutterEngine.dartExecutor.binaryMessenger)
    }

    override fun onResume() {
        super.onResume()
        microphone?.foreground = true
    }

    override fun onPause() {
        microphone?.suspend()
        super.onPause()
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        microphone?.permissionResult(code)
    }

    override fun onDestroy() {
        microphone?.dispose()
        microphone = null
        super.onDestroy()
    }
}
