package com.example.field_app_flutter

import android.Manifest
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Bounded foreground diagnostic. No file storage, networking, or automatic playback. */
class MicrophoneCheck(private val activity: Activity, messenger: BinaryMessenger) {
    companion object {
        const val SAMPLE_RATE = 16000
        private const val PERMISSION_REQUEST = 9401
    }

    var foreground = false
    private val channel = MethodChannel(messenger, "language/microphone_check")
    private val main = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()
    private val audio = activity.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val attributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
    private var clip: ShortArray? = null
    private var operation: AtomicBoolean? = null
    private var permissionReply: MethodChannel.Result? = null
    private val clearReplies = mutableListOf<MethodChannel.Result>()
    private var focusRequest: AudioFocusRequest? = null
    private var hasFocus = false
    private val focusListener = AudioManager.OnAudioFocusChangeListener { change ->
        if (change != AudioManager.AUDIOFOCUS_GAIN) operation?.set(true)
    }
    private val noisyReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) operation?.set(true)
        }
    }

    init {
        channel.setMethodCallHandler(::handle)
        val filter = IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY)
        if (Build.VERSION.SDK_INT >= 33) {
            activity.registerReceiver(noisyReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            activity.registerReceiver(noisyReceiver, filter)
        }
    }

    private fun permitted() = activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
        PackageManager.PERMISSION_GRANTED

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "permissionStatus" -> result.success(permitted())
            "requestPermission" -> {
                if (permissionReply != null) result.error("busy", "Permission request already open.", null)
                else if (!foreground) result.error("background", "Open the app to enable the microphone.", null)
                else if (permitted()) result.success(true)
                else {
                    permissionReply = result
                    activity.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), PERMISSION_REQUEST)
                }
            }
            "clear" -> {
                discard()
                if (operation == null) result.success(null) else clearReplies.add(result)
            }
            "capture", "play" -> {
                if (!foreground) result.error("background", "Keep the microphone check open.", null)
                else if (operation != null) result.error("busy", "An audio check is already running.", null)
                else if (call.method == "capture") {
                    val duration = call.argument<Int>("durationMs") ?: 3000
                    if (duration !in 1000..5000) {
                        result.error("duration", "Capture must be between one and five seconds.", null)
                    } else if (!permitted()) {
                        result.error("permission", "Enable microphone permission, then record again.", null)
                    } else {
                        discard()
                        launch(result, true) { cancel -> capture(duration, cancel) }
                    }
                } else {
                    val samples = clip
                    if (samples == null) result.error("empty", "Record a new clip first.", null)
                    else if (!acquireFocus()) result.error("focus", "Audio output is busy. Try again.", null)
                    else launch(result, false) { cancel -> play(samples, cancel) }
                }
            }
            else -> result.notImplemented()
        }
    }

    fun permissionResult(code: Int) {
        if (code == PERMISSION_REQUEST) {
            permissionReply?.success(permitted())
            permissionReply = null
        }
    }

    private data class AudioResult(val values: Map<String, Any?>, val samples: ShortArray? = null)

    private fun launch(result: MethodChannel.Result, recording: Boolean,
                       work: (AtomicBoolean) -> AudioResult) {
        val cancel = AtomicBoolean(false)
        operation = cancel
        executor.execute {
            var output: AudioResult? = null
            var failure: Exception? = null
            try { output = work(cancel) } catch (error: Exception) { failure = error }
            main.post {
                // Only this worker owns the operation until all native resources are released.
                operation = null
                releaseFocus()
                if (cancel.get() || !foreground) {
                    clip?.fill(0)
                    clip = null
                    output?.samples?.fill(0)
                    result.error("cancelled", "Audio check stopped and clip discarded.", null)
                } else if (failure != null) {
                    result.error("audio", failure.message ?: "Audio device unavailable.", null)
                } else {
                    if (recording) clip = output!!.samples
                    result.success(output!!.values)
                }
                clearReplies.forEach { it.success(null) }
                clearReplies.clear()
            }
        }
    }

    private fun capture(durationMs: Int, cancel: AtomicBoolean): AudioResult {
        val minimum = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT)
        check(minimum > 0) { "This microphone does not support 16 kHz mono PCM." }
        val recorder = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, 6400))
        val samples = ShortArray(SAMPLE_RATE * durationMs / 1000)
        var completed = false
        try {
            check(recorder.state == AudioRecord.STATE_INITIALIZED) { "Microphone could not initialize." }
            if (cancel.get()) throw IllegalStateException("Capture cancelled.")
            recorder.startRecording()
            check(recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) { "Microphone did not start." }
            val started = SystemClock.elapsedRealtime()
            val deadline = started + durationMs + 2000
            var frames = 0
            var silenced = false
            while (frames < samples.size && !cancel.get()) {
                check(SystemClock.elapsedRealtime() < deadline) { "Microphone timed out before delivering a complete clip." }
                val read = recorder.read(samples, frames, minOf(1600, samples.size - frames),
                    AudioRecord.READ_NON_BLOCKING)
                check(read >= 0) { "Microphone read failed ($read). Try recording again." }
                frames += read
                if (Build.VERSION.SDK_INT >= 29) {
                    silenced = silenced || recorder.activeRecordingConfiguration?.isClientSilenced == true
                }
                if (read == 0) Thread.sleep(10)
            }
            if (cancel.get()) throw IllegalStateException("Capture cancelled.")
            val route = recorder.routedDevice
            val bytes = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
            bytes.asShortBuffer().put(samples)
            completed = true
            return AudioResult(mapOf("pcm" to bytes.array(), "sampleRate" to SAMPLE_RATE,
                "frames" to frames, "elapsedMs" to (SystemClock.elapsedRealtime() - started),
                "source" to "VOICE_RECOGNITION", "inputType" to route?.type,
                "inputName" to route?.productName?.toString(), "silenced" to silenced), samples)
        } finally {
            try {
                if (recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) recorder.stop()
            } finally {
                recorder.release()
                if (!completed) samples.fill(0)
            }
        }
    }

    private fun play(samples: ShortArray, cancel: AtomicBoolean): AudioResult {
        val track = AudioTrack.Builder().setAudioAttributes(attributes)
            .setAudioFormat(AudioFormat.Builder().setSampleRate(SAMPLE_RATE)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
            .setTransferMode(AudioTrack.MODE_STATIC).setBufferSizeInBytes(samples.size * 2).build()
        try {
            check(track.state != AudioTrack.STATE_UNINITIALIZED) { "Audio output could not initialize." }
            if (cancel.get()) throw IllegalStateException("Playback cancelled.")
            check(track.write(samples, 0, samples.size) == samples.size) { "Audio output rejected the clip." }
            track.play()
            val deadline = SystemClock.elapsedRealtime() + samples.size * 1000L / SAMPLE_RATE + 2000
            var route = track.routedDevice
            while (track.playbackHeadPosition < samples.size && !cancel.get()) {
                check(SystemClock.elapsedRealtime() < deadline) { "Audio output timed out." }
                route = track.routedDevice ?: route
                Thread.sleep(10)
            }
            if (cancel.get()) throw IllegalStateException("Playback cancelled.")
            return AudioResult(mapOf("playedFrames" to track.playbackHeadPosition,
                "outputType" to route?.type, "outputName" to route?.productName?.toString()))
        } finally {
            try { if (track.playState == AudioTrack.PLAYSTATE_PLAYING) track.pause() }
            finally { track.release() }
        }
    }

    @Suppress("DEPRECATION")
    private fun acquireFocus(): Boolean {
        val status = if (Build.VERSION.SDK_INT >= 26) {
            val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(attributes).setWillPauseWhenDucked(true)
                .setOnAudioFocusChangeListener(focusListener, main).build()
            focusRequest = request
            audio.requestAudioFocus(request)
        } else audio.requestAudioFocus(focusListener, AudioManager.STREAM_MUSIC,
            AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
        hasFocus = status == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
        if (!hasFocus) focusRequest = null
        return hasFocus
    }

    @Suppress("DEPRECATION")
    private fun releaseFocus() {
        if (hasFocus) {
            if (Build.VERSION.SDK_INT >= 26) focusRequest?.let { audio.abandonAudioFocusRequest(it) }
            else audio.abandonAudioFocus(focusListener)
        }
        hasFocus = false
        focusRequest = null
    }

    private fun discard() {
        operation?.set(true)
        // The worker may still be reading the playback buffer; its lifetime is bounded
        // and clear replies wait until release. Do not mutate that buffer concurrently.
        if (operation == null) clip?.fill(0)
        clip = null
    }

    fun suspend() {
        foreground = false
        discard()
    }

    fun dispose() {
        suspend()
        permissionReply?.error("cancelled", "Microphone check closed.", null)
        permissionReply = null
        channel.setMethodCallHandler(null)
        activity.unregisterReceiver(noisyReceiver)
        executor.shutdown()
    }
}
