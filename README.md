## Background ##  

The code is "simplified" from a more complex system that provides streaming audio to 
LLMs using OpenAI's API. I've tried to reduce it to a bare minimum while attempting 
to replicate most of the flows used for generating audio playback to a web browser 
client using WebRTC as its communication.  

The program writes log messages to a ./logs/webrtcsvr.log file.  

The program uses an artificial sleep of 20 seconds to give the playback time to be heard in the browser.  

You'll need to press Ctrl+C when directed to cancel the program and disconnect the browser's session.  

## Problem ##  
The playback in the browser is choppy, but recognizable. I suspect it is the timing of 
frames being sent. However, I am not sure the stereo composition is correct, as the 
playback seems to have an echo effect. ***I need help reviewing the 
transformations from the mono audio bytes read from the wav file into interleaved 
stereo bytes, and the approach used with the AudioFifo to retrieve content to return 
in the MediaStreamTrack-based track's recv call***.  

I have added four data capture points, writing bytes to files at each stage of 
transformation:  

1. The bytes read from the wav file (tmp_01_rawaudio_24_\<timestamp\>)
2. The mono AudioFrame converted to bytes (tmp_02_monoframe_24_\<timestamp\>)
3. The stereo AudioFrame of interleaved mono data converted to bytes (tmp_03_stereoframe_48_\<timestamp\>) -- this seems to be at double the 24000 sample rate (48000)
4. The AudioFrame being sent is converted to bytes (tmp_04_sendframe_48_\< timestamp\>) also at 48000 sample rate  

There is a utility program named `convert_bytes_to_wav.py` that takes the timestamp as 
input and changes the byte files to wav files (it contains an array of the expected 
sample rates for each file, so no timestamp needs to be entered). Use the command:  

```console
ls -ltr
```


to find the last set of tmp_* files to copy their timestamp (following the last underscore (_)) to paste 
into the program when prompted. No need to enter a sample rate (just press enter).  

```
...
drwxr-xr-x  4 wnm3  staff      128 Sep 16 10:57 logs
-rw-r--r--  1 wnm3  staff   856320 Sep 16 10:58 tmp_01_rawaudio_24_1758034679.906118
-rw-r--r--  1 wnm3  staff   856320 Sep 16 10:58 tmp_02_monoframe_24_1758034679.906118
-rw-r--r--  1 wnm3  staff  1712640 Sep 16 10:58 tmp_03_stereoframe_48_1758034679.906118
-rw-r--r--  1 wnm3  staff  1712640 Sep 16 10:58 tmp_04_sendframe_48_1758034679.906118
webrtcsvr>python convert_bytes_to_wav.py 
Enter the timestamp or q to quit: 
1758034679.906118
Enter sample rate (e.g., 24000, nothing uses defaults for file types), or q to quit

Saved wav file as tmp_01_rawaudio_24_1758034679.906118.wav
Saved wav file as tmp_02_monoframe_24_1758034679.906118.wav
Saved wav file as tmp_03_stereoframe_48_1758034679.906118.wav
Saved wav file as tmp_04_sendframe_48_1758034679.906118.wav
webrtcsvr>
```

## Experience the Problem ##

By running the command: `python webrtcsvr.py`, you start the server. 

Next, open the URL `http://localhost:8910` in a WebRTC-enabled browser (I've been using the 
latest version of Chrome). This forms a connection to the webrtcsvr and playback should 
begin soon. The webrtc_output_audio.wav was created by using the `chrome:webrtc-internals` 
/ Create diagnostic audio recordings / Enable diagnostic audio recordings checkbox. It 
shows the choppy-sounding output.  

You need to press Ctrl+C several times to kill the webrtcsvr program and then run 
`python convert_bytes_to_wav.py` using the timestamp of the tmp_* files produced 
in order to generate wav files from their captured bytes.

There is a resetlogs.sh that will remove the log files from the ./logs directory and 
the tmp_* files produced.

## Program Execution Flow ##

The example here is based on a more complex system that originally used pyaudio for 
capturing input and playing back output. I'd tried to emulate this design using a 
callback for the audio to be played back.  

Running the webrtcsvr creates an asynchronous task for an asynchronous web server that 
serves a slightly modified page based on the 
[aiortc/examples/server code.](https://github.com/aiortc/aiortc/tree/main/examples/server) 
code (and index.html page loading webclient.js).  

The call sequence is main -> do_work -> client_input_handler which then does the 
following:  

A `client_web_audio_playback` object is created to handle loading up wav data to be played 
back. It reads content from the playback.wav file and sends events with 1024 byte chunks 
of audio data through a queue, then sends a "data_finished" action event to signify no 
more data will be sent.  This class contains thread code (`run_playback_thread` method) 
that starts to read events or actions from the queue and populates a shared_bytearray 
with the raw data. This is later read to create AudioFrames in the 
`audio_output_track.py's`  thread method `process_output_data_frames`.  

The raw audio bytes are written to the tmp_01_rawaudio_24_\<timestamp\> file.  When the 
action "data_finished" event is received, it loops to wait until the shared_bytearray 
has finished being read by the playback, then sends an event stating that the playback is 
complete. It also clears an event for playback that has started. It posts an action to 
cause the thread to shut down.

Independently, an asynchronous task is spawned for the web server that catches the 
WebRTC connection from the browser. It negotiates the addition of the output Track 
from the `audio_output_track.py` object, and once connected, enables the recv method to pull 
data from the AudioFifo and send it back to the browser for playback.  

## In Closing ##

I do not have experience with WebRTC and likely am missing a basic concept causing the inconsistent feedback. I hope 
someone with more experience can easily spot the problem and provide guidance.  

The code is more complicated than a simple mainline program because I wanted to emulate the various asynchronous 
aspects of the actual code. However, the problem either occurs in the audio_output_track.py's recv() method, or the 
code feeding the AudioFifo in audio_output_track.py's process_output_data_frames() method.  

