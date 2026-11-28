"""Opt-in OpenAI file transcription with source-relative window timestamps."""
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, build_opener
from uuid import uuid4

from clipflow.auth import NoRedirect
from clipflow.render import LOCAL_PROTOCOLS, Cue, probe, run

WINDOW_SECONDS = 6
MODEL = 'gpt-transcribe'
API_URL = 'https://api.openai.com/v1/audio/transcriptions'
# Quota estimate reserves a full minute per window at the published USD rate.
MICRO_USD_PER_WINDOW = 4500
SPEECH_MODELS = {'en': 'vosk-model-small-en-us-0.15', 'ru': 'vosk-model-small-ru-0.22'}


class TranscriptionUnavailable(ValueError):
    pass


def monthly_budget():
    if os.environ.get('CLIPFLOW_PAID_WORKLOADS_ENABLED') != 'true':
        return 0
    return max(0, int(os.environ.get('CLIPFLOW_TRANSCRIPTION_MONTHLY_MICRO_USD', '0')))


def enabled():
    return monthly_budget() > 0 or CloudSpeech.available()


class CloudSpeech:
    @staticmethod
    def model_root():
        return Path(os.environ.get('CLIPFLOW_SPEECH_MODEL_DIR', '/opt/clipflow-speech'))

    @classmethod
    def available(cls):
        return all((cls.model_root() / name / 'am' / 'final.mdl').is_file()
                   for name in SPEECH_MODELS.values())

    def captions(self, queue, job, source, start, end):
        language = json.loads(job['spec']).get('caption_language', 'en')
        model = self.model_root() / SPEECH_MODELS[language]
        with TemporaryDirectory(prefix='caption-', dir=source.parent) as directory:
            audio = Path(directory) / 'audio.wav'
            try:
                run('ffmpeg', '-nostdin', '-v', 'error', *LOCAL_PROTOCOLS,
                    '-ss', str(start), '-i', str(source), '-t', str(end - start),
                    '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
                    str(audio), timeout=30)
                words = json.loads(run(sys.executable, '-m', 'clipflow.speech_cli',
                                       str(model), str(audio), timeout=150))
            except (subprocess.SubprocessError, OSError, ValueError) as error:
                raise TranscriptionUnavailable('Could not transcribe this audio. Check that it contains clear speech.') from error
        cues = []
        group = []
        for word in words:
            if group and (len(group) == 7 or word['end'] - group[0]['start'] > 3.5
                          or word['start'] - group[-1]['end'] > 0.8):
                cues.append(self.cue(group, start, end, sentence=word['start'] - group[-1]['end'] > 0.55))
                group = []
            if start + word['start'] < end:
                group.append(word)
        if group:
            cues.append(self.cue(group, start, end, sentence=True))
        return cues

    @staticmethod
    def cue(words, offset, end, sentence):
        return Cue(offset + words[0]['start'], min(end, offset + words[-1]['end']),
                   ' '.join(word['word'] for word in words) + ('.' if sentence else ''))


class Transcriber:
    def __init__(self, key, budget, opener=None):
        self.key = key
        self.budget = budget
        self.opener = opener or build_opener(NoRedirect)

    @classmethod
    def configured(cls):
        budget = monthly_budget()
        key = os.environ.get('OPENAI_API_KEY', '')
        if not key or budget <= 0:
            return None
        return cls(key, budget)

    def request(self, audio):
        boundary = uuid4().hex
        prefix = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{MODEL}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            'Content-Type: audio/wav\r\n\r\n'
        ).encode()
        request = Request(API_URL, data=prefix + audio + f'\r\n--{boundary}--\r\n'.encode(),
                          headers={'Authorization': 'Bearer ' + self.key,
                                   'Content-Type': 'multipart/form-data; boundary=' + boundary})
        try:
            with self.opener.open(request, timeout=7) as response:
                result = json.loads(response.read(128 * 1024))
            text = result['text']
            if not isinstance(text, str):
                raise ValueError('Expected transcript text')
            return ' '.join(text.split())
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise TranscriptionUnavailable('Transcription was interrupted. No automatic paid retry was made.') from error

    def captions(self, queue, job, source, start, end):
        stored = queue.cached_captions(job['id'])
        if stored is not None:
            return [Cue(**item) for item in stored]
        metadata = probe(source)
        if not any(stream['codec_type'] == 'audio' for stream in metadata['streams']):
            raise TranscriptionUnavailable('Automatic captions require source audio.')
        if end > float(metadata['format']['duration']):
            raise TranscriptionUnavailable('The selected range goes beyond the source.')
        windows = math.ceil((end - start) / WINDOW_SECONDS)
        cues = []
        if not queue.reserve_transcription(job, windows * MICRO_USD_PER_WINDOW, self.budget):
            raise TranscriptionUnavailable('Caption budget exhausted or a previous request may have been charged.')
        with TemporaryDirectory(prefix='caption-', dir=source.parent) as directory:
            audio = Path(directory) / 'audio.wav'
            for index in range(windows):
                left = start + index * WINDOW_SECONDS
                right = min(end, left + WINDOW_SECONDS)
                run('ffmpeg', '-nostdin', '-v', 'error', '-y', *LOCAL_PROTOCOLS,
                    '-ss', str(left), '-i', str(source), '-t', str(right - left),
                    '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
                    str(audio), timeout=12)
                text = self.request(audio.read_bytes())
                if text:
                    cues.append(Cue(left, right, text[:160]))
        if not cues:
            raise TranscriptionUnavailable('No transcribable speech was found in the selected range.')
        queue.save_captions(job, cues)
        return cues
