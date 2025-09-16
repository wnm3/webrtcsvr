import sys
import aiofiles
import asyncio
import json
import logging
import os
from pathlib import Path
import queue
import ssl
import threading
import traceback
import uuid
from aiohttp import web
from aiortc import RTCPeerConnection, RTCRtpReceiver, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

from audio_input_track import audio_input_track
from audio_output_track import audio_output_track
from client_web_audio_playback import client_web_audio_playback
from shared_bytearray import shared_bytearray
from constants import constants as CONST


_INFO = False  # True to print tracebacks


class webrtcsvr:
    """Program to interact with a webrtc client"""

    def __init__(self):
        """Constructor for the webrtcsvr. Initialization occurs during the get_params call in main."""
        self.exit = False
        self.conv_data = {}
        self.logger = webrtcsvr.set_logger(__name__)
        self.prx_config = {}
        self.response_done_event = asyncio.Event()
        self.response_start_event = asyncio.Event()
        self.listen_end_event = asyncio.Event()
        self.output_index = 1
        self.pc = None
        self.ROOT = os.path.dirname(__file__)

    @staticmethod
    def set_logger(name: str) -> logging.Logger:
        """Configure a logger to report output to log file using the supplied name and a sequence suffix if one already exists

        Args:
            name (str): the base name of the log file

        Returns:
            logging.Logger: the logger for logging status
        """
        # configure logger

        configdir = Path(__file__).parent

        loglevel = "info"
        loglevel = logging.getLevelNamesMapping().get(loglevel.upper(), logging.INFO)
        logname = "webrtcsvr"
        logdir = f"{configdir}{os.sep}logs"
        logfilename = logdir + os.sep + logname + ".log"
        # delete the old log if it exists
        if os.path.exists(logfilename):
            os.remove(logfilename)

        _logger = logging.getLogger(logfilename)
        logging.basicConfig(
            filename=logfilename,
            encoding="utf-8",
            format="%(levelname)s %(asctime)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s",
            level=loglevel,
            force=True,
        )  # level=logging.INFO)
        print(f"\nLogging to {logfilename} with {_logger}\n")

        return _logger

    async def client_input_handler(self):
        """Solicit input from the client via webrtc"""
        try:
            self.conv_id = "conv_" + uuid.uuid4().hex
            self.initialize_conv_data(self.conv_id)

            # for comms with webrtcsvr_tts_audio_playback_thread
            self.prx_config[CONST.AUDIO_MESSAGE_QUEUE] = queue.Queue()

            # Event to signal that playback of the current response has started
            self.audio_playback_started_event = threading.Event()
            # Event to signal that playback of the current response is complete
            self.audio_playback_complete_event = threading.Event()

            # start up client_web_audio_playback
            self.client_web_audio_playback = client_web_audio_playback(
                self.conv_id,
                self.conv_data[self.conv_id],
                self.audio_playback_started_event,
                self.audio_playback_complete_event,
                self.prx_config,
                asyncio.get_event_loop(),
                self.logger,
            )
            self.web_audio_playback_thread = self.client_web_audio_playback.start_web_playback_thread(
                self.output_index, self.conv_data[self.conv_id].get(CONST.WEB_RTC_PLAYBACK_AUDIO_TRACK)  # type: ignore self.output_index is set in get_params
            )
            self.logger.info(
                f"Client web audio playback thread started: {self.web_audio_playback_thread.is_alive()}"
            )

            # semaphore to know we are connected
            self.conv_data[self.conv_id][
                CONST.CLIENT_WEB_RTC_CONNECTED
            ] = asyncio.Event()
            self.conv_data[self.conv_id][CONST.CLIENT_WEB_RTC_CONNECTED].clear()

            tasks = []
            async with asyncio.TaskGroup() as tg:  # NOSONAR
                web_svr_task = tg.create_task(
                    self.start_webrtc_server("localhost", 8910, tasks)
                )
                tasks.append(web_svr_task)

                # wait until the client connects
                self.logger.info("Waiting for the client connection.")
                await self.conv_data[self.conv_id][
                    CONST.CLIENT_WEB_RTC_CONNECTED
                ].wait()

        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt")
            print(CONST.TEXT_SHUTTING_DOWN)
            if _INFO:
                traceback.print_exc()
            self.exit = True
        except ExceptionGroup as egrp:
            self.logger.error(f"ExceptionGroup error occurred: {egrp}", exc_info=True)
        except asyncio.CancelledError:  # NOSONAR
            self.logger.info("CancelledError")
        except Exception as e:
            # Handle any unexpected errors
            self.exit = True
            self.logger.error(f"An error occurred: {e}", exc_info=True)
        finally:
            # shutdown the audio playback
            if hasattr(self, "client_web_audio_playback") and hasattr(
                self, "playback_thread"
            ):
                self.client_web_audio_playback.stop_web_playback_thread()

    def initialize_conv_data(self, conv_id: str) -> dict:
        """Creates/resets conversation data depending on whether a conv_id is supplied. If no conv_id is specified, an empty conv_data
        object is added to self (overwriting what is there if one exists). If a conv_id is supplied, a new object for the conv_data[conv_id] is
        created, overwriting any prior data.

        Args:
            conv_id (str | None): the conversation identifier whose conversation data is to be created/reset. If None, then all
            conversations are removed and an empty object is stored in self.conv_data.
        """
        # add expected fields to ensure they are present
        ret_obj = {}
        if conv_id:
            if not hasattr(self, "conv_data"):
                self.conv_data = {}
            ret_obj = self.conv_data.get(conv_id, {})
            self.conv_data[conv_id] = {}
            # ensure we have accumulators for output audio data used for aec
            self.conv_data[conv_id][CONST.PLAYBACK_AUDIO_BUFFER] = shared_bytearray()
        return ret_obj

    async def on_shutdown(self, app_svr):
        # close peer connections
        if self.pc is not None:
            await self.pc.close()

    async def index(self, _request):
        async with aiofiles.open(
            os.path.join(self.ROOT, "index.html"), mode="r"
        ) as handle:
            content = await handle.read()
            return web.Response(content_type="text/html", text=content)

    async def javascript(self, _request):
        async with aiofiles.open(
            os.path.join(self.ROOT, "webclient.js"), mode="r"
        ) as handle:
            content = await handle.read()
            return web.Response(content_type="application/javascript", text=content)

    async def offer(self, request) -> web.Response:
        try:

            params = await request.json()
            offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

            pc = RTCPeerConnection()

            # there is no audio/pcm16 code but if there was...
            capabilities = RTCRtpReceiver.getCapabilities("audio")
            if capabilities is not None:
                pcm_codecs = []
                audio_codecs = capabilities.codecs
                for codec in audio_codecs:
                    if codec.mimeType == "audio/pcm16":
                        pcm_codecs.append(codec)

                audio_transceivers = pc.getTransceivers()
                if audio_transceivers:
                    audio_transceiver = audio_transceivers[
                        0
                    ]  # Adjust index based on your setup
                    if hasattr(audio_transceiver, "setCodecPreferences") and pcm_codecs:
                        audio_transceiver.setCodecPreferences(pcm_codecs)

            pc_id = "PeerConnection(%s)" % uuid.uuid4()
            self.pc = pc
            self.logger.info(f"{pc_id} Created for {request.remote}")

            @pc.on("datachannel")
            def on_datachannel(channel):

                self.conv_data[self.conv_id]["chat_data_channel"] = channel
                self.logger.info("Connected the datachannel")

                @channel.on("message")
                def on_message(message):
                    if isinstance(message, str) and message.startswith("ping"):
                        channel.send("pong" + message[4:])
                    else:
                        print(f"Chat message: {message}")

                @channel.on("open")
                async def on_chat_open(event):
                    self.logger.info("Chat data channel is open")
                    msg = {
                        "type": "chat",
                        "speaker": "system",
                        "message": "Please say something to initiate the conversation:\n",
                    }
                    self.conv_data[self.conv_id]["chat_data_channel"].send(
                        json.dumps(msg)
                    )

                @channel.on("close")
                async def on_chat_close():
                    self.logger.info("Chat data channel is closed")

                @channel.on("error")
                async def on_chat_error(error):
                    self.logger.error(f"Chat data channel error: {error}")

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                self.logger.info(f"{pc_id} Connection state is {pc.connectionState}")
                if pc.connectionState == "connected":
                    self.logger.info("Offer is complete. We are connected.")
                    self.conv_data[self.conv_id][CONST.CLIENT_WEB_RTC_CONNECTED].set()
                elif pc.connectionState == "failed":
                    await pc.close()
                    self.pc = None

            @pc.on("track")
            def on_track(track):
                try:
                    self.logger.info(f"{pc_id} Track {track.kind} received")

                    if track.kind == "audio":

                        # open the track to playback output
                        output_track = audio_output_track(
                            self.prx_config,
                            self.conv_data[self.conv_id],
                            asyncio.get_event_loop(),
                            self.logger,
                            frames_per_buffer=CONST.OPUS_FRAMES_PER_BUFFER,
                            channels=CONST.AUDIO_CHANNELS_STEREO,
                            rate=CONST.WEB_RTC_AUDIO_SAMPLE_RATE,
                            output=True,
                            start=False,
                        )
                        self.conv_data[self.conv_id][
                            CONST.WEB_RTC_PLAYBACK_AUDIO_TRACK
                        ] = output_track
                        pc.addTrack(
                            self.conv_data[self.conv_id][
                                CONST.WEB_RTC_PLAYBACK_AUDIO_TRACK
                            ]
                        )

                        self.logger.info(
                            f"{pc_id} prx_audio_output_track opened but not started."
                        )

                        relay = MediaRelay()

                        # create the track to react to audio input
                        self.conv_data[self.conv_id][CONST.WEB_RTC_MIC_INPUT_STREAM] = (
                            audio_input_track(relay.subscribe(track))
                        )

                    @track.on("ended")
                    async def on_ended():
                        self.logger.info(f"{pc_id} Track {track.kind} ended")

                except Exception:
                    traceback.print_exc()

            # handle offer
            await pc.setRemoteDescription(offer)

            # send answer
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            self.logger.info(
                f"{pc_id} Returning sdp with type: {pc.localDescription.type}"
            )
            rsptext = json.dumps(
                {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
            )
            # print(rsptext)
            response = web.Response(
                content_type="application/json",
                text=rsptext,
            )
            return response
        except Exception as e:
            traceback.print_exc()
            raise e

    async def start_webrtc_server(self, host: str, port: int, tasks):
        """Listens for webrtc connections from a browers that it starts and establishes a peer connection
        to receive audio from the browser, and send audio for playback

        Args:
            tasks (list): the list of tasks being managed
        """
        runner = None
        try:
            cert_file = "client.crt"
            key_file = "client.key"
            if cert_file:
                ssl_context = ssl.SSLContext(  # NOSONAR S4830 SSL Verification
                    ssl.PROTOCOL_TLS_CLIENT
                )
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE  # NOSONAR
                try:
                    ssl_context.load_cert_chain(cert_file, key_file)
                except Exception:
                    ssl_context = None
            else:
                ssl_context = None

            self.app_svr = web.Application()
            self.app_svr.on_shutdown.append(
                self.on_shutdown
            )  # add clean up when shutdown
            self.app_svr.router.add_get("/", self.index)
            self.app_svr.router.add_get("/webclient.js", self.javascript)
            self.app_svr.router.add_post("/offer", self.offer)
            runner = web.AppRunner(self.app_svr)
            await runner.setup()
            site = web.TCPSite(runner, host=host, port=port)

            await site.start()
            self.logger.info(f"Web Server started on host {host} port {port}")
            print(
                "Please open a browser to http://localhost:8910 (or refresh the page if open) to begin the test."
            )
            # # if desired, uncomment below to start a browser session
            # import webbrowser
            # webbrowser.open_new_tab("http://localhost:8910")

            # Keep the server running until cancelled
            await asyncio.Future()
            self.logger.info("Web Server has ended")
        except KeyboardInterrupt:
            self.exit = True
            print(CONST.TEXT_SHUTTING_DOWN)
        except asyncio.CancelledError:  # NOSONAR
            if _INFO:
                traceback.print_exc()
            self.logger.info("web server task was cancelled.")
        except Exception as e:
            traceback.print_exc()
            self.exit = True
            self.logger.error(f"Error while sending message: {e}", exc_info=True)
        finally:
            if runner:
                await runner.cleanup()
            print("aiohttp server shut down.")
            for task in tasks:
                if task == asyncio.current_task():
                    # close others first
                    continue
                if task.done():
                    # already closed
                    continue
                task.cancel()
            self.logger.info(f"web server task for {self.conv_id} closed.")
            self.exit = True

    def clean_shutdown(self):
        """Ensure a clean shutdown of playback thread and WebSocket connection."""
        self.logger.info("clean_shutdown requested")
        # tts done at server
        if hasattr(self, "client_web_audio_playback"):
            self.client_web_audio_playback.stop_web_playback_thread()

        self.logger.info("All audio playback has been processed.")
        self.logger.info("Audio playback finished.")

    async def do_work(self):
        """The main processing loop"""
        try:
            while not self.exit:
                # process client requests
                await self.client_input_handler()
                self.logger.info(f"self.exit={self.exit}")
                if not self.exit:
                    # reinitialize client data and try again
                    self.conv_data = {}
            self.clean_shutdown()
        except (
            KeyboardInterrupt
        ):  # may need signal handlers if running in the background
            print(CONST.TEXT_SHUTTING_DOWN)
            self.logger.info(CONST.TEXT_SHUTTING_DOWN)
        except Exception as e:
            # Handle any unexpected errors
            self.logger.error(f"An error occurred: {e}", exc_info=True)

    @staticmethod
    async def main(pgm: "webrtcsvr", args: list):
        """The main routine of the webrtcsvr that processes command line arguments, and runs the do_work method

        Args:
            pgm (webrtcsvr): _description_
            args (list): _description_
        """
        try:
            await pgm.do_work()
        except KeyboardInterrupt:
            print(CONST.TEXT_SHUTTING_DOWN)
            # may need signal handlers if running in the background
            pgm.logger.info("Client requested to stop.")
        except ExceptionGroup:
            # die gracefully
            pass
        except Exception as e:
            # Handle any unexpected errors
            if _INFO:
                traceback.print_exc()
            pgm.logger.error(f"An error occurred: {e}", exc_info=True)


if __name__ == "__main__":
    """The main entry point for running the webrtcsvr"""
    pgm = webrtcsvr()
    try:
        asyncio.run(pgm.main(pgm, sys.argv))
    except KeyboardInterrupt:
        if _INFO:
            traceback.print_exc()
    except Exception:
        if _INFO:
            traceback.print_exc()
    finally:
        print(CONST.TEXT_SHUTTING_DOWN)
        exit()
