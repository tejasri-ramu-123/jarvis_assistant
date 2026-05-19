# Jarvis Desktop Assistant

A small Python desktop assistant built with Tkinter. It runs with the Python
standard library and stores notes/reminders locally in `jarvis_data.json`.

## Run

```powershell
python jarvis_assistant.py
```

## Example Commands

- `help`
- `open notepad`
- `open calculator`
- `open youtube`
- `search Python tkinter tutorial`
- `youtube relaxing music`
- `note buy printer ink`
- `list notes`
- `clear notes`
- `remind me to drink water in 15 minutes`
- `remind me to call Alex at 6:30 pm`
- `list reminders`
- `system info`
- `tell me a joke`

## Optional Voice Input

Text-to-speech works through `pyttsx3` if installed, or Windows speech support
when available. Microphone input is optional and needs:

```powershell
pip install SpeechRecognition PyAudio
```

The app still works in text mode without those packages.
