import boto3
import os
import logging
import sys
from datetime import datetime

###
'''
# List all available aws polly voices and generate mp3 file for the selected voice.
# //SHAL 2023
###
'''

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def list_voices(selected_languages=None):
    """Retrieve a list of available voices from AWS Polly, excluding neural voices."""
    try:
        session = boto3.Session(profile_name='default')
        polly = session.client('polly')
        response = polly.describe_voices()
        voices = response['Voices']

        # Filter by language if provided
        # Polly languages are region dependent
        if selected_languages:
            voices = [v for v in voices if v['LanguageCode'] in selected_languages]

        # EXCLUDE voices that support neural engine
        voices = [v for v in voices if 'neural' not in v.get('SupportedEngines', [])]

        return voices
    except Exception as e:
        logging.error(f"Error fetching voices: {e}")
        return []


def synthesize_speech(ssml_text, voice_id, voice_name, output_format='mp3'):
    """Synthesize speech using a specified voice and save it to a timestamped file."""
    try:
        session = boto3.Session(profile_name='default')
        polly = session.client('polly')

        response = polly.synthesize_speech(
            Engine='standard',  # switched from neural to standard
            Text=ssml_text,
            VoiceId=voice_id,
            OutputFormat=output_format,
            TextType='ssml'
        )

        if 'AudioStream' in response:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            audio_file = f"{timestamp}_{voice_name}.mp3"

            with open(audio_file, 'wb') as file:
                file.write(response['AudioStream'].read())

            logging.info(f"Audio saved as {audio_file}")
        else:
            logging.warning("No audio stream returned.")

    except Exception as e:
        logging.error(f"Error synthesizing speech with voice {voice_id}: {e}")


def choose_voice(voices):
    """Prompt user to select a voice from the list."""
    print("\nAvailable voices:\n")

    for idx, voice in enumerate(voices, start=1):
        print(f"{idx}. {voice['Name']} ({voice['Id']}, {voice['LanguageName']})")

    while True:
        try:
            choice = int(input("\nSelect a voice by number: "))
            if 1 <= choice <= len(voices):
                return voices[choice - 1]
            else:
                print("Invalid selection. Try again.")
        except ValueError:
            print("Please enter a valid number.")


def main():
    ssml_text = "<speak>This is a demo notification. You can reach us at 1-800-123. Please press 1 to hear the notification.</speak>"

    selected_languages = sys.argv[1:] if len(sys.argv) > 1 else None
    voices = list_voices(selected_languages)

    if not voices:
        logging.info("No suitable (non-neural) voices available.")
        return

    selected_voice = choose_voice(voices)

    logging.info(f"Selected voice: {selected_voice['Id']}")

    synthesize_speech(
        ssml_text,
        selected_voice['Id'],
        selected_voice['Name']
    )


if __name__ == "__main__":
    main()
    
    
 # ToDo
# - Add customization for text 
# - Add language filter
# ########################
# - references
# https://docs.aws.amazon.com/boto3/latest/
# https://docs.python.org/3/library/logging.html
#