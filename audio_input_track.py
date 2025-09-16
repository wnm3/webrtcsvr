from aiortc import MediaStreamTrack


class audio_input_track(MediaStreamTrack):
    """
    An audio stream track that converts audio received from the web browser to pass along to the prx_server
    """

    kind = "audio"

    def __init__(self, track):
        super().__init__()
        self.track = track

    async def recv(self):
        """Receives audio from the web browser to be forwarded"""
        stereo_frame = await self.track.recv()
        return stereo_frame
