// get DOM elements
let dataChannelLog = document.getElementById('data-channel'),
    iceConnectionLog = document.getElementById('ice-connection-state'),
    iceGatheringLog = document.getElementById('ice-gathering-state'),
    signalingLog = document.getElementById('signaling-state');

// peer connection
let pc = null;

// data channel
let dc = null;
let dcInterval = null;

function createPeerConnection() {
    let config = {
        sdpSemantics: 'unified-plan'
    };

    pc = new RTCPeerConnection(config);

    // register some listeners to help debugging
    pc.addEventListener('icegatheringstatechange', () => {
        iceGatheringLog.textContent += ' -> ' + pc.iceGatheringState;
    }, false);
    iceGatheringLog.textContent = pc.iceGatheringState;

    pc.addEventListener('iceconnectionstatechange', () => {
        iceConnectionLog.textContent += ' -> ' + pc.iceConnectionState;
    }, false);
    iceConnectionLog.textContent = pc.iceConnectionState;

    pc.addEventListener('signalingstatechange', () => {
        signalingLog.textContent += ' -> ' + pc.signalingState;
    }, false);
    signalingLog.textContent = pc.signalingState;

    // connect audio
    pc.addEventListener('track', (evt) => {
        if (evt.track.kind == 'playback_audio')
            // push audio for payback to the speakers
            document.getElementById('audio').srcObject = evt.streams[0];
        if (evt.track.kind == 'audio')
            // audio input from the microphone
            document.getElementById('audio').srcObject = evt.streams[0];
    });

    return pc;
}

function enumerateInputDevices() {
    const populateSelect = (select, devices) => {
        let counter = 1;
        devices.forEach((device) => {
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.text = device.label || ('Device #' + counter);
            select.appendChild(option);
            counter += 1;
        });
    };

    navigator.mediaDevices.enumerateDevices().then((devices) => {
        populateSelect(
            document.getElementById('audio-input'),
            devices.filter((device) => device.kind == 'audioinput')
        );
    }).catch((e) => {
        alert(e);
    });
}

function negotiate() {
    return pc.createOffer().then((offer) => {
        // debug
        console.log("Offer:")
        console.log(offer)
        return pc.setLocalDescription(offer);
    }).then(() => {
        // wait for ICE gathering to complete
        return new Promise((resolve) => {
            if (pc.iceGatheringState === 'complete') {
                resolve();
            } else {
                function checkState() {
                    if (pc.iceGatheringState === 'complete') {
                        pc.removeEventListener('icegatheringstatechange', checkState);
                        resolve();
                    }
                }
                pc.addEventListener('icegatheringstatechange', checkState);
            }
        });
    }).then(() => {
        let offer = pc.localDescription;
        let codec;

        codec = document.getElementById('audio-codec').value;
        if (codec !== 'default') {
            offer.sdp = sdpFilterCodec('audio', codec, offer.sdp);
        }

        document.getElementById('offer-sdp').textContent = offer.sdp;
        return fetch('/offer', {
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type
            }),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        });
    }).then((response) => {
        let rspjson = null
        try {
            rspjson = response.json();
        } catch(error) {
            console.log(error)
            console.log(response)
        }
        return rspjson;
    }).then((answer) => {
        document.getElementById('answer-sdp').textContent = answer.sdp;
        return pc.setRemoteDescription(answer);
    }).catch((e) => {
        alert(e);
    });
}

function start() { // NOSONAR
    document.getElementById('start').style.display = 'none';

    pc = createPeerConnection();

    let time_start = null;

    const current_stamp = () => {
        if (time_start === null) {
            time_start = new Date().getTime();
            return 0;
        } else {
            return new Date().getTime() - time_start;
        }
    };

    if (document.getElementById('use-datachannel').checked) {
        let parameters = JSON.parse(document.getElementById('datachannel-parameters').value);

        dc = pc.createDataChannel('chat', parameters);
        dc.addEventListener('close', () => {
            clearInterval(dcInterval);
            dataChannelLog.textContent += '- close\n';
        });
        dc.addEventListener('open', () => {
            dataChannelLog.textContent += '- open\n';
            dcInterval = setInterval(() => {
                let message = 'ping ' + current_stamp();
                dataChannelLog.textContent += '> ' + message + '\n';
                dc.send(message);
            }, 1000);
        });
        dc.addEventListener('message', (evt) => {
            try {
                let msg = JSON.parse(evt.data)
                if (msg.type == "chat") {
                    let message = msg.message;
                    let speaker = msg.speaker;
                    // append this to the chat session
                    document.getElementById('chat-channel').textContent += message;
                    if (speaker == "system") {
                        document.getElementById('chat-channel').textContent += "\n";
                    }
                }

            } catch (error) {
                if (error instanceof SyntaxError) {
                    // not proper json so likely a ping/pong response
                    document.getElementById('data-channel').textContent += '< ' + evt.data + '\n';

                    if (evt.data.substring(0, 4) === 'pong') {
                        let elapsed_ms = current_stamp() - parseInt(evt.data.substring(5), 10);
                        dataChannelLog.textContent += ' RTT ' + elapsed_ms + ' ms\n';
                    }
                }
            }
        });

    }

    // Build media constraints.

    const constraints = {
        audio: false,
        video: false
    };

    if (document.getElementById('use-audio').checked) {
        const audioConstraints = {};

        const device = document.getElementById('audio-input').value;
        if (device) {
            audioConstraints.deviceId = { exact: device };
        }

        constraints.audio = Object.keys(audioConstraints).length ? audioConstraints : true;
    }

    // Acquire media and start negociation.

    if (constraints.audio) {
        navigator.mediaDevices.getUserMedia(constraints).then((stream) => {
            stream.getTracks().forEach((track) => {
                pc.addTrack(track, stream);
            });
            return negotiate();
        }, (err) => {
            alert('Could not acquire media: ' + err);
        });
    } else {
        negotiate();
    }

    document.getElementById('stop').style.display = 'inline-block';
}

function stop() {
    document.getElementById('stop').style.display = 'none';

    // close data channel
    if (dc) {
        dc.close();
    }

    // close transceivers
    if (pc.getTransceivers) {
        pc.getTransceivers().forEach((transceiver) => {
            if (transceiver.stop) {
                transceiver.stop();
            }
        });
    }

    // close local audio / video
    pc.getSenders().forEach((sender) => {
        sender.track.stop();
    });

    // close peer connection
    setTimeout(() => {
        pc.close();
    }, 500);
}

function sdpFilterCodec(kind, codec, realSdp) { // NOSONAR
    let allowed = []
    let rtxRegex = /a=fmtp:(\d+) apt=(\d+)\r$/;
    let codecRegex = new RegExp('a=rtpmap:([0-9]+) ' + escapeRegExp(codec))
    let videoRegex = new RegExp('(m=' + kind + ' .*?)( ([0-9]+))*\\s*$')

    let lines = realSdp.split('\n');

    let isKind = false;
    for (const element of lines) {
        if (element.startsWith('m=' + kind + ' ')) {
            isKind = true;
        } else if (element.startsWith('m=')) {
            isKind = false;
        }

        if (isKind) {
            let match = element.match(codecRegex);
            if (match) {
                allowed.push(parseInt(match[1]));
            }

            match = element.match(rtxRegex);
            if (match && allowed.includes(parseInt(match[2]))) {
                allowed.push(parseInt(match[1]));
            }
        }
    }

    let skipRegex = 'a=(fmtp|rtcp-fb|rtpmap):([0-9]+)';
    let sdp = '';

    isKind = false;
    for (const element of lines) {
        if (element.startsWith('m=' + kind + ' ')) {
            isKind = true;
        } else if (element.startsWith('m=')) {
            isKind = false;
        }

        if (isKind) {
            let skipMatch = element.match(skipRegex);
            if (skipMatch && !allowed.includes(parseInt(skipMatch[2]))) {
                continue;
            } else if (element.match(videoRegex)) {
                sdp += element.replace(videoRegex, '$1 ' + allowed.join(' ')) + '\n';
            } else {
                sdp += element + '\n';
            }
        } else {
            sdp += element + '\n';
        }
    }

    return sdp;
}

function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); // $& means the whole matched string
}

enumerateInputDevices();
start();
