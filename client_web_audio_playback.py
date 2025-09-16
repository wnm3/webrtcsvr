# generic imports
from asyncio import AbstractEventLoop
from queue import Empty, Queue
from logging import Logger
import time
from threading import Thread, Event
from constants import constants as CONST
from scipy.io import wavfile
from audio_output_track import audio_output_track
from queue_msg import queue_msg
import numpy as np
from numpy import ndarray as NDArray


class client_web_audio_playback:
    """Playback of audio received from the server."""

    @staticmethod
    def float2int(sound: NDArray) -> NDArray:
        """Convert the sound

        Args:
            sound (NDArray): array of float32 sound values

        Returns:
            NDArray: sound as int16 sound values between [-32768,32767]
        """
        return (sound * 32768.0).astype(np.int16)

    def __init__(
        self,
        conv_id: str,
        client_conv_data: dict,
        audio_playback_started_event: Event,
        audio_playback_complete_event: Event,
        config: dict,
        ioloop: AbstractEventLoop,
        logger: Logger,
    ):
        """Constructor for the client_web_audio_playback thread

        Args:
            conv_id (str): conversation identity
            client_conv_data (dict): client conversation data
            audio_playback_started_event (Event): event used to communicate when playback has started
            audio_playback_complete_event (Event): event used to communicate when playback has completed so input can be solicited
            config (dict): configuration parameters for this client
            ioloop (): used for sending async messages to the action queue
            logger (Logger): logger to record status
        """
        self.conv_id = conv_id
        self.client_conv_data = client_conv_data
        self.audio_playback_started_event = audio_playback_started_event
        self.audio_playback_complete_event = audio_playback_complete_event
        self.config = config
        self.ioloop = ioloop
        self.logger = logger
        self.playback_audio_track = None

        # Audio queue for thread-safe communication
        self.audio_playback_queue = Queue()

        # Simulate audio being queued for playback
        sample_rate, input_data = wavfile.read("./playback.wav")
        assert sample_rate == CONST.TTS_AUDIO_SAMPLE_RATE
        while len(input_data) >= CONST.FRAMES_PER_BUFFER:
            audio_float32 = input_data[: CONST.FRAMES_PER_BUFFER]
            input_data = input_data[CONST.FRAMES_PER_BUFFER :]
            audio_stream = bytearray(
                client_web_audio_playback.float2int(
                    np.frombuffer(audio_float32, dtype=np.float32)
                ).tobytes()
            )
            # create a message to add to the array
            msg = queue_msg.make_user_msg(
                {
                    CONST.TYPE: CONST.TYPE_AUDIO_CHUNK,
                    CONST.AUDIO_BYTEARRAY: audio_stream,
                }
            )
            self.audio_playback_queue.put(msg)
        if len(input_data) > 0:
            audio_float32 = input_data[0:]
            input_data = None
            audio_stream = bytearray(
                client_web_audio_playback.float2int(
                    np.frombuffer(audio_float32, dtype=np.float32)
                ).tobytes()
            )
            # create a message to add to the array
            msg = queue_msg.make_user_msg(
                {
                    CONST.TYPE: CONST.TYPE_AUDIO_CHUNK,
                    CONST.AUDIO_BYTEARRAY: audio_stream,
                }
            )
            self.audio_playback_queue.put(msg)
        self.logger.info(
            f"Wav data events posted to queue. Sending {CONST.MSG_ACTION_DATA_FINISHED}"
        )
        msg = queue_msg.make_user_msg(CONST.MSG_ACTION_DATA_FINISHED)
        self.audio_playback_queue.put(msg)

        # Event to signal the playback thread to stop
        self.stop_event = Event()

    def is_playing_back_audio(self) -> bool:
        """Return true if we have begun playing back audio

        Returns:
            bool: True if we have begun playing back audio
        """
        return self.audio_playback_started_event.is_set()

    def run_playback_thread(self, output_index: int):
        """Dedicated thread function for audio playback. Note: not named "run" so we can pass parameters

        Args:
            output_index (int): index of the output device to playback audio
            playback_track (MediaStreamTrack): track to receive the audio to be played back a the web browser
        """
        # Initialize
        self.logger.info("Playback thread started.")
        self.playback_audio_track = self.client_conv_data.get(
            CONST.WEB_RTC_PLAYBACK_AUDIO_TRACK, None
        )
        try:
            while not self.stop_event.is_set() and self.playback_audio_track is None:
                self.logger.info("Waiting for playback_audio_track to be set...")
                self.playback_audio_track = self.client_conv_data.get(
                    CONST.WEB_RTC_PLAYBACK_AUDIO_TRACK, None
                )
                time.sleep(0.5)

            if self.playback_audio_track is not None:
                self.logger.info(
                    f"Stream is active: {self.playback_audio_track.is_active()}"
                )
            # loop while we don't have a stop event
            while not self.stop_event.is_set():
                try:
                    # Wait for an audio chunk without a timeout
                    action_or_audio_chunk_msg = self.audio_playback_queue.get(
                        block=True
                    )  # timeout=0.5)
                    # check if we have a chunk
                    event = action_or_audio_chunk_msg.get_event()

                    event_type = event.get("type", "")
                    if event_type == CONST.TYPE_AUDIO_CHUNK:
                        # the stream is inactivated when it has played all waiting output
                        # since we have new data to play, it should be activated again
                        if (
                            self.playback_audio_track is not None
                            and not self.playback_audio_track.is_active()
                        ):
                            self.playback_audio_track.start_stream()
                            self.logger.info(
                                f"Playback stream reactivated: {self.playback_audio_track.is_active()}"
                            )
                        else:
                            if self.playback_audio_track is None:
                                # we try to start the playback_audio_track
                                self.playback_audio_track = self.client_conv_data.get(
                                    CONST.WEB_RTC_PLAYBACK_AUDIO_TRACK, None
                                )
                                if (
                                    self.playback_audio_track is not None
                                    and not self.playback_audio_track.is_active()
                                ):
                                    self.playback_audio_track.start_stream()
                                    self.logger.info(
                                        f"Playback stream reactivated: {self.playback_audio_track.is_active()}"
                                    )

                        raw_audio_bytearray = event.get(
                            CONST.AUDIO_BYTEARRAY, bytearray()
                        )
                        self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER].extend(
                            raw_audio_bytearray
                        )
                        self.logger.info(
                            f"Accumulating audio chunk len={len(raw_audio_bytearray)} to total {len(self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER])}, {self.audio_playback_queue.unfinished_tasks - 1} remaining chunks."
                        )
                        # Mark the queue task as done
                        self.audio_playback_queue.task_done()
                        continue

                    # else we have a action
                    if event_type == CONST.ACTION:
                        action = event.get(CONST.ACTION, "")
                        if action == CONST.ACTION_SIGNAL_SHUTDOWN_THREAD:
                            try:
                                self.audio_playback_queue.task_done()
                            except ValueError:
                                # will occur if processed all queued content but
                                # while loop broken with the stop_event being set
                                pass
                            self.logger.info("Exit requested via shutdown message")
                            time.sleep(20)  # allow time for playback to be heard
                            print(
                                "Finished playing back. Press Ctrl+C a few times to exit."
                            )

                            break
                        if action == CONST.ACTION_DATA_FINISHED:
                            self.logger.info("Received data finished signal.")
                            self.logger.info("Waiting for output to finish playing")

                            # use a busy wait for playback to complete
                            counter = 0
                            while (
                                counter < 100
                                and len(
                                    self.client_conv_data.get(
                                        CONST.PLAYBACK_AUDIO_BUFFER, bytearray()
                                    )
                                )
                                > 0
                            ):
                                counter += 1
                                time.sleep(0.5)
                            self.logger.info(
                                f"Output finished with {len(self.client_conv_data[CONST.PLAYBACK_AUDIO_BUFFER])} bytes left over."
                            )
                            self.audio_playback_complete_event.set()
                            self.audio_playback_started_event.clear()
                            # Mark the queue task as done
                            try:
                                self.audio_playback_queue.task_done()
                            except ValueError:
                                # will occur if processed all queued content but
                                # while loop broken with the stop_event being set
                                pass

                            self.audio_playback_queue.put(
                                queue_msg.make_user_msg(
                                    CONST.MSG_ACTION_SIGNAL_SHUTDOWN_THREAD
                                )
                            )
                            continue
                    # Mark the queue task as done
                    self.audio_playback_queue.task_done()
                    continue
                except Empty:
                    # not called since we don't have a timeout specified for the queue
                    continue
                except TypeError:
                    continue

            # Play any remaining audio when exiting
            self.logger.info(
                f"Exiting due to stop_event being set or data finshed processing. {self.audio_playback_queue.unfinished_tasks}"
            )

        except Exception as e:
            # log the error
            self.logger.error(f"Exception in playback thread: {e}", exc_info=True)
        finally:
            self.audio_playback_complete_event.clear()
            self.audio_playback_started_event.clear()
            if self.playback_audio_track is not None:
                try:
                    # check if the stream is stopped
                    if not self.playback_audio_track.is_stopped():
                        # close the stream
                        self.playback_audio_track.close()

                except Exception as e:
                    # log the error
                    self.logger.warning(f"Error closing stream: {e}")
            else:
                # INFO
                self.logger.info("Stream was not initialized.")
            self.logger.info("Playback thread terminated.")
            # Mark the queue task as done
            try:
                self.audio_playback_queue.task_done()
            except ValueError:
                # will occur if processed all queued content but
                # while loop broken with the stop_event being set
                pass

    def start_web_playback_thread(
        self, output_index: int, playback_audio_track: audio_output_track
    ) -> Thread:
        """Starts the dedicated playback thread.

        Args:
            output_index (int): index of the output device to playback audio
            pc (RTCPeerConnection): peer connection to web browser for audio playback

        Returns:
            threading.Thread: the thread that was started
        """

        self.playback_audio_track = playback_audio_track
        # Clear any previous playback completion event
        self.audio_playback_started_event.clear()
        self.audio_playback_complete_event.clear()
        self.stop_event.clear()
        self.playback_thread = Thread(
            target=self.run_playback_thread,
            args=[output_index],
            daemon=True,
        )
        self.playback_thread.start()
        self.logger.info("Direct audio playback thread started.")
        return self.playback_thread

    def stop_web_playback_thread(self):
        """Signals the playback thread to stop and waits for it to finish.

        Args:
            playback_thread (threading.Thread): the thread to be stopped
            logger (logging.Logger): log status
        """
        self.stop_event.set()
        self.audio_playback_queue.put(
            queue_msg.make_system_msg(CONST.MSG_ACTION_SIGNAL_SHUTDOWN_THREAD)
        )  # Sentinel value to unblock the queue.get()
        self.logger.info("Playback thread successfully stopped.")

    def wait_for_web_playback_finish(self):
        """Blocking call to wait for all audio chunks to be played back."""
        self.logger.info("Waiting for playback to finish.")

        # Wait for the playback completion event
        self.audio_playback_complete_event.wait()
        self.logger.info("Playback finished.")

        # Clear the event for the next use
        self.audio_playback_started_event.clear()
        self.audio_playback_complete_event.clear()
        if (
            self.playback_audio_track is not None
            and self.playback_audio_track.is_active()
        ):
            # stop the stream so it is inactive and will be restarted with the next audio input
            self.playback_audio_track.stop_stream()
