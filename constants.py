class constants:
    ACTION = "action"
    ACTION_DATA_FINISHED = "data_finished"
    ACTION_SIGNAL_EXIT = "signal_exit"
    ACTION_SIGNAL_SHUTDOWN_THREAD = "shutdown_thread"
    AUDIO_BYTEARRAY = "audio_bytearray"
    AUDIO_CHANNELS_STEREO = 2
    AUDIO_MESSAGE_QUEUE = "audio_message_queue"
    EVENT = "event"
    FRAMES_PER_BUFFER = 1024
    MSG_ACTION_DATA_FINISHED = {"type": "action", "action": ACTION_DATA_FINISHED}
    MSG_ACTION_SIGNAL_SHUTDOWN_THREAD = {
        "type": "action",
        "action": ACTION_SIGNAL_SHUTDOWN_THREAD,
    }
    MSG_ACTION_SIGNAL_EXIT = {"type": "action", "action": ACTION_SIGNAL_EXIT}
    OPUS_FRAMES_PER_BUFFER = 960
    OUTPUT_AUDIO_BUFFER = "output_audio_buffer"
    PLAYBACK_AUDIO_BUFFER = "playback_audio_buffer"
    PRIORITY_CLASS = "priority_class"
    SEQ = "seq"
    TTS_MAX_BUFFER_SIZE = 2000
    TYPE = "type"
    TYPE_AUDIO_CHUNK = "audio.chunk"
    WEB_RTC_PLAYBACK_AUDIO_TRACK = "playback_audio_track"
    CLIENT_WEB_RTC_CONNECTED = "client_web_rtc_connected"
    TEXT_SHUTTING_DOWN = "shutting down"
    TTS_AUDIO_SAMPLE_RATE = 24000
    WEB_RTC_AUDIO_SAMPLE_RATE = 48000
