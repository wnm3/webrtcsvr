import asyncio
import fractions
from logging import Logger
from threading import Thread
import time
from aiortc import MediaStreamTrack, RTCPeerConnection
import numpy as np
from av import AudioFifo, AudioFrame
from av.frame import Frame
from constants import constants as CONST
from scipy import signal

DEBUG_FILES = False


class audio_output_track(MediaStreamTrack):
    """
    An audio stream track that converts audio received from a queue to pass along to the web client for playback
    """

    kind = "audio"

    def __init__(
        self,
        config: dict,
        client_conv_data: dict,
        ioloop: asyncio.AbstractEventLoop,
        logger: Logger,
        frames_per_buffer: int = CONST.FRAMES_PER_BUFFER,
        channels: int = CONST.AUDIO_CHANNELS_STEREO,
        rate: int = CONST.WEB_RTC_AUDIO_SAMPLE_RATE,
        output: bool = True,
        start: bool = False,
    ):
        super().__init__()
        self.config = config
        self.client_conv_data = client_conv_data
        self.ioloop = ioloop
        self.logger = logger
        self.frames_per_buffer = frames_per_buffer
        self.channels = channels
        self.rate = rate
        self.output = output
        self.start = start

        self.closed = False
        self.kind = "audio"
        self.pts = 0
        self.started_recording = False
        self.audio_fifo = AudioFifo()
        self.is_playing_back = False

        # spin off a thread to process data and fill the audio_fifo
        self.output_processor_thread = Thread(
            target=self.process_output_data_frames, args=()
        )
        self.output_processor_thread.start()

    @staticmethod
    def create_mono_audio_frame(mono_bytes_24000, sample_width=2):
        # build a mono frame
        mono_frame = AudioFrame(
            format="s16", layout="mono", samples=int(len(mono_bytes_24000) / 2)
        )
        mono_frame.sample_rate = CONST.TTS_AUDIO_SAMPLE_RATE
        mono_frame.planes[0].update(mono_bytes_24000)
        return mono_frame

    @staticmethod
    def resample_to_stereo(mono_audio_frame: np.ndarray) -> np.ndarray:
        """
        Resamples a mono 24000 Hz audio frame to a stereo frame.

        Args:
            mono_audio_frame (np.ndarray): The input mono audio data,
                                        expected to be a 1D NumPy array.

        Returns:
            np.ndarray: The resampled stereo audio data as a 1D NumPy array
                        with interleaved stereo data.
        """
        # Upsample the mono audio from 24000 to 48000
        mono_audio_frame_48_float = signal.resample(
            np.resize(mono_audio_frame, (1, mono_audio_frame.size)), 2
        )
        mono_audio_frame_48 = (
            np.array(mono_audio_frame_48_float).astype(np.int16).T.ravel()
        )
        # Convert the mono signal to stereo by duplicating the channel
        # The output will be a 2D array
        stereo_audio_frame_2D = np.array([mono_audio_frame_48, mono_audio_frame_48])
        # make this interleaved stereo in a single array
        stereo_audio_frame = stereo_audio_frame_2D.T.ravel()

        return stereo_audio_frame

    def add_track(self, pc: RTCPeerConnection):
        if pc:
            pc.addTrack(self)

    def process_output_data_frames(self):
        # wait for the connection to be ready
        # need to use asyncio to await this being set
        if not self.ioloop.is_closed():
            self.logger.info("Waiting for the client connection.")
            asyncio.run_coroutine_threadsafe(
                self.client_conv_data[CONST.CLIENT_WEB_RTC_CONNECTED].wait(),
                self.ioloop,
            )
        else:
            self.logger.info("ioloop is closed. Can't gather data")
            return

        self.logger.info("Beginning to process data frames.")
        # read from data buffer, create frames and push them to the fifo
        counter = 0
        self.pts = 0
        while not self.is_stopped():
            counter += 1
            audio_bytes = self.playback_audio_track_callback(self.frames_per_buffer * 2)
            if audio_bytes is not None:
                self.started_recording = True
                self.logger.info(
                    f"Got {len(audio_bytes)} to send to browser. {len(self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER])}"
                )
                if DEBUG_FILES:
                    self.rawaudio_24.write(audio_bytes)

                mono_frame = audio_output_track.create_mono_audio_frame(audio_bytes)
                mono_audio = mono_frame.to_ndarray()[0]

                if DEBUG_FILES:
                    mono_bytes = mono_audio.tobytes()
                    self.monoframe_24.write(mono_bytes)

                # resample to stereo frame
                stereo_audio = audio_output_track.resample_to_stereo(mono_audio)
                stereo_frame = AudioFrame(
                    format="s16",
                    layout="stereo",
                    samples=int(stereo_audio.size / 2),
                )
                stereo_frame.planes[0].update(stereo_audio[0:].tobytes())
                stereo_frames = [stereo_frame]
                if stereo_frames:
                    for frame in stereo_frames:
                        frame.sample_rate = (
                            # CONST.TTS_AUDIO_SAMPLE_RATE
                            CONST.WEB_RTC_AUDIO_SAMPLE_RATE
                        )
                        frame.pts = self.pts
                        self.pts += frame.samples
                        frame.time_base = fractions.Fraction(1, frame.sample_rate)
                        self.logger.info(
                            f"Writing to fifo pts={frame.pts} time={frame.time} duration={frame.duration} time_base={frame.time_base} size={frame.samples} remaining={len(self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER])}"
                        )
                        if DEBUG_FILES:
                            stereo_audio = frame.to_ndarray()[0]
                            stereo_bytes = stereo_audio.tobytes()
                            self.stereoframe_48.write(stereo_bytes)
                        self.audio_fifo.write(frame)
                        frame.sample_rate = (
                            # CONST.TTS_AUDIO_SAMPLE_RATE
                            CONST.WEB_RTC_AUDIO_SAMPLE_RATE
                        )
            else:
                time.sleep(0.5)
                if (counter % 100) == 0:
                    self.logger.info("Waiting for data to process")
                    counter = 0

        self.logger.info("Ending processing data thread.")

    def close(self):
        self.start = False
        self.closed = True
        self.stop()

    def is_active(self) -> bool:
        return self.start

    def is_stopped(self) -> bool:
        return self.closed

    def playback_audio_track_callback(
        self, frame_count: int = CONST.FRAMES_PER_BUFFER
    ) -> bytes | None:
        # read any accumulated audio and return it
        buf_len = len(self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER])

        if buf_len >= frame_count:
            data = self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER].extract(
                frame_count
            )
            self.logger.info(
                f"Playback callback returning {len(data)} bytes, {len(self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER])} remaining"
            )
            return bytes(data)

        else:
            return None

    def get_silence_frame(self) -> AudioFrame:
        silent_audio_data = np.zeros((1, self.frames_per_buffer), dtype=np.int16)

        frame = AudioFrame.from_ndarray(
            silent_audio_data,
            format="s16",
            layout="stereo",
        )
        # Set the sample rate of the frame
        frame.sample_rate = (
            # CONST.TTS_AUDIO_SAMPLE_RATE
            CONST.WEB_RTC_AUDIO_SAMPLE_RATE
        )
        frame.pts = self.pts
        self.pts += frame.samples  # self.frames_per_buffer
        return frame

    async def recv(self) -> AudioFrame | Frame:
        """Like a callback from the server to receive audio for playback, this method returns a frame of audio retrieved from the queue or silence."""
        if self.is_stopped():
            try:
                return self.get_silence_frame()
            except Exception:
                # we are shutting down
                self.close()

        # wait until we have started
        while not self.is_active():
            await asyncio.sleep(0.1)
        # read a frame from the fifo and return it to be sent to the browser, blocking until there is data
        frame = None
        while (
            self.is_active()
        ):  # TODO: add a test on the connection to ensure we are still communicating
            frame = self.audio_fifo.read(samples=self.frames_per_buffer)
            if frame is not None:
                if not self.is_playing_back:
                    print("Beginning to play back audio.")
                    self.is_playing_back = True

                frame.sample_rate = (
                    # CONST.TTS_AUDIO_SAMPLE_RATE
                    CONST.WEB_RTC_AUDIO_SAMPLE_RATE
                )
                if DEBUG_FILES:
                    audio_array = frame.to_ndarray()[0]
                    audio_bytes = audio_array.tobytes()
                    self.sendframe_48.write(audio_bytes)

                ftime = frame.time if frame.time is not None and frame.time > 0 else 0
                self.logger.info(
                    f"Sending frame pts={frame.pts} duration={frame.duration} time={ftime} size={frame.samples} rate={frame.rate} sample_rate={frame.sample_rate}"
                )

                break
        if frame is not None:
            # await asyncio.sleep(0.02)
            # for more dynamic based on data sent:
            await asyncio.sleep(
                frame.samples
                # / CONST.TTS_AUDIO_SAMPLE_RATE
                / CONST.WEB_RTC_AUDIO_SAMPLE_RATE
            )
            return frame
        else:
            await asyncio.sleep(0.02)
            frame = self.get_silence_frame()
            ftime = frame.time if frame.time is not None and frame.time > 0 else 0
            self.logger.info(
                f"Sending silence frame pts={frame.pts} duration={frame.duration} time={ftime} size={frame.samples} rate={frame.rate} sample_rate={frame.sample_rate}"
            )
            return frame

    def start_stream(self):
        now = time.time()
        self.started_recording = False
        if DEBUG_FILES:
            self.rawaudio_24 = open(f"./tmp_01_rawaudio_24_{now}", "wb")
            self.monoframe_24 = open(f"./tmp_02_monoframe_24_{now}", "wb")
            self.stereoframe_48 = open(f"./tmp_03_stereoframe_48_{now}", "wb")
            self.sendframe_48 = open(f"./tmp_04_sendframe_48_{now}", "wb")
        self.start = True
        self.logger.info("Done starting stream")

    def stop_stream(self):
        self.start = False
        if DEBUG_FILES:
            if self.rawaudio_24:
                self.rawaudio_24.flush()
                self.rawaudio_24.close()

            if self.sendframe_48:
                self.sendframe_48.flush()
                self.sendframe_48.close()

            if self.monoframe_24:
                self.monoframe_24.flush()
                self.monoframe_24.close()

            if self.stereoframe_48:
                self.stereoframe_48.flush()
                self.stereoframe_48.close()

        self.logger.info("Done stopping stream")
